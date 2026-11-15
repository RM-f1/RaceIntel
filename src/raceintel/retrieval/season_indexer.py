"""
Incremental ChromaDB Knowledge Base Indexer for RaceIntel.

Indexes race reports and driver reports into the persistent ChromaDB
`raceintel_knowledge` collection using deterministic IDs:
    - Race report:   `{season}_{round}` (e.g. `2022_1`)
    - Driver report: `{season}_{round}_{driver_full_name}` (e.g. `2022_1_Charles_Leclerc`)

Guarantees:
    - Queries Chroma before indexing to skip any document that already exists.
    - Existing 2024 documents (and any previously embedded documents) are never re-embedded or deleted.
    - Generates grounded documents directly from SQLite race results.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from database.connection import SessionLocal
from database.models import Constructor, Driver, Event, RaceResult, Season, Session as RaceSession
from raceintel.retrieval.chroma_client import ChromaClient
from raceintel.retrieval.generator import RaceDocumentGenerator
from raceintel.retrieval.schemas import RaceDocument


@dataclass
class IndexingStats:
    season_year: int
    total_generated: int = 0
    indexed_new: int = 0
    skipped_existing: int = 0
    errors: int = 0


class SeasonIndexer:
    """Manages incremental RAG document indexing from SQLite into ChromaDB."""

    def __init__(
        self,
        persist_directory: str = "data/chroma",
        session_factory=None,
    ) -> None:
        self.session_factory = session_factory or SessionLocal
        self.chroma = ChromaClient(persist_directory=persist_directory)

    def get_existing_doc_ids(self, candidate_ids: list[str]) -> set[str]:
        """Query ChromaDB for candidate IDs and return the set of IDs already present."""
        if not candidate_ids:
            return set()
        existing: set[str] = set()
        # Chroma .get supports batches of ids
        batch_size = 250
        for i in range(0, len(candidate_ids), batch_size):
            batch = candidate_ids[i : i + batch_size]
            try:
                res = self.chroma.collection.get(ids=batch)
                if res and res.get("ids"):
                    existing.update(res["ids"])
            except Exception:
                pass
        return existing

    def index_season(
        self,
        season_year: int,
        dry_run: bool = False,
        sprints_only: bool = False,
    ) -> IndexingStats:
        """Extract results from SQLite for season and index un-indexed documents into Chroma."""
        stats = IndexingStats(season_year=season_year)
        db = self.session_factory()

        try:
            season_rec = db.execute(
                select(Season).where(Season.season_year == season_year)
            ).scalar_one_or_none()

            if season_rec is None:
                print(f"[INDEXER] Season {season_year} not found in database.")
                return stats

            events = db.execute(
                select(Event)
                .where(Event.season_id == season_rec.season_id)
                .order_by(Event.round_number.asc())
            ).scalars().all()

            candidate_docs: list[RaceDocument] = []

            for ev in events:
                rnd = ev.round_number or 0

                if not sprints_only:
                    race_session = db.execute(
                        select(RaceSession).where(
                            RaceSession.event_id == ev.event_id,
                            RaceSession.session_type == "Race",
                        )
                    ).scalar_one_or_none()

                    if race_session is not None:
                        # Fetch race results ordered by finish position
                        results = db.execute(
                            select(RaceResult, Driver, Constructor)
                            .join(Driver, RaceResult.driver_id == Driver.driver_id)
                            .join(Constructor, RaceResult.constructor_id == Constructor.constructor_id)
                            .where(RaceResult.session_id == race_session.session_id)
                            .order_by(RaceResult.finish_position.asc())
                        ).all()

                        if results:
                            # Format race report data
                            winner_name = "Unknown"
                            podium_names = ["Unknown", "Unknown", "Unknown"]
                            classification_lines = []

                            for idx, (res, drv, con) in enumerate(results):
                                pos_str = f"P{res.finish_position}" if res.finish_position else "DNF"
                                pts_str = f"{res.points_scored:g} pts" if res.points_scored else "0 pts"
                                classification_lines.append(
                                    f"{pos_str}. {drv.driver_full_name} ({con.constructor_name}) - {pts_str}"
                                )
                                if res.finish_position == 1:
                                    winner_name = f"{drv.driver_full_name} ({con.constructor_name})"
                                if res.finish_position in (1, 2, 3) and res.finish_position <= 3:
                                    podium_names[res.finish_position - 1] = f"{drv.driver_full_name} ({con.constructor_name})"

                                # Generate individual driver summary document
                                driver_doc = RaceDocumentGenerator.generate_driver_summary(
                                    season=season_year,
                                    round_number=rnd,
                                    grand_prix=ev.event_name,
                                    driver=drv.driver_full_name,
                                    constructor=con.constructor_name,
                                    finish_position=res.finish_position or 99,
                                    points=float(res.points_scored or 0.0),
                                    country=ev.country_name or "Global",
                                )
                                candidate_docs.append(driver_doc)

                            summary_text = (
                                f"The {season_year} {ev.event_name} (Round {rnd}) took place at {ev.circuit_name or 'the circuit'}"
                                f" in {ev.country_name or 'the host country'}. "
                                f"The race was won by {winner_name}."
                            )

                            # Generate race report document
                            race_doc = RaceDocumentGenerator.generate_race_report(
                                season=season_year,
                                round_number=rnd,
                                grand_prix=ev.event_name,
                                winner=winner_name,
                                podium=podium_names,
                                classification="\n".join(classification_lines[:20]),
                                fastest_lap="Available in race telemetry records",
                                summary=summary_text,
                                country=ev.country_name or "Global",
                            )
                            candidate_docs.append(race_doc)

                # Fetch and index sprint session if present
                sprint_session = db.execute(
                    select(RaceSession).where(
                        RaceSession.event_id == ev.event_id,
                        RaceSession.session_type == "Sprint",
                    )
                ).scalar_one_or_none()

                if sprint_session is not None:
                    sprint_results = db.execute(
                        select(RaceResult, Driver, Constructor)
                        .join(Driver, RaceResult.driver_id == Driver.driver_id)
                        .join(Constructor, RaceResult.constructor_id == Constructor.constructor_id)
                        .where(RaceResult.session_id == sprint_session.session_id)
                        .order_by(RaceResult.finish_position.asc())
                    ).all()

                    if sprint_results:
                        sp_winner = "Unknown"
                        sp_podium = ["Unknown", "Unknown", "Unknown"]
                        sp_cls_lines = []

                        for s_idx, (res, drv, con) in enumerate(sprint_results):
                            pos_str = f"P{res.finish_position}" if res.finish_position else "DNF"
                            pts_str = f"{res.points_scored:g} pts" if res.points_scored else "0 pts"
                            sp_cls_lines.append(
                                f"{pos_str}. {drv.driver_full_name} ({con.constructor_name}) - {pts_str}"
                            )
                            if res.finish_position == 1:
                                sp_winner = f"{drv.driver_full_name} ({con.constructor_name})"
                            if res.finish_position in (1, 2, 3) and res.finish_position <= 3:
                                sp_podium[res.finish_position - 1] = f"{drv.driver_full_name} ({con.constructor_name})"

                            drv_sp_doc = RaceDocumentGenerator.generate_driver_sprint_summary(
                                season=season_year,
                                round_number=rnd,
                                grand_prix=ev.event_name,
                                driver=drv.driver_full_name,
                                constructor=con.constructor_name,
                                finish_position=res.finish_position or 99,
                                points=float(res.points_scored or 0.0),
                                country=ev.country_name or "Global",
                            )
                            candidate_docs.append(drv_sp_doc)

                        sp_summary_text = (
                            f"The {season_year} {ev.event_name} Sprint (Round {rnd}) took place at {ev.circuit_name or 'the circuit'}"
                            f" in {ev.country_name or 'the host country'}. "
                            f"The Sprint was won by {sp_winner}."
                        )

                        sp_doc = RaceDocumentGenerator.generate_sprint_report(
                            season=season_year,
                            round_number=rnd,
                            grand_prix=ev.event_name,
                            winner=sp_winner,
                            podium=sp_podium,
                            classification="\n".join(sp_cls_lines[:20]),
                            summary=sp_summary_text,
                            country=ev.country_name or "Global",
                        )
                        candidate_docs.append(sp_doc)

            stats.total_generated = len(candidate_docs)


            if not candidate_docs:
                print(f"[INDEXER] Season {season_year}: 0 candidate documents generated from SQLite.")
                return stats

            # Check existing document IDs to strictly avoid re-embedding
            candidate_ids = [doc.id for doc in candidate_docs]
            existing_ids = self.get_existing_doc_ids(candidate_ids)

            new_docs = [doc for doc in candidate_docs if doc.id not in existing_ids]
            stats.skipped_existing = len(existing_ids)
            stats.indexed_new = len(new_docs)

            if dry_run:
                print(
                    f"[INDEXER DRY-RUN] Season {season_year}: Total={stats.total_generated} | "
                    f"New={stats.indexed_new} | Existing={stats.skipped_existing}"
                )
                return stats

            if new_docs:
                print(f"[INDEXER] Season {season_year}: Upserting {len(new_docs)} new documents into ChromaDB...")
                batch_size = 100
                for b_idx in range(0, len(new_docs), batch_size):
                    batch = new_docs[b_idx : b_idx + batch_size]
                    self.chroma.add_documents(batch)
                print(f"[INDEXER] Season {season_year}: Successfully indexed {len(new_docs)} documents.")
            else:
                print(f"[INDEXER] Season {season_year}: All {stats.total_generated} documents already indexed in ChromaDB.")

            return stats

        finally:
            db.close()

    def index_sprints(self, season_year: int, dry_run: bool = False) -> IndexingStats:
        """Extract Sprint results from SQLite and index sprint documents into ChromaDB."""
        return self.index_season(season_year=season_year, dry_run=dry_run, sprints_only=True)


def index_all_seasons(seasons: list[int] | None = None, dry_run: bool = False) -> list[IndexingStats]:
    """Index all supported championship seasons into ChromaDB."""
    target_seasons = seasons or [2022, 2023, 2024, 2025, 2026]
    indexer = SeasonIndexer()
    results = []
    print("\n==================================================")
    print("RACEINTEL MULTI-SEASON CHROMADB INDEXER")
    print(f"Target Seasons: {target_seasons} | Dry-Run: {dry_run}")
    print(f"Initial Collection Count: {indexer.chroma.count()}")
    print("==================================================\n")

    for sy in target_seasons:
        stat = indexer.index_season(sy, dry_run=dry_run)
        results.append(stat)

    print("\n==================================================")
    print(f"FINAL CHROMADB COLLECTION COUNT: {indexer.chroma.count()}")
    print("==================================================\n")
    return results


# ---------------------------------------------------------------------
# CLI Entry Point (`python -m raceintel.retrieval.season_indexer`)
# ---------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RaceIntel Multi-Season ChromaDB Incremental Indexer",
        prog="python -m raceintel.retrieval.season_indexer",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Championship season year to index (e.g. 2022, 2023, 2025, 2026)",
    )
    parser.add_argument(
        "--all-seasons",
        action="store_true",
        default=False,
        help="Index all supported seasons (2022, 2023, 2024, 2025, 2026)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Calculate new vs existing document counts without embedding",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        default=False,
        help="Show current ChromaDB collection document count and stats",
    )
    parser.add_argument(
        "--sprints-only",
        action="store_true",
        default=False,
        help="Index only sprint reports and driver sprint summaries",
    )

    args = parser.parse_args()

    if args.status:
        chroma = ChromaClient()
        cnt = chroma.count()
        print(f"\nChromaDB Collection 'raceintel_knowledge' Total Documents: {cnt}\n")
        return

    if args.all_seasons:
        index_all_seasons(dry_run=args.dry_run)
        return

    if args.season:
        indexer = SeasonIndexer()
        indexer.index_season(args.season, dry_run=args.dry_run, sprints_only=args.sprints_only)
        return

    # Default if no arguments
    parser.print_help()


if __name__ == "__main__":
    main()