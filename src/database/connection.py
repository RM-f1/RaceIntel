"""
Database connection configuration for RaceIntel.

This module provides:
- SQLAlchemy engine
- Session factory
- Declarative base
- Helper for executing SQL queries
"""

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ---------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_FULL_DB_PATH = DATA_DIR / "raceintel.db"
_FIXTURE_DB_PATH = PROJECT_ROOT / "tests" / "fixtures" / "ci.db"


def resolve_database_path() -> Path:
    """Resolve the active SQLite database path.

    Priority:
    1. Explicit ``RACEINTEL_DB_PATH`` environment variable (if set).
    2. Full local database ``data/raceintel.db`` (if present and non-empty).
    3. Seeded CI fixture ``tests/fixtures/ci.db`` (if present and non-empty).
    4. Default path ``data/raceintel.db``.
    """
    env_path = os.environ.get("RACEINTEL_DB_PATH", "").strip()
    if env_path:
        return Path(env_path)
    if _FULL_DB_PATH.is_file() and _FULL_DB_PATH.stat().st_size > 0:
        return _FULL_DB_PATH
    if _FIXTURE_DB_PATH.is_file() and _FIXTURE_DB_PATH.stat().st_size > 0:
        return _FIXTURE_DB_PATH
    return _FULL_DB_PATH


DATABASE_PATH = resolve_database_path()

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


# ---------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------


def query_to_dataframe(
    query: str,
    params: dict | None = None,
) -> pd.DataFrame:
    """
    Execute a SQL query and return the results as a pandas DataFrame.

    Args:
        query: SQL query string.
        params: Optional SQL parameters.

    Returns:
        pandas.DataFrame containing query results.
    """

    with SessionLocal() as session:
        result = session.execute(
            text(query),
            params or {},
        )

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys(),
        )