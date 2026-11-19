import pandas as pd
import pytest

from analytics.tyre import summarise_stints


def _rows(driver_id, rows, session_id=1):
    return pd.DataFrame(
        [
            {
                "session_id": session_id,
                "driver_id": driver_id,
                "driver_code": f"D{driver_id}",
                "lap_number": n,
                "tyre_compound": c,
                "tyre_age_laps": a,
                "lap_time_seconds": t,
            }
            for n, c, a, t in rows
        ]
    )


def test_two_stints_same_compound_stay_separate():
    laps = _rows(1, [(1, "MEDIUM", 1, 90.0), (2, "MEDIUM", 2, 90.2),
                     (3, "MEDIUM", 1, 89.0), (4, "MEDIUM", 2, 89.2)])
    out = summarise_stints(laps)
    assert len(out) == 2
    assert list(out["stint_length"]) == [2, 2]


def test_text_none_and_unknown_compounds_are_dropped():
    laps = _rows(1, [(1, "SOFT", 1, 90.0), (2, "None", 2, None),
                     (3, "UNKNOWN", 3, 95.0), (4, "SOFT", 4, 90.1)])
    out = summarise_stints(laps)
    assert set(out["tyre_compound"]) == {"SOFT"}


def test_stint_length_is_span_not_timed_laps():
    laps = _rows(1, [(1, "HARD", 1, 90.0), (2, "HARD", 2, None), (3, "HARD", 3, 90.2)])
    row = summarise_stints(laps).iloc[0]
    assert row["stint_length"] == 3
    assert row["timed_laps"] == 2
    assert row["average_lap_time"] == pytest.approx(90.1)


def test_same_driver_id_in_two_sessions_is_not_merged():
    a = _rows(1, [(1, "SOFT", 1, 90.0), (2, "SOFT", 2, 90.1)], session_id=1)
    b = _rows(1, [(1, "SOFT", 1, 91.0), (2, "SOFT", 2, 91.1)], session_id=2)
    assert len(summarise_stints(pd.concat([a, b]))) == 2