import numpy as np
import pandas as pd

from analytics.degradation_v2 import fit_within_stint


def test_within_stint_recovers_net_slope_despite_stint_level_differences():
    rng = np.random.default_rng(1)
    rows = []
    for session in (1, 2):
        for driver in range(1, 11):
            for stint in (1, 2):
                level = rng.normal(0, 2.0)
                start = 1 + (stint - 1) * 25
                for lap in range(start, start + 20):
                    t = 90 + level + 0.02 * lap + rng.normal(0, 0.1)
                    rows.append((session, driver, stint, lap, "HARD", t))
    df = pd.DataFrame(rows, columns=["session_id", "driver_id", "stint_number",
                                     "lap_number", "tyre_compound", "lap_time_seconds"])
    out = fit_within_stint(df, min_laps=50).iloc[0]
    assert abs(out["net_s_per_lap"] - 0.02) < 0.005
