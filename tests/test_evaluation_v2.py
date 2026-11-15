import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from scripts.validate_evaluation_set import validate
from evaluation.run_evaluation import (
    compare_answer,
    compare_number_answer,
    compare_unanswerable,
    compare_ambiguous,
    compare_structured_answer,
    compare_string_answer,
    run_evaluation,
)
from evaluation.run_ragas_evaluation import (
    load_cache,
    save_cache,
    validate_cache_entry,
    build_ragas_dataset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = PROJECT_ROOT / "evaluation" / "raceintel_eval_2024.json"
V2_FILE = PROJECT_ROOT / "evaluation" / "raceintel_eval_v2.json"
CACHE_FILE = PROJECT_ROOT / "evaluation" / "raceintel_ragas_pilot_cache.json"


# =====================================================================
# 1. Dataset Validation & Baseline Preservation
# =====================================================================

def test_evaluation_v2_dataset_validation():
    """Verify that evaluation v2 dataset passes complete validation."""
    assert V2_FILE.exists(), f"V2 dataset file not found: {V2_FILE}"
    assert validate(V2_FILE) is True


def test_original_baseline_preservation():
    """Verify that all 30 baseline cases are preserved exactly in evaluation v2."""
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline_cases = json.load(f)["cases"]

    with open(V2_FILE, "r", encoding="utf-8") as f:
        v2_cases = json.load(f)["cases"]

    assert len(baseline_cases) == 30
    assert len(v2_cases) >= 30

    for i in range(30):
        b_case = baseline_cases[i]
        v2_case = v2_cases[i]

        assert v2_case["id"] == b_case["id"]
        assert v2_case["question"] == b_case["question"]
        assert v2_case["category"] == b_case["category"]
        assert v2_case["expected_answer"] == b_case["expected_answer"]


def test_dataset_category_coverage():
    """Verify that evaluation v2 dataset covers all required operational categories."""
    with open(V2_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data["cases"]
    assert 60 <= len(cases) <= 80, f"Expected 60-80 cases, found {len(cases)}"

    categories = {c["category"] for c in cases}

    # A. Race results
    assert "race_winner" in categories
    assert "race_result" in categories
    assert "finishing_position" in categories
    assert "points" in categories

    # B. Driver analytics
    assert "driver_performance" in categories
    assert "driver_standings" in categories
    assert "lap_time" in categories

    # C. Constructor analytics
    assert "team_performance" in categories
    assert "team_comparison" in categories
    assert "constructor_standings" in categories

    # D. Race conditions
    assert "weather" in categories

    # E. Retrieval robustness
    assert "unanswerable" in categories
    assert "ambiguous" in categories

    # F. Season awareness
    assert "season_awareness" in categories


# =====================================================================
# 2. Answer Comparison Logic
# =====================================================================

def test_answer_comparison_string():
    """Verify simple string answer comparison."""
    assert compare_string_answer("Charles Leclerc", "Charles Leclerc won the race.") is True
    assert compare_string_answer("Max Verstappen", "Max Verstappen won.") is True
    assert compare_string_answer("Lewis Hamilton", "George Russell finished P3.") is False


def test_answer_comparison_structured():
    """Verify structured dictionary answer comparison."""
    expected_driver = {
        "driver": "Charles Leclerc",
        "race": "Monaco Grand Prix",
        "position": "P1",
        "points": 25.0,
    }
    actual_driver = "Charles Leclerc finished P1 and scored 25.0 points."
    assert compare_structured_answer(expected_driver, actual_driver) is True

    # Wrong position
    actual_wrong_pos = "Charles Leclerc finished P2 and scored 25.0 points."
    assert compare_structured_answer(expected_driver, actual_wrong_pos) is False

    # Team structured answer
    expected_team = {
        "team": "Ferrari",
        "race": "Monaco Grand Prix",
        "drivers": [
            {"driver": "Charles Leclerc", "position": "P1", "points": 25.0},
            {"driver": "Carlos Sainz", "position": "P3", "points": 15.0},
        ],
    }
    actual_team = "Charles Leclerc: P1, 25.0 points\nCarlos Sainz: P3, 15.0 points"
    assert compare_structured_answer(expected_team, actual_team) is True


def test_answer_comparison_numerical():
    """Verify numerical answer comparison with appropriate tolerance."""
    # Temperature comparison
    assert compare_number_answer(18.2, "Average air temperature was 18.2 degrees Celsius.") is True
    assert compare_number_answer(18.2, "The air temp was 18.24 C.") is True
    assert compare_number_answer(18.2, "The temperature was 28.5 C.") is False

    # Points comparison
    assert compare_number_answer(25.0, "Lando Norris scored 25.0 points.") is True
    assert compare_number_answer(25.0, "He scored 25 points.") is True
    assert compare_number_answer(26.0, "He scored 25 points.") is False


def test_unanswerable_and_ambiguous_handling():
    """Verify handling of unanswerable and ambiguous questions without hallucination."""
    refusal_1 = "I couldn't find that information in the retrieved race data."
    refusal_2 = "This information is not available in the database."
    fabricated = "Max Verstappen won the 2024 Indianapolis 500."

    assert compare_unanswerable(refusal_1) is True
    assert compare_unanswerable(refusal_2) is True
    assert compare_unanswerable(fabricated) is False

    # Dispatcher check
    assert compare_answer("UNANSWERABLE", refusal_1, category="unanswerable") is True
    assert compare_answer("UNANSWERABLE", fabricated, category="unanswerable") is False

    # Ambiguous check
    ambiguity_resp = "The question is ambiguous. Please specify which Grand Prix you mean."
    assert compare_ambiguous(ambiguity_resp) is True
    assert compare_answer("AMBIGUOUS", ambiguity_resp, category="ambiguous") is True


# =====================================================================
# 3. Evaluation Persistence
# =====================================================================

def test_evaluation_result_persistence(tmp_path: Path):
    """Verify that evaluation results are persisted in machine-readable JSON format."""
    mock_dataset = {
        "schema_version": "1.0",
        "evaluation": "Test Persist",
        "season": 2024,
        "cases": [
            {
                "id": 1,
                "question": "Who won?",
                "category": "race_winner",
                "expected_answer": "Driver X",
            }
        ],
    }
    dataset_file = tmp_path / "test_eval.json"
    dataset_file.write_text(json.dumps(mock_dataset), encoding="utf-8")
    output_file = tmp_path / "test_results.json"

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"answer": "Driver X won the race."}
    mock_client.post.return_value = mock_resp

    output = run_evaluation(
        eval_file=dataset_file,
        output_file=output_file,
        in_process=False,
    )
    # When requests isn't used, run_evaluation with client mock:
    from evaluation.run_evaluation import ask_raceintel
    res = ask_raceintel("Who won?", client=mock_client)
    assert res == {"answer": "Driver X won the race."}

    # Verify output file structure
    assert output_file.exists()
    saved = json.loads(output_file.read_text(encoding="utf-8"))
    assert "total" in saved
    assert "evaluated" in saved
    assert "passed" in saved
    assert "failed" in saved
    assert "accuracy_percent" in saved
    assert "category_performance" in saved
    assert "incorrect_answers" in saved
    assert "unanswered_questions" in saved
    assert "results" in saved


# =====================================================================
# 4. RAGAS Dataset & Cache Reuse
# =====================================================================

def test_ragas_dataset_construction_v2():
    """Verify RAGAS dataset construction supports Ragas 0.2 schema and handles missing context."""
    cases = [
        {"question": "Q_normal", "expected_answer": "A_normal"},
        {"question": "Q_no_context", "expected_answer": "A_empty"},
    ]
    cache = {
        "Q_normal": {"context": "Valid grounded context.", "answer": "Answer 1"},
        "Q_no_context": {"context": "", "answer": "Refusal answer."},
    }

    dataset, updated_cache = build_ragas_dataset(
        cases=cases,
        cache=cache,
        retriever=None,
        chat_service=None,
    )

    assert len(dataset) == 2
    # Verify Ragas 0.2.15 standard columns
    assert "user_input" in dataset.column_names
    assert "response" in dataset.column_names
    assert "retrieved_contexts" in dataset.column_names
    assert "reference" in dataset.column_names

    # Verify context list handling
    assert dataset["retrieved_contexts"][0] == ["Valid grounded context."]
    assert dataset["retrieved_contexts"][1] == []


@pytest.mark.requires_data
def test_ragas_pilot_cache_reuse():
    """Verify that all 8 pilot cases in raceintel_ragas_pilot_cache.json load and reuse cleanly."""
    assert CACHE_FILE.exists(), f"Pilot cache file not found: {CACHE_FILE}"
    cache = load_cache(CACHE_FILE)

    assert len(cache) >= 8, f"Expected at least 8 cached pilot cases, found {len(cache)}"

    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline_cases = json.load(f)["cases"][:8]

    # Build dataset using ONLY the cache (retriever and chat_service are None)
    dataset, updated_cache = build_ragas_dataset(
        cases=baseline_cases,
        cache=cache,
        retriever=None,
        chat_service=None,
    )

    assert len(dataset) == 8
    for i in range(8):
        q = baseline_cases[i]["question"]
        assert q in cache
        ctx, ans = validate_cache_entry(q, cache[q])
        assert isinstance(ctx, str)
        assert isinstance(ans, str) and ans.strip()
