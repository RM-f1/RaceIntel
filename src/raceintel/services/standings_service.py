"""
Standings service.
"""

import pandas as pd
from analytics.standings import get_driver_standings


def get_driver_championship(session_id: int) -> list[dict]:
  

    standings = get_driver_standings(session_id)

    if standings.empty:
        return []

    results = []

    for _, row in standings.iterrows():
        results.append(
            {
                "finish_position": int(row["finish_position"]),
                "driver_code": row["driver_code"],
                "driver_full_name": row["driver_full_name"],
                "constructor_name": row["constructor_name"],
                "points_scored": float(row["points_scored"]),
            }
        )

    return results

from analytics.standings import (
    get_driver_standings,
    get_constructor_standings,
)


def get_constructor_championship(session_id: int) -> list[dict]:
    """
    Return constructor standings for a race session.
    """

    constructors = get_constructor_standings(session_id)

    if constructors.empty:
        return []

    results = []

    for _, row in constructors.iterrows():
        results.append(
            {
                "constructor_name": row["constructor_name"],
                "total_points": float(row["total_points"]),
            }
        )

    return results


from database.connection import query_to_dataframe


def get_driver_standings_after_event(
    session_id: int,
    season: int = 2024,
) -> list[dict]:
    """
    Calculate genuine cumulative driver championship standings after a specified event.

    Uses chronological event boundaries and aggregates Race and Sprint results
    within the specified season. Tie-breaking: points DESC, best Grand Prix finish ASC.
    """
    meta_df = query_to_dataframe(
        """
        SELECT 
            e.round_number AS target_round,
            s.session_type AS target_type,
            se.season_year AS target_season
        FROM sessions s
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons se ON e.season_id = se.season_id
        WHERE s.session_id = :session_id
        """,
        {"session_id": session_id},
    )

    if meta_df.empty:
        # Fallback if session_id passed was an event_id
        meta_df = query_to_dataframe(
            """
            SELECT 
                e.round_number AS target_round,
                'Race' AS target_type,
                se.season_year AS target_season
            FROM events e
            JOIN seasons se ON e.season_id = se.season_id
            WHERE e.event_id = :event_id
            """,
            {"event_id": session_id},
        )

    if not meta_df.empty:
        target_round = meta_df.iloc[0]["target_round"]
        target_type = str(meta_df.iloc[0]["target_type"])
        season = int(meta_df.iloc[0]["target_season"])
    else:
        target_round = None
        target_type = "Race"

    if target_round is not None:
        boundary_filter = """
            AND (
                e.round_number < :target_round
                OR (
                    e.round_number = :target_round
                    AND (:target_type = 'Race' OR s.session_type = 'Sprint')
                )
            )
        """
        params = {"season": season, "target_round": int(target_round), "target_type": target_type}
    else:
        boundary_filter = "AND s.session_id <= :session_id"
        params = {"season": season, "session_id": session_id, "target_round": None, "target_type": target_type}

    query = f"""
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            (
                SELECT c2.constructor_name
                FROM race_results rr2
                JOIN sessions s2 ON rr2.session_id = s2.session_id
                JOIN events e2 ON s2.event_id = e2.event_id
                JOIN seasons se2 ON e2.season_id = se2.season_id
                JOIN constructors c2 ON rr2.constructor_id = c2.constructor_id
                WHERE rr2.driver_id = d.driver_id
                  AND se2.season_year = :season
                  AND s2.session_type IN ('Race', 'Sprint')
                  AND (
                      :target_round IS NULL
                      OR e2.round_number < :target_round
                      OR (
                          e2.round_number = :target_round
                          AND (:target_type = 'Race' OR s2.session_type = 'Sprint')
                      )
                  )
                ORDER BY e2.round_number DESC, CASE WHEN s2.session_type = 'Race' THEN 2 ELSE 1 END DESC
                LIMIT 1
            ) AS constructor_name,
            SUM(rr.points_scored) AS total_points,
            SUM(CASE WHEN s.session_type = 'Race' THEN rr.points_scored ELSE 0 END) AS race_points,
            SUM(CASE WHEN s.session_type = 'Sprint' THEN rr.points_scored ELSE 0 END) AS sprint_points,
            MIN(CASE WHEN s.session_type = 'Race' THEN rr.finish_position ELSE 99 END) AS best_finish
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons se ON e.season_id = se.season_id
        JOIN drivers d ON rr.driver_id = d.driver_id
        WHERE se.season_year = :season
          AND s.session_type IN ('Race', 'Sprint')
          {boundary_filter}
        GROUP BY d.driver_id, d.driver_full_name, d.driver_code
        ORDER BY total_points DESC, best_finish ASC, d.driver_full_name ASC;
    """
    df = query_to_dataframe(
        query,
        params,
    )
    if df.empty:
        return []

    standings = []
    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        standings.append(
            {
                "rank": rank,
                "driver_id": int(row["driver_id"]),
                "driver_full_name": str(row["driver_full_name"]),
                "driver_code": str(row["driver_code"]),
                "constructor_name": str(row["constructor_name"]) if pd.notna(row["constructor_name"]) else "Unknown",
                "total_points": float(row["total_points"]),
                "points": float(row["total_points"]),
                "race_points": float(row["race_points"]),
                "sprint_points": float(row["sprint_points"]),
                "best_finish": int(row["best_finish"]) if row["best_finish"] is not None and row["best_finish"] < 99 else None,
            }
        )
    return standings


