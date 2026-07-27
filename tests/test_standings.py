from src.analytics.standings import (
    get_driver_standings,
    get_constructor_standings,
)

def test_driver_standings_not_empty():

    df = get_driver_standings(1)

    assert not df.empty

    assert "driver_code" in df.columns

    assert "points_scored" in df.columns


def test_constructor_standings_not_empty():

    df = get_constructor_standings(1)

    assert not df.empty

    assert "constructor_name" in df.columns

    assert "total_points" in df.columns