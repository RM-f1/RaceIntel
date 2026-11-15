
import argparse
import json
import math
import numbers
from pathlib import Path
import sys

from datasets import Dataset

try:
    from ragas import evaluate
    from ragas.metrics import (
        faithfulness,
        context_precision,
        context_recall,
        answer_relevancy,
    )
    from ragas.llms import LangchainLLMWrapper
    from ragas.run_config import RunConfig
    from langchain_google_genai import (
        ChatGoogleGenerativeAI,
        GoogleGenerativeAIEmbeddings,
    )
    RAGAS_AVAILABLE = True
except ImportError:
    RAGAS_AVAILABLE = False

from raceintel.config import settings


# ============================================================
# PATHS AND CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

EVAL_FILE = (
    BASE_DIR
    / "evaluation"
    / "raceintel_eval_2024.json"
)

OUTPUT_FILE = (
    BASE_DIR
    / "evaluation"
    / "raceintel_ragas_results.json"
)

CACHE_FILE = (
    BASE_DIR
    / "evaluation"
    / "raceintel_ragas_pilot_cache.json"
)

PILOT_SIZE = 5

METRIC_NAMES = [
    "faithfulness",
    "context_precision",
    "context_recall",
    "answer_relevancy",
]

ERROR_MARKERS = [
    "resource_exhausted",
    "quota exceeded",
    "429 too many requests",
    "rate limit exceeded",
]


# ============================================================
# CACHE FUNCTIONS
# ============================================================

def load_cache(cache_file: Path = CACHE_FILE) -> dict:
    """Load cached context and answer pairs from disk."""
    if not cache_file.exists():
        return {}

    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("The pilot cache must contain a JSON object.")

    return data


def save_cache(cache: dict, cache_file: Path = CACHE_FILE) -> None:
    """Save cache dictionary atomically using a temporary file."""
    temp_file = cache_file.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    temp_file.replace(cache_file)


def validate_cache_entry(question: str, entry: dict) -> tuple[str, str]:
    """Validate a single cache entry's context and answer."""
    if not isinstance(entry, dict):
        raise ValueError(f"Invalid cache entry for question: {question}")

    context = entry.get("context")
    answer = entry.get("answer")

    if context is not None and not isinstance(context, str):
        raise RuntimeError(f"Cached context is invalid for: {question}")

    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError(f"Cached answer is invalid for: {question}")

    if any(marker in answer.lower() for marker in ERROR_MARKERS):
        raise RuntimeError(
            f"Cached answer looks like an API error for: {question}. "
            "Inspect or remove this cache entry before proceeding."
        )

    return context or "", answer


# ============================================================
# BUILD DATASET
# ============================================================

def build_ragas_dataset(
    cases: list[dict],
    cache: dict,
    retriever=None,
    chat_service=None,
    cache_file: Path | None = None,
) -> tuple[Dataset, dict]:
    """
    Build Ragas evaluation dataset by reusing cached context/answers
    or querying Retriever and ChatService on cache misses.
    """
    questions = []
    answers = []
    contexts = []
    ground_truths = []

    for index, case in enumerate(cases, start=1):
        question = case["question"]
        ground_truth = case["expected_answer"]

        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"Case {index} has an invalid question.")

        if question in cache:
            context, answer = validate_cache_entry(question, cache[question])
            print(f"[{index}/{len(cases)}] Using cached answer and context: {question}")
        else:
            if retriever is None or chat_service is None:
                raise RuntimeError(
                    f"Retriever and ChatService required to generate missing case {index}: {question}"
                )
            context = retriever.retrieve(question)
            if not isinstance(context, str):
                raise RuntimeError(f"Retriever returned invalid context for: {question}")

            answer = chat_service.ask(question)
            if not isinstance(answer, str) or not answer.strip():
                raise RuntimeError(f"RaceIntel returned an empty or invalid answer for: {question}")

            if any(marker in answer.lower() for marker in ERROR_MARKERS):
                raise RuntimeError(
                    "Possible Gemini quota/rate-limit error detected. Stopping before caching this answer."
                )

            cache[question] = {"context": context, "answer": answer}
            if cache_file is not None:
                save_cache(cache, cache_file)

        if context is None:
            context = ""
        context_list = [context] if context.strip() else []

        questions.append(question)
        answers.append(answer)
        contexts.append(context_list)
        ground_truths.append(
            json.dumps(ground_truth, ensure_ascii=False)
            if isinstance(ground_truth, dict)
            else str(ground_truth)
        )

    dataset = Dataset.from_dict(
        {
            # Standard Ragas 0.2.15 feature names
            "user_input": questions,
            "response": answers,
            "retrieved_contexts": contexts,
            "reference": ground_truths,
            # Backwards-compatible aliases
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        }
    )

    return dataset, cache


# ============================================================
# RUN EVALUATION
# ============================================================

