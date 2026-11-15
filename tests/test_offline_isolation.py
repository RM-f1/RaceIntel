"""
Tests for explicit offline evaluation mode and API isolation.

Verifies:
1. Structured questions work in offline mode.
2. RAG questions do not make external API calls.
3. LLM fallback uses the deterministic mock.
4. An attempted external API call is blocked.
5. Normal production configuration is not silently changed.
"""
import os
import pytest

from raceintel.chat.chat_service import ChatService
from raceintel.chat.gemini import GeminiClient, OfflineBlockedError, _BlockedGenAIClient


@pytest.fixture(autouse=True)
def reset_offline_state():
    """Ensure clean offline state before and after each test."""
    original_env = os.environ.get("RACEINTEL_OFFLINE")
    GeminiClient.set_global_offline(None)
    GeminiClient.reset_external_call_count()
    yield
    if original_env is not None:
        os.environ["RACEINTEL_OFFLINE"] = original_env
    else:
        os.environ.pop("RACEINTEL_OFFLINE", None)
    GeminiClient.set_global_offline(None)
    GeminiClient.reset_external_call_count()


@pytest.mark.requires_data
def test_structured_questions_in_offline_mode():
    """1. Verify structured questions work deterministically in offline mode without external calls."""
    GeminiClient.set_global_offline(True)
    service = ChatService(offline=True)

    # Weather structured query
    weather_ans = service.ask("Was the 2024 Canadian Grand Prix wet or dry?")
    assert "wet" in weather_ans.lower() or "rain" in weather_ans.lower()

    # Fastest lap structured query
    lap_ans = service.ask("Who set the fastest lap in the 2024 Australian Grand Prix?")
    assert "Charles Leclerc" in lap_ans

    # Driver standings leader structured query
    standings_ans = service.ask("Who leads the driver standings after the Bahrain Grand Prix?")
    assert "Max Verstappen" in standings_ans

    # Verify zero external API calls were attempted
    assert GeminiClient.get_external_call_count() == 0


@pytest.mark.requires_data
def test_rag_questions_do_not_make_external_api_calls():
    """2. Verify RAG retrieval questions execute without making external API calls."""
    GeminiClient.set_global_offline(True)
    service = ChatService(offline=True)

    # Direct answer via RAG context
    ans = service.ask("Who won the Monaco Grand Prix?")
    assert "Charles Leclerc" in ans

    # Driver performance via RAG context
    perf_ans = service.ask("How did Max Verstappen perform in the Canadian Grand Prix?")
    assert "Max Verstappen" in perf_ans
    assert "P1" in perf_ans

    # Out-of-calendar unanswerable question
    unans = service.ask("Who won the 2024 Bathurst 1000?")
    assert "couldn't find" in unans.lower() or "not part of" in unans.lower()

    # Verify zero external API calls were attempted
    assert GeminiClient.get_external_call_count() == 0


def test_llm_fallback_uses_deterministic_mock():
    """3. Verify LLM fallback uses deterministic mock responses based strictly on prompt context."""
    client = GeminiClient(offline=True)
    assert client.offline is True

    # Prompt with Belgian GP winner context (Case 103 fallback scenario)
    prompt_winner = (
        "Context:\n\n"
        "Grand Prix: Belgian Grand Prix\n"
        "Winner:\n"
        "Lewis Hamilton\n"
        "Race Summary:\n"
        "Lewis Hamilton won the race.\n\n"
        "Question:\n\n"
        "Who was declared the winner of the 2024 Belgian Grand Prix?\n\n"
        "Answer:"
    )
    mock_resp = client.generate(prompt_winner)
    assert "Lewis Hamilton" in mock_resp
    assert GeminiClient.get_external_call_count() == 0

    # Prompt with driver victory query ("Did Lando Norris win the Miami Grand Prix?")
    prompt_did_win = (
        "Context:\n\n"
        "Grand Prix: Miami Grand Prix\n"
        "Driver:\n"
        "Lando Norris\n"
        "Finished:\n"
        "P1\n"
        "Points:\n"
        "25.0\n\n"
        "Question:\n\n"
        "Did Lando Norris win the Miami Grand Prix?\n\n"
        "Answer:"
    )
    mock_did_win = client.generate(prompt_did_win)
    assert "Lando Norris" in mock_did_win
    assert "won" in mock_did_win.lower()

    # Prompt with unanswerable question (German GP not in context)
    prompt_unanswerable = (
        "Context:\n\n"
        "Grand Prix: Italian Grand Prix\n"
        "Winner:\n"
        "Charles Leclerc\n\n"
        "Question:\n\n"
        "What was the race result of the 2024 German Grand Prix?\n\n"
        "Answer:"
    )
    mock_unans = client.generate(prompt_unanswerable)
    assert "couldn't find that information" in mock_unans.lower()
    assert GeminiClient.get_external_call_count() == 0


def test_attempted_external_call_is_blocked():
    """4. Verify that any attempted external API call is blocked and raises OfflineBlockedError."""
    client = GeminiClient(offline=True)

    # Direct call to _call_external must raise OfflineBlockedError
    with pytest.raises(OfflineBlockedError, match="blocked in offline mode"):
        client._call_external("Any prompt")

    # Call to underlying client.models.generate_content must raise OfflineBlockedError
    with pytest.raises(OfflineBlockedError, match="blocked in offline mode"):
        client.client.models.generate_content(contents="Any prompt")


def test_normal_production_configuration_not_silently_changed():
    """5. Verify that normal production mode does not silently use offline mocks."""
    # Ensure offline environment variable is absent
    os.environ.pop("RACEINTEL_OFFLINE", None)
    GeminiClient.set_global_offline(False)

    prod_client = GeminiClient(offline=False)
    assert prod_client.offline is False
    assert not isinstance(prod_client.client, _BlockedGenAIClient)
    assert hasattr(prod_client.client, "models")
    assert prod_client.client.__class__.__name__ != "_BlockedGenAIClient"
