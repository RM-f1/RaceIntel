"""
RaceIntel Tyre Strategy Analytics.

Provides analytics related to:
- Tyre usage
- Compound performance
- Tyre degradation
"""

import pandas as pd
from sqlalchemy import text

from src.database.connection import SessionLocal


def get_tyre_usage(session_id: int) -> pd.DataFrame:
    """
    Return the number of laps completed on each tyre compound
    by every driver.
    """

    query = text("""
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
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"session_id": session_id})

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )


def get_compound_performance(session_id: int) -> pd.DataFrame:
    """
    Average lap time for each tyre compound.
    """

    query = text("""
        SELECT
            tyre_compound,
            ROUND(AVG(lap_time_seconds),3) AS average_lap_time_seconds,
            COUNT(*) AS lap_count
        FROM laps
        WHERE
            session_id=:session_id
            AND lap_time_seconds IS NOT NULL
            AND tyre_compound IS NOT NULL
        GROUP BY tyre_compound
        ORDER BY average_lap_time_seconds;
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"session_id": session_id})

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )


def get_tyre_degradation(session_id: int) -> pd.DataFrame:
    """
    Average lap time by tyre age.
    """

    query = text("""
        SELECT
            d.driver_code,
            d.driver_full_name,
            l.tyre_compound,
            l.tyre_age_laps,
            ROUND(AVG(l.lap_time_seconds),3) AS average_lap_time_seconds
        FROM laps l
        JOIN drivers d
            ON l.driver_id=d.driver_id
        WHERE
            l.session_id=:session_id
            AND l.lap_time_seconds IS NOT NULL
            AND l.tyre_compound IS NOT NULL
            AND l.tyre_age_laps IS NOT NULL
        GROUP BY
            d.driver_code,
            d.driver_full_name,
            l.tyre_compound,
            l.tyre_age_laps
        ORDER BY
            d.driver_code,
            l.tyre_age_laps;
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"session_id": session_id})

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )


def get_stint_summary(session_id: int) -> pd.DataFrame:
    """
    Build stint summaries from consecutive laps on the same compound.
    """

    query = text("""
        SELECT
            d.driver_code,
            d.driver_full_name,
            l.lap_number,
            l.tyre_compound
        FROM laps l
        JOIN drivers d
            ON l.driver_id=d.driver_id
        WHERE
            l.session_id=:session_id
            AND l.tyre_compound IS NOT NULL
        ORDER BY
            d.driver_code,
            l.lap_number;
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"session_id": session_id})

        df = pd.DataFrame(
            result.fetchall(),
            columns=result.keys()
        )

    stints = []

    for driver, group in df.groupby("driver_code"):

        group = group.sort_values("lap_number")

        start = None
        current_compound = None

        for _, row in group.iterrows():

            if current_compound != row["tyre_compound"]:

                if current_compound is not None:
                    stints.append({
                        "driver_code": driver,
                        "tyre_compound": current_compound,
                        "first_lap": start,
                        "last_lap": previous_lap,
                        "stint_length": previous_lap - start + 1
                    })

                current_compound = row["tyre_compound"]
                start = row["lap_number"]

            previous_lap = row["lap_number"]

        stints.append({
            "driver_code": driver,
            "tyre_compound": current_compound,
            "first_lap": start,
            "last_lap": previous_lap,
            "stint_length": previous_lap - start + 1
        })

    return pd.DataFrame(stints)