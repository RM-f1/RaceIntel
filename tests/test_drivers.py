from fastapi.testclient import TestClient
from raceintel.api.main import app

client = TestClient(app)


def test_get_drivers():
    response = client.get("/drivers")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) > 0

    assert "driver_code" in data[0]
    assert "driver_full_name" in data[0]