
import re

from raceintel.chat.gemini import GeminiClient, OfflineBlockedError
from raceintel.chat.prompts import INSUFFICIENT_EVIDENCE_RESPONSE, build_prompt
from raceintel.retrieval.retriever import RetrievalResult, Retriever
from raceintel.routing.entity_registry import EntityRegistry
from raceintel.routing.domain_guard import DomainGuard
from raceintel.routing.intent_classifier import Intent, IntentResult, IntentClassifier
from raceintel.routing.query_planner import QueryPlan, QueryPlanner
from raceintel.services.session_service import resolve_race_session
from raceintel.services.weather_service import get_weather_details, format_weather_answer
from raceintel.services.pace_service import get_fastest_lap_for_session, format_fastest_lap_answer
from raceintel.services.standings_service import (
    get_driver_standings_after_event,
    get_driver_standings_leader_after_event,
    format_driver_standings_leader_answer,
    get_driver_standings_record_after_event,
    format_driver_championship_position_answer,
    format_driver_cumulative_points_answer,
    compare_driver_standings_after_event,
    format_driver_standings_comparison_answer,
    format_driver_standings_table_answer,
    get_top_constructors_for_race,
    format_constructor_points_answer,
    get_constructor_standings_after_event,
    get_constructor_standings_leader_after_event,
    format_constructor_standings_leader_answer,
    format_constructor_standings_table_answer,
    compare_constructor_standings_after_event,
    format_constructor_standings_comparison_answer,
    get_constructor_single_race_points,
    format_single_constructor_race_points_answer,
    get_driver_season_sprint_points,
    format_driver_season_sprint_points_answer,
    get_constructor_season_sprint_points,
    format_constructor_season_sprint_points_answer,
    get_most_sprint_points_driver,
    format_most_sprint_points_driver_answer,
    get_most_sprint_points_constructor,
    format_most_sprint_points_constructor_answer,
)

from raceintel.services.race_service import (
    get_race_winner,
    format_race_winner_answer,
    get_driver_race_result,
    format_driver_points_answer,
    format_driver_position_answer,
    format_driver_performance_answer,
    get_race_podium,
    format_race_podium_answer,
    get_points_scorers,
    format_points_scorers_answer,
    get_team_race_results,
    format_team_performance_answer,
    get_top_driver_in_team,
    compare_drivers_in_race,
    format_driver_race_comparison_answer,
    get_race_retirements,
    format_race_retirements_answer,
    get_full_race_classification,
    format_full_race_classification_answer,
    get_biggest_movers_for_session,
    format_biggest_movers_answer,
    get_tyre_compounds_for_session,
    format_tyre_compounds_answer,
)


