from .conftest import client


def test_get_weather():
    response = client.get("/weather/1")

    assert response.status_code == 200

    data = response.json()

    assert "average_air_temperature" in data
    assert "average_track_temperature" in data
    assert "average_humidity" in data
    assert "average_wind_speed" in data
    assert "average_pressure" in data