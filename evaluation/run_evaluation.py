import argparse
import json
import numbers
import re
from pathlib import Path

import requests


# ---------------------------------------------------------------------
# Paths and Defaults
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_EVALUATION_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_2024.json"
)

DEFAULT_OUTPUT_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_results.json"
)

EVAL_V2_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_v2.json"
)

EVAL_V2_OUTPUT_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_v2_results.json"
)

HOLDOUT_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_holdout_v1.json"
)

API_URL = "http://127.0.0.1:8000/chat/"

REFUSAL_PHRASES = [
    "couldn't find that information",
    "could not find",
    "cannot find",
    "not available",
    "no data",
    "unanswerable",
    "out of scope",
    "does not contain",
    "unable to find",
    "not found",
    "information is missing",
]

AMBIGUITY_PHRASES = [
    "ambiguous",
    "please specify",
    "which race",
    "which driver",
    "unclear",
] + REFUSAL_PHRASES


# ---------------------------------------------------------------------
# Load evaluation set
# ---------------------------------------------------------------------

def load_evaluation_set(eval_file: Path = DEFAULT_EVALUATION_FILE):
    """Load the RaceIntel evaluation questions from JSON file."""
    if not eval_file.exists():
        raise FileNotFoundError(
            f"Evaluation file not found:\n{eval_file}"
        )

    with open(eval_file, "r", encoding="utf-8") as file:
        return json.load(file)


# ---------------------------------------------------------------------
# Call RaceIntel API (HTTP or in-process TestClient)
# ---------------------------------------------------------------------

def ask_raceintel(question: str, client=None, api_url: str = API_URL):
    """Send a question to the RaceIntel API (either live server or in-process TestClient)."""
    if client is not None:
        response = client.post("/chat/", json={"question": question})
        if response.status_code == 429:
            return {
                "quota_error": True,
                "answer": "Gemini API quota exceeded.",
            }
        if response.status_code >= 500:
            return {
                "api_error": True,
                "answer": response.text,
            }
        response.raise_for_status()
        return response.json()

    response = requests.post(
        api_url,
        json={"question": question},
        timeout=120,
    )

    if response.status_code == 429:
        return {
            "quota_error": True,
            "answer": "Gemini API quota exceeded.",
        }

    if response.status_code >= 500:
        return {
            "api_error": True,
            "answer": response.text,
        }

    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------
# Extract answer
# ---------------------------------------------------------------------

def extract_answer(response):
    """Extract the answer field from the API response."""
    if isinstance(response, str):
        return response

    if not isinstance(response, dict):
        return response

    for key in ("answer", "response", "result", "message"):
        if key in response:
            return response[key]

    return response


# ---------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------

def normalize_text(value):
    """Normalize text for comparison."""
    if value is None:
        return ""

    value = str(value).lower().strip()
    value = value.replace("grand prix", "grand prix")
    value = value.replace("abu dhabi grand prix", "abu dhabi grand prix")
    value = re.sub(r"\s+", " ", value)
    return value


# ---------------------------------------------------------------------
# Extract structured facts from natural-language answer
# ---------------------------------------------------------------------

def extract_position(text):
    """Extract a finishing position such as P1, P2, P19."""
    if not text:
        return None

    match = re.search(
        r"\bP\s*(\d{1,2})\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return f"P{match.group(1)}"

    patterns = {
        "first": "P1",
        "second": "P2",
        "third": "P3",
        "fourth": "P4",
        "fifth": "P5",
        "sixth": "P6",
        "seventh": "P7",
        "eighth": "P8",
        "ninth": "P9",
        "tenth": "P10",
    }

    lower = text.lower()
    for word, position in patterns.items():
        if re.search(rf"\b{word}\b", lower):
            if "position" in lower or "finished" in lower:
                return position

    return None


def extract_points(text):
    """Extract points from natural-language answer."""
    if not text:
        return None

    patterns = [
        r"(?:points?|scored|scoring)\s*(?:scored|:)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*points?",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

    return None


# ---------------------------------------------------------------------
# Answer comparison functions
# ---------------------------------------------------------------------

def extract_temperature(text: str) -> float | None:
    """Extract temperature values from natural-language answer."""
    if not text:
        return None

    patterns = [
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:°c|celsius|degrees\s*celsius|degrees|°)",
        r"(?:temperature|temp)\s*(?:was|of|:)?\s*([0-9]+(?:\.[0-9]+)?)",
        r"(?:highest|max|peak|maximum|min|minimum|avg|average)\s*(?:air|track)?\s*(?:temperature|temp)?\s*(?:was|of|is|reached)?\s*([0-9]+(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

    return None


def compare_weather_answer(expected: str, actual: str) -> bool:
    """Compare weather answers with semantic paraphrase support."""
    actual_norm = normalize_text(actual)
    expected_norm = normalize_text(expected)

    if expected_norm in ("dry", "no"):
        dry_indicators = [
            "dry", "no rainfall", "zero precipitation", "no precipitation",
            "zero rainfall", "did not rain", "didn't rain", "clear skies", "clear conditions",
            "dry track", "dry conditions", "dry race", "rain: no", "rainfall: no"
        ]
        has_dry = any(ind in actual_norm for ind in dry_indicators)
        # Strip negated/dry precipitation phrases before checking wet contradictions
        cleaned_for_wet = re.sub(
            r"\b(?:zero|no|without|did not|didn't|little to no)\s+(?:rain|rainfall|precipitation)\b",
            "",
            actual_norm,
        )
        cleaned_for_wet = re.sub(
            r"\b(?:clear skies|clear conditions|completely dry|dry track|dry conditions|dry race)\b",
            "",
            cleaned_for_wet,
        )
        wet_contradictions = [
            "wet", "heavy rain", "rainfall was recorded", "rain was recorded",
            "rain: yes", "rainfall: yes", "intermediate"
        ]
        has_wet = any(c in cleaned_for_wet for c in wet_contradictions)
        return has_dry and not has_wet

    if expected_norm in ("wet", "yes"):
        cleaned_for_wet = re.sub(
            r"\b(?:zero|no|without|did not|didn't|little to no)\s+(?:rain|rainfall|precipitation)\b",
            "",
            actual_norm,
        )
        wet_indicators = [
            "wet", "rain", "rainfall", "rained", "raining",
            "precipitation", "intermediate", "rain: yes", "rainfall: yes",
            "rainfall was recorded", "rain was recorded"
        ]
        has_wet = any(ind in cleaned_for_wet for ind in wet_indicators)
        dry_contradictions = [
            "no rain", "no rainfall", "zero rainfall", "zero precipitation",
            "did not rain", "didn't rain", "completely dry", "dry race", "dry conditions"
        ]
        has_dry = any(c in actual_norm for c in dry_contradictions)
        return has_wet and not has_dry

    return expected_norm in actual_norm


def compare_number_answer(
    expected: float,
    actual: str,
    tolerance: float = 0.05,
    category: str | None = None,
    expected_entity: str | None = None,
) -> bool:
    """Compare a numerical ground truth against numbers extracted from actual text."""
    if not actual:
        return False

    actual_normalized = normalize_text(actual)

    # Entity validation for numerical assertions (Case 109 fix)
    if expected_entity:
        entity_norm = normalize_text(expected_entity)
        entity_found = False
        if re.search(rf"\b{re.escape(entity_norm)}\b", actual_normalized):
            entity_found = True
        elif " " in entity_norm:
            surname = entity_norm.split()[-1]
            if len(surname) >= 4 and re.search(rf"\b{re.escape(surname)}\b", actual_normalized):
                entity_found = True

        if not entity_found:
            return False

        # Negation check on expected entity
        negation_regex = r"\b(not|did not|didn't|never|was not|wasn't|failed to|excluding|except)\b"
        target_re = rf"\b{re.escape(entity_norm)}\b" if re.search(rf"\b{re.escape(entity_norm)}\b", actual_normalized) else rf"\b{re.escape(entity_norm.split()[-1])}\b"
        for m in re.finditer(target_re, actual_normalized):
            start = max(0, m.start() - 35)
            end = min(len(actual_normalized), m.end() + 35)
            window = actual_normalized[start:end]
            if re.search(negation_regex, window):
                return False

    if category == "points":
        extracted_pts = extract_points(actual)
        if extracted_pts is not None:
            return abs(extracted_pts - expected) <= tolerance
        pts_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:points?|pts?)\b", actual, re.IGNORECASE)
        if pts_match:
            try:
                return abs(float(pts_match.group(1)) - expected) <= tolerance
            except ValueError:
                pass
        return False

    if category == "weather":
        extracted_temp = extract_temperature(actual)
        if extracted_temp is not None:
            return abs(extracted_temp - expected) <= tolerance
        numbers_found = re.findall(r"\b\d+(?:\.\d+)?\b", actual)
        for n_str in numbers_found:
            try:
                val = float(n_str)
                if abs(val - expected) <= tolerance:
                    return True
            except ValueError:
                pass
        return False

    # Generic numbers: filter out lap numbers, round numbers, years, and positions
    cleaned_text = re.sub(r"\b(?:lap|round|turn|position)\s+\d+\b", "", actual, flags=re.IGNORECASE)
    cleaned_text = re.sub(r"\bP\s*\d+\b", "", cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r"\b(?:19|20)\d{2}\b", "", cleaned_text)

    numbers_found = re.findall(r"\b\d+(?:\.\d+)?\b", cleaned_text)
    for n_str in numbers_found:
        try:
            val = float(n_str)
            if abs(val - expected) <= tolerance:
                return True
        except ValueError:
            pass

    return False


def compare_unanswerable(actual: str, category: str | None = None) -> bool:
    """Verify that an unanswerable question is not answered with a fabricated result."""
    if not actual:
        return True

    actual_lower = actual.lower()
    has_refusal = any(p in actual_lower for p in REFUSAL_PHRASES)
    if not has_refusal:
        return False

    # Check for unsupported factual race results
    if re.search(r"\b(?:[a-z]+ [a-z]+|[a-z]+)\s+won the\b", actual_lower):
        return False
    if re.search(r"\bwinner (?:was|is)\b", actual_lower) or re.search(r"\bclaimed victory\b", actual_lower):
        return False
    if re.search(r"\b(?:finished|placed|was)\s+p\d+\b", actual_lower):
        return False
    if re.search(r"\bscored\s+\d+(?:\.\d+)?\s+points\b", actual_lower):
        return False

    return True


def compare_ambiguous(actual: str, category: str | None = None) -> bool:
    """Verify that an ambiguous question prompts for clarification or indicates ambiguity."""
    if not actual:
        return True

    actual_lower = actual.lower()
    has_ambiguity_phrase = any(p in actual_lower for p in AMBIGUITY_PHRASES)
    if not has_ambiguity_phrase:
        return False

    # Must NOT fabricate a winner, position, or points
    if re.search(r"\b(?:[a-z]+ [a-z]+|[a-z]+)\s+won the\b", actual_lower):
        return False
    if re.search(r"\b(?:finished|placed|was)\s+p\d+\b", actual_lower):
        return False
    if re.search(r"\bscored\s+\d+(?:\.\d+)?\s+points\b", actual_lower):
        return False

    return True


def compare_string_answer(expected, actual, category: str | None = None):
    """Compare an expected string against a natural-language answer."""
    if not actual:
        return False

    expected_normalized = normalize_text(expected)
    actual_normalized = normalize_text(actual)

    if expected_normalized == actual_normalized:
        return True

    if category == "weather" or expected_normalized in ("dry", "wet"):
        return compare_weather_answer(str(expected), str(actual))

    if expected_normalized == "unanswerable" or category == "unanswerable":
        return compare_unanswerable(str(actual), category=category)

    if expected_normalized == "ambiguous" or category == "ambiguous":
        return compare_ambiguous(str(actual), category=category)

    if re.match(r"^p\d+$", expected_normalized):
        act_pos = extract_position(str(actual))
        if act_pos and act_pos.lower() == expected_normalized:
            return True
        pos_num = expected_normalized[1:]
        if re.search(rf"\bp\s*{pos_num}\b", actual_normalized):
            return True
        return False

    # Lap time check: reject if explicitly labeled as sector time
    if category == "lap_time":
        sector_match = re.search(
            rf"\b(?:sector\s*\d?|s[1-3])\s*(?:time\s*)?(?:of\s*)?{re.escape(expected_normalized)}\b",
            actual_normalized,
        )
        if sector_match:
            return False

    # Check for word boundary matching
    pattern = rf"\b{re.escape(expected_normalized)}\b"
    has_match = bool(re.search(pattern, actual_normalized))

    if not has_match and " " in expected_normalized:
        surname = expected_normalized.split()[-1]
        if len(surname) >= 4 and re.search(rf"\b{re.escape(surname)}\b", actual_normalized):
            has_match = True

    if not has_match:
        return False

    # Negation check
    negation_regex = r"\b(not|did not|didn't|never|was not|wasn't|failed to|excluding|except)\b"
    entity_regex = (
        rf"\b{re.escape(expected_normalized)}\b"
        if re.search(rf"\b{re.escape(expected_normalized)}\b", actual_normalized)
        else rf"\b{re.escape(expected_normalized.split()[-1])}\b"
    )
    for m in re.finditer(entity_regex, actual_normalized):
        start = max(0, m.start() - 35)
        end = min(len(actual_normalized), m.end() + 35)
        window = actual_normalized[start:end]
        if re.search(negation_regex, window):
            return False

    # Contradiction / Competing winner check
    if category in ("race_winner", "season_awareness"):
        # 1. Did expected finish lower than 1st?
        lower_pos_patterns = [
            rf"\b{re.escape(expected_normalized)}\s+(?:finished|placed|was)\s+(?:second|third|fourth|fifth|p[2-9]|p\d\d)\b",
            rf"\b{re.escape(expected_normalized)}\s+(?:finished|placed)\s+in\s+(?:second|third|p[2-9]|p\d\d)\b",
        ]
        if any(re.search(p, actual_normalized) for p in lower_pos_patterns):
            return False

        # 2. Competing race winner (e.g. "Lewis Hamilton won this race")
        race_winner_matches = re.findall(
            r"\b([a-z]+ [a-z]+)\s+won\s+(?:the\s+|this\s+)?(?:race|grand prix|[a-z]+\s+grand prix)\b",
            actual_normalized,
        )
        for declared in race_winner_matches:
            if expected_normalized not in declared and declared not in expected_normalized:
                return False

        # 3. Check general winner declaration if specific race winner not found
        if not race_winner_matches:
            general_winner_matches = re.findall(r"\b([a-z]+ [a-z]+)\s+won\b", actual_normalized)
            for declared in general_winner_matches:
                idx = actual_normalized.find(declared + " won")
                after = actual_normalized[idx:idx + 50]
                if "championship" in after or "title" in after:
                    continue
                if expected_normalized not in declared and declared not in expected_normalized:
                    return False

        # 4. Check "winner was X"
        winner_was_matches = re.findall(r"\bwinner\s+(?:was|is)\s+([a-z]+ [a-z]+)\b", actual_normalized)
        for declared in winner_was_matches:
            if expected_normalized not in declared and declared not in expected_normalized:
                return False

    return True


def compare_structured_answer(expected, actual, category: str | None = None):
    """Compare structured expected facts against a natural-language answer."""
    if not isinstance(expected, dict):
        return compare_string_answer(expected, actual, category=category)

    actual_text = str(actual)

    # Driver
    if "driver" in expected:
        expected_driver = normalize_text(expected["driver"])
        if expected_driver not in normalize_text(actual_text):
            return False

    # Position
    if "position" in expected:
        actual_position = extract_position(actual_text)
        expected_position = str(expected["position"]).upper()
        if actual_position != expected_position:
            return False

    # Points
    if "points" in expected:
        actual_points = extract_points(actual_text)
        expected_points = float(expected["points"])
        if actual_points is None:
            return False
        if abs(actual_points - expected_points) > 0.001:
            return False

    # Multiple drivers
    if "drivers" in expected:
        actual_normalized = normalize_text(actual_text)
        for expected_driver in expected["drivers"]:
            driver_name = normalize_text(expected_driver["driver"])
            if driver_name not in actual_normalized:
                return False

            driver_index = actual_normalized.find(driver_name)
            driver_section = actual_normalized[driver_index:driver_index + 300]

            if "position" in expected_driver:
                expected_position = str(expected_driver["position"]).upper()
                actual_position = extract_position(driver_section)
                if actual_position != expected_position:
                    return False

            if "points" in expected_driver:
                expected_points = float(expected_driver["points"])
                actual_points = extract_points(driver_section)
                if actual_points is None:
                    return False
                if abs(actual_points - expected_points) > 0.001:
                    return False

    return True


COMMON_F1_DRIVERS = [
    "Max Verstappen", "Sergio Perez", "Charles Leclerc", "Carlos Sainz",
    "Lewis Hamilton", "George Russell", "Lando Norris", "Oscar Piastri",
    "Fernando Alonso", "Lance Stroll", "Pierre Gasly", "Esteban Ocon",
    "Alexander Albon", "Logan Sargeant", "Yuki Tsunoda", "Daniel Ricciardo",
    "Nico Hulkenberg", "Kevin Magnussen", "Valtteri Bottas", "Guanyu Zhou",
    "Oliver Bearman", "Franco Colapinto", "Liam Lawson", "Jack Doohan",
]


def extract_driver_from_text(text: str) -> str | None:
    """Extract a driver entity from question or text for entity binding."""
    if not text:
        return None
    text_norm = normalize_text(text)
    for driver in COMMON_F1_DRIVERS:
        driver_norm = normalize_text(driver)
        if re.search(rf"\b{re.escape(driver_norm)}\b", text_norm):
            return driver
        surname = driver_norm.split()[-1]
        if len(surname) >= 4 and re.search(rf"\b{re.escape(surname)}\b", text_norm):
            return driver
    return None


def compare_answer(
    expected,
    actual,
    category: str | None = None,
    question: str | None = None,
    expected_entity: str | None = None,
):
    """
    Main evaluator comparison.
    Validates expected answers against actual responses by type and category.
    """
    if isinstance(actual, dict):
        actual = extract_answer(actual)

    if actual is None:
        return False

    actual_text = str(actual)

    # Resolve expected entity from question if not explicitly provided
    if expected_entity is None and question:
        expected_entity = extract_driver_from_text(question)

    # 1. Unanswerable cases
    if category == "unanswerable" or expected == "UNANSWERABLE":
        return compare_unanswerable(actual_text, category=category)

    # 2. Ambiguous cases
    if category == "ambiguous" or expected == "AMBIGUOUS":
        return compare_ambiguous(actual_text, category=category)

    # 3. Structured dictionary
    if isinstance(expected, dict):
        return compare_structured_answer(expected, actual_text, category=category)

    # 4. Numerical ground truth
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return compare_number_answer(
            float(expected),
            actual_text,
            category=category,
            expected_entity=expected_entity,
        )

    # 5. List of items (e.g., podium, points scorers)
    if isinstance(expected, list):
        actual_text_norm = normalize_text(actual_text)
        for item in expected:
            if normalize_text(item) not in actual_text_norm:
                return False
        return True

    # 6. String ground truth
    return compare_string_answer(expected, actual_text, category=category)


# ---------------------------------------------------------------------
# Run evaluation
# ---------------------------------------------------------------------

def run_evaluation(
    eval_file: Path | None = None,
    output_file: Path | None = None,
    api_url: str = API_URL,
    in_process: bool = False,
    offline: bool = False,
):
    target_eval_file = eval_file or DEFAULT_EVALUATION_FILE
    target_output_file = output_file or (
        EVAL_V2_OUTPUT_FILE
        if "v2" in str(target_eval_file)
        else DEFAULT_OUTPUT_FILE
    )

    if offline:
        import os
        os.environ["RACEINTEL_OFFLINE"] = "1"
        in_process = True
        from raceintel.chat.gemini import GeminiClient
        GeminiClient.set_global_offline(True)
        GeminiClient.reset_external_call_count()

    evaluation = load_evaluation_set(target_eval_file)
    cases = evaluation["cases"]
    eval_title = evaluation.get("evaluation", "RaceIntel Evaluation")

    print("=" * 70)
    print(f"RaceIntel Evaluation: {eval_title}")
    print("=" * 70)
    print(f"Evaluation file : {target_eval_file}")
    print(f"Output file     : {target_output_file}")
    if in_process:
        mode_str = "In-process TestClient (OFFLINE GUARD ACTIVE)" if offline else "In-process TestClient"
    else:
        mode_str = f"HTTP ({api_url})"
    print(f"Mode            : {mode_str}")
    print(f"Offline Mode    : {offline}")
    print(f"Questions       : {len(cases)}")
    print()

    client = None
    if in_process:
        from fastapi.testclient import TestClient
        from raceintel.api.main import app
        from raceintel.api.chat import chat_service as api_chat_service
        if offline and hasattr(api_chat_service, "llm"):
            api_chat_service.llm.offline = True
        client = TestClient(app)

    passed = 0
    failed = 0
    errors = 0
    quota_errors = 0

    category_stats = {}
    incorrect_answers = []
    unanswered_questions = []
    results = []

    for index, case in enumerate(cases, start=1):
        case_id = case["id"]
        question = case["question"]
        category = case["category"]
        expected = case["expected_answer"]

        if category not in category_stats:
            category_stats[category] = {"total": 0, "passed": 0, "failed": 0, "errors": 0}
        category_stats[category]["total"] += 1

        print(f"[{index:02d}/{len(cases)}] [{category}] {question}")

        try:
            raw_response = ask_raceintel(question, client=client, api_url=api_url)

            if isinstance(raw_response, dict) and raw_response.get("quota_error"):
                quota_errors += 1
                category_stats[category]["errors"] += 1
                actual = extract_answer(raw_response)
                print("       QUOTA_ERROR: Gemini API quota exceeded.")
                unanswered_questions.append({
                    "id": case_id,
                    "question": question,
                    "category": category,
                    "status": "QUOTA_ERROR",
                    "error": "Gemini API quota exceeded."
                })
                results.append({
                    "id": case_id,
                    "question": question,
                    "category": category,
                    "expected": expected,
                    "actual": actual,
                    "status": "QUOTA_ERROR",
                })
                continue

            if isinstance(raw_response, dict) and raw_response.get("api_error"):
                errors += 1
                category_stats[category]["errors"] += 1
                actual = extract_answer(raw_response)
                print("       API_ERROR")
                unanswered_questions.append({
                    "id": case_id,
                    "question": question,
                    "category": category,
                    "status": "API_ERROR",
                    "error": actual
                })
                results.append({
                    "id": case_id,
                    "question": question,
                    "category": category,
                    "expected": expected,
                    "actual": actual,
                    "status": "API_ERROR",
                })
                continue

            actual = extract_answer(raw_response)
            is_correct = compare_answer(
                expected,
                actual,
                category=category,
                question=question,
                expected_entity=case.get("expected_entity"),
            )

            if is_correct:
                passed += 1
                category_stats[category]["passed"] += 1
                status = "PASS"
                print("       PASS")
            else:
                failed += 1
                category_stats[category]["failed"] += 1
                status = "FAIL"
                print("       FAIL")
                print(f"       Expected: {expected}")
                print(f"       Actual:   {actual}")
                incorrect_answers.append({
                    "id": case_id,
                    "question": question,
                    "category": category,
                    "expected": expected,
                    "actual": actual,
                    "reason": "Answer mismatch"
                })

            results.append({
                "id": case_id,
                "question": question,
                "category": category,
                "expected": expected,
                "actual": actual,
                "status": status,
            })

        except requests.exceptions.ConnectionError:
            errors += 1
            category_stats[category]["errors"] += 1
            print("       ERROR: Could not connect to RaceIntel API.")
            print("       Tip: Start FastAPI or run with --in-process")
            unanswered_questions.append({
                "id": case_id,
                "question": question,
                "category": category,
                "status": "CONNECTION_ERROR",
                "error": "Could not connect to API server."
            })
            results.append({
                "id": case_id,
                "question": question,
                "category": category,
                "expected": expected,
                "actual": None,
                "status": "CONNECTION_ERROR",
            })
            break

        except requests.exceptions.Timeout:
            errors += 1
            category_stats[category]["errors"] += 1
            print("       TIMEOUT")
            unanswered_questions.append({
                "id": case_id,
                "question": question,
                "category": category,
                "status": "TIMEOUT",
                "error": "Request timed out."
            })
            results.append({
                "id": case_id,
                "question": question,
                "category": category,
                "expected": expected,
                "actual": None,
                "status": "TIMEOUT",
            })

        except Exception as exc:
            errors += 1
            category_stats[category]["errors"] += 1
            print(f"       ERROR: {type(exc).__name__}: {exc}")
            unanswered_questions.append({
                "id": case_id,
                "question": question,
                "category": category,
                "status": "ERROR",
                "error": str(exc)
            })
            results.append({
                "id": case_id,
                "question": question,
                "category": category,
                "expected": expected,
                "actual": None,
                "status": "ERROR",
                "error": str(exc),
            })

    # Summary
    total = len(cases)
    evaluated = passed + failed

    print()
    print("=" * 70)
    print("Evaluation Summary")
    print("=" * 70)
    print(f"Total cases     : {total}")
    print(f"Evaluated       : {evaluated}")
    print(f"Passed          : {passed}")
    print(f"Failed          : {failed}")
    print(f"Errors          : {errors}")
    print(f"Quota errors    : {quota_errors}")

    evaluated_score = round((passed / evaluated) * 100, 2) if evaluated > 0 else 0.0
    end_to_end_score = round((passed / total) * 100, 2) if total > 0 else 0.0

    external_calls = 0
    try:
        from raceintel.chat.gemini import GeminiClient
        external_calls = GeminiClient.get_external_call_count()
    except Exception:
        pass

    print(f"Evaluated Accuracy (Passed / Evaluated)     : {evaluated_score:.1f}% ({passed}/{evaluated})")
    print(f"End-to-End Success Rate (Passed / Total)     : {end_to_end_score:.1f}% ({passed}/{total})")
    print(f"Offline Mode Active                          : {offline}")
    print(f"External Gemini API Calls Attempted          : {external_calls}")
    if errors > 0:
        print(f"NOTE: {errors} error(s) excluded from Evaluated denominator, but included in End-to-End denominator.")

    print("\nCategory-wise Performance:")
    print("-" * 70)
    for cat, stats in sorted(category_stats.items()):
        cat_eval = stats["passed"] + stats["failed"]
        cat_score = round((stats["passed"] / cat_eval) * 100, 1) if cat_eval > 0 else 0.0
        stats["score_percent"] = cat_score
        print(f"  {cat:24s}: {cat_score:5.1f}% ({stats['passed']}/{cat_eval}) [Errors: {stats['errors']}]")

    if incorrect_answers:
        print("\nIncorrect Answers Identified:")
        print("-" * 70)
        for item in incorrect_answers[:10]:
            print(f"  - Case {item['id']} [{item['category']}]: {item['question']}")
            print(f"      Expected: {item['expected']}")
            print(f"      Actual:   {item['actual']}")
        if len(incorrect_answers) > 10:
            print(f"  ... and {len(incorrect_answers) - 10} more (see JSON results).")

    if unanswered_questions:
        print("\nUnanswered Questions Identified:")
        print("-" * 70)
        for item in unanswered_questions[:10]:
            print(f"  - Case {item['id']} [{item['category']}]: {item['status']} - {item['error']}")

    print("=" * 70)

    # Save results
    output = {
        "schema_version": "1.0",
        "evaluation": eval_title,
        "eval_file": str(target_eval_file),
        "total": total,
        "evaluated": evaluated,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "quota_errors": quota_errors,
        "offline_mode": offline,
        "external_api_calls_attempted": external_calls,
        "score_percent": evaluated_score if evaluated else None,
        "accuracy_percent": evaluated_score if evaluated else None,
        "evaluated_accuracy_percent": evaluated_score if evaluated else None,
        "end_to_end_success_percent": end_to_end_score if total else None,
        "category_performance": category_stats,
        "incorrect_answers": incorrect_answers,
        "unanswered_questions": unanswered_questions,
        "results": results,
    }

    target_output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(target_output_file, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, ensure_ascii=False)

    print()
    print("Detailed results saved to:")
    print(target_output_file)

    return output


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RaceIntel Benchmark Evaluator")
    parser.add_argument(
        "--eval-file",
        type=Path,
        default=None,
        help="Path to evaluation JSON dataset",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Path to results JSON file",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=API_URL,
        help="API URL for RaceIntel chat endpoint",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Run evaluation in-process using FastAPI TestClient (offline/reproducible)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run evaluation in explicit offline mode (blocks external Gemini calls, uses deterministic mock for LLM fallback)",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Evaluate on baseline dataset (raceintel_eval_2024.json)",
    )
    parser.add_argument(
        "--v2",
        action="store_true",
        help="Evaluate on Evaluation V2 dataset (raceintel_eval_v2.json)",
    )
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="Evaluate on Holdout V1 dataset (raceintel_holdout_v1.json)",
    )
    args = parser.parse_args()

    eval_path = args.eval_file
    out_path = args.output_file
    offline_mode = args.offline
    in_process_mode = args.in_process or args.offline

    if args.baseline and eval_path is None:
        eval_path = DEFAULT_EVALUATION_FILE
        if out_path is None:
            out_path = PROJECT_ROOT / "evaluation" / "raceintel_eval_v3c3_baseline_results.json"

    elif args.v2 and eval_path is None:
        eval_path = EVAL_V2_FILE
        if out_path is None:
            out_path = PROJECT_ROOT / "evaluation" / "raceintel_eval_v3c3_v2_results.json"

    elif args.holdout and eval_path is None:
        eval_path = HOLDOUT_FILE
        if out_path is None:
            out_path = PROJECT_ROOT / "evaluation" / "raceintel_eval_v3c3_holdout_results.json"

    run_evaluation(
        eval_file=eval_path,
        output_file=out_path,
        api_url=args.api_url,
        in_process=in_process_mode,
        offline=offline_mode,
    )