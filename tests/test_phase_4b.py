"""
Phase 4B Test Suite: Intent Classification, Ambiguity Handling, and Structured Routing.

Validates:
1. Intent classification across all required archetypes.
2. Conversational synonyms for race winners ("claimed victory", "took the chequered flag").
3. Standings leader phrasing variations ("had the championship lead following", "leading the drivers' championship").
4. Constructor race points variations ("collected the highest number of points").
5. Driver vs constructor intent distinction.
6. Race winner vs championship standings distinction.
7. Single-race constructor points vs cumulative constructor standings.
8. Missing entities (missing race, missing driver, pronoun antecedents).
9. Ambiguous entities (ambiguous host country, ambiguous driver names).
10. Numerical driver results and entity binding.
11. Offline execution with verified zero external Gemini API calls.
"""

import pytest
from raceintel.routing.entity_registry import EntityRegistry
from raceintel.routing.intent_classifier import Intent, IntentClassifier
from raceintel.chat.chat_service import ChatService
from raceintel.chat.gemini import GeminiClient
from evaluation.run_evaluation import compare_answer, compare_number_answer


@pytest.fixture(scope="module")
def registry():
    return EntityRegistry()


@pytest.fixture(scope="module")
def classifier(registry):
    return IntentClassifier(registry=registry)


@pytest.fixture(scope="module")
def chat_service(registry, classifier):
    return ChatService(offline=True, entity_registry=registry, intent_classifier=classifier)


# =====================================================================
# 1. Intent Classification Archetypes
# =====================================================================

def test_intent_race_winner(classifier):
    res = classifier.classify("Who won the 2024 Monaco Grand Prix?")
    assert res.intent == Intent.RACE_WINNER
    assert res.entities["race_name"] == "Monaco Grand Prix"
    assert not res.is_ambiguous


def test_intent_driver_standings_leader(classifier):
    res = classifier.classify("Who leads the driver standings after the Bahrain Grand Prix?")
    assert res.intent == Intent.DRIVER_STANDINGS_LEADER
    assert res.entities["race_name"] == "Bahrain Grand Prix"
    assert not res.is_ambiguous


def test_intent_constructor_race_points(classifier):
    res = classifier.classify("Which constructor scored the most points in the Hungarian Grand Prix?")
    assert res.intent == Intent.CONSTRUCTOR_RACE_POINTS
    assert res.entities["race_name"] == "Hungarian Grand Prix"
    assert not res.is_ambiguous


def test_intent_fastest_lap(classifier):
    res = classifier.classify("Who set the fastest lap in the 2024 Australian Grand Prix?")
    assert res.intent == Intent.FASTEST_LAP
    assert res.entities["race_name"] == "Australian Grand Prix"
    assert not res.is_ambiguous


def test_intent_weather(classifier):
    res = classifier.classify("Did it rain during the 2024 Canadian Grand Prix?")
    assert res.intent == Intent.WEATHER
    assert res.entities["race_name"] == "Canadian Grand Prix"
    assert not res.is_ambiguous


def test_intent_podium(classifier):
    res = classifier.classify("Who finished on the podium in Monaco?")
    assert res.intent == Intent.PODIUM
    assert res.entities["race_name"] == "Monaco Grand Prix"
    assert not res.is_ambiguous


def test_intent_driver_points(classifier):
    res = classifier.classify("How many points did Carlos Sainz score in the 2024 Bahrain Grand Prix?")
    assert res.intent == Intent.DRIVER_POINTS
    assert res.entities["driver_name"] == "Carlos Sainz"
    assert res.entities["race_name"] == "Bahrain Grand Prix"
    assert not res.is_ambiguous


def test_intent_driver_position(classifier):
    res = classifier.classify("Where did Oliver Bearman finish in the 2024 Saudi Arabian Grand Prix?")
    assert res.intent == Intent.DRIVER_POSITION
    assert res.entities["driver_name"] == "Oliver Bearman"
    assert res.entities["race_name"] == "Saudi Arabian Grand Prix"
    assert not res.is_ambiguous


