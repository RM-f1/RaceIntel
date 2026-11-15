import json
import numbers
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_EVALUATION_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_2024.json"
)

REQUIRED_CASE_FIELDS = {
    "id",
    "question",
    "category",
    "expected_answer",
}

VALID_CATEGORIES = {
    "race_winner",
    "driver_performance",
    "team_performance",
    "team_comparison",
    "points",
    "race_result",
    "finishing_position",
    "driver_standings",
    "constructor_standings",
    "lap_time",
    "weather",
    "race_conditions",
    "unanswerable",
    "ambiguous",
    "season_awareness",
}


def validate_expected_answer(case_id: int, expected_answer) -> bool:
    """Validate that expected_answer is well-formed according to supported types."""
    if expected_answer is None:
        print(f"ERROR: Case {case_id}: 'expected_answer' cannot be null")
        return False

    if isinstance(expected_answer, str):
        if not expected_answer.strip():
            print(f"ERROR: Case {case_id}: 'expected_answer' string cannot be empty")
            return False
        return True

    if isinstance(expected_answer, numbers.Real):
        return True

    if isinstance(expected_answer, list):
        if not expected_answer:
            print(f"ERROR: Case {case_id}: 'expected_answer' list cannot be empty")
            return False
        for item in expected_answer:
            if not isinstance(item, str) or not item.strip():
                print(f"ERROR: Case {case_id}: item in 'expected_answer' list must be non-empty string: {item!r}")
                return False
        return True

    if isinstance(expected_answer, dict):
        if not expected_answer:
            print(f"ERROR: Case {case_id}: 'expected_answer' dictionary cannot be empty")
            return False
        return True

    print(f"ERROR: Case {case_id}: unsupported 'expected_answer' type: {type(expected_answer).__name__}")
    return False


def validate(evaluation_file: Path | None = None) -> bool:
    eval_path = evaluation_file or DEFAULT_EVALUATION_FILE

    print("=" * 60)
    print("RaceIntel Evaluation Set Validation")
    print("=" * 60)
    print(f"File: {eval_path}")

    if not eval_path.exists():
        print(f"\nERROR: File not found: {eval_path}")
        return False

    try:
        with open(eval_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        print(f"\nERROR: Invalid JSON: {exc}")
        return False

    # ---------------------------------------------------------
    # Top-level checks
    # ---------------------------------------------------------

    if data.get("schema_version") != "1.0":
        print(f"ERROR: schema_version must be '1.0', got: {data.get('schema_version')!r}")
        return False

    if data.get("season") != 2024:
        print(f"ERROR: season must be 2024, got: {data.get('season')!r}")
        return False

    cases = data.get("cases")

    if not isinstance(cases, list):
        print("ERROR: 'cases' must be a list")
        return False

    if len(cases) < 1:
        print(f"ERROR: Expected at least 1 case, found {len(cases)}")
        return False

    # Optional question_count / total_cases validation if explicitly specified in file
    if "question_count" in data:
        if data["question_count"] != len(cases):
            print(
                f"ERROR: 'question_count' ({data['question_count']}) does not match len(cases) ({len(cases)})"
            )
            return False

    if "total_cases" in data:
        if data["total_cases"] != len(cases):
            print(
                f"ERROR: 'total_cases' ({data['total_cases']}) does not match len(cases) ({len(cases)})"
            )
            return False

    # ---------------------------------------------------------
    # Individual case checks
    # ---------------------------------------------------------

    ids = set()

    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            print(f"ERROR: Case {index} must be a JSON object, got {type(case).__name__}")
            return False

        missing = REQUIRED_CASE_FIELDS - set(case.keys())
        if missing:
            print(f"ERROR: Case {index} missing required fields: {sorted(missing)}")
            return False

        case_id = case["id"]

        if not isinstance(case_id, int):
            print(f"ERROR: Case index {index}: 'id' must be an integer, got {type(case_id).__name__}")
            return False

        if case_id in ids:
            print(f"ERROR: Duplicate case ID: {case_id}")
            return False

        ids.add(case_id)

        question = case["question"]
        if not isinstance(question, str) or not question.strip():
            print(f"ERROR: Case {case_id}: 'question' must be a non-empty string")
            return False

        category = case["category"]
        if not isinstance(category, str) or not category.strip():
            print(f"ERROR: Case {case_id}: 'category' must be a non-empty string")
            return False

        if category not in VALID_CATEGORIES:
            print(f"ERROR: Case {case_id}: unknown category '{category}'")
            return False

        if not validate_expected_answer(case_id, case["expected_answer"]):
            return False

    # ---------------------------------------------------------
    # Category summary
    # ---------------------------------------------------------

    categories = sorted({case["category"] for case in cases})

    print(f"\nTotal Cases: {len(cases)}")
    print(f"Categories ({len(categories)}):")

    for category in categories:
        count = sum(1 for case in cases if case["category"] == category)
        print(f"  - {category}: {count}")

    # ---------------------------------------------------------
    # Success
    # ---------------------------------------------------------

    print("\n" + "=" * 60)
    print("VALIDATION PASSED")
    print("=" * 60)

    return True


if __name__ == "__main__":
    target_file = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVALUATION_FILE
    success = validate(target_file)

    if not success:
        sys.exit(1)