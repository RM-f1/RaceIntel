"""
Extract data from FastF1.

This module is responsible for retrieving raw Formula 1 session data.
No transformation or database operations should occur here.
"""

from pathlib import Path

from fastf1 import Cache, get_session

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "cache"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
Cache.enable_cache(str(CACHE_DIR))


def extract_session(
    season_year: int,
    event_name: str,
    session_type: str,
):

    session = get_session(
        season_year,
        event_name,
        session_type,
    )

    session.load()

    return session
