"""
Tests for RaceIntel Phase 5A: Event Resolution Correctness.

Covers all required Phase 5A scenarios using isolated temporary SQLite databases
plus non-mutating regression checks:
1. United States GP vs Miami GP (explicit event never overridden by country).
2. Multiple Grand Prix events hosted in the same country (USA, Italy).
3. Italy vs Emilia Romagna GP.
4. Explicit event name vs country alias.
5. Circuit name vs event name (including circuit winning over enclosing country).
6. Venue alias resolution (COTA, Interlagos, Red Bull Ring, Hungaroring, etc.).
7. Event resolution with a specified season (multi-season disambiguation).
8. Event resolution without a specified season.
9. Unknown event names.
10. Unsupported seasons.
11. Ambiguous event references.
12. Existing event resolution regression cases & end-to-end QueryPlanner/ChatService checks.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from raceintel.chat.chat_service import ChatService
from raceintel.routing.entity_registry import EntityRegistry
from raceintel.routing.intent_classifier import Intent, IntentClassifier
from raceintel.routing.query_planner import QueryPlanner
from raceintel.services.session_service import resolve_race_session


@pytest.fixture
def temp_multi_season_db(tmp_path):
    """Create an isolated temporary SQLite database with multi-race countries and two seasons."""
    db_file = tmp_path / "phase5a_test.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE seasons (
            season_id INTEGER PRIMARY KEY,
            season_year INTEGER UNIQUE NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE constructors (
            constructor_id INTEGER PRIMARY KEY,
            constructor_name TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE drivers (
            driver_id INTEGER PRIMARY KEY,
            driver_code TEXT,
            driver_number INTEGER,
            driver_full_name TEXT NOT NULL,
            constructor_id INTEGER
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY,
            season_id INTEGER NOT NULL,
            event_name TEXT NOT NULL,
            country_name TEXT,
            circuit_name TEXT,
            FOREIGN KEY (season_id) REFERENCES seasons(season_id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL,
            session_type TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(event_id)
        );
        """
    )

    cur.execute("INSERT INTO seasons (season_id, season_year) VALUES (1, 2023), (2, 2024);")
    cur.execute(
        "INSERT INTO constructors (constructor_id, constructor_name) VALUES (1, 'Ferrari'), (2, 'Red Bull Racing'), (3, 'McLaren');"
    )
    cur.execute(
        """
        INSERT INTO drivers (driver_id, driver_code, driver_number, driver_full_name, constructor_id) VALUES
        (1, 'VER', 1, 'Max Verstappen', 2),
        (2, 'LEC', 16, 'Charles Leclerc', 1),
        (3, 'NOR', 4, 'Lando Norris', 3);
        """
    )

    # 2023 has only Italian GP in Italy, Monaco GP, and Portuguese GP (unique to 2023)
    # 2024 deliberately puts Miami GP (session_id=7) BEFORE United States GP (session_id=20)
    # and Emilia Romagna GP (session_id=8) BEFORE Italian GP (session_id=17),
    # mirroring real chronological ordering that caused the Phase 4E bug.
    cur.execute(
        """
        INSERT INTO events (event_id, season_id, event_name, country_name, circuit_name) VALUES
        (101, 1, 'Portuguese Grand Prix', 'Portugal', 'Portimao'),
        (102, 1, 'Italian Grand Prix', 'Italy', 'Monza'),
        (103, 1, 'Monaco Grand Prix', 'Monaco', 'Monaco'),
        (2, 2, 'Bahrain Grand Prix', 'Bahrain', 'Sakhir'),
        (7, 2, 'Miami Grand Prix', 'United States', 'Miami'),
        (8, 2, 'Emilia Romagna Grand Prix', 'Italy', 'Imola'),
        (9, 2, 'Monaco Grand Prix', 'Monaco', 'Monaco'),
        (10, 2, 'Canadian Grand Prix', 'Canada', 'Montr\ufffdal'),
        (17, 2, 'Italian Grand Prix', 'Italy', 'Monza'),
        (19, 2, 'United States Grand Prix', 'United States', 'Austin'),
        (21, 2, 'S\ufffdo Paulo Grand Prix', 'Brazil', 'S\ufffdo Paulo'),
        (22, 2, 'Las Vegas Grand Prix', 'United States', 'Las Vegas');
        """
    )
    cur.execute(
        """
        INSERT INTO sessions (session_id, event_id, session_type) VALUES
        (101, 101, 'Race'),
        (102, 102, 'Race'),
        (103, 103, 'Race'),
        (2, 2, 'Race'),
        (7, 7, 'Race'),
        (8, 8, 'Race'),
        (9, 9, 'Race'),
        (10, 10, 'Race'),
        (17, 17, 'Race'),
        (20, 19, 'Race'),
        (22, 21, 'Race'),
        (23, 22, 'Race');
        """
    )

    conn.commit()
    conn.close()
    return db_file


