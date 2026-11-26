# RaceIntel — Phase 3C.1: Evaluation Matcher Integrity Report

## 1. Executive Summary

Phase 3C.1 was dedicated to auditing, hardening, and repairing the evaluation matcher in `evaluation/run_evaluation.py`. 

During Phase 3B, an independent audit revealed critical vulnerabilities in the original evaluation matcher, including contradiction false positives, numerical cross-talk (e.g. lap numbers matching points), refusal masks, and paraphrase false negatives. 

In Phase 3C.1:
- We redesigned the answer comparison architecture to enforce **strict factual validation, context-aware numerical extraction, negative assertion detection, and semantic paraphrase handling**.
- **16 isolated unit tests** were implemented in `tests/test_evaluation_matcher.py` and achieved a **100% pass rate (16/16)**.
- Full test suite expanded to **93 tests**, all passing (**93/93 passed**).
- Re-evaluated all three benchmarks on dedicated result files with zero regression on valid facts.
- **Strict Scope Integrity**: Application source code (`src/`), production SQLite (`data/raceintel.db`), and production ChromaDB (503 vectors) remained strictly untouched.

---

## 2. Original Matcher Weaknesses

Prior to this phase, `run_evaluation.py` suffered from five structural flaws:

| Flaw Category | Mechanism | Example | Prior Verdict | Real Validity |
| :--- | :--- | :--- | :---: | :---: |
| **Contradiction False Positive** | Raw substring search (`expected in actual`) ignored negative syntax and competing winner declarations. | *Expected: "Max Verstappen"*<br>*Actual: "Max Verstappen did not win the race; Lewis Hamilton won."* | **PASS** | **Invalid** (Direct negation) |
| **Numerical False Positive** | Extracted any standalone integer across the entire response without contextual association. | *Expected: 25.0 points*<br>*Actual: "Lando Norris scored 0 points after retiring on lap 25."* | **PASS** | **Invalid** (25 was a lap number) |
| **Refusal Mask False Positive** | Verified only the presence of a refusal keyword without checking for conflicting factual claims. | *Expected: "UNANSWERABLE"*<br>*Actual: "Fernando Alonso finished P12 in the 2024 French Grand Prix, but sector details are not available."* | **PASS** | **Invalid** (Fabricated result with refusal mask) |
| **Ambiguity Mask False Positive** | Verified only the presence of a clarification phrase without checking for fabricated race results. | *Expected: "AMBIGUOUS"*<br>*Actual: "Max Verstappen won the race. If you meant another event, please specify."* | **PASS** | **Invalid** (Fabricated result with ambiguity mask) |
| **Paraphrase False Negative** | Failed semantically accurate answers that lacked the literal string token. | *Expected: "Dry"*<br>*Actual: "There was zero precipitation and clear skies throughout the Grand Prix."* | **FAIL** | **Valid** (Factual synonym rejected) |
| **Sub-token False Positive** | Lack of word boundary enforcement caused short constructor names to match inside unrelated words. | *Expected: "RB"*<br>*Actual: "The turbo hybrid engine had an issue."* | **PASS** | **Invalid** ("turbo" contains "rb") |

---

## 3. Changes Implemented in `evaluation/run_evaluation.py`

### A. Context-Aware Numerical Extraction & Discrimination
- **Points Matching** (`category == "points"`): Restricts matching to explicit points patterns (`\bscored\s+(\d+)\b`, `(\d+)\s*points?`). Standalone integers associated with lap numbers (`lap 25`), round numbers (`round 12`), positions (`P7`), or calendar years (`2024`) are strictly excluded.
- **Temperature Matching** (`category == "weather"`): Implemented `extract_temperature()` to identify Celsius and degree patterns (`(\d+(?:\.\d+)?)\s*(?:°c|celsius|degrees)`).

### B. Entity Correctness, Negation & Contradiction Guard
- **Word Boundary Matching**: Replaced raw substring inclusion with boundary-delimited regex `\b{entity}\b`, preventing substring leaks (e.g. "RB" inside "turbo").
- **Negation Window Inspection**: When an expected entity is matched, the surrounding context ($\pm 35$ characters) is scanned for negation operators (`not`, `did not`, `didn't`, `never`, `was not`, `failed to`, `excluding`). If all mentions are negated, the matcher returns `False`.
- **Competing Winner Detection**: For `race_winner` and `season_awareness` questions, if the actual response explicitly asserts a competing driver as winner (e.g., *"Lewis Hamilton won the British Grand Prix in 2024. Max Verstappen finished P2"*), the matcher rejects the response even if the expected driver is mentioned.

### C. Refusal & Ambiguity Integrity
- **Refusal Validation** (`compare_unanswerable`): Requires a legitimate refusal phrase **and** asserts that the response does not contain fabricated factual claims (no winner assertions, no finishing positions `finished P12`, and no points scored).
- **Ambiguity Validation** (`compare_ambiguous`): Requires a clarification prompt **and** verifies that no arbitrary race winner, position, or points were fabricated.

### D. Semantic Paraphrase Support (`compare_weather_answer`)
- **Dry Conditions**: Maps semantic equivalents (`dry`, `no rainfall`, `zero precipitation`, `no precipitation`, `clear skies`, `clear conditions`, `did not rain`) while rejecting answers asserting wet conditions (`wet race`, `rainfall was recorded`).
- **Wet Conditions**: Maps semantic equivalents (`wet`, `rain`, `rainfall`, `rained`, `raining`, `precipitation`, `intermediate tyres`) while rejecting answers asserting clear/dry conditions (`no rain`, `completely dry`).

