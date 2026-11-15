"""
Read-only Analytics API router exposing RaceIntel's existing analytical
modules and season-level summaries cleanly over FastAPI without modifying
existing endpoint contracts.
"""

from __future__ import annotations

import hmac
import math
import os
from typing import Any

import pandas as pd
from fastapi import APIRouter, Header, HTTPException, Query

from analytics.pace import get_average_pace, get_lap_consistency
from analytics.position import get_classification_summary, get_position_changes
from analytics.tyre import get_compound_performance, get_stint_summary, get_tyre_usage
from analytics.weather import get_temperature_trend, get_wind_conditions
from database.connection import query_to_dataframe
from raceintel.data.ingest import run_ingest
from raceintel.data.status import (
    get_all_seasons_sync_summary,
    get_season_sync_status,
    is_worker_running,
)
from raceintel.services.pace_service import format_lap_time, get_fastest_lap_for_session, get_pace
from raceintel.services.race_service import get_race_report
from raceintel.services.standings_service import (
    get_constructor_championship,
    get_constructor_standings_after_event,
    get_driver_championship,
    get_driver_standings_after_event,
)
from raceintel.services.weather_service import get_weather_details

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


@router.get("/sync/status")
def get_sync_status(season: int | None = Query(default=None)):
    """Return synchronization summaries and background worker status."""
    running, pid = is_worker_running()
    summaries = get_all_seasons_sync_summary()
    detail = get_season_sync_status(season) if season else None
    return {
        "worker_running": running,
        "worker_pid": pid,
        "seasons": summaries,
        "detail": detail,
    }


