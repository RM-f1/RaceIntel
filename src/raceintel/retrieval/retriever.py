import re
from dataclasses import dataclass, field

from raceintel.retrieval.chroma_client import ChromaClient
from raceintel.routing.entity_registry import EntityRegistry, normalize_text

SEMANTIC_DISTANCE_THRESHOLD = 0.55
MAX_CONTEXT_CHUNKS = 5
MAX_CONTEXT_CHARS = 6000
NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.92


@dataclass
class RetrievalResult:
    """
    Structured retrieval output containing filtered documents, metadata,
    distances, source attribution, conflict flags, and failure status.
    """

    documents: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    metadatas: list[dict] = field(default_factory=list)
    distances: list[float] = field(default_factory=list)
    status: str = "empty"
    context: str = ""
    raw_context: str = ""
    sources: list[dict] = field(default_factory=list)
    conflict_detected: bool = False
    conflict_details: list[str] = field(default_factory=list)
    error_message: str | None = None


class Retriever:
    """
    Retrieves relevant F1 documents from ChromaDB.

    Deterministic retrieval is used whenever the question contains
    enough information to identify the required race, driver, or team.
    """

    RACES = {
        "bahrain": "Bahrain Grand Prix",
        "saudi": "Saudi Arabian Grand Prix",
        "saudi arabia": "Saudi Arabian Grand Prix",
        "australia": "Australian Grand Prix",
        "australian": "Australian Grand Prix",
        "japan": "Japanese Grand Prix",
        "japanese": "Japanese Grand Prix",
        "china": "Chinese Grand Prix",
        "chinese": "Chinese Grand Prix",
        "miami": "Miami Grand Prix",
        "emilia": "Emilia Romagna Grand Prix",
        "imola": "Emilia Romagna Grand Prix",
        "monaco": "Monaco Grand Prix",
        "canada": "Canadian Grand Prix",
        "canadian": "Canadian Grand Prix",
        "spain": "Spanish Grand Prix",
        "spanish": "Spanish Grand Prix",
        "austria": "Austrian Grand Prix",
        "austrian": "Austrian Grand Prix",
        "britain": "British Grand Prix",
        "british": "British Grand Prix",
        "hungary": "Hungarian Grand Prix",
        "hungarian": "Hungarian Grand Prix",
        "belgium": "Belgian Grand Prix",
        "belgian": "Belgian Grand Prix",
        "netherlands": "Dutch Grand Prix",
        "dutch": "Dutch Grand Prix",
        "italy": "Italian Grand Prix",
        "italian": "Italian Grand Prix",
        "azerbaijan": "Azerbaijan Grand Prix",
        "singapore": "Singapore Grand Prix",
        "usa": "United States Grand Prix",
        "united states": "United States Grand Prix",
        "austin": "United States Grand Prix",
        "cota": "United States Grand Prix",
        "circuit of the americas": "United States Grand Prix",
        "spa": "Belgian Grand Prix",
        "spa-francorchamps": "Belgian Grand Prix",
        "spa francorchamps": "Belgian Grand Prix",
        "circuit de spa-francorchamps": "Belgian Grand Prix",
        "silverstone": "British Grand Prix",
        "monza": "Italian Grand Prix",
        "interlagos": "São Paulo Grand Prix",
        "suzuka": "Japanese Grand Prix",
        "zandvoort": "Dutch Grand Prix",
        "albert park": "Australian Grand Prix",
        "red bull ring": "Austrian Grand Prix",
        "hungaroring": "Hungarian Grand Prix",
        "mexico": "Mexico City Grand Prix",
        "mexican": "Mexico City Grand Prix",
        "brazil": "São Paulo Grand Prix",
        "sao paulo": "São Paulo Grand Prix",
        "são paulo": "São Paulo Grand Prix",
        "las vegas": "Las Vegas Grand Prix",
        "qatar": "Qatar Grand Prix",
        "abu dhabi": "Abu Dhabi Grand Prix",
    }

    DRIVERS = {
        "max verstappen": "Max Verstappen",
        "verstappen": "Max Verstappen",
        "max": "Max Verstappen",

        "sergio perez": "Sergio Perez",
        "perez": "Sergio Perez",
        "checo": "Sergio Perez",

        "charles leclerc": "Charles Leclerc",
        "leclerc": "Charles Leclerc",

        "carlos sainz": "Carlos Sainz",
        "sainz": "Carlos Sainz",

        "lewis hamilton": "Lewis Hamilton",
        "hamilton": "Lewis Hamilton",

        "george russell": "George Russell",
        "russell": "George Russell",

        "lando norris": "Lando Norris",
        "norris": "Lando Norris",

        "oscar piastri": "Oscar Piastri",
        "piastri": "Oscar Piastri",

        "fernando alonso": "Fernando Alonso",
        "alonso": "Fernando Alonso",

        "lance stroll": "Lance Stroll",
        "stroll": "Lance Stroll",

        "pierre gasly": "Pierre Gasly",
        "gasly": "Pierre Gasly",

        "esteban ocon": "Esteban Ocon",
        "ocon": "Esteban Ocon",

        "yuki tsunoda": "Yuki Tsunoda",
        "tsunoda": "Yuki Tsunoda",

        "daniel ricciardo": "Daniel Ricciardo",
        "ricciardo": "Daniel Ricciardo",

        "alex albon": "Alex Albon",
        "albon": "Alex Albon",

        "logan sargeant": "Logan Sargeant",
        "sargeant": "Logan Sargeant",

        "nico hulkenberg": "Nico Hulkenberg",
        "hulkenberg": "Nico Hulkenberg",

        "kevin magnussen": "Kevin Magnussen",
        "magnussen": "Kevin Magnussen",
        "kevin": "Kevin Magnussen",

        "valtteri bottas": "Valtteri Bottas",
        "bottas": "Valtteri Bottas",

        "zhou guanyu": "Zhou Guanyu",
        "zhou": "Zhou Guanyu",
    }

    TEAMS = {
        "red bull racing": "Red Bull Racing",
        "red bull": "Red Bull Racing",

        "ferrari": "Ferrari",
        "mercedes": "Mercedes",
        "mclaren": "McLaren",
        "aston martin": "Aston Martin",
        "alpine": "Alpine",
        "haas": "Haas",
        "williams": "Williams",

        "visa cash app rb": "RB",
        "rb": "RB",

        "kick sauber": "Kick Sauber",
        "sauber": "Kick Sauber",
    }

    DRIVER_KEYWORDS = {
        "driver",
        "finish",
        "finished",
        "position",
        "points",
        "constructor",
        "team",
        "performed",
        "performance",
        "grid",
    }

    def __init__(
        self,
        registry: EntityRegistry | None = None,
        distance_threshold: float = SEMANTIC_DISTANCE_THRESHOLD,
        max_context_chunks: int = MAX_CONTEXT_CHUNKS,
        max_context_chars: int = MAX_CONTEXT_CHARS,
    ):
        self.client = ChromaClient()
        if registry is not None:
            self.registry = registry
        else:
            self.registry = EntityRegistry()
        self.distance_threshold = distance_threshold
        self.max_context_chunks = max_context_chunks
        self.max_context_chars = max_context_chars
        self.RACES = self.registry.get_races_map()
        self.DRIVERS = self.registry.get_drivers_map()
        self.TEAMS = self.registry.get_teams_map()

    # ============================================================
    # FILTER EXTRACTION
    # ============================================================

    def _extract_filters(self, question: str) -> dict:
        """
        Extract race, driver, team and season information safely.

        Uses word-boundary matching across all entity maps, resolves events in
        priority order consistent with EntityRegistry, masks matched event
        spans before driver/team lookup (preventing e.g. Spa-Francorchamps ->
        Franco Colapinto), and guards 3-letter timing codes that collide with
        common English words.
        """

        q = question.lower().strip()
        q_norm = normalize_text(question)

        filters: dict = {}

        # --------------------------------------------------------
        # Season
        # --------------------------------------------------------

        season_match = re.search(r"\b(19\d{2}|20\d{2})\b", q)
        if season_match:
            filters["season"] = int(season_match.group(1))

        # --------------------------------------------------------
        # Race (Priority-aware resolution + strict word boundaries)
        # --------------------------------------------------------

        matched_race_kw: str | None = None
        target_season = filters.get("season")

        # 1. Try EntityRegistry staged resolver first when question names a race/circuit
        registry = getattr(self, "registry", None)
        if registry is not None and hasattr(registry, "resolve_event"):
            # Scan longest normalized phrases present in registry RACES using word boundaries
            candidate_kws = [
                kw for kw in sorted(self.RACES.keys(), key=len, reverse=True)
                if kw and re.search(rf"\b{re.escape(kw)}\b", q_norm)
            ]
            if candidate_kws:
                # Prefer explicit event names / aliases / circuits over bare ambiguous country tokens
                for kw in candidate_kws:
                    res = registry.resolve_event(kw, season=target_season)
                    if res.matched:
                        filters["race_name"] = res.event_name
                        matched_race_kw = kw
                        break
                if "race_name" not in filters:
                    for kw in candidate_kws:
                        canon = self.RACES.get(kw)
                        if canon:
                            filters["race_name"] = canon
                            matched_race_kw = kw
                            break
        else:
            for keyword in sorted(self.RACES.keys(), key=len, reverse=True):
                if re.search(rf"\b{re.escape(keyword)}\b", q_norm):
                    filters["race_name"] = self.RACES[keyword]
                    matched_race_kw = keyword
                    break

        # Mask matched event tokens so circuit/location substrings never collide with driver/team names
        q_entity_norm = q_norm
        q_entity_raw = question
        if matched_race_kw:
            q_entity_norm = re.sub(rf"\b{re.escape(matched_race_kw)}\b", " ", q_entity_norm)
            q_entity_raw = re.sub(rf"\b{re.escape(matched_race_kw)}\b", " ", q_entity_raw, flags=re.IGNORECASE)

        # --------------------------------------------------------
        # Driver (Word-boundary matching + 3-letter timing code guard)
        # --------------------------------------------------------

        ambiguous_short_codes = {"nor", "per", "law", "gas", "bot", "str", "had"}
        for keyword in sorted(self.DRIVERS.keys(), key=len, reverse=True):
            if len(keyword) < 3:
                continue
            if keyword in ambiguous_short_codes:
                matched = bool(re.search(rf"\b{re.escape(keyword.upper())}\b", q_entity_raw))
            else:
                matched = bool(re.search(rf"\b{re.escape(keyword)}\b", q_entity_norm))
            if matched:
                filters["driver"] = self.DRIVERS[keyword]
                break

        # --------------------------------------------------------
        # Team (Word-boundary matching)
        # --------------------------------------------------------

        for keyword in sorted(self.TEAMS.keys(), key=len, reverse=True):
            if not keyword:
                continue
            if re.search(rf"\b{re.escape(keyword)}\b", q_entity_norm):
                filters["team"] = self.TEAMS[keyword]
                break

        # --------------------------------------------------------
        # Document type & Session type (Sprint vs Race)
        # --------------------------------------------------------

        is_sprint = bool(re.search(r"\bsprint\b", q))
        if is_sprint:
            filters["session_type"] = "Sprint"
            if "team" in filters or "driver" in filters:
                filters["document_type"] = "driver_sprint_report"
            elif any(
                re.search(rf"\b{re.escape(keyword)}\b", q_entity_norm)
                for keyword in self.DRIVER_KEYWORDS
            ):
                filters["document_type"] = "driver_sprint_report"
            else:
                filters["document_type"] = "sprint_report"
        else:
            if "team" in filters or "driver" in filters:
                filters["document_type"] = "driver_report"
            elif any(
                re.search(rf"\b{re.escape(keyword)}\b", q_entity_norm)
                for keyword in self.DRIVER_KEYWORDS
            ):
                filters["document_type"] = "driver_report"
            else:
                filters["document_type"] = "race_report"

        return filters

    # ============================================================
    # CHROMA WHERE BUILDER
    # ============================================================

    def _build_where(self, filters: dict) -> dict:
        """
        Convert metadata filters into a ChromaDB where clause.
        """

        if not filters:
            return {}

        if len(filters) == 1:
            return filters

        return {
            "$and": [
                {key: value}
                for key, value in filters.items()
            ]
        }

    # ============================================================
    # DEDUPLICATION & NEAR-DUPLICATE HELPERS
    # ============================================================

    @staticmethod
    def _canonical_text(text: str) -> str:
        """
        Canonicalize document text for duplicate detection.
        Normalizes intra-line whitespace and eliminates duplicate empty lines.
        """
        if not text:
            return ""
        lines = [
            re.sub(r"[ \t]+", " ", line).strip()
            for line in text.strip().splitlines()
        ]
        cleaned_lines = []
        for line in lines:
            if line or (cleaned_lines and cleaned_lines[-1]):
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip().lower()

    @staticmethod
    def _strip_chunk_wrappers(text: str) -> str:
        """Strip synthetic chunk/source prefixes before near-duplicate comparison."""
        cleaned = re.sub(r"^\s*\[(?:source|chunk)[^\]]*\]\s*", "", text or "", flags=re.IGNORECASE | re.MULTILINE)
        return re.sub(r"\s+", " ", cleaned).strip().lower()

    @staticmethod
    def _metadata_compatible_for_dedup(meta_a: dict | None, meta_b: dict | None) -> bool:
        """
        Return False when two chunks explicitly belong to distinct entities, events,
        seasons, or document types so genuinely distinct documents are never merged.
        """
        ma = meta_a or {}
        mb = meta_b or {}
        for key in ("season", "race_name", "driver", "team", "document_type"):
            va = ma.get(key)
            vb = mb.get(key)
            if va is not None and vb is not None and str(va).strip().lower() != str(vb).strip().lower():
                return False
        return True

    def _is_near_duplicate(
        self,
        candidate_text: str,
        candidate_meta: dict | None,
        kept_token_sets: list[tuple[set[str], dict | None]],
    ) -> bool:
        """
        Detect high-overlap near-duplicate chunks (>= NEAR_DUPLICATE_JACCARD_THRESHOLD)
        that differ only by minor formatting, headers, or wrapper text.
        """
        stripped = self._strip_chunk_wrappers(candidate_text)
        cand_tokens = set(re.findall(r"[a-z0-9]+", stripped))
        if len(cand_tokens) < 12:
            return False

        for prev_tokens, prev_meta in kept_token_sets:
            if not self._metadata_compatible_for_dedup(candidate_meta, prev_meta):
                continue
            union = cand_tokens | prev_tokens
            if not union:
                continue
            similarity = len(cand_tokens & prev_tokens) / len(union)
            if similarity >= NEAR_DUPLICATE_JACCARD_THRESHOLD:
                return True
        return False

    def _deduplicate_documents(
        self,
        documents: list[str] | None,
        ids: list[str] | None = None,
        metadatas: list[dict] | None = None,
        distances: list[float] | None = None,
        suppress_near_duplicates: bool = True,
    ) -> tuple[list[str], list[str], list[dict]]:
        """
        Deduplicates retrieved documents based on:
        1. Unique document ID
        2. Canonical document text content
        3. Optional high-overlap near-duplicate detection (respecting metadata boundaries)

        Preserves insertion order, metadata attribution, and genuinely
        distinct documents (e.g. different seasons or race events).
        """
        deduped_docs, deduped_ids, deduped_metas, _ = self._deduplicate_with_distances(
            documents=documents,
            ids=ids,
            metadatas=metadatas,
            distances=distances,
            suppress_near_duplicates=suppress_near_duplicates,
        )
        return deduped_docs, deduped_ids, deduped_metas

    def _deduplicate_with_distances(
        self,
        documents: list[str] | None,
        ids: list[str] | None = None,
        metadatas: list[dict] | None = None,
        distances: list[float] | None = None,
        suppress_near_duplicates: bool = True,
    ) -> tuple[list[str], list[str], list[dict], list[float]]:
        """Deduplicate documents while keeping IDs, metadatas, and distances aligned."""
        if not documents:
            return [], [], [], []

        seen_ids = set()
        seen_canonical_texts = set()
        kept_token_sets: list[tuple[set[str], dict | None]] = []

        deduped_docs = []
        deduped_ids = []
        deduped_metas = []
        deduped_dists = []

        num_docs = len(documents)
        resolved_ids = (
            ids
            if ids is not None and len(ids) == num_docs
            else [f"doc_{i}" for i in range(num_docs)]
        )
        resolved_metadatas = (
            metadatas
            if metadatas is not None and len(metadatas) == num_docs
            else [{} for _ in range(num_docs)]
        )
        resolved_distances = (
            distances
            if distances is not None and len(distances) == num_docs
            else [0.0 for _ in range(num_docs)]
        )

        for doc_id, doc_text, meta, dist in zip(
            resolved_ids, documents, resolved_metadatas, resolved_distances
        ):
            if not doc_text or not str(doc_text).strip():
                continue

            # 1. Check ID uniqueness
            if doc_id and doc_id in seen_ids:
                continue

            # 2. Check canonical text uniqueness
            canonical = self._canonical_text(doc_text)
            if canonical and canonical in seen_canonical_texts:
                continue

            # 3. Check near-duplicate overlap
            if suppress_near_duplicates and self._is_near_duplicate(
                doc_text, meta, kept_token_sets
            ):
                continue

            if doc_id:
                seen_ids.add(doc_id)
            if canonical:
                seen_canonical_texts.add(canonical)
            cand_tokens = set(re.findall(r"[a-z0-9]+", self._strip_chunk_wrappers(doc_text)))
            if len(cand_tokens) >= 12:
                kept_token_sets.append((cand_tokens, meta))

            deduped_docs.append(doc_text)
            deduped_ids.append(doc_id)
            deduped_metas.append(meta if meta is not None else {})
            deduped_dists.append(float(dist) if dist is not None else 0.0)

        return deduped_docs, deduped_ids, deduped_metas, deduped_dists

    # ============================================================
    # DRIVER REPORT RETRIEVAL
    # ============================================================

    def _get_driver_reports(
        self,
        race_name: str,
        driver: str | None = None,
        team: str | None = None,
        season: int | None = None,
    ):
        """
        Retrieve driver reports for a race safely.

        If driver is supplied, return that driver.
        If team is supplied, return ALL drivers belonging to that team.
        Otherwise return all drivers for the race.
        """

        conditions = [
            {"race_name": race_name},
            {"document_type": "driver_report"},
        ]

        if driver:
            conditions.append({"driver": driver})

        if team:
            conditions.append({"team": team})

        if season is not None:
            conditions.append({"season": season})

        where = (
            {"$and": conditions}
            if len(conditions) > 1
            else conditions[0]
        )

        try:
            results = self.client.collection.get(
                where=where,
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            return {
                "ids": [],
                "documents": [],
                "metadatas": [],
                "error": str(exc),
            }

        documents = results.get("documents", []) or []
        ids = results.get("ids", []) or []
        metadatas = results.get("metadatas", []) or []

        deduped_docs, deduped_ids, deduped_metas = self._deduplicate_documents(
            documents=documents,
            ids=ids,
            metadatas=metadatas,
        )

        return {
            "ids": deduped_ids,
            "documents": deduped_docs,
            "metadatas": deduped_metas,
        }

    # ============================================================
    # RACE REPORT RETRIEVAL
    # ============================================================

    def _get_race_report_details(
        self,
        race_name: str,
        season: int | None = None,
    ) -> dict:
        """Retrieve race report documents, ids, and metadatas safely."""
        conditions = [
            {"race_name": race_name},
            {"document_type": "race_report"},
        ]

        if season is not None:
            conditions.append({"season": season})

        where = (
            {"$and": conditions}
            if len(conditions) > 1
            else conditions[0]
        )

        try:
            results = self.client.collection.get(
                where=where,
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            return {
                "ids": [],
                "documents": [],
                "metadatas": [],
                "error": str(exc),
            }

        documents = results.get("documents", []) or []
        ids = results.get("ids", []) or []
        metadatas = results.get("metadatas", []) or []

        deduped_docs, deduped_ids, deduped_metas = self._deduplicate_documents(
            documents=documents,
            ids=ids,
            metadatas=metadatas,
        )

        return {
            "ids": deduped_ids,
            "documents": deduped_docs,
            "metadatas": deduped_metas,
        }

    def _get_race_report(
        self,
        race_name: str,
        season: int | None = None,
    ) -> str:
        """
        Retrieve the race report for a specific Grand Prix.
        """
        details = self._get_race_report_details(race_name=race_name, season=season)
        return "\n\n".join(details.get("documents", []))

    # ============================================================
    # SPRINT REPORT RETRIEVAL
    # ============================================================

    def _get_sprint_report_details(
        self,
        race_name: str,
        season: int | None = None,
    ) -> dict:
        """Retrieve sprint report documents, ids, and metadatas safely."""
        conditions = [
            {"race_name": race_name},
            {"document_type": "sprint_report"},
        ]
        if season is not None:
            conditions.append({"season": season})
        where = {"$and": conditions} if len(conditions) > 1 else conditions[0]
        try:
            results = self.client.collection.get(
                where=where,
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            return {"ids": [], "documents": [], "metadatas": [], "error": str(exc)}
        documents = results.get("documents", []) or []
        ids = results.get("ids", []) or []
        metadatas = results.get("metadatas", []) or []
        deduped_docs, deduped_ids, deduped_metas = self._deduplicate_documents(
            documents=documents, ids=ids, metadatas=metadatas
        )
        return {"ids": deduped_ids, "documents": deduped_docs, "metadatas": deduped_metas}

    def _get_driver_sprint_reports(
        self,
        race_name: str,
        driver: str | None = None,
        team: str | None = None,
        season: int | None = None,
    ) -> dict:
        """Retrieve driver sprint reports for a sprint event safely."""
        conditions = [
            {"race_name": race_name},
            {"document_type": "driver_sprint_report"},
        ]
        if driver:
            conditions.append({"driver": driver})
        if team:
            conditions.append({"team": team})
        if season is not None:
            conditions.append({"season": season})
        where = {"$and": conditions} if len(conditions) > 1 else conditions[0]
        try:
            results = self.client.collection.get(
                where=where,
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            return {"ids": [], "documents": [], "metadatas": [], "error": str(exc)}
        documents = results.get("documents", []) or []
        ids = results.get("ids", []) or []
        metadatas = results.get("metadatas", []) or []
        deduped_docs, deduped_ids, deduped_metas = self._deduplicate_documents(
            documents=documents, ids=ids, metadatas=metadatas
        )
        return {"ids": deduped_ids, "documents": deduped_docs, "metadatas": deduped_metas}

    # ============================================================
    # CALIBRATION, MISMATCH, CONFLICT & ATTRIBUTION HELPERS
    # ============================================================

    @staticmethod
    def _is_explanatory_query(question: str) -> bool:
        """Detect conceptual/technical/explanatory F1 questions."""
        q = question.lower().strip()
        explanatory_markers = (
            "explain ",
            "how does ",
            "how do ",
            "what is ",
            "what are ",
            "why does ",
            "why do ",
            "philosophy",
            "aerodynamic",
            "regulation",
            "rulebook",
            "drs",
            "undercut",
            "overcut",
            "tire degradation",
            "tyre degradation",
            "pit strategy",
            "upgrades",
            "upgrade",
            "ground effect",
            "porpoising",
            "ers",
            "mgu",
            "budget cap",
            "cost cap",
            "wind tunnel",
        )
        return any(marker in q for marker in explanatory_markers)

    def _extract_unrecognized_grand_prix(self, question: str, filters: dict) -> str | None:
        """
        Detect explicit '<Venue> Grand Prix' names that are not in the supported
        calendar so semantic search does not match unrelated 2024 Grand Prix docs.
        """
        if filters.get("race_name"):
            return None

        q_norm = normalize_text(question)
        generic_prefixes = {
            "the", "a", "an", "in", "at", "on", "of", "for", "to", "from", "about",
            "this", "that", "these", "those", "which", "what", "any", "each",
            "every", "next", "last", "first", "final", "sprint", "season", "year",
            "f1", "formula", "one", "1", "grand", "prix", "gp",
        }
        races_map = getattr(self, "RACES", {})
        registry = getattr(self, "registry", None)

        for match in re.finditer(r"\b([a-z0-9]+(?:\s+[a-z0-9]+)?)\s+grand\s+prix\b", q_norm):
            prefix_words = [
                w for w in match.group(1).split()
                if w not in generic_prefixes and not re.fullmatch(r"(?:19|20)\d{2}", w)
            ]
            if not prefix_words:
                continue
            venue_phrase = " ".join(prefix_words)
            if venue_phrase in races_map:
                continue
            if registry is not None:
                try:
                    if registry.resolve_event(f"{venue_phrase} grand prix").matched:
                        continue
                except Exception:
                    pass
            return f"{venue_phrase.title()} Grand Prix"

        return None

    def _extract_unmatched_person_name(self, question: str, filters: dict) -> str | None:
        """
        Extract an explicit named person/driver when EntityRegistry did not match a
        known 2024 driver (e.g., historical or out-of-dataset driver like Ayrton Senna).
        """
        if filters.get("driver"):
            return None

        non_person_tokens = {
            "grand", "prix", "formula", "one", "sprint", "qualifying", "race",
            "circuit", "park", "ring", "bay", "strip", "city", "arabia", "arabian",
            "states", "kingdom", "emilia", "romagna", "paulo", "vegas", "dhabi",
            "red", "bull", "racing", "aston", "martin", "kick", "sauber", "haas",
            "mercedes", "ferrari", "mclaren", "alpine", "williams",
        }
        races_map = getattr(self, "RACES", {})
        teams_map = getattr(self, "TEAMS", {})

        patterns = [
            r"(?i:what\s+happened\s+to|how\s+did|where\s+did|what\s+position\s+did|how\s+many\s+points\s+did|did)\s+([A-Z][a-zA-ZÀ-ÿ\-]+(?:\s+[A-Z][a-zA-ZÀ-ÿ\-]+){1,2})\b",
            r"(?i:performance\s+of|results?\s+(?:for|of)|about)\s+([A-Z][a-zA-ZÀ-ÿ\-]+(?:\s+[A-Z][a-zA-ZÀ-ÿ\-]+){1,2})\b",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, question):
                candidate = match.group(1).strip()
                c_norm = normalize_text(candidate)
                words = c_norm.split()
                if len(words) < 2:
                    continue
                if any(w in non_person_tokens for w in words):
                    continue
                if c_norm in races_map or c_norm in teams_map:
                    continue
                return candidate
        return None

    @staticmethod
    def _has_entity_in_documents(entity_name: str, documents: list[str], metadatas: list[dict]) -> bool:
        """Check whether an explicitly named person/entity is grounded in retrieved docs."""
        e_norm = normalize_text(entity_name)
        tokens = [t for t in e_norm.split() if len(t) >= 3]
        for doc, meta in zip(documents, metadatas):
            combined = normalize_text(
                f"{meta.get('driver', '')} {meta.get('team', '')} {meta.get('race_name', '')} {doc}"
            )
            if e_norm in combined:
                return True
            if tokens and all(re.search(rf"\b{re.escape(t)}\b", combined) for t in tokens):
                return True
        return False

    @staticmethod
    def _detect_conflicts(
        documents: list[str],
        metadatas: list[dict],
    ) -> tuple[bool, list[str]]:
        """
        Detect factual contradictions across retrieved documents for the same
        race/season winner or the same driver's finish position/points in a race.
        """
        if len(documents) < 2:
            return False, []

        winner_claims: dict[tuple[str, str], dict[str, str]] = {}
        driver_pos_claims: dict[tuple[str, str, str], dict[str, str]] = {}
        driver_pts_claims: dict[tuple[str, str, str], dict[str, str]] = {}

        for doc, meta in zip(documents, metadatas):
            m = meta or {}
            race = str(m.get("race_name") or "").strip()
            if not race:
                r_match = re.search(r"(?:Grand Prix|Race):\s*([^\n\r]+)", doc, re.IGNORECASE)
                race = r_match.group(1).strip() if r_match else "unknown_race"
            season = str(m.get("season") or "").strip()
            if not season:
                s_match = re.search(r"Season:\s*(\d{4})", doc, re.IGNORECASE)
                season = s_match.group(1) if s_match else "any"
            race_key = (season, normalize_text(race))

            winner_match = re.search(r"Winner:\s*([^\n\r]+)", doc, re.IGNORECASE)
            if winner_match:
                winner_disp = winner_match.group(1).strip()
                winner_norm = normalize_text(winner_disp)
                if winner_norm:
                    winner_claims.setdefault(race_key, {})[winner_norm] = winner_disp

            driver_name = str(m.get("driver") or "").strip()
            if not driver_name:
                d_match = re.search(r"Driver:\s*([^\n\r]+)", doc, re.IGNORECASE)
                driver_name = d_match.group(1).strip() if d_match else ""
            if driver_name:
                d_key = (season, normalize_text(race), normalize_text(driver_name))
                pos_match = re.search(r"Finished:\s*([^\n\r]+)", doc, re.IGNORECASE)
                if pos_match:
                    pos_val = pos_match.group(1).strip().upper()
                    driver_pos_claims.setdefault(d_key, {})[pos_val] = pos_val
                pts_match = re.search(r"Points:\s*([\d.]+)", doc, re.IGNORECASE)
                if pts_match:
                    pts_val = str(float(pts_match.group(1)))
                    driver_pts_claims.setdefault(d_key, {})[pts_val] = pts_match.group(1)

        details: list[str] = []
        for (season, race_norm), vals in winner_claims.items():
            if len(vals) > 1:
                season_lbl = f"{season} " if season != "any" else ""
                details.append(
                    f"Conflicting winner claims for {season_lbl}{race_norm.title()}: "
                    f"{' vs '.join(vals.values())}"
                )

        for (season, race_norm, drv_norm), vals in driver_pos_claims.items():
            if len(vals) > 1:
                season_lbl = f"{season} " if season != "any" else ""
                details.append(
                    f"Conflicting finishing positions for {drv_norm.title()} in "
                    f"{season_lbl}{race_norm.title()}: {' vs '.join(vals.values())}"
                )

        for (season, race_norm, drv_norm), vals in driver_pts_claims.items():
            if len(vals) > 1:
                season_lbl = f"{season} " if season != "any" else ""
                details.append(
                    f"Conflicting points for {drv_norm.title()} in "
                    f"{season_lbl}{race_norm.title()}: {' vs '.join(vals.values())}"
                )

        return bool(details), details

    @staticmethod
    def _build_sources(
        ids: list[str],
        metadatas: list[dict],
        distances: list[float],
    ) -> list[dict]:
        """Build structured source attribution list for retrieved documents."""
        sources: list[dict] = []
        for doc_id, meta, dist in zip(ids, metadatas, distances):
            m = meta or {}
            entry = {
                "id": doc_id,
                "document_type": m.get("document_type"),
                "season": m.get("season"),
                "race_name": m.get("race_name"),
                "driver": m.get("driver"),
                "team": m.get("team"),
                "distance": round(float(dist), 4) if dist is not None else None,
            }
            sources.append(entry)
        return sources

    @staticmethod
    def _format_attributed_context(
        documents: list[str],
        ids: list[str],
        metadatas: list[dict],
        conflict_details: list[str] | None = None,
    ) -> str:
        """Format retrieved chunks with explicit [Source: ...] metadata headers."""
        blocks: list[str] = []
        if conflict_details:
            blocks.append(f"[CONFLICT DETECTED] {'; '.join(conflict_details)}")

        for doc, doc_id, meta in zip(documents, ids, metadatas):
            m = meta or {}
            parts = []
            if m.get("document_type"):
                parts.append(str(m["document_type"]))
            race_label = " ".join(
                p for p in [str(m["season"]) if m.get("season") else "", m.get("race_name") or ""] if p
            ).strip()
            if race_label:
                parts.append(race_label)
            if m.get("driver"):
                parts.append(f"driver={m['driver']}")
            if m.get("team"):
                parts.append(f"team={m['team']}")
            if doc_id:
                parts.append(f"id={doc_id}")
            header = f"[Source: {' | '.join(parts)}]" if parts else "[Source: knowledge_base]"
            blocks.append(f"{header}\n{doc}")

        return "\n\n".join(blocks)

    @staticmethod
    def _enforce_context_budget(
        documents: list[str],
        ids: list[str],
        metadatas: list[dict],
        distances: list[float],
        max_chunks: int,
        max_chars: int,
    ) -> tuple[list[str], list[str], list[dict], list[float]]:
        """Apply chunk count and character budget caps cleanly without corrupting chunks."""
        kept_docs: list[str] = []
        kept_ids: list[str] = []
        kept_metas: list[dict] = []
        kept_dists: list[float] = []
        total_chars = 0

        for doc, doc_id, meta, dist in zip(documents, ids, metadatas, distances):
            if len(kept_docs) >= max_chunks:
                break
            doc_len = len(doc)
            if kept_docs and (total_chars + doc_len + 2) > max_chars:
                break
            if not kept_docs and doc_len > max_chars:
                doc = doc[:max_chars].rstrip() + "..."
            kept_docs.append(doc)
            kept_ids.append(doc_id)
            kept_metas.append(meta)
            kept_dists.append(dist)
            total_chars += len(doc) + 2

        return kept_docs, kept_ids, kept_metas, kept_dists

    @staticmethod
    def _rerank_candidates(
        question: str,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict],
        distances: list[float],
    ) -> tuple[list[str], list[str], list[dict], list[float]]:
        """
        Order threshold-passing semantic candidates by distance ascending with a
        lightweight lexical keyword overlap boost to break near ties.
        """
        stopwords = {
            "the", "a", "an", "in", "on", "at", "for", "of", "to", "is", "was", "are",
            "were", "did", "does", "do", "what", "who", "when", "where", "why", "how",
            "which", "explain", "tell", "me", "about", "and", "or", "with", "during",
        }
        q_tokens = {
            t for t in re.findall(r"[a-z0-9]+", normalize_text(question))
            if len(t) >= 3 and t not in stopwords
        }

        scored: list[tuple[float, str, str, dict, float]] = []
        for doc, doc_id, meta, dist in zip(documents, ids, metadatas, distances):
            overlap_ratio = 0.0
            if q_tokens:
                doc_tokens = set(re.findall(r"[a-z0-9]+", normalize_text(doc)))
                overlap_ratio = len(q_tokens & doc_tokens) / len(q_tokens)
            # Lower score is better; cap lexical boost so distance dominates
            combined_score = float(dist) - (0.04 * overlap_ratio)
            scored.append((combined_score, doc, doc_id, meta, float(dist)))

        scored.sort(key=lambda item: item[0])
        return (
            [item[1] for item in scored],
            [item[2] for item in scored],
            [item[3] for item in scored],
            [item[4] for item in scored],
        )

    # ============================================================
    # AMBIGUITY DETECTION
    # ============================================================

    @staticmethod
    def _is_ambiguous_query(question: str, filters: dict) -> bool:
        """
        Identify ambiguous queries that lack essential identifying entities.
        """
        q = question.lower().strip()
        race_name = filters.get("race_name")
        driver = filters.get("driver")

        if not race_name:
            race_patterns = [
                r"^who won(?: the race)?\??$",
                r"^who won\??$",
                r"^who (?:was|is) the winner\??$",
                r"^who finished on the podium\??$",
                r"^what (?:was|is) the result of the race\??$",
                r"^tell me about the race\??$",
            ]
            if any(re.search(p, q) for p in race_patterns):
                return True

        if not driver:
            driver_patterns = [
                r"\b(?:what position did|where did)\s+(?:he|she|they|the driver)\s+finish\b",
                r"\bdid (?:he|she|they|the driver) finish\b",
                r"\bhow many points did (?:he|she|they|the driver) score\b",
                r"\bhow did (?:he|she|they|the driver) perform\b",
                r"\bwhat was (?:his|her|their) finish(?:ing)? position\b",
            ]
            if any(re.search(p, q) for p in driver_patterns):
                return True

        return False

    # ============================================================
    # MAIN RETRIEVAL
    # ============================================================

    def retrieve_context(
        self,
        question: str,
        n_results: int = 5,
        include_source_headers: bool = True,
    ) -> RetrievalResult:
        """
        Retrieve calibrated, deduplicated, conflict-checked context with
        explicit metadata source attribution and safe failure status.
        """
        filters = self._extract_filters(question)

        # 1. Ambiguous queries must not pull arbitrary races from semantic search
        if self._is_ambiguous_query(question, filters):
            print("\n========== RETRIEVAL ==========")
            print("Question :", question)
            print("Status   : Ambiguous query detected — suppressing semantic retrieval.")
            print("===============================\n")
            return RetrievalResult(status="ambiguous")

        # 2. Explicit out-of-calendar named Grand Prix must not leak unrelated races
        unrecognized_gp = self._extract_unrecognized_grand_prix(question, filters)
        if unrecognized_gp:
            print("\n========== RETRIEVAL ==========")
            print("Question :", question)
            print("Status   : Unrecognized Grand Prix detected —", unrecognized_gp)
            print("===============================\n")
            return RetrievalResult(status="event_mismatch")

        print("\n========== RETRIEVAL ==========")
        print("Question :", question)
        print("Filters  :", filters)
        print("===============================\n")

        race_name = filters.get("race_name")
        driver = filters.get("driver")
        team = filters.get("team")
        season = filters.get("season")
        document_type = filters.get("document_type")
        unmatched_person = self._extract_unmatched_person_name(question, filters)

        documents: list[str] = []
        ids: list[str] = []
        metadatas: list[dict] = []
        distances: list[float] = []
        retrieval_mode = "semantic"

        # ========================================================
        # DETERMINISTIC SPRINT REPORT RETRIEVAL
        # ========================================================
        if (
            race_name
            and document_type == "sprint_report"
            and not self._is_explanatory_query(question)
        ):
            retrieval_mode = "deterministic"
            results = self._get_sprint_report_details(
                race_name=race_name,
                season=season,
            )
            if results.get("error"):
                return RetrievalResult(
                    status="error",
                    error_message=results["error"],
                )
            documents = results.get("documents", [])
            ids = results.get("ids", [])
            metadatas = results.get("metadatas", [])
            distances = [0.0] * len(documents)

        # ========================================================
        # DETERMINISTIC DRIVER SPRINT RETRIEVAL
        # ========================================================
        elif race_name and document_type == "driver_sprint_report" and driver:
            retrieval_mode = "deterministic"
            results = self._get_driver_sprint_reports(
                race_name=race_name,
                driver=driver,
                season=season,
            )
            if results.get("error"):
                return RetrievalResult(
                    status="error",
                    error_message=results["error"],
                )
            documents = results.get("documents", [])
            ids = results.get("ids", [])
            metadatas = results.get("metadatas", [])
            distances = [0.0] * len(documents)

        elif (
            race_name
            and document_type == "driver_sprint_report"
            and team
            and not self._is_explanatory_query(question)
        ):
            retrieval_mode = "deterministic"
            results = self._get_driver_sprint_reports(
                race_name=race_name,
                team=team,
                season=season,
            )
            if results.get("error"):
                return RetrievalResult(
                    status="error",
                    error_message=results["error"],
                )
            combined = list(
                zip(
                    results.get("documents", []),
                    results.get("ids", []),
                    results.get("metadatas", []),
                )
            )
            combined.sort(key=lambda item: (item[2] or {}).get("driver", ""))
            documents = [item[0] for item in combined]
            ids = [item[1] for item in combined]
            metadatas = [item[2] for item in combined]
            distances = [0.0] * len(documents)

        # ========================================================
        # DETERMINISTIC DRIVER RETRIEVAL
        # ========================================================
        elif race_name and document_type == "driver_report" and driver:
            retrieval_mode = "deterministic"
            results = self._get_driver_reports(
                race_name=race_name,
                driver=driver,
                season=season,
            )
            if results.get("error"):
                return RetrievalResult(
                    status="error",
                    error_message=results["error"],
                )
            documents = results.get("documents", [])
            ids = results.get("ids", [])
            metadatas = results.get("metadatas", [])
            distances = [0.0] * len(documents)

        # ========================================================
        # DETERMINISTIC TEAM RETRIEVAL
        # ========================================================
        elif (
            race_name
            and document_type == "driver_report"
            and team
            and not self._is_explanatory_query(question)
        ):
            retrieval_mode = "deterministic"
            results = self._get_driver_reports(
                race_name=race_name,
                team=team,
                season=season,
            )
            if results.get("error"):
                return RetrievalResult(
                    status="error",
                    error_message=results["error"],
                )
            combined = list(
                zip(
                    results.get("documents", []),
                    results.get("ids", []),
                    results.get("metadatas", []),
                )
            )
            combined.sort(key=lambda item: (item[2] or {}).get("driver", ""))
            documents = [item[0] for item in combined]
            ids = [item[1] for item in combined]
            metadatas = [item[2] for item in combined]
            distances = [0.0] * len(documents)

        # ========================================================
        # DETERMINISTIC ALL-DRIVER RETRIEVAL
        # ========================================================
        elif (
            race_name
            and document_type == "driver_report"
            and not driver
            and not team
            and not self._is_explanatory_query(question)
        ):
            retrieval_mode = "deterministic"
            results = self._get_driver_reports(
                race_name=race_name,
                season=season,
            )
            if results.get("error"):
                return RetrievalResult(
                    status="error",
                    error_message=results["error"],
                )
            combined = list(
                zip(
                    results.get("documents", []),
                    results.get("ids", []),
                    results.get("metadatas", []),
                )
            )
            combined.sort(key=lambda item: (item[2] or {}).get("driver", ""))
            documents = [item[0] for item in combined]
            ids = [item[1] for item in combined]
            metadatas = [item[2] for item in combined]
            distances = [0.0] * len(documents)

        # ========================================================
        # DETERMINISTIC RACE RETRIEVAL
        # ========================================================
        elif (
            race_name
            and document_type == "race_report"
            and not self._is_explanatory_query(question)
        ):
            retrieval_mode = "deterministic"
            results = self._get_race_report_details(
                race_name=race_name,
                season=season,
            )
            if results.get("error"):
                return RetrievalResult(
                    status="error",
                    error_message=results["error"],
                )
            documents = results.get("documents", [])
            ids = results.get("ids", [])
            metadatas = results.get("metadatas", [])
            distances = [0.0] * len(documents)

        # ========================================================
        # FALLBACK SEMANTIC RETRIEVAL
        # ========================================================
        else:
            semantic_filters = dict(filters)
            if self._is_explanatory_query(question):
                semantic_filters.pop("document_type", None)

            fetch_k = max(n_results, 8)
            query_kwargs: dict = {
                "query_texts": [question],
                "n_results": fetch_k,
                "include": ["documents", "metadatas", "distances"],
            }
            where = self._build_where(semantic_filters)
            if where:
                query_kwargs["where"] = where

            print("Semantic where clause:", where)

            try:
                results = self.client.collection.query(**query_kwargs)
            except Exception as exc:
                return RetrievalResult(
                    status="error",
                    error_message=str(exc),
                )

            raw_docs_nested = results.get("documents") or [[]]
            raw_ids_nested = results.get("ids") or [[]]
            raw_metas_nested = results.get("metadatas") or [[]]
            raw_dists_nested = results.get("distances") or [[]]

            raw_documents = raw_docs_nested[0] if raw_docs_nested else []
            raw_ids = raw_ids_nested[0] if raw_ids_nested and raw_ids_nested[0] else [
                f"doc_{i}" for i in range(len(raw_documents))
            ]
            raw_metas = raw_metas_nested[0] if raw_metas_nested and raw_metas_nested[0] else [
                {} for _ in range(len(raw_documents))
            ]
            raw_distances = raw_dists_nested[0] if raw_dists_nested and raw_dists_nested[0] else [
                0.0 for _ in range(len(raw_documents))
            ]

            threshold = getattr(self, "distance_threshold", SEMANTIC_DISTANCE_THRESHOLD)
            had_candidates = bool(raw_documents)

            if raw_distances and len(raw_distances) == len(raw_documents):
                filtered = [
                    (doc, did, meta if meta is not None else {}, float(dist))
                    for doc, did, meta, dist in zip(
                        raw_documents, raw_ids, raw_metas, raw_distances
                    )
                    if float(dist) <= threshold
                ]
            else:
                filtered = [
                    (doc, did, meta if meta is not None else {}, 0.0)
                    for doc, did, meta in zip(raw_documents, raw_ids, raw_metas)
                ]

            if had_candidates and not filtered:
                return RetrievalResult(
                    distances=[float(d) for d in raw_distances],
                    status="low_confidence",
                )

            f_docs = [x[0] for x in filtered]
            f_ids = [x[1] for x in filtered]
            f_metas = [x[2] for x in filtered]
            f_dists = [x[3] for x in filtered]

            r_docs, r_ids, r_metas, r_dists = self._rerank_candidates(
                question=question,
                documents=f_docs,
                ids=f_ids,
                metadatas=f_metas,
                distances=f_dists,
            )

            d_docs, d_ids, d_metas, d_dists = self._deduplicate_with_distances(
                documents=r_docs,
                ids=r_ids,
                metadatas=r_metas,
                distances=r_dists,
            )

            chunk_cap = min(
                n_results,
                getattr(self, "max_context_chunks", MAX_CONTEXT_CHUNKS),
            )
            char_cap = getattr(self, "max_context_chars", MAX_CONTEXT_CHARS)
            documents, ids, metadatas, distances = self._enforce_context_budget(
                documents=d_docs,
                ids=d_ids,
                metadatas=d_metas,
                distances=d_dists,
                max_chunks=chunk_cap,
                max_chars=char_cap,
            )

        if not documents:
            return RetrievalResult(status="empty")

        # 3. Validate explicitly named historical/missing person is actually grounded
        if unmatched_person and not self._has_entity_in_documents(
            unmatched_person, documents, metadatas
        ):
            print(
                f"Entity mismatch: '{unmatched_person}' absent from retrieved documents."
            )
            return RetrievalResult(status="entity_mismatch")

        # 4. Detect conflicting factual claims across retrieved documents
        conflict_detected, conflict_details = self._detect_conflicts(
            documents, metadatas
        )
        status = "conflict" if conflict_detected else "ok"

        raw_context = "\n\n".join(documents)
        attributed_context = (
            self._format_attributed_context(
                documents=documents,
                ids=ids,
                metadatas=metadatas,
                conflict_details=conflict_details if conflict_detected else None,
            )
            if include_source_headers
            else raw_context
        )

        if retrieval_mode == "deterministic":
            print(f"Deterministic retrieval ({len(documents)} doc(s)):")
            print(raw_context[:1500])

        return RetrievalResult(
            documents=documents,
            ids=ids,
            metadatas=metadatas,
            distances=distances,
            status=status,
            context=attributed_context,
            raw_context=raw_context,
            sources=self._build_sources(ids, metadatas, distances),
            conflict_detected=conflict_detected,
            conflict_details=conflict_details,
        )

    def retrieve(
        self,
        question: str,
        n_results: int = 5,
    ) -> str:
        """
        Retrieve the best grounded context string for backwards compatibility.
        """
        result = self.retrieve_context(
            question=question,
            n_results=n_results,
            include_source_headers=False,
        )
        return result.raw_context


RaceRetriever = Retriever