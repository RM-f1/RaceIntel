from sqlalchemy import delete
from sqlalchemy.orm import Session as DBSession

from src.database.models import (Constructor, Driver, Event, Lap, RaceResult,
                                 Season, Session, WeatherObservation)


def delete_session_data(
    db: DBSession,
    session_id: int,
) -> None:

    db.execute(delete(Lap).where(Lap.session_id == session_id))

    db.execute(
        delete(WeatherObservation).where(WeatherObservation.session_id == session_id)
    )

    db.execute(delete(RaceResult).where(RaceResult.session_id == session_id))

    db.execute(delete(Session).where(Session.session_id == session_id))

    db.commit()


def get_existing_session(
    db: DBSession,
    event_id: int,
    session_type: str,
):

    print("\nSearching for:")
    print("event_id     =", event_id)
    print("session_type =", repr(session_type))

    sessions = db.query(Session).all()

    print("\nSessions in database:")
    for s in sessions:
        print(
            s.session_id,
            s.event_id,
            repr(s.session_type),
        )

    return (
        db.query(Session)
        .filter(
            Session.event_id == event_id,
            Session.session_type == session_type,
        )
        .first()
    )


def load_season(
    db: DBSession,
    season_data: dict,
) -> Season:

    season = (
        db.query(Season)
        .filter(
            Season.season_year == season_data["season_year"],
        )
        .first()
    )

    if season is not None:
        return season

    season = Season(**season_data)

    db.add(season)
    db.commit()
    db.refresh(season)

    return season


def load_event(
    db: DBSession,
    season: Season,
    event_data: dict,
) -> Event:

    event = (
        db.query(Event)
        .filter(
            Event.season_id == season.season_id,
            Event.event_name == event_data["event_name"],
        )
        .first()
    )

    if event is not None:
        return event

    event = Event(
        season_id=season.season_id,
        **event_data,
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return event


def load_session(
    db: DBSession,
    event: Event,
    session_data: dict,
) -> Session:

    session = (
        db.query(Session)
        .filter(
            Session.event_id == event.event_id,
            Session.session_type == session_data["session_type"],
        )
        .first()
    )

    if session is not None:
        return session

    session = Session(
        event_id=event.event_id,
        **session_data,
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    return session


def load_constructors(
    db: DBSession,
    constructors_data: list[dict],
) -> list[Constructor]:

    constructors = []

    for data in constructors_data:

        constructor = (
            db.query(Constructor)
            .filter(
                Constructor.constructor_name == data["constructor_name"],
            )
            .first()
        )

        if constructor is None:
            constructor = Constructor(**data)
            db.add(constructor)
            db.commit()
            db.refresh(constructor)

        constructors.append(constructor)

    return constructors


def load_drivers(
    db: DBSession,
    drivers_data: list[dict],
) -> list[Driver]:

    constructors = {
        c.constructor_name: c.constructor_id for c in db.query(Constructor).all()
    }

    drivers = []

    for data in drivers_data:

        driver = (
            db.query(Driver)
            .filter(
                Driver.driver_code == data["driver_code"],
            )
            .first()
        )

        if driver is None:

            driver = Driver(
                driver_code=data["driver_code"],
                driver_number=data["driver_number"],
                driver_full_name=data["driver_full_name"],
                constructor_id=constructors[data["constructor_name"]],
            )

            db.add(driver)
            db.commit()
            db.refresh(driver)

        drivers.append(driver)

    return drivers


def load_race_results(
    db: DBSession,
    race_session: Session,
    results_data: list[dict],
) -> list[RaceResult]:
    drivers = {d.driver_code: d.driver_id for d in db.query(Driver).all()}

    constructors = {
        c.constructor_name: c.constructor_id for c in db.query(Constructor).all()
    }

    race_results = []

    for data in results_data:

        result = RaceResult(
            session_id=race_session.session_id,
            driver_id=drivers[data["driver_code"]],
            constructor_id=constructors[data["constructor_name"]],
            grid_position=data["grid_position"],
            finish_position=data["finish_position"],
            points_scored=data["points"],
            classified_status=data["status"],
        )

        db.add(result)
        race_results.append(result)

    db.commit()

    for result in race_results:
        db.refresh(result)

    return race_results


def load_laps(
    db: DBSession,
    race_session: Session,
    laps_data: list[dict],
) -> list[Lap]:
    drivers = {d.driver_code: d.driver_id for d in db.query(Driver).all()}

    laps = []

    for data in laps_data:

        lap = Lap(
            session_id=race_session.session_id,
            driver_id=drivers[data["driver_code"]],
            lap_number=data["lap_number"],
            lap_time_seconds=data["lap_time_seconds"],
            tyre_compound=data["tyre_compound"],
            tyre_age_laps=data["tyre_age_laps"],
            track_position=data["track_position"],
        )

        db.add(lap)
        laps.append(lap)

    db.commit()

    return laps


def load_weather(
    db: DBSession,
    race_session: Session,
    weather_data: list[dict],
) -> list[WeatherObservation]:
    """
    Insert weather observations into the database.
    """

    weather_records = []

    for data in weather_data:

        weather = WeatherObservation(
            session_id=race_session.session_id,
            observation_time=data["timestamp"],
            air_temperature_celsius=data["air_temperature_celsius"],
            track_temperature_celsius=data["track_temperature_celsius"],
            humidity_percent=data["humidity_percent"],
            pressure_mbar=data["pressure_mbar"],
            wind_speed_mps=data["wind_speed_mps"],
            wind_direction_degrees=data["wind_direction_degrees"],
            rainfall=data["rainfall"],
        )

        db.add(weather)
        weather_records.append(weather)

    db.commit()

    return weather_records
