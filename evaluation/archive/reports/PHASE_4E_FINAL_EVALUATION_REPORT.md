# RaceIntel — Phase 4E Independent Benchmark & Final Evaluation Report

## 1. Executive Summary

Phase 4E evaluated whether the frozen Phase 4D RaceIntel system genuinely generalises beyond the regression benchmarks (`Baseline`, `V2`, `Holdout V1`) that guided prior engineering phases. An independent 80-question validation benchmark (`evaluation/raceintel_independent_benchmark_v1.json`) was constructed directly from SQLite and ChromaDB ground truth using unseen phrasings, circuit aliases, and adversarial probes, and executed end-to-end in strict offline mode (`0` live Gemini API calls).

- **Independent Benchmark Overall Accuracy**: **`61 / 80` (`76.2%`)** (`61 Passed`, `19 Failed`, `0 Unscorable`, `0 Skipped`)
- **Regression Suite Stability (Post-Benchmark)**: Baseline **`30/30` (`100.0%`)**, V2 **`75/75` (`100.0%`)**, Holdout **`30/30` (`100.0%`)**, Pytest **`233/233`** (`107/107` in `tests/test_phase_4a.py`–`4d.py`)
- **Final Verdict**: **CONDITIONAL PASS** — Guardrails (`DomainGuard` `4/4`, Ambiguity `5/5`, Unanswerable Abstention `8/8`, EntityRegistry `25/25`) and Retrieval Precision (`7/7`, `0.0%` failure) generalise strongly, but unseen-phrasing SQL routing (`47/60`, `78.3%`), a **Critical** wrong-event SQL collision (`United States Grand Prix` -> `Miami Grand Prix` across `4` cases), and unsafe single-driver RAG fallbacks (`5` cases) prevent full production sign-off without a targeted Phase 5 remediation pass.

---

## 2. Frozen Implementation Manifest

Recorded prior to independent benchmark generation/execution and verified byte-for-byte after completion:

- **Git HEAD Commit**: `2acb2ab47a3abb1b4a5f9c5693a932f23a8023b4` (`Add atomic ETL transaction rollback safety`)
- **Working Tree State**: Existing uncommitted Phase 1–4D changes preserved untouched throughout Phase 4E; only the 6 required Phase 4E evaluation deliverables were created.
- **SQLite (`data/raceintel.db`) SHA256**: `61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e`
- **ChromaDB Collection**: `raceintel_knowledge`, `503` documents (`24` `race_report`, `479` `driver_report`), embedding model `all-MiniLM-L6-v2`
- **ChromaDB Content SHA256** (`(id, document, metadata)`): `a6af7d37f4ecf25bbff71215c184ad2dc00637d692a139188e4b506144a35a5a`

| Frozen File | SHA256 |
|---|---|
| `src/raceintel/chat/chat_service.py` | `0fe09a58a8179ae71f583c26c4918fb88fbbd2f8e111f77b1d35e34b222078fd` |
| `src/raceintel/chat/gemini.py` | `bc597c8f00ef90b6d8d970a6039b1a2f1790188b6b922b1a45ab630b2878c2a1` |
| `src/raceintel/chat/prompts.py` | `160bd755da51263495882bf6620ab308b8c7b3f8c6a7c5ea485cbd855fdf77a6` |
| `src/raceintel/routing/entity_registry.py` | `4b9d62d90b950b50ebba5d3a414a853c4c529d0d0a8fc738277cb0b4f1f76a8c` |
| `src/raceintel/routing/domain_guard.py` | `d704b8f0b9efdb380396735f585d5247ed6239b0ec87794b41d061d1a2b30b17` |
| `src/raceintel/routing/intent_classifier.py` | `33003f427be3a1b9d365762c830816e9c82f7f34c9adee5c8b05cecaf2290c2a` |
| `src/raceintel/routing/query_planner.py` | `e63ddc79c918151225e583d554396b68d28dbb55e2cc708ad8817cf5269f5f94` |
| `src/raceintel/retrieval/retriever.py` | `2b42ae2ba06bd23455672f541aec34330d95d3ea925a980a0803e13e8303caf0` |
| `src/raceintel/retrieval/chroma_client.py` | `0ebf80944b80fa8c6874303edff0d592ae3d4d7032d1dba4f46811eb511c58a8` |
| `src/raceintel/services/race_service.py` | `15d99574745dd5645cb014c70e8e7fcd0e86f3bea96bf6e6a3bb4806560736d0` |
| `src/raceintel/services/standings_service.py` | `7f882eacab090c3f98eb0482769edb1d3a5d9822bca5ece0a0b5a9d1048c6bc6` |
| `src/raceintel/services/weather_service.py` | `f2d8a8271d145a0b3ec7910e62810fe33a423dcc3ba92cac5975ca43b06efb22` |
| `src/raceintel/services/pace_service.py` | `2a83718f97c0c0d1bcd0cac3f519917c22b6f053c64012887eb6622ebdbb90d6` |
| `src/raceintel/services/session_service.py` | `b2f5a73938101440f7b9cb7556580877be4ce1de564cdb5c00b55d321aeab2d1` |
| `src/raceintel/api/routers/chat.py` | `be8dd39b784d54ceaec910cf038ea783fa4bb27594b555f17fb8c8cce171aea4` |