def get_driver_standings_leader_after_event(
    session_id: int,
    season: int = 2024,
) -> dict | None:
    """Return the driver leading the championship after a specified event."""
    standings = get_driver_standings_after_event(session_id, season)
    return standings[0] if standings else None


def format_driver_standings_leader_answer(
    leader: dict | None,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format a deterministic answer for championship leader queries."""
    if not leader:
        return f"Driver standings are not available after the {season} {event_name}."

    return (
        f"{leader['driver_full_name']} leads the driver standings after the "
        f"{event_name} with {leader['total_points']} points."
    )


def get_constructor_points_for_race(session_id: int) -> list[dict]:
    """
    Aggregate driver race results by constructor for a specified Grand Prix.
    Returns constructors sorted by points scored in that race.
    """
    query = """
        SELECT 
            c.constructor_id,
            c.constructor_name,
            SUM(rr.points_scored) AS total_points
        FROM race_results rr
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
        GROUP BY c.constructor_id, c.constructor_name
        ORDER BY total_points DESC, c.constructor_name ASC;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty:
        return []

    results = []
    for _, row in df.iterrows():
        results.append(
            {
                "constructor_name": str(row["constructor_name"]),
                "total_points": float(row["total_points"]),
            }
        )
    return results


def get_top_constructors_for_race(session_id: int) -> dict:
    """
    Return the constructor(s) scoring the most points in a race.
    Correctly detects and reports ties.
    """
    standings = get_constructor_points_for_race(session_id)
    if not standings:
        return {
            "available": False,
            "top_constructors": [],
            "points": 0.0,
            "is_tie": False,
        }

    max_pts = standings[0]["total_points"]
    top_teams = [
        t["constructor_name"] for t in standings if t["total_points"] == max_pts
    ]

    return {
        "available": True,
        "top_constructors": top_teams,
        "points": max_pts,
        "is_tie": len(top_teams) > 1,
    }


def format_constructor_points_answer(
    top_info: dict,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format a deterministic answer for constructor points queries."""
    if not top_info.get("available"):
        return f"Constructor points data is not available for the {season} {event_name}."

    teams = top_info["top_constructors"]
    pts = top_info["points"]

    if top_info.get("is_tie"):
        joined_teams = " and ".join(teams)
        return (
            f"{joined_teams} tied for the most points in the "
            f"{event_name} with {pts} points each."
        )

    return (
        f"{teams[0]} scored the most points in the "
        f"{event_name} with {pts} points."
    )


def get_driver_standings_record_after_event(
    session_id: int,
    driver_id: int,
    season: int = 2024,
) -> dict | None:
    """Return standings record for a specific driver after a specified event."""
    standings = get_driver_standings_after_event(session_id, season)
    for rec in standings:
        if rec.get("driver_id") == driver_id:
            return rec
    return None


def format_driver_championship_position_answer(
    record: dict | None,
    driver_name: str,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for driver championship position."""
    if not record:
        return f"{driver_name} has no championship standings data after the {season} {event_name}."
    return (
        f"{record['driver_full_name']} was P{record['rank']} in the driver standings after the "
        f"{event_name} with {record['total_points']} points."
    )


def format_driver_cumulative_points_answer(
    record: dict | None,
    driver_name: str,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for driver cumulative championship points."""
    if not record:
        return f"{driver_name} has no championship points data after the {season} {event_name}."

    total = record["total_points"]
    race_pts = record.get("race_points", total)
    sprint_pts = record.get("sprint_points", 0.0)
    if sprint_pts > 0:
        return (
            f"{record['driver_full_name']} had {total} championship points "
            f"({race_pts} Grand Prix points and {sprint_pts} Sprint points) after the {event_name}."
        )
    return (
        f"{record['driver_full_name']} had {total} championship points after the "
        f"{event_name}."
    )


def compare_driver_standings_after_event(
    session_id: int,
    driver_id_1: int,
    driver_id_2: int,
    season: int = 2024,
) -> dict:
    """Compare two drivers in the championship standings after a specified event."""
    standings = get_driver_standings_after_event(session_id, season)
    d1 = next((s for s in standings if s.get("driver_id") == driver_id_1), None)
    d2 = next((s for s in standings if s.get("driver_id") == driver_id_2), None)
    return {"driver_1": d1, "driver_2": d2}


def format_driver_standings_comparison_answer(
    comparison: dict,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic comparison between two drivers in the standings."""
    d1 = comparison.get("driver_1")
    d2 = comparison.get("driver_2")
    if not d1 or not d2:
        return f"Standings comparison data is incomplete for the {season} {event_name}."

    if d1["rank"] < d2["rank"]:
        diff = d1["total_points"] - d2["total_points"]
        return (
            f"After the {event_name}, {d1['driver_full_name']} was ahead of {d2['driver_full_name']} "
            f"in the championship (P{d1['rank']} with {d1['total_points']} points vs P{d2['rank']} with {d2['total_points']} points, +{diff} points)."
        )
    elif d2["rank"] < d1["rank"]:
        diff = d2["total_points"] - d1["total_points"]
        return (
            f"After the {event_name}, {d2['driver_full_name']} was ahead of {d1['driver_full_name']} "
            f"in the championship (P{d2['rank']} with {d2['total_points']} points vs P{d1['rank']} with {d1['total_points']} points, +{diff} points)."
        )
    else:
        return (
            f"After the {event_name}, {d1['driver_full_name']} and {d2['driver_full_name']} "
            f"were tied in the championship at {d1['total_points']} points."
        )


def format_driver_standings_table_answer(
    standings: list[dict],
    event_name: str,
    season: int = 2024,
    top_n: int = 10,
) -> str:
    """Format driver standings table after an event."""
    if not standings:
        return f"Driver standings are not available after the {season} {event_name}."
    lines = [f"{s['rank']}. {s['driver_full_name']}: {s['total_points']} points" for s in standings[:top_n]]
    return "\n".join(lines)


def get_constructor_standings_after_event(
    session_id: int,
    season: int = 2024,
) -> list[dict]:
    """
    Calculate cumulative constructor championship standings after a specified event.
    Aggregates Race and Sprint results within the specified season.
    Tie-breaking: total_points DESC, best Grand Prix finish ASC, constructor_name ASC.
    """
    meta_df = query_to_dataframe(
        """
        SELECT 
            e.round_number AS target_round,
            s.session_type AS target_type,
            se.season_year AS target_season
        FROM sessions s
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons se ON e.season_id = se.season_id
        WHERE s.session_id = :session_id
        """,
        {"session_id": session_id},
    )

    if meta_df.empty:
        # Fallback if session_id passed was an event_id
        meta_df = query_to_dataframe(
            """
            SELECT 
                e.round_number AS target_round,
                'Race' AS target_type,
                se.season_year AS target_season
            FROM events e
            JOIN seasons se ON e.season_id = se.season_id
            WHERE e.event_id = :event_id
            """,
            {"event_id": session_id},
        )

    if not meta_df.empty:
        target_round = meta_df.iloc[0]["target_round"]
        target_type = str(meta_df.iloc[0]["target_type"])
        season = int(meta_df.iloc[0]["target_season"])
    else:
        target_round = None
        target_type = "Race"

    if target_round is not None:
        boundary_filter = """
            AND (
                e.round_number < :target_round
                OR (
                    e.round_number = :target_round
                    AND (:target_type = 'Race' OR s.session_type = 'Sprint')
                )
            )
        """
        params = {"season": season, "target_round": int(target_round), "target_type": target_type}
    else:
        boundary_filter = "AND s.session_id <= :session_id"
        params = {"season": season, "session_id": session_id, "target_round": None, "target_type": target_type}

    query = f"""
        SELECT 
            c.constructor_id,
            c.constructor_name,
            SUM(rr.points_scored) AS total_points,
            SUM(CASE WHEN s.session_type = 'Race' THEN rr.points_scored ELSE 0 END) AS race_points,
            SUM(CASE WHEN s.session_type = 'Sprint' THEN rr.points_scored ELSE 0 END) AS sprint_points,
            MIN(CASE WHEN s.session_type = 'Race' THEN rr.finish_position ELSE 99 END) AS best_finish
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons se ON e.season_id = se.season_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE se.season_year = :season
          AND s.session_type IN ('Race', 'Sprint')
          {boundary_filter}
        GROUP BY c.constructor_id, c.constructor_name
        ORDER BY total_points DESC, best_finish ASC, c.constructor_name ASC;
    """
    df = query_to_dataframe(query, params)
    if df.empty:
        return []
    standings = []
    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        standings.append(
            {
                "rank": rank,
                "constructor_id": int(row["constructor_id"]),
                "constructor_name": str(row["constructor_name"]),
                "total_points": float(row["total_points"]),
                "points": float(row["total_points"]),
                "race_points": float(row["race_points"]),
                "sprint_points": float(row["sprint_points"]),
                "best_finish": int(row["best_finish"]) if row["best_finish"] is not None and row["best_finish"] < 99 else None,
            }
        )
    return standings


def get_constructor_standings_leader_after_event(
    session_id: int,
    season: int = 2024,
) -> dict | None:
    """Return the constructor leading the championship after a specified event."""
    standings = get_constructor_standings_after_event(session_id, season)
    return standings[0] if standings else None


def format_constructor_standings_leader_answer(
    leader: dict | None,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for constructor championship leader queries."""
    if not leader:
        return f"Constructor standings are not available after the {season} {event_name}."
    return (
        f"{leader['constructor_name']} leads the constructor standings after the "
        f"{event_name} with {leader['total_points']} points."
    )


def format_constructor_standings_table_answer(
    standings: list[dict],
    event_name: str,
    season: int = 2024,
    top_n: int = 10,
) -> str:
    """Format constructor championship standings table."""
    if not standings:
        return f"Constructor standings are not available after the {season} {event_name}."
    lines = [f"{s['rank']}. {s['constructor_name']}: {s['total_points']} points" for s in standings[:top_n]]
    return "\n".join(lines)


def compare_constructor_standings_after_event(
    session_id: int,
    constructor_id_1: int,
    constructor_id_2: int,
    season: int = 2024,
) -> dict:
    """Compare two constructors in the championship after an event."""
    standings = get_constructor_standings_after_event(session_id, season)
    c1 = next((s for s in standings if s["constructor_id"] == constructor_id_1), None)
    c2 = next((s for s in standings if s["constructor_id"] == constructor_id_2), None)
    return {"constructor_1": c1, "constructor_2": c2}


def format_constructor_standings_comparison_answer(
    comparison: dict,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic comparison between two constructors in the championship."""
    c1 = comparison.get("constructor_1")
    c2 = comparison.get("constructor_2")
    if not c1 or not c2:
        return f"Constructor standings comparison data is incomplete for the {season} {event_name}."

    def _fmt(c: dict) -> str:
        s_pts = c.get("sprint_points", 0.0)
        r_pts = c.get("race_points", c["total_points"])
        if s_pts > 0:
            return f"P{c['rank']} with {c['total_points']} points ({r_pts} race points, {s_pts} sprint points)"
        return f"P{c['rank']} with {c['total_points']} points"

    if c1["rank"] < c2["rank"]:
        diff = c1["total_points"] - c2["total_points"]
        return (
            f"After the {event_name}, {c1['constructor_name']} was ahead of {c2['constructor_name']} "
            f"in the championship ({_fmt(c1)} vs {_fmt(c2)}, +{diff} points)."
        )
    elif c2["rank"] < c1["rank"]:
        diff = c2["total_points"] - c1["total_points"]
        return (
            f"After the {event_name}, {c2['constructor_name']} was ahead of {c1['constructor_name']} "
            f"in the championship ({_fmt(c2)} vs {_fmt(c1)}, +{diff} points)."
        )
    else:
        return (
            f"After the {event_name}, {c1['constructor_name']} and {c2['constructor_name']} "
            f"were tied in the championship at {c1['total_points']} points."
        )


def get_constructor_single_race_points(session_id: int, constructor_id: int) -> dict | None:
    """Return single race points scored by a constructor."""
    query = """
        SELECT 
            c.constructor_id,
            c.constructor_name,
            SUM(rr.points_scored) AS total_points
        FROM race_results rr
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
          AND rr.constructor_id = :constructor_id
        GROUP BY c.constructor_id, c.constructor_name;
    """
    df = query_to_dataframe(query, {"session_id": session_id, "constructor_id": constructor_id})
    if df.empty:
        return None
    row = df.iloc[0]
    return {
        "constructor_id": int(row["constructor_id"]),
        "constructor_name": str(row["constructor_name"]),
        "total_points": float(row["total_points"]),
    }


def format_single_constructor_race_points_answer(
    result: dict | None,
    team_name: str,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format single constructor race points answer."""
    if not result:
        return f"{team_name} did not score points or no data was found in the {season} {event_name}."
    return f"{result['constructor_name']} scored {result['total_points']} points in the {event_name}."


# =====================================================================
# SPRINT POINTS & SEASON SPRINT AGGREGATIONS
# =====================================================================


def get_driver_season_sprint_points(driver_id: int | str, season: int = 2024) -> float:
    """Return total Sprint points scored by a driver in a season."""
    if isinstance(driver_id, str):
        val = driver_id.strip()
        drv_df = query_to_dataframe(
            "SELECT driver_id FROM drivers WHERE UPPER(driver_code) = UPPER(:val) OR LOWER(driver_full_name) = LOWER(:val) LIMIT 1;",
            {"val": val},
        )
        if drv_df.empty:
            return 0.0
        did = int(drv_df.iloc[0]["driver_id"])
    else:
        did = int(driver_id)

    query = """
        SELECT COALESCE(SUM(rr.points_scored), 0.0) AS sprint_points
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        WHERE rr.driver_id = :driver_id
          AND sn.season_year = :season
          AND s.session_type = 'Sprint';
    """
    df = query_to_dataframe(query, {"driver_id": did, "season": season})
    if df.empty or df.iloc[0]["sprint_points"] is None:
        return 0.0
    return float(df.iloc[0]["sprint_points"])


def format_driver_season_sprint_points_answer(
    points: float,
    driver_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for driver season sprint points."""
    return f"{driver_name} scored {points} Sprint points in {season}."


def get_constructor_season_sprint_points(constructor_id: int | str, season: int = 2024) -> float:
    """Return total Sprint points earned by a constructor in a season."""
    if isinstance(constructor_id, str):
        val = constructor_id.strip()
        con_df = query_to_dataframe(
            "SELECT constructor_id FROM constructors WHERE LOWER(constructor_name) = LOWER(:val) OR LOWER(constructor_name) LIKE LOWER(:like_val) LIMIT 1;",
            {"val": val, "like_val": f"%{val}%"},
        )
        if con_df.empty:
            return 0.0
        cid = int(con_df.iloc[0]["constructor_id"])
    else:
        cid = int(constructor_id)

    query = """
        SELECT COALESCE(SUM(rr.points_scored), 0.0) AS sprint_points
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        WHERE rr.constructor_id = :constructor_id
          AND sn.season_year = :season
          AND s.session_type = 'Sprint';
    """
    df = query_to_dataframe(query, {"constructor_id": cid, "season": season})
    if df.empty or df.iloc[0]["sprint_points"] is None:
        return 0.0
    return float(df.iloc[0]["sprint_points"])


def format_constructor_season_sprint_points_answer(
    points: float,
    constructor_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for constructor season sprint points."""
    return f"{constructor_name} earned {points} points from Sprints in {season}."


def get_most_sprint_points_driver(season: int = 2024) -> dict | None:
    """Return the driver who scored the most sprint points in a season."""
    query = """
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            COALESCE(c.constructor_name, 'Unknown') AS constructor_name,
            SUM(rr.points_scored) AS sprint_points
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN drivers d ON rr.driver_id = d.driver_id
        LEFT JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE sn.season_year = :season
          AND s.session_type = 'Sprint'
        GROUP BY d.driver_id, d.driver_full_name, d.driver_code
        ORDER BY sprint_points DESC
        LIMIT 1;
    """
    df = query_to_dataframe(query, {"season": season})
    if df.empty:
        return None
    row = df.iloc[0]
    return {
        "driver_id": int(row["driver_id"]),
        "driver_full_name": str(row["driver_full_name"]),
        "driver_code": str(row["driver_code"]),
        "constructor_name": str(row["constructor_name"]),
        "sprint_points": float(row["sprint_points"]),
    }


def format_most_sprint_points_driver_answer(
    leader: dict | None,
    season: int = 2024,
) -> str:
    """Format deterministic answer for driver with most sprint points."""
    if not leader:
        return f"Sprint data is not available for season {season}."
    return f"{leader['driver_full_name']} scored the most Sprint points in {season} with {leader['sprint_points']} points."


def get_most_sprint_points_constructor(season: int = 2024) -> dict | None:
    """Return top constructor(s) by sprint points in a season."""
    query = """
        SELECT 
            c.constructor_id,
            c.constructor_name,
            SUM(rr.points_scored) AS sprint_points
        FROM race_results rr
        JOIN sessions s ON rr.session_id = s.session_id
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons sn ON e.season_id = sn.season_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE sn.season_year = :season
          AND s.session_type = 'Sprint'
        GROUP BY c.constructor_id, c.constructor_name
        ORDER BY sprint_points DESC;
    """
    df = query_to_dataframe(query, {"season": season})
    if df.empty:
        return None
    max_pts = float(df.iloc[0]["sprint_points"])
    top_teams = df[df["sprint_points"] == max_pts]["constructor_name"].tolist()
    return {
        "teams": top_teams,
        "sprint_points": max_pts,
        "is_tie": len(top_teams) > 1,
    }


def format_most_sprint_points_constructor_answer(
    result: dict | None,
    season: int = 2024,
) -> str:
    """Format deterministic answer for constructor with most sprint points."""
    if not result:
        return f"Sprint data is not available for season {season}."
    teams = result["teams"]
    pts = result["sprint_points"]
    if result.get("is_tie"):
        joined = " and ".join(teams)
        return f"{joined} tied for the most Sprint points in {season} with {pts} points each."
    return f"{teams[0]} earned the most Sprint points in {season} with {pts} points."

