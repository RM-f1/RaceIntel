import pytest

from src.data.fastf1_loader import CACHE_DIR, load_session


def test_cache_directory_exists():
    """Verify that the FastF1 cache directory exists."""
    assert CACHE_DIR.exists()


def test_load_valid_session():
    """Verify that a valid race session loads successfully."""
    session = load_session(2024, "British Grand Prix", "R")

    assert session.event["EventName"] == "British Grand Prix"
    assert session.name == "Race"


def test_invalid_year():
    """Year before the first Formula 1 season should raise ValueError."""
    with pytest.raises(ValueError, match="Year must be 1950 or later."):
        load_session(1949, "British Grand Prix", "R")


def test_empty_grand_prix():
    """Empty Grand Prix name should raise ValueError."""
    with pytest.raises(ValueError, match="Grand Prix name cannot be empty."):
        load_session(2024, "", "R")


def test_invalid_session_type():
    """Invalid session type should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid session type"):
        load_session(2024, "British Grand Prix", "XYZ")
