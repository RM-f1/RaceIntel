import numpy as np
import pandas as pd

from analytics.degradation import fit_degradation


def test_recovers_known_degradation_and_fuel_effect():
    rng = np.random.default_rng(0)
    rows = []
    for session in (1, 2, 3):
        base = 80 + 10 * session
        for driver in range(1, 11):
            pit = int(rng.integers(15, 36))
            for lap in range(pit + 1, 61):
                age = lap - pit
                t = base + 0.05 * age - 0.03 * lap + rng.normal(0, 0.1)
                rows.append((session, driver, lap, "HARD", age, t))
    df = pd.DataFrame(
        rows,
        columns=["session_id", "driver_id", "lap_number", "tyre_compound",
                 "tyre_age_laps", "lap_time_seconds"],
    )
    out = fit_degradation(df, min_laps=50).iloc[0]
    assert abs(out["deg_s_per_lap"] - 0.05) < 0.01
    assert abs(out["fuel_s_per_lap"] + 0.03) < 0.01
