# RaceIntel — Phase 5 Final Engineering Report (Phases 5A–5D)

## 1. Executive Summary

Phase 5 systematically addressed the structural generalisation, event-resolution, routing-boundary, and RAG reliability failures exposed by the Phase 4E audit — **without** tuning against Phase 4E's v1 dataset, weakening DomainGuard/abstention checks, altering `data/raceintel.db` or `raceintel_knowledge`, or making external Gemini API calls.

Key verified outcomes after completing Phases 5A–5D:

- **Event Resolution Collision Eliminated**: United States Grand Prix (Austin) vs Miami Grand Prix (and Las Vegas Grand Prix / Italian Grand Prix disambiguation) now resolve with **100.0% accuracy** across both locked Ind-v1 (`71/71`, up from `67/71`) and newly authored frozen Ind-v2 (`71/71`).
- **Two-Driver Single-Race Comparison Added**: Implemented deterministic SQL `DRIVER_RACE_COMPARISON` execution and formatting (`race_service.py`, `intent_classifier.py`, `query_planner.py`, `chat_service.py`).
- **Safe RAG Filter Extraction & Mock Completeness**: Eliminated substring cross-contamination (`Spa-Francorchamps` -> Franco Colapinto), extended explanatory gating to team/all-driver retrieval shortcuts, removed blind alphabetical multi-driver fallback, and added complete `Round:` / `Race Summary:` / unbacked-topic abstention handling in offline mock mode.
- **Full Regression Safety Preserved**: Full `pytest` suite expanded from **233** to **302 passing tests** (`0` failures, `0` skipped), while Baseline (`30/30`), Evaluation V2 (`75/75`), and Holdout (`30/30`) remained at **100.0%**.
- **Locked Ind-v1 Progression**: Without modifying v1 files or optimizing for v1, performance on the locked 80-question Ind-v1 benchmark improved from **61/80 (76.2%)** to **74/80 (92.5%)** (Answerable RAG `4/7` -> `7/7`, SQL routing `47/60` -> `55/60`, Event/season `67/71` -> `71/71`).
- **Strict Frozen Ind-v2 Benchmark (Zero Leakage)**: Evaluated once offline on 80 brand-new questions (`62/80`, **77.5%**), honestly surfacing remaining unseen intent-phrasing sensitivity, named-event pronoun ambiguity (`indv2_070`), DomainGuard historical-driver coverage (`indv2_079`), plus 5 strict evaluator formatting/contraction artifacts.

---

## 2. Phase-by-Phase Engineering Summary

### Phase 5A — Deterministic Event Resolution ([`PHASE_5A_IMPLEMENTATION_REPORT.md`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/PHASE_5A_IMPLEMENTATION_REPORT.md))
- Created canonical event alias registry [`event_aliases.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/services/event_aliases.py) separating exact GP names (`United States Grand Prix`, `Miami Grand Prix`, `Las Vegas Grand Prix`, `Italian Grand Prix`, `Emilia Romagna Grand Prix`) and circuits (`Austin`/`COTA`, `Miami`, `Monza`, `Imola`) from ambiguous bare country names (`USA`, `United States`, `Italy`).
- Updated [`entity_registry.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/routing/entity_registry.py) and [`session_service.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/services/session_service.py) with priority multi-stage `resolve_race_session` matching (explicit event/circuit -> unique alias -> ambiguous country check -> null), preventing iteration-order `Miami` shadowing of explicit `United States Grand Prix` queries.
- Verified with [`tests/test_phase_5a.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/tests/test_phase_5a.py).

### Phase 5B — Intent Generalisation, Head-to-Head Race Comparisons & Capability Boundaries ([`PHASE_5B_IMPLEMENTATION_REPORT.md`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/PHASE_5B_IMPLEMENTATION_REPORT.md))
- Added `Intent.DRIVER_RACE_COMPARISON` to [`intent_classifier.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/routing/intent_classifier.py), `QueryPlanner` dispatch in [`query_planner.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/routing/query_planner.py), and `compare_drivers_in_race` / `format_driver_race_comparison_answer` in [`race_service.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/services/race_service.py) (handling `"P1"`-prefixed finish positions and tie/DNF rank keys safely).
- Generalised [`weather_service.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/services/weather_service.py) formatting for surface/asphalt/air temperatures, humidity, wind, and pressure.
- Hardened `IntentClassifier` with uppercase guards on 3-letter timing codes colliding with English words (`nor`, `per`, `law`, `gas`, `bot`, `str`), conceptual query gating (`"Explain..."`, `"What does DNF mean"`), cumulative standings vs single-race constructor points precedence, and tightened `TEAM_PERFORMANCE` matching.
- Prevented executable structured plans returning `None` in [`chat_service.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/chat/chat_service.py) from leaking silently into RAG.
- Verified with [`tests/test_phase_5b.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/tests/test_phase_5b.py).