def test_intent_driver_performance(classifier):
    res = classifier.classify("How did Max Verstappen perform in the Canadian Grand Prix?")
    assert res.intent == Intent.DRIVER_PERFORMANCE
    assert res.entities["driver_name"] == "Max Verstappen"
    assert res.entities["race_name"] == "Canadian Grand Prix"
    assert not res.is_ambiguous


# =====================================================================
# 2. Conversational Synonyms & Paraphrase Equivalence
# =====================================================================

@pytest.mark.parametrize("question", [
    "Which driver claimed victory at the Miami Grand Prix in 2024?",
    "Who took the chequered flag in the 2024 Australian Grand Prix?",
    "Who secured victory in the 2024 São Paulo Grand Prix in Brazil?",
    "Who was declared the winner of the 2024 Belgian Grand Prix?",
    "Who won the Dutch Grand Prix in 2024?",
])
def test_race_winner_conversational_synonyms(classifier, question):
    res = classifier.classify(question)
    assert res.intent == Intent.RACE_WINNER
    assert not res.is_ambiguous
    assert res.entities["race_name"] is not None


# =====================================================================
# 3. Standings Leader Phrasing Variations (Holdout Cases 117, 119)
# =====================================================================

@pytest.mark.parametrize("question", [
    "Who was leading the drivers' championship after the 2024 Bahrain Grand Prix?",
    "Which driver had the championship lead following the 2024 Canadian Grand Prix?",
    "Who was leading the driver standings after the 2024 Abu Dhabi Grand Prix?",
    "Who leads the championship after the 2024 Monaco Grand Prix?",
])
def test_standings_leader_phrasings(classifier, question):
    res = classifier.classify(question)
    assert res.intent == Intent.DRIVER_STANDINGS_LEADER
    assert not res.is_ambiguous
    assert res.entities["race_name"] is not None


# =====================================================================
# 4. Constructor Race Points Variations (Holdout Cases 121, 122)
# =====================================================================

@pytest.mark.parametrize("question", [
    "Which team collected the highest number of points in the 2024 Bahrain Grand Prix?",
    "Which constructor scored the most points in the 2024 Hungarian Grand Prix?",
    "Which team scored the most points in the Bahrain Grand Prix?",
    "Which constructor amassed the most points in the 2024 Miami Grand Prix?",
])
def test_constructor_race_points_phrasings(classifier, question):
    res = classifier.classify(question)
    assert res.intent == Intent.CONSTRUCTOR_RACE_POINTS
    assert not res.is_ambiguous
    assert res.entities["race_name"] is not None


# =====================================================================
# 5. Driver vs Constructor Intent Distinction
# =====================================================================

def test_driver_vs_constructor_intent_distinction(classifier):
    q_driver = "Who scored the most points for Ferrari in Monaco?"
    q_constructor = "Which constructor scored the most points in the Hungarian Grand Prix?"
    res_driver = classifier.classify(q_driver)
    res_constructor = classifier.classify(q_constructor)

    assert res_driver.intent == Intent.MOST_POINTS_IN_TEAM
    assert res_constructor.intent == Intent.CONSTRUCTOR_RACE_POINTS


# =====================================================================
# 6. Race Winner vs Championship Standings Distinction
# =====================================================================

def test_race_winner_vs_standings_distinction(classifier):
    q_race = "Who won the Canadian Grand Prix in 2024?"
    q_standings = "Who was leading the championship following the 2024 Canadian Grand Prix?"

    res_race = classifier.classify(q_race)
    res_standings = classifier.classify(q_standings)

    assert res_race.intent == Intent.RACE_WINNER
    assert res_standings.intent == Intent.DRIVER_STANDINGS_LEADER


# =====================================================================
# 7. Single-Race Points vs Cumulative Standings Distinction
# =====================================================================

def test_single_race_vs_cumulative_standings(chat_service):
    # Single-race constructor points in Bahrain: Red Bull Racing (44.0 pts)
    ans_race = chat_service.ask("Which team collected the highest number of points in the 2024 Bahrain Grand Prix?")
    assert "Red Bull Racing" in ans_race
    assert "44.0 points" in ans_race

    # Cumulative standings leader after Bahrain: Max Verstappen (26.0 pts)
    ans_standings = chat_service.ask("Who was leading the drivers' championship after the 2024 Bahrain Grand Prix?")
    assert "Max Verstappen" in ans_standings
    assert "26.0 points" in ans_standings


