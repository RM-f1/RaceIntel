"""
Sync Status and Worker Lock Service for RaceIntel.

Tracks per-session synchronization lifecycle in SQLite (`session_sync_status`)
and provides a safe single-worker process execution lock.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from database.connection import PROJECT_ROOT, SessionLocal
from database.models import SessionSyncStatus

DEFAULT_LOCK_FILE = PROJECT_ROOT / "data" / "sync_worker.lock"


def record_sync_start(
    season_year: int,
    round_number: int,
    event_name: str,
    session_type: str = "Race",
    event_id: int | None = None,
    session_id: int | None = None,
    session_factory=None,
) -> None:
    """Record that synchronization has commenced for a session."""
    factory = session_factory or SessionLocal
    db: DBSession = factory()
    now_utc = datetime.now(timezone.utc)
    try:
        rec = None
        if session_id is not None:
            rec = db.execute(
                select(SessionSyncStatus).where(SessionSyncStatus.session_id == session_id)
            ).scalar_one_or_none()

        if rec is None:
            rec = db.execute(
                select(SessionSyncStatus).where(
                    SessionSyncStatus.season_year == season_year,
                    SessionSyncStatus.event_name == event_name,
                    SessionSyncStatus.session_type == session_type,
                )
            ).scalar_one_or_none()

        if rec is None:
            rec = db.execute(
                select(SessionSyncStatus).where(
                    SessionSyncStatus.season_year == season_year,
                    SessionSyncStatus.round_number == round_number,
                    SessionSyncStatus.session_type == session_type,
                )
            ).scalar_one_or_none()

        if rec is None:
            rec = SessionSyncStatus(
                season_year=season_year,
                round_number=round_number,
                event_name=event_name,
                session_type=session_type,
                session_name=session_type,
                event_id=event_id,
                session_id=session_id,
                status="IN_PROGRESS",
                started_at_utc=now_utc,
            )
            db.add(rec)
        else:
            rec.status = "IN_PROGRESS"
            rec.started_at_utc = now_utc
            rec.event_name = event_name
            rec.round_number = round_number
            if event_id is not None:
                rec.event_id = event_id
            if session_id is not None:
                rec.session_id = session_id

        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def record_sync_completion(
    season_year: int,
    round_number: int,
    event_name: str,
    status: str,
    data_categories: str = "",
    inserted: int = 0,
    updated: int = 0,
    skipped: int = 0,
    failure_reason: str | None = None,
    session_type: str = "Race",
    event_id: int | None = None,
    session_id: int | None = None,
    session_factory=None,
) -> None:
    """Record synchronization outcome, counts, and timestamps."""
    factory = session_factory or SessionLocal
    db: DBSession = factory()
    now_utc = datetime.now(timezone.utc)
    try:
        rec = None
        if session_id is not None:
            rec = db.execute(
                select(SessionSyncStatus).where(SessionSyncStatus.session_id == session_id)
            ).scalar_one_or_none()

        if rec is None:
            rec = db.execute(
                select(SessionSyncStatus).where(
                    SessionSyncStatus.season_year == season_year,
                    SessionSyncStatus.event_name == event_name,
                    SessionSyncStatus.session_type == session_type,
                )
            ).scalar_one_or_none()

        if rec is None:
            rec = db.execute(
                select(SessionSyncStatus).where(
                    SessionSyncStatus.season_year == season_year,
                    SessionSyncStatus.round_number == round_number,
                    SessionSyncStatus.session_type == session_type,
                )
            ).scalar_one_or_none()

        if rec is None:
            rec = SessionSyncStatus(
                season_year=season_year,
                round_number=round_number,
                event_name=event_name,
                session_type=session_type,
                session_name=session_type,
                event_id=event_id,
                session_id=session_id,
            )
            db.add(rec)

        rec.status = status
        rec.data_categories = data_categories
        rec.records_inserted = inserted
        rec.records_updated = updated
        rec.records_skipped = skipped
        rec.failure_reason = failure_reason
        rec.completed_at_utc = now_utc
        rec.last_synced_at_utc = now_utc
        rec.event_name = event_name
        rec.round_number = round_number
        if event_id is not None:
            rec.event_id = event_id
        if session_id is not None:
            rec.session_id = session_id

        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def get_season_sync_status(season_year: int, session_factory=None) -> list[dict[str, Any]]:
    """Return synchronization records for all rounds in a season."""
    factory = session_factory or SessionLocal
    db: DBSession = factory()
    try:
        recs = db.execute(
            select(SessionSyncStatus)
            .where(SessionSyncStatus.season_year == season_year)
            .order_by(SessionSyncStatus.round_number.asc())
        ).scalars().all()

        return [
            {
                "round_number": r.round_number,
                "event_name": r.event_name,
                "session_type": r.session_type,
                "event_id": r.event_id,
                "session_id": r.session_id,
                "status": r.status,
                "data_categories": r.data_categories,
                "records_inserted": r.records_inserted,
                "records_updated": r.records_updated,
                "records_skipped": r.records_skipped,
                "failure_reason": r.failure_reason,
                "last_synced_at": r.last_synced_at_utc.isoformat() if r.last_synced_at_utc else None,
            }
            for r in recs
        ]
    finally:
        db.close()


def get_all_seasons_sync_summary(session_factory=None) -> list[dict[str, Any]]:
    """Return high-level sync summary across all seasons."""
    factory = session_factory or SessionLocal
    db: DBSession = factory()
    try:
        recs = db.execute(select(SessionSyncStatus)).scalars().all()
        by_season: dict[int, list[SessionSyncStatus]] = {}
        for r in recs:
            by_season.setdefault(r.season_year, []).append(r)

        summaries = []
        for sy in sorted(by_season.keys(), reverse=True):
            s_recs = by_season[sy]
            completed = sum(1 for r in s_recs if r.status in ("COMPLETED", "PARTIAL"))
            scheduled = sum(1 for r in s_recs if r.status in ("SKIPPED", "PENDING"))
            failed = sum(1 for r in s_recs if r.status == "FAILED")
            last_dt = max((r.last_synced_at_utc for r in s_recs if r.last_synced_at_utc), default=None)
            summaries.append(
                {
                    "season_year": sy,
                    "total_tracked_rounds": len(s_recs),
                    "completed_rounds": completed,
                    "scheduled_rounds": scheduled,
                    "failed_rounds": failed,
                    "last_synced_at": last_dt.isoformat() if last_dt else None,
                }
            )
        return summaries
    finally:
        db.close()


# ---------------------------------------------------------------------
# Worker Execution Lock
# ---------------------------------------------------------------------


def _pid_is_alive(pid: int | None) -> bool:
    """Check if process with given PID is still active."""
    if pid is None or pid <= 0:
        return False
    try:
        return bool(psutil.pid_exists(pid))
    except Exception:
        return False


_pid_exists = _pid_is_alive


def is_worker_running(lock_path: Path | str | None = None) -> tuple[bool, int | None]:
    """Check if background sync worker is running via lock file."""
    p = Path(lock_path) if lock_path else DEFAULT_LOCK_FILE
    if not p.exists():
        return False, None
    try:
        raw = p.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        pid = int(data.get("pid", 0))
        if _pid_is_alive(pid):
            return True, pid
        # Stale lock file
        return False, pid
    except Exception:
        return False, None


def acquire_worker_lock(lock_path: Path | str | None = None) -> bool:
    """Acquire single-worker lock, returning True if acquired, False if already running."""
    p = Path(lock_path) if lock_path else DEFAULT_LOCK_FILE
    p.parent.mkdir(parents=True, exist_ok=True)

    running, existing_pid = is_worker_running(p)
    if running:
        return False

    try:
        proc = psutil.Process()
        proc_create_time = proc.create_time()
        proc_cmdline = proc.cmdline()
    except Exception:
        proc_create_time = None
        proc_cmdline = []

    payload = {
        "pid": os.getpid(),
        "create_time": proc_create_time,
        "cmdline": proc_cmdline,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "hostname": os.getenv("COMPUTERNAME", "localhost"),
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True


def release_worker_lock(lock_path: Path | str | None = None) -> None:
    """Release single-worker lock file."""
    p = Path(lock_path) if lock_path else DEFAULT_LOCK_FILE
    try:
        if p.exists():
            p.unlink()
    except Exception:
        pass
