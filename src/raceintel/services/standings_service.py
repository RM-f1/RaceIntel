"""
Standings service.
"""

from analytics.standings import get_driver_standings


def get_driver_championship(session_id: int) -> list[dict]:
  

    standings = get_driver_standings(session_id)

    if standings.empty:
        return []

    results = []

    for _, row in standings.iterrows():
        results.append(
            {
                "finish_position": int(row["finish_position"]),
                "driver_code": row["driver_code"],
                "driver_full_name": row["driver_full_name"],
                "constructor_name": row["constructor_name"],
                "points_scored": float(row["points_scored"]),
            }
        )

    return results

from analytics.standings import (
    get_driver_standings,
    get_constructor_standings,
)


def get_constructor_championship(session_id: int) -> list[dict]:
    """
    Return constructor standings for a race session.
    """

    constructors = get_constructor_standings(session_id)

    if constructors.empty:
        return []

    results = []

    for _, row in constructors.iterrows():
        results.append(
            {
                "constructor_name": row["constructor_name"],
                "total_points": float(row["total_points"]),
            }
        )

    return results