"""Pit-stop time-loss estimation from raw lap data.

loss = t_in_lap + t_out_lap - 2 * median(up to 4 laps before, up to 4 after).

A stop is excluded when:
- the in-lap or out-lap time is missing,
- fewer than 3 laps are available on either side of the window,
- any lap in the [in-4 … out+4] window falls on a neutralised lap
  (field median > SLOW * rolling field-median), or
- the in-lap or out-lap tyre compound is wet (INTERMEDIATE / WET).

Lap 1 is always treated as neutralised (formation lap / standing start).

Sign convention: positive pit_loss means the stop cost time (normal case).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from raceintel.analytics.stints import derive_stints

SLOW = 1.07
WET_COMPOUNDS = frozenset({"INTERMEDIATE", "WET"})


def _neutralised_laps(session_laps: pd.DataFrame) -> set[int]:
    """Return the set of lap numbers that are likely neutralised in a session.

    Uses the field-median lap time and a rolling reference; also always
    includes lap 1.
    """
    t = (
        session_laps[session_laps["lap_time_seconds"].notna()]
        .groupby("lap_number")["lap_time_seconds"]
    )
    field = t.median()[t.count() >= 8]
    ref = field.rolling(15, center=True, min_periods=5).median()
    bad = set(field.index[field > SLOW * ref])
    bad.add(1)
    return bad


def compute_pit_losses(laps: pd.DataFrame) -> pd.DataFrame:
    """Compute per-stop pit-loss estimates from a laps DataFrame.

    Parameters
    ----------
    laps:
        DataFrame with columns: session_id, driver_id, lap_number,
        tyre_compound, lap_time_seconds.  Optional: season_year, event_name
        (passed through to the output when present).

    Returns
    -------
    DataFrame with one row per clean green-flag stop and columns:
        season, race, driver_id, in_lap, pit_loss.
    ``season`` and ``race`` are ``None`` when the input lacks season_year /
    event_name.
    """
    rows: list[dict] = []

    for sid, g in laps.groupby("session_id"):
        year = int(g["season_year"].iloc[0]) if "season_year" in g.columns else None
        name = g["event_name"].iloc[0] if "event_name" in g.columns else None
        bad = _neutralised_laps(g)

        stints = derive_stints(g)
        for did, sg in stints.groupby("driver_id"):
            dgf = (
                g[g["driver_id"] == did]
                .drop_duplicates("lap_number")
                .set_index("lap_number")
            )
            dg = dgf["lap_time_seconds"]
            comp = dgf["tyre_compound"].astype(str).str.upper()

            for start in sg.loc[sg["stint_number"] > 1, "start_lap"]:
                out_lap = int(start)
                in_lap = out_lap - 1

                t_in = dg.get(in_lap)
                t_out = dg.get(out_lap)
                if t_in is None or t_out is None or pd.isna(t_in) or pd.isna(t_out):
                    continue

                before = dg.reindex(range(in_lap - 4, in_lap)).dropna()
                after = dg.reindex(range(out_lap + 1, out_lap + 5)).dropna()
                if len(before) < 3 or len(after) < 3:
                    continue

                if set(range(in_lap - 4, out_lap + 5)) & bad:
                    continue

                if comp.get(in_lap) in WET_COMPOUNDS or comp.get(out_lap) in WET_COMPOUNDS:
                    continue

                ref = float(np.median(np.concatenate([before.values, after.values])))
                rows.append(
                    {
                        "season": year,
                        "race": name,
                        "driver_id": did,
                        "in_lap": in_lap,
                        "pit_loss": float(t_in) + float(t_out) - 2 * ref,
                    }
                )

    if not rows:
        return pd.DataFrame(columns=["season", "race", "driver_id", "in_lap", "pit_loss"])
    return pd.DataFrame(rows)


def per_circuit_summary(
    pit_losses: pd.DataFrame,
    min_stops: int = 10,
) -> pd.DataFrame:
    """Aggregate pit losses to circuit level.

    Parameters
    ----------
    pit_losses:
        Output of :func:`compute_pit_losses`.
    min_stops:
        Circuits with fewer clean stops are excluded from the result.

    Returns
    -------
    DataFrame indexed by (season, race) with columns:
        stops, p25, median, p75.
    """
    if pit_losses.empty:
        return pd.DataFrame(columns=["stops", "p25", "median", "p75"])
    per = pit_losses.groupby(["season", "race"])["pit_loss"].agg(
        stops="count",
        p25=lambda s: s.quantile(0.25),
        median="median",
        p75=lambda s: s.quantile(0.75),
    )
    return per[per["stops"] >= min_stops]


def season_comparison(circuit_summary: pd.DataFrame) -> pd.DataFrame:
    """Compare 2022 vs 2024 median pit loss on circuits common to both seasons.

    Parameters
    ----------
    circuit_summary:
        Output of :func:`per_circuit_summary` (indexed by season, race).

    Returns
    -------
    DataFrame indexed by race with columns: 2022, 2024, diff.
    ``diff = median_2024 - median_2022`` (positive = slower stops in 2024).
    """
    good = circuit_summary["median"].unstack(0)
    if 2022 not in good.columns or 2024 not in good.columns:
        return pd.DataFrame()
    both = good[[2022, 2024]].dropna()
    both = both.copy()
    both["diff"] = both[2024] - both[2022]
    return both
