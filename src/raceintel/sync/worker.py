"""
RaceIntel Background Synchronization Worker.

Manages periodic, automated synchronization of Formula 1 season data
with single-worker process locking, retry with backoff, and graceful shutdown.

CLI Usage:
    python -m raceintel.sync.worker --once
    python -m raceintel.sync.worker --interval-seconds 3600 --seasons 2026
    python -m raceintel.sync.worker --status
    python -m raceintel.sync.worker --stop
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from raceintel.data.ingest import IngestionEngine, IngestionReport
from raceintel.data.status import (
    DEFAULT_LOCK_FILE,
    acquire_worker_lock,
    get_all_seasons_sync_summary,
    is_worker_running,
    release_worker_lock,
)

logger = logging.getLogger("raceintel.sync.worker")


class SyncWorker:
    """Automated background worker for multi-season F1 synchronization."""

    def __init__(
        self,
        interval_seconds: int = 3600,
        seasons: list[int] | None = None,
        incremental: bool = True,
        force_refresh: bool = False,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        lock_path: Path | str | None = None,
    ) -> None:
        self.interval_seconds = max(10, interval_seconds)
        self.seasons = seasons if seasons is not None else [2026]
        self.incremental = incremental
        self.force_refresh = force_refresh
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.lock_path = lock_path
        self._stop_requested = False
        self._engine = IngestionEngine()

    def _handle_signal(self, signum: int, frame: Any) -> None:
        logger.info(f"Signal {signum} received. Requesting graceful shutdown...")
        print(f"\n[SYNC-WORKER] Signal {signum} received. Shutting down gracefully...")
        self._stop_requested = True

    def run_once(self) -> dict[int, IngestionReport]:
        """Execute one complete synchronization cycle across configured seasons."""
        results: dict[int, IngestionReport] = {}
        for season in self.seasons:
            if self._stop_requested:
                logger.info("Sync cycle interrupted by stop request.")
                break

            logger.info(f"Starting sync pass for Season {season}...")
            attempts = 0
            while attempts < self.max_retries and not self._stop_requested:
                attempts += 1
                try:
                    report = self._engine.ingest_season(
                        season_year=season,
                        incremental=self.incremental,
                        force_refresh=self.force_refresh,
                    )
                    results[season] = report
                    break
                except Exception as exc:
                    logger.error(
                        f"Sync pass failed for Season {season} (attempt {attempts}/{self.max_retries}): {exc}"
                    )
                    if attempts < self.max_retries:
                        sleep_time = self.backoff_factor**attempts
                        logger.info(f"Retrying Season {season} in {sleep_time:.1f}s...")
                        time.sleep(sleep_time)
                    else:
                        logger.error(f"Season {season} sync aborted after {self.max_retries} attempts.")
        return results

    def start(self) -> None:
        """Run the worker loop continuously until stopped."""
        if not acquire_worker_lock(self.lock_path):
            running, pid = is_worker_running(self.lock_path)
            err = f"Worker lock already held by active process PID={pid}. Aborting start."
            print(f"[SYNC-WORKER ERROR] {err}")
            raise RuntimeError(err)

        # Register signals
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        print(f"==================================================")
        print(f"RACEINTEL BACKGROUND SYNC WORKER STARTED")
        print(f"PID: {os.getpid()} | Interval: {self.interval_seconds}s | Seasons: {self.seasons}")
        print(f"==================================================")

        try:
            while not self._stop_requested:
                cycle_start = time.time()
                print(f"\n[SYNC-WORKER] Commencing synchronization cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
                self.run_once()
                print(f"[SYNC-WORKER] Cycle complete. Sleeping for {self.interval_seconds}s...")

                # Sleep in short increments to respond quickly to shutdown signal
                slept = 0
                while slept < self.interval_seconds and not self._stop_requested:
                    time.sleep(1)
                    slept += 1

        finally:
            release_worker_lock(self.lock_path)
            print(f"[SYNC-WORKER] Worker stopped and lock released.")


def stop_running_worker(lock_path: Path | str | None = None) -> bool:
    """Safely verify and terminate any active worker identified by the lock file."""
    p = Path(lock_path) if lock_path else DEFAULT_LOCK_FILE
    if not p.exists():
        print("[SYNC-WORKER] No active sync worker is running.")
        return False

    try:
        raw = p.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        pid = int(data.get("pid", 0))
        lock_create_time = data.get("create_time")
    except Exception:
        print("[SYNC-WORKER WARNING] Corrupted lock file. Releasing stale lock.")
        release_worker_lock(p)
        return False

    if not pid or not psutil.pid_exists(pid):
        print(f"[SYNC-WORKER] Process with PID {pid} is dead or not running. Cleaning stale lock file.")
        release_worker_lock(p)
        return False

    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, ProcessLookupError):
        print(f"[SYNC-WORKER] Process with PID {pid} no longer exists. Cleaning stale lock file.")
        release_worker_lock(p)
        return False
    except Exception as exc:
        print(f"[SYNC-WORKER WARNING] Could not inspect process {pid}: {exc}")
        release_worker_lock(p)
        return False

    # Check 1: create_time must be present
    if lock_create_time is None:
        print(
            f"[SYNC-WORKER WARNING] Lock file for PID {pid} lacks create_time (old format). "
            f"Unverified process; refusing to terminate. Releasing stale lock."
        )
        release_worker_lock(p)
        return False

    # Check 2: create_time must match within 1.0 second
    try:
        proc_create_time = proc.create_time()
    except Exception as exc:
        print(f"[SYNC-WORKER WARNING] Could not retrieve create_time for PID {pid}: {exc}")
        release_worker_lock(p)
        return False

    if abs(proc_create_time - float(lock_create_time)) > 1.0:
        print(
            f"[SYNC-WORKER WARNING] Process PID {pid} create_time ({proc_create_time}) "
            f"does not match lock create_time ({lock_create_time}). Possible PID reuse; "
            f"refusing to terminate. Releasing stale lock."
        )
        release_worker_lock(p)
        return False

    # Process verified as OUR worker! Terminate safely
    print(f"[SYNC-WORKER] Verified worker process PID {pid}. Terminating...")
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            print(f"[SYNC-WORKER WARNING] Process {pid} did not exit within 3 seconds. Escalating to kill...")
            proc.kill()
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
    except (psutil.NoSuchProcess, ProcessLookupError):
        pass
    except Exception as exc:
        print(f"[SYNC-WORKER WARNING] Error while terminating process {pid}: {exc}")
    finally:
        release_worker_lock(p)
        print(f"[SYNC-WORKER] Worker PID {pid} stopped.")
    return True


# ---------------------------------------------------------------------
# CLI Entry Point (`python -m raceintel.sync.worker`)
# ---------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RaceIntel Automated Background Sync Worker",
        prog="python -m raceintel.sync.worker",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=3600,
        help="Synchronization loop interval in seconds (default: 3600)",
    )
    parser.add_argument(
        "--seasons",
        type=str,
        default="2026",
        help="Comma-separated seasons to keep synchronized (default: 2026)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run synchronization once and exit immediately",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Show active worker process status and sync summary",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        default=False,
        help="Stop the currently running background worker",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        default=False,
        help="Force overwrite existing records for sessions in configured seasons",
    )

    args = parser.parse_args()

    if args.stop:
        stop_running_worker()
        return

    if args.status:
        running, pid = is_worker_running()
        print("\n==================================================")
        print("RACEINTEL SYNC WORKER STATUS")
        print("==================================================")
        if running:
            print(f"Worker State: RUNNING (PID={pid})")
        else:
            print("Worker State: STOPPED / IDLE")

        summaries = get_all_seasons_sync_summary()
        print("\nDatabase Season Summaries:")
        for s in summaries:
            print(
                f"  Season {s['season_year']}: Tracked={s['total_tracked_rounds']} | "
                f"Completed={s['completed_rounds']} | Scheduled={s['scheduled_rounds']} | "
                f"Failed={s['failed_rounds']} | Last Synced={s['last_synced_at']}"
            )
        print("==================================================\n")
        return

    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]

    worker = SyncWorker(
        interval_seconds=args.interval_seconds,
        seasons=seasons,
        force_refresh=args.force_refresh,
    )

    if args.once:
        print(f"[SYNC-WORKER] Running one-shot synchronization pass for seasons {seasons}...")
        res = worker.run_once()
        print(f"[SYNC-WORKER] One-shot pass completed across {len(res)} seasons.")
        return

    worker.start()


if __name__ == "__main__":
    main()
