from .conftest import client


def test_get_pace():
    response = client.get("/pace/1")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) > 0

    assert "driver_code" in data[0]
    assert "driver_full_name" in data[0]
    assert "fastest_lap_seconds" in data[0]