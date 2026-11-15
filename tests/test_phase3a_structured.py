"""
Phase 3A Structured Intelligence & Retrieval Safety Tests.

Verifies:
1. SQLite-backed weather query capabilities and missing observation handling.
2. Fastest lap query capabilities, formatting, and missing value handling.
3. Cumulative driver standings after chronological events.
4. Constructor points aggregation for a race and tie handling.
5. Session resolution by event name, circuit, country, and season.
6. Ambiguity detection and clarification prompting.
7. Out-of-domain and relevance distance filtering.
8. ChatService routing to deterministic capabilities.
9. Baseline regression preservation.
"""

import pytest
from unittest.mock import MagicMock, patch

from raceintel.services.weather_service import (
    get_weather_details,
    format_weather_answer,
)
from raceintel.services.pace_service import (
    get_fastest_lap_for_session,
    format_fastest_lap_answer,
    format_lap_time,
)
from raceintel.services.standings_service import (
    get_driver_standings_after_event,
    get_driver_standings_leader_after_event,
    format_driver_standings_leader_answer,
    get_constructor_points_for_race,
    get_top_constructors_for_race,
    format_constructor_points_answer,
)
from raceintel.services.session_service import resolve_race_session
from raceintel.chat.chat_service import ChatService
from raceintel.retrieval.retriever import Retriever


# =====================================================================
# 1. Weather Queries & Missing Observations
# =====================================================================

def test_weather_details_dry_session():
    """Verify weather metrics for a known dry session (Bahrain GP, session 2)."""
    weather = get_weather_details(session_id=2)
    assert weather["available"] is True
    assert weather["has_rainfall"] is False
    assert weather["condition"] == "Dry"
    assert weather["rain_observations"] == 0
    assert weather["total_observations"] > 100
    assert weather["average_air_temperature"] == 18.2
    assert weather["peak_track_temperature"] == 26.5
    assert weather["air_temperature_range"] == (17.6, 18.9)


def test_weather_details_wet_session():
    """Verify weather metrics for a known wet session (Canadian GP, session 10)."""
    weather = get_weather_details(session_id=10)
    assert weather["available"] is True
    assert weather["has_rainfall"] is True
    assert weather["condition"] == "Wet"
    assert weather["rain_observations"] == 31
    assert weather["total_observations"] == 113
    assert weather["average_air_temperature"] == 17.8


def test_weather_details_missing_session():
    """Verify handling of missing weather observations (session 9999)."""
    weather = get_weather_details(session_id=9999)
    assert weather["available"] is False
    assert weather["total_observations"] == 0


def test_weather_formatting_rules():
    """Verify deterministic formatting rules for rain, condition, and temperatures."""
    dry_weather = get_weather_details(session_id=2)
    wet_weather = get_weather_details(session_id=10)

    # Rain questions
    dry_ans = format_weather_answer(dry_weather, "Did it rain during the 2024 Bahrain Grand Prix?", "Bahrain Grand Prix")
    assert "No, there was no rainfall" in dry_ans
    assert "dry" in dry_ans.lower()

    wet_ans = format_weather_answer(wet_weather, "Did it rain during the 2024 Canadian Grand Prix?", "Canadian Grand Prix")
    assert "Yes, rainfall was recorded" in wet_ans
    assert "31 rain observations" in wet_ans

    # Temperature questions
    temp_ans = format_weather_answer(dry_weather, "What was the average air temperature?", "Bahrain Grand Prix")
    assert "18.2" in temp_ans

    range_ans = format_weather_answer(dry_weather, "What was the air temperature range?", "Bahrain Grand Prix")
    assert "17.6" in range_ans
    assert "18.9" in range_ans

    track_ans = format_weather_answer(dry_weather, "What was the peak track temperature?", "Bahrain Grand Prix")
    assert "26.5" in track_ans

    # Missing session formatting
    missing_weather = {"available": False}
    missing_ans = format_weather_answer(missing_weather, "Did it rain?", "Test Grand Prix", 2024)
    assert "not available" in missing_ans


# =====================================================================
# 2. Fastest Lap Queries & Lap Time Handling
# =====================================================================

def test_fastest_lap_bahrain():
    """Verify fastest lap driver, lap number, and time for Bahrain GP."""
    fastest = get_fastest_lap_for_session(session_id=2)
    assert fastest is not None
    assert fastest["driver_full_name"] == "Max Verstappen"
    assert fastest["driver_code"] == "VER"
    assert fastest["lap_number"] == 39
    assert fastest["lap_time_seconds"] == 92.608
    assert fastest["formatted_lap_time"] == "1:32.608"


