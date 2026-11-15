"""
Entity Registry for RaceIntel.

Loads and normalizes supported F1 entities (events, circuits, drivers,
constructors, and seasons) dynamically from SQLite.
SQLite is the single source of truth.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from raceintel.services.event_aliases import (
    COUNTRY_ALIASES,
    EXPLICIT_EVENT_ALIASES,
    KNOWN_CIRCUIT_ALIASES,
    normalize_text,
    strip_gp_suffix,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "raceintel.db"


@dataclass
class EventResolution:
    matched: bool
    event_name: str | None = None
    event_id: int | None = None
    country_name: str | None = None
    circuit_name: str | None = None
    season_year: int | None = None
    is_ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)


@dataclass
class CircuitResolution:
    matched: bool
    circuit_name: str | None = None
    canonical_event: str | None = None
    event_id: int | None = None
    country_name: str | None = None
    is_ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)


@dataclass
class DriverResolution:
    matched: bool
    driver_full_name: str | None = None
    driver_id: int | None = None
    driver_code: str | None = None
    driver_number: int | None = None
    constructor_id: int | None = None
    is_ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)


@dataclass
class ConstructorResolution:
    matched: bool
    constructor_name: str | None = None
    constructor_id: int | None = None
    is_ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)


class EntityRegistry:
    """
    Database-driven entity registry for RaceIntel.
    Loads entities from SQLite into memory and provides fast,
    normalized, ambiguity-aware resolution.
    """

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.supported_seasons: set[int] = set()
        self.events: list[dict] = []
        self.drivers: list[dict] = []
        self.constructors: list[dict] = []

        # Internal lookup indexes
        self._event_alias_map: dict[str, list[dict]] = {}
        self._exact_event_map: dict[str, list[dict]] = {}
        self._event_alias_stage_map: dict[str, list[dict]] = {}
        self._circuit_alias_map: dict[str, list[dict]] = {}
        self._country_alias_map: dict[str, list[dict]] = {}
        self._driver_alias_map: dict[str, list[dict]] = {}
        self._constructor_alias_map: dict[str, list[dict]] = {}

        self.reload()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a read-only SQLite connection if possible, else standard connection."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found at {self.db_path}")

        try:
            uri_path = self.db_path.resolve().as_posix()
            return sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
        except Exception:
            return sqlite3.connect(str(self.db_path))

    def reload(self, db_path: Path | str | None = None):
        """Reload all entity tables from the database."""
        if db_path is not None:
            self.db_path = Path(db_path)

        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return

        try:
            conn = self._get_connection()
        except Exception:
            return

        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()

            # 1. Seasons
            cur.execute("SELECT season_id, season_year FROM seasons ORDER BY season_year ASC;")
            self.supported_seasons = {int(row["season_year"]) for row in cur.fetchall()}

            # 2. Constructors
            cur.execute("SELECT constructor_id, constructor_name FROM constructors ORDER BY constructor_id ASC;")
            self.constructors = [dict(row) for row in cur.fetchall()]

            # 3. Drivers
            cur.execute(
                """
                SELECT driver_id, driver_code, driver_number, driver_full_name, constructor_id 
                FROM drivers ORDER BY driver_id ASC;
                """
            )
            self.drivers = [dict(row) for row in cur.fetchall()]

            # 4. Events
            cur.execute(
                """
                SELECT e.event_id, e.season_id, e.event_name, e.country_name, e.circuit_name, s.season_year
                FROM events e
                JOIN seasons s ON e.season_id = s.season_id
                ORDER BY e.event_id ASC;
                """
            )
            self.events = [dict(row) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return
        finally:
            conn.close()

        self._build_indexes()

    def _build_indexes(self):
        """Build normalized alias lookup dictionaries for events, circuits, drivers and constructors."""
        self._event_alias_map.clear()
        self._exact_event_map.clear()
        self._event_alias_stage_map.clear()
        self._circuit_alias_map.clear()
        self._country_alias_map.clear()
        self._driver_alias_map.clear()
        self._constructor_alias_map.clear()

        # --------------------------------------------------------
        # Constructors
        # --------------------------------------------------------
        # Known common aliases mapping to canonical constructor names
        common_team_aliases: dict[str, list[str]] = {
            "red bull racing": ["red bull", "red bull racing", "rbr"],
            "ferrari": ["ferrari", "scuderia", "scuderia ferrari"],
            "mercedes": ["mercedes", "mercedes amg", "silver arrows"],
            "mclaren": ["mclaren"],
            "aston martin": ["aston martin", "aston"],
            "alpine": ["alpine"],
            "haas f1 team": ["haas", "haas f1", "haas f1 team"],
            "williams": ["williams"],
            "rb": ["rb", "racing bulls", "visa cash app rb", "vcarb"],
            "kick sauber": ["kick sauber", "sauber", "stake sauber", "stake"],
        }

        for c in self.constructors:
            c_name = c["constructor_name"]
            norm_name = normalize_text(c_name)
            self._add_to_multimap(self._constructor_alias_map, norm_name, c)

            # Check common aliases
            for base_key, aliases in common_team_aliases.items():
                if normalize_text(base_key) == norm_name or norm_name.startswith(normalize_text(base_key)):
                    for alias in aliases:
                        self._add_to_multimap(self._constructor_alias_map, normalize_text(alias), c)

        # --------------------------------------------------------
        # Drivers
        # --------------------------------------------------------
        common_driver_nicknames: dict[str, list[str]] = {
            "max verstappen": ["max", "verstappen"],
            "sergio perez": ["checo", "perez", "sergio"],
            "charles leclerc": ["charles", "leclerc"],
            "carlos sainz": ["carlos", "sainz"],
            "lewis hamilton": ["lewis", "hamilton"],
            "george russell": ["george", "russell"],
            "lando norris": ["lando", "norris"],
            "oscar piastri": ["oscar", "piastri"],
            "fernando alonso": ["fernando", "alonso"],
            "lance stroll": ["lance", "stroll"],
            "pierre gasly": ["pierre", "gasly"],
            "esteban ocon": ["esteban", "ocon"],
            "yuki tsunoda": ["yuki", "tsunoda"],
            "daniel ricciardo": ["daniel", "ricciardo"],
            "alexander albon": ["alex", "alex albon", "albon"],
            "logan sargeant": ["logan", "sargeant"],
            "nico hulkenberg": ["nico", "hulkenberg", "hulk"],
            "kevin magnussen": ["kevin", "magnussen"],
            "valtteri bottas": ["valtteri", "bottas"],
            "guanyu zhou": ["zhou", "zhou guanyu", "guanyu"],
            "oliver bearman": ["bearman", "ollie", "ollie bearman"],
            "franco colapinto": ["colapinto", "franco"],
            "liam lawson": ["lawson", "liam"],
            "jack doohan": ["doohan", "jack"],
        }

        for d in self.drivers:
            full_name = d["driver_full_name"]
            norm_full = normalize_text(full_name)
            self._add_to_multimap(self._driver_alias_map, norm_full, d)

            # Driver code
            if d.get("driver_code"):
                self._add_to_multimap(self._driver_alias_map, normalize_text(d["driver_code"]), d)

            # Token names (first name, surname)
            tokens = norm_full.split()
            if len(tokens) >= 2:
                # First name
                self._add_to_multimap(self._driver_alias_map, tokens[0], d)
                # Last name
                self._add_to_multimap(self._driver_alias_map, tokens[-1], d)

            # Known nicknames
            for target_name, nicknames in common_driver_nicknames.items():
                if norm_full == normalize_text(target_name):
                    for nick in nicknames:
                        self._add_to_multimap(self._driver_alias_map, normalize_text(nick), d)

        # --------------------------------------------------------
        # Events & Circuits
        # --------------------------------------------------------
        country_norm_set = {
            normalize_text(ev.get("country_name") or "")
            for ev in self.events
            if ev.get("country_name")
        }

        for ev in self.events:
            ev_name = ev["event_name"]
            norm_ev = normalize_text(ev_name)
            clean_ev = strip_gp_suffix(norm_ev)

            # Stage 1: Exact event names (including explicit "<stem> gp" / "<stem> grand prix")
            self._add_to_multimap(self._exact_event_map, norm_ev, ev)
            self._add_to_multimap(self._event_alias_map, norm_ev, ev)
            if clean_ev:
                self._add_to_multimap(self._exact_event_map, f"{clean_ev} grand prix", ev)
                self._add_to_multimap(self._exact_event_map, f"{clean_ev} gp", ev)
                self._add_to_multimap(self._event_alias_map, clean_ev, ev)
                # Bare event stem is an event-specific alias only when it is not a country name
                # (e.g., 'emilia romagna', 'miami', 'las vegas', 'sao paulo', 'italian', 'british';
                # whereas bare 'united states' goes to country fallback so multi-race ambiguity holds).
                if clean_ev not in country_norm_set:
                    self._add_to_multimap(self._event_alias_stage_map, clean_ev, ev)

            # Stage 2: Explicit event-specific aliases
            for target_ev_norm, ev_aliases in EXPLICIT_EVENT_ALIASES.items():
                if norm_ev == target_ev_norm:
                    for alias in ev_aliases:
                        norm_a = normalize_text(alias)
                        self._add_to_multimap(self._event_alias_stage_map, norm_a, ev)
                        self._add_to_multimap(self._event_alias_map, norm_a, ev)

            # Stage 3: Circuit & venue mappings
            raw_circuit = ev.get("circuit_name") or ""
            norm_circuit = normalize_text(raw_circuit)
            if norm_circuit:
                self._add_to_multimap(self._circuit_alias_map, norm_circuit, ev)
                self._add_to_multimap(self._event_alias_map, norm_circuit, ev)

                # Expand circuit aliases using exact token-boundary / equality check on base circuit
                for base_circ, circ_aliases in KNOWN_CIRCUIT_ALIASES.items():
                    norm_base = normalize_text(base_circ)
                    if (
                        norm_base == norm_circuit
                        or re.search(rf"\b{re.escape(norm_base)}\b", norm_circuit)
                        or re.search(rf"\b{re.escape(norm_circuit)}\b", norm_base)
                    ):
                        for a in circ_aliases:
                            norm_a = normalize_text(a)
                            self._add_to_multimap(self._circuit_alias_map, norm_a, ev)
                            self._add_to_multimap(self._event_alias_map, norm_a, ev)

            # Stage 5: Country fallback mappings
            raw_country = ev.get("country_name") or ""
            norm_country = normalize_text(raw_country)
            if norm_country:
                self._add_to_multimap(self._country_alias_map, norm_country, ev)
                self._add_to_multimap(self._event_alias_map, norm_country, ev)
                for base_country, c_aliases in COUNTRY_ALIASES.items():
                    if normalize_text(base_country) == norm_country:
                        for a in c_aliases:
                            norm_a = normalize_text(a)
                            self._add_to_multimap(self._country_alias_map, norm_a, ev)
                            self._add_to_multimap(self._event_alias_map, norm_a, ev)

    @staticmethod
    def _add_to_multimap(mmap: dict[str, list[dict]], key: str, value: dict):
        if not key:
            return
        if key not in mmap:
            mmap[key] = []
        # Prevent exact duplicate records
        if value not in mmap[key]:
            mmap[key].append(value)

    # ============================================================
    # PUBLIC RESOLUTION API
    # ============================================================

    def is_season_supported(self, season: int) -> bool:
        """Check whether a season year exists in the database."""
        return season in self.supported_seasons

    def get_supported_seasons(self) -> set[int]:
        """Return the set of supported seasons from the database."""
        return set(self.supported_seasons)

    def _match_stage_map(self, stage_map: dict[str, list[dict]], norm: str) -> list[dict]:
        """Match normalized query text against one stage map using exact then non-overlapping boundary matches."""
        exact = stage_map.get(norm)
        if exact:
            return list(exact)

        matched: list[dict] = []
        occupied_spans: list[tuple[int, int]] = []
        for alias_key, ev_list in sorted(stage_map.items(), key=lambda x: len(x[0]), reverse=True):
            for m in re.finditer(rf"\b{re.escape(alias_key)}\b", norm):
                start, end = m.span()
                if any(not (end <= s or start >= e) for s, e in occupied_spans):
                    continue
                occupied_spans.append((start, end))
                matched.extend(ev_list)
        return matched

    def resolve_event(self, name_or_alias: str, season: int | None = None) -> EventResolution:
        """
        Resolve an event name, country, city, or alias to a canonical Grand Prix event
        using strict priority order:
          1. Exact event name
          2. Event-specific aliases
          3. Circuit / venue aliases
          4. Season-aware disambiguation (when season is given)
          5. Country fallback (only when no specific event/circuit matches)

        If ambiguous (multiple distinct events match at the winning stage), returns
        matched=False, is_ambiguous=True with candidates.
        """
        norm = normalize_text(name_or_alias)
        if not norm:
            return EventResolution(matched=False)

        if season is not None and self.supported_seasons and season not in self.supported_seasons:
            return EventResolution(matched=False)

        stage_maps = [
            self._exact_event_map,
            self._event_alias_stage_map,
            self._circuit_alias_map,
            self._country_alias_map,
        ]

        matches: list[dict] = []
        for stage_map in stage_maps:
            stage_matches = self._match_stage_map(stage_map, norm)
            if stage_matches:
                if season is not None:
                    season_filtered = [ev for ev in stage_matches if ev.get("season_year") == season]
                    if season_filtered:
                        matches = season_filtered
                        break
                    # Event exists in another season but not requested season
                    continue
                matches = stage_matches
                break

        if not matches:
            return EventResolution(matched=False)

        # Deduplicate matched events: when season=None and same event name appears across seasons,
        # Deduplicate matched events: when season=None and same event name appears across seasons,
        # differentiate distinct (season_year, event_id) vs distinct event names.
        unique_events = {ev["event_id"]: ev for ev in matches}
        if len(unique_events) > 1:
            distinct_names = list(dict.fromkeys(ev["event_name"] for ev in unique_events.values()))
            if season is None and len(distinct_names) == 1:
                ev = next(iter(unique_events.values()))
                return EventResolution(
                    matched=True,
                    event_name=distinct_names[0],
                    event_id=ev["event_id"],
                    country_name=ev.get("country_name"),
                    circuit_name=ev.get("circuit_name"),
                    season_year=None,
                    is_ambiguous=False,
                    candidates=[],
                )
            else:
                return EventResolution(
                    matched=False,
                    is_ambiguous=True,
                    candidates=distinct_names,
                )

        ev = next(iter(unique_events.values()))
        return EventResolution(
            matched=True,
            event_name=ev["event_name"],
            event_id=ev["event_id"],
            country_name=ev.get("country_name"),
            circuit_name=ev.get("circuit_name"),
            season_year=ev.get("season_year"),
        )

    def resolve_circuit(self, circuit_name: str) -> CircuitResolution:
        """
        Resolve a circuit name or alias to its canonical event and circuit information.
        """
        norm = normalize_text(circuit_name)
        if not norm:
            return CircuitResolution(matched=False)

        matches = self._circuit_alias_map.get(norm)
        if not matches:
            for alias_key, ev_list in sorted(self._circuit_alias_map.items(), key=lambda x: len(x[0]), reverse=True):
                if re.search(rf"\b{re.escape(alias_key)}\b", norm):
                    matches = ev_list
                    break

        if not matches:
            return CircuitResolution(matched=False)

        distinct_circuits = list(dict.fromkeys(ev.get("circuit_name", "") for ev in matches if ev.get("circuit_name")))
        distinct_events = list(dict.fromkeys(ev["event_name"] for ev in matches if ev.get("event_name")))
        if len(distinct_circuits) > 1 or len(distinct_events) > 1:
            return CircuitResolution(
                matched=False,
                is_ambiguous=True,
                candidates=distinct_circuits if len(distinct_circuits) > 1 else distinct_events,
            )

        ev = matches[0]
        return CircuitResolution(
            matched=True,
            circuit_name=ev.get("circuit_name"),
            canonical_event=ev["event_name"],
            event_id=ev["event_id"],
            country_name=ev.get("country_name"),
        )

    def resolve_driver(self, name_or_alias: str) -> DriverResolution:
        """
        Resolve a driver name, code, or nickname to a canonical driver record.
        """
        norm = normalize_text(name_or_alias)
        if not norm:
            return DriverResolution(matched=False)

        matches = self._driver_alias_map.get(norm)
        if not matches:
            norm_words = norm.split()
            for alias_key, d_list in sorted(self._driver_alias_map.items(), key=lambda x: len(x[0]), reverse=True):
                if re.search(rf"\b{re.escape(alias_key)}\b", norm):
                    alias_words = alias_key.split()
                    if len(norm_words) >= 2 and len(alias_words) == 1:
                        valid_d_list = []
                        for d in d_list:
                            dfull_words = normalize_text(d["driver_full_name"]).split()
                            if dfull_words and alias_key == dfull_words[-1]:
                                first_name = dfull_words[0]
                                leading = norm_words[0]
                                if leading == first_name or leading in dfull_words or any(
                                    leading in normalize_text(k)
                                    for k in self._driver_alias_map
                                    if d in self._driver_alias_map[k]
                                ):
                                    valid_d_list.append(d)
                            else:
                                valid_d_list.append(d)
                        if valid_d_list:
                            matches = valid_d_list
                            break
                    else:
                        matches = d_list
                        break

        if not matches:
            return DriverResolution(matched=False)

        unique_drivers = {d["driver_id"]: d for d in matches}
        if len(unique_drivers) > 1:
            return DriverResolution(
                matched=False,
                is_ambiguous=True,
                candidates=[d["driver_full_name"] for d in unique_drivers.values()],
            )

        d = next(iter(unique_drivers.values()))
        return DriverResolution(
            matched=True,
            driver_full_name=d["driver_full_name"],
            driver_id=d["driver_id"],
            driver_code=d.get("driver_code"),
            driver_number=d.get("driver_number"),
            constructor_id=d.get("constructor_id"),
        )

    def resolve_constructor(self, name_or_alias: str) -> ConstructorResolution:
        """
        Resolve a team or constructor name or alias to a canonical constructor.
        """
        norm = normalize_text(name_or_alias)
        if not norm:
            return ConstructorResolution(matched=False)

        matches = self._constructor_alias_map.get(norm)
        if not matches:
            for alias_key, c_list in sorted(self._constructor_alias_map.items(), key=lambda x: len(x[0]), reverse=True):
                if re.search(rf"\b{re.escape(alias_key)}\b", norm):
                    matches = c_list
                    break

        if not matches:
            return ConstructorResolution(matched=False)

        unique_constructors = {c["constructor_id"]: c for c in matches}
        if len(unique_constructors) > 1:
            return ConstructorResolution(
                matched=False,
                is_ambiguous=True,
                candidates=[c["constructor_name"] for c in unique_constructors.values()],
            )

        c = next(iter(unique_constructors.values()))
        return ConstructorResolution(
            matched=True,
            constructor_name=c["constructor_name"],
            constructor_id=c["constructor_id"],
        )

    # ============================================================
    # COMPATIBILITY MAP GENERATORS
    # ============================================================

    def get_races_map(self) -> dict[str, str]:
        """
        Generate a comprehensive lowercase keyword -> canonical event name dictionary
        for seamless compatibility with Retriever.RACES.
        Includes circuit names, countries, and common Grand Prix variations.
        """
        result: dict[str, str] = {}
        # Pre-seed with existing baseline names for 100% backwards compatibility
        for alias, ev_list in self._event_alias_map.items():
            distinct_names = {ev["event_name"] for ev in ev_list}
            if len(distinct_names) == 1:
                result[alias] = next(iter(distinct_names))

        # Ensure unambiguous circuits are included
        for circ_alias, ev_list in self._circuit_alias_map.items():
            distinct_names = {ev["event_name"] for ev in ev_list}
            if len(distinct_names) == 1:
                result[circ_alias] = next(iter(distinct_names))

        for alias, ev_list in self._exact_event_map.items():
            distinct_names = {ev["event_name"] for ev in ev_list}
            if len(distinct_names) == 1:
                result[alias] = next(iter(distinct_names))

        for alias, ev_list in self._event_alias_stage_map.items():
            distinct_names = {ev["event_name"] for ev in ev_list}
            if len(distinct_names) == 1:
                result[alias] = next(iter(distinct_names))

        # Specific Grand Prix short names for multi-event host nations
        for ev in self.events:
            ev_name = ev["event_name"]
            norm_name = normalize_text(ev_name)
            clean_name = strip_gp_suffix(norm_name)
            if clean_name:
                result[clean_name] = ev_name
        if any("United States Grand Prix" in ev["event_name"] for ev in self.events):
            result["usa"] = "United States Grand Prix"
            result["united states"] = "United States Grand Prix"
        if any("Italian Grand Prix" in ev["event_name"] for ev in self.events):
            result["italy"] = "Italian Grand Prix"
        for ev in self.events:
            if "paulo" in ev["event_name"].lower():
                result["são paulo"] = ev["event_name"]
                result["sao paulo"] = ev["event_name"]

        return result

    def get_ambiguous_country_aliases(self, season: int | None = None) -> dict[str, list[str]]:
        """Return country/regional aliases that map to >1 distinct event in the active season."""
        ambiguous: dict[str, list[str]] = {}
        for alias, ev_list in self._country_alias_map.items():
            scoped = [ev for ev in ev_list if season is None or ev.get("season_year") == season]
            unique_names = list(dict.fromkeys(ev["event_name"] for ev in scoped))
            if len(unique_names) > 1:
                ambiguous[alias] = unique_names
        return ambiguous

    def get_drivers_map(self) -> dict[str, str]:
        """
        Generate a comprehensive lowercase keyword -> canonical driver full name dictionary
        for seamless compatibility with Retriever.DRIVERS.
        Includes full names, surnames, first names, codes, and nicknames.
        """
        result: dict[str, str] = {}
        for alias, d_list in self._driver_alias_map.items():
            unique = {d["driver_id"]: d for d in d_list}
            if len(unique) == 1:
                d = next(iter(unique.values()))
                result[alias] = d["driver_full_name"]
        return result

    def get_teams_map(self) -> dict[str, str]:
        """
        Generate a comprehensive lowercase keyword -> canonical constructor name dictionary
        for seamless compatibility with Retriever.TEAMS.
        """
        result: dict[str, str] = {}
        for alias, c_list in self._constructor_alias_map.items():
            unique = {c["constructor_id"]: c for c in c_list}
            if len(unique) == 1:
                c = next(iter(unique.values()))
                result[alias] = c["constructor_name"]
        return result