# =====================================================================
# 1. United States GP vs Miami GP & Multi-Event Same Country
# =====================================================================

def test_us_gp_vs_miami_gp_resolution(temp_multi_season_db):
    """Explicit United States Grand Prix must never resolve to Miami GP (earlier session_id)."""
    res_us = resolve_race_session("United States Grand Prix", season=2024, db_path=temp_multi_season_db)
    assert res_us["found"] is True
    assert res_us["session_id"] == 20
    assert res_us["event_name"] == "United States Grand Prix"
    assert res_us["circuit_name"] == "Austin"

    res_miami = resolve_race_session("Miami Grand Prix", season=2024, db_path=temp_multi_season_db)
    assert res_miami["found"] is True
    assert res_miami["session_id"] == 7
    assert res_miami["event_name"] == "Miami Grand Prix"

    res_vegas = resolve_race_session("Las Vegas Grand Prix", season=2024, db_path=temp_multi_season_db)
    assert res_vegas["found"] is True
    assert res_vegas["session_id"] == 23
    assert res_vegas["event_name"] == "Las Vegas Grand Prix"


def test_explicit_event_aliases_over_country(temp_multi_season_db):
    """US GP / USA GP are event-specific aliases resolving to United States Grand Prix."""
    for alias in ("United States GP", "US Grand Prix", "US GP", "USA GP", "2024 United States Grand Prix"):
        res = resolve_race_session(alias, season=2024, db_path=temp_multi_season_db)
        assert res["found"] is True, f"Failed for alias={alias}: {res}"
        assert res["session_id"] == 20
        assert res["event_name"] == "United States Grand Prix"


def test_bare_country_with_multiple_events_is_ambiguous(temp_multi_season_db):
    """Bare 'United States' / 'USA' / 'Italy' with multiple 2024 events must return ambiguous_event."""
    for country in ("United States", "USA"):
        res = resolve_race_session(country, season=2024, db_path=temp_multi_season_db)
        assert res["found"] is False
        assert res["reason"] == "ambiguous_event"
        assert set(res["candidates"]) == {"Miami Grand Prix", "United States Grand Prix", "Las Vegas Grand Prix"}

    res_italy = resolve_race_session("Italy", season=2024, db_path=temp_multi_season_db)
    assert res_italy["found"] is False
    assert res_italy["reason"] == "ambiguous_event"
    assert set(res_italy["candidates"]) == {"Emilia Romagna Grand Prix", "Italian Grand Prix"}


# =====================================================================
# 2. Italy vs Emilia Romagna GP & Country Fallback
# =====================================================================

def test_italy_vs_emilia_romagna_resolution(temp_multi_season_db):
    """Explicit Italian Grand Prix vs Emilia Romagna Grand Prix must never collide."""
    res_italian = resolve_race_session("Italian Grand Prix", season=2024, db_path=temp_multi_season_db)
    assert res_italian["found"] is True
    assert res_italian["session_id"] == 17
    assert res_italian["event_name"] == "Italian Grand Prix"

    res_emilia = resolve_race_session("Emilia Romagna Grand Prix", season=2024, db_path=temp_multi_season_db)
    assert res_emilia["found"] is True
    assert res_emilia["session_id"] == 8
    assert res_emilia["event_name"] == "Emilia Romagna Grand Prix"

    # Unambiguous single-race country fallback still resolves cleanly
    res_brazil = resolve_race_session("Brazil", season=2024, db_path=temp_multi_season_db)
    assert res_brazil["found"] is True
    assert res_brazil["session_id"] == 22
    assert res_brazil["resolution_stage"] == "country_fallback"