def test_fastest_lap_british_gp():
    """Verify fastest lap driver for British GP."""
    fastest = get_fastest_lap_for_session(session_id=13)
    assert fastest is not None
    assert fastest["driver_full_name"] == "Carlos Sainz"
    assert fastest["driver_code"] == "SAI"
    assert fastest["lap_number"] == 52
    assert fastest["formatted_lap_time"] == "1:28.293"


def test_fastest_lap_missing_session():
    """Verify handling of sessions with no recorded laps."""
    fastest = get_fastest_lap_for_session(session_id=9999)
    assert fastest is None
    ans = format_fastest_lap_answer(fastest, "Test GP", 2024)
    assert "not available" in ans


def test_format_lap_time_helper():
    """Verify lap time formatting utility."""
    assert format_lap_time(92.608) == "1:32.608"
    assert format_lap_time(59.123) == "59.123s"
    assert format_lap_time(None) == "N/A"


# =====================================================================
# 3. Driver Standings & Cumulative Chronology
# =====================================================================

def test_driver_standings_after_bahrain():
    """Verify cumulative driver standings after Round 1 (Bahrain GP)."""
    standings = get_driver_standings_after_event(session_id=2, season=2024)
    assert len(standings) > 0
    leader = standings[0]
    assert leader["driver_full_name"] == "Max Verstappen"
    assert leader["total_points"] == 26.0

    p2 = standings[1]
    assert p2["driver_full_name"] == "Sergio Perez"
    assert p2["total_points"] == 18.0


def test_driver_standings_after_british_gp():
    """Verify cumulative driver standings after Round 12 (British GP)."""
    standings = get_driver_standings_after_event(session_id=13, season=2024)
    assert len(standings) > 0
    leader = standings[0]
    assert leader["driver_full_name"] == "Max Verstappen"
    assert leader["race_points"] == 231.0
    assert leader["sprint_points"] == 24.0
    assert leader["total_points"] == 255.0

    p2 = standings[1]
    assert p2["driver_full_name"] == "Lando Norris"
    assert p2["race_points"] == 162.0
    assert p2["sprint_points"] == 9.0
    assert p2["total_points"] == 171.0

    # Monotonic accumulation: Verstappen points at Round 12 must exceed Round 1
    r1_standings = get_driver_standings_after_event(session_id=2, season=2024)
    assert leader["total_points"] > r1_standings[0]["total_points"]


def test_driver_standings_leader_formatter():
    """Verify leader response formatting."""
    leader = {"driver_full_name": "Max Verstappen", "total_points": 26.0}
    ans = format_driver_standings_leader_answer(leader, "Bahrain Grand Prix")
    assert "Max Verstappen leads the driver standings" in ans
    assert "26.0 points" in ans


# =====================================================================
# 4. Constructor Points Aggregation & Ties
# =====================================================================

def test_constructor_points_bahrain():
    """Verify constructor points aggregation for Bahrain GP (Red Bull clear winner)."""
    top_info = get_top_constructors_for_race(session_id=2)
    assert top_info["available"] is True
    assert top_info["is_tie"] is False
    assert top_info["top_constructors"] == ["Red Bull Racing"]
    assert top_info["points"] == 44.0

    ans = format_constructor_points_answer(top_info, "Bahrain Grand Prix")
    assert "Red Bull Racing scored the most points in the Bahrain Grand Prix with 44.0 points" in ans


def test_constructor_points_canadian_gp_tie():
    """Verify constructor points tie handling for Canadian GP (McLaren & Mercedes tied at 28 pts)."""
    top_info = get_top_constructors_for_race(session_id=10)
    assert top_info["available"] is True
    assert top_info["is_tie"] is True
    assert set(top_info["top_constructors"]) == {"McLaren", "Mercedes"}
    assert top_info["points"] == 28.0

    ans = format_constructor_points_answer(top_info, "Canadian Grand Prix")
    assert "tied for the most points" in ans
    assert "McLaren" in ans
    assert "Mercedes" in ans
    assert "28.0 points each" in ans


# =====================================================================
# 5. Session & Event Resolution
# =====================================================================

def test_resolve_race_session():
    """Verify resolving varied race query strings to official database sessions."""
    res_bahr = resolve_race_session("Bahrain Grand Prix", 2024)
    assert res_bahr["found"] is True
    assert res_bahr["session_id"] == 2

    res_short = resolve_race_session("Bahrain", 2024)
    assert res_short["found"] is True
    assert res_short["session_id"] == 2

    res_accent = resolve_race_session("São Paulo Grand Prix", 2024)
    assert res_accent["found"] is True
    assert res_accent["session_id"] == 22

    res_no_accent = resolve_race_session("Sao Paulo", 2024)
    assert res_no_accent["found"] is True
    assert res_no_accent["session_id"] == 22

    # Unavailable historical season
    res_hist = resolve_race_session("Monaco Grand Prix", 2021)
    assert res_hist["found"] is False
    assert res_hist["reason"] == "season_not_found"

    # Out-of-calendar race
    res_indy = resolve_race_session("Indianapolis 500", 2024)
    assert res_indy["found"] is False
    assert res_indy["reason"] == "event_not_found"


