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


from database.connection import query_to_dataframe


def get_weather_details(session_id: int) -> dict:
    """
    Return comprehensive, verified weather metrics for a session.

    Deterministic Condition Rule:
        A race is classified as 'Wet' if any weather observation recorded
        rainfall (rainfall == 1); otherwise it is classified as 'Dry'.
    """
    query = """
        SELECT
            COUNT(weather_observation_id) AS total_observations,
            SUM(CASE WHEN rainfall = 1 THEN 1 ELSE 0 END) AS rain_observations,
            ROUND(MIN(air_temperature_celsius), 1) AS min_air_temperature,
            ROUND(MAX(air_temperature_celsius), 1) AS max_air_temperature,
            ROUND(AVG(air_temperature_celsius), 1) AS average_air_temperature,
            ROUND(MAX(track_temperature_celsius), 1) AS peak_track_temperature,
            ROUND(AVG(track_temperature_celsius), 1) AS average_track_temperature,
            ROUND(AVG(humidity_percent), 1) AS average_humidity,
            ROUND(AVG(wind_speed_mps), 1) AS average_wind_speed,
            ROUND(AVG(pressure_mbar), 1) AS average_pressure
        FROM weather_observations
        WHERE session_id = :session_id;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty or int(df.iloc[0]["total_observations"] or 0) == 0:
        return {
            "available": False,
            "session_id": session_id,
            "total_observations": 0,
        }

    row = df.iloc[0]
    total_obs = int(row["total_observations"])
    rain_obs = int(row["rain_observations"] or 0)
    has_rain = rain_obs > 0
    condition = "Wet" if has_rain else "Dry"

    min_air = float(row["min_air_temperature"]) if row["min_air_temperature"] is not None else None
    max_air = float(row["max_air_temperature"]) if row["max_air_temperature"] is not None else None
    avg_air = float(row["average_air_temperature"]) if row["average_air_temperature"] is not None else None
    peak_track = float(row["peak_track_temperature"]) if row["peak_track_temperature"] is not None else None
    avg_track = float(row["average_track_temperature"]) if row["average_track_temperature"] is not None else None

    return {
        "available": True,
        "session_id": session_id,
        "total_observations": total_obs,
        "rain_observations": rain_obs,
        "has_rainfall": has_rain,
        "condition": condition,
        "min_air_temperature": min_air,
        "max_air_temperature": max_air,
        "average_air_temperature": avg_air,
        "air_temperature_range": (min_air, max_air) if (min_air is not None and max_air is not None) else None,
        "peak_track_temperature": peak_track,
        "average_track_temperature": avg_track,
        "average_humidity": float(row["average_humidity"]) if row["average_humidity"] is not None else None,
        "average_wind_speed": float(row["average_wind_speed"]) if row["average_wind_speed"] is not None else None,
        "average_pressure": float(row["average_pressure"]) if row["average_pressure"] is not None else None,
    }


def format_weather_answer(
    weather: dict,
    question: str,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format a deterministic answer for weather-related queries."""
    if not weather.get("available"):
        return f"Weather observations are not available for the {event_name} in season {season}."

    q = question.lower()

    import re

    # 1. Rainfall / Wet track questions (use word boundary so 'Bahrain' is not matched as 'rain')
    has_rain_keyword = bool(
        re.search(r"\b(rain|rainfall|rained|raining|rainy|wet)\b", q)
        or "track wet" in q
        or "wet track" in q
    ) and "wet or dry" not in q and "dry or wet" not in q
    if has_rain_keyword:
        if weather["has_rainfall"]:
            return (
                f"Yes, rainfall was recorded during the {season} {event_name} "
                f"({weather['rain_observations']} rain observations recorded)."
            )
        return (
            f"No, there was no rainfall recorded during the {season} {event_name}. "
            f"The track conditions were dry."
        )

    # 2. Condition questions (wet or dry / what was the weather)
    if (
        "weather like" in q
        or "what was the weather" in q
        or "wet or dry" in q
        or "dry or wet" in q
        or "conditions" in q
        or ("weather" in q and not any(k in q for k in ["temperature", "temp", "humidity", "wind", "pressure", "surface", "asphalt", "ambient"]))
    ):
        return (
            f"The weather was {weather['condition']} during the {season} {event_name}. "
            f"The average air temperature was {weather['average_air_temperature']}°C "
            f"and average track temperature was {weather['average_track_temperature']}°C."
        )

    # 3. Track / asphalt / surface temperature questions
    if any(k in q for k in ["track temperature", "track temp", "track surface", "surface temp", "asphalt"]):
        if any(k in q for k in ["peak", "highest", "maximum", "max"]):
            return (
                f"The peak track temperature during the {season} {event_name} "
                f"was {weather['peak_track_temperature']}°C."
            )
        return (
            f"The average track temperature during the {season} {event_name} "
            f"was {weather['average_track_temperature']}°C (peak {weather['peak_track_temperature']}°C)."
        )

    # 4. Air / ambient temperature questions
    if any(k in q for k in ["air temperature", "air temp", "ambient", "temperature", "temp"]):
        if "range" in q:
            return (
                f"The air temperature during the {season} {event_name} ranged from "
                f"{weather['min_air_temperature']}°C to {weather['max_air_temperature']}°C "
                f"(average {weather['average_air_temperature']}°C)."
            )
        return (
            f"The average air temperature during the {season} {event_name} "
            f"was {weather['average_air_temperature']}°C "
            f"(average track temperature {weather['average_track_temperature']}°C)."
        )

    # 5. Humidity / Wind / Pressure questions
    if "humidity" in q and weather.get("average_humidity") is not None:
        return (
            f"The average humidity during the {season} {event_name} "
            f"was {round(weather['average_humidity'], 1)}%."
        )
    if "wind" in q and weather.get("average_wind_speed") is not None:
        return (
            f"The average wind speed during the {season} {event_name} "
            f"was {round(weather['average_wind_speed'], 1)} m/s."
        )
    if "pressure" in q and weather.get("average_pressure") is not None:
        return (
            f"The average atmospheric pressure during the {season} {event_name} "
            f"was {round(weather['average_pressure'], 1)} hPa."
        )

    # Default weather summary
    return (
        f"During the {season} {event_name}, conditions were {weather['condition']}. "
        f"Average air temperature was {weather['average_air_temperature']}°C, "
        f"peak track temperature was {weather['peak_track_temperature']}°C, "
        f"and rainfall was {'recorded' if weather['has_rainfall'] else 'not recorded'}."
    )