from sqlalchemy.exc import SQLAlchemyError

from src.database.connection import SessionLocal
from src.etl.extract import extract_session
from src.etl.load import (delete_session_data, get_existing_session,
                          load_constructors, load_drivers, load_event,
                          load_laps, load_race_results, load_season,
                          load_session, load_weather)
from src.etl.transform import (transform_constructors, transform_drivers,
                               transform_laps, transform_race_results,
                               transform_session_metadata, transform_weather)


def run_pipeline(
    year: int,
    grand_prix: str,
    session_type: str,
) -> None:

    db = SessionLocal()

    try:
        # -------------------------
        # Extract
        # -------------------------
        session = extract_session(
            year,
            grand_prix,
            session_type,
        )

        # -------------------------
        # Transform
        # -------------------------
        metadata = transform_session_metadata(session)
        constructors_data = transform_constructors(session)
        drivers_data = transform_drivers(session)
        race_results_data = transform_race_results(session)
        laps_data = transform_laps(session)
        weather_data = transform_weather(session)

        # -------------------------
        # Load
        # -------------------------
        season = load_season(
            db,
            metadata["season"],
        )

        event = load_event(
            db,
            season,
            metadata["event"],
        )
        existing_session = get_existing_session(
            db,
            event.event_id,
            metadata["session"]["session_type"],
        )

        if existing_session is not None:
            print("Existing session found. Deleting old data...")

            delete_session_data(
                db,
                existing_session.session_id,
            )
        print("Session type:", metadata["session"]["session_type"])
        print("Existing session:", existing_session)
        print("Event ID:", event.event_id)

        race_session = load_session(
            db,
            event,
            metadata["session"],
        )

        constructors = load_constructors(
            db,
            constructors_data,
        )

        drivers = load_drivers(
            db,
            drivers_data,
        )

        load_race_results(
            db,
            race_session,
            race_results_data,
        )

        load_laps(
            db,
            race_session,
            laps_data,
        )

        load_weather(
            db,
            race_session,
            weather_data,
        )

        print("ETL pipeline completed successfully!")

    except SQLAlchemyError:
        db.rollback()
        raise

    finally:
        db.close()
