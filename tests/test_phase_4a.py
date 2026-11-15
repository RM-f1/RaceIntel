"""
Tests for RaceIntel Phase 4A: EntityRegistry and Early DomainGuard.

Covers all 14 required capabilities:
1. Dynamic event loading from SQLite.
2. Dynamic circuit loading.
3. Dynamic driver and constructor loading.
4. Driver aliases and normalization.
5. Valid F1 questions using circuit names.
6. Unsupported season handling.
7. Explicit MotoGP rejection.
8. Explicit NASCAR rejection.
9. Explicit WEC rejection.
10. Bathurst 1000 rejection.
11. F1 comparison questions mentioning another motorsport.
12. Ambiguous entity resolution.
13. DomainGuard execution before ChromaDB retrieval.
14. No regressions in existing structured queries.
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from raceintel.chat.chat_service import ChatService
from raceintel.routing.domain_guard import DomainGuard, DomainStatus
from raceintel.routing.entity_registry import EntityRegistry


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary SQLite database with a custom schema for isolated testing."""
    db_file = tmp_path / "test_raceintel.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    # Create tables matching production schema
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
        CREATE TABLE drivers (
            driver_id INTEGER PRIMARY KEY,
            driver_code TEXT,
            driver_number INTEGER,
            driver_full_name TEXT NOT NULL,
            constructor_id INTEGER,
            FOREIGN KEY (constructor_id) REFERENCES constructors(constructor_id)
        );
        """
    )

    # Seed with test data including unique custom entities
    cur.execute("INSERT INTO seasons (season_id, season_year) VALUES (1, 2024), (2, 2025);")
    cur.execute(
        """
        INSERT INTO constructors (constructor_id, constructor_name) VALUES 
        (1, 'Ferrari'),
        (2, 'Red Bull Racing'),
        (3, 'Custom Racing Team');
        """
    )
    cur.execute(
        """
        INSERT INTO events (event_id, season_id, event_name, country_name, circuit_name) VALUES 
        (1, 1, 'Italian Grand Prix', 'Italy', 'Monza'),
        (2, 1, 'Emilia Romagna Grand Prix', 'Italy', 'Imola'),
        (3, 1, 'British Grand Prix', 'United Kingdom', 'Silverstone'),
        (4, 2, 'Future Grand Prix', 'Atlantis', 'Custom Circuit');
        """
    )
    cur.execute(
        """
        INSERT INTO drivers (driver_id, driver_code, driver_number, driver_full_name, constructor_id) VALUES 
        (1, 'HAM', 44, 'Lewis Hamilton', 1),
        (2, 'VER', 1, 'Max Verstappen', 2),
        (3, 'BEA', 38, 'Oliver Bearman', 1),
        (4, 'TST', 99, 'Test Driver', 3);
        """
    )

    conn.commit()
    conn.close()
    return db_file


# =====================================================================
# 1. Dynamic event loading from SQLite
# =====================================================================

def test_dynamic_event_loading_from_sqlite(temp_db_path):
    """Verify that EntityRegistry loads events dynamically from the specified SQLite database."""
    registry = EntityRegistry(db_path=temp_db_path)
    assert len(registry.events) == 4

    future_res = registry.resolve_event("Future Grand Prix")
    assert future_res.matched is True
    assert future_res.event_name == "Future Grand Prix"
    assert future_res.country_name == "Atlantis"
    assert future_res.circuit_name == "Custom Circuit"


# =====================================================================
# 2. Dynamic circuit loading
# =====================================================================

def test_dynamic_circuit_loading(temp_db_path):
    """Verify that circuits resolve dynamically to their corresponding canonical events."""
    registry = EntityRegistry(db_path=temp_db_path)

    monza_res = registry.resolve_circuit("Monza")
    assert monza_res.matched is True
    assert monza_res.canonical_event == "Italian Grand Prix"
    assert monza_res.circuit_name == "Monza"

    silverstone_res = registry.resolve_circuit("Silverstone")
    assert silverstone_res.matched is True
    assert silverstone_res.canonical_event == "British Grand Prix"

    custom_circ = registry.resolve_circuit("Custom Circuit")
    assert custom_circ.matched is True
    assert custom_circ.canonical_event == "Future Grand Prix"


# =====================================================================
# 3. Dynamic driver and constructor loading
# =====================================================================

def test_dynamic_driver_and_constructor_loading(temp_db_path):
    """Verify that drivers and constructors are loaded dynamically from SQLite."""
    registry = EntityRegistry(db_path=temp_db_path)

    # Custom driver from temp database
    test_d = registry.resolve_driver("Test Driver")
    assert test_d.matched is True
    assert test_d.driver_full_name == "Test Driver"
    assert test_d.driver_code == "TST"

    # Custom constructor from temp database
    test_c = registry.resolve_constructor("Custom Racing Team")
    assert test_c.matched is True
    assert test_c.constructor_name == "Custom Racing Team"


# =====================================================================
# 4. Driver aliases and normalization
# =====================================================================

def test_driver_aliases_and_normalization():
    """Verify driver diacritic stripping, nicknames, reserve drivers, and code lookup."""
    registry = EntityRegistry()  # Production read-only instance

    # Diacritic normalization
    perez_res = registry.resolve_driver("Pérez")
    assert perez_res.matched is True
    assert perez_res.driver_full_name == "Sergio Perez"

    # Nicknames
    checo_res = registry.resolve_driver("Checo")
    assert checo_res.matched is True
    assert checo_res.driver_full_name == "Sergio Perez"

    hulk_res = registry.resolve_driver("Hulk")
    assert hulk_res.matched is True
    assert hulk_res.driver_full_name == "Nico Hulkenberg"

    # Reserve drivers in 2024 official roster
    bearman_res = registry.resolve_driver("Bearman")
    assert bearman_res.matched is True
    assert bearman_res.driver_full_name == "Oliver Bearman"

    colapinto_res = registry.resolve_driver("Colapinto")
    assert colapinto_res.matched is True
    assert colapinto_res.driver_full_name == "Franco Colapinto"

    lawson_res = registry.resolve_driver("Liam Lawson")
    assert lawson_res.matched is True
    assert lawson_res.driver_full_name == "Liam Lawson"

    doohan_res = registry.resolve_driver("DOO")
    assert doohan_res.matched is True
    assert doohan_res.driver_full_name == "Jack Doohan"


# =====================================================================
# 5. Valid F1 questions using circuit names
# =====================================================================

def test_valid_f1_questions_using_circuit_names():
    """Verify that questions referencing circuits (Monza, Silverstone, Spa) are recognized as valid."""
    dg = DomainGuard()

    q1 = "Did rainfall occur during the 2024 Italian Grand Prix at Monza?"
    res1 = dg.validate(q1)
    assert res1.is_valid is True
    assert res1.status == DomainStatus.VALID

    q2 = "Who clocked the fastest lap at Silverstone in 2024?"
    res2 = dg.validate(q2)
    assert res2.is_valid is True

    q3 = "Was the track wet or dry at Spa-Francorchamps?"
    res3 = dg.validate(q3)
    assert res3.is_valid is True


# =====================================================================
# 6. Unsupported season handling
# =====================================================================

def test_unsupported_season_handling():
    """Verify that questions for historical/unsupported seasons are rejected with clear message."""
    dg = DomainGuard()

    q_2020 = "Who won the 2020 Italian Grand Prix?"
    res_2020 = dg.validate(q_2020)
    assert res_2020.is_valid is False
    assert res_2020.status == DomainStatus.UNSUPPORTED_SEASON
    assert res_2020.season == 2020
    assert "Historical data for season 2020 is not available" in res_2020.refusal_message

    q_2018 = "What was the race result of the 2018 Monaco Grand Prix?"
    res_2018 = dg.validate(q_2018)
    assert res_2018.is_valid is False
    assert res_2018.status == DomainStatus.UNSUPPORTED_SEASON
    assert "Historical data for season 2018 is not available" in res_2018.refusal_message


# =====================================================================
# 7. Explicit MotoGP rejection
# =====================================================================

def test_explicit_motogp_rejection():
    """Verify that MotoGP questions are rejected prior to retrieval."""
    dg = DomainGuard()

    q = "Who won the 2024 MotoGP World Championship?"
    res = dg.validate(q)
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT
    assert "not part of the Formula 1 2024 calendar" in res.refusal_message


# =====================================================================
# 8. Explicit NASCAR rejection
# =====================================================================

def test_explicit_nascar_rejection():
    """Verify that NASCAR and Daytona 500 questions are rejected."""
    dg = DomainGuard()

    q1 = "Who won the 2024 NASCAR Cup Series?"
    res1 = dg.validate(q1)
    assert res1.is_valid is False
    assert res1.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT

    q2 = "What was the result of the Daytona 500?"
    res2 = dg.validate(q2)
    assert res2.is_valid is False
    assert res2.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT


# =====================================================================
# 9. Explicit WEC rejection
# =====================================================================

def test_explicit_wec_rejection():
    """Verify that WEC and 24 Hours of Le Mans inquiries are rejected."""
    dg = DomainGuard()

    q1 = "Who won the 2024 24 Hours of Le Mans in WEC?"
    res1 = dg.validate(q1)
    assert res1.is_valid is False
    assert res1.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT

    q2 = "Who is leading the 2024 World Endurance Championship?"
    res2 = dg.validate(q2)
    assert res2.is_valid is False
    assert res2.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT


# =====================================================================
# 10. Bathurst 1000 rejection
# =====================================================================

def test_bathurst_1000_rejection():
    """Verify that Bathurst 1000 and Australian Supercars questions are rejected."""
    dg = DomainGuard()

    q = "Who won the 2024 Bathurst 1000?"
    res = dg.validate(q)
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT
    assert "not part of the Formula 1 2024 calendar" in res.refusal_message


# =====================================================================
# 11. F1 comparison questions mentioning another motorsport
# =====================================================================

def test_f1_comparison_questions_mentioning_another_motorsport():
    """Verify that valid F1 inquiries mentioning another racing series for comparison are NOT rejected."""
    dg = DomainGuard()

    q1 = "How do 2024 Formula 1 cornering speeds at Silverstone compare to NASCAR?"
    res1 = dg.validate(q1)
    assert res1.is_valid is True
    assert res1.status == DomainStatus.VALID

    q2 = "Did Lewis Hamilton perform better in Formula 1 compared to his NASCAR tests?"
    res2 = dg.validate(q2)
    assert res2.is_valid is True
    assert res2.status == DomainStatus.VALID

    q3 = "How fast are F1 top speeds at Monza in 2024 compared to MotoGP?"
    res3 = dg.validate(q3)
    assert res3.is_valid is True
    assert res3.status == DomainStatus.VALID


# =====================================================================
# 12. Ambiguous entity resolution
# =====================================================================

def test_ambiguous_entity_resolution(temp_db_path):
    """Verify that ambiguous entity aliases return is_ambiguous=True and candidate list."""
    registry = EntityRegistry(db_path=temp_db_path)

    # In our temp database, 'Italy' hosts both Italian GP and Emilia Romagna GP
    italy_res = registry.resolve_event("Italy")
    assert italy_res.matched is False
    assert italy_res.is_ambiguous is True
    assert len(italy_res.candidates) == 2
    assert "Italian Grand Prix" in italy_res.candidates
    assert "Emilia Romagna Grand Prix" in italy_res.candidates

    # Unambiguous specific name resolves cleanly
    monza_ev = registry.resolve_event("Italian Grand Prix")
    assert monza_ev.matched is True
    assert monza_ev.is_ambiguous is False
    assert monza_ev.event_name == "Italian Grand Prix"


# =====================================================================
# 13. DomainGuard execution before ChromaDB retrieval
# =====================================================================

def test_domainguard_execution_before_chromadb_retrieval():
    """Verify that out-of-domain and historical questions never trigger ChromaDB retrieval."""
    mock_retriever = MagicMock()
    mock_retriever.retrieve = MagicMock(side_effect=RuntimeError("ChromaDB retrieve should NOT have been called!"))

    service = ChatService(retriever=mock_retriever, offline=True)

    # 1. MotoGP
    ans_motogp = service.ask("Who won the 2024 MotoGP World Championship?")
    assert "not part of the Formula 1 2024 calendar" in ans_motogp
    mock_retriever.retrieve.assert_not_called()

    # 2. Bathurst
    ans_bathurst = service.ask("Who won the 2024 Bathurst 1000?")
    assert "not part of the Formula 1 2024 calendar" in ans_bathurst
    mock_retriever.retrieve.assert_not_called()

    # 3. 2020 Historical Season
    ans_2020 = service.ask("Who won the 2020 Italian Grand Prix?")
    assert "Historical data for season 2020 is not available" in ans_2020
    mock_retriever.retrieve.assert_not_called()

    # 4. Out of calendar German GP
    ans_german = service.ask("What was the race result of the 2024 German Grand Prix?")
    assert "not part of the Formula 1 2024 calendar" in ans_german
    mock_retriever.retrieve.assert_not_called()


# =====================================================================
# 14. No regressions in existing structured queries
# =====================================================================

def test_no_regressions_in_existing_structured_queries():
    """Verify that existing structured weather, fastest lap, standings, and constructor points still work."""
    service = ChatService(offline=True)

    # Weather
    w_ans = service.ask("Did it rain in the 2024 Bahrain Grand Prix?")
    assert "no rainfall" in w_ans.lower() or "dry" in w_ans.lower()

    # Fastest Lap
    fl_ans = service.ask("Who clocked the fastest lap in the 2024 Australian Grand Prix?")
    assert "Charles Leclerc" in fl_ans

    # Standings Leader
    st_ans = service.ask("Who leads the driver standings after the Bahrain Grand Prix?")
    assert "Max Verstappen" in st_ans

    # Constructor Points
    cp_ans = service.ask("Which team scored the most points in the 2024 Hungarian Grand Prix?")
    assert "McLaren" in cp_ans
