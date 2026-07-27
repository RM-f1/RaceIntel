"""
RaceIntel Pace Analytics.

Provides analytics related to:
- Fastest lap
- Average race pace
- Personal best laps
- Lap consistency
"""

import pandas as pd
from sqlalchemy import text

from src.database.connection import SessionLocal


def get_fastest_laps(session_id: int) -> pd.DataFrame:
    """
    Return the fastest lap recorded by each driver.
    """

    query = text("""
        SELECT
            d.driver_code,
            d.driver_full_name,
            MIN(l.lap_time_seconds) AS fastest_lap_seconds
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.lap_time_seconds IS NOT NULL
        GROUP BY
            d.driver_code,
            d.driver_full_name
        ORDER BY
            fastest_lap_seconds ASC;
    """)

    with SessionLocal() as session:
        result = session.execute(
            query,
            {"session_id": session_id}
        )

        df = pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )

    return df


def get_average_pace(session_id: int) -> pd.DataFrame:
    """
    Return the average lap time for every driver.
    """

    query = text("""
        SELECT
            d.driver_code,
            d.driver_full_name,
            ROUND(AVG(l.lap_time_seconds), 3) AS average_lap_time_seconds
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.lap_time_seconds IS NOT NULL
        GROUP BY
            d.driver_code,
            d.driver_full_name
        ORDER BY
            average_lap_time_seconds ASC;
    """)

    with SessionLocal() as session:
        result = session.execute(
            query,
            {"session_id": session_id}
        )

        df = pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )

    return df


def get_driver_best_laps(session_id: int) -> pd.DataFrame:
    """
    Return the best lap for every driver.

    This is derived from lap times instead of relying on the
    is_personal_best column.
    """

    query = text("""
        SELECT
            d.driver_code,
            d.driver_full_name,
            MIN(l.lap_time_seconds) AS best_lap_seconds
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.lap_time_seconds IS NOT NULL
        GROUP BY
            d.driver_code,
            d.driver_full_name
        ORDER BY
            best_lap_seconds ASC;
    """)

    with SessionLocal() as session:
        result = session.execute(
            query,
            {"session_id": session_id}
        )

        df = pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )

    return df

def get_lap_consistency(session_id: int) -> pd.DataFrame:
    """
    Return lap consistency for every driver.

    Lower standard deviation means more consistent pace.
    """

    query = text("""
        SELECT
            d.driver_code,
            d.driver_full_name,
            l.lap_time_seconds
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.lap_time_seconds IS NOT NULL;
    """)

    with SessionLocal() as session:
        result = session.execute(
            query,
            {"session_id": session_id}
        )

        df = pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )

    consistency = (
        df.groupby(
            ["driver_code", "driver_full_name"],
            as_index=False
        )["lap_time_seconds"]
        .std()
        .rename(
            columns={
                "lap_time_seconds": "lap_time_std_dev_seconds"
            }
        )
        .sort_values("lap_time_std_dev_seconds")
        .reset_index(drop=True)
    )

    return consistency

