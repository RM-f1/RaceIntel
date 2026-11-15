"""
Schedule Discovery Service for RaceIntel.

Discovers championship event schedules across seasons (2022–2026) using FastF1,
distinguishing completed events from scheduled/upcoming events without assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fastf1
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / "data" / "cache"


@dataclass
class EventScheduleItem:
    season_year: int
    round_number: int
    event_name: str
    country_name: str
    circuit_name: str
    event_format: str
    event_date: datetime | None
    session_name: str = "Race"
    session_type: str = "Race"
    session_date_utc: datetime | None = None
    is_completed: bool = False


@dataclass
class SeasonSchedule:
    season_year: int
    total_rounds: int
    events: list[EventScheduleItem] = field(default_factory=list)

    @property
    def completed_rounds(self) -> list[EventScheduleItem]:
        return [e for e in self.events if e.is_completed]

    @property
    def upcoming_rounds(self) -> list[EventScheduleItem]:
        return [e for e in self.events if not e.is_completed]


class ScheduleDiscovery:
    """Discovers and normalizes season calendars and event completion status."""

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            fastf1.Cache.enable_cache(str(self.cache_dir))
        except Exception:
            pass

    def get_schedule(
        self,
        season_year: int,
        round_number: int | None = None,
    ) -> SeasonSchedule:
        """
        Fetch and parse the championship event schedule for a given season.
        Filters out pre-season testing events (RoundNumber <= 0).
        """
        raw_schedule = fastf1.get_event_schedule(season_year, include_testing=False)
        valid_schedule = raw_schedule[raw_schedule["RoundNumber"] > 0].copy()

        now_utc = datetime.now(timezone.utc)
        items: list[EventScheduleItem] = []

        for _, row in valid_schedule.iterrows():
            rnd = int(row["RoundNumber"])
            if round_number is not None and rnd != round_number:
                continue

            ev_name = str(row["EventName"]).strip()
            country = str(row["Country"]).strip() if pd.notna(row["Country"]) else "Unknown"
            circuit = str(row["Location"]).strip() if pd.notna(row["Location"]) else "Unknown"
            fmt = str(row["EventFormat"]).strip() if "EventFormat" in row and pd.notna(row["EventFormat"]) else "conventional"

            ev_date = None
            if pd.notna(row["EventDate"]):
                if isinstance(row["EventDate"], datetime):
                    ev_date = row["EventDate"]
                else:
                    try:
                        ev_date = pd.to_datetime(row["EventDate"]).to_pydatetime()
                    except Exception:
                        ev_date = None

            ses_date_utc = None
            if "Session5DateUtc" in row and pd.notna(row["Session5DateUtc"]):
                try:
                    ses_date_utc = pd.to_datetime(row["Session5DateUtc"]).to_pydatetime()
                    if ses_date_utc.tzinfo is None:
                        ses_date_utc = ses_date_utc.replace(tzinfo=timezone.utc)
                except Exception:
                    ses_date_utc = None
            elif ev_date is not None:
                if ev_date.tzinfo is None:
                    ses_date_utc = ev_date.replace(tzinfo=timezone.utc)
                else:
                    ses_date_utc = ev_date

            # In seasons prior to current year (e.g. 2022, 2023, 2024, 2025 in Nov 2026), all are historical
            # In current year (2026), mark completed based on session date vs now
            is_completed = False
            if season_year < now_utc.year:
                is_completed = True
            elif season_year == now_utc.year:
                if ses_date_utc and ses_date_utc <= now_utc:
                    is_completed = True
            else:
                is_completed = False

            # Discover Sprint session if present (Session1 to Session5 == 'Sprint')
            for i in (1, 2, 3, 4, 5):
                ses_val = str(row.get(f"Session{i}") or "").strip()
                if ses_val.lower() == "sprint":
                    sprint_date_utc = None
                    if f"Session{i}DateUtc" in row and pd.notna(row[f"Session{i}DateUtc"]):
                        try:
                            sprint_date_utc = pd.to_datetime(row[f"Session{i}DateUtc"]).to_pydatetime()
                            if sprint_date_utc.tzinfo is None:
                                sprint_date_utc = sprint_date_utc.replace(tzinfo=timezone.utc)
                        except Exception:
                            sprint_date_utc = None
                    elif ev_date is not None:
                        sprint_date_utc = ev_date if ev_date.tzinfo is not None else ev_date.replace(tzinfo=timezone.utc)

                    is_sprint_completed = False
                    if season_year < now_utc.year:
                        is_sprint_completed = True
                    elif season_year == now_utc.year:
                        if sprint_date_utc and sprint_date_utc <= now_utc:
                            is_sprint_completed = True
                    else:
                        is_sprint_completed = False

                    items.append(
                        EventScheduleItem(
                            season_year=season_year,
                            round_number=rnd,
                            event_name=ev_name,
                            country_name=country,
                            circuit_name=circuit,
                            event_format=fmt,
                            event_date=ev_date,
                            session_name="Sprint",
                            session_type="Sprint",
                            session_date_utc=sprint_date_utc,
                            is_completed=is_sprint_completed,
                        )
                    )
                    break

            # Grand Prix main race session
            items.append(
                EventScheduleItem(
                    season_year=season_year,
                    round_number=rnd,
                    event_name=ev_name,
                    country_name=country,
                    circuit_name=circuit,
                    event_format=fmt,
                    event_date=ev_date,
                    session_name="Race",
                    session_type="Race",
                    session_date_utc=ses_date_utc,
                    is_completed=is_completed,
                )
            )

        return SeasonSchedule(
            season_year=season_year,
            total_rounds=len(valid_schedule),
            events=items,
        )
