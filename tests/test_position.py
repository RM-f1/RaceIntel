import pytest
pytestmark = pytest.mark.requires_data
import pytest
from src.analytics.position import (
    get_position_changes,
    get_biggest_movers,
    get_classification_summary,
)
from src.database.connection import query_to_dataframe


def get_test_session_id():
    df = query_to_dataframe(
        """
        SELECT session_id
        FROM sessions
        WHERE session_type = 'Race'
        ORDER BY session_id
        LIMIT 1;
        """,
        {},
    )

    assert not df.empty, "No race session exists in the database."

    return int(df.iloc[0]["session_id"])


def test_position_changes_not_empty():

    session_id = get_test_session_id()

    df = get_position_changes(session_id)

    assert not df.empty
    assert "positions_gained" in df.columns
    assert len(df) == 20


def test_biggest_movers_sorted():

    session_id = get_test_session_id()

    df = get_biggest_movers(session_id)

    assert not df.empty

    assert df["positions_gained"].is_monotonic_decreasing


def test_classification_summary():

    session_id = get_test_session_id()

    df = get_classification_summary(session_id)

    assert not df.empty
    assert "classified_status" in df.columns
    assert len(df) == 20