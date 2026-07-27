from pathlib import Path

import fastf1
from fastf1.core import Session

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "cache"

# Valid FastF1 session types
VALID_SESSION_TYPES = {"R", "Q", "S", "FP1", "FP2", "FP3"}


def enable_cache() -> None:

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIR))


def load_session(
    year: int,
    grand_prix: str,
    session_type: str,
) -> Session:

    if year < 1950:
        raise ValueError("Year must be 1950 or later.")

    grand_prix = grand_prix.strip()
    if not grand_prix:
        raise ValueError("Grand Prix name cannot be empty.")

    session_type = session_type.upper()
    if session_type not in VALID_SESSION_TYPES:
        raise ValueError(
            f"Invalid session type '{session_type}'. "
            f"Choose from: {', '.join(sorted(VALID_SESSION_TYPES))}."
        )

    enable_cache()

    session = fastf1.get_session(
        year=year,
        gp=grand_prix,
        identifier=session_type,
    )

    session.load()

    return session
