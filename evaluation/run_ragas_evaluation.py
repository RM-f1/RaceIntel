
import json
import math
import numbers
from pathlib import Path
from ragas.run_config import RunConfig

from datasets import Dataset

from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    context_precision,
    context_recall,
    answer_relevancy,
)
from ragas.llms import LangchainLLMWrapper
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from raceintel.chat.chat_service import ChatService
from raceintel.retrieval.retriever import Retriever
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

# Quota-efficient pilot. The full dataset remains unchanged.
PILOT_SIZE = 3

# Set to True to validate configuration and data without API calls.
DRY_RUN = False


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
# PRE-FLIGHT CHECKS
# ============================================================


if not DRY_RUN and not settings.GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is missing. Check your .env configuration."
    )


if not EVAL_FILE.exists():
    raise FileNotFoundError(
        f"Evaluation dataset not found: {EVAL_FILE}"
    )

if PILOT_SIZE < 1:
    raise ValueError("PILOT_SIZE must be at least 1.")

print("=" * 60)
print("RaceIntel RAGAS Evaluation")
print("=" * 60)

print(f"Pilot size: {PILOT_SIZE}")

if DRY_RUN:
    print("Mode: DRY RUN — no evaluation API calls.")
else:
    print("Mode: LIVE — API calls may occur during generation and scoring.")



# ============================================================
# LOAD EVALUATION CASES
# ============================================================

with open(EVAL_FILE, "r", encoding="utf-8") as f:
    evaluation_data = json.load(f)

all_cases = evaluation_data.get("cases")

if not isinstance(all_cases, list) or not all_cases:
    raise ValueError(
        "The evaluation dataset must contain a non-empty 'cases' list."
    )

cases = all_cases[:PILOT_SIZE]

print(f"Cases selected: {len(cases)}")



# ============================================================
# LOAD CACHE
# ============================================================

cache = {}

if CACHE_FILE.exists():
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)

if not isinstance(cache, dict):
    raise ValueError(
        "The pilot cache must contain a JSON object."
    )

else:
    cache = {}

if DRY_RUN:
    cached_count = sum(
        1 for case in cases
        if case.get("question") in cache
    )

    print()
    print("=" * 60)
    print("DRY RUN — VALIDATION ONLY")
    print("=" * 60)
    print(f"Dataset cases available: {len(all_cases)}")
    print(f"Pilot cases selected: {len(cases)}")
    print(f"Cached pilot cases: {cached_count}")
    print(f"Cases needing answer generation: {len(cases) - cached_count}")
    print(f"Cache file exists: {CACHE_FILE.exists()}")
    print("Gemini API calls: NONE")
    print("RAGAS scoring: SKIPPED")
    print("Dry run completed successfully.")
    raise SystemExit(0)



# ============================================================
# INITIALIZE RACEINTEL
# ============================================================

retriever = Retriever()
chat_service = ChatService()


# ============================================================
# INITIALIZE GEMINI FOR RAGAS
# ============================================================

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=settings.GEMINI_API_KEY,
    temperature=0,
)

ragas_llm = LangchainLLMWrapper(llm)

embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=settings.GEMINI_API_KEY,
)


# ============================================================
# BUILD RAGAS DATASET
# ============================================================

questions = []
answers = []
contexts = []
ground_truths = []

for index, case in enumerate(cases, start=1):
    question = case["question"]
    ground_truth = case["expected_answer"]

    if not isinstance(question, str) or not question.strip():
        raise ValueError(
            f"Case {index} has an invalid question."
        )

    print(f"\n[{index}/{len(cases)}] {question}")

    # Reuse previously generated RaceIntel outputs.
    if question in cache:
        cached_item = cache[question]

        if not isinstance(cached_item, dict):
            raise ValueError(
                f"Invalid cache entry for question: {question}"
            )

        context = cached_item.get("context")
        answer = cached_item.get("answer")

        # Validate cached data before using it.
        if not isinstance(context, str):
            raise RuntimeError(
                f"Cached context is invalid for: {question}"
            )

        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError(
                f"Cached answer is invalid for: {question}"
            )

        if any(
            marker in answer.lower()
            for marker in ERROR_MARKERS
        ):
            raise RuntimeError(
                f"Cached answer looks like an API error for: {question}. "
                "Inspect or remove this cache entry before proceeding."
            )

        print("Using cached answer and context.")

    else:
        # Retrieve context and generate a new RaceIntel answer.
        # If an API exception occurs, it propagates and stops the script.
        context = retriever.retrieve(question)

        if not isinstance(context, str):
            raise RuntimeError(
                f"Retriever returned invalid context for: {question}"
            )

        answer = chat_service.ask(question)

        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError(
                f"RaceIntel returned an empty or invalid answer "
                f"for: {question}"
            )

        if any(
            marker in answer.lower()
            for marker in ERROR_MARKERS
        ):
            raise RuntimeError(
                "Possible Gemini quota/rate-limit error detected. "
                "Stopping before caching this answer."
            )

        # Save each completed case immediately.
        # Existing cache entries for other questions are preserved.
        cache[question] = {
            "context": context,
            "answer": answer,
        }

        cache_temp = CACHE_FILE.with_suffix(".tmp")

        with open(cache_temp, "w", encoding="utf-8") as f:
            json.dump(
                cache,
                f,
                indent=2,
                ensure_ascii=False,
            )

        cache_temp.replace(CACHE_FILE)

    questions.append(question)
    answers.append(answer)
    contexts.append([context])

    ground_truths.append(
        json.dumps(ground_truth, ensure_ascii=False)
        if isinstance(ground_truth, dict)
        else str(ground_truth)
    )

    print("Answer:", answer)
    print("Context length:", len(context))


# ============================================================
# CREATE DATASET
# ============================================================

dataset = Dataset.from_dict(
    {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    }
)

if len(dataset) != len(cases):
    raise RuntimeError(
        "Dataset size mismatch. Evaluation will not start."
    )


# ============================================================
# RUN RAGAS
# ============================================================

print()
print("=" * 60)
print("Starting RAGAS scoring")
print("=" * 60)
print(
    "WARNING: RAGAS metric evaluation may make additional "
    "Gemini API calls, even when answers are cached."
)

# This is the API-consuming stage.
# Do not run until the available Gemini quota is confirmed.
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

# ============================================================
# VALIDATE RESULTS BEFORE SAVING
# ============================================================

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


# Convert metric values to standard Python floats for JSON.
result_dict = result_df.to_dict(orient="records")

for row in result_dict:
    for metric in METRIC_NAMES:
        row[metric] = float(row[metric])


# ============================================================
# PREPARE OUTPUT
# ============================================================

output = {
    "evaluation": "RaceIntel RAGAS evaluation",
    "season": 2024,
    "pilot_size": PILOT_SIZE,
    "cases": len(cases),
    "ragas_version": "0.2.15",
    "metrics": METRIC_NAMES,
    "results": result_dict,
}

# Write to a temporary file first so an interrupted write
# is less likely to damage an existing results file.
output_temp = OUTPUT_FILE.with_suffix(".tmp")

with open(output_temp, "w", encoding="utf-8") as f:
    json.dump(
        output,
        f,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )

output_temp.replace(OUTPUT_FILE)


# ============================================================
# SUMMARY
# ============================================================

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
print(f"Cache file: {CACHE_FILE}")
print(f"Results saved to: {OUTPUT_FILE}")