---

## 3. Dataset Construction, Provenance & Safeguards

See `evaluation/PHASE_4E_DATASET_PROVENANCE.md` for full details.

- **Locked Dataset**: `evaluation/raceintel_independent_benchmark_v1.json` (SHA256 `0407af561d13e9dde7d6dd8fe550cf2b3cba4e09bdcbd656c3925f0a584112a1`, `80` unique cases).
- **Corpus Adaptation**: ChromaDB holds only `24` `race_report` and `479` `driver_report` documents (no F1 regulations/strategy/aero/pit-time corpus). Thus 10 general/doc cases became `7` `rag_document_grounded` questions plus `3` missing-corpus abstention probes inside `unsupported_or_unanswerable` (`8` total).
- **Independence Verification**: `0` exact matches vs `155` historical questions/probes, `0` internal pairs with Jaccard `>= 0.70`, max Jaccard vs historical benchmarks `0.636`, zero post-execution benchmark edits, and zero system modifications.

---

## 4. Independent Evaluation Methodology & Anti-False-Positive Rules

`evaluation/run_independent_benchmark.py` executed every question end-to-end through `ChatService(offline=True)` (`GeminiClient.set_global_offline(True)`), recording intermediate read-only telemetry (`DomainGuard`, `IntentClassifier`, `QueryPlanner`, legacy fallback, `Retriever._extract_filters`, `Retriever.retrieve_context`) and scoring answers strictly:

- **Pairwise & Clause Binding**: Points/standings/comparisons require entity, rank, and exact numerical value in the same clause/line (`1. Max Verstappen: 102.0 points`, `P1. Max Verstappen ...`).
- **Event & Season Consistency**: Any response naming a different Grand Prix or wrong season fails (catching the Austin/US GP -> Miami GP bug).
- **Clarification Verification**: Ambiguous queries must ask a clarification question explicitly naming the missing slot (`grand prix`, `driver`, `Emilia Romagna`/`Italian`).
- **Offline Mock Limitation Handling**: All `80` cases ran offline (`0` live Gemini calls). Responses that failed purely due to `GeminiClient._generate_mock_response` lacking templates for un-templated paraphrases (`IND-063`, `066`, `067`) are counted as **`FAILED`** in end-to-end offline accuracy and broken out separately under offline-supported component metrics (`7/7` retrieval hit rate).

---

## 5. Independent Benchmark Results

### 5.1 Aggregate & Sub-Component Metrics

