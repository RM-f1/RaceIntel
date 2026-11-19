"""
RaceIntel Tyre Strategy Analysis.

Provides analytics related to:
- Tyre usage
- Tyre strategy
- Stint lengths
- Compound performance
"""

import pandas as pd

from analytics.stints import VALID_COMPOUNDS, assign_stint_numbers
from database.connection import query_to_dataframe

# Whitelist of real compounds, used by every query. Filtering on IS NOT NULL
# alone let the literal string 'None' through as a fake compound.
_COMPOUND_FILTER = (
    "UPPER(l.tyre_compound) IN ("
    + ", ".join(f"'{c}'" for c in VALID_COMPOUNDS)
    + ")"
)


def get_tyre_usage(session_id: int) -> pd.DataFrame:
    """Laps completed on each tyre compound by every driver."""
    query = f"""
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
            AND {_COMPOUND_FILTER}
        GROUP BY
            d.driver_code,
            d.driver_full_name,
            l.tyre_compound
        ORDER BY
            d.driver_code,
            laps_completed DESC;
    """
    return query_to_dataframe(query, {"session_id": session_id})


def get_tyre_strategy(session_id: int) -> pd.DataFrame:
    """Tyre compounds used by each driver, lap by lap."""
    query = f"""
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
            AND {_COMPOUND_FILTER}
        ORDER BY
            d.driver_code,
            l.lap_number;
    """
    return query_to_dataframe(query, {"session_id": session_id})


def get_session_laps(session_id: int) -> pd.DataFrame:
    """Raw lap rows for one session. Cleaning happens in pandas."""
    query = """
        SELECT
            l.session_id,
            l.driver_id,
            d.driver_code,
            d.driver_full_name,
            l.lap_number,
            l.tyre_compound,
            l.tyre_age_laps,
            l.lap_time_seconds
        FROM laps l
        JOIN drivers d
            ON l.driver_id = d.driver_id
        WHERE
            l.session_id = :session_id
        ORDER BY
            l.driver_id,
            l.lap_number;
    """
    return query_to_dataframe(query, {"session_id": session_id})


def summarise_stints(laps: pd.DataFrame) -> pd.DataFrame:
    """One row per stint. Pure pandas, so it is testable without a database.

    stint_length = laps spanned (end - start + 1), used for the pit-window cap.
    timed_laps = laps with a lap time, which is what average_lap_time covers.
    """
    df = assign_stint_numbers(laps)
    keys = [k for k in ("session_id", "driver_id", "stint_number") if k in df.columns]
    aggs = {
        "tyre_compound": ("tyre_compound", "first"),
        "start_lap": ("lap_number", "min"),
        "end_lap": ("lap_number", "max"),
        "timed_laps": ("lap_time_seconds", "count"),
        "average_lap_time": ("lap_time_seconds", "mean"),
    }
    for col in ("driver_code", "driver_full_name"):
        if col in df.columns:
            aggs[col] = (col, "first")
    out = df.groupby(keys).agg(**aggs).reset_index()
    out["stint_length"] = out["end_lap"] - out["start_lap"] + 1
    out["average_lap_time"] = out["average_lap_time"].round(3)
    return out


def get_stint_summary(session_id: int) -> pd.DataFrame:
    """Stint-level summary for a session (one row per stint)."""
    return summarise_stints(get_session_laps(session_id))


def get_compound_performance(session_id: int) -> pd.DataFrame:
    """Average lap time for each tyre compound."""
    query = f"""
        SELECT
            l.tyre_compound,
            COUNT(*) AS total_laps,
            ROUND(AVG(l.lap_time_seconds), 3) AS average_lap_time_seconds,
            MIN(l.lap_time_seconds) AS fastest_lap,
            MAX(l.lap_time_seconds) AS slowest_lap
        FROM laps l
        WHERE
            l.session_id = :session_id
            AND {_COMPOUND_FILTER}
            AND l.lap_time_seconds IS NOT NULL
        GROUP BY
            l.tyre_compound
        ORDER BY
            average_lap_time_seconds ASC;
    """
    return query_to_dataframe(query, {"session_id": session_id})


def get_tyre_degradation(session_id: int) -> pd.DataFrame:
    """Lap-time evolution with tyre age."""
    query = f"""
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
            AND {_COMPOUND_FILTER}
            AND l.tyre_age_laps IS NOT NULL
            AND l.lap_time_seconds IS NOT NULL
        ORDER BY
            d.driver_code,
            l.tyre_age_laps;
    """
    return query_to_dataframe(query, {"session_id": session_id})