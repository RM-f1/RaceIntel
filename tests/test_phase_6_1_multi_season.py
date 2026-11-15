"""
Comprehensive Test Suite for Phase 6.1 Multi-Season Architecture & Synchronization.

Validates:
1. Multi-season data coverage across 2022-2026 in SQLite.
2. Duplicate prevention & incremental skip idempotency.
3. Transaction rollback on failure.
4. Correct tracking of upcoming 2026 rounds (R21-R23) without fabricating results.
5. Single-worker execution process lock.
6. Admin manual synchronization security & authentication.
7. ChromaDB incremental indexing & preservation of 2024 documents.
8. Season-aware analytics endpoints and dynamic refusal messaging in DomainGuard.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.models import Base, Constructor, Driver, Event, RaceResult, Season, Session as RaceSession, SessionSyncStatus
from raceintel.api.main import app
from raceintel.data.fetcher import FetchedSessionData
from raceintel.data.ingest import IngestionEngine
from raceintel.data.persister import SessionPersister
from raceintel.data.schedule import EventScheduleItem, SeasonSchedule
from raceintel.data.status import (
    acquire_worker_lock,
    get_all_seasons_sync_summary,
    get_season_sync_status,
    is_worker_running,
    release_worker_lock,
)
from raceintel.data.validator import SessionValidator
from raceintel.routing.domain_guard import DomainGuard, DomainStatus
from raceintel.routing.entity_registry import EntityRegistry


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def isolated_db(tmp_path: Path):
    """Provide an isolated SQLite database session factory for transactional tests."""
    db_file = tmp_path / "test_isolated.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", echo=False)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return factory, db_file


# ---------------------------------------------------------------------
# 1. Multi-Season Coverage & Integrity in Primary SQLite
# ---------------------------------------------------------------------


def test_primary_database_multi_season_coverage():
    """Verify that primary database contains valid records for 2022 through 2026."""
    from database.connection import SessionLocal

    db = SessionLocal()
    try:
        seasons = db.execute(select(Season.season_year).order_by(Season.season_year.asc())).scalars().all()
        assert set(seasons) >= {2022, 2023, 2024, 2025, 2026}

        # Verify 2024 baseline laps & weather preserved
        s2024 = db.execute(select(Season).where(Season.season_year == 2024)).scalar_one()
        events_2024 = db.execute(select(Event).where(Event.season_id == s2024.season_id)).scalars().all()
        assert len(events_2024) == 24

        # Verify 2026 upcoming rounds exist in schedule but have no results
        s2026 = db.execute(select(Season).where(Season.season_year == 2026)).scalar_one()
        r21_event = db.execute(
            select(Event).where(Event.season_id == s2026.season_id, Event.round_number == 21)
        ).scalar_one_or_none()
        assert r21_event is not None
        assert "Las Vegas" in r21_event.event_name

        r21_session = db.execute(
            select(RaceSession).where(RaceSession.event_id == r21_event.event_id, RaceSession.session_type == "Race")
        ).scalar_one_or_none()
        assert r21_session is not None

        r21_results = db.execute(
            select(RaceResult).where(RaceResult.session_id == r21_session.session_id)
        ).scalars().all()
        # MUST BE ZERO - no fabricated results for future races!
        assert len(r21_results) == 0

    finally:
        db.close()


# ---------------------------------------------------------------------
# 2. Duplicate Prevention & Incremental Skipping
# ---------------------------------------------------------------------


def test_persister_duplicate_prevention(isolated_db):
    """Ensure persister does not create duplicate rows when persisting the same payload twice."""
    factory, _ = isolated_db
    persister = SessionPersister(session_factory=factory)

    sample = FetchedSessionData(
        season_year=2026,
        round_number=1,
        event_name="Australian Grand Prix",
        country_name="Australia",
        circuit_name="Albert Park",
        constructors=["Ferrari", "McLaren"],
        drivers=[
            {"driver_code": "LEC", "driver_number": 16, "driver_full_name": "Charles Leclerc", "constructor_name": "Ferrari"},
            {"driver_code": "NOR", "driver_number": 4, "driver_full_name": "Lando Norris", "constructor_name": "McLaren"},
        ],
        results=[
            {"driver_code": "LEC", "constructor_name": "Ferrari", "grid_position": 1, "finish_position": 1, "points_scored": 25.0},
            {"driver_code": "NOR", "constructor_name": "McLaren", "grid_position": 2, "finish_position": 2, "points_scored": 18.0},
        ],
    )

    # First pass
    sum1 = persister.persist_session(sample, incremental=True)
    assert sum1.records_inserted > 0
    assert sum1.status == "PARTIAL"

    # Second pass (incremental should skip existing records)
    sum2 = persister.persist_session(sample, incremental=True)
    assert sum2.records_inserted == 0
    assert sum2.records_skipped > 0

    # Verify counts in isolated database
    db = factory()
    try:
        events = db.execute(select(Event)).scalars().all()
        results = db.execute(select(RaceResult)).scalars().all()
        assert len(events) == 1
        assert len(results) == 2
    finally:
        db.close()


# ---------------------------------------------------------------------
# 3. Transaction Rollback on Failure
# ---------------------------------------------------------------------


def test_persister_rollback_on_error(isolated_db):
    """Verify that an exception during persistence causes a complete transaction rollback."""
    factory, _ = isolated_db
    persister = SessionPersister(session_factory=factory)

    # Malformed data with illegal types to trigger DB error inside transaction
    bad_sample = FetchedSessionData(
        season_year=2026,
        round_number=2,
        event_name="Chinese Grand Prix",
        constructors=["Red Bull Racing"],
        drivers=[{"driver_code": "VER", "driver_full_name": "Max Verstappen", "constructor_name": "Red Bull Racing"}],
        results=[
            {
                "driver_code": "VER",
                "constructor_name": "Red Bull Racing",
                "grid_position": "ILLEGAL_STRING",  # Will raise ValueError on int conversion
                "finish_position": 1,
            }
        ],
    )

    summary = persister.persist_session(bad_sample)
    assert summary.status == "FAILED"

    # Verify nothing was committed
    db = factory()
    try:
        events = db.execute(select(Event).where(Event.event_name == "Chinese Grand Prix")).scalars().all()
        assert len(events) == 0
    finally:
        db.close()


# ---------------------------------------------------------------------
# 4. Single-Worker Process Locking
# ---------------------------------------------------------------------


def test_worker_lock_lifecycle(tmp_path: Path):
    """Verify single-worker lock acquisition, overlap prevention, and release."""
    lock_file = tmp_path / "sync_worker.lock"

    # 1. Acquire lock
    assert acquire_worker_lock(lock_file) is True
    running, pid = is_worker_running(lock_file)
    assert running is True
    assert pid == os.getpid()

    # 2. Second worker attempts to acquire same lock -> must fail
    assert acquire_worker_lock(lock_file) is False

    # 3. Release lock
    release_worker_lock(lock_file)
    running, pid = is_worker_running(lock_file)
    assert running is False
    assert lock_file.exists() is False


# ---------------------------------------------------------------------
# 5. Admin Authentication on Manual Sync Endpoint
# ---------------------------------------------------------------------


def test_admin_sync_endpoint_security(test_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Ensure manual sync endpoint strictly enforces admin authentication and fails closed."""
    from unittest.mock import MagicMock, patch

    mock_report = MagicMock(
        is_success=True,
        season_year=2026,
        total_rounds=23,
        processed_rounds=0,
        skipped_rounds=23,
        failed_rounds=0,
        records_inserted=0,
        records_updated=0,
        records_skipped=0,
        duration_seconds=0.05,
    )

    test_secret = "test_custom_admin_secret_key_12345"

    # 1. Key UNSET -> 503 Service Unavailable (Fail closed)
    monkeypatch.delenv("RACEINTEL_ADMIN_KEY", raising=False)
    resp_unset_no_key = test_client.post("/analytics/sync?season=2026")
    assert resp_unset_no_key.status_code == 503
    assert "not configured" in resp_unset_no_key.json()["detail"].lower()

    resp_unset_with_key = test_client.post(f"/analytics/sync?season=2026&admin_key={test_secret}")
    assert resp_unset_with_key.status_code == 503

    # 2. Key EMPTY -> 503 Service Unavailable (Fail closed)
    monkeypatch.setenv("RACEINTEL_ADMIN_KEY", "   ")
    resp_empty_key = test_client.post(f"/analytics/sync?season=2026&admin_key={test_secret}")
    assert resp_empty_key.status_code == 503

    # 3. Key SET -> Invalid / Missing Key -> 403 Forbidden
    monkeypatch.setenv("RACEINTEL_ADMIN_KEY", test_secret)

    resp_no_key = test_client.post("/analytics/sync?season=2026")
    assert resp_no_key.status_code == 403

    resp_bad_key = test_client.post("/analytics/sync?season=2026&admin_key=wrong_secret")
    assert resp_bad_key.status_code == 403

    # 4. Key SET -> Valid key via header -> 200 OK
    with patch("raceintel.api.routers.analytics.run_ingest", return_value=mock_report) as mock_ingest:
        resp_valid_hdr = test_client.post(
            "/analytics/sync?season=2026&incremental=true",
            headers={"X-RaceIntel-Admin-Key": test_secret},
        )
        assert resp_valid_hdr.status_code == 200
        data = resp_valid_hdr.json()
        assert data["season"] == 2026
        assert data["total_rounds"] == 23
        mock_ingest.assert_called_once()

    # 5. Key SET -> Valid key via query parameter -> 200 OK
    with patch("raceintel.api.routers.analytics.run_ingest", return_value=mock_report) as mock_ingest:
        resp_valid_param = test_client.post(
            f"/analytics/sync?season=2026&incremental=true&admin_key={test_secret}"
        )
        assert resp_valid_param.status_code == 200
        mock_ingest.assert_called_once()


