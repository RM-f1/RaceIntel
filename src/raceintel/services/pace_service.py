"""
Pace service.
"""

from raceintel.analytics.pace import get_fastest_laps


def get_pace(session_id: int) -> list[dict]:
    pace = get_fastest_laps(session_id)

    if pace.empty:
        return []

    results = []

    for _, row in pace.iterrows():
        results.append(
            {
                "driver_code": row["driver_code"],
                "driver_full_name": row["driver_full_name"],
                "fastest_lap_seconds": float(row["fastest_lap_seconds"]),
            }
        )

    return results


from database.connection import query_to_dataframe


def format_lap_time(seconds: float | None) -> str:
    """Format lap time in seconds into standard M:SS.mmm format."""
    if seconds is None:
        return "N/A"
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}:{secs:06.3f}" if mins > 0 else f"{secs:.3f}s"


def get_fastest_lap_for_session(session_id: int) -> dict | None:
    """
    Return the fastest lap recorded across all drivers in a race session.

    Handles missing or invalid lap times gracefully.
    """
    query = """
        SELECT 
            d.driver_full_name,
            d.driver_code,
            c.constructor_name,
            l.lap_number,
            l.lap_time_seconds
        FROM laps l
        JOIN drivers d ON l.driver_id = d.driver_id
        LEFT JOIN constructors c ON d.constructor_id = c.constructor_id
        WHERE l.session_id = :session_id
          AND l.lap_time_seconds IS NOT NULL
        ORDER BY l.lap_time_seconds ASC
        LIMIT 1;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty:
        return None

    row = df.iloc[0]
    lap_sec = float(row["lap_time_seconds"])

    return {
        "driver_full_name": str(row["driver_full_name"]),
        "driver_code": str(row["driver_code"]),
        "constructor_name": str(row["constructor_name"]) if row["constructor_name"] else None,
        "lap_number": int(row["lap_number"]),
        "lap_time_seconds": lap_sec,
        "formatted_lap_time": format_lap_time(lap_sec),
    }


def format_fastest_lap_answer(
    fastest_lap: dict | None,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format a deterministic answer for fastest-lap queries."""
    if not fastest_lap:
        return f"Fastest lap data is not available for the {season} {event_name}."

    return (
        f"{fastest_lap['driver_full_name']} set the fastest lap in the "
        f"{season} {event_name} with a time of {fastest_lap['formatted_lap_time']} "
        f"on lap {fastest_lap['lap_number']}."
    )