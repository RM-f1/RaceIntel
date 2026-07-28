from fastapi.testclient import TestClient

from raceintel.api.main import app

client = TestClient(app)


def test_get_sessions():
    response = client.get("/sessions")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) > 0

    assert "session_id" in data[0]