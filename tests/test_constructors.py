from .conftest import client


def test_get_constructors():
    response = client.get("/constructors")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) > 0

    assert "constructor_id" in data[0]
    assert "constructor_name" in data[0]