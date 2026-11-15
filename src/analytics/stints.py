"""Stint derivation from lap data.

A new stint starts when the tyre compound changes, or when the
(tyre_age - lap_number) offset changes (a different set was fitted).
Rows with a missing tyre age are kept: if a later row shows a new set,
the null-age rows directly before it belong to the new stint (typically
the out-lap). Does not rely on is_pit_out_lap, which is missing for 2024.
"""

import pandas as pd


def derive_stints(laps: pd.DataFrame) -> pd.DataFrame:
    """laps needs: driver_id, lap_number, tyre_compound, tyre_age_laps."""
    df = laps.copy()
    comp = df["tyre_compound"].astype("string").str.upper()
    df = df[comp.notna() & (comp != "NONE")].copy()
    df["tyre_compound"] = df["tyre_compound"].astype(str).str.upper()
    df = df.sort_values(["driver_id", "lap_number"]).reset_index(drop=True)

    stint_ids = []
    for _, g in df.groupby("driver_id", sort=False):
        ids = []
        sid = 0
        prev_comp = None
        prev_off = None
        nulls = 0
        for c, age, lap in zip(g["tyre_compound"], g["tyre_age_laps"], g["lap_number"]):
            off = None if pd.isna(age) else age - lap
            if prev_comp is None:
                sid = 1
            elif c != prev_comp:
                sid += 1
                nulls = 0
                prev_off = None
            elif off is not None and prev_off is not None and off != prev_off:
                sid += 1
                for k in range(1, nulls + 1):
                    ids[-k] = sid
            if off is None:
                nulls += 1
            else:
                nulls = 0
                prev_off = off
            ids.append(sid)
            prev_comp = c
        stint_ids.extend(ids)

    df["stint_number"] = stint_ids

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