| Metric | Result | Rate |
|---|---:|---:|
| **Overall answer accuracy (`Passed / Total`)** | **`61 / 80`** | **`76.2%`** |
| Passed / Failed / Unscorable / Skipped | `61 / 19 / 0 / 0` | — |
| Manually audited cases | `19` failures + `15` RAG cases | — |
| SQL routing accuracy | `47 / 60` | `78.3%` |
| Intent classification accuracy | `67 / 80` | `83.8%` |
| Entity resolution accuracy | `25 / 25` | `100.0%` |
| Event / season resolution accuracy | `67 / 71` | `94.4%` |
| Ambiguity handling accuracy | `5 / 5` | `100.0%` |
| Domain rejection accuracy (`DomainGuard` & end-to-end) | `4 / 4` (`4 / 4` DG) | `100.0%` |
| RAG evidence-grounding rate (on answered offline RAG) | `4 / 4` | `100.0%` |
| RAG evidence-grounding rate (overall answerable RAG) | `4 / 7` | `57.1%` |
| RAG retrieval failure rate (answerable RAG `status != ok`) | `0 / 7` | `0.0%` |
| Correct abstention rate (all unanswerable) | `8 / 8` | `100.0%` |
| Correct abstention rate (RAG unanswerable probes) | `4 / 4` | `100.0%` |
| False abstention rate (answerable cases refused) | `10 / 67` | `14.9%` |
| Unsupported-answer rate (wrong/unverified factual claims) | `9 / 57` | `15.8%` |
| External Gemini API calls attempted | `0` | — |

### 5.2 Category-Level Breakdown

| Category | Passed / Total | Accuracy | Primary Failure Mode |
|---|---:|---:|---|
| `race_results_and_winners` | `6 / 10` | `60.0%` | `2` intent misses (`IND-001`, `002`), `1` wrong RAG fallback (`006`), `1` US->Miami bug (`007`) |
| `driver_standings_and_points` | `7 / 10` | `70.0%` | `2` intent misses (`IND-011`, `014`), `1` wrong RAG fragment (`020`) |
| `constructor_standings_and_points` | `7 / 8` | `87.5%` | `1` US->Miami bug (`IND-024`) |
| `weather_and_conditions` | `7 / 8` | `87.5%` | `1` intent miss (`IND-034` `"asphalt track surface"`) |
| `pace_and_fastest_laps` | `5 / 8` | `62.5%` | `2` intent misses (`IND-039`, `043` + filter bug), `1` US->Miami bug (`041`) |
| `tyres_position_and_classification` | `6 / 8` | `75.0%` | `1` US->Miami bug (`IND-048`), `1` wrong RAG fallback (`051`) |
| `multi_entity_comparisons` | `6 / 8` | `75.0%` | `2` `team_comparison` intent misses returning two-driver dump (`IND-059`, `060`) |
| `rag_document_grounded` | `4 / 7` | `57.1%` | Retrieval `7/7` (`100%`), `3` offline mock synthesis gaps (`IND-063`, `066`, `067`) |
| `ambiguous_or_underspecified` | `5 / 5` | `100.0%` | — |
| `unsupported_or_unanswerable` | `8 / 8` | `100.0%` | — |

---

## 6. Historical Regression vs Independent Validation Gap

| Benchmark | Result | Interpretation |
|---|---:|---|
| Baseline (`raceintel_eval_2024.json`) | `30 / 30` (`100.0%`) | Regression target met |
| Evaluation V2 (`raceintel_eval_v2.json`) | `75 / 75` (`100.0%`) | Regression target met |
| Holdout V1 (`raceintel_holdout_v1.json`) | `30 / 30` (`100.0%`) | Regression target met |
| **Independent Benchmark v1 (Phase 4E)** | **`61 / 80` (`76.2%`)** | **True unseen generalisation (`-23.8 pp` gap)** |

The `-23.8` percentage-point gap confirms that while Phases 1–4D eliminated regressions on known phrasings and built strong guardrails, rule-based intent regexes and session lookup logic remained vulnerable to unseen question wording and multi-race host countries (`United States`).

---

## 7. Key Defects Identified (Documented Without Modifying Code)

Full 19-case failure table in `evaluation/PHASE_4E_FAILURE_ANALYSIS.md`. Top defects for future Phase 5 remediation:

