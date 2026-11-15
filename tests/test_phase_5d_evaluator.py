"""
Phase 5D Evaluator Validation Tests.

Verifies `evaluation/raceintel_independent_v2.json` dataset integrity and
validates anti-false-positive behaviour of `evaluation/run_independent_v2.py`
on synthetic cases BEFORE executing the frozen independent v2 benchmark.
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation import run_independent_v2 as ev2

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"


def test_independent_v2_dataset_schema_and_novelty():
    v2_data = json.loads((EVAL_DIR / "raceintel_independent_v2.json").read_text(encoding="utf-8"))
    cases = v2_data["cases"]
    assert len(cases) == 80

    seen_ids = set()
    seen_questions = set()
    required_keys = {
        "id", "category", "difficulty", "question", "expected_intent",
        "expected_route", "answerability_status", "expected_answer",
        "required_entities", "required_event", "required_season",
        "expected_evidence", "evaluation_criteria",
    }
    for case in cases:
        assert required_keys.issubset(case.keys()), f"Missing keys in {case.get('id')}"
        assert case["id"] not in seen_ids
        seen_ids.add(case["id"])
        norm_q = ev2.normalize_str(case["question"])
        assert norm_q not in seen_questions, f"Duplicate question inside v2: {case['question']}"
        seen_questions.add(norm_q)

    # Confirm zero verbatim overlaps against regression & v1 benchmarks
    prior_questions = set()
    for fname in (
        "raceintel_eval_2024.json",
        "raceintel_eval_v2.json",
        "raceintel_holdout_v1.json",
        "raceintel_independent_benchmark_v1.json",
    ):
        raw = json.loads((EVAL_DIR / fname).read_text(encoding="utf-8"))
        items = raw["cases"] if isinstance(raw, dict) and "cases" in raw else raw
        for item in items:
            q = item.get("question") or item.get("query") or ""
            prior_questions.add(ev2.normalize_str(q))

    overlaps = seen_questions & prior_questions
    assert not overlaps, f"Found duplicate questions vs prior benchmarks: {overlaps}"


def test_position_boundary_prevents_p1_matching_p10():
    assert ev2.contains_exact_position("Max Verstappen finished P1.", 1) is True
    assert ev2.contains_exact_position("Lewis Hamilton finished P10.", 1) is False
    assert ev2.contains_exact_position("He placed 10th overall.", 1) is False


def test_dry_wet_polarity_negated_rainfall():
    ans_dry = "The 2024 Japanese Grand Prix was dry with 0 rainfall observations (no rain recorded)."
    has_dry, has_wet = ev2._detect_weather_polarity(ans_dry)
    assert has_dry is True
    assert has_wet is False

    case = {
        "evaluation_criteria": {"type": "dry_wet", "expected_dry": True},
    }
    res = ev2.evaluate_case_answer(case, ans_dry, {})
    assert res["status"] == "PASSED"


def test_clauses_prevents_swapped_entity_attribution():
    case = {
        "evaluation_criteria": {
            "type": "clauses",
            "clauses": [
                {"entity": "Charles Leclerc", "number": 272},
                {"entity": "Carlos Sainz", "number": 221},
            ],
        }
    }
    swapped = "1. Charles Leclerc - 221 pts\n2. Carlos Sainz - 272 pts"
    correct = "1. Charles Leclerc - 272 pts\n2. Carlos Sainz - 221 pts"
    assert ev2.evaluate_case_answer(case, swapped, {})["status"] == "FAILED"
    assert ev2.evaluate_case_answer(case, correct, {})["status"] == "PASSED"


def test_rag_complete_enforces_all_entities_and_source_hit():
    case = {
        "evaluation_criteria": {
            "type": "rag_complete",
            "expected_source_ids": ["2024_2"],
            "must_mention_all": ["Max Verstappen", "Sergio Perez", "Charles Leclerc"],
            "min_support_ratio": 0.45,
        }
    }
    raw_ctx = (
        "Grand Prix: Saudi Arabian Grand Prix\nWinner: Max Verstappen\n"
        "Podium: 1. Max Verstappen 2. Sergio Perez 3. Charles Leclerc\n"
        "Race Summary: Max Verstappen won ahead of Sergio Perez and Charles Leclerc."
    )
    incomplete_ans = "Max Verstappen won the Saudi Arabian Grand Prix."
    wrong_src_tel = {"retrieval_ids": ["2024_1"], "retrieval_raw_context": raw_ctx}
    good_tel = {"retrieval_ids": ["2024_2"], "retrieval_raw_context": raw_ctx}
    full_ans = "Max Verstappen won ahead of Sergio Perez and Charles Leclerc."

    assert ev2.evaluate_case_answer(case, incomplete_ans, good_tel)["status"] == "FAILED"
    assert ev2.evaluate_case_answer(case, full_ans, wrong_src_tel)["status"] == "FAILED"
    assert ev2.evaluate_case_answer(case, full_ans, good_tel)["status"] == "PASSED"


def test_answerable_never_passes_on_refusal_and_clarification_rejects_guesses():
    ans_case = {"evaluation_criteria": {"type": "single_entity", "entity": "Max Verstappen"}}
    refusal = "Data is not available to confirm whether Max Verstappen won."
    assert ev2.evaluate_case_answer(ans_case, refusal, {})["status"] == "FAILED"

    clar_case = {"evaluation_criteria": {"type": "clarification"}}
    guess = "Did you mean Italy? Charles Leclerc won in Italy."
    valid_clar = "Could you please specify whether you mean Emilia Romagna Grand Prix or Italian Grand Prix?"
    assert ev2.evaluate_case_answer(clar_case, guess, {})["status"] == "FAILED"
    assert ev2.evaluate_case_answer(clar_case, valid_clar, {})["status"] == "PASSED"
