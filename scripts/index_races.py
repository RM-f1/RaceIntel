from analytics.race_report import generate_race_report
from analytics.standings import get_driver_standings
from database.connection import query_to_dataframe

from raceintel.retrieval.chroma_client import ChromaClient
from raceintel.retrieval.generator import RaceDocumentGenerator


def main():

    sessions = query_to_dataframe(
        """
        SELECT
            s.session_id,
            se.season_year,
            e.event_id,
            e.event_name
        FROM sessions s
        JOIN events e
            ON s.event_id = e.event_id
        JOIN seasons se
            ON e.season_id = se.season_id
        WHERE s.session_type='Race'
        ORDER BY se.season_year, e.event_id
        """
    )

    client = ChromaClient()

    client.reset_collection()

    for _, row in sessions.iterrows():

        report = generate_race_report(row["session_id"])

        race_doc = RaceDocumentGenerator.generate_race_report(
            season=row["season_year"],
            round_number=row["event_id"],
            grand_prix=row["event_name"],
            winner=report["winner"],
            podium=report["podium"],
            classification=report["classification"],
            fastest_lap=report["fastest_lap"]["driver"],
            summary=report["summary"],
        )

        client.add_document(race_doc)

        drivers = get_driver_standings(row["session_id"])

        for _, driver in drivers.iterrows():

            driver_doc = RaceDocumentGenerator.generate_driver_summary(
                season=row["season_year"],
                round_number=row["event_id"],
                grand_prix=row["event_name"],
                driver=driver["driver_full_name"],
                constructor=driver["constructor_name"],
                finish_position=int(driver["finish_position"]),
                points=float(driver["points_scored"]),
            )

            client.add_document(driver_doc)

        print(f"Indexed {row['event_name']}")

    print(f"\nTotal indexed documents: {client.count()}")


if __name__ == "__main__":
    main()