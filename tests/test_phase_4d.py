"""
Adversarial tests for Phase 4D: RAG Calibration & Fallback Hardening.

Covers:
1. Relevant document retrieval and grounded answer generation.
2. Unrelated F1 document / ungrounded topic rejection (no _direct_answer hijack).
3. Unsupported season blocking without fabricated evidence.
4. Race/event and historical/missing entity mismatch detection.
5. Conflicting retrieved documents detected and reported explicitly.
6. Duplicate and near-duplicate chunks deduplicated while preserving distinct docs.
7. Empty retrieval -> safe fallback without calling LLM.
8. Low-confidence / below-threshold retrieval (including team/driver queries) blocked from LLM.
9. Retrieval exceptions caught safely without crashing ask().
10. LLM exceptions and empty/None/malformed outputs handled safely.
11. General F1 explanatory questions via isolated RAG docs work cleanly.
12. Structured SQL queries still bypass RAG.
13. Ambiguous queries still trigger clarification without RAG/LLM.
14. Unrelated motorsports still blocked early by DomainGuard.
15. Source metadata attribution preserved in context and RetrievalResult.sources,
    plus strict prompt grounding instructions and zero external Gemini calls.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import chromadb
import pytest

from raceintel.chat.chat_service import ChatService
from raceintel.chat.gemini import GeminiClient, OfflineBlockedError
from raceintel.chat.prompts import INSUFFICIENT_EVIDENCE_RESPONSE, build_prompt
from raceintel.retrieval.retriever import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_CHUNKS,
    RetrievalResult,
    Retriever,
)
from raceintel.routing.domain_guard import DomainGuard, DomainStatus
from raceintel.routing.entity_registry import EntityRegistry


class _FakeCollection:
    """Deterministic Chroma-like collection stub for isolated RAG tests."""

    def __init__(self, get_result=None, query_result=None, error: Exception | None = None):
        self._get_result = get_result or {"ids": [], "documents": [], "metadatas": []}
        self._query_result = query_result or {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        self._error = error
        self.last_query_kwargs = None
        self.last_get_kwargs = None

    def get(self, **kwargs):
        self.last_get_kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._get_result

    def query(self, **kwargs):
        self.last_query_kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._query_result


class _MockClientWrapper:
    def __init__(self, collection):
        self.collection = collection


@pytest.fixture(autouse=True)
def offline_guard():
    """Enforce strict offline isolation and zero external Gemini calls for all Phase 4D tests."""
    original = os.environ.get("RACEINTEL_OFFLINE")
    GeminiClient.set_global_offline(True)
    GeminiClient.reset_external_call_count()
    yield
    assert GeminiClient.get_external_call_count() == 0
    GeminiClient.set_global_offline(None)
    GeminiClient.reset_external_call_count()
    if original is not None:
        os.environ["RACEINTEL_OFFLINE"] = original
    else:
        os.environ.pop("RACEINTEL_OFFLINE", None)


def _make_isolated_retriever(
    get_result=None,
    query_result=None,
    error: Exception | None = None,
    distance_threshold: float = 0.55,
    max_context_chunks: int = MAX_CONTEXT_CHUNKS,
    max_context_chars: int = MAX_CONTEXT_CHARS,
) -> tuple[Retriever, _FakeCollection]:
    retriever = Retriever.__new__(Retriever)
    collection = _FakeCollection(get_result=get_result, query_result=query_result, error=error)
    retriever.client = _MockClientWrapper(collection)
    retriever.registry = EntityRegistry()
    retriever.distance_threshold = distance_threshold
    retriever.max_context_chunks = max_context_chunks
    retriever.max_context_chars = max_context_chars
    retriever.RACES = retriever.registry.get_races_map()
    retriever.DRIVERS = retriever.registry.get_drivers_map()
    retriever.TEAMS = retriever.registry.get_teams_map()
    return retriever, collection


# ==============================================================================
# 1. Relevant document retrieval & grounded generation
# ==============================================================================


def test_relevant_document_retrieval_and_grounded_prompt():
    doc = (
        "Grand Prix: British Grand Prix\n"
        "Season: 2024\n"
        "Winner: Lewis Hamilton\n"
        "Race Summary: Lewis Hamilton took a record ninth Silverstone victory."
    )
    retriever, _ = _make_isolated_retriever(
        get_result={
            "ids": ["race_british_2024"],
            "documents": [doc],
            "metadatas": [
                {
                    "document_type": "race_report",
                    "season": 2024,
                    "race_name": "British Grand Prix",
                }
            ],
        }
    )

    result = retriever.retrieve_context("Who was declared the winner of the 2024 British Grand Prix?")
    assert result.status == "ok"
    assert len(result.documents) == 1
    assert "Lewis Hamilton" in result.context
    assert "[Source: race_report | 2024 British Grand Prix | id=race_british_2024]" in result.context

    prompt = build_prompt("Who was declared the winner of the 2024 British Grand Prix?", result.context)
    assert "Answer ONLY using facts explicitly stated" in prompt
    answer = GeminiClient(offline=True).generate(prompt)
    assert "Lewis Hamilton" in answer


# ==============================================================================
# 2. Unrelated F1 document / ungrounded topic rejected safely
# ==============================================================================


def test_unrelated_topic_in_valid_team_or_race_not_hijacked_by_direct_answer():
    """
    Asking about McLaren's Austrian GP *upgrades* must NOT be hijacked by
    _direct_answer printing finish positions/points when upgrade facts are absent.
    """
    norris_doc = (
        "Race: Austrian Grand Prix\n"
        "Driver: Lando Norris\n"
        "Team: McLaren\n"
        "Finished: P20\n"
        "Points: 0.0\n"
    )
    piastri_doc = (
        "Race: Austrian Grand Prix\n"
        "Driver: Oscar Piastri\n"
        "Team: McLaren\n"
        "Finished: P2\n"
        "Points: 18.0\n"
    )
    retriever, _ = _make_isolated_retriever(
        get_result={
            "ids": ["norris_aut", "piastri_aut"],
            "documents": [norris_doc, piastri_doc],
            "metadatas": [
                {"document_type": "driver_report", "season": 2024, "race_name": "Austrian Grand Prix", "driver": "Lando Norris", "team": "McLaren"},
                {"document_type": "driver_report", "season": 2024, "race_name": "Austrian Grand Prix", "driver": "Oscar Piastri", "team": "McLaren"},
            ],
        }
    )
    service = ChatService(offline=True)
    service.retriever = retriever

    answer = service.ask("What upgrades did McLaren bring to the Austrian Grand Prix?")
    assert "Oscar Piastri: P2" not in answer
    assert "couldn't find that information" in answer.lower()


def test_team_aerodynamic_query_blocked_when_only_high_distance_driver_docs_exist():
    """
    Universal semantic distance gating must apply even when 'team' matched filters.
    """
    retriever, _ = _make_isolated_retriever(
        query_result={
            "ids": [["ver_doc"]],
            "documents": [["Race: Bahrain Grand Prix\nDriver: Max Verstappen\nTeam: Red Bull Racing\nFinished: P1\nPoints: 25.0"]],
            "metadatas": [[{"document_type": "driver_report", "season": 2024, "race_name": "Bahrain Grand Prix", "driver": "Max Verstappen", "team": "Red Bull Racing"}]],
            "distances": [[0.78]],
        }
    )
    service = ChatService(offline=True)
    service.retriever = retriever
    mock_llm = MagicMock()
    service.llm = mock_llm

    answer = service.ask("Explain Red Bull's aerodynamic philosophy in 2024")
    assert "Max Verstappen: P1" not in answer
    assert INSUFFICIENT_EVIDENCE_RESPONSE.lower() in answer.lower()
    mock_llm.generate.assert_not_called()


# ==============================================================================
# 3. Unsupported season does not fabricate or fall back to 2024 docs
# ==============================================================================


def test_unsupported_season_refuses_without_retrieval_or_llm():
    service = ChatService(offline=True)
    mock_retriever = MagicMock()
    mock_llm = MagicMock()
    service.retriever = mock_retriever
    service.llm = mock_llm

    answer = service.ask("Explain how Ferrari managed tyres in the 2020 Italian Grand Prix")
    assert "2020" in answer
    assert "not available" in answer.lower()
    mock_retriever.retrieve_context.assert_not_called()
    mock_retriever.retrieve.assert_not_called()
    mock_llm.generate.assert_not_called()


# ==============================================================================
# 4. Out-of-calendar Grand Prix & missing entity mismatch detected cleanly
# ==============================================================================


def test_unrecognized_grand_prix_blocked_by_domain_guard_and_retriever():
    guard = DomainGuard()
    res = guard.validate("Tell me about the 2024 Swiss Grand Prix")
    assert not res.is_valid
    assert res.status == DomainStatus.OUT_OF_CALENDAR_EVENT

    # Direct Retriever check must also block unrecognized named GP before Chroma query
    retriever, collection = _make_isolated_retriever(
        query_result={
            "ids": [["monaco_doc"]],
            "documents": [["Grand Prix: Monaco Grand Prix\nWinner: Charles Leclerc\nRace Summary: Leclerc won at home."]],
            "metadatas": [[{"document_type": "race_report", "season": 2024, "race_name": "Monaco Grand Prix"}]],
            "distances": [[0.35]],
        }
    )
    ret = retriever.retrieve_context("Tell me about the 2024 Swiss Grand Prix")
    assert ret.status == "event_mismatch"
    assert ret.documents == []
    assert collection.last_query_kwargs is None


def test_historical_person_absent_from_race_doc_triggers_entity_mismatch():
    monaco_doc = (
        "Grand Prix: Monaco Grand Prix\n"
        "Season: 2024\n"
        "Winner: Charles Leclerc\n"
        "Race Summary: Charles Leclerc won the 2024 Monaco Grand Prix for Ferrari."
    )
    retriever, _ = _make_isolated_retriever(
        get_result={
            "ids": ["monaco_2024"],
            "documents": [monaco_doc],
            "metadatas": [{"document_type": "race_report", "season": 2024, "race_name": "Monaco Grand Prix"}],
        }
    )
    service = ChatService(offline=True)
    service.retriever = retriever
    mock_llm = MagicMock()
    service.llm = mock_llm

    answer = service.ask("What happened to Ayrton Senna in the 2024 Monaco Grand Prix?")
    assert "Charles Leclerc" not in answer
    assert INSUFFICIENT_EVIDENCE_RESPONSE.lower() in answer.lower()
    mock_llm.generate.assert_not_called()


# ==============================================================================
# 5. Conflicting retrieved documents detected and handled safely
# ==============================================================================


def test_conflicting_race_winners_detected_and_reported_without_guessing():
    doc_a = "Grand Prix: British Grand Prix\nSeason: 2024\nWinner: Lewis Hamilton"
    doc_b = "Grand Prix: British Grand Prix\nSeason: 2024\nWinner: Max Verstappen"
    meta_a = {"document_type": "race_report", "season": 2024, "race_name": "British Grand Prix"}
    meta_b = {"document_type": "race_report_alt", "season": 2024, "race_name": "British Grand Prix"}

    # 1. Deterministic retrieval conflict (.get)
    det_retriever, _ = _make_isolated_retriever(
        get_result={
            "ids": ["brit_1", "brit_2"],
            "documents": [doc_a, doc_b],
            "metadatas": [meta_a, meta_b],
        }
    )
    det_res = det_retriever.retrieve_context("Compare the British Grand Prix winner narratives")
    assert det_res.status == "conflict"
    assert det_res.conflict_detected is True
    assert "[CONFLICT DETECTED]" in det_res.context

    # 2. Semantic retrieval conflict (.query)
    sem_retriever, _ = _make_isolated_retriever(
        query_result={
            "ids": [["brit_1", "brit_2"]],
            "documents": [[doc_a, doc_b]],
            "metadatas": [[meta_a, meta_b]],
            "distances": [[0.20, 0.22]],
        }
    )
    sem_res = sem_retriever.retrieve_context("Explain the British Grand Prix winner discrepancy")
    assert sem_res.status == "conflict"
    assert sem_res.conflict_detected is True
    assert sem_res.conflict_details

    service = ChatService(offline=True)
    service.retriever = sem_retriever
    mock_llm = MagicMock()
    service.llm = mock_llm

    answer = service.ask("Explain why different reports exist for the British Grand Prix winner")
    assert "conflicting" in answer.lower()
    assert "Lewis Hamilton" in answer and "Max Verstappen" in answer
    mock_llm.generate.assert_not_called()


def test_conflicting_driver_positions_detected():
    doc_a = "Race: Italian Grand Prix\nSeason: 2024\nDriver: Charles Leclerc\nFinished: P1\nPoints: 25.0"
    doc_b = "Race: Italian Grand Prix\nSeason: 2024\nDriver: Charles Leclerc\nFinished: P4\nPoints: 12.0"
    detected, details = Retriever._detect_conflicts(
        [doc_a, doc_b],
        [
            {"season": 2024, "race_name": "Italian Grand Prix", "driver": "Charles Leclerc"},
            {"season": 2024, "race_name": "Italian Grand Prix", "driver": "Charles Leclerc"},
        ],
    )
    assert detected is True
    assert any("P1" in d and "P4" in d for d in details)


# ==============================================================================
# 6. Duplicate & near-duplicate deduplication (without merging distinct docs)
# ==============================================================================


def test_near_duplicate_suppression_preserves_distinct_races_and_drivers():
    base_doc = (
        "Grand Prix: Bahrain Grand Prix\n"
        "Season: 2024\n"
        "Winner: Max Verstappen\n"
        "Race Summary: Max Verstappen dominated from pole position and won by over twenty seconds."
    )
    near_dup = (
        "[Chunk 2] Grand Prix: Bahrain Grand Prix\n"
        "Season: 2024\n"
        "Winner: Max Verstappen\n"
        "Race Summary: Max Verstappen dominated from pole position and won by over twenty seconds!"
    )
    distinct_race = (
        "Grand Prix: Monaco Grand Prix\n"
        "Season: 2024\n"
        "Winner: Charles Leclerc\n"
        "Race Summary: Charles Leclerc won from pole position through the streets of Monte Carlo."
    )

    retriever, _ = _make_isolated_retriever(
        query_result={
            "ids": [["id1", "id2", "id3"]],
            "documents": [[base_doc, near_dup, distinct_race]],
            "metadatas": [[
                {"season": 2024, "race_name": "Bahrain Grand Prix", "document_type": "race_report"},
                {"season": 2024, "race_name": "Bahrain Grand Prix", "document_type": "race_report"},
                {"season": 2024, "race_name": "Monaco Grand Prix", "document_type": "race_report"},
            ]],
            "distances": [[0.25, 0.26, 0.35]],
        }
    )
    result = retriever.retrieve_context("Compare Formula 1 race summaries from 2024")
    assert result.status == "ok"
    assert len(result.documents) == 2
    assert result.ids == ["id1", "id3"]


# ==============================================================================
# 7 & 8. Empty retrieval & low-confidence retrieval blocked from LLM
# ==============================================================================


def test_empty_retrieval_refuses_without_calling_llm():
    retriever, _ = _make_isolated_retriever(
        query_result={"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    )
    service = ChatService(offline=True)
    service.retriever = retriever
    mock_llm = MagicMock()
    service.llm = mock_llm

    answer = service.ask("What is the recipe for chocolate cake?")
    assert answer == INSUFFICIENT_EVIDENCE_RESPONSE
    mock_llm.generate.assert_not_called()


def test_low_confidence_retrieval_blocked_before_llm():
    retriever, _ = _make_isolated_retriever(
        query_result={
            "ids": [["distant_1", "distant_2"]],
            "documents": [["Some distant Bahrain race text", "Some distant Monaco race text"]],
            "metadatas": [[{"race_name": "Bahrain Grand Prix"}, {"race_name": "Monaco Grand Prix"}]],
            "distances": [[0.69, 0.88]],
        },
        distance_threshold=0.55,
    )
    ret = retriever.retrieve_context("Explain how Formula 1 DRS works")
    assert ret.status == "low_confidence"
    assert ret.documents == []
    assert ret.context == ""

    service = ChatService(offline=True)
    service.retriever = retriever
    mock_llm = MagicMock()
    service.llm = mock_llm

    answer = service.ask("Explain how Formula 1 DRS works")
    assert answer == INSUFFICIENT_EVIDENCE_RESPONSE
    mock_llm.generate.assert_not_called()


# ==============================================================================
# 9. Retrieval exceptions caught safely
# ==============================================================================


def test_retrieval_exception_handled_gracefully_without_crashing():
    retriever, _ = _make_isolated_retriever(error=RuntimeError("ChromaDB index corrupted"))
    res = retriever.retrieve_context("Explain how Formula 1 DRS works")
    assert res.status == "error"
    assert "ChromaDB index corrupted" in (res.error_message or "")
    assert res.documents == []

    service = ChatService(offline=True)
    service.retriever = retriever
    mock_llm = MagicMock()
    service.llm = mock_llm

    answer = service.ask("Explain how Formula 1 DRS works")
    assert "couldn't retrieve race data" in answer.lower()
    mock_llm.generate.assert_not_called()


# ==============================================================================
# 10. LLM failures and empty / None / malformed LLM outputs handled safely
# ==============================================================================


@pytest.mark.parametrize("bad_output", [None, "", "   \n\t", "None", "null", "{}", "n/a"])
def test_chat_service_handles_empty_or_malformed_llm_outputs(bad_output):
    retriever, _ = _make_isolated_retriever(
        query_result={
            "ids": [["drs_doc"]],
            "documents": [["Topic: DRS\nDrag Reduction System opens the rear wing flap on designated straights."]],
            "metadatas": [[{"document_type": "technical_guide", "topic": "DRS"}]],
            "distances": [[0.22]],
        }
    )
    service = ChatService(offline=True)
    service.retriever = retriever
    mock_llm = MagicMock()
    mock_llm.generate.return_value = bad_output
    service.llm = mock_llm

    answer = service.ask("Explain how Formula 1 DRS works")
    assert answer == INSUFFICIENT_EVIDENCE_RESPONSE
    mock_llm.generate.assert_called_once()


def test_chat_service_handles_llm_exception_gracefully():
    retriever, _ = _make_isolated_retriever(
        query_result={
            "ids": [["drs_doc"]],
            "documents": [["Topic: DRS\nDrag Reduction System reduces drag on straights to aid overtaking."]],
            "metadatas": [[{"document_type": "technical_guide"}]],
            "distances": [[0.20]],
        }
    )
    service = ChatService(offline=True)
    service.retriever = retriever
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = RuntimeError("Upstream 503 error")
    service.llm = mock_llm

    answer = service.ask("Explain how Formula 1 DRS works")
    assert "temporarily unavailable" in answer.lower()


def test_gemini_client_handles_none_or_empty_api_response_safely():
    client = GeminiClient(offline=False)
    fake_models = MagicMock()
    fake_models.generate_content.return_value = MagicMock(text="   ")
    client.client = MagicMock(models=fake_models)

    out = client._call_external("test prompt")
    assert out == INSUFFICIENT_EVIDENCE_RESPONSE

    fake_models.generate_content.return_value = None
    assert client._call_external("test prompt") == INSUFFICIENT_EVIDENCE_RESPONSE
    # Reset external counter mutated by direct offline=False unit test on fake client
    GeminiClient.reset_external_call_count()


def test_offline_blocked_error_still_propagates():
    client = GeminiClient(offline=True)
    with pytest.raises(OfflineBlockedError):
        client._call_external("test")


# ==============================================================================
# 11. General F1 explanatory questions using isolated RAG store
# ==============================================================================


def test_explanatory_f1_questions_work_with_isolated_chroma_store(tmp_path):
    """
    Use a genuinely separate PersistentClient in tmp_path (never production data/chroma)
    with a lightweight deterministic embedding function to validate semantic Chroma RAG.
    """

    class _HashEmbedder:
        def __call__(self, input):
            vecs = []
            for text in input:
                t = text.lower()
                vecs.append([
                    1.0 if ("drs" in t or "drag reduction" in t or "flap" in t) else 0.0,
                    1.0 if ("undercut" in t or "pit" in t or "tyre" in t or "tire" in t) else 0.0,
                    1.0 if ("porpoising" in t or "ground effect" in t) else 0.0,
                    0.5,
                ])
            return vecs

    client = chromadb.PersistentClient(path=str(tmp_path / "isolated_chroma"))
    collection = client.get_or_create_collection(name="test_explanatory_rag")
    embedder = _HashEmbedder()
    docs = [
        "Title: Drag Reduction System\nDRS opens an adjustable flap on the rear wing within 1 second of the car ahead to increase top speed.",
        "Title: Undercut Strategy\nAn undercut is when a driver pits earlier onto fresh tyres to set faster out-laps and overtake after rivals pit.",
    ]
    collection.add(
        ids=["guide_drs", "guide_undercut"],
        documents=docs,
        metadatas=[
            {"document_type": "technical_guide", "topic": "drs"},
            {"document_type": "strategy_guide", "topic": "undercut"},
        ],
        embeddings=embedder(docs),
    )

    class _ChromaAdapter:
        def query(self, **kwargs):
            q_texts = kwargs.get("query_texts", [""])
            query_kwargs = {
                "query_embeddings": embedder(q_texts),
                "n_results": kwargs.get("n_results", 5),
                "include": kwargs.get("include", ["documents", "metadatas", "distances"]),
            }
            if kwargs.get("where"):
                query_kwargs["where"] = kwargs["where"]
            return collection.query(**query_kwargs)

        def get(self, **kwargs):
            return collection.get(**kwargs)

    retriever = Retriever.__new__(Retriever)
    retriever.client = _MockClientWrapper(_ChromaAdapter())
    retriever.registry = EntityRegistry()
    retriever.distance_threshold = 0.55
    retriever.max_context_chunks = 5
    retriever.max_context_chars = 6000
    retriever.RACES = retriever.registry.get_races_map()
    retriever.DRIVERS = retriever.registry.get_drivers_map()
    retriever.TEAMS = retriever.registry.get_teams_map()

    service = ChatService(offline=True)
    service.retriever = retriever

    drs_ans = service.ask("Explain how Formula 1 DRS works")
    assert "rear wing" in drs_ans.lower()
    assert "1 second" in drs_ans.lower()

    undercut_ans = service.ask("How does an undercut strategy work in Formula 1?")
    assert "pits earlier" in undercut_ans.lower() or "fresh tyres" in undercut_ans.lower()


# ==============================================================================
# 12, 13, 14. Structured SQL bypass, Ambiguity clarification, DomainGuard preserved
# ==============================================================================


def test_structured_sql_queries_bypass_rag_and_llm():
    service = ChatService(offline=True)
    mock_retriever = MagicMock()
    mock_retriever._extract_filters.return_value = {}
    mock_llm = MagicMock()
    service.retriever = mock_retriever
    service.llm = mock_llm

    winner_ans = service.ask("Who won the 2024 Monaco Grand Prix?")
    assert "Charles Leclerc" in winner_ans

    weather_ans = service.ask("Was the 2024 Canadian Grand Prix wet or dry?")
    assert "wet" in weather_ans.lower() or "rain" in weather_ans.lower()

    lap_ans = service.ask("Who set the fastest lap in the 2024 Australian Grand Prix?")
    assert "Charles Leclerc" in lap_ans

    mock_retriever.retrieve_context.assert_not_called()
    mock_retriever.retrieve.assert_not_called()
    mock_llm.generate.assert_not_called()


@pytest.mark.parametrize(
    "ambig_q",
    [
        "Who won the race?",
        "Who got the fastest lap?",
        "What was the weather like?",
        "How did he perform in Monaco?",
    ],
)
def test_ambiguous_queries_return_clarification_without_rag(ambig_q):
    service = ChatService(offline=True)
    mock_retriever = MagicMock()
    mock_llm = MagicMock()
    service.retriever = mock_retriever
    service.llm = mock_llm

    ans = service.ask(ambig_q)
    assert "specify" in ans.lower() or "which" in ans.lower()
    mock_retriever.retrieve_context.assert_not_called()
    mock_retriever.retrieve.assert_not_called()
    mock_llm.generate.assert_not_called()


@pytest.mark.parametrize(
    "ood_q",
    [
        "Who won the 2024 MotoGP championship?",
        "Who won the 2024 Indy 500?",
        "Tell me about the 2024 Bathurst 1000",
    ],
)
def test_domain_guard_still_blocks_unrelated_motorsports(ood_q):
    service = ChatService(offline=True)
    mock_retriever = MagicMock()
    mock_llm = MagicMock()
    service.retriever = mock_retriever
    service.llm = mock_llm

    ans = service.ask(ood_q)
    assert "couldn't find" in ans.lower() or "not part of" in ans.lower()
    mock_retriever.retrieve_context.assert_not_called()
    mock_llm.generate.assert_not_called()


# ==============================================================================
# 15. Source attribution & chunk budgeting
# ==============================================================================


def test_source_metadata_attribution_and_budget_caps_preserved():
    docs = [[
        f"Technical Note {i}: telemetry data paragraph " + ("x" * 100)
        for i in range(7)
    ]]
    ids = [[f"note_{i}" for i in range(7)]]
    metas = [[
        {"document_type": "technical_note", "season": 2024, "race_name": "Monaco Grand Prix", "chunk_idx": i}
        for i in range(7)
    ]]
    dists = [[0.10 + i * 0.03 for i in range(7)]]

    retriever, _ = _make_isolated_retriever(
        query_result={"ids": ids, "documents": docs, "metadatas": metas, "distances": dists},
        max_context_chunks=3,
        max_context_chars=500,
    )
    res = retriever.retrieve_context("Explain Monaco telemetry notes", n_results=5)
    assert res.status == "ok"
    assert len(res.documents) <= 3
    assert len(res.raw_context) <= 520
    assert len(res.sources) == len(res.documents)
    assert all(s["season"] == 2024 and s["race_name"] == "Monaco Grand Prix" for s in res.sources)
    assert "[Source: technical_note | 2024 Monaco Grand Prix | id=" in res.context

    # Backwards-compatible .retrieve() omits [Source:] headers
    plain = retriever.retrieve("Explain Monaco telemetry notes", n_results=5)
    assert "[Source:" not in plain
