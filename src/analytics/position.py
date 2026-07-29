"""
RaceIntel Position Analysis.

Provides analytics related to:
- Grid vs Finish position
- Position changes
- Biggest movers
- Race classification summary
"""

import pandas as pd

from database.connection import query_to_dataframe


def get_position_changes(session_id: int) -> pd.DataFrame:
    """
    Return grid-to-finish position changes for each driver.
    """

    query = """
        SELECT
            d.driver_code,
            d.driver_full_name,
            rr.grid_position,
            rr.finish_position,
            (rr.grid_position - rr.finish_position) AS positions_gained
        FROM race_results rr
        JOIN drivers d
            ON rr.driver_id = d.driver_id
        WHERE rr.session_id = :session_id
        ORDER BY positions_gained DESC;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )


def get_biggest_movers(session_id: int) -> pd.DataFrame:
    """
    Return drivers sorted by positions gained.
    """

    df = get_position_changes(session_id)

    return df.sort_values(
        by="positions_gained",
        ascending=False,
    ).reset_index(drop=True)


def get_classification_summary(session_id: int) -> pd.DataFrame:
    """
    Return race classification for all drivers.
    """

    query = """
        SELECT
            d.driver_code,
            d.driver_full_name,
            rr.classified_status
        FROM race_results rr
        JOIN drivers d
            ON rr.driver_id = d.driver_id
        WHERE rr.session_id = :session_id
        ORDER BY rr.finish_position;
    """

    return query_to_dataframe(
        query,
        {"session_id": session_id},
    )