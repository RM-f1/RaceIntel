import json
from pathlib import Path
import pytest

from scripts.validate_evaluation_set import validate


def test_validate_default_dataset():
    """Verify that the official 2024 evaluation dataset passes validation."""
    assert validate() is True


def test_validate_detects_missing_fields(tmp_path: Path):
    """Verify that validate() detects and rejects datasets missing required fields."""
    invalid_data = {
        "schema_version": "1.0",
        "season": 2024,
        "cases": [
            {
                "id": 1,
                "question": "Who won?",
                # missing category and expected_answer
            }
        ],
    }
    file_path = tmp_path / "invalid_eval.json"
    file_path.write_text(json.dumps(invalid_data), encoding="utf-8")

    assert validate(file_path) is False


def test_validate_detects_duplicate_ids(tmp_path: Path):
    """Verify that validate() detects duplicate case IDs."""
    invalid_data = {
        "schema_version": "1.0",
        "season": 2024,
        "cases": [
            {
                "id": 1,
                "question": "Question 1?",
                "category": "race_winner",
                "expected_answer": "Driver A",
            },
            {
                "id": 1,
                "question": "Question 2?",
                "category": "race_winner",
                "expected_answer": "Driver B",
            },
        ],
    }
    file_path = tmp_path / "duplicate_ids.json"
    file_path.write_text(json.dumps(invalid_data), encoding="utf-8")

    assert validate(file_path) is False
