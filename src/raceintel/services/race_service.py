"""
Race report and race results service.

Provides deterministic, database-driven helpers for race winners,
podiums, driver single-race results, and constructor race performances.
"""

from __future__ import annotations

import pandas as pd
from raceintel.analytics.race_report import generate_race_report
from database.connection import query_to_dataframe


def get_race_report(session_id: int) -> dict:
    """Return comprehensive race report from analytics."""
    try:
        return generate_race_report(session_id)
    except Exception:
        # Fallback for sprint sessions or sessions without lap/fastest lap telemetry
        from raceintel.services.standings_service import (
            get_constructor_championship,
            get_driver_championship,
        )
        drivers = get_driver_championship(session_id)
        if not drivers:
            raise
        constructors = get_constructor_championship(session_id)
        winner_name = drivers[0]["driver_full_name"]
        top_con = constructors[0]["constructor_name"] if constructors else "N/A"
        podium = [d["driver_full_name"] for d in drivers[:3]]
        return {
            "session_id": session_id,
            "winner": winner_name,
            "podium": podium,
            "classification": "\n".join(f"P{d['finish_position']} {d['driver_full_name']}" for d in drivers),
            "top_constructor": top_con,
            "biggest_mover": {"driver": "N/A", "positions": 0},
            "fastest_lap": {"driver": "N/A", "seconds": 0.0},
            "summary": f"{winner_name} won the sprint session.",
            "statistics": {
                "drivers": len(drivers),
                "constructors": len(constructors),
                "weather_samples": 0,
                "tyre_compounds": [],
            },
        }


def get_race_winner(session_id: int) -> dict | None:
    """Return the driver who won the race in the given session."""
    query = """
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            c.constructor_name,
            rr.finish_position,
            rr.points_scored
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
          AND rr.finish_position = 1;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty:
        return None
    row = df.iloc[0]
    return {
        "driver_id": int(row["driver_id"]),
        "driver_full_name": str(row["driver_full_name"]),
        "driver_code": str(row["driver_code"]),
        "constructor_name": str(row["constructor_name"]),
        "finish_position": int(row["finish_position"]),
        "points_scored": float(row["points_scored"]),
    }


def format_race_winner_answer(
    winner: dict | None,
    event_name: str,
    season: int = 2024,
    session_type: str = "Race",
) -> str:
    """Format deterministic answer for race or sprint winner queries."""
    session_label = "Sprint" if session_type.lower() == "sprint" else "Race"
    if not winner:
        return f"{session_label} winner data is not available for the {season} {event_name}."
    if session_label == "Sprint":
        return f"{winner['driver_full_name']} won the {event_name} Sprint in {season}."
    return f"{winner['driver_full_name']} won the {event_name} in {season}."



def get_driver_race_result(session_id: int, driver_id: int) -> dict | None:
    """Return single-race result for a specified driver."""
    query = """
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            c.constructor_name,
            rr.grid_position,
            rr.finish_position,
            rr.points_scored,
            rr.classified_status
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
          AND rr.driver_id = :driver_id;
    """
    df = query_to_dataframe(query, {"session_id": session_id, "driver_id": driver_id})
    if df.empty:
        return None
    row = df.iloc[0]
    pos = row["finish_position"]
    pos_str = f"P{int(pos)}" if pd.notna(pos) and int(pos) > 0 else (str(row["classified_status"]) if pd.notna(row["classified_status"]) else "DNF")
    return {
        "driver_id": int(row["driver_id"]),
        "driver_full_name": str(row["driver_full_name"]),
        "driver_code": str(row["driver_code"]),
        "constructor_name": str(row["constructor_name"]),
        "grid_position": int(row["grid_position"]) if pd.notna(row["grid_position"]) else None,
        "finish_position": pos_str,
        "points_scored": float(row["points_scored"]),
        "classified_status": str(row["classified_status"]),
    }


def format_driver_points_answer(
    result: dict | None,
    driver_name: str,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for driver points scored."""
    if not result:
        return f"{driver_name} did not compete or no data was found in the {season} {event_name}."
    return f"{result['driver_full_name']} scored {result['points_scored']} points in the {event_name}."