@router.post("/sync")
def trigger_manual_sync(
    payload: dict[str, Any] | None = None,
    season: int = Query(default=2026),
    round_number: int | None = Query(default=None),
    incremental: bool = Query(default=True),
    force_refresh: bool = Query(default=False),
    admin_key: str | None = Query(default=None),
    x_admin_key: str | None = Header(default=None, alias="X-RaceIntel-Admin-Key"),
):
    """
    Trigger on-demand synchronization for a season or round.
    Requires admin key in header `X-RaceIntel-Admin-Key` or parameter `admin_key`.
    """
    expected_key = os.getenv("RACEINTEL_ADMIN_KEY")
    if not expected_key or not expected_key.strip():
        raise HTTPException(
            status_code=503,
            detail="Admin sync endpoint is unavailable: RACEINTEL_ADMIN_KEY is not configured.",
        )

    provided_key = x_admin_key or admin_key or (payload.get("admin_key") if payload else None)
    if not provided_key or not hmac.compare_digest(str(provided_key), expected_key.strip()):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: valid admin authorization key required to trigger synchronization",
        )

    # Allow payload overrides
    if payload:
        season = payload.get("season", season)
        round_number = payload.get("round_number", round_number)
        incremental = payload.get("incremental", incremental)
        force_refresh = payload.get("force_refresh", force_refresh)

    try:
        report = run_ingest(
            season=season,
            round_number=round_number,
            incremental=incremental,
            force_refresh=force_refresh,
        )
        return {
            "status": "success" if report.is_success else "partial_failure",
            "season": report.season_year,
            "total_rounds": report.total_rounds,
            "processed_rounds": report.processed_rounds,
            "skipped_rounds": report.skipped_rounds,
            "failed_rounds": report.failed_rounds,
            "records_inserted": report.records_inserted,
            "records_updated": report.records_updated,
            "records_skipped": report.records_skipped,
            "duration_seconds": report.duration_seconds,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Synchronization failed: {exc}")



def _clean_value(val: Any) -> Any:
    """Convert numpy/pandas scalars and NaNs into JSON-safe Python primitives."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if pd.isna(val):
        return None
    if hasattr(val, "item"):
        val = val.item()
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    records = []
    for _, row in df.iterrows():
        records.append({col: _clean_value(row[col]) for col in df.columns})
    return records


@router.get("/overview")
def get_season_overview(season: int = Query(default=2024)):
    """Return high-level season inventory, latest race, winners, and leaders."""
    races_q = """
        SELECT
            s.session_id,
            sn.season_year AS season,
            e.event_id,
            e.round_number,
            e.event_name,
            e.country_name,
            e.circuit_name,
            d.driver_code AS winner_code,
            d.driver_full_name AS winner_name,
            c.constructor_name AS winner_constructor
        FROM sessions s
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        LEFT JOIN race_results rr ON rr.session_id = s.session_id AND rr.finish_position = 1
        LEFT JOIN drivers d ON rr.driver_id = d.driver_id
        LEFT JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE sn.season_year = :season
          AND s.session_type = 'Race'
        ORDER BY COALESCE(e.round_number, s.session_id) ASC;
    """
    races_df = query_to_dataframe(races_q, {"season": season})
    races = _df_to_records(races_df)
    if not races:
        raise HTTPException(status_code=404, detail=f"No race data found for season {season}")

    counts_q = """
        SELECT
            (SELECT COUNT(*) FROM seasons) AS total_seasons,
            COALESCE((SELECT COUNT(DISTINCT rr.driver_id) FROM race_results rr
             JOIN sessions s ON rr.session_id = s.session_id
             JOIN events e ON s.event_id = e.event_id
             JOIN seasons sn ON e.season_id = sn.season_id
             WHERE sn.season_year = :season), 0) AS total_drivers,
            COALESCE((SELECT COUNT(DISTINCT rr.constructor_id) FROM race_results rr
             JOIN sessions s ON rr.session_id = s.session_id
             JOIN events e ON s.event_id = e.event_id
             JOIN seasons sn ON e.season_id = sn.season_id
             WHERE sn.season_year = :season), 0) AS total_constructors,
            (SELECT COUNT(*) FROM laps l
             JOIN sessions s ON l.session_id = s.session_id
             JOIN events e ON s.event_id = e.event_id
             JOIN seasons sn ON e.season_id = sn.season_id
             WHERE sn.season_year = :season) AS total_laps,
            (SELECT COUNT(*) FROM weather_observations wo
             JOIN sessions s ON wo.session_id = s.session_id
             JOIN events e ON s.event_id = e.event_id
             JOIN seasons sn ON e.season_id = sn.season_id
             WHERE sn.season_year = :season) AS total_weather_observations;
    """
    counts_row = _df_to_records(query_to_dataframe(counts_q, {"season": season}))[0]

    completed_races = [r for r in races if r.get("winner_code")]
    latest = completed_races[-1] if completed_races else races[0]
    latest_sid = int(latest["session_id"])
    driver_standings = get_driver_standings_after_event(latest_sid, season=season)
    constructor_standings = get_constructor_standings_after_event(latest_sid, season=season)

    sprint_cal_q = """
        SELECT
            s.session_id,
            sn.season_year AS season,
            e.event_id,
            e.round_number,
            e.event_name,
            e.country_name,
            e.circuit_name,
            d.driver_code AS winner_code,
            d.driver_full_name AS winner_name,
            c.constructor_name AS winner_constructor
        FROM sessions s
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        LEFT JOIN race_results rr ON rr.session_id = s.session_id AND rr.finish_position = 1
        LEFT JOIN drivers d ON rr.driver_id = d.driver_id
        LEFT JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE sn.season_year = :season
          AND s.session_type = 'Sprint'
        ORDER BY COALESCE(e.round_number, s.session_id) ASC;
    """
    sprint_calendar = _df_to_records(query_to_dataframe(sprint_cal_q, {"season": season}))

    return {
        "season": season,
        "total_races": len(races),
        "completed_races": len(completed_races),
        "counts": counts_row,
        "latest_race": latest,
        "driver_leader": driver_standings[0] if driver_standings else None,
        "constructor_leader": constructor_standings[0] if constructor_standings else None,
        "calendar": races,
        "sprint_calendar": sprint_calendar,
    }


@router.get("/standings/drivers/season/{session_id}")
def cumulative_driver_standings(session_id: int, season: int = Query(default=2024)):
    """Return cumulative driver championship standings through `session_id`."""
    standings = get_driver_standings_after_event(session_id, season=season)
    if not standings:
        raise HTTPException(status_code=404, detail="Standings not found for session")
    return standings


@router.get("/standings/constructors/season/{session_id}")
def cumulative_constructor_standings(session_id: int, season: int = Query(default=2024)):
    """Return cumulative constructor championship standings through `session_id`."""
    standings = get_constructor_standings_after_event(session_id, season=season)
    if not standings:
        raise HTTPException(status_code=404, detail="Constructor standings not found for session")
    return standings


@router.get("/standings/progression")
def season_standings_progression(season: int = Query(default=2024)):
    """Return cumulative constructor & top driver points across all races/sprints in the season."""
    q = """
        SELECT
            e.round_number,
            e.event_name,
            s.session_id,
            s.session_type,
            d.driver_code,
            d.driver_full_name,
            c.constructor_name,
            rr.finish_position,
            rr.points_scored
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE sn.season_year = :season
          AND s.session_type IN ('Race', 'Sprint')
        ORDER BY COALESCE(e.round_number, s.session_id) ASC;
    """
    df = query_to_dataframe(q, {"season": season})
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No results for season {season}")

    # Map each distinct round to round_index 1..N
    round_meta = (
        df[["round_number", "event_name"]]
        .drop_duplicates()
        .sort_values("round_number")
        .reset_index(drop=True)
    )
    round_meta["round_index"] = round_meta.index + 1
    df = df.merge(round_meta[["round_number", "round_index"]], on="round_number", how="left")

    # Constructor cumulative progression (sum Sprint + Race points per round)
    team_race = (
        df.groupby(["round_index", "event_name", "constructor_name"], as_index=False)["points_scored"]
        .sum()
        .sort_values(["constructor_name", "round_index"])
    )
    team_race["cumulative_points"] = team_race.groupby("constructor_name")["points_scored"].cumsum()

    # Driver cumulative progression (sum Sprint + Race points per round)
    drv_round = (
        df.groupby(["round_index", "event_name", "driver_code", "driver_full_name", "constructor_name"], as_index=False)
        .agg(
            points_scored=("points_scored", "sum"),
            finish_position=("finish_position", lambda s: min([p for p in s if pd.notna(p)], default=None)),
        )
        .sort_values(["driver_full_name", "round_index"])
    )
    drv_round["cumulative_points"] = drv_round.groupby("driver_full_name")["points_scored"].cumsum()

    return {
        "season": season,
        "constructors": _df_to_records(team_race),
        "drivers": _df_to_records(
            drv_round[
                [
                    "round_index",
                    "event_name",
                    "driver_code",
                    "driver_full_name",
                    "constructor_name",
                    "finish_position",
                    "points_scored",
                    "cumulative_points",
                ]
            ]
        ),
    }


@router.get("/race/{session_id}/full")
def full_race_analysis(session_id: int):
    """Return consolidated race results, position changes, pace, tyres, and weather."""
    meta_q = """
        SELECT
            s.session_id,
            sn.season_year AS season,
            e.event_name,
            e.country_name,
            e.circuit_name,
            s.session_type,
            s.session_name
        FROM sessions s
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        WHERE s.session_id = :session_id;
    """
    meta_rows = _df_to_records(query_to_dataframe(meta_q, {"session_id": session_id}))
    if not meta_rows:
        raise HTTPException(status_code=404, detail="Session not found")

    driver_classification = get_driver_championship(session_id)
    if not driver_classification:
        return {
            "session": meta_rows[0],
            "is_scheduled": True,
            "message": "This session is scheduled or upcoming. Results are not yet recorded.",
            "report": None,
            "fastest_lap_detail": None,
            "driver_classification": [],
            "constructor_points": [],
            "position_changes": [],
            "pace": {"fastest_laps": [], "average_pace": [], "consistency": []},
            "tyres": {"usage": [], "compound_performance": [], "stint_summary": []},
            "weather": {"details": {}, "trend": []},
        }

    try:
        report = get_race_report(session_id)
    except Exception:
        report = None

    constructor_points = get_constructor_championship(session_id)

    try:
        pos_changes = get_position_changes(session_id)
        cls_summary = get_classification_summary(session_id)
        if not pos_changes.empty and not cls_summary.empty:
            pos_changes = pos_changes.merge(
                cls_summary[["driver_code", "classified_status"]],
                on="driver_code",
                how="left",
            )
    except Exception:
        pos_changes = pd.DataFrame()

    try:
        fastest_lap_detail = get_fastest_lap_for_session(session_id)
    except Exception:
        fastest_lap_detail = None

    try:
        pace_best = get_pace(session_id)
        avg_pace = get_average_pace(session_id)
        consistency = get_lap_consistency(session_id)
    except Exception:
        pace_best, avg_pace, consistency = [], pd.DataFrame(), pd.DataFrame()

    try:
        tyre_usage = get_tyre_usage(session_id)
        compound_perf = get_compound_performance(session_id)
        stint_summary = get_stint_summary(session_id)
    except Exception:
        tyre_usage, compound_perf, stint_summary = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    try:
        weather_details = get_weather_details(session_id)
        temp_trend = get_temperature_trend(session_id)
        wind_trend = get_wind_conditions(session_id)
        if not temp_trend.empty and not wind_trend.empty:
            wx_trend = temp_trend.merge(wind_trend, on="observation_time", how="left")
        else:
            wx_trend = temp_trend
    except Exception:
        weather_details, wx_trend = {}, pd.DataFrame()

    return {
        "session": meta_rows[0],
        "report": report,
        "fastest_lap_detail": fastest_lap_detail,
        "driver_classification": driver_classification,
        "constructor_points": constructor_points,
        "position_changes": _df_to_records(pos_changes),
        "pace": {
            "fastest_laps": [
                {**p, "formatted_lap_time": format_lap_time(p["fastest_lap_seconds"])}
                for p in pace_best
            ],
            "average_pace": _df_to_records(avg_pace),
            "consistency": _df_to_records(consistency),
        },
        "tyres": {
            "usage": _df_to_records(tyre_usage),
            "compound_performance": _df_to_records(compound_perf),
            "stint_summary": _df_to_records(stint_summary),
        },
        "weather": {
            "details": weather_details,
            "trend": _df_to_records(wx_trend),
        },
    }


@router.get("/drivers/{driver_id}/season")
def get_driver_season_profile(driver_id: int, season: int = Query(default=2024)):
    """Return driver bio, aggregated KPIs, and race-by-race history for a season."""
    drv_q = """
        SELECT
            d.driver_id,
            d.driver_code,
            d.driver_number,
            d.driver_full_name,
            c.constructor_name
        FROM drivers d
        LEFT JOIN constructors c ON d.constructor_id = c.constructor_id
        WHERE d.driver_id = :driver_id;
    """
    drv_rows = _df_to_records(query_to_dataframe(drv_q, {"driver_id": driver_id}))
    if not drv_rows:
        raise HTTPException(status_code=404, detail="Driver not found")

    res_q = """
        SELECT
            s.session_id,
            e.event_name,
            e.circuit_name,
            c.constructor_name,
            rr.grid_position,
            rr.finish_position,
            rr.points_scored,
            rr.classified_status
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.driver_id = :driver_id
          AND sn.season_year = :season
          AND s.session_type = 'Race'
        ORDER BY s.session_id ASC;
    """
    df = query_to_dataframe(res_q, {"driver_id": driver_id, "season": season})
    if df.empty:
        return {
            "driver": drv_rows[0],
            "season": season,
            "summary": {
                "races": 0,
                "wins": 0,
                "podiums": 0,
                "points_finishes": 0,
                "retirements": 0,
                "total_points": 0.0,
                "best_finish": None,
                "average_finish": None,
                "best_grid": None,
                "net_positions_gained": 0,
            },
            "races": [],
        }

    sprint_res_q = """
        SELECT
            s.session_id,
            e.round_number,
            e.event_name,
            c.constructor_name,
            rr.grid_position,
            rr.finish_position,
            rr.points_scored,
            rr.classified_status
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.driver_id = :driver_id
          AND sn.season_year = :season
          AND s.session_type = 'Sprint'
        ORDER BY COALESCE(e.round_number, s.session_id) ASC;
    """
    sprint_df = query_to_dataframe(sprint_res_q, {"driver_id": driver_id, "season": season})
    sprint_pts_by_event = (
        sprint_df.set_index("event_name")["points_scored"].to_dict() if not sprint_df.empty else {}
    )
    sprint_pts = float(sprint_df["points_scored"].sum()) if not sprint_df.empty else 0.0
    race_pts = float(df["points_scored"].sum())
    total_pts = race_pts + sprint_pts

    df["sprint_points"] = df["event_name"].map(sprint_pts_by_event).fillna(0.0)
    df["round_points"] = df["points_scored"] + df["sprint_points"]
    df["round_index"] = range(1, len(df) + 1)
    df["cumulative_points"] = df["round_points"].cumsum()
    df["positions_gained"] = df.apply(
        lambda r: (
            int(r["grid_position"]) - int(r["finish_position"])
            if pd.notna(r["grid_position"])
            and pd.notna(r["finish_position"])
            and int(r["grid_position"]) > 0
            and str(r["classified_status"]) in ("Finished", "Lapped")
            else None
        ),
        axis=1,
    )

    finished_mask = df["classified_status"].isin(["Finished", "Lapped"]) | df["classified_status"].astype(str).str.startswith("+")
    valid_finishes = df.loc[df["finish_position"].notna(), "finish_position"]
    valid_grids = df.loc[df["grid_position"].notna() & (df["grid_position"] > 0), "grid_position"]
    wins = int((df["finish_position"] == 1).sum())
    podiums = int((df["finish_position"] <= 3).sum())
    pts_finishes = int((df["points_scored"] > 0).sum())
    retirements = int((~finished_mask).sum())
    best_fin = int(valid_finishes.min()) if not valid_finishes.empty else None
    avg_fin = round(float(valid_finishes.mean()), 2) if not valid_finishes.empty else None
    best_grid = int(valid_grids.min()) if not valid_grids.empty else None
    avg_grid = round(float(valid_grids.mean()), 2) if not valid_grids.empty else None
    net_gain = int(df["positions_gained"].dropna().sum()) if df["positions_gained"].notna().any() else 0

    # Calculate championship rank in this season (Race + Sprint points, Grand Prix tie-breaker)
    rank_q = """
        SELECT
            rr.driver_id,
            SUM(rr.points_scored) AS total_pts,
            MIN(CASE WHEN s.session_type = 'Race' THEN rr.finish_position ELSE 99 END) AS best_finish
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        WHERE sn.season_year = :season
          AND s.session_type IN ('Race', 'Sprint')
        GROUP BY rr.driver_id
        ORDER BY total_pts DESC, best_finish ASC;
    """
    rank_df = query_to_dataframe(rank_q, {"season": season})
    championship_rank = None
    if not rank_df.empty and driver_id in rank_df["driver_id"].values:
        match_idx = rank_df.index[rank_df["driver_id"] == driver_id].tolist()
        if match_idx:
            championship_rank = int(match_idx[0]) + 1

    driver_meta = dict(drv_rows[0])
    season_constructor = df["constructor_name"].iloc[-1] if not df.empty else None
    if season_constructor:
        driver_meta["season_constructor"] = season_constructor
        driver_meta["constructor_name"] = season_constructor

    return {
        "driver": driver_meta,
        "season": season,
        "summary": {
            "championship_rank": championship_rank,
            "races": len(df),
            "wins": wins,
            "podiums": podiums,
            "points_finishes": pts_finishes,
            "retirements": retirements,
            "total_points": round(total_pts, 1),
            "race_points": round(race_pts, 1),
            "sprint_points": round(sprint_pts, 1),
            "best_finish": best_fin,
            "average_finish": avg_fin,
            "best_grid": best_grid,
            "average_grid": avg_grid,
            "net_positions_gained": net_gain,
        },
        "races": _df_to_records(df),
        "sprint_results": _df_to_records(sprint_df),
    }


@router.get("/constructors/{constructor_id}/season")
def get_constructor_season_profile(constructor_id: int, season: int = Query(default=2024)):
    """Return constructor season KPIs, championship rank, driver contributions, and race history."""
    con_q = """
        SELECT constructor_id, constructor_name
        FROM constructors
        WHERE constructor_id = :constructor_id;
    """
    con_rows = _df_to_records(query_to_dataframe(con_q, {"constructor_id": constructor_id}))
    if not con_rows:
        raise HTTPException(status_code=404, detail="Constructor not found")

    res_q = """
        SELECT
            s.session_id,
            e.event_name,
            e.circuit_name,
            d.driver_id,
            d.driver_code,
            d.driver_full_name,
            rr.grid_position,
            rr.finish_position,
            rr.points_scored,
            rr.classified_status
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN drivers d ON rr.driver_id = d.driver_id
        WHERE rr.constructor_id = :constructor_id
          AND sn.season_year = :season
          AND s.session_type = 'Race'
        ORDER BY s.session_id ASC, rr.finish_position ASC;
    """
    df = query_to_dataframe(res_q, {"constructor_id": constructor_id, "season": season})
    if df.empty:
        return {
            "constructor": con_rows[0],
            "season": season,
            "summary": {
                "races": 0,
                "total_points": 0.0,
                "wins": 0,
                "podiums": 0,
                "championship_rank": None,
                "double_points_finishes": 0,
            },
            "driver_contributions": [],
            "race_totals": [],
            "driver_results": [],
        }

    # Fetch constructor sprint points per event
    sprint_team_q = """
        SELECT e.event_name, SUM(rr.points_scored) AS sprint_points
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        WHERE rr.constructor_id = :constructor_id
          AND sn.season_year = :season
          AND s.session_type = 'Sprint'
        GROUP BY e.event_name;
    """
    sprint_team_df = query_to_dataframe(sprint_team_q, {"constructor_id": constructor_id, "season": season})
    sprint_map = sprint_team_df.set_index("event_name")["sprint_points"].to_dict() if not sprint_team_df.empty else {}

    race_totals = (
        df.groupby(["session_id", "event_name"], as_index=False)
        .agg(
            race_points=("points_scored", "sum"),
            best_finish=("finish_position", "min"),
            scorers=("points_scored", lambda s: int((s > 0).sum())),
        )
        .sort_values("session_id")
        .reset_index(drop=True)
    )
    race_totals["sprint_points"] = race_totals["event_name"].map(sprint_map).fillna(0.0)
    race_totals["team_points"] = race_totals["race_points"] + race_totals["sprint_points"]
    race_totals["round_index"] = race_totals.index + 1
    race_totals["cumulative_points"] = race_totals["team_points"].cumsum()

    # Driver contributions combining Race and Sprint points
    drv_contrib_q = """
        SELECT
            d.driver_id,
            d.driver_code,
            d.driver_full_name,
            COUNT(DISTINCT CASE WHEN s.session_type = 'Race' THEN s.session_id END) AS races,
            SUM(rr.points_scored) AS total_points,
            SUM(CASE WHEN s.session_type = 'Race' THEN rr.points_scored ELSE 0 END) AS race_points,
            SUM(CASE WHEN s.session_type = 'Sprint' THEN rr.points_scored ELSE 0 END) AS sprint_points,
            COUNT(CASE WHEN s.session_type = 'Race' AND rr.finish_position = 1 THEN 1 END) AS wins,
            COUNT(CASE WHEN s.session_type = 'Race' AND rr.finish_position <= 3 THEN 1 END) AS podiums,
            MIN(CASE WHEN s.session_type = 'Race' THEN rr.finish_position END) AS best_finish,
            AVG(CASE WHEN s.session_type = 'Race' THEN rr.finish_position END) AS average_finish
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN drivers d ON rr.driver_id = d.driver_id
        WHERE rr.constructor_id = :constructor_id
          AND sn.season_year = :season
          AND s.session_type IN ('Race', 'Sprint')
        GROUP BY d.driver_id, d.driver_code, d.driver_full_name
        ORDER BY total_points DESC;
    """
    drv_contrib = query_to_dataframe(drv_contrib_q, {"constructor_id": constructor_id, "season": season})
    if not drv_contrib.empty:
        drv_contrib["average_finish"] = drv_contrib["average_finish"].apply(
            lambda v: round(float(v), 2) if pd.notna(v) else None
        )

    total_team_pts = float(drv_contrib["total_points"].sum()) if not drv_contrib.empty else float(df["points_scored"].sum())
    total_race_pts = float(drv_contrib["race_points"].sum()) if not drv_contrib.empty else float(df["points_scored"].sum())
    total_sprint_pts = float(drv_contrib["sprint_points"].sum()) if not drv_contrib.empty else 0.0

    latest_sid = int(race_totals["session_id"].max())
    season_table = get_constructor_standings_after_event(latest_sid, season=season)
    rank_rec = next((r for r in season_table if r["constructor_id"] == constructor_id), None)

    return {
        "constructor": con_rows[0],
        "season": season,
        "summary": {
            "races": len(race_totals),
            "total_points": round(total_team_pts, 1),
            "race_points": round(total_race_pts, 1),
            "sprint_points": round(total_sprint_pts, 1),
            "wins": int((df["finish_position"] == 1).sum()),
            "podiums": int((df["finish_position"] <= 3).sum()),
            "championship_rank": rank_rec["rank"] if rank_rec else None,
            "double_points_finishes": int((race_totals["scorers"] >= 2).sum()),
        },
        "driver_contributions": _df_to_records(drv_contrib),
        "race_totals": _df_to_records(race_totals),
        "driver_results": _df_to_records(df),
    }
