# RaceIntel — Phase 3B: Independent Generalisation & Evaluation Audit Report

## 1. Executive Summary

Phase 3B was commissioned to perform an independent, objective validation of the Phase 3A implementation. While Phase 3A achieved 100% accuracy on the 75-question Evaluation V2 benchmark, the purpose of Phase 3B is to determine whether the architecture genuinely generalises or whether performance was flattered by benchmark overfitting, narrow regex routing, and evaluation matcher vulnerabilities.

Strict protocol was maintained throughout this audit:
- **Zero application source code was modified.**
- **No benchmark datasets or previous results were overwritten.**
- **Production SQLite and ChromaDB (503 vectors) remained strictly unmodified.**
- **All findings are backed by reproducible empirical measurements.**

### Key Findings Summary:
1. **Benchmark Leakage Confirmed**: Multiple routing rules, ambiguity patterns, and out-of-domain exclusion lists were specifically tailored to the phrasing of Evaluation V2.
2. **Independent Holdout Benchmark (30 cases)**: Evaluated on `evaluation/raceintel_holdout_v1.json`, RaceIntel achieved **83.3% accuracy (25/30 passed, 5 failed)** without modifying application code.
3. **Empirical Failure Diagnosis**: All 5 holdout failures directly confirmed the audit's leakage hypotheses (rigid regex, missing calendar whitelisting, non-empty context masking out-of-domain queries).
4. **Matcher Vulnerabilities Exposed**: Empirical testing proved the evaluation matcher in `run_evaluation.py` suffers from false positives on contradiction, numerical collisions (lap numbers matching points), and refusal phrase presence in hallucinated answers.
5. **Retrieval Safety Limits**: Empirical testing of 28 queries against ChromaDB proved that a 0.55 cosine distance threshold alone cannot separate Formula 1 from other motorsports (e.g., NASCAR Daytona 500 at 0.4404, MotoGP at 0.4389).

---

## 2. Benchmark Leakage Audit Findings

Inspection of `chat_service.py`, `retriever.py`, and structured query services identified four distinct mechanisms of benchmark tailoring:

### A. Hardcoded Keyword Exclusion Lists
In `src/raceintel/chat/chat_service.py` (lines 811–814):
```python
if any(term in q_lower for term in ["500", "le mans", "daytona", "french grand prix", "nascar", "motogp"]):
    return "I couldn't find that information in the retrieved race data. That event is not part of the Formula 1 2024 calendar."
```
- **Finding**: This list directly mirrors questions 64 (*"Indianapolis 500"*), 65 (*"24 Hours of Le Mans"*), and 66 (*"French Grand Prix"*) from Evaluation V2.
- **Leakage Consequence**: Other unheld Grand Prix races (e.g. *German Grand Prix*, *Russian Grand Prix*) or major motorsports (e.g. *Bathurst 1000*, *Rally Finland*) bypass this filter.

### B. Masked Exclusion Gating (`if not context:`)
In `chat_service.py` (lines 805–814), the exclusion check is placed inside `if not context:`.
- **Finding**: When an out-of-domain query contains words like "championship" or "2024", `_extract_filters()` assigns `filters={'season': 2024, 'document_type': 'race_report'}`. Semantic retrieval returns 5 generic 2024 race reports.
- **Leakage Consequence**: Because `context` is non-empty, `if not context:` evaluates to `False`. The query bypasses the exclusion check, falls through `_direct_answer()`, and triggers LLM fallback.

### C. Overly Narrow Standings Routing
In `chat_service.py` (lines 671–678):
```python
standings_keywords = [
    "leads the driver standings",
    "leading the driver standings",
    "leads the championship",
    "leading the championship",
    "driver standings after",
    "championship leader after",
]
```
- **Finding**: Routing relies on exact multi-word substrings anchored to "after" or "leading".
- **Leakage Consequence**: Natural phrasings such as *"Which driver had the championship lead following the Canadian Grand Prix?"* or *"Who was top of the standings after round 9?"* fail to route and drop into LLM fallback.

### D. Anchored Ambiguity Patterns
In `chat_service.py` (lines 633–640) and `retriever.py` (lines 482–489):
```python
race_patterns = [
    r"^who won(?: the race)?\??$",
    r"^who won\??$",
    r"^who (?:was|is) the winner\??$",
    ...
]
```
- **Finding**: Regex patterns use start (`^`) and end (`$`) anchors matching the exact 4-word question *"Who won the race?"*.
- **Leakage Consequence**: Phrasings with conversational prefixes or suffixes (e.g. *"Can you tell me who won the race?"* or *"Who won the race last weekend?"*) fail the regex.

