"""
RaceIntel Tyre Strategy Analysis.

Provides analytics related to:
- Tyre usage
- Tyre strategy
- Stint lengths
- Compound performance
"""

import pandas as pd

from src.database.connection import query_to_dataframe


def get_tyre_usage(session_id: int) -> pd.DataFrame:
    """
    Return the number of laps completed on each tyre compound
    by every driver.
    """

    query = """
        SELECT
            d.driver_code,
            d.driver_full_name,
            l.tyre_compound,
            COUNT(*) AS laps_completed
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.tyre_compound IS NOT NULL
        GROUP BY
            d.driver_code,
            d.driver_full_name,
            l.tyre_compound
        ORDER BY
            d.driver_code,
            laps_completed DESC;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_tyre_strategy(session_id: int) -> pd.DataFrame:
    """
    Return the tyre compounds used by each driver.
    """

    query = """
        SELECT
            d.driver_code,
            d.driver_full_name,
            l.lap_number,
            l.tyre_compound,
            l.tyre_age_laps
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.tyre_compound IS NOT NULL
        ORDER BY
            d.driver_code,
            l.lap_number;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_stint_summary(session_id: int) -> pd.DataFrame:
    """
    Return summary statistics for tyre usage.
    """

    query = """
        SELECT
            d.driver_code,
            d.driver_full_name,
            l.tyre_compound,
            COUNT(*) AS stint_length,
            ROUND(AVG(l.lap_time_seconds), 3) AS average_lap_time
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.tyre_compound IS NOT NULL
            AND l.lap_time_seconds IS NOT NULL
        GROUP BY
            d.driver_code,
            d.driver_full_name,
            l.tyre_compound
        ORDER BY
            d.driver_code,
            stint_length DESC;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_compound_performance(session_id: int) -> pd.DataFrame:
    """
    Return average lap time for each tyre compound.
    """

    query = """
        SELECT
            l.tyre_compound,
            COUNT(*) AS total_laps,
            ROUND(AVG(l.lap_time_seconds), 3) AS average_lap_time_seconds,
            MIN(l.lap_time_seconds) AS fastest_lap,
            MAX(l.lap_time_seconds) AS slowest_lap
        FROM laps l
        WHERE
            l.session_id = :session_id
            AND l.tyre_compound IS NOT NULL
            AND l.lap_time_seconds IS NOT NULL
        GROUP BY
            l.tyre_compound
        ORDER BY
            average_lap_time_seconds ASC;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )
def get_tyre_degradation(session_id: int) -> pd.DataFrame:
    """
    Return lap-time evolution with tyre age.
    """

    query = """
        SELECT
            d.driver_code,
            d.driver_full_name,
            l.tyre_compound,
            l.tyre_age_laps,
            l.lap_time_seconds
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
            AND l.tyre_compound IS NOT NULL
            AND l.tyre_age_laps IS NOT NULL
            AND l.lap_time_seconds IS NOT NULL
        ORDER BY
            d.driver_code,
            l.tyre_age_laps;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )