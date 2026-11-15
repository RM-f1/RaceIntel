"""Stint derivation from lap data.

A new stint starts when the tyre compound changes or tyre age drops
(a new set was fitted). Does not rely on is_pit_out_lap, which is
missing for 2024.
"""

import pandas as pd


def derive_stints(laps: pd.DataFrame) -> pd.DataFrame:
    """laps needs: driver_id, lap_number, tyre_compound, tyre_age_laps."""
    df = laps.copy()
    comp = df["tyre_compound"].astype("string").str.upper()
    df = df[comp.notna() & (comp != "NONE")].copy()
    df["tyre_compound"] = df["tyre_compound"].astype(str).str.upper()
    df = df[df["tyre_age_laps"].notna()].copy()
    df = df.sort_values(["driver_id", "lap_number"])

    grp = df.groupby("driver_id")
    prev_comp = grp["tyre_compound"].shift()
    prev_age = grp["tyre_age_laps"].shift()
    prev_lap = grp["lap_number"].shift()

    age_step = df["tyre_age_laps"] - prev_age
    lap_step = df["lap_number"] - prev_lap

    is_new = (
        prev_comp.isna()
        | (df["tyre_compound"] != prev_comp)
        | (age_step != lap_step)
    )
    df["stint_number"] = is_new.groupby(df["driver_id"]).cumsum()

    return (
        df.groupby(["driver_id", "stint_number"])
        .agg(
            tyre_compound=("tyre_compound", "first"),
            start_lap=("lap_number", "min"),
            end_lap=("lap_number", "max"),
            laps=("lap_number", "count"),
            start_tyre_age=("tyre_age_laps", "first"),
        )
        .reset_index()
    )
