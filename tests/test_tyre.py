from src.analytics.tyre import (
    get_tyre_usage,
    get_compound_performance,
    get_tyre_degradation,
    get_stint_summary,
)


def test_tyre_usage():

    df = get_tyre_usage(1)

    assert not df.empty
    assert "laps_completed" in df.columns


def test_compound_performance():

    df = get_compound_performance(1)

    assert not df.empty
    assert "average_lap_time_seconds" in df.columns


def test_tyre_degradation():

    df = get_tyre_degradation(1)

    assert not df.empty
    assert "tyre_age_laps" in df.columns


def test_stint_summary():

    df = get_stint_summary(1)

    assert not df.empty
    assert "stint_length" in df.columns