"""
Pace service.
"""

from analytics.pace import get_fastest_laps


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
                "fastest_lap_seconds": float(
                    row["fastest_lap_seconds"]
                ),
            }
        )

    return results