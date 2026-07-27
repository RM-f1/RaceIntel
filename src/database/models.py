"""
SQLAlchemy ORM models for RaceIntel.

This module defines the relational database schema used by the ETL pipeline.
"""

from datetime import datetime

from sqlalchemy import (DateTime, Float, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base

# ---------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------


class Season(Base):
    """Formula 1 season."""

    __tablename__ = "seasons"

    season_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    season_year: Mapped[int] = mapped_column(
        Integer,
        unique=True,
        index=True,
        nullable=False,
    )

    events: Mapped[list["Event"]] = relationship(
        back_populates="season",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------


class Event(Base):
    """Grand Prix weekend."""

    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.season_id"),
        nullable=False,
    )

    event_name: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=False,
    )

    country_name: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    circuit_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    season: Mapped["Season"] = relationship(
        back_populates="events",
    )

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------


class Session(Base):
    """Race weekend session."""

    __tablename__ = "sessions"

    session_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.event_id"),
        nullable=False,
    )

    session_type: Mapped[str] = mapped_column(
        String(20),
        index=True,
        nullable=False,
    )

    session_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    event: Mapped["Event"] = relationship(
        back_populates="sessions",
    )

    race_results: Mapped[list["RaceResult"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    laps: Mapped[list["Lap"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    weather_observations: Mapped[list["WeatherObservation"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------


class Constructor(Base):
    """Formula 1 constructor (team)."""

    __tablename__ = "constructors"

    constructor_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    constructor_name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    drivers: Mapped[list["Driver"]] = relationship(
        back_populates="constructor",
    )

    race_results: Mapped[list["RaceResult"]] = relationship(
        back_populates="constructor",
    )


# ---------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------


class Driver(Base):
    """Formula 1 driver."""

    __tablename__ = "drivers"

    driver_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    driver_code: Mapped[str] = mapped_column(
        String(3),
        unique=True,
        index=True,
        nullable=False,
    )

    driver_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    driver_full_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    constructor_id: Mapped[int | None] = mapped_column(
        ForeignKey("constructors.constructor_id"),
        nullable=True,
    )

    constructor: Mapped["Constructor | None"] = relationship(
        back_populates="drivers",
    )

    race_results: Mapped[list["RaceResult"]] = relationship(
        back_populates="driver",
    )

    laps: Mapped[list["Lap"]] = relationship(
        back_populates="driver",
    )


# ---------------------------------------------------------------------
# Race Results
# ---------------------------------------------------------------------


class RaceResult(Base):
    """Final classification for a race session."""

    __tablename__ = "race_results"

    race_result_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.session_id"),
        nullable=False,
    )

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.driver_id"),
        nullable=False,
    )

    constructor_id: Mapped[int] = mapped_column(
        ForeignKey("constructors.constructor_id"),
        nullable=False,
    )

    grid_position: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    finish_position: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    points_scored: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    classified_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    session: Mapped["Session"] = relationship(
        back_populates="race_results",
    )

    driver: Mapped["Driver"] = relationship(
        back_populates="race_results",
    )

    constructor: Mapped["Constructor"] = relationship(
        back_populates="race_results",
    )


# ---------------------------------------------------------------------
# Laps
# ---------------------------------------------------------------------


class Lap(Base):
    """Driver lap-level data."""

    __tablename__ = "laps"

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "driver_id",
            "lap_number",
            name="uq_session_driver_lap",
        ),
    )

    lap_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.session_id"),
        nullable=False,
    )

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.driver_id"),
        nullable=False,
    )

    lap_number: Mapped[int] = mapped_column(
        Integer,
        index=True,
        nullable=False,
    )

    lap_time_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    sector_1_time_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    sector_2_time_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    sector_3_time_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    tyre_compound: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    tyre_age_laps: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    track_position: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    is_pit_out_lap: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    is_personal_best: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    session: Mapped["Session"] = relationship(
        back_populates="laps",
    )

    driver: Mapped["Driver"] = relationship(
        back_populates="laps",
    )


# ---------------------------------------------------------------------
# Weather Observations
# ---------------------------------------------------------------------


class WeatherObservation(Base):
    """Weather conditions during a session."""

    __tablename__ = "weather_observations"

    weather_observation_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.session_id"),
        nullable=False,
    )

    observation_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    air_temperature_celsius: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    track_temperature_celsius: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    humidity_percent: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    wind_speed_mps: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    rainfall: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    session: Mapped["Session"] = relationship(
        back_populates="weather_observations",
    )
    pressure_mbar: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    wind_direction_degrees: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )


# ---------------------------------------------------------------------
# ETL Runs
# ---------------------------------------------------------------------


class ETLRun(Base):
    """Audit log for ETL pipeline executions."""

    __tablename__ = "etl_runs"

    etl_run_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    started_at_utc: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    completed_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    season_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    event_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    session_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    records_loaded: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    error_message: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
