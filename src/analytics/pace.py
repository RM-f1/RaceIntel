"""
RaceIntel Pace Analysis.

Provides analytics related to:
- Fastest laps
- Average race pace
- Personal best laps
- Lap consistency
"""

import pandas as pd

from src.database.connection import query_to_dataframe


def get_fastest_laps(session_id: int) -> pd.DataFrame:
    """
    Return the fastest lap recorded by each driver.
    """

    query = """
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
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_average_pace(session_id: int) -> pd.DataFrame:
    """
    Return the average lap time for every driver.
    """

    query = """
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
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_personal_best_laps(session_id: int) -> pd.DataFrame:
    """
    Return every driver's personal best lap.
    """

    query = """
        SELECT
            d.driver_code,
            d.driver_full_name,
            l.lap_number,
            l.lap_time_seconds
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.lap_time_seconds = (
                SELECT MIN(l2.lap_time_seconds)
                FROM laps l2
                WHERE
                    l2.driver_id = l.driver_id
                    AND l2.session_id = l.session_id
                    AND l2.lap_time_seconds IS NOT NULL
            )
        ORDER BY
            l.lap_time_seconds ASC;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_lap_consistency(session_id: int) -> pd.DataFrame:
    """
    Return lap-time standard deviation for each driver.
    Lower values indicate more consistent pace.
    """

    query = """
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
    """

    laps = query_to_dataframe(
        query,
        {"session_id": session_id},
    )

    df = (
        laps.groupby(
            ["driver_code", "driver_full_name"],
            as_index=False,
        )["lap_time_seconds"]
        .std()
        .rename(
            columns={
                "lap_time_seconds": "lap_time_std_dev_seconds"
            }
        )
        .sort_values(
            by="lap_time_std_dev_seconds"
        )
        .reset_index(drop=True)
    )

    return df
def get_driver_best_laps(session_id: int) -> pd.DataFrame:
    """
    Return the best lap time for every driver.
    """

    query = """
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
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )