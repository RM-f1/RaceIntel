"""
Session Data Fetcher for RaceIntel.

Retrieves session data from FastF1 with graceful adaptive degradation
when telemetry or timing streams are unavailable for historical or upcoming rounds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fastf1
import pandas as pd

from raceintel.data.schedule import CACHE_DIR, EventScheduleItem

logger = logging.getLogger(__name__)

CONSTRUCTOR_CANONICAL_MAP = {
    "Red Bull": "Red Bull Racing",
    "Red Bull Racing": "Red Bull Racing",
    "Alpine F1 Team": "Alpine",
    "Alpine": "Alpine",
    "RB F1 Team": "RB",
    "RB": "RB",
    "Sauber": "Kick Sauber",
    "Kick Sauber": "Kick Sauber",
    "Haas": "Haas F1 Team",
    "Haas F1 Team": "Haas F1 Team",
}


def canonical_constructor_name(raw_name: str) -> str:
    cleaned = (raw_name or "").strip()
    return CONSTRUCTOR_CANONICAL_MAP.get(cleaned, cleaned)


@dataclass
class FetchedSessionData:
    season_year: int
    round_number: int
    event_name: str
    country_name: str = "Unknown"
    circuit_name: str = "Unknown"
    session_type: str = "Race"
    session_name: str = "Race"
    has_results: bool = False
    has_laps: bool = False
    has_weather: bool = False
    constructors: list[str] = field(default_factory=list)
    drivers: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    laps: list[dict[str, Any]] = field(default_factory=list)
    weather: list[dict[str, Any]] = field(default_factory=list)
    warning_notes: list[str] = field(default_factory=list)
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.results and not self.has_results:
            self.has_results = True
        if self.laps and not self.has_laps:
            self.has_laps = True
        if self.weather and not self.has_weather:
            self.has_weather = True


class SessionFetcher:
    """Fetches race sessions from FastF1 with fallback handling for partial telemetry."""

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            fastf1.Cache.enable_cache(str(self.cache_dir))
        except Exception:
            pass

    def fetch_session(self, event_item: EventScheduleItem) -> FetchedSessionData:
        """
        Fetch session results, laps, and weather data for a single Grand Prix round.
        """
        season = event_item.season_year
        rnd = event_item.round_number
        ev_name = event_item.event_name
        country = event_item.country_name
        circuit = event_item.circuit_name

        data = FetchedSessionData(
            season_year=season,
            round_number=rnd,
            event_name=ev_name,
            country_name=country,
            circuit_name=circuit,
            session_type=event_item.session_type,
            session_name=event_item.session_name,
        )

        if not event_item.is_completed:
            data.warning_notes.append("Session is scheduled/upcoming; skipping remote fetch.")
            data.error_message = "Session is scheduled/upcoming"
            return data

        # Determine FastF1 session identifier based on session_type
        if event_item.session_type.lower() == "sprint":
            f1_identifier = "Sprint"
        elif event_item.session_type.lower() == "race":
            f1_identifier = "R"
        else:
            f1_identifier = event_item.session_name or event_item.session_type

        try:
            session = fastf1.get_session(season, rnd, f1_identifier)
        except Exception as exc:
            data.error_message = f"Failed to acquire session descriptor: {exc}"
            return data

        # Try full load (results + laps + weather)
        full_loaded = False
        try:
            session.load(telemetry=False, messages=False)
            full_loaded = True
        except Exception as exc:
            data.warning_notes.append(f"Full session load failed ({type(exc).__name__}: {exc}); falling back to results-only load.")
            try:
                session.load(laps=False, telemetry=False, weather=False, messages=False)
            except Exception as res_exc:
                data.error_message = f"Session results load failed: {res_exc}"
                return data

        # 1. Transform Results
        if hasattr(session, "results") and session.results is not None and not session.results.empty:
            res_df = session.results
            constructors_set: set[str] = set()
            drivers_list: list[dict[str, Any]] = []
            results_list: list[dict[str, Any]] = []

            for _, row in res_df.iterrows():
                code = str(row.get("Abbreviation") or "").strip()
                if not code or code == "None":
                    continue

                raw_team = str(row.get("TeamName") or "Unknown").strip()
                team_name = canonical_constructor_name(raw_team)
                constructors_set.add(team_name)

                full_name = str(row.get("FullName") or code).strip()
                drv_num = None
                if pd.notna(row.get("DriverNumber")):
                    try:
                        drv_num = int(row.get("DriverNumber"))
                    except Exception:
                        drv_num = None

                drivers_list.append(
                    {
                        "driver_code": code,
                        "driver_number": drv_num,
                        "driver_full_name": full_name,
                        "constructor_name": team_name,
                    }
                )

                grid_pos = int(row["GridPosition"]) if pd.notna(row.get("GridPosition")) else None
                fin_pos = int(row["Position"]) if pd.notna(row.get("Position")) else None
                pts = float(row["Points"]) if pd.notna(row.get("Points")) else 0.0
                status_str = str(row.get("Status") or "Finished").strip()

                results_list.append(
                    {
                        "driver_code": code,
                        "constructor_name": team_name,
                        "grid_position": grid_pos,
                        "finish_position": fin_pos,
                        "points_scored": pts,
                        "classified_status": status_str,
                    }
                )

            data.constructors = sorted(list(constructors_set))
            data.drivers = drivers_list
            data.results = results_list
            data.has_results = len(results_list) > 0

        # 2. Transform Laps (if loaded)
        if full_loaded:
            try:
                laps_df = session.laps
                if laps_df is not None and not laps_df.empty:
                    laps_list: list[dict[str, Any]] = []
                    for _, lap in laps_df.iterrows():
                        dcode = str(lap.get("Driver") or "").strip()
                        if not dcode:
                            continue
                        lap_num = int(lap["LapNumber"]) if pd.notna(lap.get("LapNumber")) else None
                        if lap_num is None:
                            continue

                        lap_sec = None
                        lt = lap.get("LapTime")
                        if pd.notna(lt) and hasattr(lt, "total_seconds"):
                            lap_sec = lt.total_seconds()

                        s1_sec = None
                        s1 = lap.get("Sector1Time")
                        if pd.notna(s1) and hasattr(s1, "total_seconds"):
                            s1_sec = s1.total_seconds()

                        s2_sec = None
                        s2 = lap.get("Sector2Time")
                        if pd.notna(s2) and hasattr(s2, "total_seconds"):
                            s2_sec = s2.total_seconds()

                        s3_sec = None
                        s3 = lap.get("Sector3Time")
                        if pd.notna(s3) and hasattr(s3, "total_seconds"):
                            s3_sec = s3.total_seconds()

                        compound = str(lap.get("Compound")).strip() if pd.notna(lap.get("Compound")) else None
                        tyre_age = int(lap["TyreLife"]) if pd.notna(lap.get("TyreLife")) else None
                        trk_pos = int(lap["Position"]) if pd.notna(lap.get("Position")) else None
                        is_pit_out = bool(pd.notna(lap.get("PitOutTime")))
                        is_pb = bool(lap.get("IsPersonalBest") is True)

                        laps_list.append(
                            {
                                "driver_code": dcode,
                                "lap_number": lap_num,
                                "lap_time_seconds": lap_sec,
                                "sector_1_time_seconds": s1_sec,
                                "sector_2_time_seconds": s2_sec,
                                "sector_3_time_seconds": s3_sec,
                                "tyre_compound": compound,
                                "tyre_age_laps": tyre_age,
                                "track_position": trk_pos,
                                "is_pit_out_lap": is_pit_out,
                                "is_personal_best": is_pb,
                            }
                        )
                    data.laps = laps_list
                    data.has_laps = len(laps_list) > 0
            except Exception as exc:
                data.warning_notes.append(f"Lap extraction skipped: {exc}")

            # 3. Transform Weather (if loaded)
            try:
                wx_df = session.weather_data
                if wx_df is not None and not wx_df.empty:
                    wx_list: list[dict[str, Any]] = []
                    for _, wrow in wx_df.iterrows():
                        t_sec = wrow["Time"].total_seconds() if hasattr(wrow.get("Time"), "total_seconds") else 0.0
                        wx_list.append(
                            {
                                "timestamp": float(t_sec),
                                "air_temperature_celsius": float(wrow["AirTemp"]) if pd.notna(wrow.get("AirTemp")) else None,
                                "track_temperature_celsius": float(wrow["TrackTemp"]) if pd.notna(wrow.get("TrackTemp")) else None,
                                "humidity_percent": float(wrow["Humidity"]) if pd.notna(wrow.get("Humidity")) else None,
                                "pressure_mbar": float(wrow["Pressure"]) if pd.notna(wrow.get("Pressure")) else None,
                                "wind_speed_mps": float(wrow["WindSpeed"]) if pd.notna(wrow.get("WindSpeed")) else None,
                                "wind_direction_degrees": int(wrow["WindDirection"]) if pd.notna(wrow.get("WindDirection")) else None,
                                "rainfall": bool(wrow.get("Rainfall") is True or wrow.get("Rainfall") == 1),
                            }
                        )
                    data.weather = wx_list
                    data.has_weather = len(wx_list) > 0
            except Exception as exc:
                data.warning_notes.append(f"Weather extraction skipped: {exc}")

        return data
