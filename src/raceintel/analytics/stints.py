"""Stint derivation from lap data.

A new stint starts when the tyre compound changes, or when the
(tyre_age - lap_number) offset changes (a different set was fitted).
Rows with a missing tyre age are kept: if a later row shows a new set,
the null-age rows directly before it belong to the new stint (typically
the out-lap). Does not rely on is_pit_out_lap, which is missing for 2024.
"""

import pandas as pd

VALID_COMPOUNDS = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")


def normalise_compound(raw):
    """Upper-case compound from VALID_COMPOUNDS, or None for anything else."""
    if raw is None or pd.isna(raw):
        return None
    c = str(raw).strip().upper()
    return c if c in VALID_COMPOUNDS else None


def assign_stint_numbers(laps: pd.DataFrame) -> pd.DataFrame:
    """Clean laps and add a stint_number column.

    laps needs: driver_id, lap_number, tyre_compound, tyre_age_laps.
    If session_id is present, stints are derived per (session, driver);
    without it, pass one session at a time.
    """
    keys = ["session_id", "driver_id"] if "session_id" in laps.columns else ["driver_id"]
    df = laps.copy()
    comp = df["tyre_compound"].astype("string").str.strip().str.upper()
    df = df[comp.isin(VALID_COMPOUNDS)].copy()
    df["tyre_compound"] = df["tyre_compound"].astype(str).str.strip().str.upper()
    df = df.sort_values(keys + ["lap_number"]).reset_index(drop=True)

    stint_ids = []
    for _, g in df.groupby(keys, sort=False):
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
    return df


def derive_stints(laps: pd.DataFrame) -> pd.DataFrame:
    df = assign_stint_numbers(laps)
    keys = (["session_id"] if "session_id" in df.columns else []) + ["driver_id", "stint_number"]
    out = (
        df.groupby(keys)
        .agg(
            tyre_compound=("tyre_compound", "first"),
            start_lap=("lap_number", "min"),
            end_lap=("lap_number", "max"),
            laps=("lap_number", "count"),
            start_tyre_age=("tyre_age_laps", "first"),
        )
        .reset_index()
    )
    out["span_laps"] = out["end_lap"] - out["start_lap"] + 1
    return out