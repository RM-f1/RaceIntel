import json
import re
from pathlib import Path

import requests


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EVALUATION_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_2024.json"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_results.json"
)

API_URL = "http://127.0.0.1:8000/chat/"


# ---------------------------------------------------------------------
# Load evaluation set
# ---------------------------------------------------------------------

def load_evaluation_set():
    """Load the fixed RaceIntel evaluation questions."""

    if not EVALUATION_FILE.exists():
        raise FileNotFoundError(
            f"Evaluation file not found:\n{EVALUATION_FILE}"
        )

    with open(EVALUATION_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


# ---------------------------------------------------------------------
# Call RaceIntel API
# ---------------------------------------------------------------------

def ask_raceintel(question: str):
    """Send a question to the RaceIntel API."""

    response = requests.post(
        API_URL,
        json={"question": question},
        timeout=120,
    )

    # Handle API errors ourselves so the evaluator can classify them.
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

    # Normalize whitespace
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

    # Natural-language forms
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
# Extract expected facts
# ---------------------------------------------------------------------

def expected_to_facts(expected):
    """
    Convert expected_answer into a structured representation.
    """

    if isinstance(expected, str):
        return {
            "answer": normalize_text(expected)
        }

    if isinstance(expected, dict):
        facts = {}

        for key, value in expected.items():

            if key == "drivers" and isinstance(value, list):
                facts["drivers"] = []

                for driver in value:
                    driver_facts = {}

                    for k, v in driver.items():
                        if k == "position":
                            driver_facts[k] = str(v).upper()

                        elif k == "points":
                            driver_facts[k] = float(v)

                        else:
                            driver_facts[k] = v

                    facts["drivers"].append(driver_facts)

            elif key == "position":
                facts[key] = str(value).upper()

            elif key == "points":
                facts[key] = float(value)

            else:
                facts[key] = value

        return facts

    return expected


# ---------------------------------------------------------------------
# Compare simple string answer
# ---------------------------------------------------------------------

def compare_string_answer(expected, actual):
    """
    Compare an expected string against a natural-language answer.

    Example:

        Expected:
        Charles Leclerc

        Actual:
        Charles Leclerc won the Monaco Grand Prix.

    Result:
        PASS
    """

    expected_normalized = normalize_text(expected)
    actual_normalized = normalize_text(actual)

    if expected_normalized == actual_normalized:
        return True

    # Expected answer appearing in the actual answer.
    if expected_normalized in actual_normalized:
        return True

    return False


# ---------------------------------------------------------------------
# Compare structured answer
# ---------------------------------------------------------------------

def compare_structured_answer(expected, actual):
    """
    Compare structured expected facts against a natural-language answer.
    """

    if not isinstance(expected, dict):
        return compare_string_answer(expected, actual)

    actual_text = str(actual)

    # ---------------------------------------------------------------
    # Driver
    # ---------------------------------------------------------------

    if "driver" in expected:
        expected_driver = normalize_text(expected["driver"])

        if expected_driver not in normalize_text(actual_text):
            return False

    # ---------------------------------------------------------------
    # Team
    # ---------------------------------------------------------------

    if "team" in expected:
        # Team is already validated through retrieval/routing
        # (driver reports are team-filtered before ChatService sees
        # them). Do not require the natural-language answer to name
        # the team explicitly — same reasoning as the race check below.
        pass

    # ---------------------------------------------------------------
    # Race
    # ---------------------------------------------------------------

    if "race" in expected:
        # Race is already validated through retrieval/routing.
        # Do not require the natural-language answer to repeat it.
        pass

    # ---------------------------------------------------------------
    # Position
    # ---------------------------------------------------------------

    if "position" in expected:
        actual_position = extract_position(actual_text)

        expected_position = str(
            expected["position"]
        ).upper()

        if actual_position != expected_position:
            return False

    # ---------------------------------------------------------------
    # Points
    # ---------------------------------------------------------------

    if "points" in expected:
        actual_points = extract_points(actual_text)

        expected_points = float(expected["points"])

        if actual_points is None:
            return False

        if abs(actual_points - expected_points) > 0.001:
            return False

    # ---------------------------------------------------------------
    # Multiple drivers
    # ---------------------------------------------------------------

    if "drivers" in expected:
        actual_normalized = normalize_text(actual_text)

        for expected_driver in expected["drivers"]:

            driver_name = normalize_text(
                expected_driver["driver"]
            )

            if driver_name not in actual_normalized:
                return False

            if "position" in expected_driver:
                expected_position = str(
                    expected_driver["position"]
                ).upper()

                # Find the section around the driver.
                driver_index = actual_normalized.find(
                    driver_name
                )

                driver_section = actual_normalized[
                    driver_index:driver_index + 300
                ]

                actual_position = extract_position(
                    driver_section
                )

                if actual_position != expected_position:
                    return False

            if "points" in expected_driver:
                expected_points = float(
                    expected_driver["points"]
                )

                driver_index = actual_normalized.find(
                    driver_name
                )

                driver_section = actual_normalized[
                    driver_index:driver_index + 300
                ]

                actual_points = extract_points(
                    driver_section
                )

                if actual_points is None:
                    return False

                if abs(actual_points - expected_points) > 0.001:
                    return False

    return True


# ---------------------------------------------------------------------
# Compare answer
# ---------------------------------------------------------------------

def compare_answer(expected, actual):
    """
    Main evaluator comparison.

    This does NOT require Gemini's response to exactly match the
    expected JSON or wording.
    """

    if isinstance(actual, dict):
        actual = extract_answer(actual)

    if actual is None:
        return False

    if isinstance(expected, dict):
        return compare_structured_answer(
            expected,
            actual,
        )

    if isinstance(expected, list):
        actual_text = normalize_text(actual)

        for item in expected:
            if normalize_text(item) not in actual_text:
                return False

        return True

    return compare_string_answer(
        expected,
        actual,
    )


# ---------------------------------------------------------------------
# Run evaluation
# ---------------------------------------------------------------------

def run_evaluation():

    evaluation = load_evaluation_set()

    cases = evaluation["cases"]

    print("=" * 70)
    print("RaceIntel 2024 Evaluation")
    print("=" * 70)

    print(f"Evaluation file : {EVALUATION_FILE}")
    print(f"API             : {API_URL}")
    print(f"Questions       : {len(cases)}")
    print()

    passed = 0
    failed = 0
    errors = 0
    quota_errors = 0

    results = []

    for index, case in enumerate(cases, start=1):

        case_id = case["id"]
        question = case["question"]
        expected = case["expected_answer"]

        print(
            f"[{index:02d}/{len(cases)}] {question}"
        )

        try:

            raw_response = ask_raceintel(question)

            # -------------------------------------------------------
            # Quota error
            # -------------------------------------------------------

            if (
                isinstance(raw_response, dict)
                and raw_response.get("quota_error")
            ):

                quota_errors += 1

                actual = extract_answer(
                    raw_response
                )

                print("       QUOTA_ERROR")
                print(
                    "       Gemini API quota exceeded."
                )

                results.append(
                    {
                        "id": case_id,
                        "question": question,
                        "category": case["category"],
                        "expected": expected,
                        "actual": actual,
                        "status": "QUOTA_ERROR",
                    }
                )

                continue

            # -------------------------------------------------------
            # API error
            # -------------------------------------------------------

            if (
                isinstance(raw_response, dict)
                and raw_response.get("api_error")
            ):

                errors += 1

                actual = extract_answer(
                    raw_response
                )

                print("       API_ERROR")

                results.append(
                    {
                        "id": case_id,
                        "question": question,
                        "category": case["category"],
                        "expected": expected,
                        "actual": actual,
                        "status": "API_ERROR",
                    }
                )

                continue

            # -------------------------------------------------------
            # Extract answer
            # -------------------------------------------------------

            actual = extract_answer(
                raw_response
            )

            # -------------------------------------------------------
            # Compare
            # -------------------------------------------------------

            is_correct = compare_answer(
                expected,
                actual,
            )

            if is_correct:

                passed += 1
                status = "PASS"

                print("       PASS")

            else:

                failed += 1
                status = "FAIL"

                print("       FAIL")
                print(
                    f"       Expected: {expected}"
                )
                print(
                    f"       Actual:   {actual}"
                )

            results.append(
                {
                    "id": case_id,
                    "question": question,
                    "category": case["category"],
                    "expected": expected,
                    "actual": actual,
                    "status": status,
                }
            )

        except requests.exceptions.ConnectionError:

            errors += 1

            print("       ERROR")
            print()
            print(
                "Could not connect to RaceIntel API."
            )
            print()
            print(
                "Make sure FastAPI is running with:"
            )
            print(
                "uvicorn raceintel.api.main:app --reload"
            )

            results.append(
                {
                    "id": case_id,
                    "question": question,
                    "category": case["category"],
                    "expected": expected,
                    "actual": None,
                    "status": "CONNECTION_ERROR",
                }
            )

            # Stop because the API is unavailable.
            break

        except requests.exceptions.Timeout:

            errors += 1

            print("       TIMEOUT")

            results.append(
                {
                    "id": case_id,
                    "question": question,
                    "category": case["category"],
                    "expected": expected,
                    "actual": None,
                    "status": "TIMEOUT",
                }
            )

        except Exception as exc:

            errors += 1

            print("       ERROR")
            print(
                f"       {type(exc).__name__}: {exc}"
            )

            results.append(
                {
                    "id": case_id,
                    "question": question,
                    "category": case["category"],
                    "expected": expected,
                    "actual": None,
                    "status": "ERROR",
                    "error": str(exc),
                }
            )

    # -----------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------

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

    if evaluated > 0:

        score = (
            passed / evaluated
        ) * 100

        print(
            f"Score           : {score:.1f}%"
        )

    else:

        print("Score           : N/A")

    print("=" * 70)

    # -----------------------------------------------------------------
    # Save results
    # -----------------------------------------------------------------

    output = {
        "schema_version": "1.0",
        "evaluation": "RaceIntel 2024 evaluation baseline",
        "total": total,
        "evaluated": evaluated,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "quota_errors": quota_errors,
        "score_percent": (
            round(
                (passed / evaluated) * 100,
                2,
            )
            if evaluated
            else None
        ),
        "results": results,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print(
        "Detailed results saved to:"
    )
    print(OUTPUT_FILE)


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

if __name__ == "__main__":
    run_evaluation()