# =====================================================================
# 6. Ambiguity Detection
# =====================================================================

def test_ambiguity_detection_unspecified_race():
    """Verify that questions lacking a race are flagged as ambiguous."""
    retriever = Retriever()
    filters = retriever._extract_filters("Who won the race?")
    assert retriever._is_ambiguous_query("Who won the race?", filters) is True

    filters_podium = retriever._extract_filters("Who finished on the podium?")
    assert retriever._is_ambiguous_query("Who finished on the podium?", filters_podium) is True


def test_ambiguity_detection_unspecified_driver():
    """Verify that questions using pronouns without a driver are flagged as ambiguous."""
    retriever = Retriever()
    filters_pos = retriever._extract_filters("What position did he finish?")
    assert retriever._is_ambiguous_query("What position did he finish?", filters_pos) is True

    filters_pts = retriever._extract_filters("How many points did the driver score in Canada?")
    assert retriever._is_ambiguous_query("How many points did the driver score in Canada?", filters_pts) is True


def test_ambiguity_detection_unambiguous_queries():
    """Verify that well-specified queries are NOT flagged as ambiguous."""
    retriever = Retriever()
    f1 = retriever._extract_filters("Who won the Monaco Grand Prix?")
    assert retriever._is_ambiguous_query("Who won the Monaco Grand Prix?", f1) is False

    f2 = retriever._extract_filters("What position did Charles Leclerc finish in Monaco?")
    assert retriever._is_ambiguous_query("What position did Charles Leclerc finish in Monaco?", f2) is False


# =====================================================================
# 7. ChatService End-to-End Routing
# =====================================================================

def test_chatservice_weather_routing():
    """Verify ChatService routes weather questions to deterministic answers."""
    service = ChatService()
    ans_rain = service.ask("Did it rain during the 2024 Canadian Grand Prix?")
    assert "Yes" in ans_rain
    assert "rainfall" in ans_rain.lower()

    ans_dry = service.ask("Did it rain during the 2024 Bahrain Grand Prix?")
    assert "No" in ans_dry
    assert "dry" in ans_dry.lower()

    ans_temp = service.ask("What was the average air temperature during the 2024 Bahrain Grand Prix?")
    assert "18.2" in ans_temp


def test_chatservice_fastest_lap_routing():
    """Verify ChatService routes fastest lap questions deterministically."""
    service = ChatService()
    ans = service.ask("Who set the fastest lap in the 2024 Bahrain Grand Prix?")
    assert "Max Verstappen" in ans
    assert "1:32.608" in ans


def test_chatservice_standings_leader_routing():
    """Verify ChatService routes standings leader questions deterministically."""
    service = ChatService()
    ans = service.ask("Who leads the driver standings after the Bahrain Grand Prix?")
    assert "Max Verstappen" in ans
    assert "26.0 points" in ans


def test_chatservice_constructor_points_routing():
    """Verify ChatService routes constructor points without confusing with driver points."""
    service = ChatService()
    ans = service.ask("Which constructor scored the most points in the Bahrain Grand Prix?")
    assert "Red Bull Racing" in ans
    assert "44.0 points" in ans
    assert "Max Verstappen" not in ans  # Must NOT return driver name!


def test_chatservice_ambiguous_handling():
    """Verify ChatService requests clarification on ambiguous queries."""
    service = ChatService()
    ans_race = service.ask("Who won the race?")
    assert "ambiguous" in ans_race.lower()
    assert "specify" in ans_race.lower()

    ans_driver = service.ask("What position did he finish?")
    assert "ambiguous" in ans_driver.lower()
    assert "specify which driver" in ans_driver.lower()


def test_chatservice_out_of_domain_unanswerable():
    """Verify ChatService does not hallucinate answers to out-of-domain races."""
    service = ChatService()
    ans_indy = service.ask("Who won the 2024 Indianapolis 500?")
    assert any(p in ans_indy.lower() for p in ["not part of", "couldn't find", "not available"])
    assert "Hungarian" not in ans_indy  # Must NOT substitute Hungarian GP!


def test_chatservice_historical_season_refusal():
    """Verify ChatService refuses historical seasons honestly."""
    service = ChatService()
    ans_2021 = service.ask("Who won the 2021 Monaco Grand Prix?")
    assert any(p in ans_2021.lower() for p in ["not available", "couldn't find"])
