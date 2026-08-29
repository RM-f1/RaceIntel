
import json
from pathlib import Path

import requests


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EVALUATION_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_2024.json"
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
        data = json.load(file)

    return data


# ---------------------------------------------------------------------
# Call RaceIntel
# ---------------------------------------------------------------------

def ask_raceintel(question: str):
    """
    Send a question to the existing RaceIntel API.

    The evaluator talks to the API instead of importing internal
    RaceIntel components. This keeps evaluation independent from
    the implementation details of the retriever/LLM pipeline.
    """

    response = requests.post(
        API_URL,
        json={"question": question},
        timeout=120,
    )

    response.raise_for_status()

    return response.json()


# ---------------------------------------------------------------------
# Extract answer
# ---------------------------------------------------------------------

def extract_answer(response):
    """
    Extract the answer from the API response.

    RaceIntel's response format may evolve, so this checks common
    answer field names instead of assuming the entire response
    is the answer.
    """

    if isinstance(response, str):
        return response

    if not isinstance(response, dict):
        return response

    for key in ("answer", "response", "result", "message"):
        if key in response:
            return response[key]

    return response


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------

def normalize_text(value):
    """Normalize text for case-insensitive comparison."""

    return " ".join(str(value).lower().split())


def contains_number(actual_text, number):
    """
    Check whether a numeric value is represented in the answer.
    Handles values such as:
        25
        25.0
        25 points
    """

    text = normalize_text(actual_text)

    try:
        number = float(number)
    except (TypeError, ValueError):
        return str(number).lower() in text

    if number.is_integer():
        integer_value = str(int(number))

        patterns = [
            integer_value,
            f"{integer_value}.0",
        ]

        return any(pattern in text for pattern in patterns)

    return str(number) in text


def contains_position(actual_text, position):
    """
    Check whether a finishing position is represented.

    Examples:
        P1
        P2
        P10
        Position: P1
        Finishing Position: P1
    """

    text = normalize_text(actual_text)

    try:
        position = int(position)
    except (TypeError, ValueError):
        return str(position).lower() in text

    patterns = [
        f"p{position}",
        f"p{position}.",
        f"p{position},",
        f"position: p{position}",
        f"position p{position}",
        f"position {position}",
        f"finished: p{position}",
        f"finishing position: p{position}",
    ]

    return any(pattern in text for pattern in patterns)


def contains_laps(actual_text, laps):
    """
    Check whether the expected number of completed laps is represented.
    """

    text = normalize_text(actual_text)

    try:
        laps = int(laps)
    except (TypeError, ValueError):
        return str(laps).lower() in text

    patterns = [
        f"{laps} laps",
        f"laps: {laps}",
        f"laps completed: {laps}",
        f"completed {laps} laps",
    ]

    return any(pattern in text for pattern in patterns)


# ---------------------------------------------------------------------
# Compare answer
# ---------------------------------------------------------------------

def compare_answer(expected, actual):
    """
    Compare structured expected facts against RaceIntel's
    natural-language answer.

    Example:

        Expected:
            {"driver": "Charles Leclerc"}

        Actual:
            "Charles Leclerc won the Monaco Grand Prix."

        Result:
            PASS

    The evaluator checks every expected field instead of requiring
    the API response to have exactly the same JSON structure.
    """

    if not isinstance(expected, dict):
        return normalize_text(expected) == normalize_text(actual)

    if not isinstance(actual, str):
        return False

    actual_text = normalize_text(actual)

    for field, expected_value in expected.items():

        # -------------------------------------------------------------
        # Driver
        # -------------------------------------------------------------

        if field == "driver":
            value = normalize_text(expected_value)

            if value not in actual_text:
                return False

        # -------------------------------------------------------------
        # Constructor / Team
        # -------------------------------------------------------------

        elif field in {"constructor", "team"}:
            value = normalize_text(expected_value)

            if value not in actual_text:
                return False

        # -------------------------------------------------------------
        # Status
        # -------------------------------------------------------------

        elif field == "status":
            value = normalize_text(expected_value)

            if value not in actual_text:
                return False

        # -------------------------------------------------------------
        # Position
        # -------------------------------------------------------------

        elif field in {
            "position",
            "finishing_position",
        }:

            if not contains_position(
                actual,
                expected_value,
            ):
                return False

        # -------------------------------------------------------------
        # Points
        # -------------------------------------------------------------

        elif field in {
            "points",
            "points_scored",
        }:

            if not contains_number(
                actual,
                expected_value,
            ):
                return False

        # -------------------------------------------------------------
        # Laps completed
        # -------------------------------------------------------------

        elif field == "laps_completed":

            if not contains_laps(
                actual,
                expected_value,
            ):
                return False

        # -------------------------------------------------------------
        # Unknown field
        # -------------------------------------------------------------

        else:
            value = normalize_text(expected_value)

            if value not in actual_text:
                return False

    return True


# ---------------------------------------------------------------------
# Run evaluation
# ---------------------------------------------------------------------

def run_evaluation():
    """Run every evaluation question."""

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

            actual = extract_answer(raw_response)

            is_correct = compare_answer(
                expected,
                actual,
            )

            if is_correct:
                passed += 1
                status = "PASS"

            else:
                failed += 1
                status = "FAIL"

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

            print(f"       {status}")

            if not is_correct:
                print(
                    f"       Expected: {expected}"
                )
                print(
                    f"       Actual:   {actual}"
                )

        except requests.exceptions.ConnectionError:

            errors += 1

            print("       ERROR")
            print()
            print(
                "Could not connect to RaceIntel API."
            )
            print(
                "Make sure FastAPI is running with:"
            )
            print(
                "uvicorn raceintel.api.main:app --reload"
            )

            return

        except requests.exceptions.HTTPError as exc:

            errors += 1

            print("       ERROR")
            print(
                f"       HTTPError: {exc}"
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

    print()
    print("=" * 70)
    print("Evaluation Summary")
    print("=" * 70)

    print(f"Total   : {total}")
    print(f"Passed  : {passed}")
    print(f"Failed  : {failed}")
    print(f"Errors  : {errors}")

    if total > 0:
        score = (passed / total) * 100
    else:
        score = 0

    print(f"Score   : {score:.1f}%")

    print("=" * 70)

    # -----------------------------------------------------------------
    # Save results
    # -----------------------------------------------------------------

    output_file = (
        PROJECT_ROOT
        / "evaluation"
        / "raceintel_eval_results.json"
    )

    output = {
        "schema_version": "1.0",
        "evaluation": "RaceIntel 2024 evaluation baseline",
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "score_percent": round(score, 2),
        "results": results,
    }

    with open(
        output_file,
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
    print("Detailed results saved to:")
    print(output_file)


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

if __name__ == "__main__":
    run_evaluation()
