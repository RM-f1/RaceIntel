"""Tests for analytics.pit_window — no database required."""

import pytest

from analytics.pit_window import (
    DEFAULT_FUEL_EFFECT,
    SENSITIVITY_FUEL_EFFECTS,
    compute_pit_window,
    recommend_pit_window_from_artifacts,
)


def _deg_records(
    slope_soft: float = 0.03,
    slope_medium: float = -0.02,
    slope_hard: float = -0.02,
    season: int = 2024,
) -> list[dict]:
    return [
        {"season": season, "compound": "SOFT", "slope": slope_soft, "se": 0.005, "n": 1000},
        {"season": season, "compound": "MEDIUM", "slope": slope_medium, "se": 0.005, "n": 2000},
        {"season": season, "compound": "HARD", "slope": slope_hard, "se": 0.005, "n": 3000},
    ]


def _stint_caps(
    cap_soft: float = 24.0,
    cap_medium: float = 35.0,
    cap_hard: float = 45.0,
    season: int = 2024,
) -> list[dict]:
    return [
        {"season": season, "compound": "SOFT", "p95_stint_length": cap_soft},
        {"season": season, "compound": "MEDIUM", "p95_stint_length": cap_medium},
        {"season": season, "compound": "HARD", "p95_stint_length": cap_hard},
    ]


def test_higher_wear_produces_earlier_pit_window():
    """Increasing compound_1 degradation slope must shift the pit window earlier."""
    low_wear = compute_pit_window(
        total_laps=57,
        compound_1="SOFT",
        compound_2="HARD",
        degradation_records=_deg_records(slope_soft=0.01, slope_hard=-0.02),
        stint_p95_records=_stint_caps(cap_soft=40.0, cap_hard=45.0),
        pit_loss_s=24.0,
    )
    high_wear = compute_pit_window(
        total_laps=57,
        compound_1="SOFT",
        compound_2="HARD",
        degradation_records=_deg_records(slope_soft=0.08, slope_hard=-0.02),
        stint_p95_records=_stint_caps(cap_soft=40.0, cap_hard=45.0),
        pit_loss_s=24.0,
    )
    assert high_wear["recommendation"]["optimal_lap"] < low_wear["recommendation"]["optimal_lap"]
    assert high_wear["recommendation"]["earliest_lap"] < low_wear["recommendation"]["earliest_lap"]
    assert high_wear["recommendation"]["latest_lap"] < low_wear["recommendation"]["latest_lap"]


def test_fuel_assumptions_shift_window_without_changing_compound_ordering():
    """Global fuel assumptions shift the pit window while preserving w1 - w2 == slope1 - slope2."""
    res = compute_pit_window(
        total_laps=57,
        compound_1="SOFT",
        compound_2="HARD",
        degradation_records=_deg_records(slope_soft=0.02588, slope_hard=-0.020572),
        stint_p95_records=_stint_caps(cap_soft=24.0, cap_hard=45.0),
        pit_loss_s=23.999,
    )
    sens = res["sensitivity"]
    assert [s["fuel_effect_s_per_lap"] for s in sens] == list(SENSITIVITY_FUEL_EFFECTS)

    opt_laps = [s["optimal_lap"] for s in sens]
    assert opt_laps[0] < opt_laps[1] < opt_laps[2]

    expected_diff = round(0.02588 - (-0.020572), 6)
    for row in sens:
        w1 = row["wear_per_lap"]["compound_1"]
        w2 = row["wear_per_lap"]["compound_2"]
        assert w1 > w2
        assert round(w1 - w2, 6) == pytest.approx(expected_diff, abs=1e-6)


def test_stint_caps_enforced_with_flat_and_negative_wear():
    """Empirical P95 stint caps must never be exceeded even when wear is flat or negative."""
    # Flat wear: both compounds have wear = 0.0 (slope = -0.05, fuel = 0.05)
    flat = compute_pit_window(
        total_laps=50,
        compound_1="MEDIUM",
        compound_2="HARD",
        degradation_records=_deg_records(slope_medium=-0.05, slope_hard=-0.05),
        stint_p95_records=_stint_caps(cap_medium=28.0, cap_hard=32.0),
        pit_loss_s=22.0,
        fuel_effect=0.05,
    )
    rec_flat = flat["recommendation"]
    assert 18 <= rec_flat["earliest_lap"] <= rec_flat["optimal_lap"] <= rec_flat["latest_lap"] <= 28
    assert (50 - rec_flat["earliest_lap"]) <= 32

    # Negative wear on both compounds (concave objective -> pushes to cap boundary)
    neg = compute_pit_window(
        total_laps=50,
        compound_1="MEDIUM",
        compound_2="HARD",
        degradation_records=_deg_records(slope_medium=-0.08, slope_hard=-0.06),
        stint_p95_records=_stint_caps(cap_medium=28.0, cap_hard=32.0),
        pit_loss_s=22.0,
        fuel_effect=0.05,
    )
    rec_neg = neg["recommendation"]
    assert 18 <= rec_neg["earliest_lap"] <= rec_neg["optimal_lap"] <= rec_neg["latest_lap"] <= 28
    assert (50 - rec_neg["earliest_lap"]) <= 32
    assert rec_neg["cap_constrained"] is True


