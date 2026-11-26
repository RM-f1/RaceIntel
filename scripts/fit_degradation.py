import sys, sqlite3
import pandas as pd

sys.path.insert(0, "src")
from raceintel.analytics.degradation import build_clean_laps, fit_degradation

c = sqlite3.connect("data/raceintel.db")
laps = pd.read_sql(
    """select l.session_id, l.driver_id, l.lap_number, l.tyre_compound,
              l.tyre_age_laps, l.lap_time_seconds, s.season_year
       from laps l
       join sessions ss on ss.session_id = l.session_id
       join events e on e.event_id = ss.event_id
       join seasons s on s.season_id = e.season_id
       where ss.session_type = 'Race'""",
    c,
)
pd.set_option("display.width", 200)
for year, g in laps.groupby("season_year"):
    clean = build_clean_laps(g)
    print("\n=== %d: %d laps in, %d kept after cleaning" % (year, len(g), len(clean)))
    print(fit_degradation(clean).round(4).to_string(index=False))
