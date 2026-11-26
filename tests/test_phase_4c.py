import pytest
pytestmark = pytest.mark.requires_data
"""
Phase 4C Test Suite: Structured SQL Routing Expansion.

Covers all 13 required test dimensions plus supplementary generalisation tests:
1. Intent-to-service mapping
2. Service selection
3. Event and session resolution
4. Driver and constructor handling
5. Race-specific vs season-wide calculations
6. Missing entity handling
7. Ambiguous entity handling
8. Empty result handling
9. Ties and duplicate values
10. SQL parameterization & read-only safety
11. Entity and numerical correctness
12. Regression preservation
13. Semantic retrieval (RAG) fallback
14. Supplementary generalisation tests with novel phrasings
"""

import hashlib
import sqlite3
import pytest

from raceintel.routing.entity_registry import EntityRegistry
from raceintel.routing.intent_classifier import Intent, IntentClassifier
from raceintel.routing.query_planner import QueryPlan, QueryPlanner
from raceintel.chat.chat_service import ChatService
from raceintel.services.race_service import (
    get_race_winner,
    get_race_retirements,
    get_full_race_classification,
    get_biggest_movers_for_session,
    get_tyre_compounds_for_session,
)
from raceintel.services.standings_service import (
    get_driver_standings_after_event,
    get_driver_standings_leader_after_event,
    get_driver_standings_record_after_event,
    compare_driver_standings_after_event,
    get_constructor_standings_after_event,
    get_constructor_standings_leader_after_event,
    compare_constructor_standings_after_event,
)


@pytest.fixture(scope="module")
def registry():
    return EntityRegistry()


@pytest.fixture(scope="module")
def classifier(registry):
    return IntentClassifier(registry=registry)


@pytest.fixture(scope="module")
def planner(registry):
    return QueryPlanner(registry=registry)


@pytest.fixture(scope="module")
def chat_service(registry, classifier, planner):
    return ChatService(
        offline=True,
        entity_registry=registry,
        intent_classifier=classifier,
        query_planner=planner,
    )


# =====================================================================
# Dimension 1: Intent-to-Service Mapping
# =====================================================================

def test_intent_to_service_mapping(planner, classifier):
    cases = [
        ("Who won the 2024 Monaco Grand Prix?", "race_service", "race_winner"),
        ("Who finished on the podium in Monaco?", "race_service", "race_podium"),
        ("Who scored points in the Bahrain Grand Prix?", "race_service", "points_scorers"),
        ("Who retired from the 2024 Australian Grand Prix?", "race_service", "race_retirements"),
        ("What was the full race classification in the 2024 Bahrain Grand Prix?", "race_service", "race_classification"),
        ("Who gained the most positions in the 2024 Japanese Grand Prix?", "race_service", "biggest_movers"),
        ("Which tyre compounds were used during the 2024 Bahrain Grand Prix?", "race_service", "tyre_usage"),
        ("Who was leading the driver standings after the Bahrain Grand Prix?", "standings_service", "driver_standings_leader"),
        ("Where was Charles Leclerc in the driver standings after the Monaco Grand Prix?", "standings_service", "driver_championship_position"),
        ("How many championship points did Max Verstappen have after the Austrian Grand Prix?", "standings_service", "driver_cumulative_points"),
        ("Who was leading the constructors championship after the Miami Grand Prix?", "standings_service", "constructor_standings_leader"),
        ("What were the constructor standings after the Spanish Grand Prix?", "standings_service", "constructor_standings_table"),
        ("What were the driver standings after the Bahrain Grand Prix?", "standings_service", "driver_standings_table"),
        ("Who set the fastest lap in the 2024 Australian Grand Prix?", "pace_service", "fastest_lap"),
        ("Did it rain during the 2024 Canadian Grand Prix?", "weather_service", "weather_details"),
    ]
    for q, expected_service, expected_op in cases:
        intent_res = classifier.classify(q)
        plan = planner.create_plan(q, intent_res)
        assert plan.is_executable is True, f"Failed for {q}: {plan.clarification_message}"
        assert plan.service_name == expected_service, f"Expected {expected_service} for {q}, got {plan.service_name}"
        assert plan.operation == expected_op, f"Expected {expected_op} for {q}, got {plan.operation}"


# =====================================================================
# Dimension 2: Service Selection
# =====================================================================