1. **[CRITICAL] Single-Pass Country-Over-Event Session Collision (`src/raceintel/services/session_service.py`)**: `resolve_race_session()` iterates sessions by `session_id ASC` checking `clean_target == ev_clean ... or clean_target == country` in one loop. `Miami Grand Prix` (`session_id=7`, `country='United States'`) precedes `United States Grand Prix` (`session_id=20`), so every SQL query for Austin / United States GP (`IND-007`, `024`, `041`, `048`) silently returns **Miami Grand Prix** data. Fix: rank exact event/circuit matches strictly ahead of country fallback matches.
2. **[HIGH] Unsafe Offline RAG Fallback on Misrouted SQL Queries (`IND-006`, `020`, `051`)**: When `IntentClassifier` misses `"top three finishers"`, `"walked away with championship points"`, or `"failed to finish"`, RAG retrieves all 20 `driver_report` docs and `GeminiClient._generate_mock_response` emits a single arbitrary driver line (`Alexander Albon...` or `scored 6.0 points, finishing P7.`). Live LLM synthesis or an explicit multi-driver / non-matching-question guard is needed.
3. **[MEDIUM] Brittle Regex Coverage in `IntentClassifier` (`12/60` SQL misses)**: Phrasings like `"Which Formula 1 driver came first"`, `"victor"`, `"topped the drivers' championship"`, `"asphalt track surface"`, `"quickest single/race lap"`, `"failed to finish"`, `"stronger classification"`, and `"placed ahead of their teammate"` fall through to RAG.
4. **[MEDIUM] Substring Driver Collision in `Retriever._extract_filters()` (`IND-043`)**: `"Spa-Francorchamps"` contains `"franc"`, falsely matching driver `"Franco Colapinto"` and causing `empty` Chroma retrieval (`EntityRegistry` was unaffected). Fix: enforce word boundaries in `_extract_filters()`.

---

## 8. Post-Benchmark Regression & Integrity Verification

Executed after independent benchmark completion:

- **Pytest Full Suite**: `233 passed, 22 warnings in 16.55s` (`tests/test_phase_4a.py`–`4d.py`: `107 passed in 4.98s`)
- **Regression Benchmarks (Offline, `0` external API calls)**: Baseline `30/30`, V2 `75/75`, Holdout `30/30`
- **All 15 Frozen `src/` File Hashes**: Verified identical to pre-benchmark manifest (`git status` shows zero post-freeze edits to `src/` or regression datasets)
- **SQLite (`data/raceintel.db`)**: SHA256 unchanged (`61b1a5b...3fbb6e`); `PRAGMA quick_check` = `ok`
- **ChromaDB (`raceintel_knowledge`)**: Collection count `503` (`24` `race_report`, `479` `driver_report`); content-level SHA256 over all `(id, document, metadata)` records verified identical (`a6af7d37f4ecf25bbff71215c184ad2dc00637d692a139188e4b506144a35a5a`). *(Note: `data/chroma/chroma.sqlite3` file-container hash changed from `2a87b264...` to `8c9885cb...` due to ChromaDB `PersistentClient` updating SQLite header timestamps on connection; stored document/metadata content is cryptographically unchanged.)*
- **Benchmark Dataset Integrity**: `evaluation/raceintel_independent_benchmark_v1.json` SHA256 verified identical before and after evaluation (`0407af561d13e9dde7d6dd8fe550cf2b3cba4e09bdcbd656c3925f0a584112a1`).

---

## 9. Final Engineering Recommendation

**Verdict: CONDITIONAL PASS** — Freeze Phase 4E here and schedule **Phase 5 Remediation** focused on: (1) two-tier exact-event-first precedence in `resolve_race_session()` (highest priority), (2) word-boundary enforcement in `Retriever._extract_filters()`, (3) broadened compositional intent matching (or constrained LLM fallback classifier) in `IntentClassifier`, and (4) a gated live-Gemini RAG synthesis check (`7` RAG cases + `2` context-bearing unanswerable probes `IND-074`/`075`) under explicit API authorization.
