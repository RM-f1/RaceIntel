"""
Race report analytics.

This module combines analytics from multiple modules and returns
a structured race report dictionary that can be reused by the CLI,
FastAPI, and Streamlit.
"""

from src.analytics.standings import (
    get_driver_standings,
    get_constructor_standings,
)
from src.analytics.position import get_biggest_movers
from src.analytics.pace import get_fastest_laps
from src.analytics.tyre import get_tyre_usage
from src.analytics.weather import get_weather_summary


def generate_race_report(session_id: int) -> dict:

    drivers = get_driver_standings(session_id)
    constructors = get_constructor_standings(session_id)
    movers = get_biggest_movers(session_id)
    fastest = get_fastest_laps(session_id)
    tyres = get_tyre_usage(session_id)
    weather = get_weather_summary(session_id)

    return {
        "session_id": session_id,
        "winner": drivers.iloc[0]["driver_full_name"],
        "podium": drivers.iloc[:3]["driver_full_name"].tolist(),
        "top_constructor": constructors.iloc[0]["constructor_name"],
        "biggest_mover": {
            "driver": movers.iloc[0]["driver_full_name"],
            "positions": int(movers.iloc[0]["positions_gained"]),
        },
        "fastest_lap": {
            "driver": fastest.iloc[0]["driver_full_name"],
            "seconds": float(fastest.iloc[0]["fastest_lap_seconds"]),
        },
        "statistics": {     
             "drivers": len(drivers),
             "constructors": len(constructors),
             "weather_samples": len(weather),
             "tyre_compounds": sorted(
                 tyres["tyre_compound"].unique().tolist()
             ) if not tyres.empty else [],
        },
    }