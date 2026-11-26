"""Tests for analytics.pit_loss — no database required."""

import numpy as np
import pandas as pd
import pytest

from analytics.pit_loss import (
    WET_COMPOUNDS,
    compute_pit_losses,
    per_circuit_summary,
    season_comparison,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_laps(
    rows: list[tuple],
    session_id: int = 1,
    season_year: int = 2024,
    event_name: str = "TestGP",
) -> pd.DataFrame:
    """Build a minimal laps DataFrame.

    rows: list of (driver_id, lap_number, tyre_compound, lap_time_seconds)
    """
    return pd.DataFrame(
        [
            {
                "session_id": session_id,
                "driver_id": did,
                "lap_number": lap,
                "tyre_compound": compound,
                "tyre_age_laps": age,
                "lap_time_seconds": lt,
                "season_year": season_year,
                "event_name": event_name,
            }
            for did, lap, compound, age, lt in rows
        ]
    )


def _steady_driver(
    driver_id: int,
    n_laps: int,
    compound: str,
    base_time: float,
    session_id: int = 1,
    season_year: int = 2024,
    event_name: str = "TestGP",
) -> pd.DataFrame:
    """Single-stint driver with constant lap time."""
    rows = [
        (driver_id, lap, compound, lap, base_time)
        for lap in range(1, n_laps + 1)
    ]
    return _make_laps(rows, session_id=session_id, season_year=season_year, event_name=event_name)


# ---------------------------------------------------------------------------
# Test: clean green-flag stop is detected and pit_loss is sane
# ---------------------------------------------------------------------------

def test_clean_stop_detected():
    """A two-stint driver should produce exactly one pit_loss row."""
    rows = []
    base = 90.0

    # Driver 1 — stint 1: laps 1-15 on SOFT (~90 s each)
    for lap in range(1, 16):
        rows.append((1, lap, "SOFT", lap, base))

    # Driver 1 — in-lap (lap 15 already counted above but slower) → tweak
    rows[-1] = (1, 15, "SOFT", 15, base + 25.0)   # in-lap costs ~25 s extra

    # Driver 1 — stint 2: laps 16-40 on MEDIUM
    for lap in range(16, 41):
        rows.append((1, lap, "MEDIUM", lap - 15, base + 0.5))

    # Lots of other drivers so neutralisation logic has field data
    for d in range(2, 12):
        for lap in range(1, 41):
            rows.append((d, lap, "MEDIUM", lap, base + 0.1 * d))

    df = _make_laps(rows)
    result = compute_pit_losses(df)

    assert len(result) == 1, f"Expected 1 stop, got {len(result)}"
    row = result.iloc[0]
    assert row["driver_id"] == 1
    assert row["in_lap"] == 15
    # pit_loss = t_in + t_out - 2*ref; ref ≈ base, t_in ≈ base+25, t_out ≈ base+0.5
    # so pit_loss ≈ 25.5; just check it is positive and not huge
    assert 10.0 < row["pit_loss"] < 50.0


# ---------------------------------------------------------------------------
# Test: non-green stop (neutralised window) is excluded
# ---------------------------------------------------------------------------

def test_neutralised_stop_excluded():
    """A stop whose window overlaps a safety-car lap should be dropped."""
    base = 90.0
    rows = []

    # 10 background drivers to generate a field median
    for d in range(2, 12):
        for lap in range(1, 31):
            # lap 10 is a SC lap (very slow for everyone)
            lt = base * 2 if lap == 10 else base
            rows.append((d, lap, "MEDIUM", lap, lt))

    # Driver 1 — pit on lap 10 (the SC lap)
    for lap in range(1, 16):
        lt = base * 2 if lap == 10 else base + (25 if lap == 10 else 0)
        rows.append((1, lap, "SOFT", lap, lt))
    rows.append((1, 10, "SOFT", 10, base * 2 + 25))  # the in-lap
    for lap in range(11, 31):
        rows.append((1, lap, "MEDIUM", lap - 10, base))

    df = _make_laps(rows)
    result = compute_pit_losses(df)
    # The stop's window (laps 6-14) overlaps with lap 10, so it must be excluded
    assert result.empty or all(r["in_lap"] != 10 for _, r in result.iterrows())


# ---------------------------------------------------------------------------
# Test: wet-compound stop is excluded
# ---------------------------------------------------------------------------

def test_wet_compound_stop_excluded():
    """A stop onto INTERMEDIATE tyres must not appear in the output."""
    base = 90.0
    rows = []

    for d in range(2, 12):
        for lap in range(1, 31):
            rows.append((d, lap, "SOFT", lap, base))

    # Driver 1: SOFT → INTERMEDIATE
    for lap in range(1, 16):
        rows.append((1, lap, "SOFT", lap, base + (25 if lap == 15 else 0)))
    for lap in range(16, 31):
        rows.append((1, lap, "INTERMEDIATE", lap - 15, base))

    df = _make_laps(rows)
    result = compute_pit_losses(df)
    assert result.empty or all(r["driver_id"] != 1 for _, r in result.iterrows())


# ---------------------------------------------------------------------------
# Test: per_circuit_summary filters by min_stops
# ---------------------------------------------------------------------------

def test_per_circuit_summary_min_stops():
    """Circuits with fewer than min_stops stops should be excluded."""
    data = pd.DataFrame(
        {
            "season": [2024] * 15 + [2024] * 3,
            "race": ["Monza"] * 15 + ["Monaco"] * 3,
            "driver_id": list(range(15)) + list(range(3)),
            "in_lap": list(range(15)) + list(range(3)),
            "pit_loss": [22.0] * 15 + [21.0] * 3,
        }
    )
    per = per_circuit_summary(data, min_stops=10)
    assert (2024, "Monza") in per.index
    assert (2024, "Monaco") not in per.index
    assert round(per.loc[(2024, "Monza"), "median"], 1) == 22.0


# ---------------------------------------------------------------------------
# Test: season_comparison computes diff correctly
# ---------------------------------------------------------------------------

def test_season_comparison():
    """diff column must equal 2024 median minus 2022 median."""
    data = pd.DataFrame(
        {
            "season": [2022] * 12 + [2024] * 12,
            "race": ["Silverstone"] * 12 + ["Silverstone"] * 12,
            "driver_id": list(range(12)) * 2,
            "in_lap": list(range(12)) * 2,
            "pit_loss": [20.0] * 12 + [21.0] * 12,
        }
    )
    per = per_circuit_summary(data, min_stops=10)
    comp = season_comparison(per)
    assert not comp.empty
    assert round(comp.loc["Silverstone", "diff"], 1) == 1.0
