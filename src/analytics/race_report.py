"""
Race report analytics.
"""

from analytics.standings import (
    get_driver_standings,
    get_constructor_standings,
)
from analytics.position import get_biggest_movers
from analytics.pace import get_fastest_laps
from analytics.tyre import get_tyre_usage
from analytics.weather import get_weather_summary


def generate_race_report(session_id: int) -> dict:
    """
    Generate a structured race report.
    """

    drivers = get_driver_standings(session_id)
    constructors = get_constructor_standings(session_id)
    movers = get_biggest_movers(session_id)
    fastest = get_fastest_laps(session_id)
    tyres = get_tyre_usage(session_id)
    weather = get_weather_summary(session_id)

    classification = "\n".join(
        f"P{int(row['finish_position'])} {row['driver_full_name']}"
        for _, row in drivers.iterrows()
    )

    summary = (
        f"{drivers.iloc[0]['driver_full_name']} won the race. "
        f"The podium consisted of "
        f"{', '.join(drivers.iloc[:3]['driver_full_name'])}. "
        f"{movers.iloc[0]['driver_full_name']} gained "
        f"{int(movers.iloc[0]['positions_gained'])} positions. "
        f"The fastest lap was set by "
        f"{fastest.iloc[0]['driver_full_name']}."
    )

    return {
        "session_id": session_id,

        "winner": drivers.iloc[0]["driver_full_name"],
        "podium": drivers.iloc[:3]["driver_full_name"].tolist(),

        "classification": classification,

        "top_constructor": constructors.iloc[0]["constructor_name"],

        "biggest_mover": {
            "driver": movers.iloc[0]["driver_full_name"],
            "positions": int(movers.iloc[0]["positions_gained"]),
        },

        "fastest_lap": {
            "driver": fastest.iloc[0]["driver_full_name"],
            "seconds": float(fastest.iloc[0]["fastest_lap_seconds"]),
        },

        "summary": summary,

        "statistics": {
            "drivers": len(drivers),
            "constructors": len(constructors),
            "weather_samples": len(weather),
            "tyre_compounds": (
                sorted(tyres["tyre_compound"].unique().tolist())
                if not tyres.empty
                else []
            ),
        },
    }