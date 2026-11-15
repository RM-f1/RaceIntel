import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from evaluation.run_ragas_evaluation import (
    load_cache,
    save_cache,
    validate_cache_entry,
    build_ragas_dataset,
)


def test_load_existing_cache(tmp_path: Path):
    cache_file = tmp_path / "test_cache.json"
    cache_file.write_text(
        json.dumps({"Who won?": {"context": "Doc A", "answer": "Driver X"}}),
        encoding="utf-8",
    )

    data = load_cache(cache_file)
    assert "Who won?" in data
    assert data["Who won?"]["answer"] == "Driver X"


def test_load_non_existent_cache(tmp_path: Path):
    non_existent = tmp_path / "does_not_exist.json"
    data = load_cache(non_existent)
    assert data == {}


def test_load_invalid_cache_json(tmp_path: Path):
    cache_file = tmp_path / "invalid_cache.json"
    cache_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_cache(cache_file)


def test_validate_cache_entry_valid():
    entry = {"context": "Some context", "answer": "Some answer"}
    ctx, ans = validate_cache_entry("Q?", entry)
    assert ctx == "Some context"
    assert ans == "Some answer"


def test_validate_cache_entry_invalid_types():
    with pytest.raises(ValueError, match="Invalid cache entry"):
        validate_cache_entry("Q?", "not a dict")

    with pytest.raises(RuntimeError, match="Cached context is invalid"):
        validate_cache_entry("Q?", {"context": 123, "answer": "Ans"})

    with pytest.raises(RuntimeError, match="Cached answer is invalid"):
        validate_cache_entry("Q?", {"context": "Ctx", "answer": ""})


def test_validate_cache_entry_detects_error_marker():
    entry = {"context": "Ctx", "answer": "429 Too Many Requests: quota exceeded"}
    with pytest.raises(RuntimeError, match="Cached answer looks like an API error"):
        validate_cache_entry("Q?", entry)


def test_build_ragas_dataset_uses_cache():
    cases = [
        {"question": "Q1", "expected_answer": "A1"},
        {"question": "Q2", "expected_answer": "A2"},
    ]
    cache = {
        "Q1": {"context": "Ctx 1", "answer": "Ans 1"},
        "Q2": {"context": "Ctx 2", "answer": "Ans 2"},
    }

    # retriever and chat_service are None, proving they are not called
    dataset, updated_cache = build_ragas_dataset(
        cases=cases,
        cache=cache,
        retriever=None,
        chat_service=None,
    )

    assert len(dataset) == 2
    assert dataset["question"] == ["Q1", "Q2"]
    assert dataset["answer"] == ["Ans 1", "Ans 2"]
    assert dataset["contexts"] == [["Ctx 1"], ["Ctx 2"]]
    assert dataset["ground_truth"] == ["A1", "A2"]


def test_build_ragas_dataset_cache_miss(tmp_path: Path):
    cases = [{"question": "Q_new", "expected_answer": "A_new"}]
    cache = {}
    cache_file = tmp_path / "new_cache.json"

    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = "Retrieved context"

    mock_chat = MagicMock()
    mock_chat.ask.return_value = "Generated answer"

    dataset, updated_cache = build_ragas_dataset(
        cases=cases,
        cache=cache,
        retriever=mock_retriever,
        chat_service=mock_chat,
        cache_file=cache_file,
    )

    assert len(dataset) == 1
    assert dataset["question"] == ["Q_new"]
    assert dataset["answer"] == ["Generated answer"]
    assert "Q_new" in updated_cache
    assert updated_cache["Q_new"]["context"] == "Retrieved context"
    assert cache_file.exists()


def test_save_cache_atomic(tmp_path: Path):
    cache_file = tmp_path / "atomic_cache.json"
    save_cache({"test_key": {"context": "c", "answer": "a"}}, cache_file)

    assert cache_file.exists()
    loaded = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "test_key" in loaded
