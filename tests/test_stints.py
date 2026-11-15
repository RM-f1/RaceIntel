import pandas as pd

from analytics.stints import derive_stints


def _laps(driver_id, rows):
    return pd.DataFrame(
        [
            {"driver_id": driver_id, "lap_number": n, "tyre_compound": c, "tyre_age_laps": a}
            for n, c, a in rows
        ]
    )


def test_compound_change_starts_new_stint():
    laps = _laps(1, [(1, "MEDIUM", 1), (2, "MEDIUM", 2), (3, "HARD", 1), (4, "HARD", 2)])
    stints = derive_stints(laps)
    assert list(stints["tyre_compound"]) == ["MEDIUM", "HARD"]
    assert list(stints["laps"]) == [2, 2]


def test_same_compound_new_set_is_a_new_stint():
    laps = _laps(1, [(1, "MEDIUM", 1), (2, "MEDIUM", 2), (3, "MEDIUM", 5), (4, "MEDIUM", 6)])
    assert len(derive_stints(laps)) == 2


def test_text_none_compound_is_ignored():
    laps = _laps(1, [(1, "SOFT", 1), (2, "None", 2), (3, "SOFT", 3)])
    stints = derive_stints(laps)
    assert len(stints) == 1 and stints.loc[0, "laps"] == 2


def test_drivers_are_separate():
    laps = pd.concat([_laps(1, [(1, "SOFT", 1), (2, "SOFT", 2)]), _laps(2, [(1, "HARD", 1)])])
    assert len(derive_stints(laps)) == 2


def test_missing_lap_row_does_not_split_stint():
    laps = _laps(1, [(1, "HARD", 1), (2, "HARD", 2), (4, "HARD", 4), (5, "HARD", 5)])
    assert len(derive_stints(laps)) == 1


def test_null_age_out_lap_joins_new_stint():
    laps = _laps(1, [(1, "MEDIUM", 1), (2, "MEDIUM", 2), (3, "MEDIUM", None), (4, "MEDIUM", 2)])
    stints = derive_stints(laps)
    assert len(stints) == 2
    assert stints.loc[1, "start_lap"] == 3
