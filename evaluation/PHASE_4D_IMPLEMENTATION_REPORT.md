# RaceIntel — Phase 4D Implementation Report: RAG Calibration & Fallback Hardening

## Verdict: PASS

Phase 4D has been implemented, tested, calibrated, and verified offline against the full pytest suite, benchmark evaluation suites, and dedicated RAG calibration stress probes with **zero** live external Gemini API calls and **zero** mutations to production SQLite or ChromaDB stores.

---

## 1. Executive Summary

Prior to Phase 4D, RaceIntel had achieved `100%` pass rates on deterministic structured SQL routing across the Baseline (`30/30`), Evaluation V2 (`75/75`), and Holdout V1 (`30/30`) regression benchmarks, while leaving six concrete weaknesses in the RAG retrieval and fallback layer. Phase 4D closed those gaps by:

1. Adding structured retrieval (`RetrievalResult`, `Retriever.retrieve_context()`) with universal semantic distance gating (`0.55` across **all** queries, including entity-filtered ones), lightweight lexical-overlap reranking, chunk/character context budgeting (`5` chunks / `6000` chars), near-duplicate suppression (`Jaccard >= 0.92` respecting metadata boundaries), `[Source: ...]` attribution headers, event/person mismatch detection, conflict detection (`_detect_conflicts()`), and exception containment while preserving `Retriever.retrieve() -> str` compatibility.
2. Extending `DomainGuard` (`src/raceintel/routing/domain_guard.py`) after unrelated-motorsport validation (`3b`) to dynamically reject unrecognized `<Venue> Grand Prix` names (e.g., `Swiss Grand Prix`) against `EntityRegistry`.
3. Hardening `prompts.py` (`INSUFFICIENT_EVIDENCE_RESPONSE`, source boundary rules, conceptual/explanatory rules, and explicit conflict reporting rules).
4. Hardening `GeminiClient` (`src/raceintel/chat/gemini.py`) and `ChatService` (`src/raceintel/chat/chat_service.py`) so empty/low-confidence/mismatch/error retrievals abstain cleanly **before** reaching LLM generation, `_direct_answer` no longer hijacks non-result team queries (such as upgrades or aerodynamic philosophy), conflicting evidence is surfaced explicitly rather than resolved arbitrarily, and empty/malformed/failing LLM outputs fail safely.

---

## 2. Baseline RAG & Fallback Defects Identified (Pre-Phase 4D Audit)

Direct code inspection and read-only production ChromaDB (`all-MiniLM-L6-v2`, 503 docs) + offline `ChatService` probing before Phase 4D edits exposed six specific defects:

