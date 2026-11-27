"""
Authoritative Event Chronology and Metadata Reconciliation Engine for RaceIntel.

Provides reusable, season-independent metadata reconciliation across seasons 2022–2026.
Compares stored SQLite event metadata with FastF1 official schedules, matching events
using stable identity and validated aliases. Produces dry-run reports before applying
any changes, guarantees transaction safety, and enforces strict idempotency.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.connection import PROJECT_ROOT
from raceintel.data.schedule import EventScheduleItem, ScheduleDiscovery
from raceintel.services.event_aliases import (
    EXPLICIT_EVENT_ALIASES,
    normalize_text,
    strip_gp_suffix,
)

logger = logging.getLogger(__name__)

from database.connection import resolve_database_path

DEFAULT_DB_PATH = resolve_database_path()


@dataclass
class ProposedChange:
    season_year: int
    table: str
    record_id: int
    entity_name: str
    field_name: str
    old_value: Any
    new_value: Any
    reason: str


@dataclass
class SeasonReconciliationSummary:
    season_year: int
    authoritative_rounds: int
    db_events_count: int
    matched_events_count: int
    event_changes_count: int
    sync_status_changes_count: int
    status: str = "MATCHED"  # MATCHED, CORRECTIONS_PROPOSED, UNRESOLVED
    unresolved_reason: str | None = None


@dataclass
class ReconciliationReport:
    generated_at_utc: str
    dry_run: bool
    seasons_inspected: list[int]
    total_proposed_changes: int
    season_summaries: list[SeasonReconciliationSummary] = field(default_factory=list)
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    unresolved_items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "dry_run": self.dry_run,
            "seasons_inspected": self.seasons_inspected,
            "total_proposed_changes": self.total_proposed_changes,
            "season_summaries": [asdict(s) for s in self.season_summaries],
            "proposed_changes": [asdict(c) for c in self.proposed_changes],
            "unresolved_items": self.unresolved_items,
        }


class ChronologyReconciler:
    """
    Reusable metadata reconciler that aligns SQLite event metadata with authoritative FastF1 schedules.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        schedule_discovery: ScheduleDiscovery | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.schedule_discovery = schedule_discovery or ScheduleDiscovery()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _match_event_name(self, auth_name: str, db_events: list[sqlite3.Row]) -> sqlite3.Row | None:
        """
        Match authoritative FastF1 event name to stored database event using:
        1. Exact normalized name
        2. Clean stem without 'Grand Prix'
        3. Validated aliases from EXPLICIT_EVENT_ALIASES
        """
        auth_norm = normalize_text(auth_name)
        auth_stem = strip_gp_suffix(auth_norm)

        # 1. Exact normalized match
        for ev in db_events:
            ev_norm = normalize_text(ev["event_name"])
            if auth_norm == ev_norm:
                return ev

        # 2. Match via stem (e.g. 'monaco' == 'monaco')
        if auth_stem:
            for ev in db_events:
                ev_norm = normalize_text(ev["event_name"])
                ev_stem = strip_gp_suffix(ev_norm)
                if auth_stem == ev_stem:
                    return ev

        # 3. Validated aliases
        for canon, aliases in EXPLICIT_EVENT_ALIASES.items():
            canon_norm = normalize_text(canon)
            if auth_norm == canon_norm or auth_stem == strip_gp_suffix(canon_norm):
                for ev in db_events:
                    ev_norm = normalize_text(ev["event_name"])
                    if ev_norm in [normalize_text(a) for a in aliases] or ev_norm == canon_norm:
                        return ev

        return None

    def reconcile_season(
        self,
        season_year: int,
        dry_run: bool = True,
    ) -> tuple[SeasonReconciliationSummary, list[ProposedChange], list[dict[str, Any]]]:
        """
        Inspect and optionally correct chronology metadata for a single season.
        """
        changes: list[ProposedChange] = []
        unresolved: list[dict[str, Any]] = []

        try:
            sched = self.schedule_discovery.get_schedule(season_year)
        except Exception as e:
            return (
                SeasonReconciliationSummary(
                    season_year=season_year,
                    authoritative_rounds=0,
                    db_events_count=0,
                    matched_events_count=0,
                    event_changes_count=0,
                    sync_status_changes_count=0,
                    status="UNRESOLVED",
                    unresolved_reason=f"Failed to fetch authoritative schedule: {e}",
                ),
                [],
                [{"season_year": season_year, "error": str(e)}],
            )

        # Deduplicate schedule by event (one per round_number)
        auth_by_round: dict[int, EventScheduleItem] = {}
        for ev in sched.events:
            if ev.round_number not in auth_by_round:
                auth_by_round[ev.round_number] = ev

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT e.event_id, e.season_id, e.event_name, e.round_number, e.country_name, e.circuit_name
                FROM events e
                JOIN seasons se ON e.season_id = se.season_id
                WHERE se.season_year = ?
                ORDER BY e.event_id ASC;
                """,
                (season_year,),
            )
            db_events = cur.fetchall()

            cur.execute(
                """
                SELECT sync_id, season_year, round_number, event_name, session_type, status
                FROM session_sync_status
                WHERE season_year = ?
                ORDER BY sync_id ASC;
                """,
                (season_year,),
            )
            db_sync = cur.fetchall()

            cur.execute(
                """
                SELECT s.session_id, s.event_id, s.session_type, s.session_name
                FROM sessions s
                JOIN events e ON s.event_id = e.event_id
                JOIN seasons se ON e.season_id = se.season_id
                WHERE se.season_year = ?;
                """,
                (season_year,),
            )
            db_sessions = cur.fetchall()

        finally:
            conn.close()

        matched_count = 0
        db_matched_ids: set[int] = set()

        for auth_rnd, auth_item in sorted(auth_by_round.items()):
            matched_ev = self._match_event_name(auth_item.event_name, db_events)
            if not matched_ev:
                unresolved.append(
                    {
                        "season_year": season_year,
                        "round_number": auth_rnd,
                        "event_name": auth_item.event_name,
                        "reason": "Authoritative event could not be confidently matched in database.",
                    }
                )
                continue

            matched_count += 1
            db_matched_ids.add(matched_ev["event_id"])
            current_ev_round = matched_ev["round_number"]

            # 1. Compare events.round_number
            if current_ev_round != auth_rnd:
                changes.append(
                    ProposedChange(
                        season_year=season_year,
                        table="events",
                        record_id=matched_ev["event_id"],
                        entity_name=matched_ev["event_name"],
                        field_name="round_number",
                        old_value=current_ev_round,
                        new_value=auth_rnd,
                        reason=f"FastF1 authoritative schedule designates {auth_item.event_name} as Round {auth_rnd}",
                    )
                )

            # 2. Compare session_sync_status records for this event
            # Match sync status rows for this event by event_name
            ev_sync_rows = [
                r for r in db_sync
                if normalize_text(r["event_name"]) == normalize_text(matched_ev["event_name"])
                or strip_gp_suffix(normalize_text(r["event_name"])) == strip_gp_suffix(normalize_text(matched_ev["event_name"]))
            ]

            for srow in ev_sync_rows:
                if srow["round_number"] != auth_rnd:
                    changes.append(
                        ProposedChange(
                            season_year=season_year,
                            table="session_sync_status",
                            record_id=srow["sync_id"],
                            entity_name=f"{srow['event_name']} [{srow['session_type']}]",
                            field_name="round_number",
                            old_value=srow["round_number"],
                            new_value=auth_rnd,
                            reason=f"Align sync tracking round with authoritative Round {auth_rnd}",
                        )
                    )

        ev_changes = sum(1 for c in changes if c.table == "events")
        sync_changes = sum(1 for c in changes if c.table == "session_sync_status")

        status = "MATCHED"
        if len(unresolved) > 0:
            status = "UNRESOLVED"
        elif len(changes) > 0:
            status = "CORRECTIONS_PROPOSED"

        summary = SeasonReconciliationSummary(
            season_year=season_year,
            authoritative_rounds=len(auth_by_round),
            db_events_count=len(db_events),
            matched_events_count=matched_count,
            event_changes_count=ev_changes,
            sync_status_changes_count=sync_changes,
            status=status,
        )

        return summary, changes, unresolved

    def reconcile_all_seasons(
        self,
        seasons: tuple[int, ...] = (2022, 2023, 2024, 2025, 2026),
        dry_run: bool = True,
        output_report_path: Path | str | None = None,
    ) -> ReconciliationReport:
        """
        Execute full cross-season reconciliation dry-run or application.
        """
        all_summaries: list[SeasonReconciliationSummary] = []
        all_changes: list[ProposedChange] = []
        all_unresolved: list[dict[str, Any]] = []

        for yr in seasons:
            summary, changes, unresolved = self.reconcile_season(yr, dry_run=dry_run)
            all_summaries.append(summary)
            all_changes.extend(changes)
            all_unresolved.extend(unresolved)

        report = ReconciliationReport(
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            dry_run=dry_run,
            seasons_inspected=list(seasons),
            total_proposed_changes=len(all_changes),
            season_summaries=all_summaries,
            proposed_changes=all_changes,
            unresolved_items=all_unresolved,
        )

        if output_report_path:
            out_p = Path(output_report_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            with open(out_p, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2)

        return report

    def apply_reconciliation(
        self,
        report: ReconciliationReport,
    ) -> dict[str, Any]:
        """
        Safely apply proposed reconciliation changes within a single database transaction.
        Preserves all factual tables (race_results, laps, weather_observations, drivers, constructors).
        """
        if not report.proposed_changes:
            return {"applied_changes": 0, "status": "noop", "integrity_check": "ok"}

        conn = self._get_connection()
        try:
            cur = conn.cursor()

            # Record baseline row counts for protected tables
            protected_counts_before = {}
            for tbl in ["race_results", "laps", "weather_observations", "drivers", "constructors", "sessions"]:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                protected_counts_before[tbl] = cur.fetchone()[0]

            # 1. Update events.round_number
            event_changes = [c for c in report.proposed_changes if c.table == "events"]
            for c in event_changes:
                cur.execute(
                    "UPDATE events SET round_number = ? WHERE event_id = ?;",
                    (c.new_value, c.record_id),
                )

            # 2. Update session_sync_status.round_number safely
            # To prevent unique constraint violation during reordering, shift affected rows
            # to temporary negative rounds first, then assign final authoritative rounds.
            sync_changes = [c for c in report.proposed_changes if c.table == "session_sync_status"]
            if sync_changes:
                for c in sync_changes:
                    cur.execute(
                        "UPDATE session_sync_status SET round_number = -round_number - 1000 WHERE sync_id = ?;",
                        (c.record_id,),
                    )
                for c in sync_changes:
                    cur.execute(
                        "UPDATE session_sync_status SET round_number = ? WHERE sync_id = ?;",
                        (c.new_value, c.record_id),
                    )

            # 3. Ensure event_id and session_id foreign keys are linked in session_sync_status
            cur.execute("PRAGMA table_info(session_sync_status);")
            col_names = {col["name"] for col in cur.fetchall()}

            if "event_id" not in col_names:
                cur.execute("ALTER TABLE session_sync_status ADD COLUMN event_id INTEGER REFERENCES events(event_id);")
            if "session_id" not in col_names:
                cur.execute("ALTER TABLE session_sync_status ADD COLUMN session_id INTEGER REFERENCES sessions(session_id);")

            # Populate event_id and session_id for all rows
            cur.execute(
                """
                UPDATE session_sync_status
                SET event_id = (
                    SELECT e.event_id
                    FROM events e
                    JOIN seasons se ON e.season_id = se.season_id
                    WHERE se.season_year = session_sync_status.season_year
                      AND LOWER(e.event_name) = LOWER(session_sync_status.event_name)
                    LIMIT 1
                )
                WHERE event_id IS NULL;
                """
            )
            cur.execute(
                """
                UPDATE session_sync_status
                SET session_id = (
                    SELECT s.session_id
                    FROM sessions s
                    WHERE s.event_id = session_sync_status.event_id
                      AND s.session_type = session_sync_status.session_type
                    LIMIT 1
                )
                WHERE session_id IS NULL AND event_id IS NOT NULL;
                """
            )

            # Add index on event_id, session_id if not present
            cur.execute("CREATE INDEX IF NOT EXISTS ix_sync_event_id ON session_sync_status(event_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_sync_session_id ON session_sync_status(session_id);")

            # 4. Verify integrity and foreign keys
            cur.execute("PRAGMA foreign_key_check;")
            fk_violations = cur.fetchall()
            if fk_violations:
                raise RuntimeError(f"Foreign key integrity violation after reconciliation: {fk_violations}")

            cur.execute("PRAGMA integrity_check;")
            integrity_rows = cur.fetchall()
            integrity_status = integrity_rows[0][0] if integrity_rows else "unknown"
            if integrity_status.lower() != "ok":
                raise RuntimeError(f"Database integrity check failed: {integrity_status}")

            # 5. Verify protected tables were untouched
            protected_counts_after = {}
            for tbl in ["race_results", "laps", "weather_observations", "drivers", "constructors", "sessions"]:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                protected_counts_after[tbl] = cur.fetchone()[0]

            for tbl, cnt_before in protected_counts_before.items():
                cnt_after = protected_counts_after[tbl]
                if cnt_before != cnt_after:
                    raise RuntimeError(
                        f"CRITICAL SAFETY VIOLATION: Row count in protected table '{tbl}' changed from {cnt_before} to {cnt_after}!"
                    )

            conn.commit()

            return {
                "applied_changes": len(report.proposed_changes),
                "event_changes": len(event_changes),
                "sync_changes": len(sync_changes),
                "status": "success",
                "integrity_check": integrity_status,
                "fk_check": "ok",
                "protected_counts": protected_counts_after,
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