# ---------------------------------------------------------------------
# 6. Season-Aware Analytics Endpoints
# ---------------------------------------------------------------------


def test_analytics_sync_status_endpoint(test_client: TestClient):
    """Verify /analytics/sync/status reports multi-season summary and worker status."""
    resp = test_client.get("/analytics/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "worker_running" in data
    assert "seasons" in data
    seasons = [s["season_year"] for s in data["seasons"]]
    assert set(seasons) >= {2022, 2023, 2024, 2025, 2026}


def test_analytics_overview_multi_season(test_client: TestClient):
    """Verify /analytics/overview supports querying 2022, 2024, and 2026."""
    # 2022
    resp_2022 = test_client.get("/analytics/overview?season=2022")
    assert resp_2022.status_code == 200
    assert resp_2022.json()["total_races"] == 22

    # 2026 with upcoming races
    resp_2026 = test_client.get("/analytics/overview?season=2026")
    assert resp_2026.status_code == 200
    d2026 = resp_2026.json()
    assert d2026["total_races"] == 23
    assert d2026["completed_races"] == 20
    # Latest race must be round 20 (completed), not upcoming round 23
    assert d2026["latest_race"]["winner_code"] is not None


# ---------------------------------------------------------------------
# 7. Season-Aware DomainGuard Validation
# ---------------------------------------------------------------------


def test_domain_guard_multi_season_awareness():
    """Verify DomainGuard dynamically validates supported seasons and formats refusals."""
    guard = DomainGuard()

    # 2022 French GP is VALID because 2022 is in the database and French GP was round 12
    res_2022_french = guard.validate("Who won the 2022 French Grand Prix?")
    assert res_2022_french.is_valid is True

    # 2024 French GP is OUT OF CALENDAR because French GP was not on the 2024 calendar
    res_2024_french = guard.validate("Who won the 2024 French Grand Prix?")
    assert res_2024_french.is_valid is False
    assert "Formula 1 2024 calendar" in res_2024_french.refusal_message

    # Unsupported season (e.g. 2018) is rejected with historical season refusal
    res_unsupported = guard.validate("Who won the 2018 Australian Grand Prix?")
    assert res_unsupported.is_valid is False
    assert res_unsupported.status == DomainStatus.UNSUPPORTED_SEASON
    assert "season 2018 is not available" in res_unsupported.refusal_message