---

## 3. Evaluation Matcher Reliability Audit

Using `audit_matcher.py`, we audited the comparison functions in `run_evaluation.py` against edge cases.

### Empirical Test Matrix:

| Test Case | Expected Ground Truth | Actual Model Output | Matcher Verdict | Real Status | Explanation |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Contradiction False Positive** | `"Max Verstappen"` | *"Max Verstappen did not win the race; Lewis Hamilton won."* | **PASS** | **FALSE POSITIVE** | Substring search `expected in actual` ignores negative syntax. |
| **Numerical False Positive** | `25.0` | *"Lando Norris scored 0 points after retiring on lap 25."* | **PASS** | **FALSE POSITIVE** | Regex `\b\d+\b` extracts lap 25 and matches points ground truth. |
| **Hallucination in Refusal** | `"UNANSWERABLE"` | *"Fernando Alonso finished P12 in the 2024 French Grand Prix, but sector details are not available."* | **PASS** | **FALSE POSITIVE** | Checks only for `"not available"` substring, ignoring the fabricated result. |
| **Hallucination in Ambiguity** | `"AMBIGUOUS"` | *"Max Verstappen won the race. If you meant another event, please specify."* | **PASS** | **FALSE POSITIVE** | Checks only for `"please specify"`, ignoring the arbitrary winner hallucination. |
| **Paraphrase False Negative** | `"Dry"` | *"There was zero precipitation and clear skies throughout the Grand Prix."* | **FAIL** | **FALSE NEGATIVE** | Factual synonym lacks the literal substring `"dry"`. |
| **Affirmation False Negative** | `"Yes"` | *"Rainfall was recorded during the race, making intermediate tyres necessary."* | **FAIL** | **FALSE NEGATIVE** | Descriptive confirmation lacks the literal token `"yes"`. |
| **Sub-token False Positive** | `"RB"` | *"The turbo hybrid engine had an issue."* | **PASS** | **FALSE POSITIVE** | Substring `"rb"` matches inside the word `"turbo"`. |

### Conclusion on Matcher:
The evaluation matcher has an asymmetric bias: it is overly lenient on responses that include the expected entity alongside contradictions or hallucinations, while being overly strict on paraphrased semantic truths.

---

## 4. SQL Correctness & Database Audit

An independent SQL investigation of `data/raceintel.db` via `audit_sql.py` confirmed:

### A. Monotonicity of `session_id`
- Exactly 24 race sessions exist in `sessions`, strictly contiguous from `session_id = 2` to `session_id = 25`.
- Chronological alignment:
  - Round 1: Bahrain (`session_id = 2`)
  - Round 9: Canada (`session_id = 10`)
  - Round 12: Britain (`session_id = 13`)
  - Round 24: Abu Dhabi (`session_id = 25`)
- **Conclusion**: `session_id <= target_session_id` correctly segments chronological event history for the 2024 season.

### B. Sprint Race Point Limitation
- In `data/raceintel.db`, all sessions in `sessions` are categorized as `session_type = 'Race'`.
- **Finding**: Saturday Sprint race results (China, Miami, Austria, Austin, Brazil, Qatar) are **not present** in `race_results`.
- Cumulative points after the British Grand Prix (Round 12) calculate to **231.0 points** for Max Verstappen, whereas the official FIA total was **255.0 points** (including 24 Sprint points).
- The evaluation passes because the benchmark expects driver name `"Max Verstappen"` rather than the exact numerical total.

### C. Constructor Points & Ties
- Full database scan across all 24 rounds revealed that Round 9 (Canadian Grand Prix) was the **only** race in 2024 where two constructors tied for maximum points (McLaren: 28.0 pts, Mercedes: 28.0 pts).
- The tie-handling query correctly extracts both constructors.

### D. Lap-Time Telemetry Integrity
- Total laps in `laps`: 26,604.
- `NULL` lap times: exactly 223 (in-laps, out-laps, retirements).
- Negative or zero lap times: 0.
- Min valid lap: 67.694s (Austria).
- The filter `lap_time_seconds IS NOT NULL AND lap_time_seconds > 0 ORDER BY lap_time_seconds ASC LIMIT 1` is completely sound.

