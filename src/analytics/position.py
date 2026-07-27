"""
RaceIntel Position Analysis.

Provides analytics related to:
- Grid vs Finish position
- Position changes
- Biggest movers
- Race classification summary
"""

import pandas as pd
from sqlalchemy import text

from src.database.connection import SessionLocal


def get_position_changes(session_id: int) -> pd.DataFrame:
    

    query = text("""
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


def get_biggest_movers(session_id: int) -> pd.DataFrame:
   

    df = get_position_changes(session_id)

    return df.sort_values(
        by="positions_gained",
        ascending=False
    ).reset_index(drop=True)


def get_classification_summary(session_id: int) -> pd.DataFrame:
   

    query = text("""
        SELECT
            d.driver_code,
            d.driver_full_name,
            rr.classified_status
        FROM race_results rr
        JOIN drivers d
            ON rr.driver_id = d.driver_id
        WHERE rr.session_id = :session_id
        ORDER BY rr.finish_position;
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