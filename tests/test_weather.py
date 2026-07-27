from src.analytics.weather import (
    get_weather_summary,
    get_rain_periods,
    get_temperature_trend,
    get_weather_extremes,
)


def test_weather_summary():

    df = get_weather_summary(1)

    assert not df.empty
    assert "average_air_temperature" in df.columns
    assert "average_track_temperature" in df.columns


def test_rain_periods():

    df = get_rain_periods(1)

    # Some races may have no rain.
    assert "rainfall" in df.columns


def test_temperature_trend():

    df = get_temperature_trend(1)

    assert not df.empty
    assert "observation_time" in df.columns
    assert "air_temperature_celsius" in df.columns
    assert "track_temperature_celsius" in df.columns


def test_weather_extremes():

    df = get_weather_extremes(1)

    assert not df.empty
    assert "minimum_air_temperature" in df.columns
    assert "maximum_air_temperature" in df.columns
    assert "maximum_wind_speed" in df.columns