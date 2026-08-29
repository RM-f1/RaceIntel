import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

EVALUATION_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "raceintel_eval_2024.json"
)


REQUIRED_CASE_FIELDS = {
    "id",
    "question",
    "category",
    "expected_answer",
    "expected_entities",
}


def validate():
    print("=" * 60)
    print("RaceIntel Evaluation Set Validation")
    print("=" * 60)

    if not EVALUATION_FILE.exists():
        print(f"\nERROR: File not found:")
        print(EVALUATION_FILE)
        return False

    try:
        with open(EVALUATION_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        print(f"\nERROR: Invalid JSON")
        print(exc)
        return False

    print(f"\nFile: {EVALUATION_FILE}")

    # ---------------------------------------------------------
    # Top-level checks
    # ---------------------------------------------------------

    if data.get("schema_version") != "1.0":
        print("ERROR: schema_version must be '1.0'")
        return False

    if data.get("season") != 2024:
        print("ERROR: season must be 2024")
        return False

    if data.get("question_count") != 30:
        print("ERROR: question_count must be 30")
        return False

    cases = data.get("cases")

    if not isinstance(cases, list):
        print("ERROR: cases must be a list")
        return False

    if len(cases) != 30:
        print(
            f"ERROR: Expected 30 cases, found {len(cases)}"
        )
        return False

    # ---------------------------------------------------------
    # Individual case checks
    # ---------------------------------------------------------

    ids = set()

    for index, case in enumerate(cases, start=1):

        missing = REQUIRED_CASE_FIELDS - set(case.keys())

        if missing:
            print(
                f"ERROR: Case {index} missing fields: "
                f"{sorted(missing)}"
            )
            return False

        case_id = case["id"]

        if case_id in ids:
            print(f"ERROR: Duplicate case ID: {case_id}")
            return False

        ids.add(case_id)

        if not isinstance(case["question"], str):
            print(
                f"ERROR: Case {case_id}: "
                "question must be a string"
            )
            return False

        if not isinstance(case["category"], str):
            print(
                f"ERROR: Case {case_id}: "
                "category must be a string"
            )
            return False

        if not isinstance(case["expected_entities"], dict):
            print(
                f"ERROR: Case {case_id}: "
                "expected_entities must be an object"
            )
            return False

    # ---------------------------------------------------------
    # Category check
    # ---------------------------------------------------------

    categories = sorted(
        {case["category"] for case in cases}
    )

    print(f"\nCases: {len(cases)}")
    print(f"Categories: {len(categories)}")

    for category in categories:
        count = sum(
            1
            for case in cases
            if case["category"] == category
        )

        print(f"  - {category}: {count}")

    # ---------------------------------------------------------
    # Success
    # ---------------------------------------------------------

    print("\n" + "=" * 60)
    print("VALIDATION PASSED")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = validate()

    if not success:
        raise SystemExit(1)