def run_ragas_evaluation(
    dry_run: bool = False,
    pilot_size: int = PILOT_SIZE,
    cache_file: Path = CACHE_FILE,
    eval_file: Path = EVAL_FILE,
    output_file: Path = OUTPUT_FILE,
):
    if not eval_file.exists():
        raise FileNotFoundError(f"Evaluation dataset not found: {eval_file}")

    if pilot_size < 1:
        raise ValueError("pilot_size must be at least 1.")

    print("=" * 60)
    print("RaceIntel RAGAS Evaluation")
    print("=" * 60)
    print(f"Pilot size: {pilot_size}")

    with open(eval_file, "r", encoding="utf-8") as f:
        evaluation_data = json.load(f)

    all_cases = evaluation_data.get("cases")
    if not isinstance(all_cases, list) or not all_cases:
        raise ValueError("The evaluation dataset must contain a non-empty 'cases' list.")

    cases = all_cases[:pilot_size]
    print(f"Cases selected: {len(cases)}")

    cache = load_cache(cache_file)
    cached_count = sum(1 for c in cases if c.get("question") in cache)

    if dry_run:
        print()
        print("=" * 60)
        print("DRY RUN — VALIDATION ONLY")
        print("=" * 60)
        print(f"Dataset cases available: {len(all_cases)}")
        print(f"Pilot cases selected: {len(cases)}")
        print(f"Cached pilot cases: {cached_count}")
        print(f"Cases needing answer generation: {len(cases) - cached_count}")
        print(f"Cache file exists: {cache_file.exists()}")
        print("Gemini API calls: NONE")
        print("RAGAS scoring: SKIPPED")
        print("Dry run completed successfully.")
        return

    # Check if answer generation is needed on cache misses
    retriever = None
    chat_service = None
    if cached_count < len(cases):
        from raceintel.retrieval.retriever import Retriever
        from raceintel.chat.chat_service import ChatService

        retriever = Retriever()
        chat_service = ChatService()

    dataset, cache = build_ragas_dataset(
        cases=cases,
        cache=cache,
        retriever=retriever,
        chat_service=chat_service,
        cache_file=cache_file,
    )

    if len(dataset) != len(cases):
        raise RuntimeError("Dataset size mismatch. Evaluation will not start.")

    if not RAGAS_AVAILABLE:
        raise RuntimeError(
            "RAGAS dependencies are not installed in this environment. "
            "Please run with the 'ragas-venv' environment (Python 3.13) to execute scoring."
        )

    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing. Check your .env configuration.")

    print()
    print("=" * 60)
    print("Starting RAGAS scoring")
    print("=" * 60)
    print(
        "WARNING: RAGAS metric evaluation may make additional "
        "Gemini API calls, even when answers are cached."
    )

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0,
    )
    ragas_llm = LangchainLLMWrapper(llm)

    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/text-embedding-004",
        google_api_key=settings.GEMINI_API_KEY,
    )

    result = evaluate(
        dataset,
        metrics=[
            faithfulness,
            context_precision,
            context_recall,
            answer_relevancy,
        ],
        llm=ragas_llm,
        embeddings=embeddings,
        run_config=RunConfig(
            timeout=300,
            max_retries=2,
            max_wait=30,
            max_workers=2,
        ),
    )

    result_df = result.to_pandas()

    if result_df.empty:
        raise RuntimeError(
            "RAGAS returned no evaluation results. "
            "The existing results file will not be updated."
        )

    if len(result_df) != len(cases):
        raise RuntimeError(
            f"Expected {len(cases)} result rows but received "
            f"{len(result_df)}. The results file will not be updated."
        )

    for metric in METRIC_NAMES:
        if metric not in result_df.columns:
            raise RuntimeError(
                f"Missing expected metric: {metric}. "
                "The existing results file will not be updated."
            )

        if result_df[metric].isna().any():
            raise RuntimeError(
                f"Missing scores detected for {metric}. "
                "The existing results file will not be updated."
            )

        for row_index, score in enumerate(result_df[metric]):
            if (
                not isinstance(score, numbers.Real)
                or not math.isfinite(float(score))
                or not 0.0 <= float(score) <= 1.0
            ):
                raise RuntimeError(
                    f"Invalid {metric} score at row {row_index}: "
                    f"{score!r}. Scores must be finite numbers "
                    "between 0 and 1. The existing results file "
                    "will not be updated."
                )

    result_dict = result_df.to_dict(orient="records")
    for row in result_dict:
        for metric in METRIC_NAMES:
            row[metric] = float(row[metric])

    output = {
        "evaluation": "RaceIntel RAGAS evaluation",
        "season": 2024,
        "pilot_size": pilot_size,
        "cases": len(cases),
        "ragas_version": "0.2.15",
        "metrics": METRIC_NAMES,
        "results": result_dict,
    }

    output_temp = output_file.with_suffix(".tmp")
    with open(output_temp, "w", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
    output_temp.replace(output_file)

    print()
    print("=" * 60)
    print("RAGAS EVALUATION COMPLETE")
    print("=" * 60)

    for metric in METRIC_NAMES:
        values = [row[metric] for row in result_dict]
        average = sum(values) / len(values)
        print(f"{metric:20s}: {average:.4f}")

    print()
    print(f"Cases evaluated: {len(result_dict)}")
    print(f"Cache file: {cache_file}")
    print(f"Results saved to: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RaceIntel RAGAS Evaluator")
    parser.add_argument("--dry-run", action="store_true", help="Validate data and cache without API calls")
    parser.add_argument("--pilot-size", type=int, default=PILOT_SIZE, help="Number of pilot cases to evaluate")
    args = parser.parse_args()

    run_ragas_evaluation(
        dry_run=args.dry_run,
        pilot_size=args.pilot_size,
    )
