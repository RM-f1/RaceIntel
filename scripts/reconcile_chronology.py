"""
CLI runner for RaceIntel Chronology and Metadata Reconciliation.

Usage:
    python scripts/reconcile_chronology.py --dry-run
    python scripts/reconcile_chronology.py --apply
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from raceintel.data.reconciliation import ChronologyReconciler, DEFAULT_DB_PATH


def main():
    parser = argparse.ArgumentParser(description="Reconcile RaceIntel event chronology against FastF1 authoritative schedules.")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Produce report without writing changes.")
    parser.add_argument("--apply", action="store_true", default=False, help="Apply proposed reconciliation changes.")
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB_PATH), help="Path to SQLite database.")
    parser.add_argument("--output-json", type=str, default="evaluation/chronology_reconciliation_report.json", help="Path to output JSON report.")

    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        print("Error: Specify either --dry-run or --apply")
        sys.exit(1)

    reconciler = ChronologyReconciler(db_path=args.db_path)
    dry_run = not args.apply

    print(f"\n=======================================================")
    print(f"RACEINTEL METADATA RECONCILIATION // DRY_RUN={dry_run}")
    print(f"Target Database: {args.db_path}")
    print(f"=======================================================\n")

    report = reconciler.reconcile_all_seasons(dry_run=dry_run, output_report_path=args.output_json)

    print(f"Seasons Inspected: {report.seasons_inspected}")
    print(f"Total Proposed Changes: {report.total_proposed_changes}")
    for s in report.season_summaries:
        print(f"  Season {s.season_year}: {s.status} (Auth={s.authoritative_rounds}, DB={s.db_events_count}, EvChanges={s.event_changes_count}, SyncChanges={s.sync_status_changes_count})")

    if report.proposed_changes:
        print(f"\nProposed Changes Detail ({len(report.proposed_changes)}):")
        for c in report.proposed_changes:
            print(f"  [{c.table}] {c.entity_name} (id={c.record_id}): {c.field_name} {c.old_value} -> {c.new_value} ({c.reason})")

    if args.apply:
        print("\nApplying reconciliation changes within atomic transaction...")
        result = reconciler.apply_reconciliation(report)
        print(f"Application Result: {result}")
        print("\nRe-running dry-run verification to assert idempotency...")
        verify_report = reconciler.reconcile_all_seasons(dry_run=True)
        print(f"Post-Application Pending Changes: {verify_report.total_proposed_changes}")
        if verify_report.total_proposed_changes == 0:
            print("SUCCESS: Chronology reconciliation is 100% IDEMPOTENT and complete.")
        else:
            print(f"WARNING: Remaining changes detected: {verify_report.total_proposed_changes}")
            sys.exit(2)


if __name__ == "__main__":
    main()
