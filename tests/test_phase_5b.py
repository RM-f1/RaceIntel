"""Phase 5B tests: Intent Classification Generalisation & Routing Capability Boundaries."""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.requires_data

from raceintel.chat.chat_service import ChatService
from raceintel.chat.gemini import GeminiClient
from raceintel.routing.entity_registry import EntityRegistry
from raceintel.routing.intent_classifier import Intent, IntentClassifier
from raceintel.routing.query_planner import QueryPlanner


class DummyRetriever:
    """Minimal dummy retriever verifying offline structured routing never triggers RAG."""

    def __init__(self, should_fail_if_called: bool = False):
        self.should_fail_if_called = should_fail_if_called
        self.calls: list[str] = []

    def _extract_filters(self, question: str) -> dict:
        return {}

    def retrieve(self, question: str, n_results: int = 8):
        self.calls.append(question)
        if self.should_fail_if_called:
            raise AssertionError(f"Retriever should not have been called for: {question}")
        from raceintel.retrieval.retriever import RetrievalResult
        return RetrievalResult(status="empty", reason="empty_retrieval")

    def retrieve_context(self, question: str, n_results: int = 8) -> str:
        self.calls.append(question)
        return ""


@pytest.fixture(scope="module")
def classifier() -> IntentClassifier:
    return IntentClassifier(EntityRegistry())


@pytest.fixture(scope="module")
def planner() -> QueryPlanner:
    return QueryPlanner(EntityRegistry())


@pytest.mark.parametrize(
    "question, expected_intent",
    [
        # Race winner phrasings
        ("In the 2024 Italian Grand Prix, which Formula 1 driver came first?", Intent.RACE_WINNER),
        ("Who took the win at the Silverstone circuit in 2024?", Intent.RACE_WINNER),
        ("Who stood on the top step of the podium at Monaco? Wait who was the race victor of the Monaco Grand Prix?", Intent.PODIUM),
        ("Who emerged victorious at the Belgian Grand Prix?", Intent.RACE_WINNER),
        # Podium & points scorers phrasings
        ("Who finished in the top three at the 2024 Canadian Grand Prix?", Intent.PODIUM),
        ("List the top-3 finishers of the 2024 Japanese Grand Prix.", Intent.PODIUM),
        ("Which drivers earned points at the 2024 Austrian Grand Prix?", Intent.POINTS_SCORERS),
        ("Who were the points-scoring drivers in the 2024 Dutch Grand Prix?", Intent.POINTS_SCORERS),
        # Weather & surface/ambient/humidity/wind phrasings
        ("What was the track surface temperature during the 2024 Spanish Grand Prix?", Intent.WEATHER),
        ("Was the 2024 Canadian Grand Prix dry or wet?", Intent.WEATHER),
        ("What was the ambient air temp during the 2024 Bahrain Grand Prix?", Intent.WEATHER),
        ("What was the humidity during the 2024 Singapore Grand Prix?", Intent.WEATHER),
        # Fastest lap phrasings
        ("Who clocked the quickest lap time at the 2024 Japanese Grand Prix?", Intent.FASTEST_LAP),
        ("Who earned the bonus point for the fastest lap at Suzuka?", Intent.FASTEST_LAP),
        # Retirements / Classification / Movers / Tyres
        ("Which drivers failed to finish the 2024 Australian Grand Prix?", Intent.RACE_RETIREMENTS),
        ("Which cars did not see the chequered flag in Monaco?", Intent.RACE_RETIREMENTS),
        ("What was the final classification of the 2024 British Grand Prix?", Intent.RACE_CLASSIFICATION),
        ("Who were the biggest gainers in the 2024 Saudi Arabian Grand Prix?", Intent.BIGGEST_MOVERS),
        ("Which driver climbed the most positions in the 2024 Las Vegas Grand Prix?", Intent.BIGGEST_MOVERS),
        ("Which compounds did Max Verstappen run during the 2024 Bahrain Grand Prix?", Intent.TYRE_USAGE),
        ("What compounds were fitted by drivers during the 2024 Monaco Grand Prix?", Intent.TYRE_USAGE),
        # Standings leaders, tables, cumulative points & championship positions
        ("Who topped the Formula 1 drivers' championship after the 2024 British Grand Prix?", Intent.DRIVER_STANDINGS_LEADER),
        ("Which team sat atop the Formula 1 constructors' championship after Azerbaijan?", Intent.CONSTRUCTOR_STANDINGS_LEADER),
        ("How many championship points total did Lando Norris have following the 2024 Dutch Grand Prix?", Intent.DRIVER_CUMULATIVE_POINTS),
        ("What rank was Carlos Sainz in the Formula 1 drivers' standings after the 2024 Japanese Grand Prix?", Intent.DRIVER_CHAMPIONSHIP_POSITION),
        ("Show the updated Formula 1 constructor championship standings after the Belgian Grand Prix.", Intent.CONSTRUCTOR_STANDINGS_TABLE),
        ("Show the Formula 1 driver championship standings after the 2024 Miami Grand Prix.", Intent.DRIVER_STANDINGS_TABLE),
        # Comparisons (standings + intra-team + head-to-head single-race)
        ("Between McLaren and Ferrari, who had the better championship total after the United States Grand Prix?", Intent.CONSTRUCTOR_STANDINGS_COMPARISON),
        ("Between Max Verstappen and Lando Norris, who had more points in the standings after Brazil?", Intent.DRIVER_STANDINGS_COMPARISON),
        ("Between Charles Leclerc and Carlos Sainz, who achieved the stronger classification at Monza?", Intent.DRIVER_RACE_COMPARISON),
        ("Between Lewis Hamilton and George Russell, who finished ahead at the British Grand Prix?", Intent.DRIVER_RACE_COMPARISON),
        ("Which Ferrari driver placed higher at the 2024 Italian Grand Prix?", Intent.TEAM_COMPARISON),
        ("Which McLaren driver outscored their teammate in the 2024 Hungarian Grand Prix?", Intent.MOST_POINTS_IN_TEAM),
        # Driver / Constructor points, position & performance
        ("How many championship points did Ferrari tally in the 2024 Australian Grand Prix?", Intent.CONSTRUCTOR_RACE_POINTS),
        ("How did Lando Norris fare at the 2024 Miami Grand Prix?", Intent.DRIVER_PERFORMANCE),
        ("In which place did Oscar Piastri finish at the 2024 Azerbaijan Grand Prix?", Intent.DRIVER_POSITION),
        ("How did McLaren perform in the 2024 Dutch Grand Prix?", Intent.TEAM_PERFORMANCE),
    ],
)
def test_intent_classifier_generalised_phrasings(classifier: IntentClassifier, question: str, expected_intent: Intent):
    res = classifier.classify(question)
    assert res.intent == expected_intent, f"Expected {expected_intent} for '{question}', got {res.intent}"


@pytest.mark.parametrize(
    "question",
    [
        "What does DNF mean in Formula 1?",
        "Explain how tyre compounds work in Formula 1.",
        "What is a podium in Formula 1?",
        "Why do teams use hard vs soft tyres during a race?",
        "What upgrades did McLaren bring to the Austrian Grand Prix?",
    ],
)
def test_conceptual_and_explanatory_questions_stay_on_rag(classifier: IntentClassifier, question: str):
    res = classifier.classify(question)
    assert res.intent == Intent.GENERAL_RAG
    assert res.is_ambiguous is False


def test_short_three_letter_english_words_do_not_trigger_false_drivers(classifier: IntentClassifier):
    q = "Neither rain per lap nor fuel law nor gas affected the Belgian Grand Prix weather conditions"
    res = classifier.classify(q)
    assert res.entities["all_drivers"] == []
    assert res.intent == Intent.WEATHER

    q_upper = "How many points did VER and NOR score? Compare VER and NOR in Bahrain"
    res_upper = classifier.classify(q_upper)
    assert "Max Verstappen" in res_upper.entities["all_drivers"]
    assert "Lando Norris" in res_upper.entities["all_drivers"]


def test_head_to_head_race_comparison_executes_deterministically():
    dummy_retriever = DummyRetriever(should_fail_if_called=True)
    chat = ChatService(retriever=dummy_retriever, llm=GeminiClient(offline=True))

    ans_monza = chat.ask("Between Charles Leclerc and Carlos Sainz, who achieved the stronger classification at Monza?")
    assert "Charles Leclerc" in ans_monza
    assert "Carlos Sainz" in ans_monza
    assert "finished ahead" in ans_monza

    ans_us = chat.ask("Between McLaren and Ferrari, who had the better championship total after the United States Grand Prix?")
    assert "McLaren" in ans_us
    assert "Ferrari" in ans_us
    assert "United States Grand Prix" in ans_us
    assert dummy_retriever.calls == []


def test_weather_surface_temperature_and_humidity_queries_end_to_end():
    dummy_retriever = DummyRetriever(should_fail_if_called=True)
    chat = ChatService(retriever=dummy_retriever, llm=GeminiClient(offline=True))

    ans_track = chat.ask("What was the track surface temperature during the 2024 Spanish Grand Prix?")
    assert "Spanish Grand Prix" in ans_track
    assert "°C" in ans_track

    ans_hum = chat.ask("What was the humidity during the 2024 Singapore Grand Prix?")
    assert "Singapore Grand Prix" in ans_hum
    assert "%" in ans_hum
    assert dummy_retriever.calls == []


def test_capability_boundary_prevents_sql_plan_leak_to_rag(classifier: IntentClassifier, planner: QueryPlanner):
    # Unsupported season on a structured intent must remain non-executable and never leak to RAG
    intent_2021 = classifier.classify("Who won the 2021 British Grand Prix?")
    plan_2021 = planner.create_plan("Who won the 2021 British Grand Prix?", intent_2021)
    assert plan_2021.is_executable is False
    assert plan_2021.unresolved_reason == "season_not_supported"

    # Unhandled executable service operation in ChatService must not fall back to RAG
    dummy_retriever = DummyRetriever(should_fail_if_called=True)
    chat = ChatService(retriever=dummy_retriever, llm=GeminiClient(offline=True))
    res = chat._execute_query_plan(
        planner.create_plan("Who won the 2024 Bahrain Grand Prix?", classifier.classify("Who won the 2024 Bahrain Grand Prix?")),
        "Who won the 2024 Bahrain Grand Prix?",
    )
    assert res and "Max Verstappen" in res
    assert dummy_retriever.calls == []
