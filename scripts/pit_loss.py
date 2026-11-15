"""Pit-loss estimate per race: green-flag stops only.

loss = in_lap + out_lap - 2 * median(4 laps before, 4 laps after).
Stops are dropped if any lap in the window is neutralised (field median
lap time > 1.07x the rolling field median), or on wet/intermediate tyres.
"""
import sys, sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from analytics.stints import derive_stints

SLOW = 1.07
WET = {"INTERMEDIATE", "WET"}

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


def neutralised_laps(g):
    t = g[g["lap_time_seconds"].notna()].groupby("lap_number")["lap_time_seconds"]
    field = t.median()[t.count() >= 8]
    ref = field.rolling(15, center=True, min_periods=5).median()
    return set(field.index[field > SLOW * ref])


rows = []
counts = {}
for sid, g in laps.groupby("session_id"):
    year = int(g["season_year"].iloc[0])
    name = g["event_name"].iloc[0]
    bad = neutralised_laps(g) | {1}
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
            ref = float(np.median(np.concatenate([before.values, after.values])))
            rows.append((year, name, did, in_lap, t_in + t_out - 2 * ref))

df = pd.DataFrame(rows, columns=["season", "race", "driver_id", "in_lap", "pit_loss"])
pd.set_option("display.width", 200)
per = df.groupby(["season", "race"])["pit_loss"].agg(
    stops="count",
    p25=lambda s: s.quantile(0.25),
    median="median",
    p75=lambda s: s.quantile(0.75),
)
print("stops measured:", sum(v[0] for v in counts.values()), " clean:", len(df))
print(per[per.stops >= 10].round(1).to_string())

print("\nNot reported (fewer than 10 clean stops):")
for (y, n), (m, k) in sorted(counts.items()):
    if k < 10:
        print(y, n, "measured", m, "clean", k)

good = per[per.stops >= 10]["median"].unstack(0)
if {2022, 2024} <= set(good.columns):
    both = good[[2022, 2024]].dropna()
    both["diff"] = both[2024] - both[2022]
    print("\nSame circuit, both seasons:")
    print(both.round(1).to_string())
    print("median abs diff (s):", round(both["diff"].abs().median(), 2))
