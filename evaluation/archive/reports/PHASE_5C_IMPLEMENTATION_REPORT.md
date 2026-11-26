# RaceIntel — Phase 5C Implementation Report: RAG Answer Completeness, Safe Filter Extraction & Mock/Live Separation

## 1. Objective

Phase 5C targeted three concrete RAG pipeline reliability defects observed across the Phase 4E audit without weakening DomainGuard, abstention, or safety gates:

1. **Unsafe substring matching & event/driver cross-contamination in `Retriever._extract_filters()`** (`Spa-Francorchamps` matching `franc` -> `Franco Colapinto`, unbounded partial tokens, and driver/team scanning colliding with matched Grand Prix names).
2. **Explanatory queries hijacked by deterministic single-entity / team / all-driver retrieval shortcuts** in `Retriever.retrieve_context()`.
3. **Offline `GeminiClient._generate_mock_response()` truncation and blind alphabetical multi-driver extraction** (blindly returning the first alphabetical `Driver:` block when multiple drivers appeared in context, truncating multi-fact documents at 4 lines so `Race Summary:` near the bottom of `race_report` chunks was lost, lacking `Round:` extraction, and omitting unbacked-topic abstention checks for topics absent from `race_report`/`driver_report` metadata such as pit stop durations, qualifying/pole position, sprints, sector times, and speed traps).

---

## 2. Changes Implemented

### 2.1 `src/raceintel/retrieval/retriever.py`

- **Word-boundary & priority event filtering + token masking in `_extract_filters()`**:
  - Resolves events using priority ordering and word boundaries (`\b...\b`) instead of naive substring scans.
  - Masks matched event spans before scanning for driver and team keywords so event tokens (such as `"Spa-Francorchamps"`) cannot false-match driver substrings (such as `"franc"` -> Franco Colapinto).
  - Enforces `\b...\b` boundaries across all driver and team matching keys, with an uppercase requirement for short 3-letter timing-code collisions (`{"nor", "per", "law", "gas", "bot", "str"}`).
- **Explanatory query guard on deterministic branches in `retrieve_context()`**:
  - Gated the deterministic `team` and `all-driver` `driver_report` branches with `not self._is_explanatory_query(question)` (matching the existing `race_report` guard), preventing conceptual/explanatory questions from collapsing to raw single-document dumps.

### 2.2 `src/raceintel/chat/gemini.py`

- **Structured block/field helpers (`_extract_driver_blocks`, `_extract_race_fields`)**:
  - Parses `driver_report` and `race_report` blocks cleanly for deterministic offline mock extraction without altering live Gemini generation (`_call_external`).
- **Removed blind multi-driver first-block fallback**:
  - Eliminated the unsafe fallback that returned the first alphabetical `Driver:` block regardless of which driver was asked when multiple drivers existed in retrieved context.
- **Complete `race_report` & explanatory RAG extraction**:
  - Added `Round:` query support alongside `Winner:`, `Podium:`, `Classification:`, `Fastest Lap:`, and full `Race Summary:` recap extraction.
  - Expanded explanatory/knowledge document extraction from 4 lines up to 12 lines per top-scoring chunk so complete summaries and narrative facts are preserved.
- **Unbacked-topic abstention gating in offline mock mode**:
  - Added explicit abstention gating when a query requests unsupported telemetry/session concepts absent from the corpus (`pit stop duration`, `qualifying`, `pole position`, `sprint`, `sector time`, `speed trap`, etc.).
- **Offline vs Live Separation**:
  - All Phase 5C formatting/extraction changes live strictly in `_generate_mock_response` (offline test/eval path). `GeminiClient._call_external` remains untouched, keeping offline evaluation (`0` external calls) cleanly separated from live Gemini answer synthesis.

---

## 3. Verification

### 3.1 New Tests (`tests/test_phase_5c.py`)

8 dedicated unit/integration tests covering:
- Event token masking preventing `Spa-Francorchamps` -> `Franco Colapinto` false driver filter extraction.
- Word-boundary & uppercase timing-code guards in `Retriever._extract_filters()`.
- Explanatory query gating across team and all-driver retrieval paths.
- Multi-driver mock extraction avoiding wrong alphabetical first-driver fallback.
- `Round:` and `Race Summary:` recap completeness beyond the former 4-line cutoff.
- Unbacked-topic abstention (qualifying/pole/pit stop duration/sprint/sector/speed trap) with `GeminiClient.get_external_call_count() == 0`.

### 3.2 Targeted Regression Run (Verified)

Command executed:
```powershell
.\venv\Scripts\python.exe -m pytest tests\test_phase_5c.py tests\test_phase_5b.py tests\test_phase_5a.py tests\test_phase3a_structured.py tests\test_phase_4a.py tests\test_phase_4a_adversarial.py tests\test_phase_4b.py tests\test_phase_4c.py tests\test_phase_4d.py -v
```

Result:
- **`205 passed, 2 warnings in 11.66s`** (`exit code 0`, 0 failed, 0 skipped)
- **`GeminiClient.get_external_call_count() == 0`**

---

## 4. Modified & Verified File Checksums (SHA256)

| File | SHA256 |
|---|---|
| `src/raceintel/retrieval/retriever.py` | `526cb231bc496f633643fdc880a8a73e044122de1539b1091427a107c33f87ec` |
| `src/raceintel/chat/gemini.py` | `004614fe09c7788138e195b25d4fb3ecd8832ee205763e1100cad05fef6deb3b` |
| `tests/test_phase_5c.py` | `db655e29bdedfd125a378efd2e5859c5fd64153c500b824028273ca38e0d0cc1` |

Integrity invariants preserved:
- `data/raceintel.db` SHA256 unchanged (`61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e`).
- ChromaDB `raceintel_knowledge` untouched (503 documents).
- Phase 4E independent v1 dataset, results, and runner untouched.