### Phase 5C — RAG Filter Safety, Answer Completeness & Mock/Live Separation ([`PHASE_5C_IMPLEMENTATION_REPORT.md`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/PHASE_5C_IMPLEMENTATION_REPORT.md))
- Hardened `Retriever._extract_filters()` in [`retriever.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/retrieval/retriever.py) to mask matched event tokens prior to scanning drivers/teams (fixing `Spa-Francorchamps` -> `Franco Colapinto`) and enforce `\b...\b` boundaries + uppercase timing-code guards.
- Gated deterministic team and all-driver retrieval paths in `retrieve_context()` with `not self._is_explanatory_query(question)`.
- Upgraded offline `GeminiClient._generate_mock_response()` in [`gemini.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/chat/gemini.py) with structured `_extract_driver_blocks` / `_extract_race_fields`, removal of wrong alphabetical first-driver fallback across multi-driver contexts, `Round:` + full `Race Summary:` extraction (up to 12 lines), and explicit abstention checks for unbacked topics (qualifying, pole, pit stop durations, sprint, sector time, speed trap) while leaving `_call_external` untouched.
- Verified with [`tests/test_phase_5c.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/tests/test_phase_5c.py).

### Phase 5D — Independent Revalidation & Pre-Registered Benchmark V2 ([`PHASE_5D_INDEPENDENT_REVALIDATION_REPORT.md`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/PHASE_5D_INDEPENDENT_REVALIDATION_REPORT.md))
- Audited Phase 4E runner [`run_independent_benchmark.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/run_independent_benchmark.py).
- Authored 80 novel ground-truth-verified cases in [`raceintel_independent_v2.json`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_independent_v2.json) paired with strict evaluator [`run_independent_v2.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/run_independent_v2.py) and unit tests [`test_phase_5d_evaluator.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/tests/test_phase_5d_evaluator.py).
- Locked SHA256 hashes in [`phase_5d_frozen_manifest.json`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/phase_5d_frozen_manifest.json) **before** executing `run_independent_v2.py` once offline -> [`raceintel_independent_v2_results.json`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_independent_v2_results.json).

---

## 3. Consolidated Evaluation & Regression Comparison

| Suite | Phase 4D/4E Baseline | Post-Phase 5 Verified | Delta | External Gemini Calls |
|---|---:|---:|---:|---:|
| Full `pytest` suite | 233/233 | **302/302** (`28.86s`, 22 warnings) | +69 tests | 0 |
| Baseline benchmark | 30/30 (100.0%) | **30/30 (100.0%)** | — | 0 |
| Evaluation V2 | 75/75 (100.0%) | **75/75 (100.0%)** | — | 0 |
| Holdout V1 | 30/30 (100.0%) | **30/30 (100.0%)** | — | 0 |
| Locked Ind-v1 (reference) | 61/80 (76.2%) | **74/80 (92.5%)** | +13 (+16.3 pp) | 0 |
| Frozen Ind-v2 (unseen, strict) | N/A | **62/80 (77.5%)** | Pre-registered | 0 |

### Detailed Locked Ind-v1 Sub-Metric Shift (Reference)

| Sub-Metric | Phase 4E | Post-Phase 5 |
|---|---:|---:|
| SQL routing accuracy | 47/60 (78.3%) | **55/60 (91.7%)** |
| Intent classification accuracy | 67/80 (83.8%) | **75/80 (93.8%)** |
| Entity resolution | 25/25 (100.0%) | **25/25 (100.0%)** |
| Event / season resolution | 67/71 (94.4%) | **71/71 (100.0%)** |
| Ambiguity handling | 5/5 (100.0%) | **5/5 (100.0%)** |
| Answerable RAG | 4/7 (57.1%) | **7/7 (100.0%)** |
| False abstention rate | 10/67 (14.9%) | **5/67 (7.5%)** |
| Unsupported-answer rate | 9/57 (15.8%) | **1/63 (1.6%)** |

---

## 4. Remaining Limitations & Next Engineering Priorities

The frozen Ind-v2 run (`62/80`) objectively highlights the remaining generalisation boundaries:

1. **Rule-based `IntentClassifier` lexical brittleness (10 cases)**: Novel natural-language synonyms (e.g., `"took top honours"`, `"crossed the finish line first"`, `"teams' championship"`, `"fastest single lap"`) still miss SQL routing rules and fall back to RAG. Future work: replace brittle keyword lists with lightweight semantic intent classification or broader lemma/pattern coverage while keeping deterministic SQL execution.
2. **Named-event pronoun ambiguity (`indv2_070`)**: Pronouns like `"his"` inside a race-qualified query (`"What were his championship points after the Singapore Grand Prix?"`) still escape ambiguity clarification when no driver is resolved.
3. **Mock `"What round..."` extraction (`indv2_067`)**: Offline mock round extraction missed `"What round of the 2024 F1 calendar was ...?"` even though Chroma retrieval returned the exact race report (`2024_19`).
4. **DomainGuard historical driver coverage (`indv2_079`)**: Historical retired drivers not in DomainGuard's curated list (`Alain Prost`) reach RAG (where entity-mismatch prevents hallucination) instead of fast DomainGuard rejection.
5. **Live Gemini validation deferred**: Offline evaluation verifies deterministic SQL, routing, DomainGuard, Chroma retrieval, and offline mock extraction/abstention (`0` API calls), not live Gemini natural-language generation quality.

---

## 5. Integrity & Immutability Verification

- **Git state**: Branch `main`, base commit `2acb2ab47a3abb1b4a5f9c5693a932f23a8023b4`.
- **Database integrity**: `data/raceintel.db` SHA256 unchanged (`61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e`), `PRAGMA quick_check` -> `ok`.
- **Vector store integrity**: ChromaDB collection `raceintel_knowledge` untouched at `503` documents.
- **Locked Phase 4E artifacts**: All three v1 files (`raceintel_independent_benchmark_v1.json`, `raceintel_independent_benchmark_v1_results.json`, `run_independent_benchmark.py`) verified byte-identical to pre-Phase-5 SHA256s.
- **Frozen Phase 5D artifacts**: `raceintel_independent_v2.json` (`61246124...`), `run_independent_v2.py` (`9ede6048...`), and all `82` `src/**/*.py` files verified matching `evaluation/phase_5d_frozen_manifest.json` after execution.