---

## 4. Test Cases & Verification Results

### New Isolated Matcher Test Suite: `tests/test_evaluation_matcher.py`

| Test Case Name | Tested Input Scenario | Expected Verdict | Matcher Status |
| :--- | :--- | :---: | :---: |
| `test_correct_entity_answer` | *"Max Verstappen won the Canadian Grand Prix in 2024."* | PASS | **PASS** |
| `test_wrong_entity_answer` | *"Lewis Hamilton won the race."* (Expected: Max Verstappen) | FAIL | **PASS** |
| `test_negated_expected_entity` | *"Max Verstappen did not win the race; Lewis Hamilton won."* | FAIL | **PASS** |
| `test_contradictory_winner_claims` | *"Lewis Hamilton won the British Grand Prix in 2024. Max Verstappen finished P2."* | FAIL | **PASS** |
| `test_subtoken_matching_prevention` | *"The turbo hybrid power unit was effective."* (Expected: "RB") | FAIL | **PASS** |
| `test_correct_points_value` | *"Lando Norris scored 25.0 points in the Miami Grand Prix."* | PASS | **PASS** |
| `test_incorrect_points_value_appearing_as_lap_number` | *"Lando Norris scored 0 points after retiring on lap 25."* (Expected: 25.0) | FAIL | **PASS** |
| `test_incorrect_position_appearing_as_points_value` | *"Oliver Bearman finished P7 and scored 6.0 points."* (Expected: 7.0 pts) | FAIL | **PASS** |
| `test_temperature_numerical_extraction` | *"The peak track temperature recorded was 54.6 degrees Celsius."* | PASS | **PASS** |
| `test_correct_paraphrased_weather_dry` | *"There was zero precipitation and clear skies throughout the Grand Prix."* | PASS | **PASS** |
| `test_correct_paraphrased_weather_wet` | *"Rainfall was recorded during the race, making intermediate tyres necessary."* | PASS | **PASS** |
| `test_incorrect_weather_answer` | *"The race was held under sunny, dry conditions with zero rain."* (Expected: Wet) | FAIL | **PASS** |
| `test_clean_refusal_passes` | *"I couldn't find that information in the retrieved race data..."* | PASS | **PASS** |
| `test_refusal_with_unsupported_factual_claims_fails` | *"Fernando Alonso finished P12 in the 2024 French GP, but details are not available."* | FAIL | **PASS** |
| `test_ambiguous_question_with_fabricated_answer_fails` | *"Max Verstappen won the race. If you meant another event, please specify."* | FAIL | **PASS** |
| `test_correct_clarification_response_passes` | *"The question is ambiguous. Please specify which Grand Prix you are referring to."* | PASS | **PASS** |

**Unit Test Result**: `16 passed, 0 failed in 0.12s`  
**Full Test Suite Result**: `93 passed, 0 failed in 13.24s`

---

## 5. Benchmark Score Comparison

All benchmarks were re-evaluated using the hardened matcher and saved to new, dedicated result files:

| Benchmark Dataset | Total Cases | Phase 3B Score | Phase 3C.1 Score | Result File |
| :--- | :---: | :---: | :---: | :--- |
| **Baseline (30 cases)** | 30 | 100.0% (30/30) | **100.0% (30/30)** | `evaluation/raceintel_eval_v3c1_baseline_results.json` |
| **Evaluation V2 (75 cases)** | 75 | 100.0% (75/75) | **100.0% (75/75)** | `evaluation/raceintel_eval_v3c1_v2_results.json` |
| **Holdout V1 (30 cases)** | 30 | 83.3% (25/30) | **86.2% (25/29)** | `evaluation/raceintel_eval_v3c1_holdout_results.json` |

*Holdout note: Evaluated 29 cases (25 passed, 4 failed). Case 103 encountered a transient upstream API 503 error during fallback and was recorded as an error.*

---

## 6. Remaining Limitations

1. **Natural Language Variation in Contradictions**: The matcher uses regex lookarounds and sentence-level windowing for negation. Complex multi-clause constructions (e.g., *"While it appeared that Norris might win, Verstappen prevailed"*) require full dependency parsing or an LLM-as-a-judge for general language evaluation.
2. **Context Window Slicing for Multi-Driver Reports**: For questions expecting multiple driver results within one team (e.g. `team_performance`), the matcher slices a 300-character window following each driver name. If a narrative spans across paragraphs, a driver section could exceed 300 characters.
3. **Transient External API Errors in Offline Evaluation**: When a question falls through direct deterministic rules to Gemini generation, offline evaluations without mock responses can encounter transient network/API issues. A mock LLM provider should be formalized for offline CI runs.

---

## 7. Scope & Integrity Confirmation

- **Application source code (`src/`)**: **Zero files modified.**
- **Production SQLite (`data/raceintel.db`)**: **Zero modifications.**
- **Production ChromaDB (`data/chroma`)**: **Document count confirmed at exactly 503.**
- **Existing datasets and previous evaluation result files**: **Strictly preserved.**
- **Files Modified**:
  - `evaluation/run_evaluation.py`
- **Files Created**:
  - `tests/test_evaluation_matcher.py`
  - `evaluation/raceintel_eval_v3c1_baseline_results.json`
  - `evaluation/raceintel_eval_v3c1_v2_results.json`
  - `evaluation/raceintel_eval_v3c1_holdout_results.json`
  - `evaluation/PHASE_3C_1_MATCHER_REPORT.md`