### E. Weather Aggregation & Sensor Noise Sensitivity
- Races with genuine heavy rain: Canada (31 rain observations), Britain (51 obs), São Paulo (117 obs).
- **Sensor Noise Finding**: Spain had 1 rain observation out of 154, and Austria had 1 rain observation out of 143.
- The rule `rain_obs > 0 => Wet` classifies the 2024 Spanish and Austrian Grands Prix as "Wet" due to single-minute sensor blips, despite both running entirely on dry slick tyres.
- **Recommendation**: Require a minimum noise threshold (e.g., `rain_obs >= 5` or `> 3%` of session observations).

---

## 5. Retrieval Generalisation Audit

We tested the 0.55 distance threshold across 28 diverse queries in ChromaDB (`all-MiniLM-L6-v2` embeddings) via `audit_retrieval.py`:

| Category | Query | Min Distance | Result (<= 0.55) | Audit Assessment |
| :--- | :--- | :---: | :---: | :--- |
| **Valid F1** | *"Who finished on the podium at the 2024 Belgian Grand Prix?"* | **0.3197** | Accepted | True Positive |
| **Valid F1** | *"What happened to Charles Leclerc in the 2024 Monaco Grand Prix?"* | **0.3785** | Accepted | True Positive |
| **Valid F1** | *"Did Max Verstappen get a penalty in Austria 2024?"* | **0.5815** | **Rejected** | **FALSE REJECTION** |
| **Valid F1 (No GP)** | *"Who had the highest top speed at Spa?"* | **0.5555** | **Rejected** | **FALSE REJECTION** |
| **Valid F1 (No GP)** | *"Did Ferrari score a 1-2 finish this year?"* | **0.4127** | Accepted | True Positive |
| **Historical F1** | *"Who won the 2021 Abu Dhabi Grand Prix?"* | **0.3250** | **Accepted** | **FALSE ACCEPTANCE** |
| **Other Motorsport** | *"Who won the 2024 Daytona 500 in NASCAR?"* | **0.4404** | **Accepted** | **FALSE ACCEPTANCE** |
| **Other Motorsport** | *"Who is leading the 2024 MotoGP World Championship?"* | **0.4389** | **Accepted** | **FALSE ACCEPTANCE** |
| **Other Motorsport** | *"Who won the Bathurst 1000 in 2024?"* | **0.4354** | **Accepted** | **FALSE ACCEPTANCE** |
| **Ambiguous** | *"How many points did they get?"* | **0.5396** | **Accepted** | **FALSE ACCEPTANCE** |
| **Non-Motorsport** | *"What is the capital of Australia?"* | **0.7453** | Rejected | True Negative |
| **Non-Motorsport** | *"How do quantum computers factor large integers?"* | **0.9347** | Rejected | True Negative |

### Key Takeaway:
General sports and motorsport questions cluster tightly in the 0.40–0.50 distance range. Cosine distance alone **cannot** distinguish Formula 1 from NASCAR, MotoGP, or Australian Supercars. Robustness requires metadata and entity whitelisting, not distance threshold tuning alone.

---

## 6. Independent Holdout Evaluation Results

### Dataset: `evaluation/raceintel_holdout_v1.json` (30 Cases)
- 30 new, non-overlapping questions created.
- Conversational phrasing (*"chequered flag"*, *"claimed victory"*, *"crowned champion"*).
- Executed offline in-process via FastAPI TestClient without modifying application code.
- Detailed results saved to `evaluation/raceintel_holdout_v1_results.json`.

### Comparative Accuracy Across All Three Benchmarks:

| Benchmark Dataset | Total Cases | Accuracy | Status |
| :--- | :---: | :---: | :--- |
| **Baseline (Original Benchmark)** | 30 | **100.0% (30/30)** | Verified reproducible |
| **Evaluation V2 (Phase 2 Expanded)** | 75 | **100.0% (75/75)** | Verified reproducible |
| **Holdout V1 (Phase 3B Independent)** | 30 | **83.3% (25/30)** | **Empirical ground truth measured** |

### Category Breakdown (Holdout V1):

| Category | Cases | Passed | Failed | Accuracy |
| :--- | :---: | :---: | :---: | :---: |
| `ambiguous` | 2 | 2 | 0 | 100.0% |
| `constructor_standings` | 2 | 2 | 0 | 100.0% |
| `driver_standings` | 3 | 2 | 1 | 66.7% |
| `finishing_position` | 2 | 2 | 0 | 100.0% |
| `lap_time` | 3 | 3 | 0 | 100.0% |
| `points` | 2 | 2 | 0 | 100.0% |
| `race_result` | 1 | 1 | 0 | 100.0% |
| `race_winner` | 5 | 5 | 0 | 100.0% |
| `season_awareness` | 2 | 1 | 1 | 50.0% |
| `unanswerable` | 4 | 1 | 3 | 25.0% |
| `weather` | 4 | 4 | 0 | 100.0% |
| **Total** | **30** | **25** | **5** | **83.3%** |

