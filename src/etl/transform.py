from typing import Any


def transform_session_metadata(session) -> dict[str, Any]:
    """
    Transform season, event and session metadata into
    database-ready dictionaries.
    """

    event = session.event

    return {
        "season": {
            "season_year": int(event["EventDate"].year),
        },
        "event": {
            "event_name": event["EventName"],
            "country_name": event["Country"],
            "circuit_name": event["Location"],
        },
        "session": {
            "session_type": session.name,
            "session_name": session.name,
        },
    }


def transform_constructors(session) -> list[dict]:
    """
    Transform constructor data into database-ready dictionaries.
    """

    constructors = set()

    for _, row in session.results.iterrows():
        constructors.add(row["TeamName"])

    return [
        {
            "constructor_name": name,
        }
        for name in sorted(constructors)
    ]


def transform_drivers(session) -> list[dict]:
    """
    Transform driver data into database-ready dictionaries.
    """

    drivers = []

    for _, row in session.results.iterrows():
        drivers.append(
            {
                "driver_code": row["Abbreviation"],
                "driver_number": int(row["DriverNumber"]),
                "driver_full_name": row["FullName"],
                "constructor_name": row["TeamName"],
            }
        )

    return drivers


def transform_race_results(session) -> list[dict]:
    """
    Transform race results into database-ready dictionaries.
    """

    results = []

    for _, row in session.results.iterrows():
        results.append(
            {
                "driver_code": row["Abbreviation"],
                "constructor_name": row["TeamName"],
                "grid_position": int(row["GridPosition"]),
                "finish_position": int(row["Position"]),
                "points": float(row["Points"]),
                "status": row["Status"],
            }
        )

    return results


def transform_laps(session) -> list[dict]:
    """
    Transform lap data into database-ready dictionaries.
    """

    laps = []

    for _, lap in session.laps.iterrows():

        lap_time = None
        if lap["LapTime"] is not None:
            if hasattr(lap["LapTime"], "total_seconds"):
                lap_time = lap["LapTime"].total_seconds()

        laps.append(
            {
                "driver_code": lap["Driver"],
                "lap_number": int(lap["LapNumber"]),
                "lap_time_seconds": lap_time,
                "tyre_compound": lap["Compound"],
                "tyre_age_laps": lap["TyreLife"],
                "track_position": lap["Position"],
            }
        )

    return laps


def transform_weather(session) -> list[dict]:
    """
    Transform weather observations into database-ready dictionaries.
    """

    weather_records = []

    weather = session.weather_data

    for _, row in weather.iterrows():
        weather_records.append(
            {
                "timestamp": row["Time"].total_seconds(),
                "air_temperature_celsius": row["AirTemp"],
                "track_temperature_celsius": row["TrackTemp"],
                "humidity_percent": row["Humidity"],
                "pressure_mbar": row["Pressure"],
                "wind_speed_mps": row["WindSpeed"],
                "wind_direction_degrees": row["WindDirection"],
                "rainfall": row["Rainfall"],
            }
        )

    return weather_records
