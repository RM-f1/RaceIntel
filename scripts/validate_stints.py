import sys
import sqlite3
import pandas as pd

sys.path.insert(0, "src")
from raceintel.analytics.stints import derive_stints

c = sqlite3.connect("data/raceintel.db")
laps = pd.read_sql(
    """select l.session_id, l.driver_id, l.lap_number, l.tyre_compound,
              l.tyre_age_laps, l.is_pit_out_lap,
              s.season_year, e.event_name
       from laps l
       join sessions ss on ss.session_id = l.session_id
       join events e on e.event_id = ss.event_id
       join seasons s on s.season_id = e.season_id
       where ss.session_type = 'Race'""",
    c,
)

rows = []
stint_rate = {}
for sid, g in laps.groupby("session_id"):
    year = int(g["season_year"].iloc[0])
    name = g["event_name"].iloc[0]
    stints = derive_stints(g)
    n_drivers = max(g["driver_id"].nunique(), 1)
    stint_rate.setdefault(year, []).append(len(stints) / n_drivers)
    if year != 2022:
        continue
    tp_exact = tp_prec = tp_rec = n_found = n_flag = 0
    for did, sg in stints.groupby("driver_id"):
        found = set(sg.loc[sg["stint_number"] > 1, "start_lap"])
        dg = g[g["driver_id"] == did]
        flagged = set(dg.loc[(dg["is_pit_out_lap"] == 1) & (dg["lap_number"] > 1), "lap_number"])
        n_found += len(found)
        n_flag += len(flagged)
        tp_exact += len(found & flagged)
        tp_prec += sum(any(abs(a - b) <= 1 for b in flagged) for a in found)
        tp_rec += sum(any(abs(a - b) <= 1 for a in found) for b in flagged)
    rows.append((name, n_found, n_flag, tp_exact, tp_prec, tp_rec))

df = pd.DataFrame(rows, columns=["race", "found", "flagged", "exact", "prec_hits", "rec_hits"])
print("2022 races:", len(df))
print("found stint starts:", df.found.sum(), " flagged pit-outs:", df.flagged.sum())
print("exact matches:", df.exact.sum())
print("precision exact: %.1f%%  within1: %.1f%%" % (100 * df.exact.sum() / df.found.sum(), 100 * df.prec_hits.sum() / df.found.sum()))
print("recall    exact: %.1f%%  within1: %.1f%%" % (100 * df.exact.sum() / df.flagged.sum(), 100 * df.rec_hits.sum() / df.flagged.sum()))

df["gap"] = (df.found - df.flagged).abs()
print("\nWorst 5 races by |found - flagged|:")
print(df.sort_values("gap", ascending=False).head(5).to_string(index=False))

print("\nAverage stints per driver per race:")
for y, v in sorted(stint_rate.items()):
    print(y, round(sum(v) / len(v), 2), "(races: %d)" % len(v))
