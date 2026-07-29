"""
RaceIntel Driver and Constructor Standings Analytics.

This module provides read-only analytical functions built on top of
the RaceIntel SQLite database.
"""

import pandas as pd

from database.connection import query_to_dataframe


def get_driver_standings(session_id: int) -> pd.DataFrame:
    """
    Return the driver standings for a race session.

    Parameters
    ----------
    session_id : int
        Session identifier.

    Returns
    -------
    pandas.DataFrame
        Driver standings sorted by points.
    """

    query = """
        SELECT
            d.driver_code,
            d.driver_full_name,
            c.constructor_name,
            rr.finish_position,
            rr.points_scored
        FROM race_results rr
        JOIN drivers d
            ON rr.driver_id = d.driver_id
        JOIN constructors c
            ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
        ORDER BY
            rr.points_scored DESC,
            rr.finish_position ASC;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_constructor_standings(session_id: int) -> pd.DataFrame:
    """
    Return constructor standings for a race session.
    """

    query = """
        SELECT
            c.constructor_name,
            SUM(rr.points_scored) AS total_points
        FROM race_results rr
        JOIN constructors c
            ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
        GROUP BY
            c.constructor_name
        ORDER BY
            total_points DESC;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )