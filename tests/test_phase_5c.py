"""Phase 5C tests: RAG Filter Extraction, Completeness, Abstention Calibration & Mock Isolation."""

from __future__ import annotations

import pytest

from raceintel.chat.chat_service import ChatService
from raceintel.chat.gemini import GeminiClient, OfflineBlockedError
from raceintel.chat.prompts import INSUFFICIENT_EVIDENCE_RESPONSE, build_prompt
from raceintel.retrieval.retriever import RetrievalResult, Retriever
from raceintel.routing.entity_registry import EntityRegistry


@pytest.fixture(scope="module")
def retriever() -> Retriever:
    return Retriever(EntityRegistry())


@pytest.mark.requires_data
def test_spa_francorchamps_does_not_extract_franco_colapinto(retriever: Retriever):
    filters = retriever._extract_filters("Give a summary of what happened at Spa-Francorchamps in 2024.")
    assert filters.get("race_name") == "Belgian Grand Prix"
    assert "driver" not in filters

    filters_fl = retriever._extract_filters("Who set the fastest lap at Circuit de Spa-Francorchamps?")
    assert filters_fl.get("race_name") == "Belgian Grand Prix"
    assert "driver" not in filters_fl


@pytest.mark.requires_data
def test_filter_extraction_event_priority_and_short_code_guards(retriever: Retriever):
    f_us = retriever._extract_filters("Tell me about the 2024 United States Grand Prix")
    assert f_us.get("race_name") == "United States Grand Prix"
    assert "driver" not in f_us

    f_cota = retriever._extract_filters("What happened at COTA in Austin in 2024?")
    assert f_cota.get("race_name") == "United States Grand Prix"
    assert "driver" not in f_cota

    f_prose = retriever._extract_filters("Neither rain per lap nor tyre law nor gas strategy decided Monza")
    assert f_prose.get("race_name") == "Italian Grand Prix"
    assert "driver" not in f_prose

    f_code = retriever._extract_filters("How did NOR finish at Bahrain?")
    assert f_code.get("driver") == "Lando Norris"
    assert f_code.get("race_name") == "Bahrain Grand Prix"


@pytest.mark.requires_data
def test_explanatory_team_race_query_does_not_bypass_calibration(retriever: Retriever):
    # Should fall through to semantic search with distance threshold rather than deterministic dump
    res = retriever.retrieve_context("What aerodynamic upgrades did McLaren bring to the Austrian Grand Prix?")
    # Either low_confidence / empty / ok without fabricated upgrade claims — Gemini mock must refuse
    llm = GeminiClient(offline=True)
    if res.status == "ok":
        prompt = build_prompt(
            "What aerodynamic upgrades did McLaren bring to the Austrian Grand Prix?",
            res.context or res.raw_context,
        )
        ans = llm.generate(prompt)
        assert ans == INSUFFICIENT_EVIDENCE_RESPONSE
    else:
        assert res.status in {"low_confidence", "empty"}


def test_mock_does_not_hallucinate_first_alphabetical_driver_from_multi_driver_context():
    llm = GeminiClient(offline=True)
    multi_driver_context = (
        "[Source: doc_1 | Grand Prix: Bahrain Grand Prix]\n"
        "Season: 2024\nRound: 1\nGrand Prix: Bahrain Grand Prix\nDriver:\nAlexander Albon\nConstructor:\nWilliams\nFinished:\nP15\nPoints:\n0.0\n\n"
        "[Source: doc_2 | Grand Prix: Bahrain Grand Prix]\n"
        "Season: 2024\nRound: 1\nGrand Prix: Bahrain Grand Prix\nDriver:\nCharles Leclerc\nConstructor:\nFerrari\nFinished:\nP4\nPoints:\n12.0"
    )

    # Asking about an ungrounded driver must NEVER fall back to Alexander Albon (P15)
    prompt_missing = build_prompt(
        "What position did Sebastian Vettel finish in the 2024 Bahrain Grand Prix?",
        multi_driver_context,
    )
    ans_missing = llm.generate(prompt_missing)
    assert ans_missing == INSUFFICIENT_EVIDENCE_RESPONSE
    assert "Albon" not in ans_missing

    # Asking about an ambiguous unspecified driver across multiple blocks must not guess
    prompt_unmatched = build_prompt(
        "What position did the reserve driver finish in the 2024 Bahrain Grand Prix?",
        multi_driver_context,
    )
    ans_unmatched = llm.generate(prompt_unmatched)
    assert ans_unmatched == INSUFFICIENT_EVIDENCE_RESPONSE

    # Asking explicitly about Charles Leclerc returns Charles Leclerc (not Alexander Albon)
    prompt_lec = build_prompt(
        "Where did Charles Leclerc finish in the 2024 Bahrain Grand Prix?",
        multi_driver_context,
    )
    ans_lec = llm.generate(prompt_lec)
    assert "Charles Leclerc" in ans_lec
    assert "P4" in ans_lec
    assert "Albon" not in ans_lec


@pytest.mark.requires_data
def test_rag_race_round_recap_and_narrative_completeness_real_corpus():
    GeminiClient.reset_external_call_count()
    chat = ChatService(llm=GeminiClient(offline=True))

    # 1. Round metadata question resolved cleanly via RAG over race_report
    ans_round = chat.ask("What round of the 2024 championship was the British Grand Prix?")
    assert "12" in ans_round
    assert "British Grand Prix" in ans_round

    # 2. Summary/recap at Spa-Francorchamps works cleanly without Franco Colapinto collision
    ans_spa = chat.ask("Give a brief recap of what happened at Spa-Francorchamps in 2024.")
    assert "Belgian Grand Prix" in ans_spa
    assert "Colapinto" not in ans_spa

    # 3. Race Summary prose completeness for British Grand Prix
    ans_recap = chat.ask("Give a brief summary of the 2024 British Grand Prix.")
    assert "Lewis Hamilton" in ans_recap
    assert "intermediate tyres" in ans_recap.lower()

    assert GeminiClient.get_external_call_count() == 0


def test_multi_fact_knowledge_doc_not_truncated_at_four_lines():
    llm = GeminiClient(offline=True)
    long_doc = (
        "[Source: kb_pit_rules | Document Type: knowledge]\n"
        "Formula 1 tyre compound regulations require drivers to use two different dry compounds during a dry Grand Prix.\n"
        "Line 2: Soft tyres provide the highest mechanical grip and fastest warm-up.\n"
        "Line 3: Medium tyres balance stint longevity and pace across varying fuel loads.\n"
        "Line 4: Hard tyres offer maximum durability over long green-flag stints.\n"
        "Line 5: Under wet conditions, drivers may switch to Intermediate tyres for damp surfaces.\n"
        "Line 6: Full Wet tyres evacuate heavy standing water during torrential rainfall."
    )
    prompt = build_prompt("Explain how Formula 1 tyre compounds work and the wet tyre options.", long_doc)
    ans = llm.generate(prompt)
    assert "Intermediate" in ans
    assert "Full Wet" in ans


@pytest.mark.requires_data
def test_unanswerable_and_conflict_calibration_in_offline_rag():
    GeminiClient.reset_external_call_count()
    chat = ChatService(llm=GeminiClient(offline=True))

    # Unbacked telemetry/pit-stop/qualifying facts on valid 2024 GP must abstain cleanly
    ans_pit = chat.ask("What was the duration of Charles Leclerc's fastest pit stop in the 2024 Monaco Grand Prix?")
    assert ans_pit == INSUFFICIENT_EVIDENCE_RESPONSE

    ans_pole = chat.ask("Who took pole position in qualifying for the 2024 Monaco Grand Prix?")
    assert ans_pole == INSUFFICIENT_EVIDENCE_RESPONSE

    # Conflict banner must explicitly decline to guess
    llm = GeminiClient(offline=True)
    conflict_prompt = build_prompt(
        "Who won the 2024 Belgian Grand Prix?",
        "[CONFLICT DETECTED] Conflicting winners: George Russell vs Lewis Hamilton\nWinner: George Russell\nWinner: Lewis Hamilton",
    )
    ans_conflict = llm.generate(conflict_prompt)
    assert "Conflicting" in ans_conflict
    assert GeminiClient.get_external_call_count() == 0


def test_offline_vs_live_gemini_separation():
    offline_client = GeminiClient(offline=True)
    assert offline_client.offline is True
    with pytest.raises(OfflineBlockedError):
        offline_client._call_external("test prompt")