---

## 7. Deep-Dive on Failed Holdout Cases

Every single failure in the holdout evaluation directly confirmed our prior code audit:

| Case ID | Category | Question | Root Cause Diagnosis |
| :---: | :--- | :--- | :--- |
| **119** | `driver_standings` | *Which driver had the championship lead following the 2024 Canadian Grand Prix?* | **Narrow Regex**: Query used `"championship lead following"` instead of `"after"` or `"leading"`. Failed routing and fell through to LLM fallback. |
| **124** | `season_awareness` | *Did Lando Norris win the Miami Grand Prix?* | **Narrow Winner Parser**: `_direct_answer` checks for `"who won"` or `"which driver won"`, missing `"Did [Driver] win"`. Dropped into LLM fallback. |
| **126** | `unanswerable` | *What was the race result of the 2024 German Grand Prix?* | **Incomplete Whitelist**: `"german grand prix"` was omitted from the hardcoded exclusion list `["500", "le mans", "daytona", "french grand prix"]`. Retrieved generic docs and failed. |
| **127** | `unanswerable` | *Who won the 2024 Bathurst 1000?* | **Incomplete Whitelist & Distance Leakage**: Bathurst 1000 had distance 0.4354 (< 0.55) and was absent from exclusion list. |
| **128** | `unanswerable` | *Who won the 2024 MotoGP World Championship?* | **Gating Flaw (`if not context`)**: Query extracted `season=2024, document_type=race_report`, retrieving 5 F1 reports. Because `context` was non-empty, the exclusion check was bypassed. |

---

## 8. Confirmed Bugs & Unresolved Risks

1. **Calendar Validation Missing**: System lacks an authoritative calendar lookup from the `events` table. Non-existent Grands Prix (e.g. German GP, French GP) should be validated against SQLite events before vector search.
2. **Context Gating Bypass**: The `if not context:` check prevents out-of-domain rejection when unrelated documents are retrieved.
3. **Rigid Keyword Routing**: Routing depends on specific phrasing rather than semantic intent.
4. **Weather Sensor Noise**: 1 rain observation in Spain and Austria triggers a "Wet" race classification for dry races.
5. **Sprint Race Data Omission**: Sprint races are absent from SQLite, leading to incorrect championship totals.
6. **Matcher Asymmetry**: Matcher allows contradictions and lap numbers to pass while failing valid paraphrases.

---

## 9. File Inventory & Audit Integrity Confirmation

### Files Created During Phase 3B:
- `evaluation/raceintel_holdout_v1.json`: 30 new, independent, grounded benchmark questions.
- `evaluation/raceintel_holdout_v1_results.json`: Full execution output of the holdout benchmark (83.3% accuracy).
- `evaluation/archive/reports/PHASE_3B_VALIDATION_REPORT.md`: This report.
- Scratch diagnostic scripts: `audit_matcher.py`, `audit_sql.py`, `audit_retrieval.py`, `verify_holdout_facts.py`, `inspect_tables.py` in local audit scratch files.

### Integrity Confirmation:
- **Application source code**: **Unchanged**. Zero lines in `src/` were modified.
- **Production database (`data/raceintel.db`)**: **Unchanged**. Strictly read-only operations.
- **ChromaDB (`data/chroma`)**: **Unchanged**. Document count confirmed at exactly **503**.
- **Existing datasets & results**: Baseline and Evaluation V2 files strictly preserved.

---

## 10. Recommended Next Engineering Phase (Phase 4)

1. **Authoritative Calendar Whitelist**: Check `events` table directly. If a query mentions an unheld race, reject immediately before retrieval.
2. **Semantic Intent Classifier**: Replace brittle regex with a robust intent classifier or structured query mapper.
3. **Sensor Noise Thresholding**: Require `rain_obs >= 5` or `> 3%` of session observations to classify a session as Wet.
4. **Evaluation Matcher Upgrade**: Enhance `run_evaluation.py` to check for negative assertions (contradictions) and isolate numerical tokens by entity proximity.
5. **Sprint Race Ingestion**: Add sprint race sessions to `sessions` and `race_results` to ensure complete championship points calculations.