class ChatService:
    """
    Handles RaceIntel questions.

    Strategy:
    1. Validate domain and supported season before any retrieval.
    2. Classify intent and detect ambiguities with IntentClassifier.
    3. Generate structured QueryPlan via QueryPlanner separating plan from execution.
    4. Route structured factual intents directly to deterministic SQLite queries.
    5. Retrieve grounded F1 data via semantic search for general queries.
    6. Answer deterministic factual questions directly.
    7. Use Gemini only when generation is genuinely required.
    """

    def __init__(
        self,
        retriever: Retriever | None = None,
        llm: GeminiClient | None = None,
        offline: bool | None = None,
        entity_registry: EntityRegistry | None = None,
        domain_guard: DomainGuard | None = None,
        intent_classifier: IntentClassifier | None = None,
        query_planner: QueryPlanner | None = None,
    ):
        self.entity_registry = entity_registry if entity_registry is not None else EntityRegistry()
        self.domain_guard = domain_guard if domain_guard is not None else DomainGuard(registry=self.entity_registry)
        self.intent_classifier = intent_classifier if intent_classifier is not None else IntentClassifier(registry=self.entity_registry)
        self.query_planner = query_planner if query_planner is not None else QueryPlanner(registry=self.entity_registry)
        self.retriever = retriever if retriever is not None else Retriever(registry=self.entity_registry)
        if llm is not None:
            self.llm = llm
        else:
            self.llm = GeminiClient(offline=offline)

    def set_offline(self, offline: bool):
        """Toggle offline mode for the underlying GeminiClient."""
        if hasattr(self.llm, "offline"):
            self.llm.offline = offline
        else:
            self.llm = GeminiClient(offline=offline)

    # ============================================================
    # PARSING
    # ============================================================

    def _extract_driver_results(self, context: str):
        """
        Extract driver, position, points and team from RaceIntel
        driver reports.

        Handles the actual ChromaDB format:

        Driver:
        Charles Leclerc

        Constructor:
        Ferrari

        Finished:
        P1

        Points:
        25.0
        """

        results = []

        context = context.replace("\r\n", "\n").strip()

        # Split only when a NEW Driver section starts.
        sections = re.split(
            r"(?=^Driver:\s*$)",
            context,
            flags=re.IGNORECASE | re.MULTILINE
        )

        for section in sections:

            if not re.search(
                r"^Driver:\s*$",
                section,
                re.IGNORECASE | re.MULTILINE
            ):
                continue

            # ----------------------------------------------------
            # DRIVER
            # ----------------------------------------------------

            driver_match = re.search(
                r"^Driver:\s*$\s*(.+)",
                section,
                re.IGNORECASE | re.MULTILINE
            )

            if not driver_match:
                continue

            driver = driver_match.group(1).strip()

            # ----------------------------------------------------
            # TEAM / CONSTRUCTOR
            # ----------------------------------------------------

            team_match = re.search(
                r"^(?:Constructor|Team):\s*$\s*(.+)",
                section,
                re.IGNORECASE | re.MULTILINE
            )

            team = (
                team_match.group(1).strip()
                if team_match
                else None
            )

            # ----------------------------------------------------
            # FINISHING POSITION
            # ----------------------------------------------------

            position_match = re.search(
                r"^(?:Finished|Finishing Position|Finished Position):"
                r"\s*$\s*(P\d+|DNF|DNS)",
                section,
                re.IGNORECASE | re.MULTILINE
            )

            position = (
                position_match.group(1).upper()
                if position_match
                else None
            )

            # ----------------------------------------------------
            # POINTS
            # ----------------------------------------------------

            points_match = re.search(
                r"^Points(?:\s+Scored)?:"
                r"\s*$\s*([\d.]+)",
                section,
                re.IGNORECASE | re.MULTILINE
            )

            points = (
                float(points_match.group(1))
                if points_match
                else None
            )

            results.append(
                {
                    "driver": driver,
                    "position": position,
                    "points": points,
                    "team": team,
                }
            )

        return results

    # ============================================================
    # RACE REPORT PARSING
    # ============================================================

    def _extract_race_info(self, context: str):
        """
        Extract winner and podium information from race reports.
        """

        winner = None
        podium = []

        # Winner
        winner_match = re.search(
            r"Winner:\s*(?:\n\s*)?(.+)",
            context,
            re.IGNORECASE
        )

        if winner_match:
            winner = winner_match.group(1).strip()

        # Podium section
        podium_match = re.search(
            r"Podium:\s*(.*?)(?:\n\s*\n|Classification:|$)",
            context,
            re.IGNORECASE | re.DOTALL
        )

        if podium_match:

            podium_text = podium_match.group(1)

            podium_matches = re.findall(
                r"([123])\.\s*(.+)",
                podium_text
            )

            podium = [
                {
                    "position": f"P{position}",
                    "driver": driver.strip()
                }
                for position, driver in podium_matches
            ]

        # Fastest Lap
        fastest_lap = None
        fastest_match = re.search(
            r"Fastest Lap:\s*(?:\n\s*)?([^\n]+)",
            context,
            re.IGNORECASE
        )
        if fastest_match:
            fastest_lap = fastest_match.group(1).strip()

        return {
            "winner": winner,
            "podium": podium,
            "fastest_lap": fastest_lap,
        }

    # ============================================================
    # DIRECT ANSWERS
    # ============================================================

    def _direct_answer(self, question: str, context: str):

        q = question.lower().strip()

        results = self._extract_driver_results(context)
        race_info = self._extract_race_info(context)

        print("\n========== PARSED RESULTS ==========")
        print(results)
        print("====================================")

        # ========================================================
        # 1. DRIVER PERFORMANCE
        # ========================================================

        if "how did" in q and "perform" in q:

            for result in results:

                if result["driver"].lower() in q:

                    if (
                        result["position"] is not None
                        and result["points"] is not None
                    ):
                        return (
                            f"{result['driver']} finished "
                            f"{result['position']} and scored "
                            f"{result['points']} points."
                        )

        # ========================================================
        # 2. HOW MANY POINTS DID DRIVER SCORE?
        # ========================================================

        if (
            "how many points" in q
            or "how much points" in q
        ):

            for result in results:

                if result["driver"].lower() in q:

                    if result["points"] is not None:

                        return (
                            f"{result['driver']} scored "
                            f"{result['points']} points."
                        )

        # ========================================================
        # 3. WHAT POSITION DID DRIVER FINISH?
        # ========================================================

        if (
            "what position" in q
            or "which position" in q
            or "position did" in q
        ):

            for result in results:

                if result["driver"].lower() in q:

                    if result["position"]:

                        return (
                            f"{result['driver']} finished "
                            f"{result['position']}."
                        )

        # ========================================================
        # 4. WHO WON?
        # ========================================================

        if (
            "who won" in q
            or "which driver won" in q
        ):
            # First use race report winner.
            if race_info["winner"]:
                race_match = re.search(
                    r"^Grand Prix:\s*(.+)$",
                    context,
                    re.IGNORECASE | re.MULTILINE
                )
                season_match = re.search(
                    r"^Season:\s*(\d{4})",
                    context,
                    re.IGNORECASE | re.MULTILINE
                )

                if race_match:
                    race_name_in_context = race_match.group(1).strip()
                    # Verify that this race was actually asked about in question q
                    race_mentioned = False
                    for kw, canonical in self.retriever.RACES.items():
                        if kw in q and canonical.lower() == race_name_in_context.lower():
                            race_mentioned = True
                            break

                    if not race_mentioned:
                        # Context race does not match query! Do not hallucinate!
                        return None

                    if season_match:
                        return (
                            f"{race_info['winner']} won the "
                            f"{race_name_in_context} "
                            f"in {season_match.group(1)}."
                        )

                    return f"{race_info['winner']} won the {race_name_in_context}."

                return f"{race_info['winner']} won the race."

            # Fallback to driver reports.
            for result in results:
                if result["position"] == "P1":
                    return f"{result['driver']} won the race."

        # ========================================================
        # 5. WHO SCORED POINTS?
        # ========================================================

        if "who scored points" in q:

            scored = [
                r
                for r in results
                if (
                    r["points"] is not None
                    and r["points"] > 0
                )
            ]

            if scored:

                return "\n".join(
                    f"{r['driver']}: {r['points']} points"
                    for r in scored
                )

        # ========================================================
        # 6. WHO FINISHED ON THE PODIUM?
        # ========================================================

        if "podium" in q:

            # Race report podium is the most reliable source.
            if race_info["podium"]:

                return "\n".join(
                    f"{p['position']}. {p['driver']}"
                    for p in race_info["podium"]
                )

            # Fallback to driver reports.
            podium = [
                r
                for r in results
                if (
                    r["position"] is not None
                    and r["position"] in {
                        "P1",
                        "P2",
                        "P3"
                    }
                )
            ]

            if podium:

                podium.sort(
                    key=lambda r: int(
                        r["position"][1:]
                    )
                )

                return "\n".join(
                    f"{r['position']}. {r['driver']}"
                    for r in podium
                )

        # ========================================================
        # 7. WHICH DRIVER FINISHED HIGHER?
        # ========================================================

        if "finished higher" in q:

            # IMPORTANT:
            # If the question mentions a team, restrict results
            # to that team before comparing positions.

            team_names = {
                "ferrari": "Ferrari",
                "mercedes": "Mercedes",
                "mclaren": "McLaren",
                "red bull": "Red Bull Racing",
                "aston martin": "Aston Martin",
                "alpine": "Alpine",
                "haas": "Haas",
                "williams": "Williams",
                "rb": "RB",
                "sauber": "Kick Sauber",
            }

            selected_team = None

            for name, team in team_names.items():

                if name in q:

                    selected_team = team
                    break

            if selected_team:

                team_results = [
                    r
                    for r in results
                    if r["team"] == selected_team
                ]

                if team_results:

                    valid_results = [
                        r
                        for r in team_results
                        if (
                            r["position"] is not None
                            and r["position"].startswith("P")
                        )
                    ]

                    if valid_results:

                        valid_results.sort(
                            key=lambda r: int(
                                r["position"][1:]
                            )
                        )

                        return valid_results[0]["driver"]

            # Generic fallback.
            valid_results = [
                r
                for r in results
                if (
                    r["position"] is not None
                    and r["position"].startswith("P")
                )
            ]

            if valid_results:

                valid_results.sort(
                    key=lambda r: int(
                        r["position"][1:]
                    )
                )

                return valid_results[0]["driver"]

        # ========================================================
        # 8. WHO SCORED THE MOST POINTS?
        # ========================================================

        if "most points" in q:

            # Constructor / team query: aggregate points by team
            if "constructor" in q or "which team" in q or "team scored the most" in q:
                team_points = {}
                for r in results:
                    t = r.get("team")
                    p = r.get("points")
                    if t and p is not None:
                        team_points[t] = team_points.get(t, 0.0) + p
                if team_points:
                    max_pts = max(team_points.values())
                    top_teams = [t for t, pts in team_points.items() if pts == max_pts]
                    if len(top_teams) == 1:
                        return f"{top_teams[0]} scored the most points with {max_pts} points."
                    return f"{' and '.join(top_teams)} tied for the most points with {max_pts} points each."

            # Driver-level most points within team or race
            team_names = {
                "ferrari": "Ferrari",
                "mercedes": "Mercedes",
                "mclaren": "McLaren",
                "red bull": "Red Bull Racing",
                "aston martin": "Aston Martin",
                "alpine": "Alpine",
                "haas": "Haas",
                "williams": "Williams",
                "rb": "RB",
                "sauber": "Kick Sauber",
            }

            selected_team = None

            for name, team in team_names.items():

                if name in q:

                    selected_team = team
                    break

            candidates = results

            if selected_team:

                candidates = [
                    r
                    for r in results
                    if r["team"] == selected_team
                ]

            candidates = [
                r
                for r in candidates
                if r["points"] is not None
            ]

            if candidates:

                best = max(
                    candidates,
                    key=lambda r: r["points"]
                )

                return best["driver"]

        # ========================================================
        # FASTEST LAP
        # ========================================================

        if "fastest lap" in q or "quickest lap" in q:
            if race_info.get("fastest_lap"):
                return f"{race_info['fastest_lap']} set the fastest lap."

        # ========================================================
        # 9. TEAM RESULT / TEAM PERFORMANCE
        # ========================================================

        team_keywords = {
            "red bull racing": "Red Bull Racing",
            "red bull": "Red Bull Racing",
            "aston martin": "Aston Martin",
            "kick sauber": "Kick Sauber",
            "ferrari": "Ferrari",
            "mercedes": "Mercedes",
            "mclaren": "McLaren",
            "alpine": "Alpine",
            "haas": "Haas",
            "williams": "Williams",
            "sauber": "Kick Sauber",
            "rb": "RB",
        }

        non_result_topics = (
            "upgrade", "upgrades", "aerodynamic", "philosophy", "wing", "diffuser",
            "floor", "suspension", "brake", "strategy", "reason", "why", "explain",
            "how does", "pit stop", "regulation", "drs", "porpoising",
        )
        team_result_intents = (
            "finish", "finished", "position", "place", "point", "points", "result",
            "results", "perform", "performed", "performance", "score", "scored",
            "rank", "grid", "how did", "drivers", "standings", "do in",
        )

        is_team_result_question = (
            not any(tok in q for tok in non_result_topics)
            and any(tok in q for tok in team_result_intents)
        )

        selected_team = None
        if is_team_result_question:
            for name, team in team_keywords.items():
                if re.search(rf"\b{re.escape(name)}\b", q):
                    selected_team = team
                    break

        if selected_team:

            team_results = [
                r
                for r in results
                if r["team"] == selected_team
            ]

            if team_results:

                team_results.sort(
                    key=lambda r: (
                        int(r["position"][1:])
                        if (
                            r["position"]
                            and r["position"].startswith("P")
                        )
                        else 999
                    )
                )

                return "\n".join(
                    f"{r['driver']}: "
                    f"{r['position']}, "
                    f"{r['points']} points"
                    for r in team_results
                )

        return None

    # ============================================================
    # AMBIGUITY CHECKING
    # ============================================================

    def _check_ambiguous(self, question: str, filters: dict) -> tuple[bool, str]:
        """
        Detect ambiguous questions that lack essential identifying entities.
        Requests clarification rather than fabricating an arbitrary answer.
        """
        q = question.lower().strip()
        race_name = filters.get("race_name")
        driver = filters.get("driver")

        # 1. Unspecified race
        race_patterns = [
            r"^who won(?: the race)?\??$",
            r"^who won\??$",
            r"^who (?:was|is) the winner\??$",
            r"^who finished on the podium\??$",
            r"^what (?:was|is) the result of the race\??$",
            r"^tell me about the race\??$",
        ]
        if not race_name and any(re.search(p, q) for p in race_patterns):
            return True, "The question is ambiguous. Please specify which Grand Prix or race you are referring to."

        # 2. Unspecified driver with pronoun or indefinite noun
        driver_patterns = [
            r"\b(?:what position did|where did)\s+(?:he|she|they|the driver)\s+finish\b",
            r"\bdid (?:he|she|they|the driver) finish\b",
            r"\bhow many points did (?:he|she|they|the driver) score\b",
            r"\bhow did (?:he|she|they|the driver) perform\b",
            r"\bwhat was (?:his|her|their) finish(?:ing)? position\b",
        ]
        if not driver and any(re.search(p, q) for p in driver_patterns):
            return True, "The question is ambiguous. Please specify which driver you are referring to."

        return False, ""

    # ============================================================
    # STRUCTURED QUERY ROUTING
    # ============================================================

    def _route_structured_query(self, question: str, filters: dict) -> str | None:
        """
        Route structured question archetypes directly to deterministic SQLite queries.
        Handles weather, fastest lap, driver championship standings leader,
        and constructor points aggregation.
        """
        q = question.lower().strip()
        race_name = filters.get("race_name")
        season = filters.get("season", 2024)

        # 1. Driver championship standings leader
        standings_keywords = [
            "leads the driver standings",
            "leading the driver standings",
            "leads the championship",
            "leading the championship",
            "driver standings after",
            "championship leader after",
        ]
        if any(k in q for k in standings_keywords):
            if not race_name:
                return "The question is ambiguous. Please specify after which Grand Prix you would like the standings."
            resolved = resolve_race_session(race_name, season)
            if resolved and resolved.get("found"):
                leader = get_driver_standings_leader_after_event(
                    resolved["session_id"], resolved["season_year"]
                )
                return format_driver_standings_leader_answer(
                    leader, resolved["event_name"], resolved["season_year"]
                )
            elif resolved and resolved.get("reason") == "season_not_found":
                return f"I couldn't find that information in the retrieved race data. Historical data for season {season} is not available."
            return "I couldn't find that information in the retrieved race data."

        # 2. Constructor points for a race
        if ("constructor" in q or "team" in q) and (
            "most points" in q
            or "points scored" in q
            or "scored the most points" in q
        ):
            if not race_name:
                return "The question is ambiguous. Please specify which Grand Prix you are referring to."
            resolved = resolve_race_session(race_name, season)
            if resolved and resolved.get("found"):
                top_info = get_top_constructors_for_race(resolved["session_id"])
                return format_constructor_points_answer(
                    top_info, resolved["event_name"], resolved["season_year"]
                )
            elif resolved and resolved.get("reason") == "season_not_found":
                return f"I couldn't find that information in the retrieved race data. Historical data for season {season} is not available."
            return "I couldn't find that information in the retrieved race data."

        # 3. Fastest lap
        fastest_lap_keywords = ["fastest lap", "quickest lap", "best lap"]
        if any(k in q for k in fastest_lap_keywords):
            if not race_name:
                return "The question is ambiguous. Please specify which Grand Prix you are referring to."
            resolved = resolve_race_session(race_name, season)
            if resolved and resolved.get("found"):
                fastest = get_fastest_lap_for_session(resolved["session_id"])
                return format_fastest_lap_answer(
                    fastest, resolved["event_name"], resolved["season_year"]
                )
            elif resolved and resolved.get("reason") == "season_not_found":
                return f"I couldn't find that information in the retrieved race data. Historical data for season {season} is not available."
            return "I couldn't find that information in the retrieved race data."

        # 4. Weather queries
        # Note: avoid matching 'rain' inside 'Bahrain' by checking word boundaries
        has_weather_term = bool(
            re.search(r"\b(rain|rainfall|rained|raining)\b", q)
            or any(
                w in q
                for w in [
                    "weather",
                    "temperature",
                    "wet track",
                    "track wet",
                    "dry or wet",
                    "wet or dry",
                    "conditions",
                ]
            )
        )
        if has_weather_term:
            if not race_name:
                return "The question is ambiguous. Please specify which Grand Prix you are asking about."
            resolved = resolve_race_session(race_name, season)
            if resolved and resolved.get("found"):
                w = get_weather_details(resolved["session_id"])
                return format_weather_answer(
                    w, question, resolved["event_name"], resolved["season_year"]
                )
            elif resolved and resolved.get("reason") == "season_not_found":
                return f"I couldn't find that information in the retrieved race data. Historical weather data for season {season} is not available."
            return "I couldn't find that information in the retrieved race data."

        return None

    def _execute_query_plan(self, plan: QueryPlan, question: str) -> str | None:
        """
        Execute a structured QueryPlan by dispatching to the designated service.
        Logs route selection and returns deterministic, validated response.
        """
        if not plan.is_executable:
            return plan.clarification_message or "The question is ambiguous. Please provide more details."

        service = plan.service_name
        op = plan.operation
        params = plan.parameters

        print(f"\n[QueryPlanner] Dispatched to {service}.{op} with params: {params}")

        if service == "race_service":
            sid = params["session_id"]
            ev = params.get("event_name", "Grand Prix")
            yr = params.get("season_year", 2024)

            if op == "race_winner":
                winner = get_race_winner(sid)
                return format_race_winner_answer(
                    winner, ev, yr, session_type=params.get("session_type", "Race")
                )
            elif op == "race_podium":
                podium = get_race_podium(sid)
                return format_race_podium_answer(podium, ev, yr)
            elif op == "points_scorers":
                scorers = get_points_scorers(sid)
                return format_points_scorers_answer(scorers, ev, yr)
            elif op == "driver_points":
                res = get_driver_race_result(sid, params["driver_id"])
                return format_driver_points_answer(res, params["driver_name"], ev, yr)
            elif op == "driver_position":
                res = get_driver_race_result(sid, params["driver_id"])
                return format_driver_position_answer(res, params["driver_name"], ev, yr)
            elif op == "driver_performance":
                res = get_driver_race_result(sid, params["driver_id"])
                return format_driver_performance_answer(res, params["driver_name"], ev, yr)
            elif op == "team_performance":
                res = get_team_race_results(sid, params["constructor_id"])
                return format_team_performance_answer(res, params["team_name"], ev, yr)
            elif op == "team_comparison":
                top_d = get_top_driver_in_team(sid, params["constructor_id"], by_points=False)
                return top_d["driver"] if top_d else "I couldn't find that information in the retrieved race data."
            elif op == "most_points_in_team":
                top_d = get_top_driver_in_team(sid, params["constructor_id"], by_points=True)
                return top_d["driver"] if top_d else "I couldn't find that information in the retrieved race data."
            elif op == "driver_race_comparison":
                d1 = params["driver_1"]
                d2 = params["driver_2"]
                comp = compare_drivers_in_race(sid, d1["driver_id"], d2["driver_id"])
                return format_driver_race_comparison_answer(comp, ev, yr)
            elif op == "race_retirements":
                retirements = get_race_retirements(sid)
                return format_race_retirements_answer(retirements, ev, yr)
            elif op == "race_classification":
                classification = get_full_race_classification(sid)
                return format_full_race_classification_answer(classification, ev, yr)
            elif op == "biggest_movers":
                movers = get_biggest_movers_for_session(sid)
                return format_biggest_movers_answer(movers, ev, yr)
            elif op == "tyre_usage":
                compounds = get_tyre_compounds_for_session(sid, params.get("driver_id"))
                return format_tyre_compounds_answer(compounds, ev, params.get("driver_name"), yr)

        elif service == "standings_service":
            sid = params.get("session_id")
            ev = params.get("event_name", "Grand Prix")
            yr = params.get("season_year", 2024)

            if op == "driver_season_sprint_points":
                pts = get_driver_season_sprint_points(params["driver_id"], yr)
                return format_driver_season_sprint_points_answer(pts, params["driver_name"], yr)
            elif op == "constructor_season_sprint_points":
                pts = get_constructor_season_sprint_points(params["constructor_id"], yr)
                return format_constructor_season_sprint_points_answer(pts, params["constructor_name"], yr)
            elif op == "most_sprint_points":
                if params.get("target") == "constructor":
                    lead = get_most_sprint_points_constructor(yr)
                    return format_most_sprint_points_constructor_answer(lead, yr)
                else:
                    lead = get_most_sprint_points_driver(yr)
                    return format_most_sprint_points_driver_answer(lead, yr)
            elif op == "driver_standings_leader":
                leader = get_driver_standings_leader_after_event(sid, yr)
                return format_driver_standings_leader_answer(leader, ev, yr)
            elif op == "driver_championship_position":
                record = get_driver_standings_record_after_event(sid, params["driver_id"], yr)
                return format_driver_championship_position_answer(record, params["driver_name"], ev, yr)
            elif op == "driver_cumulative_points":
                record = get_driver_standings_record_after_event(sid, params["driver_id"], yr)
                return format_driver_cumulative_points_answer(record, params["driver_name"], ev, yr)
            elif op == "driver_standings_comparison":
                d1 = params["driver_1"]
                d2 = params["driver_2"]
                comp = compare_driver_standings_after_event(sid, d1["driver_id"], d2["driver_id"], yr)
                return format_driver_standings_comparison_answer(comp, ev, yr)
            elif op == "driver_standings_table":
                standings = get_driver_standings_after_event(sid, yr)
                return format_driver_standings_table_answer(standings, ev, yr)
            elif op == "constructor_race_points":
                cid = params.get("constructor_id")
                cname = params.get("constructor_name")
                if cid and cname:
                    res = get_constructor_single_race_points(sid, cid)
                    return format_single_constructor_race_points_answer(res, cname, ev, yr)
                top_info = get_top_constructors_for_race(sid)
                return format_constructor_points_answer(top_info, ev, yr)
            elif op == "constructor_standings_leader":
                leader = get_constructor_standings_leader_after_event(sid, yr)
                return format_constructor_standings_leader_answer(leader, ev, yr)
            elif op == "constructor_standings_table":
                standings = get_constructor_standings_after_event(sid, yr)
                return format_constructor_standings_table_answer(standings, ev, yr)
            elif op == "constructor_standings_comparison":
                c1 = params["constructor_1"]
                c2 = params["constructor_2"]
                comp = compare_constructor_standings_after_event(sid, c1["constructor_id"], c2["constructor_id"], yr)
                return format_constructor_standings_comparison_answer(comp, ev, yr)


        elif service == "pace_service":
            sid = params["session_id"]
            ev = params.get("event_name", "Grand Prix")
            yr = params.get("season_year", 2024)
            if op == "fastest_lap":
                fastest = get_fastest_lap_for_session(sid)
                return format_fastest_lap_answer(fastest, ev, yr)

        elif service == "weather_service":
            sid = params["session_id"]
            ev = params.get("event_name", "Grand Prix")
            yr = params.get("season_year", 2024)
            if op == "weather_details":
                w = get_weather_details(sid)
                return format_weather_answer(w, params.get("question", question), ev, yr)

        return None

    def _route_intent(self, question: str, intent_res: IntentResult) -> str | None:
        """
        Execute deterministic structured queries for classified intents.
        Uses QueryPlanner to create plan and then executes it.
        """
        plan = self.query_planner.create_plan(question, intent_res)
        if not plan.is_executable:
            return plan.clarification_message or "The question is ambiguous. Please provide more details."
        return self._execute_query_plan(plan, question)

    # ============================================================
    # ASK
    # ============================================================

    def ask(self, question: str) -> str:

        print("\n========================================")
        print("RACEINTEL CHAT")
        print("========================================")
        print("Question:", question)

        # --------------------------------------------------------
        # 0. EARLY DOMAIN & SEASON VALIDATION
        # --------------------------------------------------------
        domain_result = self.domain_guard.validate(question)
        if not domain_result.is_valid:
            print("\n========== DOMAIN GUARD REJECTION ==========")
            print(domain_result.refusal_message)
            print("===========================================\n")
            return domain_result.refusal_message

        # --------------------------------------------------------
        # 1. INTENT CLASSIFICATION & AMBIGUITY DETECTION
        # --------------------------------------------------------
        intent_res = self.intent_classifier.classify(question)
        if intent_res.is_ambiguous:
            print("\n========== AMBIGUOUS QUERY ==========")
            print(intent_res.clarification_message)
            print("=====================================\n")
            return intent_res.clarification_message or "The question is ambiguous. Please provide more details."

        # --------------------------------------------------------
        # 2. STRUCTURED QUERY PLANNING & EXECUTION
        # --------------------------------------------------------
        plan = self.query_planner.create_plan(question, intent_res)
        if not plan.is_executable:
            print("\n========== QUERY PLAN UNEXECUTABLE ==========")
            print(plan.clarification_message)
            print("============================================\n")
            return plan.clarification_message or "The question is ambiguous. Please provide more details."

        if plan.service_name and plan.service_name != "retriever":
            structured_answer = self._execute_query_plan(plan, question)
            if structured_answer is not None:
                print("\n========== STRUCTURED ANSWER ==========")
                print(structured_answer)
                print("=======================================\n")
                return structured_answer
            print("\n========== STRUCTURED CAPABILITY EMPTY ==========")
            return "I couldn't find that information in the retrieved race data."

        filters = self.retriever._extract_filters(question)

        # Fallback to legacy structured queries if any
        legacy_answer = self._route_structured_query(question, filters)
        if legacy_answer is not None:
            print("\n========== LEGACY STRUCTURED ANSWER ==========")
            print(legacy_answer)
            print("=============================================\n")
            return legacy_answer

        # --------------------------------------------------------
        # 3. CALIBRATED RETRIEVE
        # --------------------------------------------------------

        retrieval_result = self._retrieve_with_safety(question)
        raw_context = retrieval_result.raw_context
        grounded_context = retrieval_result.context or raw_context

        print("\n========== CONTEXT ==========")
        print(f"Status: {retrieval_result.status}")
        print(grounded_context[:3000])
        print("=============================")

        if retrieval_result.status == "error":
            return (
                "I couldn't retrieve race data right now due to a knowledge base error. "
                "Please try again later."
            )

        if retrieval_result.status == "event_mismatch":
            return (
                "I couldn't find that information in the retrieved race data. "
                "That event is not part of the Formula 1 2024 calendar."
            )

        if (
            retrieval_result.status in ("entity_mismatch", "low_confidence", "empty", "ambiguous")
            or not raw_context.strip()
        ):
            if filters.get("season") and not self.entity_registry.is_season_supported(filters["season"]):
                return (
                    f"I couldn't find that information in the retrieved race data. "
                    f"Historical data for season {filters['season']} is not available."
                )
            q_lower = question.lower()
            if any(term in q_lower for term in ["500", "le mans", "daytona", "french grand prix", "nascar", "motogp"]):
                return (
                    "I couldn't find that information in the retrieved race data. "
                    "That event is not part of the Formula 1 2024 calendar."
                )
            return INSUFFICIENT_EVIDENCE_RESPONSE

        if retrieval_result.conflict_detected:
            conflict_summary = "; ".join(retrieval_result.conflict_details)
            return (
                f"Conflicting race data was found in the retrieved documents: "
                f"{conflict_summary}. I cannot determine a single definitive answer."
            )

        # --------------------------------------------------------
        # 4. DIRECT ANSWER
        # --------------------------------------------------------

        direct_answer = self._direct_answer(
            question,
            raw_context,
        )

        if direct_answer is not None:
            print("\n========== DIRECT ANSWER ==========")
            print(direct_answer)
            print("===================================\n")
            return direct_answer

        # --------------------------------------------------------
        # 5. EVIDENCE-GROUNDED LLM FALLBACK
        # --------------------------------------------------------

        print("\n========== GEMINI FALLBACK ==========")

        prompt = build_prompt(
            question,
            grounded_context,
        )

        try:
            llm_response = self.llm.generate(prompt)
        except OfflineBlockedError:
            raise
        except Exception as exc:
            print(f"[LLM Fallback Error] {exc}")
            return (
                "I couldn't find that information in the retrieved race data "
                "because the language model service is temporarily unavailable."
            )

        sanitized = self._sanitize_llm_response(llm_response)
        if sanitized is None:
            return INSUFFICIENT_EVIDENCE_RESPONSE

        return sanitized

    def _retrieve_with_safety(self, question: str) -> RetrievalResult:
        """
        Execute calibrated retrieval safely, supporting both RetrievalResult-aware
        retrievers and mocked string-returning .retrieve() callables.
        """
        try:
            retriever_dict = getattr(self.retriever, "__dict__", {})
            if "retrieve_context" in retriever_dict:
                res = self.retriever.retrieve_context(question)
                if isinstance(res, RetrievalResult):
                    return res

            if "retrieve" in retriever_dict or not isinstance(self.retriever, Retriever):
                raw_ctx = self.retriever.retrieve(question)
            else:
                return self.retriever.retrieve_context(question)
        except Exception as exc:
            print(f"[Retrieval Error] {exc}")
            return RetrievalResult(status="error", error_message=str(exc))

        if not isinstance(raw_ctx, str) or not raw_ctx.strip():
            return RetrievalResult(status="empty")

        blocks = [b.strip() for b in raw_ctx.split("\n\n") if b.strip()]
        metadatas = [{} for _ in blocks]
        conflict_detected, conflict_details = Retriever._detect_conflicts(
            blocks, metadatas
        )
        return RetrievalResult(
            documents=blocks,
            ids=[f"mock_{i}" for i in range(len(blocks))],
            metadatas=metadatas,
            distances=[0.0 for _ in blocks],
            status="conflict" if conflict_detected else "ok",
            context=(
                f"[CONFLICT DETECTED] {'; '.join(conflict_details)}\n\n{raw_ctx}"
                if conflict_detected
                else raw_ctx
            ),
            raw_context=raw_ctx,
            conflict_detected=conflict_detected,
            conflict_details=conflict_details,
        )

    @staticmethod
    def _sanitize_llm_response(response: object) -> str | None:
        """Reject empty, None, or malformed placeholder LLM outputs."""
        if not isinstance(response, str):
            return None
        cleaned = response.strip()
        if not cleaned:
            return None
        if cleaned.lower() in {"none", "null", "nan", "{}", "[]", "n/a", "undefined"}:
            return None
        return cleaned
