"""API tests for GET /analytics/pit-window using synthetic artifacts (no DB required)."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from raceintel.api.main import app
import raceintel.api.routers.analytics as analytics_router

client = TestClient(app)

_SYNTHETIC_ARTIFACTS = {
    "metadata": {
        "build_date": "2026-11-25",
        "sign_convention": "positive = slower (degradation costs time)",
        "note": "Synthetic v2 test artifacts",
    },
    "degradation": [
        {"season": 2024, "compound": "SOFT", "slope": 0.02588, "se": 0.009, "n": 1480},
        {"season": 2024, "compound": "MEDIUM", "slope": -0.02401, "se": 0.007, "n": 7633},
        {"season": 2024, "compound": "HARD", "slope": -0.020572, "se": 0.004, "n": 12255},
    ],
    "pit_loss": [
        {"season": 2024, "race": "Bahrain Grand Prix", "median_pit_loss_s": 23.999, "n_stops": 40},
    ],
    "stint_p95": [
        {"season": 2024, "compound": "SOFT", "p95_stint_length": 24.0},
        {"season": 2024, "compound": "MEDIUM", "p95_stint_length": 35.0},
        {"season": 2024, "compound": "HARD", "p95_stint_length": 45.0},
    ],
}


def test_get_pit_window_happy_path():
    with patch.object(analytics_router, "load_artifacts", return_value=_SYNTHETIC_ARTIFACTS):
        resp = client.get(
            "/analytics/pit-window",
            params={
                "race": "Bahrain Grand Prix",
                "total_laps": 57,
                "season": 2024,
                "compound_1": "SOFT",
                "compound_2": "HARD",
            },
        )
    assert resp.status_code == 200
    data = resp.json()

    assert data["race"] == "Bahrain Grand Prix"
    assert data["season"] == 2024
    assert data["total_laps"] == 57
    assert data["pit_loss_s"] == 23.999
    assert data["compounds"]["stint_1"]["p95_stint_cap_laps"] == 24.0
    assert data["compounds"]["stint_2"]["p95_stint_cap_laps"] == 45.0
    assert data["fuel_assumptions"]["default_s_per_lap"] == 0.05
    assert data["fuel_assumptions"]["sensitivity_s_per_lap"] == [0.03, 0.05, 0.07]

    rec = data["recommendation"]
    assert rec["earliest_lap"] <= rec["optimal_lap"] <= rec["latest_lap"]
    assert rec["latest_lap"] <= 24
    assert len(data["sensitivity"]) == 3


def test_get_pit_window_unknown_race_returns_404():
    with patch.object(analytics_router, "load_artifacts", return_value=_SYNTHETIC_ARTIFACTS):
        resp = client.get(
            "/analytics/pit-window",
            params={"race": "Unknown GP", "total_laps": 57, "season": 2024},
        )
    assert resp.status_code == 404
    assert "No pit_loss record" in resp.json()["detail"]


def test_get_pit_window_infeasible_laps_returns_422():
    with patch.object(analytics_router, "load_artifacts", return_value=_SYNTHETIC_ARTIFACTS):
        resp = client.get(
            "/analytics/pit-window",
            params={
                "race": "Bahrain Grand Prix",
                "total_laps": 80,
                "season": 2024,
                "compound_1": "SOFT",
                "compound_2": "HARD",
            },
        )
    assert resp.status_code == 422
    assert "infeasible" in resp.json()["detail"]


def test_get_pit_window_invalid_query_params_returns_422():
    resp = client.get(
        "/analytics/pit-window",
        params={"race": "Bahrain Grand Prix", "total_laps": 1},
    )
    assert resp.status_code == 422


def test_get_pit_window_missing_artifacts_returns_503():
    with patch.object(analytics_router, "load_artifacts", side_effect=FileNotFoundError("missing")):
        resp = client.get(
            "/analytics/pit-window",
            params={"race": "Bahrain Grand Prix", "total_laps": 57},
        )
    assert resp.status_code == 503