# =====================================================================
# 3. Circuit Name & Venue Alias Resolution
# =====================================================================

def test_circuit_and_venue_alias_resolution(temp_multi_season_db):
    """Circuit names and venue aliases resolve accurately and beat enclosing country aliases."""
    assert resolve_race_session("Austin", season=2024, db_path=temp_multi_season_db)["event_name"] == "United States Grand Prix"
    assert resolve_race_session("COTA", season=2024, db_path=temp_multi_season_db)["event_name"] == "United States Grand Prix"
    assert resolve_race_session("Circuit of the Americas", season=2024, db_path=temp_multi_season_db)["event_name"] == "United States Grand Prix"
    assert resolve_race_session("Imola", season=2024, db_path=temp_multi_season_db)["event_name"] == "Emilia Romagna Grand Prix"
    assert resolve_race_session("Autodromo Enzo e Dino Ferrari", season=2024, db_path=temp_multi_season_db)["event_name"] == "Emilia Romagna Grand Prix"
    assert resolve_race_session("Monza", season=2024, db_path=temp_multi_season_db)["event_name"] == "Italian Grand Prix"
    assert resolve_race_session("Interlagos", season=2024, db_path=temp_multi_season_db)["session_id"] == 22
    assert resolve_race_session("Circuit Gilles Villeneuve", season=2024, db_path=temp_multi_season_db)["session_id"] == 10

    # Circuit mentioned alongside enclosing ambiguous country must still pick the circuit's event
    res_circuit_plus_country = resolve_race_session("Imola in Italy", season=2024, db_path=temp_multi_season_db)
    assert res_circuit_plus_country["found"] is True
    assert res_circuit_plus_country["event_name"] == "Emilia Romagna Grand Prix"

    registry = EntityRegistry(db_path=temp_multi_season_db)
    reg_res = registry.resolve_event("at COTA in the United States")
    assert reg_res.matched is True
    assert reg_res.event_name == "United States Grand Prix"


# =====================================================================
# 4. Season-Aware & Seasonless Resolution
# =====================================================================

def test_season_aware_and_seasonless_resolution(temp_multi_season_db):
    """Requested season disambiguates country/events; season=None avoids arbitrary first-pick."""
    # In 2023, Italy only hosts Italian GP -> country 'Italy' resolves unambiguously
    res_italy_2023 = resolve_race_session("Italy", season=2023, db_path=temp_multi_season_db)
    assert res_italy_2023["found"] is True
    assert res_italy_2023["season_year"] == 2023
    assert res_italy_2023["session_id"] == 102

    # In 2024, Italy hosts two races -> ambiguous
    res_italy_2024 = resolve_race_session("Italy", season=2024, db_path=temp_multi_season_db)
    assert res_italy_2024["found"] is False
    assert res_italy_2024["reason"] == "ambiguous_event"

    # Without season specified: event unique to one season resolves deterministically
    res_portugal = resolve_race_session("Portuguese Grand Prix", season=None, db_path=temp_multi_season_db)
    assert res_portugal["found"] is True
    assert res_portugal["season_year"] == 2023
    assert res_portugal["session_id"] == 101

    res_us_none = resolve_race_session("United States Grand Prix", season=None, db_path=temp_multi_season_db)
    assert res_us_none["found"] is True
    assert res_us_none["season_year"] == 2024
    assert res_us_none["session_id"] == 20

    # Without season specified: event present in BOTH 2023 and 2024 must NOT arbitrarily pick session_id ASC
    res_monaco_none = resolve_race_session("Monaco Grand Prix", season=None, db_path=temp_multi_season_db)
    assert res_monaco_none["found"] is False
    assert res_monaco_none["reason"] == "ambiguous_season"
    assert set(res_monaco_none["available_seasons"]) == {2023, 2024}


