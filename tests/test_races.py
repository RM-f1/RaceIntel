import pytest
pytestmark = pytest.mark.requires_data
import pytest
from .conftest import client


def test_get_race_report():
    response = client.get("/races/2")

    assert response.status_code == 200

    data = response.json()

    assert data["session_id"] == 2
    assert "winner" in data
    assert "podium" in data
    assert "top_constructor" in data
    assert "biggest_mover" in data
    assert "fastest_lap" in data
    assert "statistics" in data