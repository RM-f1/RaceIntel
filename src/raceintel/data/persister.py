"""
Transactional SQLite Data Persister for RaceIntel.

Safely inserts and upserts multi-season Formula 1 data with duplicate prevention,
idempotent incremental skipping, and full transaction rollback on failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DBSession

from database.connection import SessionLocal
from database.models import (
    Constructor,
    Driver,
    Event,
    Lap,
    RaceResult,
    Season,
    Session as RaceSession,
    WeatherObservation,
)
from raceintel.data.fetcher import FetchedSessionData

logger = logging.getLogger(__name__)


@dataclass
class PersistenceSummary:
    season_year: int
    round_number: int
    session_id: int | None
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    status: str = "COMPLETED"
    data_categories: str = ""
    error_message: str | None = None


class SessionPersister:
    """Manages transactional database persistence for multi-season F1 sessions."""

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or SessionLocal

    def persist_session(
        self,
        data: FetchedSessionData,
        incremental: bool = True,
        force_refresh: bool = False,
    ) -> PersistenceSummary:
        """
        Persist fetched session data safely within a single transaction.
        If force_refresh is True, existing session records are replaced.
        If incremental is True, existing populated tables are preserved.
        """
        summary = PersistenceSummary(
            season_year=data.season_year,
            round_number=data.round_number,
            session_id=None,
        )
        cats: list[str] = []

        db: DBSession = self.session_factory()
        try:
            # 1. Season
            season = db.execute(
                select(Season).where(Season.season_year == data.season_year)
            ).scalar_one_or_none()
            if season is None:
                season = Season(season_year=data.season_year)
                db.add(season)
                db.flush()
                summary.records_inserted += 1
            else:
                summary.records_skipped += 1

            # 2. Event
            event = db.execute(
                select(Event).where(
                    Event.season_id == season.season_id,
                    Event.event_name == data.event_name,
                )
            ).scalar_one_or_none()

            if event is None:
                event = Event(
                    season_id=season.season_id,
                    event_name=data.event_name,
                    country_name=data.country_name,
                    circuit_name=data.circuit_name,
                    round_number=data.round_number,
                )
                db.add(event)
                db.flush()
                summary.records_inserted += 1
            else:
                updated = False
                if event.round_number != data.round_number:
                    event.round_number = data.round_number
                    updated = True
                if not event.country_name and data.country_name:
                    event.country_name = data.country_name
                    updated = True
                if not event.circuit_name and data.circuit_name:
                    event.circuit_name = data.circuit_name
                    updated = True
                if updated:
                    db.flush()
                    summary.records_updated += 1
                else:
                    summary.records_skipped += 1

            # 3. Session
            session_rec = db.execute(
                select(RaceSession).where(
                    RaceSession.event_id == event.event_id,
                    RaceSession.session_type == data.session_type,
                )
            ).scalar_one_or_none()

            if session_rec is None:
                session_rec = RaceSession(
                    event_id=event.event_id,
                    session_type=data.session_type,
                    session_name=data.session_name,
                )
                db.add(session_rec)
                db.flush()
                summary.records_inserted += 1
            else:
                summary.records_skipped += 1

            summary.session_id = session_rec.session_id
            sid = session_rec.session_id

            # 4. Constructors
            con_id_map: dict[str, int] = {}
            for cname in data.constructors:
                con = db.execute(
                    select(Constructor).where(Constructor.constructor_name == cname)
                ).scalar_one_or_none()
                if con is None:
                    con = Constructor(constructor_name=cname)
                    db.add(con)
                    db.flush()
                    summary.records_inserted += 1
                con_id_map[cname] = con.constructor_id

            # Ensure all constructors referenced in results are present
            for r in data.results:
                rteam = r.get("constructor_name")
                if rteam and rteam not in con_id_map:
                    con = db.execute(
                        select(Constructor).where(Constructor.constructor_name == rteam)
                    ).scalar_one_or_none()
                    if con is None:
                        con = Constructor(constructor_name=rteam)
                        db.add(con)
                        db.flush()
                        summary.records_inserted += 1
                    con_id_map[rteam] = con.constructor_id

            # 5. Drivers
            drv_id_map: dict[str, int] = {}
            for d in data.drivers:
                dcode = d["driver_code"]
                team_id = con_id_map.get(d.get("constructor_name"))
                drv = db.execute(
                    select(Driver).where(Driver.driver_code == dcode)
                ).scalar_one_or_none()

                if drv is None:
                    drv = Driver(
                        driver_code=dcode,
                        driver_number=d.get("driver_number"),
                        driver_full_name=d["driver_full_name"],
                        constructor_id=team_id,
                    )
                    db.add(drv)
                    db.flush()
                    summary.records_inserted += 1
                else:
                    changed = False
                    if team_id and drv.constructor_id != team_id:
                        drv.constructor_id = team_id
                        changed = True
                    if d.get("driver_number") is not None and drv.driver_number is None:
                        drv.driver_number = d["driver_number"]
                        changed = True
                    if changed:
                        db.flush()
                        summary.records_updated += 1
                    else:
                        summary.records_skipped += 1

                drv_id_map[dcode] = drv.driver_id

            # 6. Race Results
            existing_rr_count = db.execute(
                select(RaceResult).where(RaceResult.session_id == sid)
            ).scalars().all()

            if data.has_results and data.results:
                cats.append("results")
                if len(existing_rr_count) > 0:
                    if force_refresh:
                        db.execute(delete(RaceResult).where(RaceResult.session_id == sid))
                        db.flush()
                        for r in data.results:
                            grid_pos = int(r["grid_position"]) if r.get("grid_position") is not None else None
                            fin_pos = int(r["finish_position"]) if r.get("finish_position") is not None else None
                            pts = float(r.get("points_scored", 0.0)) if r.get("points_scored") is not None else 0.0
                            db.add(
                                RaceResult(
                                    session_id=sid,
                                    driver_id=drv_id_map[r["driver_code"]],
                                    constructor_id=con_id_map[r["constructor_name"]],
                                    grid_position=grid_pos,
                                    finish_position=fin_pos,
                                    points_scored=pts,
                                    classified_status=r.get("classified_status"),
                                )
                            )
                        db.flush()
                        summary.records_updated += len(data.results)
                    else:
                        summary.records_skipped += len(existing_rr_count)
                else:
                    for r in data.results:
                        grid_pos = int(r["grid_position"]) if r.get("grid_position") is not None else None
                        fin_pos = int(r["finish_position"]) if r.get("finish_position") is not None else None
                        pts = float(r.get("points_scored", 0.0)) if r.get("points_scored") is not None else 0.0
                        db.add(
                            RaceResult(
                                session_id=sid,
                                driver_id=drv_id_map[r["driver_code"]],
                                constructor_id=con_id_map[r["constructor_name"]],
                                grid_position=grid_pos,
                                finish_position=fin_pos,
                                points_scored=pts,
                                classified_status=r.get("classified_status"),
                            )
                        )
                    db.flush()
                    summary.records_inserted += len(data.results)

            # 7. Laps
            existing_laps_count = db.execute(
                select(Lap).where(Lap.session_id == sid)
            ).scalars().all()

            if data.has_laps and data.laps:
                cats.append("laps")
                if len(existing_laps_count) > 0:
                    if force_refresh:
                        db.execute(delete(Lap).where(Lap.session_id == sid))
                        db.flush()
                        for l in data.laps:
                            db.add(
                                Lap(
                                    session_id=sid,
                                    driver_id=drv_id_map[l["driver_code"]],
                                    lap_number=l["lap_number"],
                                    lap_time_seconds=l.get("lap_time_seconds"),
                                    sector_1_time_seconds=l.get("sector_1_time_seconds"),
                                    sector_2_time_seconds=l.get("sector_2_time_seconds"),
                                    sector_3_time_seconds=l.get("sector_3_time_seconds"),
                                    tyre_compound=l.get("tyre_compound"),
                                    tyre_age_laps=l.get("tyre_age_laps"),
                                    track_position=l.get("track_position"),
                                    is_pit_out_lap=l.get("is_pit_out_lap", False),
                                    is_personal_best=l.get("is_personal_best", False),
                                )
                            )
                        db.flush()
                        summary.records_updated += len(data.laps)
                    else:
                        summary.records_skipped += len(existing_laps_count)
                else:
                    for l in data.laps:
                        db.add(
                            Lap(
                                session_id=sid,
                                driver_id=drv_id_map[l["driver_code"]],
                                lap_number=l["lap_number"],
                                lap_time_seconds=l.get("lap_time_seconds"),
                                sector_1_time_seconds=l.get("sector_1_time_seconds"),
                                sector_2_time_seconds=l.get("sector_2_time_seconds"),
                                sector_3_time_seconds=l.get("sector_3_time_seconds"),
                                tyre_compound=l.get("tyre_compound"),
                                tyre_age_laps=l.get("tyre_age_laps"),
                                track_position=l.get("track_position"),
                                is_pit_out_lap=l.get("is_pit_out_lap", False),
                                is_personal_best=l.get("is_personal_best", False),
                            )
                        )
                    db.flush()
                    summary.records_inserted += len(data.laps)

            # 8. Weather Observations
            existing_wx_count = db.execute(
                select(WeatherObservation).where(WeatherObservation.session_id == sid)
            ).scalars().all()

            if data.has_weather and data.weather:
                cats.append("weather")
                if len(existing_wx_count) > 0:
                    if force_refresh:
                        db.execute(delete(WeatherObservation).where(WeatherObservation.session_id == sid))
                        db.flush()
                        for w in data.weather:
                            db.add(
                                WeatherObservation(
                                    session_id=sid,
                                    observation_time=w["timestamp"],
                                    air_temperature_celsius=w.get("air_temperature_celsius"),
                                    track_temperature_celsius=w.get("track_temperature_celsius"),
                                    humidity_percent=w.get("humidity_percent"),
                                    pressure_mbar=w.get("pressure_mbar"),
                                    wind_speed_mps=w.get("wind_speed_mps"),
                                    wind_direction_degrees=w.get("wind_direction_degrees"),
                                    rainfall=w.get("rainfall", False),
                                )
                            )
                        db.flush()
                        summary.records_updated += len(data.weather)
                    else:
                        summary.records_skipped += len(existing_wx_count)
                else:
                    for w in data.weather:
                        db.add(
                            WeatherObservation(
                                session_id=sid,
                                observation_time=w["timestamp"],
                                air_temperature_celsius=w.get("air_temperature_celsius"),
                                track_temperature_celsius=w.get("track_temperature_celsius"),
                                humidity_percent=w.get("humidity_percent"),
                                pressure_mbar=w.get("pressure_mbar"),
                                wind_speed_mps=w.get("wind_speed_mps"),
                                wind_direction_degrees=w.get("wind_direction_degrees"),
                                rainfall=w.get("rainfall", False),
                            )
                        )
                    db.flush()
                    summary.records_inserted += len(data.weather)

            db.commit()

            if not data.has_results:
                summary.status = "SKIPPED"
                summary.data_categories = "schedule"
            elif data.has_laps and data.has_weather:
                summary.status = "COMPLETED"
                summary.data_categories = ",".join(cats)
            else:
                summary.status = "PARTIAL"
                summary.data_categories = ",".join(cats) if cats else "results"

            return summary

        except Exception as exc:
            db.rollback()
            summary.status = "FAILED"
            summary.error_message = str(exc)
            logger.error(f"Persistence error for {data.season_year} R{data.round_number}: {exc}", exc_info=True)
            return summary
        finally:
            db.close()
