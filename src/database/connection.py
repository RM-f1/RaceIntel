"""
Database connection configuration for RaceIntel.

This module provides:
- SQLAlchemy engine
- Session factory
- Declarative base
- SQLite database configuration

All database interactions throughout the project should use this module.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ---------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_DIR / "raceintel.db"

DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# ---------------------------------------------------------------------
# SQLAlchemy Engine
# ---------------------------------------------------------------------

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

# ---------------------------------------------------------------------
# Session Factory
# ---------------------------------------------------------------------

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------
# Declarative Base
# ---------------------------------------------------------------------


class Base(DeclarativeBase):
    """Base class inherited by every ORM model."""

    pass
