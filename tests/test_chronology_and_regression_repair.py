import pytest
pytestmark = pytest.mark.requires_data
"""
Regression and Chronology Repair Test Suite.

Verifies:
1. Reconciled 2024 chronology matches FastF1 official schedule (R1 Bahrain through R24 Abu Dhabi).
2. Standings chronology:
   - Standings after Bahrain (Round 1)
   - Standings after Chinese GP (Round 5 - sprint + race)
   - Standings after British GP (Round 12)
   - Final standings after Abu Dhabi (Round 24)
   - Separation of race and sprint points, correct combined totals.
   - Sprint winners do not become Grand Prix winners (e.g. Austria 2024: Russell won GP, Verstappen won Sprint).
3. DomainGuard regressions:
   - Valid F1 event without a specified season (e.g. "Who won the Monaco Grand Prix?") resolved to 2024.
   - French GP without year is accepted (held in supported 2022 season), whereas 2024 French GP is rejected.
   - Ambiguous multi-word names: "Michael Schumacher" does not match Mick Schumacher.
4. Schema & Data safety:
   - ChronologyReconciler produces zero proposed changes on repeated dry-run (idempotency).
   - SQLite foreign key integrity and table integrity pass.
   - Protected factual tables remain intact.
"""

import sqlite3
import pytest

from database.connection import SessionLocal
from database.models import Event, RaceResult, Season, Session as RaceSession
from raceintel.chat.chat_service import ChatService
from raceintel.data.reconciliation import ChronologyReconciler
from raceintel.routing.domain_guard import DomainGuard, DomainStatus
from raceintel.routing.entity_registry import EntityRegistry
from raceintel.services.race_service import get_race_winner
from raceintel.services.standings_service import (
    get_constructor_standings_after_event,
    get_driver_standings_after_event,
)


@pytest.fixture(scope="module")
def chat_service():
    return ChatService()


# =====================================================================
# 1. 2024 Event Chronology & Identity Verification
# =====================================================================


def test_2024_official_chronology_order():
    """Verify all 24 rounds of 2024 match FastF1 official schedule in database."""
    expected_2024_schedule = [
        (1, "Bahrain Grand Prix"),
        (2, "Saudi Arabian Grand Prix"),
        (3, "Australian Grand Prix"),
        (4, "Japanese Grand Prix"),
        (5, "Chinese Grand Prix"),
        (6, "Miami Grand Prix"),
        (7, "Emilia Romagna Grand Prix"),
        (8, "Monaco Grand Prix"),
        (9, "Canadian Grand Prix"),
        (10, "Spanish Grand Prix"),
        (11, "Austrian Grand Prix"),
        (12, "British Grand Prix"),
        (13, "Hungarian Grand Prix"),
        (14, "Belgian Grand Prix"),
        (15, "Dutch Grand Prix"),
        (16, "Italian Grand Prix"),
        (17, "Azerbaijan Grand Prix"),
        (18, "Singapore Grand Prix"),
        (19, "United States Grand Prix"),
        (20, "Mexico City Grand Prix"),
        (21, "São Paulo Grand Prix"),
        (22, "Las Vegas Grand Prix"),
        (23, "Qatar Grand Prix"),
        (24, "Abu Dhabi Grand Prix"),
    ]

    db = SessionLocal()
    try:
        season_2024 = db.query(Season).filter(Season.season_year == 2024).one()
        events = (
            db.query(Event)
            .filter(Event.season_id == season_2024.season_id)
            .order_by(Event.round_number.asc())
            .all()
        )

        assert len(events) == 24
        for (exp_round, exp_name), ev in zip(expected_2024_schedule, events):
            assert ev.round_number == exp_round, f"Expected round {exp_round}, got {ev.round_number} for {ev.event_name}"
            assert exp_name in ev.event_name, f"Expected '{exp_name}' in '{ev.event_name}'"
    finally:
        db.close()


# =====================================================================
# 2. Cumulative Standings Chronology (Authoritative Event Ordering)
# =====================================================================


def test_standings_after_bahrain_gp():
    """Verify standings after Round 1 Bahrain: no Sprint points, Verstappen leads with 26."""
    db = SessionLocal()
    try:
        ev = (
            db.query(Event)
            .join(Season)
            .filter(Season.season_year == 2024, Event.round_number == 1)
            .one()
        )
        assert "Bahrain" in ev.event_name

        race_sess = (
            db.query(RaceSession)
            .filter(RaceSession.event_id == ev.event_id, RaceSession.session_type == "Race")
            .one()
        )
        driver_standings = get_driver_standings_after_event(race_sess.session_id)
        assert len(driver_standings) >= 20
        # P1: Verstappen - 26.0 (25 win + 1 fastest lap, 0 sprint)
        assert driver_standings[0]["driver_code"] == "VER"
        assert driver_standings[0]["points"] == 26.0
        assert driver_standings[0]["race_points"] == 26.0
        assert driver_standings[0]["sprint_points"] == 0.0

        # P2: Perez - 18.0
        assert driver_standings[1]["driver_code"] == "PER"
        assert driver_standings[1]["points"] == 18.0
        assert driver_standings[1]["race_points"] == 18.0
        assert driver_standings[1]["sprint_points"] == 0.0

        constructor_standings = get_constructor_standings_after_event(race_sess.session_id)
        # Red Bull Racing: 44.0 (26 + 18)
        assert constructor_standings[0]["constructor_name"] == "Red Bull Racing"
        assert constructor_standings[0]["points"] == 44.0
        assert constructor_standings[0]["race_points"] == 44.0
        assert constructor_standings[0]["sprint_points"] == 0.0
    finally:
        db.close()