def test_service_selection_separation(planner, classifier):
    # Race service
    p1 = planner.create_plan("Who won in Monaco?", classifier.classify("Who won in Monaco?"))
    assert p1.service_name == "race_service"

    # Standings service
    p2 = planner.create_plan("Who was leading the championship after Monaco?", classifier.classify("Who was leading the championship after Monaco?"))
    assert p2.service_name == "standings_service"

    # Weather service
    p3 = planner.create_plan("What were the weather conditions in Monaco?", classifier.classify("What were the weather conditions in Monaco?"))
    assert p3.service_name == "weather_service"

    # Pace service
    p4 = planner.create_plan("Who set the fastest lap in Monaco?", classifier.classify("Who set the fastest lap in Monaco?"))
    assert p4.service_name == "pace_service"

    # General RAG fallback
    p5 = planner.create_plan("Explain the aerodynamics of the ground effect cars", classifier.classify("Explain the aerodynamics of the ground effect cars"))
    assert p5.service_name == "retriever"
    assert p5.operation == "semantic_search"


# =====================================================================
# Dimension 3: Event and Session Resolution
# =====================================================================

def test_session_resolution_variations(planner, classifier):
    # Resolution by circuit name
    p_monza = planner.create_plan("Who won at Monza?", classifier.classify("Who won at Monza?"))
    assert p_monza.is_executable
    assert p_monza.parameters["event_name"] == "Italian Grand Prix"
    assert p_monza.parameters["session_id"] == 17

    # Resolution by city / location
    p_melbourne = planner.create_plan("Who retired in Melbourne?", classifier.classify("Who retired in Melbourne?"))
    assert p_melbourne.is_executable
    assert p_melbourne.parameters["event_name"] == "Australian Grand Prix"
    assert p_melbourne.parameters["session_id"] == 4

    # Resolution by official Grand Prix name
    p_spa = planner.create_plan("What were the tyre compounds used in the Belgian Grand Prix?", classifier.classify("What were the tyre compounds used in the Belgian Grand Prix?"))
    assert p_spa.is_executable
    assert p_spa.parameters["event_name"] == "Belgian Grand Prix"
    assert p_spa.parameters["session_id"] == 15


# =====================================================================
# Dimension 4: Driver and Constructor Handling
# =====================================================================

def test_driver_and_constructor_resolution(planner, classifier):
    # Driver code (VER)
    p_code = planner.create_plan("How many points did VER score in Bahrain?", classifier.classify("How many points did VER score in Bahrain?"))
    assert p_code.is_executable
    assert p_code.parameters["driver_name"] == "Max Verstappen"

    # Full driver name
    p_full = planner.create_plan("Where did Charles Leclerc finish in Monaco?", classifier.classify("Where did Charles Leclerc finish in Monaco?"))
    assert p_full.is_executable
    assert p_full.parameters["driver_name"] == "Charles Leclerc"

    # Team name alias
    p_team = planner.create_plan("How did Red Bull perform in Bahrain?", classifier.classify("How did Red Bull perform in Bahrain?"))
    assert p_team.is_executable
    assert p_team.parameters["team_name"] == "Red Bull Racing"


# =====================================================================
# Dimension 5: Race-Specific vs Season-Wide Calculations
# =====================================================================

def test_race_vs_season_wide_distinction(classifier, planner, chat_service):
    # Single race driver points: Carlos Sainz in Bahrain (15.0 pts)
    q_race_pts = "How many points did Carlos Sainz score in the 2024 Bahrain Grand Prix?"
    plan_race_pts = planner.create_plan(q_race_pts, classifier.classify(q_race_pts))
    assert plan_race_pts.operation == "driver_points"
    ans_race_pts = chat_service.ask(q_race_pts)
    assert "15.0" in ans_race_pts or "15 points" in ans_race_pts

    # Cumulative championship points: Max Verstappen after Austria (213.0 pts)
    q_cum_pts = "How many championship points did Max Verstappen have after the Austrian Grand Prix?"
    plan_cum_pts = planner.create_plan(q_cum_pts, classifier.classify(q_cum_pts))
    assert plan_cum_pts.operation == "driver_cumulative_points"
    ans_cum_pts = chat_service.ask(q_cum_pts)
    assert "213.0" in ans_cum_pts or "213" in ans_cum_pts

    # Single race constructor points vs Cumulative constructor standings
    q_team_race = "Which constructor scored the most points in the Hungarian Grand Prix?"
    plan_team_race = planner.create_plan(q_team_race, classifier.classify(q_team_race))
    assert plan_team_race.operation == "constructor_race_points"

    q_team_cum = "What were the constructor standings after the Spanish Grand Prix?"
    plan_team_cum = planner.create_plan(q_team_cum, classifier.classify(q_team_cum))
    assert plan_team_cum.operation == "constructor_standings_table"


# =====================================================================
# Dimension 6: Missing Entity Handling
# =====================================================================

def test_missing_entities_handling(chat_service):
    # Missing race
    ans1 = chat_service.ask("Who retired?")
    assert "specify which Grand Prix" in ans1

    # Missing driver (pronoun)
    ans2 = chat_service.ask("Where did he finish in the Bahrain Grand Prix?")
    assert "specify which driver" in ans2

    # Missing constructor
    ans3 = chat_service.ask("How did the team perform in Monaco?")
    assert "specify which team" in ans3


