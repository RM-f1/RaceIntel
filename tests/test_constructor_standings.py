from .conftest import client


def test_get_constructor_standings():
    response = client.get("/standings/constructors/1")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) > 0

    assert "constructor_name" in data[0]
    assert "total_points" in data[0]