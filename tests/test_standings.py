from .conftest import client


def test_get_standings():
    response = client.get("/standings/drivers/1")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) > 0

    assert "driver_code" in data[0]
    assert "driver_full_name" in data[0]
    assert "constructor_name" in data[0]
    assert "finish_position" in data[0]
    assert "points_scored" in data[0]