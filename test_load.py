from src.database.connection import SessionLocal
from src.database.schema import recreate_database
from src.etl.extract import extract_session
from src.etl.load import (load_constructors, load_drivers, load_event,
                          load_laps, load_race_results, load_season,
                          load_session, load_weather)
from src.etl.transform import (transform_constructors, transform_drivers,
                               transform_laps, transform_race_results,
                               transform_session_metadata, transform_weather)

recreate_database()

db = SessionLocal()

session = extract_session(
    2024,
    "British Grand Prix",
    "R",
)

metadata = transform_session_metadata(session)

season = load_season(
    db,
    metadata["season"],
)

event = load_event(
    db,
    season,
    metadata["event"],
)

race_session = load_session(
    db,
    event,
    metadata["session"],
)
constructors_data = transform_constructors(session)

constructors = load_constructors(
    db,
    constructors_data,
)

drivers_data = transform_drivers(session)

drivers = load_drivers(
    db,
    drivers_data,
)
results_data = transform_race_results(session)

race_results = load_race_results(
    db,
    race_session,
    results_data,
)
laps_data = transform_laps(session)

laps = load_laps(
    db,
    race_session,
    laps_data,
)
weather_data = transform_weather(session)

weather_records = load_weather(
    db,
    race_session,
    weather_data,
)

print(f"Season        : {season.season_year}")
print(f"Event         : {event.event_name}")
print(f"Session       : {race_session.session_type}")

print(f"Constructors  : {len(constructors)}")
print(f"Drivers       : {len(drivers)}")
print(f"Race Results  : {len(race_results)}")
print(f"Laps          : {len(laps)}")
print(f"Weather       : {len(weather_records)}")

print("\nFirst Weather Record:")
print(f"Time      : {weather_records[0].observation_time}")
print(f"Air Temp  : {weather_records[0].air_temperature_celsius}")
print(f"Track Temp: {weather_records[0].track_temperature_celsius}")
db.close()
