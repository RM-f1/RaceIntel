# RaceIntel — Phase 5D Independent Revalidation Report

## 1. Objective & Protocol Compliance

Phase 5D evaluated RaceIntel after Phases 5A–5C under a **pre-registered, frozen, single-shot offline evaluation protocol**:

1. Audited `evaluation/run_independent_benchmark.py` (Phase 4E evaluator) and documented its structural weaknesses.
2. Constructed a fresh 80-question dataset (`evaluation/raceintel_independent_v2.json`) verified against read-only SQLite (`data/raceintel.db`) and ChromaDB (`raceintel_knowledge`, 503 docs) ground truth, with **zero exact duplicates** across Baseline (30), V2 (75), Holdout (30), and Ind-v1 (80).
3. Built a stricter evaluator (`evaluation/run_independent_v2.py`) and validated its anti-false-positive logic on synthetic test cases (`tests/test_phase_5d_evaluator.py`, 6/6 passed) **before** touching real model runs.
4. Recorded pre-execution SHA256 hashes of `raceintel_independent_v2.json`, `run_independent_v2.py`, and all `82` `src/**/*.py` source files in `evaluation/phase_5d_frozen_manifest.json`.
5. Executed `evaluation/run_independent_v2.py` **once**, offline (`0` live Gemini calls), and did **not** patch `src/` or `run_independent_v2.py` afterward to inflate the score.

---

## 2. Phase 4E Evaluator Audit Findings

Auditing `evaluation/run_independent_benchmark.py` (lines 1–980) identified five methodological and scoring limitations:

1. **Post-inspection edits (non-frozen reference)**: In Phase 4E, `run_independent_benchmark.py` was modified after inspecting initial v1 failures; therefore v1 (`61/80`) is a historical regression reference rather than a clean zero-leakage test.
2. **Permissive RAG grounding (`rag_grounded` & `rag_fact`)**: `rag_grounded` required only `must_mention_any` (at least one entity) rather than complete multi-entity coverage (`must_mention_all`), and did not cleanly separate retrieval hit accuracy from answer synthesis completeness.
3. **Sub-metric leakage into `unsupported_answer_rate`**: Several SQL formatting/routing mismatches returned `evidence_grounded: False` even when the issue was a routing miss or partial match rather than an unsupported fabrication.
4. **Dual execution telemetry trace**: Telemetry pre-probed `_extract_filters`, `_route_structured_query`, and `_retrieve_with_safety` before running `service.ask(q)` rather than extracting single-pass execution metadata cleanly inside `ChatService`.
5. **Naive substring checks in `check_entity_resolution`**: Allowed 4+ character substrings against the question text rather than full token/variant boundary checks.

### Improvements Applied in `evaluation/run_independent_v2.py`

- Enforces `clauses` co-occurrence (entity + number/position must appear in the same line/clause).
- Enforces exact position tokens (`P1` cannot match `P10`) and boundary-safe number extraction (`7` cannot match `77` or `17`).
- Strips negated weather phrases (`"no rainfall"`, `"0 rainfall"`) before checking wet keywords (`_detect_weather_polarity`).
- Replaces `must_mention_any` with `rag_complete` (`must_mention_all` + `source_hit` + `_token_support_ratio >= 0.45`) and reports `rag_retrieval_source_hit_rate` separately from `rag_answerable_complete_accuracy`.
- Records `benchmark_sha256` and `runner_sha256` inside `evaluation/raceintel_independent_v2_results.json`.

---

## 3. Pre-Run Frozen Manifest & Post-Run Verification

Recorded in `evaluation/phase_5d_frozen_manifest.json` **before** executing `run_independent_v2.py` and verified byte-identical after execution (`0` mismatches across `82` `src/**/*.py` files):

| Artifact | SHA256 |
|---|---|
| `evaluation/raceintel_independent_v2.json` | `61246124c121757a3b5c2343fbb2eac98f6741af2ac6a580725cb72011339d3a` |
| `evaluation/run_independent_v2.py` | `9ede6048511c19525a65761afd661f219138b21828c5a0763ea19d19ac20404f` |
| `evaluation/raceintel_independent_v2_results.json` | `1fefa90a4fd8b3d7d25d4fb87133e94cecd30920417630c99333e05bdbef24ca` |
| `tests/test_phase_5d_evaluator.py` | `135011981485aaa4ec840426517d49280f001150e5182f7977756835ae6a27b9` |
| `data/raceintel.db` (`PRAGMA quick_check: ok`) | `61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e` |
| `evaluation/raceintel_independent_benchmark_v1.json` (locked) | `0407af561d13e9dde7d6dd8fe550cf2b3cba4e09bdcbd656c3925f0a584112a1` |
| `evaluation/raceintel_independent_benchmark_v1_results.json` (locked) | `41cf5226c65925595e6b0c7acdbeb0c3f98f00ca70e9941cfc86c85ae03b5190` |
| `evaluation/run_independent_benchmark.py` (locked) | `7e9ff45b00b28d11f5dd2e6e6e976ba7109c13c6259ee1c6c06c5de16a4b57ad` |

ChromaDB `raceintel_knowledge` verified untouched: **503 documents** (`race_report`: 24, `driver_report`: 479).

---

## 4. Independent Benchmark V2 Results (Frozen Offline Run)

Executed strictly offline (`total_duration_seconds: 47.33`, `external_api_calls_attempted: 0`):

| Metric | Result | Rate |
|---|---:|---:|
| **Overall answer accuracy** | **62/80** | **77.5%** |
| SQL routing accuracy | 45/58 | 77.6% |
| SQL end-to-end accuracy | 46/58 | 79.3% |
| Intent classification accuracy (strict enum label match) | 30/80 | 37.5% |
| Entity resolution accuracy | 24/24 | 100.0% |
| Event / season resolution accuracy | 71/71 | 100.0% |
| Ambiguity handling accuracy | 4/5 | 80.0% |
| DomainGuard block accuracy | 3/4 | 75.0% |
| Domain rejection end-to-end accuracy | 3/4 | 75.0% |
| RAG retrieval source hit rate | 9/9 | 100.0% |
| RAG answerable complete accuracy | 8/9 | 88.9% |
| Correct abstention (all unanswerable) | 4/8 | 50.0% |
| Correct abstention (in-domain unanswerable) | 1/4 | 25.0% |
| False abstention rate | 0/67 | 0.0% |

### Category Breakdown

| Category | Passed / Total | Rate |
|---|---:|---:|
| `race_results_and_winners` | 5/9 | 55.6% |
| `driver_standings_and_points` | 8/9 | 88.9% |
| `constructor_standings_and_points` | 5/8 | 62.5% |
| `weather_and_conditions` | 8/8 | 100.0% |
| `pace_and_fastest_laps` | 6/8 | 75.0% |
| `tyres_positions_and_classification` | 7/8 | 87.5% |
| `multi_entity_comparisons` | 7/8 | 87.5% |
| `rag_race_reports_and_metadata` | 8/9 | 88.9% |
| `ambiguous_or_underspecified` | 4/5 | 80.0% |
| `unanswerable_in_domain` | 1/4 | 25.0% |
| `domain_rejection` | 3/4 | 75.0% |

---

## 5. Honest Failure Analysis of All 18 Failed Cases

All 18 non-passing cases split cleanly into **13 genuine system gaps** and **5 frozen evaluator/contract artifacts**:

### 5.1 Genuine System Gaps (13 cases)

1. **Unseen Winner & Scorer Phrasings Missed SQL Intent -> Fell Back to RAG (`indv2_001`–`indv2_004`, `indv2_018`, `indv2_019`, `indv2_021`, `indv2_024`, `indv2_036`, `indv2_041` — 10 cases)**:
   - Unseen winner phrasing (`"took top honours"`, `"crossed the finish line first"`, `"captured first place"`, `"prevailed"`) was not matched by `IntentClassifier`, causing queries to route to RAG rather than SQL.
   - Similar intent misses occurred on `"earned championship points"` (`indv2_018`), `"teams' championship"` (`indv2_019`), `"constructors' championship table"` (`indv2_021`), `"collected the most race points"` (`indv2_024`), `"fastest race lap"` (`indv2_036`), and `"fastest single lap"` (`indv2_041`).
   - Once on RAG, `indv2_004`, `indv2_018`, `indv2_024`, `indv2_041` suffered from un-targeted single `driver_report` extraction in deterministic/mock paths, whereas `indv2_036` retrieved the right `race_report` summary containing `Lando Norris` alongside podium names (tripping the `single_entity` anti-ambiguity check).
2. **Offline Mock Round Question Phrasing Gap (`indv2_067` — 1 case)**:
   - `"What round of the 2024 F1 calendar was the United States Grand Prix in Austin?"` achieved `source_hit=True` (`2024_19` was retrieved!), yet `_generate_mock_response` returned `"I couldn't find that information in the retrieved race data."` because it expected `"which round"` / stricter round cues.
