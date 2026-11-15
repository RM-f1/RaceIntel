"""Within-stint pace trend (degradation v2).

Demeans lap time and lap number inside each (race, driver, stint), so only
within-stint change remains. Within a stint tyre age and lap number are
perfectly collinear, so the slope is a NET pace trend (wear + fuel burn +
track evolution). Wear-only = net slope + assumed fuel effect (s/lap, positive).
SEs clustered by (race, driver).
"""

import numpy as np
import pandas as pd


def fit_within_stint(clean, min_laps=200, fuel_assumptions=(0.03, 0.05, 0.07)):
    rows = []
    for compound, g in clean.groupby("tyre_compound"):
        if len(g) < min_laps:
            continue
        key = (
            g["session_id"].astype(str) + "-" + g["driver_id"].astype(str)
            + "-" + g["stint_number"].astype(str)
        )
        data = g[["lap_time_seconds", "lap_number"]].astype(float)
        data = data - data.groupby(key.values).transform("mean")
        x = data[["lap_number"]].to_numpy()
        y = data["lap_time_seconds"].to_numpy()
        beta = float((x[:, 0] @ y) / (x[:, 0] @ x[:, 0]))
        resid = y - x[:, 0] * beta
        codes = pd.factorize(g["session_id"].astype(str) + "-" + g["driver_id"].astype(str))[0]
        bread = 1.0 / float(x[:, 0] @ x[:, 0])
        scores = pd.Series(x[:, 0] * resid).groupby(codes).sum().to_numpy()
        se = float(np.sqrt(bread * (scores @ scores) * bread))
        row = {
            "compound": compound,
            "laps": len(g),
            "stints": key.nunique(),
            "net_s_per_lap": beta,
            "net_se": se,
        }
        for f in fuel_assumptions:
            row["wear_if_fuel_%.2f" % f] = beta + f
        rows.append(row)
    return pd.DataFrame(rows)
