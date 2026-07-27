"""
RaceIntel Driver and Constructor Standings Analytics.

This module provides read-only analytical functions built on top of
the RaceIntel SQLite database.
"""

import pandas as pd
from sqlalchemy import text

from src.database.connection import SessionLocal


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

    query = text("""
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
    """)

    with SessionLocal() as session:
        result = session.execute(
            query,
            {"session_id": session_id}
        )

        dataframe = pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )

    return dataframe


def get_constructor_standings(session_id: int) -> pd.DataFrame:
    """
    Return constructor standings for a race session.
    """

    query = text("""
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
    """)

    with SessionLocal() as session:
        result = session.execute(
            query,
            {"session_id": session_id}
        )

        dataframe = pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )

    return dataframe