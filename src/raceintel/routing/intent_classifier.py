"""
Intent Classification and Ambiguity Handling for RaceIntel.

Classifies natural-language Formula 1 queries into structured archetypes,
extracts and resolves entities using the database-driven EntityRegistry,
and cleanly detects ambiguous or incomplete queries requiring clarification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from raceintel.routing.entity_registry import EntityRegistry, normalize_text


class Intent(str, Enum):
    """Supported query intents in RaceIntel."""
    RACE_WINNER = "race_winner"
    DRIVER_STANDINGS_LEADER = "driver_standings_leader"
    CONSTRUCTOR_RACE_POINTS = "constructor_race_points"
    DRIVER_POINTS = "driver_points"
    DRIVER_POSITION = "driver_position"
    DRIVER_PERFORMANCE = "driver_performance"
    FASTEST_LAP = "fastest_lap"
    WEATHER = "weather"
    PODIUM = "podium"
    POINTS_SCORERS = "points_scorers"
    TEAM_PERFORMANCE = "team_performance"
    TEAM_COMPARISON = "team_comparison"
    MOST_POINTS_IN_TEAM = "most_points_in_team"
    DRIVER_RACE_COMPARISON = "driver_race_comparison"
    RACE_RETIREMENTS = "race_retirements"
    RACE_CLASSIFICATION = "race_classification"
    BIGGEST_MOVERS = "biggest_movers"
    TYRE_USAGE = "tyre_usage"
    DRIVER_CHAMPIONSHIP_POSITION = "driver_championship_position"
    DRIVER_CUMULATIVE_POINTS = "driver_cumulative_points"
    DRIVER_STANDINGS_COMPARISON = "driver_standings_comparison"
    DRIVER_STANDINGS_TABLE = "driver_standings_table"
    CONSTRUCTOR_STANDINGS_LEADER = "constructor_standings_leader"
    CONSTRUCTOR_STANDINGS_TABLE = "constructor_standings_table"
    CONSTRUCTOR_STANDINGS_COMPARISON = "constructor_standings_comparison"
    DRIVER_SPRINT_POINTS = "driver_sprint_points"
    CONSTRUCTOR_SPRINT_POINTS = "constructor_sprint_points"
    MOST_SPRINT_POINTS = "most_sprint_points"
    AMBIGUOUS = "ambiguous"
    GENERAL_RAG = "general_rag"



@dataclass
class IntentResult:
    """Result of intent classification and entity resolution."""
    intent: Intent
    confidence: float
    entities: dict = field(default_factory=dict)
    is_ambiguous: bool = False
    clarification_message: str | None = None


class IntentClassifier:
    """
    Classifies user queries into structured F1 intents and detects ambiguities.
    Uses the database-driven EntityRegistry for grounded entity resolution.
    """

    def __init__(self, registry: EntityRegistry | None = None):
        self.registry = registry if registry is not None else EntityRegistry()

    def extract_entities(self, question: str) -> dict:
        """
        Extract race event, driver, constructor, and season from the question.
        Returns a dictionary of resolved entity records.
        """
        entities = {
            "race_name": None,
            "event_name": None,
            "event_id": None,
            "circuit_name": None,
            "country_name": None,
            "is_event_ambiguous": False,
            "event_candidates": [],
            "driver_name": None,
            "driver_id": None,
            "driver_code": None,
            "is_driver_ambiguous": False,
            "driver_candidates": [],
            "constructor_name": None,
            "constructor_id": None,
            "is_constructor_ambiguous": False,
            "constructor_candidates": [],
            "season": 2024,
            "season_explicit": False,
            "session_type": "Race",
        }

        norm_q = normalize_text(question)
        if re.search(r"\bsprints?\b", norm_q):
            entities["session_type"] = "Sprint"

        norm_q_event = re.sub(r"\bsprints?\b", "", norm_q).strip()
        norm_q_event = re.sub(r"\s+", " ", norm_q_event)

        # 1. Season extraction (e.g. 2024, 2020)
        season_match = re.search(r"\b(19\d\d|20\d\d)\b", question)
        if season_match:
            entities["season"] = int(season_match.group(1))
            entities["season_explicit"] = True

        # 2. Event / Race extraction (Priority: exact event -> event alias -> circuit/venue -> country)
        # Check exact events, explicit event aliases, and circuit aliases first so that
        # e.g. "US GP" or "at COTA in the United States" never gets treated as ambiguous country text.
        matched_events: list[str] = []
        specific_stage_maps = (
            self.registry._exact_event_map,
            self.registry._event_alias_stage_map,
            self.registry._circuit_alias_map,
        )
        occupied_spans: list[tuple[int, int]] = []
        for stage_map in specific_stage_maps:
            for key in sorted(stage_map.keys(), key=len, reverse=True):
                if not key:
                    continue
                for q_target in (norm_q, norm_q_event):
                    for m in re.finditer(rf"\b{re.escape(key)}\b", q_target):
                        start, end = m.span()
                        if any(not (end <= s or start >= e) for s, e in occupied_spans):
                            continue
                        occupied_spans.append((start, end))
                        for ev in stage_map[key]:
                            ev_name = ev["event_name"]
                            if ev_name not in matched_events:
                                matched_events.append(ev_name)
            if matched_events:
                break


        # Only check ambiguous country references when no specific event, event alias, or circuit matched
        if not matched_events:
            active_season = (
                entities["season"]
                if self.registry.is_season_supported(entities["season"])
                else None
            )
            ambiguous_countries = self.registry.get_ambiguous_country_aliases(season=active_season)
            for country_alias in sorted(ambiguous_countries.keys(), key=len, reverse=True):
                if country_alias == "us":
                    # Avoid false triggers on English pronoun 'us' ("tell us who won")
                    if not re.search(r"\b(?:U\.?S\.?|US)\b", question) and not re.search(
                        r"\b(?:in|at|for|from)\s+the\s+us\b", norm_q
                    ):
                        continue
                elif re.search(rf"\b{re.escape(country_alias)}\b", norm_q):
                    entities["is_event_ambiguous"] = True
                    entities["event_candidates"] = ambiguous_countries[country_alias]
                    break
                else:
                    continue
                # If country_alias == "us" passed the uppercase/the-US guard:
                entities["is_event_ambiguous"] = True
                entities["event_candidates"] = ambiguous_countries[country_alias]
                break

        # Fallback: check remaining unambiguous race mappings (e.g., single-race country fallback)
        if not entities["is_event_ambiguous"] and not matched_events:
            races_map = self.registry.get_races_map()
            sorted_race_keys = sorted(races_map.keys(), key=len, reverse=True)
            for key in sorted_race_keys:
                if key == "us":
                    continue
                pattern = rf"\b{re.escape(key)}\b"
                if re.search(pattern, norm_q):
                    canonical = races_map[key]
                    if canonical not in matched_events:
                        matched_events.append(canonical)

        target_season = (
            entities["season"]
            if entities.get("season_explicit")
            else None
        )
        if not entities["is_event_ambiguous"] and len(matched_events) == 1:
            canonical = matched_events[0]
            res = self.registry.resolve_event(canonical, season=target_season)
            if res.matched:
                entities["race_name"] = res.event_name
                entities["event_name"] = res.event_name
                entities["event_id"] = res.event_id
                entities["circuit_name"] = res.circuit_name
                entities["country_name"] = res.country_name
            else:
                entities["race_name"] = canonical
                entities["event_name"] = canonical
        elif not entities["is_event_ambiguous"] and len(matched_events) > 1:
            # Check if all matches resolve to a single event (e.g., across seasons or circuit+event)
            unique_ids = set()
            resolved_objs = []
            for ev_name in matched_events:
                r = self.registry.resolve_event(ev_name, season=target_season)
                if r.matched:
                    unique_ids.add(r.event_id)
                    resolved_objs.append(r)
            if len(unique_ids) == 1:
                r = resolved_objs[0]
                entities["race_name"] = r.event_name
                entities["event_name"] = r.event_name
                entities["event_id"] = r.event_id
                entities["circuit_name"] = r.circuit_name
                entities["country_name"] = r.country_name
            else:
                entities["is_event_ambiguous"] = True
                entities["event_candidates"] = matched_events

        # 3. Driver extraction
        ambiguous_short_codes = {"nor", "per", "law", "gas", "bot", "str", "had"}
        drivers_map = self.registry.get_drivers_map()
        sorted_driver_keys = sorted(drivers_map.keys(), key=len, reverse=True)
        matched_drivers = []
        for key in sorted_driver_keys:
            # Require minimum 3 characters to avoid trivial collisions
            if len(key) < 3:
                continue
            if key in ambiguous_short_codes:
                matched_key = bool(re.search(rf"\b{re.escape(key.upper())}\b", question))
            else:
                matched_key = bool(re.search(rf"\b{re.escape(key)}\b", norm_q))
            if matched_key:
                canonical = drivers_map[key]
                if canonical not in matched_drivers:
                    matched_drivers.append(canonical)

        entities["all_drivers"] = matched_drivers
        driver_records = []
        for d_name in matched_drivers:
            dr = self.registry.resolve_driver(d_name)
            if dr.matched:
                driver_records.append({
                    "driver_id": dr.driver_id,
                    "driver_name": dr.driver_full_name,
                    "driver_code": dr.driver_code,
                })
        entities["driver_records"] = driver_records

        if len(matched_drivers) == 1:
            canonical = matched_drivers[0]
            d_res = self.registry.resolve_driver(canonical)
            if d_res.matched:
                entities["driver_name"] = d_res.driver_full_name
                entities["driver_id"] = d_res.driver_id
                entities["driver_code"] = d_res.driver_code
            else:
                entities["driver_name"] = canonical
        elif len(matched_drivers) > 1:
            entities["is_driver_ambiguous"] = True
            entities["driver_candidates"] = matched_drivers

        # 4. Constructor / Team extraction
        teams_map = self.registry.get_teams_map()
        sorted_team_keys = sorted(teams_map.keys(), key=len, reverse=True)
        matched_teams = []
        for key in sorted_team_keys:
            pattern = rf"\b{re.escape(key)}\b"
            if re.search(pattern, norm_q):
                canonical = teams_map[key]
                if canonical not in matched_teams:
                    matched_teams.append(canonical)

        entities["all_constructors"] = matched_teams
        constructor_records = []
        for c_name in matched_teams:
            cr = self.registry.resolve_constructor(c_name)
            if cr.matched:
                constructor_records.append({
                    "constructor_id": cr.constructor_id,
                    "constructor_name": cr.constructor_name,
                })
        entities["constructor_records"] = constructor_records

        if len(matched_teams) == 1:
            canonical = matched_teams[0]
            c_res = self.registry.resolve_constructor(canonical)
            if c_res.matched:
                entities["constructor_name"] = c_res.constructor_name
                entities["constructor_id"] = c_res.constructor_id
            else:
                entities["constructor_name"] = canonical
        elif len(matched_teams) > 1:
            entities["is_constructor_ambiguous"] = True
            entities["constructor_candidates"] = matched_teams

        return entities

    def classify(self, question: str) -> IntentResult:
        """
        Classify question into an IntentResult with resolved entities and ambiguity guards.
        """
        q_raw = question.strip()
        q_norm = normalize_text(question)
        entities = self.extract_entities(question)

        race_name = entities.get("race_name")
        driver_name = entities.get("driver_name")
        constructor_name = entities.get("constructor_name")

        # --------------------------------------------------------
        # 0. AMBIGUITY CHECKS: Multiple entities or unresolved host country
        # --------------------------------------------------------
        if entities.get("is_event_ambiguous"):
            candidates_str = ", ".join(entities["event_candidates"])
            return IntentResult(
                intent=Intent.AMBIGUOUS,
                confidence=1.0,
                entities=entities,
                is_ambiguous=True,
                clarification_message=(
                    f"The question is ambiguous because multiple Grand Prix events match: "
                    f"{candidates_str}. Please specify which Grand Prix you are referring to."
                ),
            )

        # --------------------------------------------------------
        # 0.05 CONCEPTUAL / DEFINITIONAL QUESTION GUARD
        # --------------------------------------------------------
        # Keep pure conceptual F1 questions out of event-bound ambiguity traps
        if not race_name and not driver_name and not constructor_name:
            is_conceptual = bool(
                re.search(
                    r"\b(?:mean|meaning|definition|define|explain|purpose of|role of|difference between|how does .+ work|how do .+ work|why do teams|why do drivers|what is (?:a|an) )\b",
                    q_norm,
                )
            )
            if is_conceptual:
                return IntentResult(
                    intent=Intent.GENERAL_RAG,
                    confidence=0.85,
                    entities=entities,
                )

        # --------------------------------------------------------
        # 0.08 SPRINT INTENTS
        # --------------------------------------------------------
        has_sprint_kw = bool(re.search(r"\bsprints?\b", q_norm))

        # A. MOST SPRINT POINTS: "Which driver scored the most Sprint points in 2024?"
        if has_sprint_kw and re.search(r"\b(?:most|highest|maximum|top)\s+(?:sprint\s+points|points\s+in\s+sprints?)\b|\b(?:scored|won|earned|had)\s+the\s+most\s+sprint\s+points\b", q_norm):
            target = "constructor" if (re.search(r"\b(?:team|constructor)\b", q_norm) or constructor_name) else "driver"
            entities["target"] = target
            return IntentResult(
                intent=Intent.MOST_SPRINT_POINTS,
                confidence=0.98,
                entities=entities,
            )

        # B. DRIVER SEASON SPRINT POINTS: "How many Sprint points did Max Verstappen score in 2024?" (when no specific race event is named)
        if has_sprint_kw and driver_name and not race_name and re.search(r"\bpoints?\b", q_norm):
            return IntentResult(
                intent=Intent.DRIVER_SPRINT_POINTS,
                confidence=0.98,
                entities=entities,
            )

        # C. CONSTRUCTOR SEASON SPRINT POINTS: "How many points did McLaren earn from Sprints in 2024?" (when no specific race event is named)
        if has_sprint_kw and constructor_name and not race_name and re.search(r"\bpoints?\b", q_norm):
            return IntentResult(
                intent=Intent.CONSTRUCTOR_SPRINT_POINTS,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.1 RETIREMENTS / DNFS INTENT
        # --------------------------------------------------------
        retirements_patterns = [
            r"\b(?:who|which\s+(?:drivers?|cars?|competitors?)|what\s+(?:drivers?|cars?))\s+(?:retired|crashed\s+out|failed\s+to\s+finish|did\s+not\s+finish|didn\'t\s+finish|dropped\s+out|bowed\s+out)\b",
            r"\b(?:drivers?|cars?)\s+(?:who|that)\s+(?:retired|crashed\s+out|failed\s+to\s+finish|did\s+not\s+finish|didn\'t\s+finish|dropped\s+out|bowed\s+out)\b",
            r"\b(?:retirements?|did\s+not\s+finish|didn\'t\s+finish|failed\s+to\s+finish|dnfs?|forced\s+to\s+retire|retired\s+from\s+the\s+race|listed\s+as\s+(?:dnf|retired)|non[- ]?finishers?)\b",
            r"\bdid\s+not\s+(?:see|reach|make)\s+the\s+(?:chequered|checkered)\s+flag\b",
        ]
        is_retirements = any(re.search(p, q_norm) for p in retirements_patterns)
        if is_retirements:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            return IntentResult(
                intent=Intent.RACE_RETIREMENTS,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.2 RACE CLASSIFICATION INTENT
        # --------------------------------------------------------
        classification_patterns = [
            r"\b(?:full|complete|final|official)\s+(?:race\s+)?(?:classification|results?)\b",
            r"\brace\s+classification\b",
            r"\bclassification\s+(?:of|for)\s+the\b",
            r"\b(?:finishing\s+order|order\s+of\s+finish)\b",
            r"\bwhere\s+(?:everyone|every\s+driver|all\s+drivers|the\s+field)\s+finished\b",
        ]
        is_classification = (
            any(re.search(p, q_norm) for p in classification_patterns)
            and not re.search(r"\b(?:driver|drivers\'?|constructor|constructors\'?|team)\s+standings\b", q_norm)
        )
        if is_classification:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            return IntentResult(
                intent=Intent.RACE_CLASSIFICATION,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.3 BIGGEST MOVERS INTENT
        # --------------------------------------------------------
        movers_patterns = [
            r"\b(?:biggest\s+(?:movers?|gainers?)|largest\s+(?:position|place)\s+gain)\b",
            r"\b(?:gained|made\s+up|improved|climbed|moved\s+up|rose)\s+(?:the\s+)?most\s+(?:positions?|places?|spots?)\b",
            r"\bmost\s+(?:positions?|places?|spots?)\s+(?:gained|made\s+up|improved|climbed)\b",
            r"\b(?:gained|made\s+up|climbed)\s+more\s+(?:positions?|places?|spots?)\s+than\b",
            r"\bmoved\s+up\s+the\s+most\b",
        ]
        is_movers = any(re.search(p, q_norm) for p in movers_patterns)
        if is_movers:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            return IntentResult(
                intent=Intent.BIGGEST_MOVERS,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.4 TYRE USAGE INTENT
        # --------------------------------------------------------
        tyre_patterns = [
            r"\b(?:tyre|tire)\s+compounds?\b",
            r"\bcompounds?\s+(?:were\s+)?(?:used|run|fitted|utilized|utilised|appeared|chosen)\b",
            r"\b(?:what|which)\s+(?:compounds?|tyres?|tires?)\b",
            r"\b(?:tyres?|tires?)\s+(?:were\s+)?(?:used|run|fitted|chosen)\b",
            r"\b(?:tyre|tire)\s+strategy\b",
            r"\bcompounds?\s+did\b",
            r"\bdid\s+.+?\s+(?:use|run|fit)\s+.*?(?:tyres?|tires?|compounds?)\b",
        ]
        is_tyre = any(re.search(p, q_norm) for p in tyre_patterns)
        if is_tyre and not re.search(r"\bpit\s+stop\s+(?:duration|time|length|speed|seconds)\b", q_norm):
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix you are referring to.",
                )
            return IntentResult(
                intent=Intent.TYRE_USAGE,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.5 CONSTRUCTOR STANDINGS LEADER INTENT
        # --------------------------------------------------------
        f1_mod = r"(?:(?:formula\s+(?:1|one)|f1|world)\s+)?"
        constr_scope = rf"{f1_mod}(?:constructors?\'?\s+(?:world\s+)?championship|constructor\s+standings|constructors?\s+standings|team\s+standings)"
        constructor_lead_patterns = [
            rf"\b(?:lead(?:ing|s)?|led|topped|sat\s+atop|head(?:ed|ing|s)?)\s+the\s+{constr_scope}\b",
            rf"\b{constr_scope}\s+lead(?:er)?\b",
            rf"\b(?:who|which\s+(?:team|constructor))\s+(?:was|is)\s+(?:leading|atop|first\s+in|on\s+top\s+of|top\s+of)\s+the\s+{constr_scope}\b",
            rf"\b(?:which|what)\s+(?:team|constructor)\s+(?:led|topped|held\s+(?:first|p1|the\s+lead|top\s+spot)\s+in)\s+the\s+{constr_scope}\b",
        ]
        is_constr_lead = any(re.search(p, q_norm) for p in constructor_lead_patterns)
        if is_constr_lead:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the standings.",
                )
            return IntentResult(
                intent=Intent.CONSTRUCTOR_STANDINGS_LEADER,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.6 STANDINGS & SINGLE-RACE COMPARISON INTENTS
        # --------------------------------------------------------
        standings_comp_cues = [
            r"\b(?:championship|standings|championship\s+total|points\s+total|points\s+tally|total\s+points|overall\s+points|better\s+championship)\b",
        ]
        is_standings_ctx = any(re.search(p, q_norm) for p in standings_comp_cues)
        comparison_patterns = [
            r"\bcompare\b",
            r"\bbetween\b",
            r"\bwho\s+(?:was|is|finished|placed|ranked)\s+(?:ahead|higher|better|above)\b",
            r"\bwho\s+had\s+(?:more|higher|greater|the\s+better)\b",
            r"\b(?:stronger|better)\s+(?:classification|finish|result|championship)\b",
            r"\b(?:ahead|higher)\s+in\s+the\s+(?:championship|standings)\b",
            r"\b(?:finished|placed|came)\s+(?:ahead\s+of|higher\s+than)\b",
            r"\b(?:outperformed|outscored)\b",
            r"\bmore\s+(?:championship\s+)?points\b",
            r"\bhigher\s+finishing\s+position\b",
        ]
        is_comparison = any(re.search(p, q_norm) for p in comparison_patterns)
        if is_comparison:
            constr_records = entities.get("constructor_records", [])
            driver_records = entities.get("driver_records", [])
            if len(constr_records) >= 2 or (is_standings_ctx and ("constructor" in q_norm or "team" in q_norm) and len(driver_records) < 2):
                if len(constr_records) >= 2:
                    entities["is_constructor_ambiguous"] = False
                    entities["constructor_1"] = constr_records[0]
                    entities["constructor_2"] = constr_records[1]
                if not race_name:
                    return IntentResult(
                        intent=Intent.AMBIGUOUS,
                        confidence=0.95,
                        entities=entities,
                        is_ambiguous=True,
                        clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the comparison.",
                    )
                return IntentResult(
                    intent=Intent.CONSTRUCTOR_STANDINGS_COMPARISON,
                    confidence=0.98,
                    entities=entities,
                )

            if len(driver_records) >= 2:
                entities["is_driver_ambiguous"] = False
                entities["driver_1"] = driver_records[0]
                entities["driver_2"] = driver_records[1]
                if is_standings_ctx:
                    if not race_name:
                        return IntentResult(
                            intent=Intent.AMBIGUOUS,
                            confidence=0.95,
                            entities=entities,
                            is_ambiguous=True,
                            clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the comparison.",
                        )
                    return IntentResult(
                        intent=Intent.DRIVER_STANDINGS_COMPARISON,
                        confidence=0.98,
                        entities=entities,
                    )
                if not race_name:
                    return IntentResult(
                        intent=Intent.AMBIGUOUS,
                        confidence=0.95,
                        entities=entities,
                        is_ambiguous=True,
                        clarification_message="The question is ambiguous. Please specify which Grand Prix you are referring to.",
                    )
                return IntentResult(
                    intent=Intent.DRIVER_RACE_COMPARISON,
                    confidence=0.98,
                    entities=entities,
                )

            if is_standings_ctx and ("driver" in q_norm):
                if not race_name:
                    return IntentResult(
                        intent=Intent.AMBIGUOUS,
                        confidence=0.95,
                        entities=entities,
                        is_ambiguous=True,
                        clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the comparison.",
                    )
                return IntentResult(
                    intent=Intent.DRIVER_STANDINGS_COMPARISON,
                    confidence=0.98,
                    entities=entities,
                )

        # --------------------------------------------------------
        # 0.7 DRIVER CUMULATIVE CHAMPIONSHIP POINTS INTENT
        # --------------------------------------------------------
        driver_scope = rf"{f1_mod}(?:drivers?\'?\s+(?:world\s+)?championship|driver\s+standings|drivers?\s+standings)"
        cum_pts_patterns = [
            rf"\b(?:championship\s+points|cumulative\s+points|total\s+(?:championship\s+)?points|points\s+in\s+the\s+(?:drivers?\'?\s+)?championship|points\s+in\s+the\s+standings|points\s+tally|points\s+total)\b",
            r"\bpoints\s+(?:did\s+[a-z\s]+\s+have|had)\s+(?:after|following)\b",
        ]
        is_cum_pts = any(re.search(p, q_norm) for p in cum_pts_patterns)
        has_after_standings = bool(re.search(r"\b(?:after|following|post|standings|cumulative)\b", q_norm))
        if not has_after_standings and (
            re.search(r"\b(?:score(?:d)?|tall(?:y|ied)|earn(?:ed)?|collect(?:ed)?)\b", q_norm)
            or (constructor_name and not driver_name)
        ):
            is_cum_pts = False

        if is_cum_pts:
            if re.search(r"\b(?:he|she|they|a driver|this driver)\b", q_norm) or re.search(r"\bthe driver\b(?!\s+standings)", q_norm):
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which driver you are referring to.",
                )
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the standings.",
                )
            if not driver_name:
                return IntentResult(
                    intent=Intent.GENERAL_RAG,
                    confidence=0.5,
                    entities=entities,
                )
            return IntentResult(
                intent=Intent.DRIVER_CUMULATIVE_POINTS,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.8 DRIVER CHAMPIONSHIP POSITION INTENT
        # --------------------------------------------------------
        driver_champ_pos_patterns = [
            rf"\b(?:championship\s+(?:position|standing|rank(?:ing)?)|position\s+in\s+the\s+(?:{driver_scope}|championship|standings))\b",
            rf"\b(?:where|what\s+position|what\s+rank)\s+(?:was|sat|ranked)\s+.+?\s+in\s+the\s+(?:{driver_scope}|championship|standings)\b",
            r"\b(?:championship|standings)\s+(?:standing|position|rank(?:ing)?)\s+(?:after|following)\b",
            rf"\b(?:place|ranked)\s+in\s+the\s+(?:{driver_scope}|championship|standings)\s+(?:after|following)\b",
        ]
        is_driver_champ_pos = any(re.search(p, q_norm) for p in driver_champ_pos_patterns)
        if is_driver_champ_pos:
            if re.search(r"\b(?:he|she|they|a driver|this driver)\b", q_norm) or re.search(r"\bthe driver\b(?!\s+standings)", q_norm):
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which driver you are referring to.",
                )
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the standings.",
                )
            if not driver_name:
                return IntentResult(
                    intent=Intent.GENERAL_RAG,
                    confidence=0.5,
                    entities=entities,
                )
            return IntentResult(
                intent=Intent.DRIVER_CHAMPIONSHIP_POSITION,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 1. STANDINGS LEADER INTENT (Cumulative after event)
        # --------------------------------------------------------
        standings_patterns = [
            rf"\b(?:who|which\s+driver)\s+(?:was|is)\s+(?:leading|atop|first\s+in|on\s+top\s+of|top\s+of)\s+the\s+(?:{driver_scope}|championship|standings)\b",
            rf"\b(?:who|which\s+driver)\s+(?:led|topped|sat\s+atop|held\s+(?:first|p1|the\s+lead|top\s+spot)\s+in)\s+the\s+(?:{driver_scope}|championship|standings)\b",
            rf"\b(?:lead(?:ing|s)?|led|topped|head(?:ing|s|ed)?)\s+the\s+(?:{driver_scope}|championship|standings)\b",
            r"\bchampionship\s+lead\s+(?:after|following|post)\b",
            r"\b(?:championship|standings)\s+leader\s+(?:after|following|post)\b",
            r"\bhad\s+the\s+championship\s+lead\b",
        ]
        is_standings = any(re.search(p, q_norm) for p in standings_patterns)
        if is_standings:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the standings.",
                )
            return IntentResult(
                intent=Intent.DRIVER_STANDINGS_LEADER,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.9 CONSTRUCTOR STANDINGS TABLE INTENT
        # --------------------------------------------------------
        constr_table_patterns = [
            rf"\b{f1_mod}(?:constructor|constructors\'?|team)\s+(?:championship\s+)?standings\b",
        ]
        is_constr_table = any(re.search(p, q_norm) for p in constr_table_patterns)
        if is_constr_table and not constructor_name:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the standings.",
                )
            return IntentResult(
                intent=Intent.CONSTRUCTOR_STANDINGS_TABLE,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 0.10 DRIVER STANDINGS TABLE INTENT
        # --------------------------------------------------------
        driver_table_patterns = [
            rf"\b{f1_mod}(?:driver|drivers\'?)\s+(?:championship\s+)?standings\b",
        ]
        is_driver_table = any(re.search(p, q_norm) for p in driver_table_patterns)
        if is_driver_table and not driver_name and not any(k in q_norm for k in ["lead", "leads", "leading", "leader", "head", "heading", "top", "topped", "atop"]):
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify after which Grand Prix you would like the standings.",
                )
            return IntentResult(
                intent=Intent.DRIVER_STANDINGS_TABLE,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 2. CONSTRUCTOR RACE POINTS INTENT (Single race aggregation)
        # --------------------------------------------------------
        constructor_points_patterns = [
            r"\b(?:which|what)\s+(?:team|constructor)\s+(?:collected|scored|got|earned|took|amassed|claimed|tallied)\s+(?:the\s+)?(?:highest|most|maximum|greatest)\s+(?:number\s+of\s+)?points\b",
            r"\b(?:which|what)\s+(?:team|constructor)\s+(?:scored|earned|collected|took)\s+the\s+most\s+points\b",
            r"\b(?:team|constructor)\s+(?:with|scoring|collecting|earning)\s+the\s+most\s+points\b",
            r"\bconstructor\s+points\s+(?:in|at|for)\b",
        ]
        is_constructor_pts = any(re.search(p, q_norm) for p in constructor_points_patterns)
        if not is_constructor_pts and constructor_name and not driver_name and re.search(r"\bpoints\b", q_norm) and not re.search(r"\b(?:most|more|outscored|higher)\s+points\b", q_norm):
            if not has_after_standings:
                is_constructor_pts = True
        if is_constructor_pts:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix you are referring to.",
                )
            return IntentResult(
                intent=Intent.CONSTRUCTOR_RACE_POINTS,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 3. FASTEST LAP INTENT
        # --------------------------------------------------------
        fastest_lap_patterns = [
            r"\b(?:who|which\s+driver)\s+(?:set|clocked|drove|got|recorded|achieved|had|posted|put\s+in|laid\s+down)\s+(?:the\s+)?(?:fastest|quickest|best)\s+lap\b",
            r"\b(?:fastest|quickest|best)\s+lap(?:\s+(?:time|holder|of|in|at|during))?\b",
            r"\bbonus\s+point\s+for\s+(?:the\s+)?fastest\s+lap\b",
        ]
        is_fastest_lap = any(re.search(p, q_norm) for p in fastest_lap_patterns)
        if is_fastest_lap and not re.search(r"\bpit\s+stop\b", q_norm):
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            return IntentResult(
                intent=Intent.FASTEST_LAP,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 4. WEATHER INTENT
        # --------------------------------------------------------
        weather_patterns = [
            r"\b(?:did\s+it\s+rain|rain|rainfall|rained|raining|rainy)\b",
            r"\b(?:was\s+(?:the\s+track|the\s+race|it)\s+wet|track\s+wet|wet\s+track|wet\s+race)\b",
            r"\b(?:dry\s+or\s+wet|wet\s+or\s+dry)\b",
            r"\b(?:weather|temperature|humidity|wind(?:\s+speed)?|atmospheric\s+pressure)\b",
            r"\b(?:track|air|ambient|surface|asphalt)\s+temp(?:erature)?\b",
            r"\b(?:weather|track|ambient|atmospheric)\s+conditions\b",
            r"\bconditions\b",
        ]
        is_weather = any(re.search(p, q_norm) for p in weather_patterns)
        if is_weather:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix you are asking about.",
                )
            return IntentResult(
                intent=Intent.WEATHER,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 5. PODIUM INTENT
        # --------------------------------------------------------
        podium_patterns = [
            r"\b(?:who|which\s+drivers?)\s+(?:finished|placed|ended\s+up|stood)?\s*(?:on\s+the\s+podium|in\s+the\s+top\s+(?:three|3))\b",
            r"\bpodium\s+(?:finishers?|results?|trio|places?)\b",
            r"\btop[- ]?(?:three|3)\s+(?:finishers?|drivers?|places?|positions?)\b",
            r"\b(?:steps?\s+of\s+the\s+podium|on\s+the\s+podium|podium|rostrum)\b",
        ]
        is_podium = any(re.search(p, q_norm) for p in podium_patterns)
        if is_podium:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            return IntentResult(
                intent=Intent.PODIUM,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 6. RACE WINNER INTENT
        # --------------------------------------------------------
        winner_patterns = [
            r"\b(?:who|which\s+(?:[a-z0-9]+\s+){0,2}driver)\s+(?:won|claimed\s+victory|took\s+victory|secured\s+victory|sealed\s+victory|took\s+the\s+win|secured\s+the\s+win|captured\s+the\s+win|took\s+the\s+(?:chequered|checkered)\s+flag|was\s+declared\s+(?:the\s+)?winner|finished\s+first|came\s+first|finished\s+in\s+(?:1st|first)\s+place|took\s+(?:1st|first)\s+place|took\s+p1|stood\s+on\s+the\s+top\s+step|triumphed|emerged\s+victorious|was\s+victorious)\b",
            r"\b(?:winner|victor)\s+of\b",
            r"\bwon\s+the\b",
            r"\bdid\s+(?:[a-z]+(?:\s+[a-z]+)?)\s+win\b",
            r"\bwho\s+(?:was|is)\s+the\s+(?:race\s+)?(?:winner|victor)\b",
            r"\bwho\s+won\b",
        ]
        is_winner = any(re.search(p, q_norm) for p in winner_patterns)
        if is_winner:
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            return IntentResult(
                intent=Intent.RACE_WINNER,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 7. DRIVER POINTS INTENT
        # --------------------------------------------------------
        points_patterns = [
            r"\b(?:how\s+many|how\s+much|what)\s+(?:championship\s+)?points\s+(?:did|has)\b",
            r"\bpoints\s+did\s+(?:[a-z]+(?:\s+[a-z]+)?)\s+(?:score|take\s+away|collect|earn|get|pick\s+up|tally)\b",
            r"\bpoints\s+(?:scored|earned|collected|tallied)\s+by\b",
            r"\b(?:points\s+tally|points\s+haul)\s+(?:of|for)\b",
            r"\bdid\s+.+?\s+score\s+(?:any\s+)?points\b",
        ]
        is_points = any(re.search(p, q_norm) for p in points_patterns)
        if is_points:
            if re.search(r"\b(?:he|she|they|the driver|a driver|this driver)\b", q_norm):
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which driver you are referring to.",
                )
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            if constructor_name and not driver_name:
                return IntentResult(
                    intent=Intent.CONSTRUCTOR_RACE_POINTS,
                    confidence=0.98,
                    entities=entities,
                )
            driver_records = entities.get("driver_records", [])
            if len(driver_records) >= 2:
                entities["is_driver_ambiguous"] = False
                entities["driver_1"] = driver_records[0]
                entities["driver_2"] = driver_records[1]
                return IntentResult(
                    intent=Intent.DRIVER_RACE_COMPARISON,
                    confidence=0.95,
                    entities=entities,
                )
            if not driver_name:
                return IntentResult(
                    intent=Intent.GENERAL_RAG,
                    confidence=0.5,
                    entities=entities,
                )
            return IntentResult(
                intent=Intent.DRIVER_POINTS,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 8. DRIVER POSITION INTENT
        # --------------------------------------------------------
        position_patterns = [
            r"\b(?:what\s+position|which\s+position|what\s+place|which\s+place|where)\s+did\s+.+?\s+(?:finish|place|end\s+up|classify|come\s+in)\b",
            r"\bwhat\s+was\s+.+?\'?s\s+finish(?:ing)?\s+(?:position|place)\b",
            r"\bfinishing\s+(?:position|place)\s+(?:of|for)\b",
        ]
        is_position = any(re.search(p, q_norm) for p in position_patterns)
        if is_position:
            if re.search(r"\b(?:he|she|they|the driver|a driver|this driver)\b", q_norm):
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which driver you are referring to.",
                )
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            driver_records = entities.get("driver_records", [])
            if len(driver_records) >= 2:
                entities["is_driver_ambiguous"] = False
                entities["driver_1"] = driver_records[0]
                entities["driver_2"] = driver_records[1]
                return IntentResult(
                    intent=Intent.DRIVER_RACE_COMPARISON,
                    confidence=0.95,
                    entities=entities,
                )
            if not driver_name:
                return IntentResult(
                    intent=Intent.GENERAL_RAG,
                    confidence=0.5,
                    entities=entities,
                )
            return IntentResult(
                intent=Intent.DRIVER_POSITION,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 9. DRIVER PERFORMANCE INTENT
        # --------------------------------------------------------
        perf_patterns = [
            r"\bhow\s+did\s+.+?\s+(?:perform|do|fare|get\s+on|finish)\b",
            r"\bwhat\s+was\s+.+?\'?s\s+(?:result|performance|outcome)\b",
        ]
        is_perf = any(re.search(p, q_norm) for p in perf_patterns)
        if is_perf and not constructor_name:
            if re.search(r"\b(?:the team|a team|this team)\b", q_norm):
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which team you are referring to.",
                )
            if re.search(r"\b(?:he|she|they|the driver|a driver|this driver)\b", q_norm):
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which driver you are referring to.",
                )
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix or race you are referring to.",
                )
            driver_records = entities.get("driver_records", [])
            if len(driver_records) >= 2:
                entities["is_driver_ambiguous"] = False
                entities["driver_1"] = driver_records[0]
                entities["driver_2"] = driver_records[1]
                return IntentResult(
                    intent=Intent.DRIVER_RACE_COMPARISON,
                    confidence=0.95,
                    entities=entities,
                )
            if not driver_name:
                return IntentResult(
                    intent=Intent.GENERAL_RAG,
                    confidence=0.5,
                    entities=entities,
                )
            return IntentResult(
                intent=Intent.DRIVER_PERFORMANCE,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 10. TEAM COMPARISON / MOST POINTS IN TEAM / TEAM PERFORMANCE
        # --------------------------------------------------------
        team_comp_patterns = [
            r"\b(?:finished|placed|classified)\s+(?:higher|ahead|better)\b",
            r"\b(?:higher|stronger|better)\s+(?:finishing\s+position|classification|finish|result)\b",
            r"\b(?:outperformed|beat\s+(?:their|his)\s+teammate|top\s+driver\s+for)\b",
        ]
        if constructor_name and any(re.search(p, q_norm) for p in team_comp_patterns):
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix you are referring to.",
                )
            return IntentResult(
                intent=Intent.TEAM_COMPARISON,
                confidence=0.98,
                entities=entities,
            )

        if constructor_name and re.search(r"\b(?:most\s+points|more\s+points|outscored|higher\s+points|scored\s+the\s+most\s+points)\b", q_norm):
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix you are referring to.",
                )
            return IntentResult(
                intent=Intent.MOST_POINTS_IN_TEAM,
                confidence=0.98,
                entities=entities,
            )

        if constructor_name and not driver_name and (
            re.search(r"\b(?:result|results|perform(?:ance|ed)?|fare(?:d)?|finish(?:ed)?)\b", q_norm)
            or re.search(r"\bhow\s+did\s+.+?\s+do\b", q_norm)
        ):
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix you are referring to.",
                )
            return IntentResult(
                intent=Intent.TEAM_PERFORMANCE,
                confidence=0.98,
                entities=entities,
            )

        if not constructor_name and re.search(r"\b(?:the team|a team|this team)\b", q_norm) and (
            re.search(r"\b(?:result|results|perform|fare)\b", q_norm)
            or re.search(r"\bhow\s+did\s+.+?\s+do\b", q_norm)
        ):
            return IntentResult(
                intent=Intent.AMBIGUOUS,
                confidence=0.95,
                entities=entities,
                is_ambiguous=True,
                clarification_message="The question is ambiguous. Please specify which team you are referring to.",
            )

        # --------------------------------------------------------
        # 11. POINTS SCORERS INTENT
        # --------------------------------------------------------
        points_scorers_patterns = [
            r"\b(?:who|which\s+drivers?|what\s+drivers?|all\s+drivers\s+who)\s+(?:scored|earned|collected|picked\s+up|finished\s+in(?:\s+the)?)\s+(?:any\s+)?points\b",
            r"\bpoints[- ]?scor(?:ers?|ing\s+drivers?)\b",
            r"\b(?:top[- ]?(?:10|ten)\s+finishers?|finished\s+in\s+the\s+top\s+(?:10|ten))\b",
        ]
        if any(re.search(p, q_norm) for p in points_scorers_patterns):
            if not race_name:
                return IntentResult(
                    intent=Intent.AMBIGUOUS,
                    confidence=0.95,
                    entities=entities,
                    is_ambiguous=True,
                    clarification_message="The question is ambiguous. Please specify which Grand Prix you are referring to.",
                )
            return IntentResult(
                intent=Intent.POINTS_SCORERS,
                confidence=0.98,
                entities=entities,
            )

        # --------------------------------------------------------
        # 12. GENERAL RAG FALLBACK
        # --------------------------------------------------------
        return IntentResult(
            intent=Intent.GENERAL_RAG,
            confidence=0.5,
            entities=entities,
        )