# =====================================================================
# 8. Missing Entities & Ambiguity Detection
# =====================================================================

@pytest.mark.parametrize("question,expected_fragment", [
    ("Who won the race?", "specify which Grand Prix"),
    ("Who got the fastest lap?", "specify which Grand Prix"),
    ("Where did the driver finish?", "specify which driver"),
    ("What position did he finish?", "specify which driver"),
    ("How many points did she score?", "specify which driver"),
    ("How did they perform?", "specify which driver"),
    ("Who leads the championship?", "specify after which Grand Prix"),
    ("Which team scored the most points?", "specify which Grand Prix"),
])
def test_missing_entity_ambiguity(classifier, chat_service, question, expected_fragment):
    res = classifier.classify(question)
    assert res.is_ambiguous
    ans = chat_service.ask(question)
    assert expected_fragment.lower() in ans.lower()


# =====================================================================
# 9. Ambiguous Entities (Multiple Grand Prix in Host Country)
# =====================================================================

def test_ambiguous_host_country_us(classifier, chat_service):
    # The US hosts Miami, Austin (US GP), and Las Vegas
    q = "Who won in the United States?"
    res = classifier.classify(q)
    assert res.is_ambiguous
    assert len(res.entities["event_candidates"]) > 1
    ans = chat_service.ask(q)
    assert "ambiguous" in ans.lower() or "specify" in ans.lower()


# =====================================================================
# 10. Mandatory Holdout Regression Cases (102, 109, 117, 119, 122)
# =====================================================================

def test_holdout_case_102_claimed_victory(chat_service):
    """Case 102: Miami GP winner via 'claimed victory' phrasing."""
    ans = chat_service.ask("Which driver claimed victory at the Miami Grand Prix in 2024?")
    assert compare_answer("Lando Norris", ans, category="race_winner") is True


def test_holdout_case_109_driver_points(chat_service):
    """Case 109: Carlos Sainz points in Bahrain."""
    ans = chat_service.ask("How many championship points did Carlos Sainz score in the 2024 Bahrain Grand Prix?")
    q = "How many championship points did Carlos Sainz score in the 2024 Bahrain Grand Prix?"
    assert compare_answer(15.0, ans, category="points", question=q) is True
    # Verify entity binding: wrong driver fails
    assert compare_number_answer(15.0, "Charles Leclerc scored 15.0 points.", category="points", expected_entity="Carlos Sainz") is False


def test_holdout_case_117_standings_leader_bahrain(chat_service):
    """Case 117: Standings leader after Bahrain."""
    ans = chat_service.ask("Who was leading the drivers' championship after the 2024 Bahrain Grand Prix?")
    assert compare_answer("Max Verstappen", ans, category="driver_standings") is True


def test_holdout_case_119_standings_lead_canada(chat_service):
    """Case 119: Championship lead following Canada."""
    ans = chat_service.ask("Which driver had the championship lead following the 2024 Canadian Grand Prix?")
    assert compare_answer("Max Verstappen", ans, category="driver_standings") is True


def test_holdout_case_122_top_team_points_bahrain(chat_service):
    """Case 122: Highest constructor points in Bahrain."""
    ans = chat_service.ask("Which team collected the highest number of points in the 2024 Bahrain Grand Prix?")
    assert compare_answer("Red Bull Racing", ans, category="constructor_standings") is True


# =====================================================================
# 11. Offline Verification: Zero External API Calls
# =====================================================================

def test_offline_guard_zero_api_calls(chat_service):
    """Verify that structured questions make zero external API calls."""
    GeminiClient.reset_external_call_count()
    chat_service.set_offline(True)

    queries = [
        "Which driver claimed victory at the Miami Grand Prix in 2024?",
        "Who was leading the drivers' championship after the 2024 Bahrain Grand Prix?",
        "Which team collected the highest number of points in the 2024 Bahrain Grand Prix?",
        "How many championship points did Carlos Sainz score in the 2024 Bahrain Grand Prix?",
        "Who won the race?",
    ]
    for q in queries:
        ans = chat_service.ask(q)
        assert ans is not None

    assert GeminiClient.get_external_call_count() == 0
