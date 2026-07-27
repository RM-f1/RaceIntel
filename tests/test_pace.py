from src.analytics.pace import (
    get_fastest_laps,
    get_average_pace,
    get_driver_best_laps,
    get_lap_consistency,
)


def test_fastest_laps_not_empty():
    df = get_fastest_laps(1)

    assert not df.empty
    assert "driver_code" in df.columns
    assert "fastest_lap_seconds" in df.columns
    assert len(df) >= 19


def test_average_pace_not_empty():
    df = get_average_pace(1)

    assert not df.empty
    assert "driver_code" in df.columns
    assert "average_lap_time_seconds" in df.columns
    assert len(df) >= 19


def test_driver_best_laps():
    df = get_driver_best_laps(1)

    assert not df.empty
    assert "driver_code" in df.columns
    assert "best_lap_seconds" in df.columns
    assert len(df) >= 19


def test_lap_consistency():
    df = get_lap_consistency(1)

    assert not df.empty
    assert "driver_code" in df.columns
    assert "lap_time_std_dev_seconds" in df.columns
    assert len(df) >= 19

    assert (df["lap_time_std_dev_seconds"] >= 0).all()