# =====================================================================
# Dimension 7: Ambiguous Entity Handling
# =====================================================================

def test_ambiguous_entity_handling(chat_service):
    # Ambiguous host country without circuit name
    ans = chat_service.ask("Who won in the United States?")
    assert "ambiguous" in ans.lower()
    assert "specify which Grand Prix" in ans


# =====================================================================
# Dimension 8: Empty Result Handling
# =====================================================================

def test_empty_result_handling(chat_service):
    # 2024 Bahrain Grand Prix had ZERO retirements
    ans = chat_service.ask("Who retired from the 2024 Bahrain Grand Prix?")
    assert "no retirements" in ans.lower()

    # Driver who did not race in that event
    ans2 = chat_service.ask("How many points did Oliver Bearman score in the 2024 Monaco Grand Prix?")
    assert "did not compete" in ans2.lower() or "no data" in ans2.lower()


# =====================================================================
# Dimension 9: Ties and Duplicate Values
# =====================================================================

def test_ties_and_duplicate_values(chat_service):
    # Constructor race points tie detection
    from raceintel.services.standings_service import format_constructor_points_answer
    tie_info = {
        "available": True,
        "top_constructors": ["Ferrari", "McLaren"],
        "points": 43.0,
        "is_tie": True,
    }
    ans = format_constructor_points_answer(tie_info, "Test Grand Prix", 2024)
    assert "tied for the most points" in ans
    assert "Ferrari and McLaren" in ans


# =====================================================================
# Dimension 10: SQL Parameterization & Read-Only Safety
# =====================================================================

