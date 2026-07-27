"""
RaceIntel Weather Analytics.

Provides analytics related to:
- Weather summary
- Rain periods
- Temperature trends
- Weather extremes
"""

import pandas as pd
from sqlalchemy import text

from src.database.connection import SessionLocal


def get_weather_summary(session_id: int) -> pd.DataFrame:
    """
    Return average weather conditions during the race.
    """

    query = text("""
        SELECT
            ROUND(AVG(air_temperature_celsius),2) AS average_air_temperature,
            ROUND(AVG(track_temperature_celsius),2) AS average_track_temperature,
            ROUND(AVG(humidity_percent),2) AS average_humidity,
            ROUND(AVG(wind_speed_mps),2) AS average_wind_speed
        FROM weather_observations
        WHERE session_id = :session_id;
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"session_id": session_id})

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )


def get_rain_periods(session_id: int) -> pd.DataFrame:
    """
    Return all weather observations where rainfall occurred.
    """

    query = text("""
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
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"session_id": session_id})

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )


def get_temperature_trend(session_id: int) -> pd.DataFrame:
    """
    Return the temperature trend throughout the race.
    """

    query = text("""
        SELECT
            observation_time,
            air_temperature_celsius,
            track_temperature_celsius
        FROM weather_observations
        WHERE session_id = :session_id
        ORDER BY observation_time;
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"session_id": session_id})

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )


def get_weather_extremes(session_id: int) -> pd.DataFrame:
    """
    Return weather extremes observed during the race.
    """

    query = text("""
        SELECT
            MIN(air_temperature_celsius) AS minimum_air_temperature,
            MAX(air_temperature_celsius) AS maximum_air_temperature,
            MIN(track_temperature_celsius) AS minimum_track_temperature,
            MAX(track_temperature_celsius) AS maximum_track_temperature,
            MAX(wind_speed_mps) AS maximum_wind_speed
        FROM weather_observations
        WHERE session_id = :session_id;
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"session_id": session_id})

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )