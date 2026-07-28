"""
Weather service.
"""

from analytics.weather import get_weather_summary


def get_weather(session_id: int) -> dict:


    weather = get_weather_summary(session_id)

    if weather.empty:
        return {}

    row = weather.iloc[0]

    return {
        "average_air_temperature": float(row["average_air_temperature"]),
        "average_track_temperature": float(row["average_track_temperature"]),
        "average_humidity": float(row["average_humidity"]),
        "average_wind_speed": float(row["average_wind_speed"]),
        "average_pressure": float(row["average_pressure"]),
    }