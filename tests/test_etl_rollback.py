
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.connection import Base
from database.models import (
    Constructor,
    Driver,
    Event,
    Lap,
    RaceResult,
    Season,
    Session,
    WeatherObservation,
)
from etl import pipeline


def test_pipeline_failure_rolls_back_existing_session(monkeypatch):
    # Create an isolated in-memory database.
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)

    TestSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    try:
        # Seed previously committed race data.
        with TestSessionLocal() as db:
            season = Season(season_year=2024)
            constructor = Constructor(constructor_name="Old Team")
            db.add_all([season, constructor])
            db.flush()

            event = Event(
                season_id=season.season_id,
                event_name="Rollback Test GP",
                country_name="Test Country",
                circuit_name="Test Circuit",
            )
            db.add(event)
            db.flush()

            driver = Driver(
                driver_code="OLD",
                driver_number=99,
                driver_full_name="Old Driver",
                constructor_id=constructor.constructor_id,
            )
            db.add(driver)
            db.flush()

            old_session = Session(
                event_id=event.event_id,
                session_type="R",
                session_name="Old Race Session",
            )
            db.add(old_session)
            db.flush()

            old_session_id = old_session.session_id

            db.add(
                RaceResult(
                    session_id=old_session_id,
                    driver_id=driver.driver_id,
                    constructor_id=constructor.constructor_id,
                    grid_position=1,
                    finish_position=1,
                    points_scored=25.0,
                    classified_status="Finished",
                )
            )
            db.add(
                Lap(
                    session_id=old_session_id,
                    driver_id=driver.driver_id,
                    lap_number=1,
                    lap_time_seconds=90.0,
                    tyre_compound="SOFT",
                    tyre_age_laps=1,
                    track_position=1,
                )
            )
            db.add(
                WeatherObservation(
                    session_id=old_session_id,
                    observation_time=1000.0,
                    air_temperature_celsius=25.0,
                    track_temperature_celsius=35.0,
                    humidity_percent=50.0,
                    pressure_mbar=1013.0,
                    wind_speed_mps=2.0,
                    wind_direction_degrees=180,
                    rainfall=False,
                )
            )
            db.commit()

        # Redirect the pipeline to the isolated database.
        monkeypatch.setattr(pipeline, "SessionLocal", TestSessionLocal)

        # Mock extraction and transformations so no real F1 data is fetched.
        monkeypatch.setattr(
            pipeline,
            "extract_session",
            lambda *args: object(),
        )
        monkeypatch.setattr(
            pipeline,
            "transform_session_metadata",
            lambda session: {
                "season": {"season_year": 2024},
                "event": {
                    "event_name": "Rollback Test GP",
                    "country_name": "Test Country",
                    "circuit_name": "Test Circuit",
                },
                "session": {
                    "session_type": "R",
                    "session_name": "Replacement Race Session",
                },
            },
        )
        monkeypatch.setattr(pipeline, "transform_constructors", lambda s: [])
        monkeypatch.setattr(pipeline, "transform_drivers", lambda s: [])
        monkeypatch.setattr(pipeline, "transform_race_results", lambda s: [])
        monkeypatch.setattr(pipeline, "transform_laps", lambda s: [])
        monkeypatch.setattr(pipeline, "transform_weather", lambda s: [])

        # Force a failure after the old session has been deleted in the
        # uncommitted transaction and the replacement session has been added.
        def fail_weather(*args, **kwargs):
            raise RuntimeError("Simulated weather-loading failure")

        monkeypatch.setattr(pipeline, "load_weather", fail_weather)

        with pytest.raises(
            RuntimeError,
            match="Simulated weather-loading failure",
        ):
            pipeline.run_pipeline(2024, "Rollback Test GP", "R")

        # Verify the previous committed session and its data were restored.
        with TestSessionLocal() as db:
            restored_session = db.get(Session, old_session_id)

            assert restored_session is not None
            assert restored_session.session_name == "Old Race Session"

            assert (
                db.query(RaceResult)
                .filter(RaceResult.session_id == old_session_id)
                .count()
                == 1
            )
            assert (
                db.query(Lap)
                .filter(Lap.session_id == old_session_id)
                .count()
                == 1
            )
            assert (
                db.query(WeatherObservation)
                .filter(
                    WeatherObservation.session_id == old_session_id
                )
                .count()
                == 1
            )

            # The failed replacement must not have been committed.
            assert (
                db.query(Session)
                .filter(
                    Session.event_id == restored_session.event_id,
                    Session.session_type == "R",
                )
                .count()
                == 1
            )
    finally:
        test_engine.dispose()