def test_standings_after_chinese_gp():
    """Verify standings after Round 5 China (First sprint of 2024): sprint + race points."""
    db = SessionLocal()
    try:
        ev = (
            db.query(Event)
            .join(Season)
            .filter(Season.season_year == 2024, Event.round_number == 5)
            .one()
        )
        assert "China" in ev.event_name or "Chinese" in ev.event_name

        race_sess = (
            db.query(RaceSession)
            .filter(RaceSession.event_id == ev.event_id, RaceSession.session_type == "Race")
            .one()
        )
        driver_standings = get_driver_standings_after_event(race_sess.session_id)
        ver = next(d for d in driver_standings if d["driver_code"] == "VER")
        # VER through R5:
        # R1 (26), R2 (25), R3 (0 DNF), R4 (26), R5 (Sprint P1: 8 + Race P1: 25) = 110.0 total
        assert ver["points"] == 110.0
        assert ver["race_points"] == 102.0
        assert ver["sprint_points"] == 8.0
        assert ver["rank"] == 1
    finally:
        db.close()


def test_standings_after_british_gp():
    """Verify standings after Round 12 British GP: includes China, Miami, Austria sprints."""
    db = SessionLocal()
    try:
        ev = (
            db.query(Event)
            .join(Season)
            .filter(Season.season_year == 2024, Event.round_number == 12)
            .one()
        )
        assert "British" in ev.event_name

        race_sess = (
            db.query(RaceSession)
            .filter(RaceSession.event_id == ev.event_id, RaceSession.session_type == "Race")
            .one()
        )
        driver_standings = get_driver_standings_after_event(race_sess.session_id)
        ver = next(d for d in driver_standings if d["driver_code"] == "VER")
        nor = next(d for d in driver_standings if d["driver_code"] == "NOR")

        # VER: 231.0 race pts + 24.0 sprint pts = 255.0 total
        assert ver["points"] == 255.0
        assert ver["race_points"] == 231.0
        assert ver["sprint_points"] == 24.0
        assert ver["rank"] == 1

        # NOR: 162.0 race pts + 9.0 sprint pts = 171.0 total
        assert nor["points"] == 171.0
        assert nor["race_points"] == 162.0
        assert nor["sprint_points"] == 9.0
        assert nor["rank"] == 2
    finally:
        db.close()


def test_final_standings_after_abu_dhabi_gp():
    """Verify full-season standings after Round 24 Abu Dhabi."""
    db = SessionLocal()
    try:
        ev = (
            db.query(Event)
            .join(Season)
            .filter(Season.season_year == 2024, Event.round_number == 24)
            .one()
        )
        assert "Abu Dhabi" in ev.event_name

        race_sess = (
            db.query(RaceSession)
            .filter(RaceSession.event_id == ev.event_id, RaceSession.session_type == "Race")
            .one()
        )
        driver_standings = get_driver_standings_after_event(race_sess.session_id)
        constructor_standings = get_constructor_standings_after_event(race_sess.session_id)

        # Drivers: VER champion (437 pts), NOR P2 (374 pts), LEC P3 (356 pts)
        assert driver_standings[0]["driver_code"] == "VER"
        assert driver_standings[0]["points"] == 437.0
        assert driver_standings[1]["driver_code"] == "NOR"
        assert driver_standings[1]["points"] == 374.0
        assert driver_standings[2]["driver_code"] == "LEC"
        assert driver_standings[2]["points"] == 356.0

        # Constructors: McLaren champion (666 pts), Ferrari P2 (652 pts), Red Bull P3 (589 pts)
        assert constructor_standings[0]["constructor_name"] == "McLaren"
        assert constructor_standings[0]["points"] == 666.0
        assert constructor_standings[1]["constructor_name"] == "Ferrari"
        assert constructor_standings[1]["points"] == 652.0
        assert constructor_standings[2]["constructor_name"] == "Red Bull Racing"
        assert constructor_standings[2]["points"] == 589.0
    finally:
        db.close()