# =====================================================================
# 5. Unknown Events, Unsupported Seasons, Multi-Event Phrases & Regressions
# =====================================================================

def test_unknown_events_and_unsupported_seasons(temp_multi_season_db):
    """Unknown events and missing seasons return explicit failure reasons."""
    res_unk = resolve_race_session("Swiss Grand Prix", season=2024, db_path=temp_multi_season_db)
    assert res_unk["found"] is False
    assert res_unk["reason"] == "event_not_found"

    res_bad_season = resolve_race_session("Monaco Grand Prix", season=2020, db_path=temp_multi_season_db)
    assert res_bad_season["found"] is False
    assert res_bad_season["reason"] == "season_not_found"

    res_ambig_phrase = resolve_race_session(
        "Miami Grand Prix vs United States Grand Prix", season=2024, db_path=temp_multi_season_db
    )
    assert res_ambig_phrase["found"] is False
    assert res_ambig_phrase["reason"] == "ambiguous_event"


def test_existing_regressions_and_query_planner_us_gp(temp_multi_season_db):
    """Regressions (Bahrain, Sao Paulo, Montreal) and QueryPlanner US GP session_id match ground truth."""
    assert resolve_race_session("Bahrain Grand Prix", 2024, db_path=temp_multi_season_db)["session_id"] == 2
    assert resolve_race_session("Bahrain", 2024, db_path=temp_multi_season_db)["session_id"] == 2
    assert resolve_race_session("São Paulo Grand Prix", 2024, db_path=temp_multi_season_db)["session_id"] == 22
    assert resolve_race_session("Sao Paulo", 2024, db_path=temp_multi_season_db)["session_id"] == 22
    assert resolve_race_session("Montréal", 2024, db_path=temp_multi_season_db)["session_id"] == 10

    registry = EntityRegistry(db_path=temp_multi_season_db)
    classifier = IntentClassifier(registry=registry)
    planner = QueryPlanner(registry=registry)

    for q in (
        "Who finished on the podium in the 2024 United States Grand Prix?",
        "Who won the US GP in 2024?",
        "How did Charles Leclerc do at COTA in the United States in 2024?",
    ):
        ires = classifier.classify(q)
        assert ires.is_ambiguous is False, f"Unexpected ambiguity on: {q}"
        plan = planner.create_plan(q, ires)
        assert plan.is_executable is True
        assert plan.parameters["session_id"] == 20
        assert plan.parameters["event_name"] == "United States Grand Prix"

    # Ambiguous country via classifier/planner asks for clarification instead of arbitrary session
    ambig_q = "Who won in the US in 2024?"
    ambig_res = classifier.classify(ambig_q)
    assert ambig_res.intent == Intent.AMBIGUOUS
    assert ambig_res.is_ambiguous is True


def test_production_read_only_us_gp_end_to_end():
    """Verify against real production DB (read-only) that US GP podium & points != Miami GP."""
    us_session = resolve_race_session("United States Grand Prix", season=2024)
    miami_session = resolve_race_session("Miami Grand Prix", season=2024)
    assert us_session["found"] is True and us_session["session_id"] == 20
    assert miami_session["found"] is True and miami_session["session_id"] == 7

    mock_retriever = MagicMock()
    service = ChatService(retriever=mock_retriever, offline=True)

    podium_ans = service.ask("Who finished on the podium in the 2024 United States Grand Prix?")
    assert "Charles Leclerc" in podium_ans
    assert "Carlos Sainz" in podium_ans
    assert "Max Verstappen" in podium_ans
    assert "Lando Norris" not in podium_ans

    ferrari_ans = service.ask("How many points did Ferrari score in the 2024 United States Grand Prix?")
    assert "United States Grand Prix" in ferrari_ans
    assert "43" in ferrari_ans
    assert "Miami" not in ferrari_ans
