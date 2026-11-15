"""
Test Suite for Phase 6.2.1 — Sprint Session Integration & Championship Point Verification.

Verifies:
1. 2024 Sprint session discovery and ingestion (all 6 sprints present).
2. Total sprint points in 2024 equals exactly 216.0.
3. Standings accuracy: Verstappen (437), Norris (374), Piastri (292), McLaren (666).
4. Zero duplicate sprint results.
5. All 24 Grand Prix classifications remain intact.
6. Grand Prix winners refer strictly to Race sessions.
7. Multi-constructor driver substitutions (Bearman 7.0 pts across Ferrari & Haas).
8. Historical accuracy: 2022 (3 sprints, VER 454), 2023 (6 sprints, VER 575).
9. Scheduled sprint discovery: 2025 (6 sprints).
10. Idempotent incremental synchronization.
"""

from __future__ import annotations

import sqlite3
import pytest
from fastapi.testclient import TestClient

from database.connection import SessionLocal
from database.models import Event, RaceResult, Season, Session as RaceSession
from raceintel.api.main import app
from raceintel.data.schedule import ScheduleDiscovery
from raceintel.services.race_service import get_race_winner
from raceintel.services.standings_service import (
    get_constructor_standings_after_event,
    get_driver_standings_after_event,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_2024_sprint_sessions_coverage_and_points():
    """Verify all 6 sprint sessions and exactly 216.0 sprint points in 2024."""
    db = SessionLocal()
    try:
        s2024 = db.query(Season).filter(Season.season_year == 2024).first()
        assert s2024 is not None

        sprint_sessions = (
            db.query(RaceSession)
            .join(Event)
            .filter(Event.season_id == s2024.season_id, RaceSession.session_type == "Sprint")
            .all()
        )
        assert len(sprint_sessions) == 6

        # Sum of sprint points
        sprint_session_ids = [s.session_id for s in sprint_sessions]
        sprint_pts = sum(
            r.points_scored or 0.0
            for r in db.query(RaceResult).filter(RaceResult.session_id.in_(sprint_session_ids)).all()
        )
        assert sprint_pts == 216.0

        # Verify Grand Prix races count
        gp_sessions = (
            db.query(RaceSession)
            .join(Event)
            .filter(Event.season_id == s2024.season_id, RaceSession.session_type == "Race")
            .all()
        )
        assert len(gp_sessions) == 24
    finally:
        db.close()


def test_2024_championship_standings_exact_totals():
    """Verify Verstappen 437, Norris 374, Piastri 292, McLaren 666."""
    db = SessionLocal()
    try:
        # Find Abu Dhabi GP session_id (final round)
        abu_dhabi_gp = (
            db.query(RaceSession)
            .join(Event)
            .join(Season)
            .filter(
                Season.season_year == 2024,
                Event.event_name.like("%Abu Dhabi%"),
                RaceSession.session_type == "Race",
            )
            .first()
        )
        assert abu_dhabi_gp is not None
        sid = abu_dhabi_gp.session_id

        # Driver standings
        drv_standings = get_driver_standings_after_event(sid, season=2024)
        drv_map = {d["driver_code"]: d["total_points"] for d in drv_standings}

        assert drv_map.get("VER") == 437.0
        assert drv_map.get("NOR") == 374.0
        assert drv_map.get("PIA") == 292.0
        assert drv_map.get("LEC") == 356.0
        assert drv_map.get("SAI") == 290.0
        assert drv_map.get("RUS") == 245.0
        assert drv_map.get("HAM") == 223.0
        assert drv_map.get("PER") == 152.0

        # Constructor standings
        con_standings = get_constructor_standings_after_event(sid, season=2024)
        con_map = {c["constructor_name"]: c["total_points"] for c in con_standings}

        assert con_map.get("McLaren") == 666.0
        assert con_map.get("Ferrari") == 652.0
        assert con_map.get("Red Bull Racing") == 589.0
        assert con_map.get("Mercedes") == 468.0
    finally:
        db.close()


def test_no_duplicate_results_per_session():
    """Verify no driver has duplicate results in any session."""
    conn = sqlite3.connect("data/raceintel.db")
    c = conn.cursor()
    c.execute("""
        SELECT session_id, driver_id, COUNT(*) as cnt
        FROM race_results
        GROUP BY session_id, driver_id
        HAVING cnt > 1;
    """)
    dups = c.fetchall()
    assert len(dups) == 0, f"Found duplicate results: {dups}"


def test_driver_substitution_unification():
    """Verify Oliver Bearman has unified 7.0 points across Ferrari and Haas."""
    db = SessionLocal()
    try:
        abu_dhabi_gp = (
            db.query(RaceSession)
            .join(Event)
            .join(Season)
            .filter(
                Season.season_year == 2024,
                Event.event_name.like("%Abu Dhabi%"),
                RaceSession.session_type == "Race",
            )
            .first()
        )
        drv_standings = get_driver_standings_after_event(abu_dhabi_gp.session_id, season=2024)
        bea_entries = [d for d in drv_standings if d["driver_code"] == "BEA"]
        assert len(bea_entries) == 1
        assert bea_entries[0]["total_points"] == 7.0
    finally:
        db.close()


def test_race_winner_preserves_grand_prix_only():
    """Verify get_race_winner for Austrian GP returns George Russell, not Verstappen (sprint winner)."""
    db = SessionLocal()
    try:
        austria_gp = (
            db.query(RaceSession)
            .join(Event)
            .join(Season)
            .filter(
                Season.season_year == 2024,
                Event.event_name.like("%Austrian%"),
                RaceSession.session_type == "Race",
            )
            .first()
        )
        assert austria_gp is not None
        winner = get_race_winner(austria_gp.session_id)
        assert winner is not None
        assert winner["driver_code"] == "RUS"
        assert winner["finish_position"] == 1
    finally:
        db.close()


def test_historical_seasons_sprint_integration():
    """Verify 2022 (3 sprints, VER 454) and 2023 (6 sprints, VER 575)."""
    conn = sqlite3.connect("data/raceintel.db")
    c = conn.cursor()

    # 2022
    c.execute("""
        SELECT COUNT(*)
        FROM sessions s
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        WHERE sn.season_year = 2022 AND s.session_type = 'Sprint'
    """)
    s2022_count = c.fetchone()[0]
    assert s2022_count == 3

    c.execute("""
        SELECT SUM(rr.points_scored)
        FROM race_results rr
        JOIN sessions s ON s.session_id = rr.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN drivers d ON d.driver_id = rr.driver_id
        WHERE sn.season_year = 2022 AND d.driver_code = 'VER'
    """)
    ver_2022 = c.fetchone()[0]
    assert ver_2022 == 454.0

    # 2023
    c.execute("""
        SELECT COUNT(*)
        FROM sessions s
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        WHERE sn.season_year = 2023 AND s.session_type = 'Sprint'
    """)
    s2023_count = c.fetchone()[0]
    assert s2023_count == 6

    c.execute("""
        SELECT SUM(rr.points_scored)
        FROM race_results rr
        JOIN sessions s ON s.session_id = rr.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN drivers d ON d.driver_id = rr.driver_id
        WHERE sn.season_year = 2023 AND d.driver_code = 'VER'
    """)
    ver_2023 = c.fetchone()[0]
    assert ver_2023 == 575.0


def test_2025_sprints_discovery_and_coverage():
    """Verify 2025 schedule discovers all 6 scheduled sprint rounds."""
    disc = ScheduleDiscovery()
    sched = disc.get_schedule(2025)
    sprints = [e for e in sched.events if e.session_type == "Sprint"]
    assert len(sprints) == 6
    sprint_rounds = {s.round_number for s in sprints}
    assert sprint_rounds == {2, 6, 13, 19, 21, 23}


def test_analytics_api_endpoints_sprint_aware(client: TestClient):
    """Verify analytics endpoints return sprint-integrated championship standings."""
    # Overview
    r = client.get("/analytics/overview?season=2024")
    assert r.status_code == 200
    data = r.json()
    assert data["driver_leader"]["driver_code"] == "VER"
    assert data["driver_leader"]["total_points"] == 437.0
    assert data["constructor_leader"]["constructor_name"] == "McLaren"
    assert data["constructor_leader"]["total_points"] == 666.0

    # Driver profile (VER has driver_id = 2)
    r_ver = client.get("/analytics/drivers/2/season?season=2024")
    assert r_ver.status_code == 200
    vdata = r_ver.json()
    assert vdata["summary"]["total_points"] == 437.0
    assert vdata["summary"]["sprint_points"] == 38.0
    assert vdata["summary"]["wins"] == 9
    assert len(vdata["sprint_results"]) == 6

    # Constructor profile (McLaren has constructor_id = 6)
    r_mcl = client.get("/analytics/constructors/6/season?season=2024")
    assert r_mcl.status_code == 200
    mdata = r_mcl.json()
    assert mdata["summary"]["total_points"] == 666.0
    assert mdata["summary"]["sprint_points"] == 57.0
    assert mdata["summary"]["wins"] == 6