def test_disconnected_tolerance_regions_and_equal_cost_ties():
    """Concave symmetric negative wear produces equal-cost ties and disconnected windows."""
    # Equal negative wear w1 = w2 = -0.05 (slope = -0.10, fuel = 0.05):
    # J(L) is symmetric and strictly concave, minimized equally at L_min=18 and L_max=32.
    res = compute_pit_window(
        total_laps=50,
        compound_1="MEDIUM",
        compound_2="HARD",
        degradation_records=_deg_records(slope_medium=-0.10, slope_hard=-0.10),
        stint_p95_records=_stint_caps(cap_medium=32.0, cap_hard=32.0),
        pit_loss_s=22.0,
        fuel_effect=0.05,
        window_tolerance_s=0.5,
    )
    rec = res["recommendation"]
    # Tie-breaker picks earliest minimum-cost lap (L_min = 18)
    assert rec["tied_optimal_laps"] == [18, 32]
    assert rec["optimal_lap"] == 18
    # Primary window is contiguous around L=18, NOT [18, 32]
    assert rec["earliest_lap"] == 18
    assert rec["latest_lap"] < 25
    # Disconnected region around L=32 is reported separately
    assert len(rec["alternate_windows"]) == 1
    alt = rec["alternate_windows"][0]
    assert alt["latest_lap"] == 32
    assert alt["earliest_lap"] > rec["latest_lap"] + 1


def test_window_contains_optimum_and_pit_loss_is_constant():
    """Window always contains optimal_lap, and pit_loss_s does not shift optimal_lap."""
    r1 = compute_pit_window(
        total_laps=57,
        compound_1="SOFT",
        compound_2="HARD",
        degradation_records=_deg_records(),
        stint_p95_records=_stint_caps(),
        pit_loss_s=18.0,
    )
    r2 = compute_pit_window(
        total_laps=57,
        compound_1="SOFT",
        compound_2="HARD",
        degradation_records=_deg_records(),
        stint_p95_records=_stint_caps(),
        pit_loss_s=30.0,
    )
    for r in (r1, r2):
        rec = r["recommendation"]
        assert rec["earliest_lap"] <= rec["optimal_lap"] <= rec["latest_lap"]
    assert r1["recommendation"]["optimal_lap"] == r2["recommendation"]["optimal_lap"]
    assert r1["recommendation"]["earliest_lap"] == r2["recommendation"]["earliest_lap"]
    assert r1["recommendation"]["latest_lap"] == r2["recommendation"]["latest_lap"]


def test_sensitivity_matches_direct_calls():
    """Each sensitivity entry must match a direct compute_pit_window call at that fuel_effect."""
    deg = _deg_records(slope_soft=0.02588, slope_hard=-0.020572)
    caps = _stint_caps(cap_soft=24.0, cap_hard=45.0)
    res = compute_pit_window(
        total_laps=57,
        compound_1="SOFT",
        compound_2="HARD",
        degradation_records=deg,
        stint_p95_records=caps,
        pit_loss_s=23.999,
        fuel_effect=DEFAULT_FUEL_EFFECT,
    )
    for entry in res["sensitivity"]:
        f = entry["fuel_effect_s_per_lap"]
        direct = compute_pit_window(
            total_laps=57,
            compound_1="SOFT",
            compound_2="HARD",
            degradation_records=deg,
            stint_p95_records=caps,
            pit_loss_s=23.999,
            fuel_effect=f,
        )["recommendation"]
        assert entry == direct


def test_invalid_inputs_raise_clear_errors():
    """Invalid parameters, missing compounds, or infeasible caps must raise ValueError."""
    deg = _deg_records()
    caps = _stint_caps(cap_soft=20.0, cap_hard=25.0)

    with pytest.raises(ValueError, match="total_laps"):
        compute_pit_window(1, "SOFT", "HARD", deg, caps, pit_loss_s=22.0)

    with pytest.raises(ValueError, match="pit_loss_s"):
        compute_pit_window(50, "SOFT", "HARD", deg, caps, pit_loss_s=0.0)

    with pytest.raises(ValueError, match="fuel_effect"):
        compute_pit_window(50, "SOFT", "HARD", deg, caps, pit_loss_s=22.0, fuel_effect=-0.01)

    with pytest.raises(ValueError, match="No degradation record"):
        compute_pit_window(40, "HYPERSOFT", "HARD", deg, caps, pit_loss_s=22.0)

    with pytest.raises(ValueError, match="infeasible"):
        compute_pit_window(50, "SOFT", "HARD", deg, caps, pit_loss_s=22.0)


def test_recommend_from_artifacts_unknown_race_raises(tmp_path):
    """Unknown circuit name raises a clear ValueError."""
    import json

    art = {
        "metadata": {
            "build_date": "2026-11-25",
            "sign_convention": "positive = slower",
            "note": "v2",
        },
        "degradation": _deg_records(),
        "pit_loss": [{"season": 2024, "race": "Bahrain Grand Prix", "median_pit_loss_s": 24.0, "n_stops": 40}],
        "stint_p95": _stint_caps(),
    }
    p = tmp_path / "artifacts.json"
    p.write_text(json.dumps(art), encoding="utf-8")

    with pytest.raises(ValueError, match="No pit_loss record"):
        recommend_pit_window_from_artifacts("Atlantis GP", 57, artifacts_path=p)