| Defect ID | Pre-Phase 4D Failure Behavior | Root Cause | Phase 4D Remediation |
|---|---|---|---|
| `D1` | `"Explain Red Bull's aerodynamic philosophy in 2024"` returned 5 Verstappen finish results (`P1, 25.0 pts`). | `Retriever.retrieve()` skipped distance gating whenever `has_entity` (`team`/`driver`/`race`) was True, and `_direct_answer` unconditionally matched `"red bull"`. | Universal semantic distance gating (`<= 0.55`, observed aero distances `0.617–0.636` rejected as `low_confidence`) + intent-gated `_direct_answer`. |
| `D2` | `"Tell me about the 2024 Swiss Grand Prix"` leaked Azerbaijan/Monaco GP race summaries (`dist = 0.3848`). | `"Swiss Grand Prix"` was absent from `OUT_OF_CALENDAR_F1_VENUES`; Chroma matched `"2024"` + `"Grand Prix"`. | Dynamic unrecognized `<Venue> Grand Prix` detection in both `DomainGuard` (post-motorsport check) and `Retriever._extract_unrecognized_grand_prix()`. |
| `D3` | `"What happened to Ayrton Senna in the 2024 Monaco Grand Prix?"` returned Charles Leclerc's Monaco race summary. | Deterministic `Monaco Grand Prix` `race_report` lookup ignored unmatched historical driver names, and offline mock fell through to `Race Summary:`. | `_extract_unmatched_person_name()` + `_has_entity_in_documents()` sets `status = "entity_mismatch"` and abstains before LLM. |
| `D4` | `"What upgrades did McLaren bring to the Austrian Grand Prix?"` returned Oscar Piastri & Lando Norris race finishes. | `_direct_answer` triggered on bare team substring match without verifying finish/points/result intent. | Restricted `_direct_answer` team branch with `non_result_topics` exclusions and `team_result_intents` requirements + topic-grounded offline mock validation. |
| `D5` | Empty/insufficient RAG context still reached `self.llm.generate(prompt)`. | `ChatService.ask()` only handled narrow hardcoded season/OOC keywords when `context` was empty. | Explicit pre-LLM gate on `error`, `event_mismatch`, `entity_mismatch`, `low_confidence`, `empty`, `ambiguous`, and `conflict` states. |
| `D6` | No Chroma exception containment, no conflict detection, no near-duplicate collapsing, and no guard against empty/`None`/malformed LLM responses. | Bare `.get()`/`.query()` calls, concatenated docs without cross-checks, and unvalidated `llm.generate()` return values. | `try/except` wrappers around Chroma & LLM calls, `_detect_conflicts()`, `_is_near_duplicate()`, and `_sanitize_llm_response()`. |

---

## 3. Architecture & Code Changes Implemented

### 3.1 `src/raceintel/retrieval/retriever.py`
- Added constants `SEMANTIC_DISTANCE_THRESHOLD = 0.55`, `MAX_CONTEXT_CHUNKS = 5`, `MAX_CONTEXT_CHARS = 6000`, `NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.92`, and `RetrievalResult` dataclass (`documents`, `ids`, `metadatas`, `distances`, `status`, `context`, `raw_context`, `sources`, `conflict_detected`, `conflict_details`, `error_message`).
- Made `distance_threshold`, `max_context_chunks`, and `max_context_chars` configurable on `Retriever.__init__()`.
- Wrapped `.get()` and `.query()` calls in `try/except Exception` returning safe empty/error states.
- Applied semantic distance gating unconditionally across all semantic queries, added `_rerank_candidates()` (distance + lexical keyword overlap tie-break), `_enforce_context_budget()` for semantic chunks, and omitted narrow `document_type="race_report"/"driver_report"` filters when `_is_explanatory_query()` is True so conceptual/technical F1 documents can match in RAG stores.
- Preserved deterministic all-driver race queries without truncating below P6–P10 points scorers, while routing explicit explanatory race queries (`_is_explanatory_query`) to semantic retrieval.
- Implemented near-duplicate detection (`_is_near_duplicate` with metadata boundary guard `_metadata_compatible_for_dedup`), factual conflict detection (`_detect_conflicts` on race winners and driver finishes/points), and `[Source: ...]` chunk headers via `_format_attributed_context()`.
- Kept `Retriever.retrieve() -> str` returning exact unprefixed `raw_context` for full backwards compatibility (`tests/test_retriever_deduplication.py`, `KnowledgeService`).

### 3.2 `src/raceintel/routing/domain_guard.py`
- Added section `3b. Dynamic Unrecognized Named Grand Prix Check` after `Unrelated Motorsport Validation` (`3`) so genuine non-F1 motorsports (e.g., `"MotoGP Grand Prix of Qatar"`) preserve `DomainStatus.OUT_OF_DOMAIN_MOTORSPORT`, while ungrounded named Grand Prix events not in `EntityRegistry` cleanly return `DomainStatus.OUT_OF_CALENDAR_EVENT`.

