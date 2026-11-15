"""
Adversarial Regression Tests for RaceIntel Phase 4A.

Tests edge cases, negative examples, cross-discipline comparisons,
ambiguous entities, unknown tokens, multi-season dynamics, and pipeline ordering.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from raceintel.chat.chat_service import ChatService
from raceintel.routing.domain_guard import DomainGuard, DomainStatus
from raceintel.routing.entity_registry import EntityRegistry


# =====================================================================
# 1. Entity Resolution: Drivers, Reserves, Surnames, Diacritics
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_driver_resolution_names_surnames_reserves():
    """Verify robust resolution of drivers across names, surnames, nicknames, codes, and accents."""
    registry = EntityRegistry()

    # Full names
    assert registry.resolve_driver("Max Verstappen").matched is True
    assert registry.resolve_driver("Lewis Hamilton").matched is True

    # Surnames alone
    assert registry.resolve_driver("Hamilton").driver_full_name == "Lewis Hamilton"
    assert registry.resolve_driver("Sainz").driver_full_name == "Carlos Sainz"
    assert registry.resolve_driver("Leclerc").driver_full_name == "Charles Leclerc"
    assert registry.resolve_driver("Norris").driver_full_name == "Lando Norris"
    assert registry.resolve_driver("Russell").driver_full_name == "George Russell"

    # Accented & unaccented forms
    assert registry.resolve_driver("Perez").driver_full_name == "Sergio Perez"
    assert registry.resolve_driver("Pérez").driver_full_name == "Sergio Perez"
    assert registry.resolve_driver("Hulkenberg").driver_full_name == "Nico Hulkenberg"
    assert registry.resolve_driver("Hülkenberg").driver_full_name == "Nico Hulkenberg"

    # Nicknames
    assert registry.resolve_driver("Checo").driver_full_name == "Sergio Perez"
    assert registry.resolve_driver("Hulk").driver_full_name == "Nico Hulkenberg"
    assert registry.resolve_driver("Alex").driver_full_name == "Alexander Albon"
    assert registry.resolve_driver("Ollie").driver_full_name == "Oliver Bearman"

    # 2024 Reserve drivers
    assert registry.resolve_driver("Bearman").driver_full_name == "Oliver Bearman"
    assert registry.resolve_driver("Colapinto").driver_full_name == "Franco Colapinto"
    assert registry.resolve_driver("Lawson").driver_full_name == "Liam Lawson"
    assert registry.resolve_driver("Doohan").driver_full_name == "Jack Doohan"

    # 3-Letter Driver Codes
    assert registry.resolve_driver("VER").driver_full_name == "Max Verstappen"
    assert registry.resolve_driver("HAM").driver_full_name == "Lewis Hamilton"
    assert registry.resolve_driver("BEA").driver_full_name == "Oliver Bearman"
    assert registry.resolve_driver("COL").driver_full_name == "Franco Colapinto"
    assert registry.resolve_driver("LAW").driver_full_name == "Liam Lawson"
    assert registry.resolve_driver("DOO").driver_full_name == "Jack Doohan"
    assert registry.resolve_driver("ZHO").driver_full_name == "Guanyu Zhou"


# =====================================================================
# 2. Entity Resolution: Constructors & Aliases
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_constructor_resolution():
    """Verify resolution of constructors across formal and colloquial aliases."""
    registry = EntityRegistry()

    assert registry.resolve_constructor("Ferrari").constructor_name == "Ferrari"
    assert registry.resolve_constructor("Scuderia Ferrari").constructor_name == "Ferrari"
    assert registry.resolve_constructor("Scuderia").constructor_name == "Ferrari"

    assert registry.resolve_constructor("Red Bull Racing").constructor_name == "Red Bull Racing"
    assert registry.resolve_constructor("Red Bull").constructor_name == "Red Bull Racing"
    assert registry.resolve_constructor("RBR").constructor_name == "Red Bull Racing"

    assert registry.resolve_constructor("Mercedes").constructor_name == "Mercedes"
    assert registry.resolve_constructor("Silver Arrows").constructor_name == "Mercedes"

    assert registry.resolve_constructor("Haas").constructor_name == "Haas F1 Team"
    assert registry.resolve_constructor("Haas F1").constructor_name == "Haas F1 Team"

    assert registry.resolve_constructor("Sauber").constructor_name == "Kick Sauber"
    assert registry.resolve_constructor("Kick Sauber").constructor_name == "Kick Sauber"
    assert registry.resolve_constructor("Stake").constructor_name == "Kick Sauber"

    assert registry.resolve_constructor("RB").constructor_name == "RB"
    assert registry.resolve_constructor("VCARB").constructor_name == "RB"
    assert registry.resolve_constructor("Racing Bulls").constructor_name == "RB"


# =====================================================================
# 3. Entity Resolution: Circuits, Track Aliases, and Accented Events
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_circuit_and_event_resolution():
    """Verify track names, circuit aliases, and accented Grand Prix names."""
    registry = EntityRegistry()

    # Track names to canonical events
    assert registry.resolve_circuit("Monza").canonical_event == "Italian Grand Prix"
    assert registry.resolve_circuit("Autodromo Nazionale Monza").canonical_event == "Italian Grand Prix"
    assert registry.resolve_circuit("Silverstone").canonical_event == "British Grand Prix"
    assert registry.resolve_circuit("Spa").canonical_event == "Belgian Grand Prix"
    assert registry.resolve_circuit("Spa-Francorchamps").canonical_event == "Belgian Grand Prix"
    assert registry.resolve_circuit("Interlagos").canonical_event == "São Paulo Grand Prix"
    assert registry.resolve_circuit("Suzuka").canonical_event == "Japanese Grand Prix"
    assert registry.resolve_circuit("Zandvoort").canonical_event == "Dutch Grand Prix"
    assert registry.resolve_circuit("COTA").canonical_event == "United States Grand Prix"
    assert registry.resolve_circuit("Circuit of the Americas").canonical_event == "United States Grand Prix"
    assert registry.resolve_circuit("Hungaroring").canonical_event == "Hungarian Grand Prix"
    assert registry.resolve_circuit("Albert Park").canonical_event == "Australian Grand Prix"
    assert registry.resolve_circuit("Red Bull Ring").canonical_event == "Austrian Grand Prix"

    # Accented & unaccented event names
    assert registry.resolve_event("São Paulo Grand Prix").matched is True
    assert registry.resolve_event("Sao Paulo Grand Prix").matched is True
    assert registry.resolve_event("Canadian Grand Prix").matched is True
    assert registry.resolve_event("Montréal").matched is True
    assert registry.resolve_event("Montreal").matched is True


# =====================================================================
# 4. Ambiguity and Unknown Entities
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_ambiguous_and_unknown_entities():
    """Verify that ambiguous geographical names are not silently resolved to arbitrary records."""
    registry = EntityRegistry()

    # Italy hosts both Italian Grand Prix (Monza) and Emilia Romagna Grand Prix (Imola)
    italy_res = registry.resolve_event("Italy")
    assert italy_res.matched is False
    assert italy_res.is_ambiguous is True
    assert len(italy_res.candidates) >= 2
    assert "Italian Grand Prix" in italy_res.candidates
    assert "Emilia Romagna Grand Prix" in italy_res.candidates

    # United States hosts Miami GP, United States GP (Austin), and Las Vegas GP
    us_res = registry.resolve_event("United States")
    assert us_res.matched is False
    assert us_res.is_ambiguous is True
    assert len(us_res.candidates) >= 2

    # Specific Grand Prix names are unambiguous
    us_gp = registry.resolve_event("United States Grand Prix")
    assert us_gp.matched is True
    assert us_gp.is_ambiguous is False
    assert us_gp.event_name == "United States Grand Prix"

    # Unknown entities
    assert registry.resolve_driver("Michael Schumacher").matched is False
    assert registry.resolve_driver("Mario Andretti").matched is False
    assert registry.resolve_circuit("Brands Hatch").matched is False
    assert registry.resolve_circuit("Kyalami").matched is False


# =====================================================================
# 5. DomainGuard: Explicit Unrelated Motorsport Rejections
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_domainguard_motorsport_rejections():
    """Verify pre-retrieval rejection across multiple motorsport disciplines."""
    dg = DomainGuard()

    # MotoGP
    res = dg.validate("Who is the current MotoGP world champion?")
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT

    res = dg.validate("What was the result of the MotoGP Grand Prix of Qatar?")
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT

    # NASCAR
    res = dg.validate("Who won the 2024 Daytona 500?")
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT

    res = dg.validate("Who leads the NASCAR Cup Series points table?")
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT

    # WEC / Le Mans
    res = dg.validate("Did Ferrari win the 2024 24 Hours of Le Mans in the World Endurance Championship?")
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT

    # IndyCar / Indy 500
    res = dg.validate("Who won the 2024 Indianapolis 500 in IndyCar?")
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT

    # Supercars / Bathurst
    res = dg.validate("Who was declared the winner of the 2024 Bathurst 1000?")
    assert res.is_valid is False
    assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT


# =====================================================================
# 6. DomainGuard: F1 Comparisons Preserved
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_domainguard_f1_comparisons_preserved():
    """Verify that in-domain F1 questions mentioning other motorsports for comparison are preserved."""
    dg = DomainGuard()

    # Comparison with NASCAR
    res = dg.validate("How do 2024 Formula 1 cornering speeds at Silverstone compare to NASCAR?")
    assert res.is_valid is True
    assert res.status == DomainStatus.VALID

    res = dg.validate("Did Lewis Hamilton perform better in Formula 1 compared to his NASCAR test runs?")
    assert res.is_valid is True
    assert res.status == DomainStatus.VALID

    # Comparison with MotoGP
    res = dg.validate("How fast are F1 top speeds at Monza in 2024 compared to MotoGP?")
    assert res.is_valid is True
    assert res.status == DomainStatus.VALID

    # Multi-discipline driver inquiries
    res = dg.validate("Did Fernando Alonso drive faster in the 2024 Monaco Grand Prix compared to his WEC races?")
    assert res.is_valid is True
    assert res.status == DomainStatus.VALID


# =====================================================================
# 7. DomainGuard: General Racing Terminology Preserved
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_domainguard_racing_terminology_preserved():
    """Verify that general motorsport terms (apex, telemetry, slipstream, pit stop) do not trigger false rejections."""
    dg = DomainGuard()

    res1 = dg.validate("Did Charles Leclerc hit the apex consistently during the 2024 Monaco Grand Prix?")
    assert res1.is_valid is True
    assert res1.status == DomainStatus.VALID

    res2 = dg.validate("What was the fastest pit stop recorded in the 2024 British Grand Prix?")
    assert res2.is_valid is True
    assert res2.status == DomainStatus.VALID

    res3 = dg.validate("How effective was the slipstream on the straight during the 2024 Italian Grand Prix at Monza?")
    assert res3.is_valid is True
    assert res3.status == DomainStatus.VALID


# =====================================================================
# 8. DomainGuard: Unsupported vs Dynamically Supported Seasons
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_domainguard_unsupported_seasons():
    """Verify rejection of historical seasons not present in the database."""
    dg = DomainGuard()

    # Unsupported seasons outside supported range (2022-2026)
    for unsupported_year in [2020, 2021, 2019, 1998, 2030]:
        q = f"Who won the {unsupported_year} Italian Grand Prix?"
        res = dg.validate(q)
        assert res.is_valid is False
        assert res.status == DomainStatus.UNSUPPORTED_SEASON
        assert res.season == unsupported_year
        assert f"Historical data for season {unsupported_year} is not available" in res.refusal_message


def test_adversarial_domainguard_supported_seasons_other_than_2024():
    """Verify that if a database genuinely supports multiple seasons, they are accepted dynamically."""
    mock_registry = MagicMock()
    mock_registry.is_season_supported.side_effect = lambda s: s in {2022, 2023, 2024, 2025}
    mock_registry.events = [{"event_name": "Italian Grand Prix", "circuit_name": "Monza"}]
    mock_registry.drivers = []
    mock_registry.constructors = []

    dg = DomainGuard(registry=mock_registry)

    # 2023 is supported in mock_registry
    res_2023 = dg.validate("Who won the 2023 Italian Grand Prix?")
    assert res_2023.is_valid is True
    assert res_2023.status == DomainStatus.VALID

    # 2025 is supported in mock_registry
    res_2025 = dg.validate("Who will race in the 2025 Italian Grand Prix?")
    assert res_2025.is_valid is True
    assert res_2025.status == DomainStatus.VALID

    # 2018 is still unsupported
    res_2018 = dg.validate("Who won the 2018 Italian Grand Prix?")
    assert res_2018.is_valid is False
    assert res_2018.status == DomainStatus.UNSUPPORTED_SEASON


# =====================================================================
# 9. Pipeline Ordering & ChromaDB Isolation
# =====================================================================

@pytest.mark.requires_data
def test_adversarial_pipeline_ordering_and_chromadb_isolation():
    """Verify that DomainGuard executes strictly before ChromaDB retrieval, and rejected queries never trigger vector search."""
    mock_retriever = MagicMock()
    mock_retriever.retrieve = MagicMock(side_effect=RuntimeError("ChromaDB retrieve called on rejected query!"))

    service = ChatService(retriever=mock_retriever, offline=True)

    rejected_queries = [
        "Who won the 2024 MotoGP World Championship?",
        "Who won the 2024 Bathurst 1000?",
        "What was the race result of the Daytona 500 in NASCAR?",
        "Who won the 2024 24 Hours of Le Mans in WEC?",
        "Who won the 2020 Italian Grand Prix?",
        "What was the race result of the 2024 German Grand Prix?",
    ]

    for q in rejected_queries:
        ans = service.ask(q)
        assert "I couldn't find that information" in ans
        mock_retriever.retrieve.assert_not_called()


# =====================================================================
# 10. Retriever Isolation & Single Source of Truth
# =====================================================================

def test_adversarial_retriever_entity_isolation_from_database(tmp_path):
    """
    Verify that Retriever instances derive entities EXCLUSIVELY from the provided EntityRegistry,
    without bleeding legacy hardcoded fallback mappings for drivers or races that do not exist in the database.
    """
    from raceintel.retrieval.retriever import Retriever
    db_file = tmp_path / "isolated.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE seasons (season_id INTEGER PRIMARY KEY, season_year INTEGER UNIQUE);")
    cur.execute("CREATE TABLE constructors (constructor_id INTEGER PRIMARY KEY, constructor_name TEXT);")
    cur.execute("CREATE TABLE events (event_id INTEGER PRIMARY KEY, season_id INTEGER, event_name TEXT, country_name TEXT, circuit_name TEXT);")
    cur.execute("CREATE TABLE drivers (driver_id INTEGER PRIMARY KEY, driver_full_name TEXT, driver_code TEXT, driver_number INTEGER, constructor_id INTEGER);")

    cur.execute("INSERT INTO seasons VALUES (1, 2024);")
    cur.execute("INSERT INTO constructors VALUES (1, 'Custom Racing');")
    cur.execute("INSERT INTO events VALUES (1, 1, 'Custom Grand Prix', 'Customland', 'Custom Circuit');")
    cur.execute("INSERT INTO drivers VALUES (1, 'Alice Speed', 'ASP', 99, 1);")
    conn.commit()
    conn.close()

    isolated_reg = EntityRegistry(db_path=db_file)
    retriever = Retriever(registry=isolated_reg)

    # 1. Custom entities from DB are present
    assert "alice speed" in retriever.DRIVERS
    assert retriever.DRIVERS["alice speed"] == "Alice Speed"
    assert "custom grand prix" in retriever.RACES
    assert retriever.RACES["custom grand prix"] == "Custom Grand Prix"

    # 2. Legacy hardcoded entities NOT in this DB must NOT be present
    assert "max verstappen" not in retriever.DRIVERS
    assert "lewis hamilton" not in retriever.DRIVERS
    assert "monaco grand prix" not in retriever.RACES
    assert "ferrari" not in retriever.TEAMS

    # 3. Filter extraction on isolated retriever
    filters = retriever._extract_filters("How did Alice Speed perform in Custom Grand Prix?")
    assert filters.get("driver") == "Alice Speed"
    assert filters.get("race_name") == "Custom Grand Prix"

    # Filter extraction on entity not in DB returns None
    filters_unsupported = retriever._extract_filters("How did Lewis Hamilton perform in Monaco?")
    assert filters_unsupported.get("driver") is None
    assert filters_unsupported.get("race_name") is None

