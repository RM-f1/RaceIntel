"""
Offline RAG Calibration & Fallback Hardening Evaluation Harness (Phase 4D).

Measures deterministic, reproducible RAG quality and safety metrics without
calling external Gemini APIs (unlike RAGAS, which requires live LLM/embedding
judge endpoints):
- context_precision
- context_recall
- groundedness
- abstention_accuracy
- conflict_detection_rate
- retrieval_error_containment

Writes results to evaluation/raceintel_rag_calibration_v4d_results.json.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock

from raceintel.chat.chat_service import ChatService
from raceintel.chat.gemini import GeminiClient
from raceintel.retrieval.retriever import Retriever
from raceintel.routing.entity_registry import EntityRegistry, normalize_text

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_FILE = BASE_DIR / "evaluation" / "raceintel_rag_calibration_v4d_results.json"


class _StubCollection:
    def __init__(self, get_result=None, query_result=None, error: Exception | None = None):
        self._get_result = get_result or {"ids": [], "documents": [], "metadatas": []}
        self._query_result = query_result or {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        self._error = error

    def get(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._get_result

    def query(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._query_result


class _StubClient:
    def __init__(self, collection):
        self.collection = collection


def _isolated_retriever(
    get_result=None,
    query_result=None,
    error: Exception | None = None,
) -> Retriever:
    r = Retriever.__new__(Retriever)
    r.client = _StubClient(
        _StubCollection(get_result=get_result, query_result=query_result, error=error)
    )
    r.registry = EntityRegistry()
    r.distance_threshold = 0.55
    r.max_context_chunks = 5
    r.max_context_chars = 6000
    r.RACES = r.registry.get_races_map()
    r.DRIVERS = r.registry.get_drivers_map()
    r.TEAMS = r.registry.get_teams_map()
    return r


def _token_support_ratio(answer: str, context: str) -> float:
    """Measure fraction of content words in answer supported by retrieved context."""
    stopwords = {
        "the", "and", "was", "were", "for", "with", "that", "this", "from", "into",
        "are", "has", "have", "had", "not", "can", "all", "its", "race", "data",
        "won", "finished", "scored", "points", "driver", "declared", "winner",
    }
    a_tokens = [
        t for t in re.findall(r"[a-z0-9]+", normalize_text(answer))
        if len(t) >= 3 and t not in stopwords
    ]
    if not a_tokens:
        return 1.0
    c_norm = normalize_text(context)
    supported = sum(1 for t in a_tokens if t in c_norm)
    return supported / len(a_tokens)


def run_calibration_suite(output_file: Path = OUTPUT_FILE) -> dict:
    """Run offline production-store probes + isolated RAG stress cases."""
    GeminiClient.set_global_offline(True)
    GeminiClient.reset_external_call_count()
    os.environ["RACEINTEL_OFFLINE"] = "1"

    prod_service = ChatService(offline=True)

    # Part A: Read-only production knowledge-base stress probes
    prod_probes = [
        {
            "id": "P4D-01",
            "category": "ungrounded_team_upgrades",
            "question": "What upgrades did McLaren bring to the Austrian Grand Prix?",
            "expect_abstain": True,
        },
        {
            "id": "P4D-02",
            "category": "ungrounded_team_aero",
            "question": "Explain Red Bull's aerodynamic philosophy in 2024",
            "expect_abstain": True,
        },
        {
            "id": "P4D-03",
            "category": "out_of_calendar_gp",
            "question": "Tell me about the 2024 Swiss Grand Prix",
            "expect_abstain": True,
        },
        {
            "id": "P4D-04",
            "category": "historical_entity_mismatch",
            "question": "What happened to Ayrton Senna in the 2024 Monaco Grand Prix?",
            "expect_abstain": True,
        },
        {
            "id": "P4D-05",
            "category": "non_f1_empty_retrieval",
            "question": "What is the recipe for chocolate cake?",
            "expect_abstain": True,
        },
        {
            "id": "P4D-06",
            "category": "missing_technical_docs",
            "question": "Explain how Formula 1 DRS works",
            "expect_abstain": True,
        },
        {
            "id": "P4D-07",
            "category": "unsupported_season",
            "question": "Explain how Ferrari performed in the 2020 Italian Grand Prix",
            "expect_abstain": True,
        },
        {
            "id": "P4D-08",
            "category": "grounded_race_summary",
            "question": "Give a brief race summary of the 2024 Monaco Grand Prix",
            "expect_abstain": False,
            "expected_keywords": ["Charles Leclerc"],
        },
        {
            "id": "P4D-09",
            "category": "grounded_victory_verification",
            "question": "Did Lando Norris win the Miami Grand Prix?",
            "expect_abstain": False,
            "expected_keywords": ["Lando Norris", "won"],
        },
        {
            "id": "P4D-10",
            "category": "grounded_rag_narrative",
            "question": "Give an overview of what happened in the 2024 British Grand Prix race summary",
            "expect_abstain": False,
            "expected_keywords": ["Hamilton"],
        },
    ]

    abstention_expected = 0
    abstention_correct = 0
    answerable_cases = 0
    groundedness_scores: list[float] = []
    probe_results: list[dict] = []

    refusal_markers = (
        "couldn't find that information",
        "not available",
        "not part of the formula 1",
    )

    for probe in prod_probes:
        ans = prod_service.ask(probe["question"])
        ret = prod_service.retriever.retrieve_context(probe["question"])
        is_refusal = any(m in ans.lower() for m in refusal_markers)

        if probe["expect_abstain"]:
            abstention_expected += 1
            passed = is_refusal
            if passed:
                abstention_correct += 1
        else:
            answerable_cases += 1
            expected_kws = probe.get("expected_keywords", [])
            kw_ok = all(k.lower() in ans.lower() for k in expected_kws)
            support = _token_support_ratio(ans, ret.raw_context)
            groundedness_scores.append(support)
            passed = kw_ok and not is_refusal

        probe_results.append({
            "id": probe["id"],
            "category": probe["category"],
            "question": probe["question"],
            "retrieval_status": ret.status,
            "retrieved_count": len(ret.documents),
            "distances": ret.distances,
            "answer": ans,
            "passed": passed,
        })

    # Part B: Isolated synthetic calibration fixtures (precision/recall/conflict/error)
    drs_doc = "Topic: DRS\nDrag Reduction System opens the rear wing flap within 1 second to aid overtaking."
    noise_doc = "Race: Bahrain Grand Prix\nSeason: 2024\nWinner: Max Verstappen"
    cal_retriever = _isolated_retriever(
        query_result={
            "ids": [["drs_guide", "noise_bahrain"]],
            "documents": [[drs_doc, noise_doc]],
            "metadatas": [
                [{"document_type": "technical_guide", "topic": "drs"}],
                [{"document_type": "race_report", "season": 2024, "race_name": "Bahrain Grand Prix"}],
            ],
            "distances": [[0.22, 0.78]],
        }
    )
    cal_ret = cal_retriever.retrieve_context("Explain how Formula 1 DRS works")
    context_precision = 1.0 if cal_ret.ids == ["drs_guide"] else 0.0
    context_recall = (
        1.0
        if ("rear wing flap" in cal_ret.raw_context.lower() and "1 second" in cal_ret.raw_context.lower())
        else 0.0
    )

    # Conflict fixture
    conf_retriever = _isolated_retriever(
        query_result={
            "ids": [["c1", "c2"]],
            "documents": [[
                "Grand Prix: British Grand Prix\nSeason: 2024\nWinner: Lewis Hamilton",
                "Grand Prix: British Grand Prix\nSeason: 2024\nWinner: Max Verstappen",
            ]],
            "metadatas": [[
                {"document_type": "race_report", "season": 2024, "race_name": "British Grand Prix"},
                {"document_type": "race_report_alt", "season": 2024, "race_name": "British Grand Prix"},
            ]],
            "distances": [[0.18, 0.21]],
        }
    )
    conf_service = ChatService(offline=True)
    conf_service.retriever = conf_retriever
    conf_ans = conf_service.ask("Explain British Grand Prix winner disagreement")
    conflict_caught = "conflicting" in conf_ans.lower()

    # Retrieval failure fixture
    err_service = ChatService(offline=True)
    err_service.retriever = _isolated_retriever(error=RuntimeError("Simulated Chroma failure"))
    err_service.llm = MagicMock()
    err_ans = err_service.ask("Explain DRS rules")
    error_contained = (
        "couldn't retrieve race data" in err_ans.lower()
        and err_service.llm.generate.call_count == 0
    )

    external_calls = GeminiClient.get_external_call_count()
    assert external_calls == 0, f"Offline calibration triggered {external_calls} external API calls!"

    summary = {
        "mode": "offline_deterministic_calibration",
        "ragas_live_api_status": "skipped_in_offline_mode_requires_live_gemini_judge_and_embeddings",
        "external_gemini_calls": external_calls,
        "metrics": {
            "production_probe_pass_rate": round(
                sum(1 for r in probe_results if r["passed"]) / len(probe_results), 4
            ),
            "abstention_accuracy": round(
                abstention_correct / abstention_expected if abstention_expected else 1.0, 4
            ),
            "answerable_groundedness": round(
                sum(groundedness_scores) / len(groundedness_scores) if groundedness_scores else 1.0, 4
            ),
            "isolated_context_precision": context_precision,
            "isolated_context_recall": context_recall,
            "conflict_detection_rate": 1.0 if conflict_caught else 0.0,
            "retrieval_error_containment_rate": 1.0 if error_contained else 0.0,
        },
        "probe_results": probe_results,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n================ PHASE 4D OFFLINE RAG CALIBRATION ================")
    for k, v in summary["metrics"].items():
        print(f"  {k}: {v}")
    print(f"  external_gemini_calls: {external_calls}")
    print(f"  saved_to: {output_file}")
    print("==================================================================\n")
    return summary


if __name__ == "__main__":
    run_calibration_suite()