def test_sprint_vs_grand_prix_winner_separation():
    """Verify sprint winners do not become Grand Prix winners (e.g. Austrian GP 2024)."""
    db = SessionLocal()
    try:
        # Race session for Austrian GP
        ev = (
            db.query(Event)
            .join(Season)
            .filter(Season.season_year == 2024, Event.round_number == 11)
            .one()
        )
        assert "Austria" in ev.event_name or "Austrian" in ev.event_name

        race_sess = (
            db.query(RaceSession)
            .filter(RaceSession.event_id == ev.event_id, RaceSession.session_type == "Race")
            .one()
        )
        sprint_sess = (
            db.query(RaceSession)
            .filter(RaceSession.event_id == ev.event_id, RaceSession.session_type == "Sprint")
            .one()
        )

        # GP Winner is George Russell
        gp_winner = get_race_winner(race_sess.session_id)
        assert gp_winner["driver_code"] == "RUS"
        assert "George Russell" in gp_winner["driver_full_name"]

        # Sprint Winner is Max Verstappen
        sprint_winner = (
            db.query(RaceResult)
            .filter(RaceResult.session_id == sprint_sess.session_id, RaceResult.finish_position == 1)
            .one()
        )
        assert sprint_winner.driver.driver_code == "VER"
    finally:
        db.close()


# =====================================================================
# 3. DomainGuard & Entity Disambiguation Regressions
# =====================================================================


def test_domainguard_event_without_year_monaco(chat_service):
    """Verify Monaco GP query without year is accepted and answered with 2024 winner."""
    guard = DomainGuard()
    res = guard.validate("Who won the Monaco Grand Prix?")
    assert res.is_valid is True
    assert res.status == DomainStatus.VALID

    # ChatService should default to 2024 and identify Charles Leclerc
    answer = chat_service.ask("Who won the Monaco Grand Prix?")
    assert "Charles Leclerc" in answer
    assert "Monaco" in answer


def test_domainguard_event_without_year_french():
    """Verify French GP without year is accepted because French GP was held in supported 2022 season."""
    guard = DomainGuard()
    res = guard.validate("Who won the French Grand Prix?")
    assert res.is_valid is True
    assert res.status == DomainStatus.VALID


def test_domainguard_out_of_calendar_year_french():
    """Verify French GP with 2024 is rejected as OUT_OF_CALENDAR."""
    guard = DomainGuard()
    res = guard.validate("Who won the 2024 French Grand Prix?")
    assert res.is_valid is False
    assert "calendar" in res.refusal_message.lower()


def test_entity_resolution_michael_vs_mick_schumacher():
    """Verify Michael Schumacher does not match Mick Schumacher by single surname token."""
    reg = EntityRegistry()
    res = reg.resolve_driver("Michael Schumacher")
    # Michael Schumacher is not a driver in 2022-2026 database (Mick is)
    assert res.matched is False


def test_domainguard_non_f1_queries():
    """Verify DomainGuard strictly rejects non-F1 motorsport queries."""
    guard = DomainGuard()
    for non_f1_motorsport in [
        "Who won the 2024 Indianapolis 500?",
        "Who won the 2024 Daytona 500 in NASCAR?",
        "Who won the 2024 MotoGP World Championship?",
        "Who won the 24 Hours of Le Mans in WEC?",
    ]:
        res = guard.validate(non_f1_motorsport)
        assert res.is_valid is False
        assert res.status == DomainStatus.OUT_OF_DOMAIN_MOTORSPORT


# =====================================================================
# 4. Database Integrity and Reconciler Idempotency
# =====================================================================


def test_chronology_reconciler_idempotency():
    """Verify that running the reconciler again proposes zero changes."""
    reconciler = ChronologyReconciler(db_path="data/raceintel.db")
    report = reconciler.reconcile_all_seasons(dry_run=True)
    assert report.total_proposed_changes == 0, f"Reconciler should be idempotent but proposed {report.total_proposed_changes} changes"
    assert len(report.proposed_changes) == 0


def test_database_foreign_key_and_integrity():
    """Verify SQLite database integrity and foreign key constraints."""
    conn = sqlite3.connect("data/raceintel.db")
    cursor = conn.cursor()
    try:
        # Integrity check
        cursor.execute("PRAGMA integrity_check;")
        integrity_row = cursor.fetchone()
        assert integrity_row[0] == "ok"

        # Foreign key check
        cursor.execute("PRAGMA foreign_key_check;")
        fk_violations = cursor.fetchall()
        assert len(fk_violations) == 0, f"Found foreign key violations: {fk_violations}"
    finally:
        conn.close()


def test_protected_table_row_counts():
    """Verify row counts in protected factual tables."""
    conn = sqlite3.connect("data/raceintel.db")
    cursor = conn.cursor()
    try:
        counts = {}
        for table in ["race_results", "laps", "weather_observations", "drivers", "constructors", "sessions"]:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            counts[table] = cursor.fetchone()[0]

        assert counts["race_results"] == 2830
        assert counts["laps"] == 51486
        assert counts["weather_observations"] == 7614
        assert counts["drivers"] == 34
        assert counts["constructors"] == 14
        assert counts["sessions"] == 142
    finally:
        conn.close()