### 3.3 `src/raceintel/chat/prompts.py`
- Exported `INSUFFICIENT_EVIDENCE_RESPONSE = "I couldn't find that information in the retrieved race data."`.
- Updated `SYSTEM_PROMPT` with strict `[Source: ...]` boundary adherence, anti-extrapolation constraints, conceptual/explanatory grounding instructions, `[CONFLICT DETECTED]` handling rules, and explicit refusal directives when context is `[NO RELEVANT CONTEXT RETRIEVED]` or insufficient.

### 3.4 `src/raceintel/chat/gemini.py` & `src/raceintel/chat/chat_service.py`
- **`GeminiClient._call_external()`**: Guards against `response is None`, non-string/whitespace `response.text`, and malformed placeholders (`none`, `null`, `n/a`), returning `INSUFFICIENT_EVIDENCE_RESPONSE` safely while preserving 429 quota handling and `OfflineBlockedError` isolation.
- **`GeminiClient._generate_mock_response()`**: Enforces `[NO RELEVANT CONTEXT RETRIEVED]`, `[CONFLICT DETECTED]`, specific non-summary topic grounding (`upgrades`, `aerodynamic`, `drs`, `undercut`, `regulations`, etc.), explanatory chunk grounding, and intent-gated `Race Summary:` extraction rather than unconditionally emitting a race summary.
- **`ChatService._direct_answer()`**: Word-boundary matching and intent/non-result topic guards prevent team keywords from hijacking upgrade/technical/conceptual queries.
- **`ChatService.ask()`**: Added `_retrieve_with_safety()` (supporting both real `Retriever.retrieve_context()` and monkeypatched/mock `.retrieve()`), short-circuits pre-LLM on `error`, `event_mismatch`, `entity_mismatch`, `low_confidence`, `empty`, `ambiguous`, and `conflict` states, catches non-isolation LLM exceptions gracefully, and applies `_sanitize_llm_response()`.

---

## 4. Verification Results

### 4.1 Automated Test Suites (`venv`, Python 3.14.6)

| Check | Command | Result | External Calls |
|---|---|---|---|
| Phase 4D Adversarial + Phase 4A Adversarial | `.\venv\Scripts\python.exe -m pytest tests/test_phase_4a_adversarial.py tests/test_phase_4d.py -v` | **43 passed** (`11` Phase 4A adversarial + `32` Phase 4D items) in `2.04s` | `0` |
| Full Pytest Suite (`27` test files) | `.\venv\Scripts\python.exe -m pytest -v` | **233 passed, 0 failed, 22 warnings** in `13.39s` | `0` |

### 4.2 Offline Evaluation Benchmarks & Before/After Comparison

All benchmarks ran using `--offline` (blocking network calls via `_BlockedGenAIClient` and verifying `external_api_calls_attempted == 0`):

| Dataset | Before Phase 4D (`v4c`) | After Phase 4D (`v4d`) | Errors | External Gemini Calls | Output Artifact |
|---|---|---|---|---|---|
| Baseline (`30` cases) | `30/30` (`100.0%`) | **`30/30` (`100.0%`)** | `0` | `0` | [raceintel_eval_v4d_baseline_results.json](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_eval_v4d_baseline_results.json) |
| Evaluation V2 (`75` cases) | `75/75` (`100.0%`) | **`75/75` (`100.0%`)** | `0` | `0` | [raceintel_eval_v4d_v2_results.json](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_eval_v4d_v2_results.json) |
| Holdout V1 (`30` cases) | `30/30` (`100.0%`) | **`30/30` (`100.0%`)** | `0` | `0` | [raceintel_eval_v4d_holdout_results.json](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_eval_v4d_holdout_results.json) |

*(Note: Holdout V1 is treated as a regression benchmark rather than an unseen holdout set.)*

### 4.3 Reproducible Offline RAG Calibration & RAGAS Status

