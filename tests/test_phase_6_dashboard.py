"""
Phase 6 Verification Tests — Retro Terminal Dashboard & Analytics API.

Covers:
1. New read-only FastAPI `/analytics/*` endpoints + backward compatibility of existing routes
2. `frontend.api_client` HTTP error/timeout/empty/success handling
3. `frontend.theme` Retro Terminal CSS palette & Altair theme verification
4. End-to-end headless Streamlit `AppTest` navigation across all 6 dashboard modules,
   AI Race Engineer chat interaction, and offline error recovery
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("RACEINTEL_OFFLINE", "1")
APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

import altair as alt
import pandas as pd
import pytest
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from frontend.api_client import RaceIntelAPIClient
from frontend.theme import (
    BG_PRIMARY,
    BG_SECONDARY,
    FG_LIGHT,
    FG_PRIMARY,
    get_retro_css,
    style_altair_chart,
)
from raceintel.api.main import app


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. FastAPI Analytics Router & Existing Endpoints Compatibility
# ---------------------------------------------------------------------------

@pytest.mark.requires_data
def test_existing_endpoints_preserved(api_client: TestClient):
    h = api_client.get("/health/")
    assert h.status_code == 200
    assert h.json() == {"status": "healthy", "database": "connected"}

    sess = api_client.get("/sessions/", params={"season": 2024})
    assert sess.status_code == 200
    sessions = sess.json()
    assert len(sessions) >= 24

    first_sid = sessions[0]["session_id"]
    assert api_client.get("/drivers/").status_code == 200
    assert api_client.get("/constructors/").status_code == 200
    assert api_client.get(f"/races/{first_sid}").status_code == 200
    assert api_client.get(f"/weather/{first_sid}").status_code == 200
    assert api_client.get(f"/pace/{first_sid}").status_code == 200
    assert api_client.get(f"/standings/drivers/{first_sid}").status_code == 200
    assert api_client.get(f"/standings/constructors/{first_sid}").status_code == 200


@pytest.mark.requires_data
def test_analytics_overview_and_progression(api_client: TestClient):
    ov = api_client.get("/analytics/overview", params={"season": 2024})
    assert ov.status_code == 200
    data = ov.json()
    assert data["season"] == 2024
    assert data["total_races"] == 24
    assert data["counts"]["total_drivers"] > 0
    assert data["counts"]["total_constructors"] == 10
    assert data["driver_leader"]["driver_code"] is not None
    assert data["constructor_leader"]["constructor_name"] is not None

    prog = api_client.get("/analytics/standings/progression", params={"season": 2024})
    assert prog.status_code == 200
    pdata = prog.json()
    assert len(pdata["constructors"]) > 0
    assert len(pdata["drivers"]) > 0


@pytest.mark.requires_data
def test_analytics_season_standings_and_404(api_client: TestClient):
    sessions = api_client.get("/sessions/", params={"season": 2024}).json()
    last_sid = sessions[-1]["session_id"]

    drv = api_client.get(f"/analytics/standings/drivers/season/{last_sid}", params={"season": 2024})
    assert drv.status_code == 200
    drv_rows = drv.json()
    assert drv_rows[0]["rank"] == 1
    assert drv_rows[0]["driver_code"] == "VER"

    con = api_client.get(f"/analytics/standings/constructors/season/{last_sid}", params={"season": 2024})
    assert con.status_code == 200
    con_rows = con.json()
    assert con_rows[0]["rank"] == 1
    assert con_rows[0]["constructor_name"] == "McLaren"

    assert api_client.get("/analytics/overview", params={"season": 1999}).status_code == 404
    assert api_client.get("/analytics/race/999999/full").status_code == 404


@pytest.mark.requires_data
def test_analytics_full_race_driver_and_constructor_profiles(api_client: TestClient):
    sessions = api_client.get("/sessions/", params={"season": 2024}).json()
    sid = sessions[0]["session_id"]
    race_full = api_client.get(f"/analytics/race/{sid}/full")
    assert race_full.status_code == 200
    rjson = race_full.json()
    assert {"session", "report", "driver_classification", "position_changes", "pace", "tyres", "weather"}.issubset(
        rjson.keys()
    )
    assert len(rjson["pace"]["fastest_laps"]) > 0
    assert len(rjson["tyres"]["usage"]) > 0

    drivers = api_client.get("/drivers/").json()
    did = drivers[0]["driver_id"]
    d_prof = api_client.get(f"/analytics/drivers/{did}/season", params={"season": 2024})
    assert d_prof.status_code == 200
    assert "summary" in d_prof.json()

    constructors = api_client.get("/constructors/").json()
    cid = constructors[0]["constructor_id"]
    c_prof = api_client.get(f"/analytics/constructors/{cid}/season", params={"season": 2024})
    assert c_prof.status_code == 200
    assert "driver_contributions" in c_prof.json()

    assert api_client.get("/analytics/drivers/999999/season").status_code == 404
    assert api_client.get("/analytics/constructors/999999/season").status_code == 404


@pytest.mark.requires_data
def test_chat_endpoint_offline_preserved(api_client: TestClient):
    resp = api_client.post("/chat/", json={"question": "Who won the 2024 British Grand Prix?"})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("answer"), str)
    assert "Hamilton" in body["answer"]


# ---------------------------------------------------------------------------
# 2. Frontend API Client & Retro Theme Unit Tests
# ---------------------------------------------------------------------------

def test_api_client_error_handling_and_empty_chat():
    client = RaceIntelAPIClient(base_url="http://127.0.0.1:8001")
    data, err = client.ask_race_engineer("   ")
    assert data is None
    assert err == "Query cannot be empty."

    with patch("frontend.api_client.requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
        data, err = client.get_health()
        assert data is None
        assert "unreachable" in err.lower()

    with patch("frontend.api_client.requests.get", side_effect=requests.exceptions.Timeout("timeout")):
        data, err = client.get_overview()
        assert data is None
        assert "timed out" in err.lower()

    bad_resp = MagicMock()
    bad_resp.status_code = 500
    bad_resp.json.return_value = {"detail": "Internal test fault"}
    bad_resp.text = "Internal test fault"
    with patch("frontend.api_client.requests.post", return_value=bad_resp):
        data, err = client.ask_race_engineer("Who won Monaco 2024?")
        assert data is None
        assert "500" in err and "Internal test fault" in err


def test_retro_theme_palette_and_chart_styling():
    css = get_retro_css()
    assert BG_PRIMARY == "#17251D"
    assert FG_PRIMARY == "#D5E8B5"
    assert BG_SECONDARY == "#A7B89C"
    assert FG_LIGHT == "#FFFFFF"
    for hex_code in (BG_PRIMARY, FG_PRIMARY, BG_SECONDARY, FG_LIGHT):
        assert hex_code in css
    assert "border-radius: 0px !important" in css

    df = pd.DataFrame({"x": ["VER", "NOR"], "y": [10, 8]})
    styled = style_altair_chart(alt.Chart(df).mark_bar().encode(x="x:N", y="y:Q"), title="TEST")
    cfg = styled.to_dict()["config"]
    assert cfg["background"] == BG_PRIMARY
    assert cfg["axis"]["labelColor"] == FG_PRIMARY


# ---------------------------------------------------------------------------
# 3. Headless Streamlit AppTest Across All 6 Dashboard Views
# ---------------------------------------------------------------------------

def _make_testclient_adapter(tc: TestClient):
    """Bridge requests.get / requests.post in AppTest directly to FastAPI TestClient."""

    def _convert(resp):
        mock_r = MagicMock()
        mock_r.status_code = resp.status_code
        mock_r.text = resp.text
        mock_r.json = resp.json
        return mock_r

    def fake_get(url, params=None, timeout=12):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        return _convert(tc.get(path, params=params))

    def fake_post(url, json=None, timeout=60):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        return _convert(tc.post(path, json=json))

    return fake_get, fake_post


@pytest.mark.requires_data
def test_streamlit_multipage_navigation_and_ai_chat(api_client: TestClient):
    fake_get, fake_post = _make_testclient_adapter(api_client)
    with patch("frontend.api_client.requests.get", side_effect=fake_get), patch(
        "frontend.api_client.requests.post", side_effect=fake_post
    ):
        at = AppTest.from_file(APP_PATH, default_timeout=20)
        at.run()
        assert not at.exception

        pages = [
            "02 // RACE ANALYSIS",
            "03 // DRIVER INTELLIGENCE",
            "04 // CONSTRUCTOR INTELLIGENCE",
            "05 // AI RACE ENGINEER",
            "06 // SYSTEM / ABOUT",
            "01 // DASHBOARD",
        ]
        for page in pages:
            at.radio(key="nav_module").set_value(page).run()
            assert not at.exception, f"Exception rendering page {page}: {at.exception}"

        # Exercise AI Race Engineer chat submission + Clear Log
        at.radio(key="nav_module").set_value("05 // AI RACE ENGINEER").run()
        at.chat_input(key="ai_chat_input").set_value("Who won the 2024 British Grand Prix?").run()
        assert not at.exception
        history = at.session_state["ri_chat_history"]
        assert len(history) == 2
        assert "Hamilton" in history[1]["content"]

        at.button(key="ai_clear_btn").click().run()
        assert at.session_state["ri_chat_history"] == []


def test_streamlit_offline_graceful_degradation():
    with patch("frontend.api_client.requests.get", side_effect=requests.exceptions.ConnectionError("offline")):
        at = AppTest.from_file(APP_PATH, default_timeout=20)
        at.run()
        assert not at.exception
        rendered_html = " ".join(m.value for m in at.markdown)
        assert "OFFLINE" in rendered_html
        assert "BACKEND API CONNECTION UNAVAILABLE" in rendered_html
