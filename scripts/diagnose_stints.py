import sys, sqlite3
import pandas as pd

sys.path.insert(0, "src")
from analytics.stints import derive_stints

c = sqlite3.connect("data/raceintel.db")
laps = pd.read_sql(
    """select l.session_id, l.driver_id, l.lap_number, l.tyre_compound,
              l.tyre_age_laps, l.is_pit_out_lap, s.season_year, e.event_name
       from laps l
       join sessions ss on ss.session_id = l.session_id
       join events e on e.event_id = ss.event_id
       join seasons s on s.season_id = e.season_id
       where ss.session_type = 'Race' and s.season_year = 2022""",
    c,
)

out = []
for sid, g in laps.groupby("session_id"):
    name = g["event_name"].iloc[0]
    stints = derive_stints(g)
    starts = {(r.driver_id, r.start_lap) for r in stints[stints.stint_number > 1].itertuples()}
    g = g.sort_values(["driver_id", "lap_number"])
    for did, dg in g.groupby("driver_id"):
        dg = dg.reset_index(drop=True)
        for i, r in dg.iterrows():
            if r.is_pit_out_lap != 1 or r.lap_number <= 1:
                continue
            if (did, r.lap_number) in starts:
                continue
            if i == 0:
                cat = "no previous row"
            else:
                p = dg.loc[i - 1]
                if pd.isna(r.tyre_age_laps):
                    cat = "tyre age null on out-lap"
                elif str(r.tyre_compound).upper() in ("NONE", "NAN"):
                    cat = "compound missing"
                elif (r.tyre_compound == p.tyre_compound
                      and (r.tyre_age_laps - p.tyre_age_laps) == (r.lap_number - p.lap_number)):
                    cat = "same tyre carried on"
                else:
                    cat = "other"
            out.append((name, cat))

df = pd.DataFrame(out, columns=["race", "category"])
print("missed flagged pit-outs:", len(df))
print(df.category.value_counts().to_string())
print()
print(pd.crosstab(df.race, df.category).to_string())
