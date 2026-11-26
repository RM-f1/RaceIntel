"""Conditional, degradation-based 1-stop pit-window estimator.

This module estimates a feasible 1-stop pit window for a **supplied**
compound sequence (``compound_1 -> compound_2``) using pre-fitted
degradation v2 net slopes, empirical 95th-percentile stint caps, and
circuit-specific median pit loss.

Scope & Limitations
-------------------
- **Conditional estimator**: Evaluates only a fixed 1-stop on the supplied
  ``compound_1 -> compound_2`` sequence. It does **not** select optimal
  compounds or compare 0-stop vs 1-stop vs 2-stop strategies.
- **No compound base-pace offsets**: Artifacts do not include lap-0 pace
  deltas between compounds, so no synthetic base-pace offsets are invented.
- **Global fuel progression**: Fuel burn ``-fuel_effect * (t - 1)`` depends
  only on global race lap ``t`` and does not reset at a pit stop. Summed over
  the race, ``C_fuel = -fuel_effect * N * (N - 1) / 2`` is invariant to the
  pit lap ``L``. The fuel assumption enters through inferred pure tyre wear:
  ``w_c(phi) = net_slope_c + phi``.
- **Constant pit loss**: In a fixed 1-stop comparison, ``pit_loss_s`` is
  constant across pit laps ``L`` and does not independently shift ``optimal_lap``.
- **Empirical stint caps**: ``p95_stint_length`` values are treated as
  observed empirical limits, not physical tyre-life limits.

Mathematical Objective
----------------------
For race length ``N = total_laps`` and pit stop after lap ``L`` (stint 1 of
length ``L`` on ``compound_1``, stint 2 of length ``N - L`` on ``compound_2``):

    D_1(L; phi) = 0.5 * w_1(phi) * L * (L - 1)
    D_2(L; phi) = 0.5 * w_2(phi) * (N - L) * (N - L - 1)
    J(L; phi)   = D_1(L; phi) + D_2(L; phi)
    T_rel(L)    = J(L; phi) + C_fuel(N; phi) + pit_loss_s

Feasible integer pit laps are ``L in [L_min, L_max]`` where:

    L_min = max(1, N - floor(cap_2))
    L_max = min(N - 1, floor(cap_1))

Tie-breaking: when multiple feasible laps share the global constrained minimum
``J(L)`` (within ``1e-12``), the earliest such lap is selected as ``optimal_lap``.
The primary pit window ``[earliest_lap, latest_lap]`` is the maximal contiguous
tolerance-qualified interval (``J(L) - min_J <= window_tolerance_s``) that
contains ``optimal_lap``. Any other disconnected tolerance-qualified intervals
are reported separately in ``alternate_windows``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from raceintel.analytics.artifacts import load_artifacts

DEFAULT_FUEL_EFFECT = 0.05
SENSITIVITY_FUEL_EFFECTS = (0.03, 0.05, 0.07)
DEFAULT_WINDOW_TOLERANCE_S = 0.5
_TIE_EPS = 1e-12


def _normalise_compound_name(compound: str) -> str:
    if not isinstance(compound, str) or not compound.strip():
        raise ValueError("Compound name must be a non-empty string.")
    return compound.strip().upper()


def _lookup_degradation_record(
    degradation_records: list[dict[str, Any]],
    season: int,
    compound: str,
) -> dict[str, Any]:
    for rec in degradation_records:
        if int(rec["season"]) == int(season) and str(rec["compound"]).upper() == compound:
            return rec
    available = sorted(
        {str(r["compound"]).upper() for r in degradation_records if int(r["season"]) == int(season)}
    )
    raise ValueError(
        f"No degradation record for season={season}, compound={compound!r}. "
        f"Available compounds for {season}: {available}"
    )


def _lookup_stint_cap(
    stint_p95_records: list[dict[str, Any]],
    season: int,
    compound: str,
) -> float:
    for rec in stint_p95_records:
        if int(rec["season"]) == int(season) and str(rec["compound"]).upper() == compound:
            cap = float(rec["p95_stint_length"])
            if not math.isfinite(cap) or cap < 1.0:
                raise ValueError(
                    f"Invalid p95_stint_length={cap} for season={season}, compound={compound!r}."
                )
            return cap
    available = sorted(
        {str(r["compound"]).upper() for r in stint_p95_records if int(r["season"]) == int(season)}
    )
    raise ValueError(
        f"No stint_p95 record for season={season}, compound={compound!r}. "
        f"Available compounds for {season}: {available}"
    )


def _lookup_pit_loss(
    pit_loss_records: list[dict[str, Any]],
    season: int,
    race: str,
) -> dict[str, Any]:
    if not isinstance(race, str) or not race.strip():
        raise ValueError("Race name must be a non-empty string.")
    target = race.strip().casefold()
    for rec in pit_loss_records:
        if int(rec["season"]) == int(season) and str(rec["race"]).strip().casefold() == target:
            return rec
    available = sorted(
        {str(r["race"]) for r in pit_loss_records if int(r["season"]) == int(season)}
    )
    raise ValueError(
        f"No pit_loss record for season={season}, race={race!r}. "
        f"Available races for {season}: {available}"
    )


def _cumulative_stint_deg(wear_per_lap: float, stint_laps: int) -> float:
    """Cumulative tyre-age degradation sum_{a=0}^{L-1} w * a."""
    return 0.5 * wear_per_lap * stint_laps * (stint_laps - 1)


def _contiguous_intervals(laps: list[int]) -> list[tuple[int, int]]:
    """Group a sorted list of integer laps into maximal contiguous [start, end] spans."""
    if not laps:
        return []
    intervals: list[tuple[int, int]] = []
    start = prev = laps[0]
    for lap in laps[1:]:
        if lap == prev + 1:
            prev = lap
        else:
            intervals.append((start, prev))
            start = prev = lap
    intervals.append((start, prev))
    return intervals


def _solve_for_fuel(
    total_laps: int,
    slope_1: float,
    slope_2: float,
    cap_1: float,
    cap_2: float,
    pit_loss_s: float,
    fuel_effect: float,
    window_tolerance_s: float,
) -> dict[str, Any]:
    wear_1 = slope_1 + fuel_effect
    wear_2 = slope_2 + fuel_effect

    cap_1_int = int(math.floor(cap_1))
    cap_2_int = int(math.floor(cap_2))
    l_min = max(1, total_laps - cap_2_int)
    l_max = min(total_laps - 1, cap_1_int)

    if l_min > l_max:
        raise ValueError(
            f"1-stop strategy is infeasible for total_laps={total_laps} under observed P95 caps "
            f"(cap_1={cap_1}, cap_2={cap_2}; max combined laps={cap_1_int + cap_2_int})."
        )

    feasible_laps = list(range(l_min, l_max + 1))
    costs = {
        lap: _cumulative_stint_deg(wear_1, lap) + _cumulative_stint_deg(wear_2, total_laps - lap)
        for lap in feasible_laps
    }
    min_cost = min(costs.values())
    # Deterministic tie-breaking: earliest feasible lap achieving min_cost.
    tied_min_laps = [lap for lap in feasible_laps if abs(costs[lap] - min_cost) <= _TIE_EPS]
    optimal_lap = tied_min_laps[0]

    qualified_laps = [
        lap for lap in feasible_laps if (costs[lap] - min_cost) <= window_tolerance_s + _TIE_EPS
    ]
    intervals = _contiguous_intervals(qualified_laps)

    primary_interval: tuple[int, int] | None = None
    alternate_intervals: list[tuple[int, int]] = []
    for a, b in intervals:
        if a <= optimal_lap <= b:
            primary_interval = (a, b)
        else:
            alternate_intervals.append((a, b))

    if primary_interval is None:  # pragma: no cover - defensive; optimal_lap always qualifies
        primary_interval = (optimal_lap, optimal_lap)

    earliest_lap, latest_lap = primary_interval

    # Check whether empirical caps constrained the unconstrained optimum [1, total_laps - 1].
    all_laps = list(range(1, total_laps))
    all_costs = {
        lap: _cumulative_stint_deg(wear_1, lap) + _cumulative_stint_deg(wear_2, total_laps - lap)
        for lap in all_laps
    }
    unc_min_cost = min(all_costs.values())
    unc_optimal_lap = next(
        lap for lap in all_laps if abs(all_costs[lap] - unc_min_cost) <= _TIE_EPS
    )

    hit_stint_1_cap = unc_optimal_lap > l_max or latest_lap == cap_1_int and total_laps - 1 > cap_1_int
    hit_stint_2_cap = unc_optimal_lap < l_min or earliest_lap == (total_laps - cap_2_int) and 1 < (total_laps - cap_2_int)

    if hit_stint_1_cap and hit_stint_2_cap:
        binding_cap: str | None = "both"
    elif hit_stint_1_cap:
        binding_cap = "stint_1_cap"
    elif hit_stint_2_cap:
        binding_cap = "stint_2_cap"
    else:
        binding_cap = None

    cap_constrained = binding_cap is not None
    global_fuel_cost_s = -0.5 * fuel_effect * total_laps * (total_laps - 1)

    return {
        "fuel_effect_s_per_lap": round(fuel_effect, 6),
        "wear_per_lap": {
            "compound_1": round(wear_1, 6),
            "compound_2": round(wear_2, 6),
        },
        "optimal_lap": optimal_lap,
        "unconstrained_optimal_lap": unc_optimal_lap,
        "earliest_lap": earliest_lap,
        "latest_lap": latest_lap,
        "alternate_windows": [
            {"earliest_lap": a, "latest_lap": b} for a, b in alternate_intervals
        ],
        "feasible_range": {"min_lap": l_min, "max_lap": l_max},
        "cap_constrained": cap_constrained,
        "binding_cap": binding_cap,
        "tied_optimal_laps": tied_min_laps,
        "objective": {
            "stint_degradation_cost_s": round(min_cost, 4),
            "global_fuel_cost_s": round(global_fuel_cost_s, 4),
            "pit_loss_s": round(pit_loss_s, 3),
            "total_relative_cost_s": round(min_cost + global_fuel_cost_s + pit_loss_s, 4),
        },
    }


def compute_pit_window(
    total_laps: int,
    compound_1: str,
    compound_2: str,
    degradation_records: list[dict[str, Any]],
    stint_p95_records: list[dict[str, Any]],
    pit_loss_s: float,
    season: int = 2024,
    fuel_effect: float = DEFAULT_FUEL_EFFECT,
    sensitivity_fuels: tuple[float, ...] = SENSITIVITY_FUEL_EFFECTS,
    window_tolerance_s: float = DEFAULT_WINDOW_TOLERANCE_S,
) -> dict[str, Any]:
    """Compute a conditional 1-stop pit window and fuel-sensitivity table.

    Parameters
    ----------
    total_laps:
        Total race distance in laps (must be >= 2).
    compound_1, compound_2:
        Dry tyre compounds for stint 1 and stint 2.
    degradation_records, stint_p95_records:
        Artifact record lists matching ``analytics.artifacts`` schema.
    pit_loss_s:
        Circuit median pit-loss in seconds (must be > 0).
    season:
        Season year key used to look up degradation and stint_p95 records.
    fuel_effect:
        Assumed global fuel-burn pace improvement in s/lap (>= 0).
    sensitivity_fuels:
        Fuel assumptions to evaluate in the sensitivity table.
    window_tolerance_s:
        Allowable degradation-cost delta above the constrained minimum (>= 0).
    """
    if isinstance(total_laps, bool) or not isinstance(total_laps, int) or total_laps < 2:
        raise ValueError(f"total_laps must be an integer >= 2, got {total_laps!r}.")
    if not isinstance(pit_loss_s, (int, float)) or isinstance(pit_loss_s, bool) or not math.isfinite(pit_loss_s) or pit_loss_s <= 0:
        raise ValueError(f"pit_loss_s must be a positive finite number, got {pit_loss_s!r}.")
    if not isinstance(fuel_effect, (int, float)) or isinstance(fuel_effect, bool) or not math.isfinite(fuel_effect) or fuel_effect < 0:
        raise ValueError(f"fuel_effect must be a finite number >= 0, got {fuel_effect!r}.")
    if not isinstance(window_tolerance_s, (int, float)) or isinstance(window_tolerance_s, bool) or not math.isfinite(window_tolerance_s) or window_tolerance_s < 0:
        raise ValueError(f"window_tolerance_s must be a finite number >= 0, got {window_tolerance_s!r}.")

    c1 = _normalise_compound_name(compound_1)
    c2 = _normalise_compound_name(compound_2)

    deg_1 = _lookup_degradation_record(degradation_records, season, c1)
    deg_2 = _lookup_degradation_record(degradation_records, season, c2)
    cap_1 = _lookup_stint_cap(stint_p95_records, season, c1)
    cap_2 = _lookup_stint_cap(stint_p95_records, season, c2)

    slope_1 = float(deg_1["slope"])
    slope_2 = float(deg_2["slope"])
    if not (math.isfinite(slope_1) and math.isfinite(slope_2)):
        raise ValueError("Degradation slopes must be finite numbers.")

    primary = _solve_for_fuel(
        total_laps=total_laps,
        slope_1=slope_1,
        slope_2=slope_2,
        cap_1=cap_1,
        cap_2=cap_2,
        pit_loss_s=float(pit_loss_s),
        fuel_effect=float(fuel_effect),
        window_tolerance_s=float(window_tolerance_s),
    )

    sensitivity = []
    for f in sensitivity_fuels:
        if not isinstance(f, (int, float)) or isinstance(f, bool) or not math.isfinite(f) or f < 0:
            raise ValueError(f"Sensitivity fuel_effect must be >= 0, got {f!r}.")
        sensitivity.append(
            _solve_for_fuel(
                total_laps=total_laps,
                slope_1=slope_1,
                slope_2=slope_2,
                cap_1=cap_1,
                cap_2=cap_2,
                pit_loss_s=float(pit_loss_s),
                fuel_effect=float(f),
                window_tolerance_s=float(window_tolerance_s),
            )
        )

    return {
        "model": "conditional_1stop_degradation_v2",
        "scope_note": (
            "Conditional 1-stop pit-window estimate for the supplied compound sequence. "
            "Assumes global linear fuel progression, no compound lap-0 pace offsets, "
            "constant pit loss, and empirical P95 observed stint caps."
        ),
        "season": int(season),
        "total_laps": total_laps,
        "compounds": {
            "stint_1": {
                "compound": c1,
                "net_slope_s_per_lap": slope_1,
                "p95_stint_cap_laps": cap_1,
            },
            "stint_2": {
                "compound": c2,
                "net_slope_s_per_lap": slope_2,
                "p95_stint_cap_laps": cap_2,
            },
        },
        "pit_loss_s": round(float(pit_loss_s), 3),
        "fuel_assumptions": {
            "default_s_per_lap": DEFAULT_FUEL_EFFECT,
            "applied_s_per_lap": float(fuel_effect),
            "sensitivity_s_per_lap": [float(f) for f in sensitivity_fuels],
        },
        "window_tolerance_s": float(window_tolerance_s),
        "tie_break_rule": "earliest_minimum_cost_lap",
        "recommendation": primary,
        "sensitivity": sensitivity,
    }


def recommend_pit_window_from_artifacts(
    race: str,
    total_laps: int,
    compound_1: str = "SOFT",
    compound_2: str = "HARD",
    season: int = 2024,
    fuel_effect: float = DEFAULT_FUEL_EFFECT,
    sensitivity_fuels: tuple[float, ...] = SENSITIVITY_FUEL_EFFECTS,
    window_tolerance_s: float = DEFAULT_WINDOW_TOLERANCE_S,
    artifacts_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load artifacts and compute a conditional 1-stop pit window for a circuit."""
    artifacts = load_artifacts(artifacts_path)
    pit_rec = _lookup_pit_loss(artifacts["pit_loss"], season, race)
    result = compute_pit_window(
        total_laps=total_laps,
        compound_1=compound_1,
        compound_2=compound_2,
        degradation_records=artifacts["degradation"],
        stint_p95_records=artifacts["stint_p95"],
        pit_loss_s=float(pit_rec["median_pit_loss_s"]),
        season=season,
        fuel_effect=fuel_effect,
        sensitivity_fuels=sensitivity_fuels,
        window_tolerance_s=window_tolerance_s,
    )
    result["race"] = str(pit_rec["race"])
    result["pit_loss_n_stops"] = int(pit_rec["n_stops"])
    return result


if __name__ == "__main__":
    import json

    example = recommend_pit_window_from_artifacts(
        race="Bahrain Grand Prix",
        total_laps=57,
        compound_1="SOFT",
        compound_2="HARD",
        season=2024,
    )
    print(json.dumps(example, indent=2))