3. **Pronoun Ambiguity Missed When Named Event Present (`indv2_070` — 1 case)**:
   - `"What were his championship points after the Singapore Grand Prix?"` was NOT flagged ambiguous because event resolution succeeded and pronoun gating only rejected unanchored queries or fell through to `general_rag`, where deterministic `all_drivers` retrieval dumped Alexander Albon (`P20`, `0.0` points).
4. **Historical Retired Driver Missed by DomainGuard (`indv2_079` — 1 case)**:
   - `"What position did Alain Prost finish in the 2024 Singapore Grand Prix?"` passed `DomainGuard` (`Alain Prost` absent from its historical blocklist) and reached RAG. Notably, Retriever's entity-mismatch safety guard caught that `'Alain Prost'` was absent from the retrieved 2024 documents and safely returned `"I couldn't find that information in the retrieved race data."` (zero hallucination), though `domain_rejection` expected an upfront DomainGuard block.

### 5.2 Evaluator & Formatting Stringency Artifacts (5 cases — System Behaviour Correct)

5. **Frozen `REFUSAL_PHRASES` Omitted `"couldn't find"` (`indv2_073`, `indv2_074`, `indv2_076` — 3 cases)**:
   - For pole position in qualifying (`indv2_073`), Verstappen's pit stop duration (`indv2_074`), and FIA wet DRS regulations (`indv2_076`), the system returned the exact safe abstention: `"I couldn't find that information in the retrieved race data."`
   - Because `run_independent_v2.py` checked `REFUSAL_PHRASES` (`"not found in"`, etc.) without `"couldn't find"` / `"could not find"`, all 3 genuine abstentions were scored `FAILED`. (Per protocol, `run_independent_v2.py` was **not** patched after observing results.)
6. **Evaluator `split_clauses` Broke `"P1. Charles Leclerc"` on Period-Space (`indv2_050` — 1 case)**:
   - `ChatService` returned the full 20-driver classification accurately (`P1. Charles Leclerc (Ferrari) - 25.0 points\n...`), but `re.split(r"(?<=[.;])\s+", ln)` split `"P1."` from `"Charles Leclerc"` across separate clauses, causing the clause co-occurrence check to fail.
7. **Concise Formatter vs Expected Position Clause (`indv2_058` — 1 case)**:
   - For `"Out of the Mercedes teammates, who finished better in the 2024 Saudi Arabian Grand Prix?"`, SQL returned the exact winning teammate `"George Russell"`, failing the benchmark's stricter expectation that position `P6` also be stated in the text.

*Note on `intent_classification_accuracy` (`30/80`)*: Most mismatches reflect dataset label naming differences vs RaceIntel's concrete `Intent` enum values (e.g., dataset `weather_summary` vs enum `weather`, `driver_race_result` vs `driver_position`/`driver_performance`, `race_report` vs `general_rag`, `tyre_strategy` vs `tyre_usage`, `retirements` vs `race_retirements`), alongside the ~12 genuine intent routing misses above.

---

## 6. Offline Mock vs Live Gemini Evaluation Scope

- **Zero live Gemini API calls (`0`)** were executed anywhere in Phase 5.
- Deterministic SQL answers (weather, standings, comparisons, race results, tyres, retirements, fastest laps) exercise the **exact production formatting code** used in live mode.
- RAG answers (`rag_race_reports_and_metadata`, `unanswerable_in_domain`) measure real ChromaDB retrieval (`rag_retrieval_source_hit_rate: 9/9`) paired with `GeminiClient._generate_mock_response` extraction/abstention rules — **not** live Gemini synthesis fluency or prompt adherence (`_call_external`).

---

## 7. Full Regression Suite Verification (Post-Phase 5)

| Suite | Result | External Gemini Calls | Notes |
|---|---|---:|---|
| Full `pytest` suite | **302 passed, 0 failed, 0 skipped** (`22` library deprecation warnings, `28.86s`) | 0 | Includes Phase 1–4 tests + Phases 5A, 5B, 5C, and 5D evaluator tests |
| Baseline benchmark (30) | **30/30 (100.0%)** | 0 | Executed offline via `run_evaluation.py --baseline --offline` |
| Evaluation V2 (75) | **75/75 (100.0%)** | 0 | Executed offline via `run_evaluation.py --v2 --offline` |
| Holdout V1 (30) | **30/30 (100.0%)** | 0 | Executed offline via `run_evaluation.py --holdout --offline` |
| Locked Ind-v1 reference (80) | **74/80 (92.5%)** | 0 | Up from Phase 4E baseline `61/80 (76.2%)`; zero edits to v1 dataset or v1 runner |
| Frozen Ind-v2 (80) | **62/80 (77.5%)** | 0 | Pre-registered SHA256s verified unchanged pre/post run |
