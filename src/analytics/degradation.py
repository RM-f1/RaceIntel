"""Tyre degradation model (per season, per compound).

lap_time = race_effect + a * tyre_age + b * lap_number + error

Race effect is removed by demeaning within each race. Laps excluded: lap 1,
out-laps, in-laps, missing time/age, non-dry compounds, and laps slower than
slow_factor x the stint median (proxy for safety car and traffic laps).
Standard errors are clustered by (race, driver).
"""

import numpy as np
import pandas as pd

from analytics.stints import derive_stints

DRY_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")


def _clean_session(g, slow_factor):
    stints = derive_stints(g)
    if stints.empty:
        return g.iloc[0:0]
    laps = g.copy()
    laps["tyre_compound"] = laps["tyre_compound"].astype(str).str.upper()
    m = laps.merge(
        stints[["driver_id", "stint_number", "start_lap", "end_lap"]], on="driver_id"
    )
    m = m[(m["lap_number"] >= m["start_lap"]) & (m["lap_number"] <= m["end_lap"])]
    m = m[
        m["tyre_compound"].isin(DRY_COMPOUNDS)
        & m["lap_time_seconds"].notna()
        & m["tyre_age_laps"].notna()
        & (m["lap_number"] > 1)
        & (m["lap_number"] != m["start_lap"])
        & (m["lap_number"] != m["end_lap"])
    ].copy()
    med = m.groupby(["driver_id", "stint_number"])["lap_time_seconds"].transform("median")
    return m[m["lap_time_seconds"] <= slow_factor * med]


def build_clean_laps(laps, slow_factor=1.07):
    """laps needs: session_id, driver_id, lap_number, tyre_compound,
    tyre_age_laps, lap_time_seconds. Use Race sessions only."""
    parts = [_clean_session(g, slow_factor) for _, g in laps.groupby("session_id")]
    return pd.concat(parts, ignore_index=True) if parts else laps.iloc[0:0]


def _cluster_se(x, resid, codes):
    bread = np.linalg.inv(x.T @ x)
    scores = pd.DataFrame(x * resid[:, None]).groupby(codes).sum().to_numpy()
    return np.sqrt(np.diag(bread @ (scores.T @ scores) @ bread))


def fit_degradation(clean, min_laps=200):
    rows = []
    cols = ["lap_time_seconds", "tyre_age_laps", "lap_number"]
    for compound, g in clean.groupby("tyre_compound"):
        if len(g) < min_laps:
            continue
        data = g[cols].astype(float)
        data = data - data.groupby(g["session_id"]).transform("mean")
        x = data[["tyre_age_laps", "lap_number"]].to_numpy()
        y = data["lap_time_seconds"].to_numpy()
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
        resid = y - x @ beta
        codes = pd.factorize(g["session_id"].astype(str) + "-" + g["driver_id"].astype(str))[0]
        se = _cluster_se(x, resid, codes)
        rows.append(
            {
                "compound": compound,
                "laps": len(g),
                "races": g["session_id"].nunique(),
                "deg_s_per_lap": beta[0],
                "deg_se": se[0],
                "fuel_s_per_lap": beta[1],
                "fuel_se": se[1],
                "corr_age_lap": np.corrcoef(x[:, 0], x[:, 1])[0, 1],
            }
        )
    return pd.DataFrame(rows)
