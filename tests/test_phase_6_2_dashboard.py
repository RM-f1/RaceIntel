"""
Phase 6.2 Verification Tests — Season-Aware Analytics Dashboard.

Comprehensive verification of:
1. Global season selector (2022-2026) persistence and multi-page propagation
2. Authentic driver photo catalog, local cache validation, licensing & graceful fallbacks
3. Driver Intelligence dossier with genuine portraits, championship rank & telemetry
4. Side-by-side Head-to-Head (H2H) comparison, teammate detection, and delta metrics
5. Constructor Intelligence with lineup progression, driver contribution split, and rank
6. Race Analysis classification, grid delta movers, pace, tyres, and weather
7. AI Race Engineer season-specific prompt suggestions and interaction
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
from frontend.driver_photos import (
    DRIVER_CATALOG,
    DRIVER_CODE_BY_ID,
    get_driver_photo_info,
)
from raceintel.api.main import app


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    return TestClient(app)


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


# ---------------------------------------------------------------------------
# 1. Driver Photographs, Licensing & Graceful Fallback System
# ---------------------------------------------------------------------------

def test_driver_photo_catalog_coverage_and_attribution():
    """Verify that every driver in catalog has genuine source, author, and license."""
    assert len(DRIVER_CATALOG) >= 30

    for code, meta in DRIVER_CATALOG.items():
        assert meta.get("driver_code") == code
        assert meta.get("wiki_title"), f"Missing wiki title for {code}"
        assert meta.get("author"), f"Missing author for {code}"
        assert meta.get("license"), f"Missing license for {code}"
        assert meta.get("source_url"), f"Missing source url for {code}"

        # Verify no synthetic AI faces: must be Wikimedia / public domain
        assert "wikimedia.org" in meta.get("source_url", "").lower() or "wikipedia.org" in meta.get("source_url", "").lower()
        lic = meta.get("license", "")
        assert any(term in lic for term in ["CC", "Public", "OGL", "cc"]), f"Unexpected license {lic} for {code}"


@pytest.mark.requires_data
def test_driver_photo_local_cache_integrity():
    """Verify that cached image files exist on disk and are valid non-empty files."""
    assets_dir = Path("frontend/assets/drivers")
    assert assets_dir.exists()

    key_drivers = ["VER", "HAM", "NOR", "LEC", "PIA", "RUS", "SAI", "ALO", "PER", "GAS", "OCO", "ALB", "TSU", "STR", "HUL", "BOT"]
    for code in key_drivers:
        info = get_driver_photo_info(code)
        assert info["has_image"] is True, f"Image reported missing for {code}"
        assert info["local_path"] is not None
        p = Path(info["local_path"])
        assert p.exists(), f"Local image file missing: {p}"
        assert p.stat().st_size > 5000, f"Image file too small or corrupted: {p}"


@pytest.mark.requires_data
def test_driver_photo_fallback_handling():
    """Verify unknown or missing drivers return graceful fallback info without crashing."""
    unknown = get_driver_photo_info("UNKNOWN_XYZ_999")
    assert unknown["has_image"] is False
    assert unknown["local_path"] is None
    assert unknown["author"] is not None

    by_id = get_driver_photo_info(driver_id=2)  # Max Verstappen
    assert by_id["driver_code"] == "VER"
    assert by_id["has_image"] is True


# ---------------------------------------------------------------------------
# 2. Multi-Season API Verification (2022 - 2026)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "season",
    [
        2022,
        pytest.param(2023, marks=pytest.mark.requires_full_data),
        2024,
        pytest.param(2025, marks=pytest.mark.requires_full_data),
        pytest.param(2026, marks=pytest.mark.requires_full_data),
    ],
)
@pytest.mark.requires_data
def test_analytics_endpoints_multi_season_support(api_client: TestClient, season: int):
    """Verify /analytics/overview, progression, and standings for all 5 seasons."""
    ov = api_client.get("/analytics/overview", params={"season": season})
    assert ov.status_code == 200, f"Overview failed for season {season}: {ov.text}"
    ov_data = ov.json()
    assert ov_data["season"] == season
    assert ov_data["total_races"] > 0
    assert ov_data["counts"]["total_drivers"] > 0
    assert ov_data["counts"]["total_constructors"] in (10, 11)
    assert len(ov_data["calendar"]) > 0

    prog = api_client.get("/analytics/standings/progression", params={"season": season})
    assert prog.status_code == 200, f"Progression failed for season {season}: {prog.text}"
    p_data = prog.json()
    assert len(p_data["constructors"]) > 0
    assert len(p_data["drivers"]) > 0


@pytest.mark.requires_data
def test_driver_season_profile_championship_rank(api_client: TestClient):
    """Verify that get_driver_season_profile includes championship_rank and season_constructor."""
    # Max Verstappen (driver_id=2) won 2022, 2023, 2024
    d2024 = api_client.get("/analytics/drivers/2/season", params={"season": 2024}).json()
    assert d2024["summary"]["championship_rank"] == 1
    assert d2024["summary"]["wins"] > 0
    assert d2024["summary"]["total_points"] > 350
    assert d2024["driver"]["season_constructor"] == "Red Bull Racing"
    assert d2024["summary"]["best_finish"] == 1
    assert d2024["summary"]["best_grid"] == 1

    # Lando Norris (driver_id=3) was P2 in 2024
    d_nor = api_client.get("/analytics/drivers/3/season", params={"season": 2024}).json()
    assert d_nor["summary"]["championship_rank"] == 2
    assert d_nor["driver"]["season_constructor"] == "McLaren"


@pytest.mark.requires_data
def test_constructor_season_profile_and_contribution_split(api_client: TestClient):
    """Verify constructor profile KPIs and driver contribution breakdown."""
    # McLaren (constructor_id=6) won 2024 Constructors Championship
    c2024 = api_client.get("/analytics/constructors/6/season", params={"season": 2024}).json()
    assert c2024["summary"]["championship_rank"] == 1
    assert c2024["summary"]["total_points"] > 600
    assert len(c2024["driver_contributions"]) >= 2
    # Verify drivers are Norris & Piastri
    codes = {d["driver_code"] for d in c2024["driver_contributions"]}
    assert "NOR" in codes
    assert "PIA" in codes

    # Ferrari (constructor_id=3) finished P2 in 2024
    ferrari = api_client.get("/analytics/constructors/3/season", params={"season": 2024}).json()
    assert ferrari["summary"]["championship_rank"] == 2


# ---------------------------------------------------------------------------
# 3. Streamlit Multi-Season End-to-End AppTest
# ---------------------------------------------------------------------------

@pytest.mark.requires_data
def test_streamlit_season_selector_propagation_and_persistence(api_client: TestClient):
    """Verify that changing the season in the sidebar propagates to all views."""
    fake_get, fake_post = _make_testclient_adapter(api_client)
    with patch("frontend.api_client.requests.get", side_effect=fake_get), patch(
        "frontend.api_client.requests.post", side_effect=fake_post
    ):
        at = AppTest.from_file(APP_PATH, default_timeout=25)
        at.run()
        assert not at.exception

        # Check season selector options
        season_sel = at.selectbox(key="global_season")
        opt_strs = [str(x) for x in season_sel.options]
        assert "2024" in opt_strs
        assert "2022" in opt_strs
        assert "2023" in opt_strs
        assert "2025" in opt_strs
        assert "2026" in opt_strs

        # Switch to 2023 season
        target_val = 2023 if 2023 in season_sel.options else "2023"
        season_sel.set_value(target_val).run()
        assert not at.exception
        assert int(at.session_state["global_season"]) == 2023

        # Navigate to DRIVER INTELLIGENCE with 2023 active
        at.radio(key="nav_module").set_value("03 // DRIVER INTELLIGENCE").run()
        assert not at.exception
        # Season must persist across navigation
        assert at.session_state["global_season"] == 2023
        rendered = " ".join(m.value for m in at.markdown)
        assert "2023" in rendered

        # Navigate to CONSTRUCTOR INTELLIGENCE
        at.radio(key="nav_module").set_value("04 // CONSTRUCTOR INTELLIGENCE").run()
        assert not at.exception
        assert at.session_state["global_season"] == 2023

        # Navigate to RACE ANALYSIS
        at.radio(key="nav_module").set_value("02 // RACE ANALYSIS").run()
        assert not at.exception
        assert at.session_state["global_season"] == 2023

        # Navigate to SYSTEM / ABOUT and verify licensing registry
        at.radio(key="nav_module").set_value("06 // SYSTEM / ABOUT").run()
        assert not at.exception
        rendered_about = " ".join(m.value for m in at.markdown)
        assert "DRIVER PHOTOGRAPHY ATTRIBUTION" in rendered_about


@pytest.mark.requires_data
def test_streamlit_driver_intel_h2h_comparison(api_client: TestClient):
    """Verify Driver Intel renders genuine portrait and exercises Head-to-Head mode."""
    fake_get, fake_post = _make_testclient_adapter(api_client)
    with patch("frontend.api_client.requests.get", side_effect=fake_get), patch(
        "frontend.api_client.requests.post", side_effect=fake_post
    ):
        at = AppTest.from_file(APP_PATH, default_timeout=25)
        at.run()

        # Set to 2024 and Driver Intelligence
        at.selectbox(key="global_season").set_value(2024).run()
        at.radio(key="nav_module").set_value("03 // DRIVER INTELLIGENCE").run()
        assert not at.exception

        # Check compare options
        cmp_select = at.selectbox(key="drv_compare_select")
        assert len(cmp_select.options) > 1

        # Select second option for H2H battle
        second_option = cmp_select.options[1]
        cmp_select.set_value(second_option).run()
        assert not at.exception
        rendered = " ".join(m.value for m in at.markdown)
        assert "HEAD-TO-HEAD" in rendered
        assert "HEAD-TO-HEAD FINISH RECORD" in rendered


@pytest.mark.requires_data
def test_streamlit_ai_engineer_season_prompts(api_client: TestClient):
    """Verify AI Race Engineer adapts suggestions to active season and answers queries."""
    fake_get, fake_post = _make_testclient_adapter(api_client)
    with patch("frontend.api_client.requests.get", side_effect=fake_get), patch(
        "frontend.api_client.requests.post", side_effect=fake_post
    ):
        at = AppTest.from_file(APP_PATH, default_timeout=25)
        at.run()

        # Switch to 2024 and navigate to AI Engineer
        at.selectbox(key="global_season").set_value(2024).run()
        at.radio(key="nav_module").set_value("05 // AI RACE ENGINEER").run()
        assert not at.exception

        rendered = " ".join(m.value for m in at.markdown)
        assert "SEASON 2024" in rendered

        # Submit a query
        at.chat_input(key="ai_chat_input").set_value("Who won the 2024 British Grand Prix?").run()
        assert not at.exception
        history = at.session_state["ri_chat_history"]
        assert len(history) == 2
        assert "Hamilton" in history[1]["content"]
