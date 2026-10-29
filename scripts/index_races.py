from analytics.race_report import generate_race_report
from analytics.standings import get_driver_standings
from database.connection import query_to_dataframe

from raceintel.retrieval.chroma_client import ChromaClient
from raceintel.retrieval.generator import RaceDocumentGenerator


# Actual 2024 Formula 1 championship round numbers.
ROUND_NUMBERS_2024 = {
    "Bahrain Grand Prix": 1,
    "Saudi Arabian Grand Prix": 2,
    "Australian Grand Prix": 3,
    "Japanese Grand Prix": 4,
    "Chinese Grand Prix": 5,
    "Miami Grand Prix": 6,
    "Emilia Romagna Grand Prix": 7,
    "Monaco Grand Prix": 8,
    "Canadian Grand Prix": 9,
    "Spanish Grand Prix": 10,
    "Austrian Grand Prix": 11,
    "British Grand Prix": 12,
    "Hungarian Grand Prix": 13,
    "Belgian Grand Prix": 14,
    "Dutch Grand Prix": 15,
    "Italian Grand Prix": 16,
    "Azerbaijan Grand Prix": 17,
    "Singapore Grand Prix": 18,
    "United States Grand Prix": 19,
    "Mexico City Grand Prix": 20,
    "São Paulo Grand Prix": 21,
    "Las Vegas Grand Prix": 22,
    "Qatar Grand Prix": 23,
    "Abu Dhabi Grand Prix": 24,
}


def main():
    sessions = query_to_dataframe(
        """
        SELECT
            s.session_id,
            se.season_year,
            e.event_id,
            e.event_name,
            e.country_name
        FROM sessions s
        JOIN events e
            ON s.event_id = e.event_id
        JOIN seasons se
            ON e.season_id = se.season_id
        WHERE s.session_type = 'Race'
        ORDER BY se.season_year, e.event_id
        """
    )

    # Validate all event names before resetting the existing index.
    for _, row in sessions.iterrows():
        season = int(row["season_year"])
        event_name = row["event_name"]

        if season != 2024:
            raise ValueError(
                f"No round-number mapping configured for season {season}."
            )

        if event_name not in ROUND_NUMBERS_2024:
            raise ValueError(
                f"No round number configured for event: {event_name}"
            )

    if len(sessions) != 24:
        raise ValueError(
            f"Expected 24 race sessions for 2024, found {len(sessions)}."
        )

    client = ChromaClient()

    # This clears the current ChromaDB collection.
    # Run this script only when you are ready to rebuild the index.
    client.reset_collection()

    for _, row in sessions.iterrows():
        season = int(row["season_year"])
        event_name = row["event_name"]
        round_number = ROUND_NUMBERS_2024[event_name]

        report = generate_race_report(int(row["session_id"]))

        race_doc = RaceDocumentGenerator.generate_race_report(
            season=season,
            round_number=round_number,
            grand_prix=event_name,
            winner=report["winner"],
            podium=report["podium"],
            classification=report["classification"],
            fastest_lap=report["fastest_lap"]["driver"],
            summary=report["summary"],
            country=row["country_name"],
        )

        documents = [race_doc]
        drivers = get_driver_standings(int(row["session_id"]))

        for _, driver in drivers.iterrows():
            driver_doc = RaceDocumentGenerator.generate_driver_summary(
                season=season,
                round_number=round_number,
                grand_prix=event_name,
                driver=driver["driver_full_name"],
                constructor=driver["constructor_name"],
                finish_position=int(driver["finish_position"]),
                points=float(driver["points_scored"]),
                country=row["country_name"],
            )

            documents.append(driver_doc)

        client.add_documents(documents)

        print(
            f"Indexed Round {round_number}: {event_name} "
            f"({len(documents)} documents)"
        )

    print(f"\nTotal indexed documents: {client.count()}")


if __name__ == "__main__":
    main()
