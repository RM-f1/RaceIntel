"""Tests for analytics.artifacts — no database required."""

import json
import tempfile
from pathlib import Path

import pytest

from analytics.artifacts import (
    load_artifacts,
    load_degradation,
    load_pit_loss,
    load_stint_p95,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_ARTIFACTS = {
    "metadata": {
        "build_date": "2026-11-25",
        "sign_convention": "positive = slower (degradation costs time)",
        "note": "Net trends; fuel effect not removed.",
    },
    "degradation": [
        {"season": 2024, "compound": "SOFT", "slope": 0.032, "se": 0.004, "n": 1200},
        {"season": 2024, "compound": "MEDIUM", "slope": -0.019, "se": 0.003, "n": 900},
    ],
    "pit_loss": [
        {"season": 2024, "race": "Monza", "median_pit_loss_s": 22.1, "n_stops": 15},
    ],
    "stint_p95": [
        {"compound": "SOFT", "season": 2024, "p95_stint_length": 28},
        {"compound": "MEDIUM", "season": 2024, "p95_stint_length": 38},
    ],
}


def _write_artifacts(data: dict, tmp_path: Path) -> Path:
    p = tmp_path / "raceintel_artifacts.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_load_artifacts_happy_path(tmp_path):
    p = _write_artifacts(_MINIMAL_ARTIFACTS, tmp_path)
    data = load_artifacts(p)
    assert "metadata" in data
    assert "degradation" in data
    assert "pit_loss" in data
    assert "stint_p95" in data


def test_load_degradation_returns_list(tmp_path):
    p = _write_artifacts(_MINIMAL_ARTIFACTS, tmp_path)
    deg = load_degradation(p)
    assert isinstance(deg, list)
    assert len(deg) == 2
    assert deg[0]["compound"] == "SOFT"


def test_load_pit_loss_returns_list(tmp_path):
    p = _write_artifacts(_MINIMAL_ARTIFACTS, tmp_path)
    pl = load_pit_loss(p)
    assert isinstance(pl, list)
    assert pl[0]["race"] == "Monza"


def test_load_stint_p95_returns_list(tmp_path):
    p = _write_artifacts(_MINIMAL_ARTIFACTS, tmp_path)
    sp = load_stint_p95(p)
    assert isinstance(sp, list)
    assert sp[0]["compound"] == "SOFT"


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="Artifacts file not found"):
        load_artifacts(tmp_path / "nonexistent.json")


def test_missing_section_raises_value_error(tmp_path):
    bad = dict(_MINIMAL_ARTIFACTS)
    del bad["degradation"]
    p = _write_artifacts(bad, tmp_path)
    with pytest.raises(ValueError, match="missing section 'degradation'"):
        load_artifacts(p)


def test_missing_key_in_degradation_record_raises_value_error(tmp_path):
    bad = json.loads(json.dumps(_MINIMAL_ARTIFACTS))  # deep copy
    del bad["degradation"][0]["slope"]
    p = _write_artifacts(bad, tmp_path)
    with pytest.raises(ValueError, match="missing keys"):
        load_artifacts(p)


def test_missing_key_in_pit_loss_record_raises_value_error(tmp_path):
    bad = json.loads(json.dumps(_MINIMAL_ARTIFACTS))
    del bad["pit_loss"][0]["median_pit_loss_s"]
    p = _write_artifacts(bad, tmp_path)
    with pytest.raises(ValueError, match="missing keys"):
        load_artifacts(p)


def test_missing_key_in_stint_record_raises_value_error(tmp_path):
    bad = json.loads(json.dumps(_MINIMAL_ARTIFACTS))
    del bad["stint_p95"][0]["p95_stint_length"]
    p = _write_artifacts(bad, tmp_path)
    with pytest.raises(ValueError, match="missing keys"):
        load_artifacts(p)


def test_metadata_sign_convention_present(tmp_path):
    p = _write_artifacts(_MINIMAL_ARTIFACTS, tmp_path)
    data = load_artifacts(p)
    assert "positive" in data["metadata"]["sign_convention"].lower()


def test_slope_values_are_numeric(tmp_path):
    p = _write_artifacts(_MINIMAL_ARTIFACTS, tmp_path)
    deg = load_degradation(p)
    for rec in deg:
        assert isinstance(rec["slope"], (int, float))
        assert isinstance(rec["se"], (int, float))
        assert isinstance(rec["n"], int)


def test_build_artifacts_uses_degradation_v2(tmp_path):
    """Artifact slopes and SEs must come from degradation_v2.fit_within_stint."""
    import importlib.util
    import numpy as np
    import pandas as pd
    from analytics.degradation import build_clean_laps
    from analytics.degradation_v2 import fit_within_stint

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_artifacts.py"
    spec = importlib.util.spec_from_file_location("build_artifacts", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rng = np.random.default_rng(42)
    rows = []
    for session_id in (1, 2):
        for driver_id in range(1, 7):
            # Two stints with distinct baseline levels; true within-stint net slope = +0.04
            for stint, (start, end, level) in enumerate([(1, 15, 0.0), (16, 30, -3.0)], start=1):
                for lap in range(start, end + 1):
                    age = lap - start + 1
                    lt = 90.0 + level + 0.04 * lap + rng.normal(0, 0.05)
                    rows.append(
                        {
                            "session_id": session_id,
                            "driver_id": driver_id,
                            "lap_number": lap,
                            "tyre_compound": "SOFT",
                            "tyre_age_laps": age,
                            "lap_time_seconds": lt,
                            "season_year": 2024,
                            "event_name": "TestGP",
                        }
                    )
    laps = pd.DataFrame(rows)
    artifacts = mod.build_artifacts_from_laps(laps, min_laps=50, min_stops=10)

    p = _write_artifacts(artifacts, tmp_path)
    loaded = load_artifacts(p)

    assert "beta[1]" not in loaded["metadata"]["note"]
    assert "v2" in loaded["metadata"]["note"].lower()

    v2 = fit_within_stint(build_clean_laps(laps), min_laps=50).iloc[0]
    deg_rec = loaded["degradation"][0]
    assert deg_rec["compound"] == "SOFT"
    assert deg_rec["slope"] == pytest.approx(round(float(v2["net_s_per_lap"]), 6), abs=1e-9)
    assert deg_rec["se"] == pytest.approx(round(float(v2["net_se"]), 6), abs=1e-9)
    assert deg_rec["n"] == int(v2["laps"])
