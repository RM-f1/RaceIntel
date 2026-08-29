from __future__ import annotations

import fastf1

from raceintel.retrieval.chroma_client import ChromaClient
from data.fastf1_loader import load_session


class SeasonIndexer:
    """Indexes an entire Formula 1 season into the RaceIntel knowledge base."""

    def __init__(self, season: int = 2024, overwrite: bool = True) -> None:
        self.season = season
        self.overwrite = overwrite

        # Create one Chroma client for the entire indexing run
        self.chroma = ChromaClient()

    def index(self) -> None:
        """Iterate through every championship race."""

        print(f"\nIndexing {self.season} Formula 1 season...\n")

        schedule = fastf1.get_event_schedule(self.season)

        # Skip pre-season testing
        schedule = schedule[schedule["RoundNumber"] > 0]

        total_events = len(schedule)

        for idx, (_, event) in enumerate(schedule.iterrows(), start=1):

            round_number = int(event["RoundNumber"])

            race = {
                "season": self.season,
                "round": round_number,
                "race_name": event["EventName"],
                "country": event["Country"],
                "location": event["Location"],
            }

            print(
                f"[{idx}/{total_events}] "
                f"Round {race['round']}: {race['race_name']}"
            )

            self._index_race(race)

        print("\nSeason iteration complete.")

    def _index_race(self, race: dict) -> None:

        session = load_session(
            year=race["season"],
            grand_prix=race["race_name"],
            session_type="R",

        )
        """
        Placeholder for the indexing pipeline.

        Later this method will:
        - Load the FastF1 race session
        - Generate race report
        - Generate driver reports
        - Index documents into ChromaDB
        """

        print(
            f"    Indexing {race['race_name']}..."
        )


def index_season(
    season: int = 2024,
    overwrite: bool = True,
) -> None:
    """Entry point for indexing an entire season."""

    indexer = SeasonIndexer(
        season=season,
        overwrite=overwrite,
    )

    indexer.index()