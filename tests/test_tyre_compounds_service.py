"""Tests for race_service.get_tyre_compounds_for_session null-skipping fix.

No database required: we monkey-patch query_to_dataframe.
"""

from unittest.mock import patch

import pandas as pd
import pytest

import raceintel.services.race_service as race_service


def _patch_query(df: pd.DataFrame):
    """Return a context manager that replaces query_to_dataframe with a stub."""
    return patch.object(race_service, "query_to_dataframe", return_value=df)


def test_null_compound_is_skipped():
    """None / NaN values must not appear in the returned list."""
    df = pd.DataFrame({"tyre_compound": ["SOFT", None, "MEDIUM"]})
    with _patch_query(df):
        result = race_service.get_tyre_compounds_for_session(session_id=1)
    assert "None" not in result
    assert result == ["SOFT", "MEDIUM"]


def test_string_none_compound_is_skipped():
    """The literal string 'None' must be excluded."""
    df = pd.DataFrame({"tyre_compound": ["HARD", "None", "SOFT"]})
    with _patch_query(df):
        result = race_service.get_tyre_compounds_for_session(session_id=1)
    assert "None" not in result
    assert "HARD" in result
    assert "SOFT" in result


def test_all_valid_compounds_returned():
    """When all compounds are valid, all are returned unchanged."""
    df = pd.DataFrame({"tyre_compound": ["SOFT", "MEDIUM", "HARD"]})
    with _patch_query(df):
        result = race_service.get_tyre_compounds_for_session(session_id=1)
    assert result == ["SOFT", "MEDIUM", "HARD"]


def test_empty_dataframe_returns_empty_list():
    """Empty query result must return an empty list (unchanged behaviour)."""
    df = pd.DataFrame({"tyre_compound": pd.Series([], dtype=object)})
    with _patch_query(df):
        result = race_service.get_tyre_compounds_for_session(session_id=1)
    assert result == []


def test_all_null_compounds_returns_empty_list():
    """If every row is null, the list must be empty."""
    df = pd.DataFrame({"tyre_compound": [None, None]})
    with _patch_query(df):
        result = race_service.get_tyre_compounds_for_session(session_id=1)
    assert result == []
