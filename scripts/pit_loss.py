"""Pit-loss estimates per race.  Thin runner over analytics.pit_loss.

Prints: total stops measured, clean stops, per-circuit table,
        not-reported circuits, and the 2022 vs 2024 comparison.
"""

import sys
import sqlite3

import pandas as pd

sys.path.insert(0, "src")

from raceintel.analytics.pit_loss import compute_pit_losses, per_circuit_summary, season_comparison

c = sqlite3.connect("data/raceintel.db")
laps = pd.read_sql(
    """select l.session_id, l.driver_id, l.lap_number, l.tyre_compound,
              l.tyre_age_laps, l.lap_time_seconds, s.season_year, e.event_name
       from laps l
       join sessions ss on ss.session_id = l.session_id
       join events e on e.event_id = ss.event_id
       join seasons s on s.season_id = e.season_id
       where ss.session_type = 'Race'""",
    c,
)
c.close()

# ------------------------------------------------------------------
# Count total and clean stops to verify 914
# ------------------------------------------------------------------
# Re-run the counting logic identically to the original script so the
# total-measured / clean split is reproduced faithfully.
import numpy as np
from raceintel.analytics.stints import derive_stints

SLOW = 1.07
WET = {"INTERMEDIATE", "WET"}

counts: dict = {}
for sid, g in laps.groupby("session_id"):
    year = int(g["season_year"].iloc[0])
    name = g["event_name"].iloc[0]
    t = g[g["lap_time_seconds"].notna()].groupby("lap_number")["lap_time_seconds"]
    field = t.median()[t.count() >= 8]
    ref = field.rolling(15, center=True, min_periods=5).median()
    bad = set(field.index[field > SLOW * ref]) | {1}

    stats = counts.setdefault((year, name), [0, 0])
    stints = derive_stints(g)
    for did, sg in stints.groupby("driver_id"):
        dgf = g[g["driver_id"] == did].drop_duplicates("lap_number").set_index("lap_number")
        dg = dgf["lap_time_seconds"]
        comp = dgf["tyre_compound"].astype(str).str.upper()
        for start in sg.loc[sg["stint_number"] > 1, "start_lap"]:
            out_lap, in_lap = int(start), int(start) - 1
            t_in, t_out = dg.get(in_lap), dg.get(out_lap)
            if t_in is None or t_out is None or pd.isna(t_in) or pd.isna(t_out):
                continue
            before = dg.reindex(range(in_lap - 4, in_lap)).dropna()
            after = dg.reindex(range(out_lap + 1, out_lap + 5)).dropna()
            if len(before) < 3 or len(after) < 3:
                continue
            stats[0] += 1
            if set(range(in_lap - 4, out_lap + 5)) & bad:
                continue
            if comp.get(in_lap) in WET or comp.get(out_lap) in WET:
                continue
            stats[1] += 1

# ------------------------------------------------------------------
# Main outputs via the library functions
# ------------------------------------------------------------------
df = compute_pit_losses(laps)
per = per_circuit_summary(df, min_stops=10)
comp = season_comparison(per)

pd.set_option("display.width", 200)
print("stops measured:", sum(v[0] for v in counts.values()), " clean:", len(df))
print(per.round(1).to_string())

print("\nNot reported (fewer than 10 clean stops):")
for (y, n), (m, k) in sorted(counts.items()):
    if k < 10:
        print(y, n, "measured", m, "clean", k)

if not comp.empty:
    print("\nSame circuit, both seasons:")
    print(comp.round(1).to_string())
    print("median abs diff (s):", round(comp["diff"].abs().median(), 2))