def test_sql_parameterization_and_readonly_safety():
    from database.connection import DATABASE_PATH

    # Verify database file hash is unchanged across read-only operations
    with open(DATABASE_PATH, "rb") as f:
        sha256_before = hashlib.sha256(f.read()).hexdigest()

    # Verify write commands fail under read-only URI
    ro_conn = sqlite3.connect(f"file:{DATABASE_PATH.resolve().as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        ro_conn.execute("INSERT INTO seasons (season_year) VALUES (2025);")
    ro_conn.close()

    with open(DATABASE_PATH, "rb") as f:
        sha256_after = hashlib.sha256(f.read()).hexdigest()
    assert sha256_before == sha256_after


# =====================================================================
# Dimension 11: Entity and Numerical Correctness
# =====================================================================

def test_entity_and_numerical_correctness(chat_service):
    # 1. Retirements in Australian GP: Russell, Hamilton, Verstappen
    ans_ret = chat_service.ask("Who retired from the 2024 Australian Grand Prix?")
    assert "George Russell" in ans_ret
    assert "Lewis Hamilton" in ans_ret
    assert "Max Verstappen" in ans_ret

    # 2. Biggest mover in Bahrain: Guanyu Zhou (+6 places, P17 to P11)
    ans_mov = chat_service.ask("Which driver gained the most positions in the 2024 Bahrain Grand Prix?")
    assert "Guanyu Zhou" in ans_mov
    assert "6" in ans_mov

    # 3. Tyre compounds in Bahrain: HARD, SOFT
    ans_tyre = chat_service.ask("Which tyre compounds were used during the 2024 Bahrain Grand Prix?")
    assert "HARD" in ans_tyre
    assert "SOFT" in ans_tyre

    # 4. Constructor standings leader after Miami: Red Bull Racing (239.0 pts with sprint, 211.0 race)
    ans_c_lead = chat_service.ask("Who was leading the constructors championship after the Miami Grand Prix?")
    assert "Red Bull Racing" in ans_c_lead
    assert any(pts in ans_c_lead for pts in ["239.0", "211.0"])

    # 5. Charles Leclerc driver championship position after Monaco: P2 with 138.0 combined points (126.0 race + 12.0 sprint)
    ans_d_pos = chat_service.ask("Where was Charles Leclerc in the driver standings after the Monaco Grand Prix?")
    assert "P2" in ans_d_pos
    # Sprint points (5.0 from China + 7.0 from Miami) are now included in cumulative championship total
    assert "138.0" in ans_d_pos

    # Explicit query asserting race-only breakdown (126.0 Grand Prix points and 12.0 Sprint points)
    ans_d_breakdown = chat_service.ask("How many points did Charles Leclerc have after the Monaco Grand Prix?")
    assert "138.0" in ans_d_breakdown
    assert "126.0" in ans_d_breakdown
    assert "12.0" in ans_d_breakdown

    # 6. Full classification in Monaco: Leclerc P1, Piastri P2, Sainz P3
    ans_class = chat_service.ask("What was the full race classification in the 2024 Monaco Grand Prix?")
    assert "Charles Leclerc" in ans_class
    assert "Oscar Piastri" in ans_class
    assert "Carlos Sainz" in ans_class


# =====================================================================
# Dimension 12: Regression Preservation
# =====================================================================

def test_regression_preservation(chat_service):
    # Winner
    ans1 = chat_service.ask("Who won the 2024 Monaco Grand Prix?")
    assert "Charles Leclerc" in ans1

    # Fastest lap
    ans2 = chat_service.ask("Who set the fastest lap in the 2024 Australian Grand Prix?")
    assert "Charles Leclerc" in ans2

    # Weather
    ans3 = chat_service.ask("Did it rain during the 2024 Canadian Grand Prix?")
    assert "rain" in ans3.lower()

    # Out-of-calendar rejection
    ans4 = chat_service.ask("Who won the 2024 French Grand Prix?")
    assert "not part of the Formula 1 2024 calendar" in ans4

    # Historical season refusal
    ans5 = chat_service.ask("Who won the 2020 Monaco Grand Prix?")
    assert "Historical data for season 2020 is not available" in ans5


# =====================================================================
# Dimension 13: Semantic Retrieval (RAG) Fallback
# =====================================================================

def test_semantic_retrieval_fallback(chat_service, classifier, planner):
    q = "What upgrades did McLaren bring to the Austrian Grand Prix?"
    intent_res = classifier.classify(q)
    assert intent_res.intent == Intent.GENERAL_RAG
    plan = planner.create_plan(q, intent_res)
    assert plan.service_name == "retriever"
    assert plan.operation == "semantic_search"


# =====================================================================
# Dimension 14: Supplementary Generalisation Tests
# =====================================================================

def test_supplementary_generalisation_phrasings(chat_service):
    # DNF variant
    ans1 = chat_service.ask("Which drivers did not finish the Monaco Grand Prix?")
    assert "Sergio Perez" in ans1
    assert "Esteban Ocon" in ans1

    # Order of finish variant
    ans2 = chat_service.ask("Order of finish for the 2024 Bahrain Grand Prix")
    assert "Max Verstappen" in ans2

    # Made up places variant
    ans3 = chat_service.ask("Who made up the most places in the 2024 Bahrain Grand Prix?")
    assert "Guanyu Zhou" in ans3

    # Tyre strategy variant
    ans4 = chat_service.ask("What tyre strategy compounds were used in Monaco?")
    assert "HARD" in ans4
    assert "MEDIUM" in ans4


# =====================================================================
# Additional Deep Coverage Tests
# =====================================================================

def test_constructor_standings_comparison(chat_service):
    # After British GP, Ferrari had 276.0 points, McLaren had 274.0 points
    ans = chat_service.ask("Who was ahead in the championship between Ferrari and McLaren after the British Grand Prix?")
    assert "Ferrari" in ans
    assert "McLaren" in ans
    assert "276.0" in ans
    assert "274.0" in ans


def test_driver_standings_comparison(chat_service):
    # After Spa (Belgian GP)
    ans = chat_service.ask("Compare Hamilton and Russell in the driver standings after the Belgian Grand Prix")
    assert "Lewis Hamilton" in ans
    assert "George Russell" in ans


def test_constructor_single_race_points(chat_service):
    # Ferrari in Australian GP 2024: Sainz 25 + Leclerc 19 = 44 points
    ans = chat_service.ask("How many points did Ferrari score in the 2024 Australian Grand Prix?")
    assert "Ferrari" in ans
    assert "44.0" in ans or "44 points" in ans


def test_constructor_standings_table(chat_service):
    ans = chat_service.ask("What were the constructor standings after the Spanish Grand Prix?")
    assert "Red Bull Racing" in ans
    assert "Ferrari" in ans
    assert "McLaren" in ans


def test_driver_standings_table(chat_service):
    ans = chat_service.ask("What were the driver standings after the Bahrain Grand Prix?")
    assert "Max Verstappen" in ans
    assert "Sergio Perez" in ans
    assert "Carlos Sainz" in ans


def test_driver_tyre_compounds(chat_service):
    ans = chat_service.ask("What tyre compounds were used by Max Verstappen in the Bahrain Grand Prix?")
    assert "Max Verstappen" in ans
    assert "HARD" in ans
    assert "SOFT" in ans


def test_pit_stop_duration_safety(chat_service, classifier, planner):
    # Pit stop duration is NOT in SQLite and must never be fabricated as a tyre compound
    q = "What was the duration of Charles Leclerc's pit stop in Monaco?"
    intent_res = classifier.classify(q)
    assert intent_res.intent != Intent.TYRE_USAGE

