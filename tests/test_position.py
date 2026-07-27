from src.analytics.position import (
    get_position_changes,
    get_biggest_movers,
    get_classification_summary,
)


def test_position_changes_not_empty():

    df = get_position_changes(1)

    assert not df.empty

    assert "positions_gained" in df.columns

    assert len(df) == 20


def test_biggest_movers_sorted():

    df = get_biggest_movers(1)

    assert not df.empty

    assert (
        df["positions_gained"].is_monotonic_decreasing
    )


def test_classification_summary():

    df = get_classification_summary(1)

    assert not df.empty

    assert "classified_status" in df.columns

    assert len(df) == 20