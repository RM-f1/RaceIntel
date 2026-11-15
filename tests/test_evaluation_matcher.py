"""
Isolated unit tests for the evaluation matcher in evaluation/run_evaluation.py.
Covers entity correctness, negation handling, contradictory claims,
numerical context discrimination, refusal integrity, ambiguity handling,
and weather paraphrasing.
"""

import pytest
from evaluation.run_evaluation import (
    compare_answer,
    compare_string_answer,
    compare_number_answer,
    compare_unanswerable,
    compare_ambiguous,
    compare_weather_answer,
    compare_structured_answer,
)


# =====================================================================
# 1. Entity Correctness & Contradiction Handling
# =====================================================================

def test_correct_entity_answer():
    """Verify that an exact or supported entity answer passes."""
    actual = "Max Verstappen won the Canadian Grand Prix in 2024."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is True
    assert compare_string_answer("Max Verstappen", actual, category="race_winner") is True


def test_wrong_entity_answer():
    """Verify that a completely wrong entity fails."""
    actual = "Lewis Hamilton won the race."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is False
    assert compare_string_answer("Max Verstappen", actual, category="race_winner") is False


def test_negated_expected_entity():
    """Verify that an explicit negation of the expected entity fails."""
    actual = "Max Verstappen did not win the race; Lewis Hamilton won."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is False
    assert compare_string_answer("Max Verstappen", actual, category="race_winner") is False


def test_contradictory_winner_claims():
    """
    Verify that mentioning the expected driver alongside a competing winner
    fails for race_winner questions.
    """
    actual = "Lewis Hamilton won the British Grand Prix in 2024. Max Verstappen finished P2."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is False
    assert compare_string_answer("Max Verstappen", actual, category="race_winner") is False


def test_subtoken_matching_prevention():
    """Verify that substring matching does not match inside other words (e.g. 'RB' inside 'turbo')."""
    actual = "The turbo hybrid power unit was effective."
    assert compare_string_answer("RB", actual, category="team_comparison") is False


# =====================================================================
# 2. Numerical Context Discrimination
# =====================================================================

def test_correct_points_value():
    """Verify that a genuine points value passes."""
    actual = "Lando Norris scored 25.0 points in the Miami Grand Prix."
    assert compare_answer(25.0, actual, category="points") is True
    assert compare_number_answer(25.0, actual, category="points") is True


def test_incorrect_points_value_appearing_as_lap_number():
    """
    Verify that digits matching the expected points value are rejected
    when they refer to a lap number rather than points.
    """
    actual = "Lando Norris scored 0 points after retiring on lap 25."
    assert compare_answer(25.0, actual, category="points") is False
    assert compare_number_answer(25.0, actual, category="points") is False


def test_incorrect_position_appearing_as_points_value():
    """
    Verify that a finishing position (e.g. P7) is not accepted as points (e.g. 7.0).
    """
    actual = "Oliver Bearman finished P7 and scored 6.0 points."
    assert compare_answer(7.0, actual, category="points") is False
    assert compare_number_answer(7.0, actual, category="points") is False
    assert compare_answer(6.0, actual, category="points") is True


def test_temperature_numerical_extraction():
    """Verify temperature numerical extraction with tolerance."""
    actual = "The peak track temperature recorded was 54.6 degrees Celsius."
    assert compare_answer(54.6, actual, category="weather") is True
    assert compare_number_answer(54.6, actual, category="weather") is True
    assert compare_number_answer(35.0, actual, category="weather") is False


# =====================================================================
# 3. Weather Paraphrasing
# =====================================================================

def test_correct_paraphrased_weather_dry():
    """Verify that semantic equivalents of 'Dry' pass."""
    actual_1 = "There was zero precipitation and clear skies throughout the Grand Prix."
    actual_2 = "Track conditions were completely dry with no rain observed."
    assert compare_answer("Dry", actual_1, category="weather") is True
    assert compare_answer("Dry", actual_2, category="weather") is True
    assert compare_weather_answer("Dry", actual_1) is True


def test_correct_paraphrased_weather_wet():
    """Verify that semantic equivalents of 'Wet' pass."""
    actual_1 = "Rainfall was recorded during the race, making intermediate tyres necessary."
    actual_2 = "Rain fell in the second half of the session resulting in wet track conditions."
    assert compare_answer("Wet", actual_1, category="weather") is True
    assert compare_answer("Wet", actual_2, category="weather") is True
    assert compare_weather_answer("Wet", actual_1) is True


def test_incorrect_weather_answer():
    """Verify that a dry assertion fails for an expected wet race."""
    actual = "The race was held under sunny, dry conditions with zero rain."
    assert compare_answer("Wet", actual, category="weather") is False
    assert compare_weather_answer("Wet", actual) is False


# =====================================================================
# 4. Refusal & Ambiguity Integrity
# =====================================================================

def test_clean_refusal_passes():
    """Verify that a genuine, factual refusal passes."""
    actual = "I couldn't find that information in the retrieved race data. Historical data for season 2020 is not available."
    assert compare_answer("UNANSWERABLE", actual, category="unanswerable") is True
    assert compare_unanswerable(actual) is True


def test_refusal_with_unsupported_factual_claims_fails():
    """
    Verify that an answer asserting an unsupported winner or position
    does not pass merely because it contains 'not available'.
    """
    actual = "Fernando Alonso finished P12 in the 2024 French Grand Prix, but sector details are not available."
    assert compare_answer("UNANSWERABLE", actual, category="unanswerable") is False
    assert compare_unanswerable(actual) is False


def test_ambiguous_question_with_fabricated_answer_fails():
    """
    Verify that an answer asserting a fabricated winner does not pass
    merely because it contains 'please specify'.
    """
    actual = "Max Verstappen won the race. If you meant another event, please specify."
    assert compare_answer("AMBIGUOUS", actual, category="ambiguous") is False
    assert compare_ambiguous(actual) is False


def test_correct_clarification_response_passes():
    """Verify that a genuine clarification request passes for ambiguous questions."""
    actual = "The question is ambiguous. Please specify which Grand Prix or race you are referring to."
    assert compare_answer("AMBIGUOUS", actual, category="ambiguous") is True
    assert compare_ambiguous(actual) is True


# =====================================================================
# 5. Adversarial Audit Tests (Phase 3C.2)
# =====================================================================

def test_adversarial_championship_vs_race_winner():
    """Verify that winning the championship is not confused with winning the race."""
    actual = "Max Verstappen won the championship, but Lewis Hamilton won this race."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is False


def test_adversarial_finished_second_without_negation():
    """Verify that a P2 finish claim fails for a race_winner question."""
    actual = "Max Verstappen finished second behind Lewis Hamilton."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is False


def test_adversarial_affirmative_winner_assertion():
    """Verify that an affirmative declaration ('did win') passes."""
    actual = "Max Verstappen did win the race."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is True


def test_adversarial_position_as_points():
    """Verify that finishing position P2 is rejected when expected points is 2.0."""
    actual = "Lando Norris finished P2 and scored 18.0 points."
    assert compare_answer(2.0, actual, category="points") is False


def test_adversarial_points_as_position():
    """Verify that 2 points scored is rejected when expected position is P2."""
    actual = "Lando Norris scored 2 points."
    assert compare_answer("P2", actual, category="finishing_position") is False


def test_adversarial_sector_time_vs_lap_time():
    """Verify that a sector time is rejected when a lap time is requested."""
    actual = "Max Verstappen set a sector 1 time of 1:32.608."
    assert compare_answer("1:32.608", actual, category="lap_time") is False


def test_adversarial_valid_lap_time():
    """Verify that a valid lap time with proper context passes."""
    actual = "Max Verstappen set the fastest lap with a 1:32.608."
    assert compare_answer("1:32.608", actual, category="lap_time") is True


def test_adversarial_factual_claim_followed_by_cannot_verify():
    """Verify that a factual claim with 'cannot verify' fails unanswerable."""
    actual = "Max Verstappen won the 2024 Indianapolis 500, though I cannot verify this."
    assert compare_answer("UNANSWERABLE", actual, category="unanswerable") is False


def test_adversarial_dry_as_zero_rainfall():
    """Verify that 'zero rainfall' matches 'Dry' without false positive on 'rainfall'."""
    actual = "There was zero rainfall during the Grand Prix."
    assert compare_answer("Dry", actual, category="weather") is True


def test_adversarial_cloudy_no_rainfall():
    """Verify that 'cloudy but no rainfall' matches 'Dry'."""
    actual = "It was cloudy but there was no rainfall."
    assert compare_answer("Dry", actual, category="weather") is True


def test_adversarial_contradictory_weather():
    """Verify that an answer asserting both wet and dry conditions fails."""
    actual = "It was a dry race with wet conditions and heavy rain."
    assert compare_answer("Dry", actual, category="weather") is False
    assert compare_answer("Wet", actual, category="weather") is False


def test_adversarial_driver_in_different_context():
    """Verify that driver mentioned as retiring/crashing fails race_winner."""
    actual = "Lewis Hamilton won the race while Max Verstappen crashed out on lap 10."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is False


def test_adversarial_championship_winner_confused_with_gp_winner():
    """Verify that world champion mentioned alongside GP winner fails race_winner."""
    actual = "Max Verstappen is the world champion, but Charles Leclerc won the Monaco Grand Prix."
    assert compare_answer("Max Verstappen", actual, category="race_winner") is False


# =====================================================================
# 6. Numerical Entity Binding (Case 109 Evaluator Integrity)
# =====================================================================

def test_numerical_entity_binding_correct_num_and_correct_entity():
    """Combination 1: Correct number (15.0) + correct entity (Carlos Sainz) passes."""
    actual = "Carlos Sainz scored 15.0 points in the Bahrain Grand Prix."
    assert compare_number_answer(15.0, actual, category="points", expected_entity="Carlos Sainz") is True
    question = "How many championship points did Carlos Sainz score in the 2024 Bahrain Grand Prix?"
    assert compare_answer(15.0, actual, category="points", question=question) is True


def test_numerical_entity_binding_correct_num_and_wrong_entity():
    """Combination 2: Correct number (15.0) + wrong entity (Charles Leclerc) fails."""
    actual = "Charles Leclerc scored 15.0 points in the Bahrain Grand Prix."
    assert compare_number_answer(15.0, actual, category="points", expected_entity="Carlos Sainz") is False
    question = "How many championship points did Carlos Sainz score in the 2024 Bahrain Grand Prix?"
    assert compare_answer(15.0, actual, category="points", question=question) is False


def test_numerical_entity_binding_correct_num_and_missing_entity():
    """Combination 3: Correct number (15.0) + missing entity fails."""
    actual = "The driver scored 15.0 points in the Bahrain Grand Prix."
    assert compare_number_answer(15.0, actual, category="points", expected_entity="Carlos Sainz") is False
    question = "How many championship points did Carlos Sainz score in the 2024 Bahrain Grand Prix?"
    assert compare_answer(15.0, actual, category="points", question=question) is False


def test_numerical_entity_binding_wrong_num_and_correct_entity():
    """Combination 4: Wrong number (10.0) + correct entity (Carlos Sainz) fails."""
    actual = "Carlos Sainz scored 10.0 points in the Bahrain Grand Prix."
    assert compare_number_answer(15.0, actual, category="points", expected_entity="Carlos Sainz") is False
    question = "How many championship points did Carlos Sainz score in the 2024 Bahrain Grand Prix?"
    assert compare_answer(15.0, actual, category="points", question=question) is False


