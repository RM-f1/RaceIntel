"""Build pre-fitted analytics artifacts and write to artifacts/raceintel_artifacts.json.

Fits within-stint net degradation slopes (per season, per compound) using the
v2 degradation model (analytics.degradation_v2.fit_within_stint), computes
per-circuit pit-loss medians, and derives the 95th-percentile stint length per
compound.

Output schema
-------------
{
  "metadata": {
    "build_date": "YYYY-MM-DD",
    "sign_convention": "positive = slower (degradation costs time)",
    "note": "..."
  },
  "degradation": [
    {
      "season": int,
      "compound": str,
      "slope": float,     # net_s_per_lap (s / lap within stint)
      "se": float,        # net_se (clustered standard error on slope)
      "n": int            # number of clean laps used
    }, ...
  ],
  "pit_loss": [
    {
      "season": int,
      "race": str,
      "median_pit_loss_s": float,
      "n_stops": int
    }, ...
  ],
  "stint_p95": [
    {
      "compound": str,
      "season": int,
      "p95_stint_length": float   # 95th-percentile span_laps across all races
    }, ...
  ]
}
"""

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raceintel.analytics.degradation import build_clean_laps
from raceintel.analytics.degradation_v2 import fit_within_stint
from raceintel.analytics.pit_loss import compute_pit_losses, per_circuit_summary
from raceintel.analytics.stints import derive_stints

DB_PATH = Path("data/raceintel.db")
OUT_PATH = Path("artifacts/raceintel_artifacts.json")


def build_artifacts_from_laps(
    laps: pd.DataFrame,
    min_laps: int = 200,
    min_stops: int = 10,
) -> dict:
    """Build the artifacts dictionary from a Race-session laps DataFrame."""
    deg_rows = []
    for season, sg in laps.groupby("season_year"):
        clean = build_clean_laps(sg)
        result = fit_within_stint(clean, min_laps=min_laps)
        if result.empty:
            continue
        for _, row in result.iterrows():
            deg_rows.append(
                {
                    "season": int(season),
                    "compound": str(row["compound"]),
                    "slope": float(round(row["net_s_per_lap"], 6)),
                    "se": float(round(row["net_se"], 6)),
                    "n": int(row["laps"]),
                }
            )

    pit_df = compute_pit_losses(laps)
    per = per_circuit_summary(pit_df, min_stops=min_stops)
    pit_rows = []
    for (season, race), row in per.iterrows():
        pit_rows.append(
            {
                "season": int(season),
                "race": str(race),
                "median_pit_loss_s": float(round(row["median"], 3)),
                "n_stops": int(row["stops"]),
            }
        )

    stint_rows = []
    for season, sg in laps.groupby("season_year"):
        stints = derive_stints(sg)
        for compound, cg in stints.groupby("tyre_compound"):
            p95 = float(cg["span_laps"].quantile(0.95))
            stint_rows.append(
                {
                    "compound": str(compound),
                    "season": int(season),
                    "p95_stint_length": float(round(p95, 1)),
                }
            )

    return {
        "metadata": {
            "build_date": date.today().isoformat(),
            "sign_convention": "positive = slower (degradation costs time)",
            "note": (
                "Within-stint net pace trends (degradation v2): demeaned within each "
                "(race, driver, stint). Includes tyre wear, fuel burn, and track evolution; "
                "pure tyre wear = net slope + assumed fuel effect (s/lap)."
            ),
        },
        "degradation": deg_rows,
        "pit_loss": pit_rows,
        "stint_p95": stint_rows,
    }


def main() -> None:
    print("Connecting to", DB_PATH)
    conn = sqlite3.connect(f"file:{DB_PATH.resolve().as_posix()}?mode=ro", uri=True)

    laps = pd.read_sql(
        """
        SELECT
            l.session_id, l.driver_id, l.lap_number,
            l.tyre_compound, l.tyre_age_laps, l.lap_time_seconds,
            s.season_year, e.event_name
        FROM laps l
        JOIN sessions ss ON ss.session_id = l.session_id
        JOIN events e    ON e.event_id    = ss.event_id
        JOIN seasons s   ON s.season_id   = e.season_id
        WHERE ss.session_type = 'Race'
        """,
        conn,
    )
    conn.close()

    print(f"Loaded {len(laps):,} lap rows covering seasons: {sorted(laps['season_year'].unique())}")

    artifacts = build_artifacts_from_laps(laps)
    deg_rows = artifacts["degradation"]
    pit_rows = artifacts["pit_loss"]
    stint_rows = artifacts["stint_p95"]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(artifacts, indent=2), encoding="utf-8")
    print(f"\nArtifacts written to {OUT_PATH}")
    print(f"  degradation records : {len(deg_rows)}")
    print(f"  pit_loss records    : {len(pit_rows)}")
    print(f"  stint_p95 records   : {len(stint_rows)}")

    print("\n--- Slope comparison (artifact vs live degradation_v2 fit) ---")
    print(f"{'season':>6}  {'compound':>8}  {'artifact slope':>14}  {'live v2 slope':>13}  {'match?':>6}")
    deg_lookup = {(r["season"], r["compound"]): r["slope"] for r in deg_rows}
    for season, sg in laps.groupby("season_year"):
        clean = build_clean_laps(sg)
        live = fit_within_stint(clean)
        for _, row in live.iterrows():
            key = (int(season), str(row["compound"]))
            art = deg_lookup.get(key)
            live_slope = float(round(row["net_s_per_lap"], 6))
            match = "YES" if art is not None and abs(art - live_slope) < 1e-9 else "NO"
            print(f"{season:>6}  {row['compound']:>8}  {art!s:>14}  {live_slope:>13}  {match:>6}")


if __name__ == "__main__":
    main()
