"""
Query Planning Module for RaceIntel.

Translates classified intents and resolved entities into a structured,
executable QueryPlan before SQL dispatch, maintaining complete architectural
separation between query planning and execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from raceintel.routing.entity_registry import DEFAULT_DB_PATH, EntityRegistry
from raceintel.routing.intent_classifier import Intent, IntentResult
from raceintel.services.session_service import resolve_race_session


@dataclass
class QueryPlan:
    """
    Structured query plan specifying the service, operation, and parameters
    for deterministic data resolution.
    """
    intent: Intent
    service_name: str
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    is_executable: bool = True
    unresolved_reason: str | None = None
    clarification_message: str | None = None


class QueryPlanner:
    """
    Translates IntentResult into an executable QueryPlan.
    Validates required entities, sessions, and parameters before SQL dispatch.
    """

    def __init__(self, registry: EntityRegistry | None = None):
        self.registry = registry if registry is not None else EntityRegistry()

    def create_plan(self, question: str, intent_res: IntentResult) -> QueryPlan:
        """
        Produce a structured QueryPlan from an IntentResult and user question.
        """
        intent = intent_res.intent
        entities = intent_res.entities

        # 1. Ambiguous query check
        if intent_res.is_ambiguous:
            return QueryPlan(
                intent=intent,
                service_name="",
                operation="",
                parameters={},
                is_executable=False,
                unresolved_reason="ambiguous_query",
                clarification_message=intent_res.clarification_message or "The question is ambiguous. Please provide more details.",
            )

        # 2. General RAG (Semantic Search)
        if intent == Intent.GENERAL_RAG:
            return QueryPlan(
                intent=Intent.GENERAL_RAG,
                service_name="retriever",
                operation="semantic_search",
                parameters={"question": question},
                is_executable=True,
            )

        # 3. Explicit season support check
        season = entities.get("season", 2024)
        if entities.get("season_explicit") and not self.registry.is_season_supported(season):
            return QueryPlan(
                intent=intent,
                service_name="",
                operation="",
                parameters={"season": season},
                is_executable=False,
                unresolved_reason="season_not_supported",
                clarification_message=(
                    f"I couldn't find that information in the retrieved race data. "
                    f"Historical data for season {season} is not available."
                ),
            )

        # 3.5 Season-level Sprint intents
        if intent == Intent.DRIVER_SPRINT_POINTS:
            driver_id = entities.get("driver_id")
            driver_name = entities.get("driver_name")
            if not driver_id or not driver_name:
                return QueryPlan(
                    intent=intent,
                    service_name="",
                    operation="",
                    parameters=entities,
                    is_executable=False,
                    unresolved_reason="missing_driver",
                    clarification_message="The question is ambiguous. Please specify which driver you are referring to.",
                )
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="driver_season_sprint_points",
                parameters={
                    "driver_id": driver_id,
                    "driver_name": driver_name,
                    "season_year": season,
                },
                is_executable=True,
            )

        if intent == Intent.CONSTRUCTOR_SPRINT_POINTS:
            constructor_id = entities.get("constructor_id")
            constructor_name = entities.get("constructor_name")
            if not constructor_id or not constructor_name:
                return QueryPlan(
                    intent=intent,
                    service_name="",
                    operation="",
                    parameters=entities,
                    is_executable=False,
                    unresolved_reason="missing_constructor",
                    clarification_message="The question is ambiguous. Please specify which team you are referring to.",
                )
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="constructor_season_sprint_points",
                parameters={
                    "constructor_id": constructor_id,
                    "constructor_name": constructor_name,
                    "season_year": season,
                },
                is_executable=True,
            )

        if intent == Intent.MOST_SPRINT_POINTS:
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="most_sprint_points",
                parameters={
                    "target": entities.get("target", "driver"),
                    "season_year": season,
                },
                is_executable=True,
            )

        # 4. Event / Session resolution for event-bound intents
        race_name = entities.get("race_name")
        session_type = entities.get("session_type", "Race")
        session_info = None

        standings_intents = {
            Intent.DRIVER_STANDINGS_LEADER,
            Intent.DRIVER_CHAMPIONSHIP_POSITION,
            Intent.DRIVER_CUMULATIVE_POINTS,
            Intent.DRIVER_STANDINGS_COMPARISON,
            Intent.DRIVER_STANDINGS_TABLE,
            Intent.CONSTRUCTOR_STANDINGS_LEADER,
            Intent.CONSTRUCTOR_STANDINGS_TABLE,
            Intent.CONSTRUCTOR_STANDINGS_COMPARISON,
        }

        if not race_name:
            if intent in standings_intents:
                msg = "The question is ambiguous. Please specify after which Grand Prix you would like the standings."
            elif intent == Intent.WEATHER:
                msg = "The question is ambiguous. Please specify which Grand Prix you are asking about."
            else:
                msg = "The question is ambiguous. Please specify which Grand Prix or race you are referring to."

            return QueryPlan(
                intent=intent,
                service_name="",
                operation="",
                parameters=entities,
                is_executable=False,
                unresolved_reason="missing_event",
                clarification_message=msg,
            )

        custom_db = self.registry.db_path if self.registry.db_path != DEFAULT_DB_PATH else None
        session_info = resolve_race_session(race_name, season, session_type=session_type, db_path=custom_db)
        if session_info and not session_info.get("found"):
            reason = session_info.get("reason")
            if reason == "season_not_found":
                msg = f"I couldn't find that information in the retrieved race data. Historical data for season {season} is not available."
            elif reason == "event_not_found":
                msg = f"I couldn't find that information in the retrieved race data. That event is not part of the Formula 1 {season} calendar."
            elif reason == "ambiguous_event":
                cands = ", ".join(session_info.get("candidates", []))

                msg = (
                    f"The question is ambiguous. Multiple Grand Prix events match '{race_name}'"
                    f"{f' ({cands})' if cands else ''}. Please specify which Grand Prix you are referring to."
                )
            elif reason == "ambiguous_season":
                cands = ", ".join(str(s) for s in session_info.get("available_seasons", []))
                msg = (
                    f"The question is ambiguous. '{race_name}' occurred in multiple seasons"
                    f"{f' ({cands})' if cands else ''}. Please specify which season you are referring to."
                )
            else:
                msg = "I couldn't find that information in the retrieved race data."
            return QueryPlan(
                intent=intent,
                service_name="",
                operation="",
                parameters={"race_name": race_name, "season": season},
                is_executable=False,
                unresolved_reason=reason or "session_not_found",
                clarification_message=msg,
            )

        session_id = session_info["session_id"] if session_info else None
        session_type = session_info.get("session_type", session_type) if session_info else session_type
        event_name = session_info["event_name"] if session_info else race_name
        season_year = session_info["season_year"] if session_info else season

        # 5. Intent-specific entity validation & parameter dispatch

        # Driver-specific single-driver intents
        driver_single_intents = {
            Intent.DRIVER_POINTS,
            Intent.DRIVER_POSITION,
            Intent.DRIVER_PERFORMANCE,
            Intent.DRIVER_CHAMPIONSHIP_POSITION,
            Intent.DRIVER_CUMULATIVE_POINTS,
        }
        if intent in driver_single_intents:
            driver_id = entities.get("driver_id")
            driver_name = entities.get("driver_name")
            if not driver_id or not driver_name:
                return QueryPlan(
                    intent=intent,
                    service_name="",
                    operation="",
                    parameters=entities,
                    is_executable=False,
                    unresolved_reason="missing_driver",
                    clarification_message="The question is ambiguous. Please specify which driver you are referring to.",
                )

        # Constructor-specific team intents
        constructor_team_intents = {
            Intent.TEAM_PERFORMANCE,
            Intent.TEAM_COMPARISON,
            Intent.MOST_POINTS_IN_TEAM,
        }
        if intent in constructor_team_intents:
            constructor_id = entities.get("constructor_id")
            constructor_name = entities.get("constructor_name")
            if not constructor_id or not constructor_name:
                return QueryPlan(
                    intent=intent,
                    service_name="",
                    operation="",
                    parameters=entities,
                    is_executable=False,
                    unresolved_reason="missing_constructor",
                    clarification_message="The question is ambiguous. Please specify which team you are referring to.",
                )

        # Comparison intents
        if intent == Intent.DRIVER_RACE_COMPARISON:
            d1 = entities.get("driver_1")
            d2 = entities.get("driver_2")
            if not d1 or not d2:
                recs = entities.get("driver_records", [])
                if len(recs) >= 2:
                    d1, d2 = recs[0], recs[1]
            if not d1 or not d2:
                return QueryPlan(
                    intent=intent,
                    service_name="",
                    operation="",
                    parameters=entities,
                    is_executable=False,
                    unresolved_reason="missing_comparison_drivers",
                    clarification_message="The question is ambiguous. Please specify which two drivers you would like to compare.",
                )
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="driver_race_comparison",
                parameters={
                    "session_id": session_id,
                    "driver_1": d1,
                    "driver_2": d2,
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )

        if intent == Intent.DRIVER_STANDINGS_COMPARISON:
            d1 = entities.get("driver_1")
            d2 = entities.get("driver_2")
            if not d1 or not d2:
                recs = entities.get("driver_records", [])
                if len(recs) >= 2:
                    d1, d2 = recs[0], recs[1]
            if not d1 or not d2:
                return QueryPlan(
                    intent=intent,
                    service_name="",
                    operation="",
                    parameters=entities,
                    is_executable=False,
                    unresolved_reason="missing_comparison_drivers",
                    clarification_message="The question is ambiguous. Please specify which two drivers you would like to compare.",
                )
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="driver_standings_comparison",
                parameters={
                    "session_id": session_id,
                    "driver_1": d1,
                    "driver_2": d2,
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )

        if intent == Intent.CONSTRUCTOR_STANDINGS_COMPARISON:
            c1 = entities.get("constructor_1")
            c2 = entities.get("constructor_2")
            if not c1 or not c2:
                recs = entities.get("constructor_records", [])
                if len(recs) >= 2:
                    c1, c2 = recs[0], recs[1]
            if not c1 or not c2:
                return QueryPlan(
                    intent=intent,
                    service_name="",
                    operation="",
                    parameters=entities,
                    is_executable=False,
                    unresolved_reason="missing_comparison_constructors",
                    clarification_message="The question is ambiguous. Please specify which two constructors you would like to compare.",
                )
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="constructor_standings_comparison",
                parameters={
                    "session_id": session_id,
                    "constructor_1": c1,
                    "constructor_2": c2,
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )

        # Standard Service Mappings
        # Race service
        if intent == Intent.RACE_WINNER:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="race_winner",
                parameters={
                    "session_id": session_id,
                    "event_name": event_name,
                    "season_year": season_year,
                    "session_type": session_type,
                },
                is_executable=True,
            )

        elif intent == Intent.PODIUM:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="race_podium",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )
        elif intent == Intent.POINTS_SCORERS:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="points_scorers",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )
        elif intent == Intent.DRIVER_POINTS:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="driver_points",
                parameters={
                    "session_id": session_id,
                    "driver_id": entities["driver_id"],
                    "driver_name": entities["driver_name"],
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.DRIVER_POSITION:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="driver_position",
                parameters={
                    "session_id": session_id,
                    "driver_id": entities["driver_id"],
                    "driver_name": entities["driver_name"],
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.DRIVER_PERFORMANCE:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="driver_performance",
                parameters={
                    "session_id": session_id,
                    "driver_id": entities["driver_id"],
                    "driver_name": entities["driver_name"],
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.TEAM_PERFORMANCE:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="team_performance",
                parameters={
                    "session_id": session_id,
                    "constructor_id": entities["constructor_id"],
                    "team_name": entities["constructor_name"],
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.TEAM_COMPARISON:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="team_comparison",
                parameters={
                    "session_id": session_id,
                    "constructor_id": entities["constructor_id"],
                    "team_name": entities["constructor_name"],
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.MOST_POINTS_IN_TEAM:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="most_points_in_team",
                parameters={
                    "session_id": session_id,
                    "constructor_id": entities["constructor_id"],
                    "team_name": entities["constructor_name"],
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.RACE_RETIREMENTS:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="race_retirements",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )
        elif intent == Intent.RACE_CLASSIFICATION:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="race_classification",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )
        elif intent == Intent.BIGGEST_MOVERS:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="biggest_movers",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )
        elif intent == Intent.TYRE_USAGE:
            return QueryPlan(
                intent=intent,
                service_name="race_service",
                operation="tyre_usage",
                parameters={
                    "session_id": session_id,
                    "event_name": event_name,
                    "driver_id": entities.get("driver_id"),
                    "driver_name": entities.get("driver_name"),
                    "season_year": season_year,
                },
                is_executable=True,
            )

        # Standings service
        elif intent == Intent.DRIVER_STANDINGS_LEADER:
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="driver_standings_leader",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )
        elif intent == Intent.DRIVER_CHAMPIONSHIP_POSITION:
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="driver_championship_position",
                parameters={
                    "session_id": session_id,
                    "driver_id": entities["driver_id"],
                    "driver_name": entities["driver_name"],
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.DRIVER_CUMULATIVE_POINTS:
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="driver_cumulative_points",
                parameters={
                    "session_id": session_id,
                    "driver_id": entities["driver_id"],
                    "driver_name": entities["driver_name"],
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.DRIVER_STANDINGS_TABLE:
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="driver_standings_table",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )
        elif intent == Intent.CONSTRUCTOR_RACE_POINTS:
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="constructor_race_points",
                parameters={
                    "session_id": session_id,
                    "constructor_id": entities.get("constructor_id"),
                    "constructor_name": entities.get("constructor_name"),
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )
        elif intent == Intent.CONSTRUCTOR_STANDINGS_LEADER:
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="constructor_standings_leader",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )
        elif intent == Intent.CONSTRUCTOR_STANDINGS_TABLE:
            return QueryPlan(
                intent=intent,
                service_name="standings_service",
                operation="constructor_standings_table",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )

        # Pace service
        elif intent == Intent.FASTEST_LAP:
            return QueryPlan(
                intent=intent,
                service_name="pace_service",
                operation="fastest_lap",
                parameters={"session_id": session_id, "event_name": event_name, "season_year": season_year},
                is_executable=True,
            )

        # Weather service
        elif intent == Intent.WEATHER:
            return QueryPlan(
                intent=intent,
                service_name="weather_service",
                operation="weather_details",
                parameters={
                    "session_id": session_id,
                    "question": question,
                    "event_name": event_name,
                    "season_year": season_year,
                },
                is_executable=True,
            )

        # Generic fallback
        return QueryPlan(
            intent=intent,
            service_name="retriever",
            operation="semantic_search",
            parameters={"question": question},
            is_executable=True,
        )
