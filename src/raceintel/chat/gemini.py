import os
import re
from google import genai
from google.genai import errors

from raceintel import config
settings = config.settings


class OfflineBlockedError(RuntimeError):
    """Raised when an external Gemini API request is attempted in offline mode."""
    pass


class _BlockedModels:
    """Mock models interface that raises OfflineBlockedError if invoked."""

    def generate_content(self, *args, **kwargs):
        raise OfflineBlockedError(
            "External Gemini API calls are blocked in offline mode."
        )


class _BlockedGenAIClient:
    """Guarded client that prevents network requests in offline mode."""

    def __init__(self):
        self.models = _BlockedModels()


class GeminiClient:
    """
    RaceIntel Gemini client with support for explicit offline evaluation.

    Modes:
    - Normal (production): Communicates with Google GenAI API.
    - Offline: Blocks all external network calls and generates deterministic mock responses
      when ChatService reaches the LLM fallback.
    """

    _global_offline: bool | None = None
    _external_call_count: int = 0

    @classmethod
    def set_global_offline(cls, offline: bool | None):
        """Globally toggle offline mode across all instances."""
        cls._global_offline = offline

    @classmethod
    def is_offline(cls) -> bool:
        """Check whether offline mode is currently active."""
        if cls._global_offline is not None:
            return cls._global_offline
        if os.getenv("RACEINTEL_OFFLINE", "").lower() in ("1", "true", "yes"):
            return True
        if not config.settings.GEMINI_API_KEY:
            return True
        return False

    @classmethod
    def get_external_call_count(cls) -> int:
        """Return the total number of external Gemini API calls attempted."""
        return cls._external_call_count

    @classmethod
    def reset_external_call_count(cls):
        """Reset external call counter to zero."""
        cls._external_call_count = 0

    def __init__(self, offline: bool | None = None):
        if offline is not None:
            self.offline = bool(offline)
        else:
            self.offline = self.is_offline()

        if not self.offline:
            self.client = genai.Client(
                api_key=config.settings.GEMINI_API_KEY or "dummy_key_unauthenticated"
            )
        else:
            self.client = _BlockedGenAIClient()

    def generate(self, prompt: str) -> str:
        """
        Generate answer for prompt. In offline mode, uses deterministic mock.
        In normal mode, calls Google GenAI API.
        """
        if self.offline:
            return self._generate_mock_response(prompt)

        return self._call_external(prompt)

    def _call_external(self, prompt: str) -> str:
        """Execute live external Gemini API request."""
        if self.offline:
            raise OfflineBlockedError(
                "External Gemini API calls are blocked in offline mode."
            )

        GeminiClient._external_call_count += 1

        try:
            response = self.client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config={
                    "temperature": 0.0,
                },
            )

            text = getattr(response, "text", None) if response is not None else None
            if not isinstance(text, str) or not text.strip():
                return "I couldn't find that information in the retrieved race data."
            cleaned = text.strip()
            if cleaned.lower() in {"none", "null", "n/a"}:
                return "I couldn't find that information in the retrieved race data."
            return cleaned

        except errors.ClientError as e:
            if e.code == 429:
                return (
                    "Gemini API quota exceeded. "
                    "Please try again later."
                )

            raise

    @staticmethod
    def _extract_driver_blocks(context: str) -> list[dict]:
        """Parse driver_report structured blocks from retrieved RAG context."""
        blocks: list[dict] = []
        chunks = re.split(r"(?=^Driver:|\n\[Source:)", context, flags=re.MULTILINE | re.IGNORECASE)
        for chunk in chunks:
            d_m = re.search(r"^Driver:\s*(?:\n\s*)?([^\n\r]+)", chunk, re.MULTILINE | re.IGNORECASE)
            if not d_m:
                continue
            driver = d_m.group(1).strip()
            c_m = re.search(r"^Constructor:\s*(?:\n\s*)?([^\n\r]+)", chunk, re.MULTILINE | re.IGNORECASE)
            f_m = re.search(r"^Finished:\s*(?:\n\s*)?([^\n\r]+)", chunk, re.MULTILINE | re.IGNORECASE)
            p_m = re.search(r"^Points:\s*(?:\n\s*)?([\d.]+)", chunk, re.MULTILINE | re.IGNORECASE)
            e_m = re.search(r"^Grand Prix:\s*(?:\n\s*)?([^\n\r]+)", chunk, re.MULTILINE | re.IGNORECASE)
            blocks.append({
                "driver": driver,
                "constructor": c_m.group(1).strip() if c_m else None,
                "finished": f_m.group(1).strip().upper() if f_m else None,
                "points": p_m.group(1).strip() if p_m else None,
                "event": e_m.group(1).strip() if e_m else None,
            })
        return blocks

    @staticmethod
    def _extract_race_fields(context: str) -> dict:
        """Parse structured race_report fields from retrieved RAG context."""
        season_m = re.search(r"^Season:\s*(?:\n\s*)?(\d{4})", context, re.MULTILINE | re.IGNORECASE)
        round_m = re.search(r"^Round:\s*(?:\n\s*)?(\d+)", context, re.MULTILINE | re.IGNORECASE)
        event_m = re.search(r"^Grand Prix:\s*(?:\n\s*)?([^\n\r]+)", context, re.MULTILINE | re.IGNORECASE)
        winner_m = re.search(r"^Winner:\s*(?:\n\s*)?([^\n\r]+)", context, re.MULTILINE | re.IGNORECASE)
        fastest_m = re.search(r"^Fastest Lap:\s*(?:\n\s*)?([^\n\r]+)", context, re.MULTILINE | re.IGNORECASE)
        podium_m = re.search(
            r"^Podium:\s*(?:\n\s*)?(.*?)(?:\n\s*\n|Classification:|Fastest Lap:|Race Summary:|\[Source:|$)",
            context,
            re.MULTILINE | re.IGNORECASE | re.DOTALL,
        )
        summary_m = re.search(
            r"^Race Summary:\s*(?:\n\s*)?(.*?)(?:\n\s*\[Source:|\n\s*Season:|$)",
            context,
            re.MULTILINE | re.IGNORECASE | re.DOTALL,
        )
        summary_text = ""
        if summary_m:
            summary_text = " ".join(
                line.strip() for line in summary_m.group(1).splitlines() if line.strip()
            )
        podium_lines: list[str] = []
        if podium_m:
            for line in podium_m.group(1).splitlines():
                s = line.strip()
                if s and not s.startswith("[Source:"):
                    podium_lines.append(s)

        return {
            "season": season_m.group(1).strip() if season_m else None,
            "round": round_m.group(1).strip() if round_m else None,
            "event": event_m.group(1).strip() if event_m else None,
            "winner": winner_m.group(1).strip() if winner_m else None,
            "fastest_lap": fastest_m.group(1).strip() if fastest_m else None,
            "podium_lines": podium_lines,
            "summary": summary_text,
        }

    def _generate_mock_response(self, prompt: str) -> str:
        """
        Deterministic extractive mock response used ONLY in offline mode
        (offline=True). Live Gemini generation uses _call_external() exclusively.
        """
        prompt_text = str(prompt)
        refusal_msg = "I couldn't find that information in the retrieved race data."

        context_match = re.search(r"Context:\s*\n(.*?)\n\s*Question:", prompt_text, re.DOTALL)
        question_match = re.search(r"Question:\s*\n(.*?)\n\s*Answer:", prompt_text, re.DOTALL)

        context = context_match.group(1).strip() if context_match else ""
        question = question_match.group(1).strip() if question_match else ""

        if not context or "[NO RELEVANT CONTEXT RETRIEVED]" in context:
            return refusal_msg

        # 0. Conflict banner check
        if "[CONFLICT DETECTED]" in context:
            first_line = context.splitlines()[0].replace("[CONFLICT DETECTED]", "").strip()
            return (
                "Conflicting race data was found in the retrieved documents"
                + (f": {first_line}." if first_line else ".")
                + " I cannot determine a single definitive answer."
            )

        q_lower = question.lower()
        c_lower = context.lower()

        # 1. Verify race location in question is grounded in context
        f1_locations = [
            "bahrain", "saudi", "australian", "australia", "japanese", "japan",
            "chinese", "china", "miami", "emilia", "imola", "monaco", "canadian",
            "canada", "spanish", "spain", "austrian", "austria", "british",
            "hungarian", "hungary", "belgian", "belgium", "dutch", "netherlands",
            "italian", "monza", "azerbaijan", "baku", "singapore", "united states",
            "austin", "mexico", "brazilian", "são paulo", "sao paulo", "las vegas",
            "qatar", "abu dhabi", "french", "german", "germany", "swiss",
        ]
        for loc in f1_locations:
            if re.search(rf"\b{re.escape(loc)}\b", q_lower) and not re.search(rf"\b{re.escape(loc)}\b", c_lower):
                return refusal_msg

        # 2. Out-of-domain or unsupported season references absent from context
        ood_terms = [
            "french grand prix", "german grand prix", "germany", "swiss grand prix",
            "motogp", "bathurst", "nascar", "indy", "2020", "2021", "2022", "2023",
        ]
        for term in ood_terms:
            if term in q_lower and term not in c_lower:
                return refusal_msg

        # 2b. Verify requested technical/unbacked topic is grounded in retrieved text
        specific_topics = [
            "upgrade", "upgrades", "aerodynamic", "philosophy", "front wing",
            "rear wing", "diffuser", "budget cap", "cost cap", "wind tunnel",
            "drs", "undercut", "overcut", "porpoising", "ground effect",
            "regulation", "regulations", "steward", "penalty", "telemetry",
            "power unit", "suspension", "gearbox", "recipe", "cake",
            "pit stop duration", "pit stop time", "fastest pit stop",
            "qualifying", "pole position", "sprint", "sector time", "speed trap",
        ]
        asked_topics = [t for t in specific_topics if re.search(rf"\b{re.escape(t)}\b", q_lower)]
        if asked_topics and not any(t in c_lower for t in asked_topics):
            return refusal_msg

        driver_blocks = self._extract_driver_blocks(context)
        race_fields = self._extract_race_fields(context)

        # Match driver blocks actually named in the question
        matched_blocks: list[dict] = []
        for b in driver_blocks:
            full = b["driver"].lower()
            parts = full.split()
            surname = parts[-1] if parts else full
            if re.search(rf"\b{re.escape(full)}\b", q_lower) or (
                len(surname) >= 3 and re.search(rf"\b{re.escape(surname)}\b", q_lower)
            ):
                matched_blocks.append(b)

        # 3. Check if an explicitly named driver/person query is absent from context
        driver_perf_match = re.search(
            r"(?:how\s+did|where\s+did|what\s+position\s+did|what\s+happened\s+to)\s+([A-Za-z\s]+?)\s+(?:perform|finish|qualify|in)\b",
            q_lower,
        )
        if driver_perf_match:
            target_driver = driver_perf_match.group(1).strip().lower()
            if target_driver and target_driver not in {"the race", "it"} and target_driver not in c_lower:
                return refusal_msg

        # 4. "Did [Driver] win [Race]?"
        did_win_match = re.search(r"did\s+([A-Za-z\s]+?)\s+win\b", q_lower)
        if did_win_match:
            driver_q = did_win_match.group(1).strip().lower()
            if driver_q not in c_lower:
                return refusal_msg

            p1_block = next((b for b in driver_blocks if b.get("finished") == "P1"), None)
            if p1_block:
                p1_driver = p1_block["driver"]
                if driver_q in p1_driver.lower() or p1_driver.lower() in driver_q:
                    return f"Yes, {p1_driver} won the race, finishing P1."
                return f"No, {driver_q.title()} did not win the race."

            if race_fields.get("winner"):
                winner = race_fields["winner"]
                if driver_q in winner.lower() or winner.lower() in driver_q:
                    return f"Yes, {winner} won the race."
                return f"No, {driver_q.title()} did not win the race."

        # 5. Race winner / podium / fastest lap queries in RAG mock
        if any(k in q_lower for k in ["winner", "who won", "which driver won", "victory", "chequered flag"]):
            if race_fields.get("winner"):
                return f"{race_fields['winner']} was declared the winner of the race."
            p1_block = next((b for b in driver_blocks if b.get("finished") == "P1"), None)
            if p1_block:
                return f"{p1_block['driver']} won the race, finishing P1."
            p1_match = re.search(r"^P1\s+([A-Za-z\s]+)$", context, re.MULTILINE)
            if p1_match:
                return f"{p1_match.group(1).strip()} won the race, finishing P1."
            summary_match = re.search(r"([A-Za-z\s]+?)\s+won the race", context, re.IGNORECASE)
            if summary_match:
                return f"{summary_match.group(1).strip()} won the race."

        if "fastest lap" in q_lower and race_fields.get("fastest_lap"):
            ev = race_fields.get("event") or "race"
            return f"{race_fields['fastest_lap']} recorded the fastest lap in the {ev}."

        if any(k in q_lower for k in ["podium", "top 3", "top three"]) and race_fields.get("podium_lines"):
            ev = race_fields.get("event") or "race"
            return f"{ev} podium:\n" + "\n".join(race_fields["podium_lines"])

        # 5b. Round / metadata queries on race_report
        if re.search(r"\b(?:what\s+round|which\s+round|round\s+number|round\s+of)\b", q_lower):
            if race_fields.get("round") and race_fields.get("event"):
                season_str = f" of the {race_fields['season']} season" if race_fields.get("season") else ""
                return f"The {race_fields['event']} was Round {race_fields['round']}{season_str}."

        # 6 & 7. Named driver position / points queries (ONLY when grounded for asked driver(s))
        if any(k in q_lower for k in ["position", "where did", "finish", "point", "score"]):
            if matched_blocks:
                parts = []
                for b in matched_blocks:
                    pos = b["finished"] or "unknown"
                    pts = b["points"] if b["points"] is not None else "0.0"
                    parts.append(f"{b['driver']} finished {pos} and scored {pts} points.")
                return " ".join(parts)
            # Only use sole driver block when question does not introduce another ungrounded person
            if len(driver_blocks) == 1 and not driver_perf_match:
                b = driver_blocks[0]
                pos = b["finished"] or "unknown"
                pts = b["points"] if b["points"] is not None else "0.0"
                return f"{b['driver']} finished {pos} and scored {pts} points."

        # 8. Grounded race summary / recap / narrative queries
        summary_intents = [
            "summary", "recap", "overview", "tell me about", "describe",
            "what happened", "highlights", "highlight", "narrative", "story", "key moment",
        ]
        if any(k in q_lower for k in summary_intents) and (race_fields.get("summary") or race_fields.get("winner")):
            details: list[str] = []
            ev = race_fields.get("event")
            rnd = race_fields.get("round")
            yr = race_fields.get("season")
            if ev and rnd and yr:
                details.append(f"Round {rnd} of the {yr} Formula 1 season was the {ev}.")
            elif ev:
                details.append(f"{ev} summary:")
            if race_fields.get("winner"):
                details.append(f"Winner: {race_fields['winner']}.")
            if race_fields.get("podium_lines"):
                details.append("Podium: " + ", ".join(race_fields["podium_lines"]) + ".")
            if race_fields.get("fastest_lap"):
                details.append(f"Fastest Lap: {race_fields['fastest_lap']}.")
            if race_fields.get("summary"):
                details.append(race_fields["summary"])
            if details:
                return " ".join(details)

        # 9. Grounded explanatory / multi-fact / prose Race Summary answers
        stopwords = {
            "the", "and", "for", "with", "that", "this", "from", "what", "how",
            "does", "why", "explain", "tell", "about", "formula", "one", "2024",
            "which", "when", "where", "who", "was", "were", "did", "race", "grand", "prix",
        }
        q_keywords = [
            w for w in re.findall(r"[a-z0-9]+", q_lower)
            if len(w) >= 3 and w not in stopwords
        ]
        doc_chunks = [c.strip() for c in re.split(r"(?=^\[Source:)", context, flags=re.MULTILINE) if c.strip()]
        if not doc_chunks:
            doc_chunks = [context]

        best_lines: list[str] = []
        best_score = -1
        for chunk in doc_chunks:
            chunk_lower = chunk.lower()
            score = sum(1 for kw in q_keywords if kw in chunk_lower)
            if score > best_score:
                lines = [
                    ln.strip() for ln in chunk.splitlines()
                    if ln.strip() and not ln.strip().startswith("[Source:")
                ]
                best_score = score
                best_lines = lines

        if best_lines and q_keywords and best_score >= max(1, len(q_keywords) // 2):
            if race_fields.get("summary") and any(kw in race_fields["summary"].lower() for kw in q_keywords):
                return race_fields["summary"]
            return " ".join(best_lines[:12])

        # Fallback to standard refusal if retrieved context lacks grounded answer
        return refusal_msg