- **RAGAS Dry-Run & Limitation**: Running `.\venv\Scripts\python.exe evaluation/run_ragas_evaluation.py --dry-run` verified `30` dataset cases and `5/5` cached pilot cases with `Gemini API calls: NONE`. Full live `ragas.evaluate()` scoring requires live `ChatGoogleGenerativeAI` and `GoogleGenerativeAIEmbeddings` calls, which cannot execute in strict offline mode without making external Gemini requests; therefore live RAGAS scores were **not** re-scored or fabricated offline.
- **Offline Calibration Harness ([run_rag_calibration.py](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/run_rag_calibration.py))**: Evaluated `10` read-only production knowledge-base stress probes + isolated retrieval precision/recall/conflict/failure fixtures cleanly offline:

| Calibration Metric | Measured Score | Notes |
|---|---|---|
| Production Stress Probes (`P4D-01`..`P4D-10`) | **`1.0` (`10/10`)** | All 7 unanswerable/mismatch/unsupported probes abstained cleanly; all 3 answerable probes grounded cleanly. |
| Abstention Accuracy | **`1.0` (`7/7`)** | Pre-Phase 4D, `P4D-01`..`P4D-06` produced hallucinated/wrong answers or leaked LLM calls. |
| Answerable Groundedness | **`1.0`** | Token-level support of answers against retrieved context. |
| Isolated Context Precision | **`1.0`** | Relevant DRS doc retained (`0.22 <= 0.55`); unrelated Bahrain doc filtered (`0.78 > 0.55`). |
| Isolated Context Recall | **`1.0`** | All expected grounded facts retained within chunk/char budget. |
| Conflict Detection Rate | **`1.0`** | Winner and driver finish/points conflicts explicitly reported without guessing. |
| Retrieval Error Containment Rate | **`1.0`** | Simulated Chroma failure returned safe unavailability message without crashing or invoking LLM. |
| External Gemini API Calls | **`0`** | Verified via `GeminiClient.get_external_call_count() == 0`. |

Artifact: [raceintel_rag_calibration_v4d_results.json](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_rag_calibration_v4d_results.json).

---

## 5. Production Database & Vector Store Integrity

Verified read-only after all code changes and evaluation runs completed:
- **SQLite (`data/raceintel.db`) SHA256**: `61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e` (exact match to pre-Phase 4D baseline).
- **ChromaDB (`data/chroma`, `raceintel_knowledge`) Document Count**: `503` (unchanged: `479` `driver_report` + `24` `race_report` docs).

---

## 6. Files Added or Modified in Phase 4D

- Modified: [src/raceintel/retrieval/retriever.py](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/retrieval/retriever.py)
- Modified: [src/raceintel/routing/domain_guard.py](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/routing/domain_guard.py)
- Modified: [src/raceintel/chat/prompts.py](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/chat/prompts.py)
- Modified: [src/raceintel/chat/gemini.py](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/chat/gemini.py)
- Modified: [src/raceintel/chat/chat_service.py](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/chat/chat_service.py)
- Created: [tests/test_phase_4d.py](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/tests/test_phase_4d.py)
- Created: [evaluation/run_rag_calibration.py](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/run_rag_calibration.py)
- Created: [evaluation/raceintel_rag_calibration_v4d_results.json](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_rag_calibration_v4d_results.json)
- Created: [evaluation/raceintel_eval_v4d_baseline_results.json](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_eval_v4d_baseline_results.json)
- Created: [evaluation/raceintel_eval_v4d_v2_results.json](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_eval_v4d_v2_results.json)
- Created: [evaluation/raceintel_eval_v4d_holdout_results.json](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/raceintel_eval_v4d_holdout_results.json)
- Created: [evaluation/PHASE_4D_IMPLEMENTATION_REPORT.md](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/evaluation/PHASE_4D_IMPLEMENTATION_REPORT.md)

---

## 7. Conclusion

Phase 4D objectives are complete and verified (`PASS`). Retrieval distance thresholds, source attribution, deduplication, entity/event mismatch blocking, conflict handling, and pre/post-LLM fallback guards are enforced consistently without degrading structured SQL routing, DomainGuard protections, or ambiguity handling. Phase 4E was intentionally not started.
