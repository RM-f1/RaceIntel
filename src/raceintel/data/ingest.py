"""
Reusable Data Ingestion Engine for RaceIntel.

Provides the central orchestrator for historical ingestion, incremental syncs,
and manual dashboard triggers, alongside the unified CLI:
    python -m raceintel.data.ingest --season <year>
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from database.connection import SessionLocal
from raceintel.data.fetcher import SessionFetcher
from raceintel.data.persister import SessionPersister
from raceintel.data.schedule import EventScheduleItem, ScheduleDiscovery
from raceintel.data.status import (
    get_all_seasons_sync_summary,
    get_season_sync_status,
    record_sync_completion,
    record_sync_start,
)
from raceintel.data.validator import SessionValidator


@dataclass
class IngestionReport:
    season_year: int
    total_rounds: int = 0
    processed_rounds: list[int] = field(default_factory=list)
    skipped_rounds: list[int] = field(default_factory=list)
    failed_rounds: list[dict[str, Any]] = field(default_factory=list)
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    duration_seconds: float = 0.0

    @property
    def is_success(self) -> bool:
        return len(self.failed_rounds) == 0


class IngestionEngine:
    """Orchestrates multi-season F1 schedule discovery, fetching, validation, and persistence."""

    def __init__(
        self,
        schedule_discovery: ScheduleDiscovery | None = None,
        fetcher: SessionFetcher | None = None,
        validator: SessionValidator | None = None,
        persister: SessionPersister | None = None,
        session_factory=None,
    ) -> None:
        self.schedule_discovery = schedule_discovery or ScheduleDiscovery()
        self.fetcher = fetcher or SessionFetcher()
        self.validator = validator or SessionValidator()
        self.persister = persister or SessionPersister(session_factory=session_factory)
        self.session_factory = session_factory or SessionLocal

    def ingest_season(
        self,
        season_year: int,
        round_number: int | None = None,
        incremental: bool = True,
        force_refresh: bool = False,
        dry_run: bool = False,
    ) -> IngestionReport:
        """
        Ingest or synchronize an entire season or a specific round.
        """
        start_t = time.time()
        report = IngestionReport(season_year=season_year)

        schedule = self.schedule_discovery.get_schedule(season_year, round_number=round_number)
        report.total_rounds = len(schedule.events)

        if report.total_rounds == 0:
            report.duration_seconds = time.time() - start_t
            return report

        status_list = get_season_sync_status(season_year, session_factory=self.session_factory)
        existing_by_round_type = {
            (r["round_number"], r.get("session_type", "Race")): r
            for r in status_list
        }
        existing_by_event_type = {
            (r["event_name"].strip().lower(), r.get("session_type", "Race")): r
            for r in status_list
        }

        print(f"\n==================================================")
        print(f"RACEINTEL INGESTION ENGINE // SEASON {season_year}")
        print(f"Sessions: {report.total_rounds} | Incremental: {incremental} | Force-Refresh: {force_refresh} | Dry-Run: {dry_run}")
        print(f"==================================================\n")

        for item in schedule.events:
            rnd = item.round_number
            stype = item.session_type
            ev_name = item.event_name
            # Look up status by both event name and round number for safe identity
            status_rec = existing_by_event_type.get((ev_name.strip().lower(), stype))
            if status_rec is None:
                cand = existing_by_round_type.get((rnd, stype))
                if cand and cand.get("event_name", "").strip().lower() == ev_name.strip().lower():
                    status_rec = cand

            # Incremental check: if already completed and has results, skip unless force_refresh
            if (
                incremental
                and not force_refresh
                and status_rec is not None
                and status_rec.get("status") in ("COMPLETED", "PARTIAL")
                and status_rec.get("event_name", "").strip().lower() == ev_name.strip().lower()
            ):
                print(f"[{stype.upper()} R{rnd:02d}] {ev_name} -> SKIPPED (Already {status_rec.get('status')})")
                report.skipped_rounds.append(rnd)
                report.records_skipped += status_rec.get("records_inserted", 0)
                continue

            if dry_run:
                print(f"[DRY-RUN] Would process {stype.upper()} Round {rnd:02d}: {ev_name} (completed_est={item.is_completed})")
                report.processed_rounds.append(rnd)
                continue

            print(f"[{stype.upper()} R{rnd:02d}] Ingesting {ev_name}...")
            record_sync_start(
                season_year=season_year,
                round_number=rnd,
                event_name=ev_name,
                session_type=item.session_type,
                session_factory=self.session_factory,
            )

            try:
                fetched = self.fetcher.fetch_session(item)

                if fetched.error_message and not fetched.has_results:
                    # If this is an upcoming uncompleted round in 2026, mark as SKIPPED / SCHEDULED
                    if not item.is_completed:
                        # Safely register Event and RaceSession in database without race results
                        try:
                            self.persister.persist_session(
                                fetched,
                                incremental=incremental,
                                force_refresh=force_refresh,
                            )
                        except Exception:
                            pass
                        record_sync_completion(
                            season_year=season_year,
                            round_number=rnd,
                            event_name=ev_name,
                            status="SKIPPED",
                            data_categories="schedule",
                            session_type=item.session_type,
                            session_factory=self.session_factory,
                        )
                        print(f"  -> Round {rnd:02d} is upcoming/scheduled. Preserved in schedule.")
                        report.skipped_rounds.append(rnd)
                        continue

                    record_sync_completion(
                        season_year=season_year,
                        round_number=rnd,
                        event_name=ev_name,
                        status="FAILED",
                        failure_reason=fetched.error_message,
                        session_type=item.session_type,
                        session_factory=self.session_factory,
                    )
                    print(f"  -> FAILED: {fetched.error_message}")
                    report.failed_rounds.append({"round": rnd, "event": ev_name, "error": fetched.error_message})
                    continue

                val_res = self.validator.validate(fetched)
                if not val_res.is_valid:
                    err_msg = "; ".join(val_res.issues)
                    record_sync_completion(
                        season_year=season_year,
                        round_number=rnd,
                        event_name=ev_name,
                        status="FAILED",
                        failure_reason=err_msg,
                        session_type=item.session_type,
                        session_factory=self.session_factory,
                    )
                    print(f"  -> VALIDATION FAILED: {err_msg}")
                    report.failed_rounds.append({"round": rnd, "event": ev_name, "error": err_msg})
                    continue

                # Persist
                pers_sum = self.persister.persist_session(
                    fetched,
                    incremental=incremental,
                    force_refresh=force_refresh,
                )

                record_sync_completion(
                    season_year=season_year,
                    round_number=rnd,
                    event_name=ev_name,
                    status=pers_sum.status,
                    data_categories=pers_sum.data_categories,
                    inserted=pers_sum.records_inserted,
                    updated=pers_sum.records_updated,
                    skipped=pers_sum.records_skipped,
                    session_type=item.session_type,
                    session_id=pers_sum.session_id,
                    session_factory=self.session_factory,
                )

                if pers_sum.status == "FAILED":
                    print(f"  -> PERSISTENCE FAILED: {pers_sum.error_message}")
                    report.failed_rounds.append({"round": rnd, "event": ev_name, "error": pers_sum.error_message})
                    continue

                print(
                    f"  -> SUCCESS: Status={pers_sum.status} | "
                    f"Inserted={pers_sum.records_inserted} | "
                    f"Updated={pers_sum.records_updated} | "
                    f"Categories=[{pers_sum.data_categories}]"
                )
                report.processed_rounds.append(rnd)
                report.records_inserted += pers_sum.records_inserted
                report.records_updated += pers_sum.records_updated
                report.records_skipped += pers_sum.records_skipped

            except Exception as exc:
                err_str = str(exc)
                record_sync_completion(
                    season_year=season_year,
                    round_number=rnd,
                    event_name=ev_name,
                    status="FAILED",
                    failure_reason=err_str,
                    session_type=item.session_type,
                    session_factory=self.session_factory,
                )
                print(f"  -> EXCEPTION in Round {rnd:02d}: {err_str}")
                report.failed_rounds.append({"round": rnd, "event": ev_name, "error": err_str})

        report.duration_seconds = round(time.time() - start_t, 2)
        print(f"\nSeason {season_year} Ingestion Finished in {report.duration_seconds}s.")
        print(f"Processed: {len(report.processed_rounds)} | Skipped: {len(report.skipped_rounds)} | Failed: {len(report.failed_rounds)}\n")
        return report


def run_ingest(
    season: int,
    round_number: int | None = None,
    incremental: bool = True,
    force_refresh: bool = False,
    dry_run: bool = False,
) -> IngestionReport:
    """Convenience function to execute ingestion."""
    engine = IngestionEngine()
    return engine.ingest_season(
        season_year=season,
        round_number=round_number,
        incremental=incremental,
        force_refresh=force_refresh,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------
# CLI Entry Point (`python -m raceintel.data.ingest`)
# ---------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RaceIntel Multi-Season Data Ingestion Engine",
        prog="python -m raceintel.data.ingest",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Championship season year to ingest (e.g. 2022, 2023, 2024, 2025, 2026)",
    )
    parser.add_argument(
        "--round",
        type=int,
        default=None,
        help="Specific championship round number to ingest (optional)",
    )
    parser.add_argument(
        "--incremental",
        dest="incremental",
        action="store_true",
        default=True,
        help="Skip already completed sessions (default: True)",
    )
    parser.add_argument(
        "--no-incremental",
        dest="incremental",
        action="store_false",
        help="Do not skip completed sessions",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        default=False,
        help="Force replace existing records for requested rounds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate schedule discovery and planned operations without database modifications",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Display current synchronization summary across all seasons",
    )

    args = parser.parse_args()

    if args.status:
        summaries = get_all_seasons_sync_summary()
        print("\n=======================================================")
        print("RACEINTEL MULTI-SEASON SYNCHRONIZATION STATUS")
        print("=======================================================")
        if not summaries:
            print("No synchronization records found in database.")
        for s in summaries:
            print(
                f"Season {s['season_year']}: Tracked={s['total_tracked_rounds']} | "
                f"Completed={s['completed_rounds']} | Scheduled={s['scheduled_rounds']} | "
                f"Failed={s['failed_rounds']} | Last Synced={s['last_synced_at'] or 'Never'}"
            )
        print()
        if args.season is None:
            return

    if args.season is None:
        parser.print_help()
        sys.exit(1)

    rep = run_ingest(
        season=args.season,
        round_number=args.round,
        incremental=args.incremental,
        force_refresh=args.force_refresh,
        dry_run=args.dry_run,
    )

    if not rep.is_success:
        sys.exit(1)


if __name__ == "__main__":
    main()