def format_driver_position_answer(
    result: dict | None,
    driver_name: str,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for driver finishing position."""
    if not result:
        return f"{driver_name} did not compete or no data was found in the {season} {event_name}."
    return f"{result['driver_full_name']} finished {result['finish_position']} in the {event_name}."


def format_driver_performance_answer(
    result: dict | None,
    driver_name: str,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for driver race performance."""
    if not result:
        return f"{driver_name} did not compete or no data was found in the {season} {event_name}."
    return (
        f"{result['driver_full_name']} finished {result['finish_position']} "
        f"and scored {result['points_scored']} points in the {event_name}."
    )


def get_race_podium(session_id: int) -> list[dict]:
    """Return top 3 drivers for a race session."""
    query = """
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            c.constructor_name,
            rr.finish_position,
            rr.points_scored
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
          AND rr.finish_position IN (1, 2, 3)
        ORDER BY rr.finish_position ASC;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty:
        return []
    podium = []
    for _, row in df.iterrows():
        podium.append({
            "position": f"P{int(row['finish_position'])}",
            "driver": str(row["driver_full_name"]),
            "constructor": str(row["constructor_name"]),
        })
    return podium


def format_race_podium_answer(podium: list[dict], event_name: str, season: int = 2024) -> str:
    """Format deterministic answer for podium finishers."""
    if not podium:
        return f"Podium data is not available for the {season} {event_name}."
    return "\n".join(f"{i+1}. {p['driver']}" for i, p in enumerate(podium))


def get_points_scorers(session_id: int) -> list[dict]:
    """Return all drivers who scored points in a race session."""
    query = """
        SELECT 
            d.driver_full_name,
            rr.finish_position,
            rr.points_scored
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        WHERE rr.session_id = :session_id
          AND rr.points_scored > 0
        ORDER BY rr.points_scored DESC, rr.finish_position ASC;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty:
        return []
    return [
        {
            "driver": str(row["driver_full_name"]),
            "points": float(row["points_scored"]),
        }
        for _, row in df.iterrows()
    ]


def format_points_scorers_answer(scorers: list[dict], event_name: str, season: int = 2024) -> str:
    """Format deterministic answer for drivers who scored points."""
    if not scorers:
        return f"No points scorers data available for the {season} {event_name}."
    return "\n".join(f"{s['driver']}: {s['points']} points" for s in scorers)


def get_team_race_results(session_id: int, constructor_id: int) -> list[dict]:
    """Return drivers for a constructor in a race session."""
    query = """
        SELECT 
            d.driver_full_name,
            rr.finish_position,
            rr.points_scored
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        WHERE rr.session_id = :session_id
          AND rr.constructor_id = :constructor_id
        ORDER BY rr.finish_position ASC;
    """
    df = query_to_dataframe(query, {"session_id": session_id, "constructor_id": constructor_id})
    if df.empty:
        return []
    results = []
    for _, row in df.iterrows():
        pos = row["finish_position"]
        pos_str = f"P{int(pos)}" if pd.notna(pos) and int(pos) > 0 else "DNF"
        results.append({
            "driver": str(row["driver_full_name"]),
            "position": pos_str,
            "points": float(row["points_scored"]),
        })
    return results


def format_team_performance_answer(
    results: list[dict],
    team_name: str,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for team performance in a race."""
    if not results:
        return f"No race results found for {team_name} in the {season} {event_name}."
    return "\n".join(f"{r['driver']}: {r['position']}, {r['points']} points" for r in results)


def get_top_driver_in_team(session_id: int, constructor_id: int, by_points: bool = True) -> dict | None:
    """Return top driver for a constructor in a race session (by points or finish position)."""
    results = get_team_race_results(session_id, constructor_id)
    if not results:
        return None
    if by_points:
        return max(results, key=lambda r: r["points"])
    else:
        valid = [r for r in results if r["position"].startswith("P")]
        if valid:
            valid.sort(key=lambda r: int(r["position"][1:]))
            return valid[0]
        return results[0]


def compare_drivers_in_race(
    session_id: int,
    driver_id_1: int,
    driver_id_2: int,
) -> dict:
    """Compare two drivers' finishing classification and points in a single race session."""
    d1 = get_driver_race_result(session_id, driver_id_1)
    d2 = get_driver_race_result(session_id, driver_id_2)
    return {"driver_1": d1, "driver_2": d2}


def _classified_rank_key(result: dict) -> tuple[int, int, float]:
    pos_str = str(result.get("finish_position") or "").strip()
    if pos_str.upper().startswith("P") and pos_str[1:].isdigit():
        num = int(pos_str[1:])
        if num > 0:
            return (0, num, -float(result.get("points_scored") or 0.0))
    elif pos_str.isdigit() and int(pos_str) > 0:
        return (0, int(pos_str), -float(result.get("points_scored") or 0.0))
    return (1, 999, -float(result.get("points_scored") or 0.0))


def _format_driver_pos_label(result: dict) -> str:
    pos = result.get("finish_position")
    if pos is not None and str(pos).strip():
        return str(pos).strip()
    return str(result.get("classified_status") or "DNF")


def format_driver_race_comparison_answer(
    comparison: dict,
    event_name: str,
    season: int = 2024,
) -> str:
    """Format a deterministic comparison between two drivers in a single race."""
    d1 = comparison.get("driver_1")
    d2 = comparison.get("driver_2")
    if not d1 or not d2:
        return f"Race comparison data is incomplete for the {season} {event_name}."

    k1 = _classified_rank_key(d1)
    k2 = _classified_rank_key(d2)
    l1 = _format_driver_pos_label(d1)
    l2 = _format_driver_pos_label(d2)
    p1 = float(d1.get("points_scored") or 0.0)
    p2 = float(d2.get("points_scored") or 0.0)
    n1 = d1["driver_full_name"]
    n2 = d2["driver_full_name"]

    if k1[:2] < k2[:2]:
        better, other = n1, n2
        bl, ol = l1, l2
        bp, op = p1, p2
    elif k2[:2] < k1[:2]:
        better, other = n2, n1
        bl, ol = l2, l1
        bp, op = p2, p1
    else:
        return (
            f"In the {event_name}, {n1} ({l1}, {p1} points) and {n2} ({l2}, {p2} points) "
            f"finished with matching classification status."
        )

    return (
        f"In the {event_name}, {better} finished ahead of {other} "
        f"({better}: {bl}, {bp} points vs {other}: {ol}, {op} points)."
    )



def get_race_retirements(session_id: int) -> list[dict]:
    """
    Return drivers who retired, did not start, or were disqualified in the session.
    """
    query = """
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            c.constructor_name,
            rr.classified_status,
            rr.finish_position
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
          AND (
              rr.classified_status IN ('Retired', 'Did not start', 'Disqualified')
              OR rr.finish_position IS NULL
          )
        ORDER BY d.driver_full_name ASC;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty:
        return []
    retirements = []
    for _, row in df.iterrows():
        retirements.append(
            {
                "driver": str(row["driver_full_name"]),
                "driver_code": str(row["driver_code"]),
                "constructor": str(row["constructor_name"]),
                "status": str(row["classified_status"]),
            }
        )
    return retirements


def format_race_retirements_answer(
    retirements: list[dict],
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for race retirements/DNFs."""
    if not retirements:
        return f"There were no retirements in the {season} {event_name}."
    lines = [f"{r['driver']} ({r['constructor']}) - {r['status']}" for r in retirements]
    return "\n".join(lines)


def get_full_race_classification(session_id: int) -> list[dict]:
    """Return complete race classification ordered by finish position."""
    query = """
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            c.constructor_name,
            rr.finish_position,
            rr.points_scored,
            rr.classified_status
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
        ORDER BY 
            CASE WHEN rr.finish_position IS NOT NULL THEN rr.finish_position ELSE 999 END ASC,
            rr.race_result_id ASC;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty:
        return []
    classification = []
    for _, row in df.iterrows():
        pos = row["finish_position"]
        pos_str = f"P{int(pos)}" if pd.notna(pos) and int(pos) > 0 else str(row["classified_status"])
        classification.append(
            {
                "driver": str(row["driver_full_name"]),
                "driver_code": str(row["driver_code"]),
                "constructor": str(row["constructor_name"]),
                "position": pos_str,
                "points": float(row["points_scored"]),
                "status": str(row["classified_status"]),
            }
        )
    return classification


def format_full_race_classification_answer(
    classification: list[dict],
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for full race classification."""
    if not classification:
        return f"Race classification is not available for the {season} {event_name}."
    lines = [f"{c['position']}. {c['driver']} ({c['constructor']}) - {c['points']} points" for c in classification]
    return "\n".join(lines)


def get_biggest_movers_for_session(session_id: int) -> list[dict]:
    """
    Return drivers sorted by positions gained from grid to finish.
    Ties broken by finish position (better finish first).
    """
    query = """
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            c.constructor_name,
            rr.grid_position,
            rr.finish_position,
            (rr.grid_position - rr.finish_position) AS positions_gained
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN constructors c ON rr.constructor_id = c.constructor_id
        WHERE rr.session_id = :session_id
          AND rr.grid_position IS NOT NULL
          AND rr.finish_position IS NOT NULL
        ORDER BY positions_gained DESC, rr.finish_position ASC;
    """
    df = query_to_dataframe(query, {"session_id": session_id})
    if df.empty:
        return []
    movers = []
    for _, row in df.iterrows():
        movers.append(
            {
                "driver": str(row["driver_full_name"]),
                "driver_code": str(row["driver_code"]),
                "constructor": str(row["constructor_name"]),
                "grid_position": int(row["grid_position"]),
                "finish_position": int(row["finish_position"]),
                "positions_gained": int(row["positions_gained"]),
            }
        )
    return movers


def format_biggest_movers_answer(
    movers: list[dict],
    event_name: str,
    season: int = 2024,
) -> str:
    """Format deterministic answer for biggest movers in a race."""
    if not movers:
        return f"Position change data is not available for the {season} {event_name}."
    best_gain = movers[0]["positions_gained"]
    top_movers = [m for m in movers if m["positions_gained"] == best_gain]
    if len(top_movers) == 1:
        m = top_movers[0]
        return (
            f"{m['driver']} gained the most positions in the {event_name}, "
            f"moving up {m['positions_gained']} places from P{m['grid_position']} to P{m['finish_position']}."
        )
    names = " and ".join(m["driver"] for m in top_movers)
    return (
        f"{names} tied for the most positions gained in the {event_name}, "
        f"each moving up {best_gain} places."
    )


def get_tyre_compounds_for_session(session_id: int, driver_id: int | None = None) -> list[str]:
    """
    Return distinct tyre compounds used during the session.
    """
    if driver_id is not None:
        query = """
            SELECT DISTINCT tyre_compound
            FROM laps
            WHERE session_id = :session_id
              AND driver_id = :driver_id
              AND tyre_compound IS NOT NULL
            ORDER BY tyre_compound ASC;
        """
        params = {"session_id": session_id, "driver_id": driver_id}
    else:
        query = """
            SELECT DISTINCT tyre_compound
            FROM laps
            WHERE session_id = :session_id
              AND tyre_compound IS NOT NULL
            ORDER BY tyre_compound ASC;
        """
        params = {"session_id": session_id}
    df = query_to_dataframe(query, params)
    if df.empty:
        return []
    return [
        str(row["tyre_compound"])
        for _, row in df.iterrows()
        if row["tyre_compound"] is not None and str(row["tyre_compound"]).upper() != "NONE"
    ]


def format_tyre_compounds_answer(
    compounds: list[str],
    event_name: str,
    driver_name: str | None = None,
    season: int = 2024,
) -> str:
    """Format deterministic answer for tyre compounds used."""
    if not compounds:
        return f"Tyre compound data is not available for the {season} {event_name}."
    joined = ", ".join(compounds)
    if driver_name:
        return f"In the {event_name}, {driver_name} used the following tyre compounds: {joined}."
    return f"The tyre compounds used in the {event_name} were {joined}."