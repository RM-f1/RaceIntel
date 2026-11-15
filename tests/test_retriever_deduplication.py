import pytest
pytestmark = pytest.mark.requires_data
from unittest.mock import MagicMock
import pytest

from raceintel.retrieval.retriever import Retriever


@pytest.fixture
def mock_retriever():
    """Retriever instance with mocked ChromaClient and collection."""
    retriever = Retriever()
    retriever.client = MagicMock()
    retriever.client.collection = MagicMock()
    return retriever


def test_deduplicate_identical_documents_different_ids(mock_retriever):
    """
    Two identical documents with different IDs (e.g. 2024_1 and 2024_12 from British GP).
    Only one should be returned.
    """
    report_text = (
        "Season: 2024\n"
        "Grand Prix: British Grand Prix\n"
        "Winner:\nLewis Hamilton\n"
        "Race Summary:\nLewis Hamilton won the race."
    )
    mock_retriever.client.collection.get.return_value = {
        "ids": ["2024_1", "2024_12"],
        "documents": [report_text, report_text],
        "metadatas": [
            {"race_name": "British Grand Prix", "round": 1},
            {"race_name": "British Grand Prix", "round": 12},
        ],
    }

    result = mock_retriever.retrieve("Who won the British Grand Prix?")

    assert result == report_text
    # Ensure it only appears once
    assert result.count("Lewis Hamilton won the race.") == 1


def test_deduplicate_identical_ids(mock_retriever):
    """
    Two records with identical IDs should be deduplicated to the first occurrence.
    """
    mock_retriever.client.collection.get.return_value = {
        "ids": ["2024_12", "2024_12"],
        "documents": ["First version of report", "Second duplicate ID version"],
        "metadatas": [{"doc": 1}, {"doc": 2}],
    }

    result = mock_retriever.retrieve("Who won the British Grand Prix?")

    assert "First version of report" in result
    assert "Second duplicate ID version" not in result


def test_preserve_different_reports_same_race(mock_retriever):
    """
    Two genuinely different reports from the same race (e.g. driver report and race report)
    must both be preserved.
    """
    doc1 = "Driver: Lewis Hamilton\nConstructor: Mercedes\nFinished: P1\nPoints: 25.0"
    doc2 = "Driver: George Russell\nConstructor: Mercedes\nFinished: DNF\nPoints: 0.0"

    mock_retriever.client.collection.get.return_value = {
        "ids": ["2024_12_hamilton", "2024_12_russell"],
        "documents": [doc1, doc2],
        "metadatas": [
            {"driver": "Lewis Hamilton", "team": "Mercedes"},
            {"driver": "George Russell", "team": "Mercedes"},
        ],
    }

    result = mock_retriever.retrieve("How did Mercedes perform in the British Grand Prix?")

    assert "Lewis Hamilton" in result
    assert "George Russell" in result
    assert "25.0" in result


def test_preserve_reports_different_seasons(mock_retriever):
    """
    Reports from different seasons must be preserved when no season is specified.
    """
    doc_2023 = "Season: 2023\nGrand Prix: British Grand Prix\nWinner:\nMax Verstappen"
    doc_2024 = "Season: 2024\nGrand Prix: British Grand Prix\nWinner:\nLewis Hamilton"

    mock_retriever.client.collection.get.return_value = {
        "ids": ["2023_10", "2024_12"],
        "documents": [doc_2023, doc_2024],
        "metadatas": [
            {"season": 2023, "race_name": "British Grand Prix"},
            {"season": 2024, "race_name": "British Grand Prix"},
        ],
    }

    result = mock_retriever.retrieve("Who won the British Grand Prix?")

    assert "Max Verstappen" in result
    assert "Lewis Hamilton" in result


def test_season_filtering_when_specified(mock_retriever):
    """
    When season is specified in query, filter conditions must include season.
    When not specified, season must NOT be hardcoded.
    """
    mock_retriever.client.collection.get.return_value = {
        "ids": ["2024_12"],
        "documents": ["Season: 2024 British GP Report"],
        "metadatas": [{"season": 2024}],
    }

    # Query with explicit season
    mock_retriever.retrieve("Who won the 2024 British Grand Prix?")
    call_kwargs_with_season = mock_retriever.client.collection.get.call_args[1]
    where_clause = call_kwargs_with_season["where"]
    conditions = where_clause.get("$and", [where_clause])
    assert any(c.get("season") == 2024 for c in conditions)

    # Query without explicit season
    mock_retriever.retrieve("Who won the British Grand Prix?")
    call_kwargs_no_season = mock_retriever.client.collection.get.call_args[1]
    where_clause_no_season = call_kwargs_no_season["where"]
    conditions_no_season = where_clause_no_season.get("$and", [where_clause_no_season])
    assert not any("season" in c for c in conditions_no_season)


def test_empty_retrieval_results(mock_retriever):
    """
    Empty retrieval results from ChromaDB must return an empty string safely.
    """
    mock_retriever.client.collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": [],
    }

    result = mock_retriever.retrieve("Who won the British Grand Prix?")

    assert result == ""
