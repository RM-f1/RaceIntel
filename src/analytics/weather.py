"""
RaceIntel Weather Analysis.

Provides analytics related to:
- Average weather conditions
- Rainfall periods
- Temperature trends
- Wind conditions
"""

import pandas as pd

from src.database.connection import query_to_dataframe


def get_weather_summary(session_id: int) -> pd.DataFrame:
    """
    Return average weather conditions during the race.
    """

    query = """
        SELECT
            ROUND(AVG(air_temperature_celsius), 2) AS average_air_temperature,
            ROUND(AVG(track_temperature_celsius), 2) AS average_track_temperature,
            ROUND(AVG(humidity_percent), 2) AS average_humidity,
            ROUND(AVG(wind_speed_mps), 2) AS average_wind_speed,
            ROUND(AVG(pressure_mbar), 2) AS average_pressure
        FROM weather_observations
        WHERE session_id = :session_id;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_rain_periods(session_id: int) -> pd.DataFrame:
    """
    Return all observations where rainfall was recorded.
    """

    query = """
        SELECT
            observation_time,
            air_temperature_celsius,
            track_temperature_celsius,
            humidity_percent,
            wind_speed_mps,
            rainfall
        FROM weather_observations
        WHERE
            session_id = :session_id
            AND rainfall = 1
        ORDER BY observation_time;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_temperature_trend(session_id: int) -> pd.DataFrame:
    """
    Return air and track temperature throughout the race.
    """

    query = """
        SELECT
            observation_time,
            air_temperature_celsius,
            track_temperature_celsius
        FROM weather_observations
        WHERE session_id = :session_id
        ORDER BY observation_time;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_wind_conditions(session_id: int) -> pd.DataFrame:
    """
    Return wind conditions throughout the race.
    """

    query = """
        SELECT
            observation_time,
            wind_speed_mps,
            wind_direction_degrees
        FROM weather_observations
        WHERE session_id = :session_id
        ORDER BY observation_time;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )
def get_weather_extremes(session_id: int) -> pd.DataFrame:
    """
    Return minimum/maximum weather values recorded.
    """

    query = """
        SELECT
            MIN(air_temperature_celsius) AS minimum_air_temperature,
            MAX(air_temperature_celsius) AS maximum_air_temperature,
            MIN(track_temperature_celsius) AS minimum_track_temperature,
            MAX(track_temperature_celsius) AS maximum_track_temperature,
            MAX(wind_speed_mps) AS maximum_wind_speed
        FROM weather_observations
        WHERE session_id = :session_id;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )