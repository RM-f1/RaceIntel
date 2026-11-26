# RaceIntel — Phase 4A Implementation Report: EntityRegistry & Early DomainGuard

**Status**: Completed  
**Type**: Implementation & Validation Report  
**Date**: November 11, 2026  
**Target File**: `evaluation/PHASE_4A_IMPLEMENTATION_REPORT.md`  

---

## 1. Executive Summary

In Phase 4A, RaceIntel implemented a dynamic, database-driven entity resolution layer (`EntityRegistry`) and an early domain boundary validation layer (`DomainGuard`). These components systematically decouple entity recognition from static keyword mappings and prevent out-of-domain motorsport inquiries from entering semantic vector retrieval.

### Key Highlights:
1. **Dynamic Single Source of Truth**: All 24 official Grand Prix events, 24 circuits/venues, 24 drivers (including mid-season reserve drivers Oliver Bearman, Franco Colapinto, Liam Lawson, and Jack Doohan), 10 constructors, and supported seasons are loaded dynamically from SQLite in read-only mode (`mode=ro`).
2. **Early Domain Interception**: Unrelated motorsport questions (MotoGP, NASCAR, WEC, Bathurst 1000, IndyCar, etc.) and unsupported historical seasons (2020, 2018, etc.) are validated and cleanly refused **before ChromaDB vector retrieval**, eliminating vector leakage.
3. **F1 Comparison Preservation**: In-domain Formula 1 inquiries that mention non-F1 motorsports for comparison (e.g. cornering speeds, lap times, or multi-discipline driver careers) are preserved as valid and processed normally.
4. **Zero Regressions & 100% Test Pass Rate**:
   - Isolated Phase 4A Test Suite: **14 / 14 passed (100.0%)** in 0.42s.
   - Full Test Suite: **125 / 125 passed (100.0%)** in 10.92s.
   - Baseline Benchmark (30 cases): **30 / 30 passed (100.0%)**, 0 errors.
   - Evaluation V2 Benchmark (75 cases): **75 / 75 passed (100.0%)**, 0 errors.
   - Holdout V1 Dataset (30 cases): **26 / 30 passed (86.7%)**, 0 errors (with unanswerable cases 125–128 cleanly intercepted by DomainGuard without Chroma vector search).
5. **Database Invariants Preserved**: Verified that production SQLite (`raceintel.db`: 479 race results, 26,604 laps, 3,690 weather observations) and ChromaDB (503 documents) remained completely untouched.

---

## 2. Files Created and Modified

### Created Files:
1. **`src/raceintel/routing/__init__.py`**:
   - Module init exporting `EntityRegistry`, `EventResolution`, `CircuitResolution`, `DriverResolution`, `ConstructorResolution`, `DomainGuard`, `DomainStatus`, `DomainValidationResult`, and `normalize_text`.
2. **`src/raceintel/routing/entity_registry.py`**:
   - Dynamic database-driven registry with normalization, diacritic stripping, circuit resolution, driver nicknames/codes, and ambiguity detection without arbitrary resolution.
3. **`src/raceintel/routing/domain_guard.py`**:
   - Pre-retrieval validation guard covering motorsport taxonomies, out-of-calendar F1 venues, unsupported historical seasons, and comparative analysis filtering.
4. **`tests/test_phase_4a.py`**:
   - 14 comprehensive unit and integration tests covering dynamic DB loading, circuit resolution, driver codes/nicknames, ambiguity handling, pre-retrieval guard interception, and structured query continuity.
5. **`evaluation/raceintel_eval_v4a_baseline_results.json`**:
   - Baseline offline evaluation run results (30/30).
6. **`evaluation/raceintel_eval_v4a_v2_results.json`**:
   - Evaluation V2 offline evaluation run results (75/75).
7. **`evaluation/raceintel_eval_v4a_holdout_results.json`**:
   - Holdout V1 offline evaluation run results (26/30).
8. **`evaluation/PHASE_4A_IMPLEMENTATION_REPORT.md`**:
   - This implementation report.

### Modified Files:
1. **`src/raceintel/retrieval/retriever.py`**:
   - Updated `Retriever.__init__` to accept an optional `EntityRegistry` and merge dynamic database-backed maps with baseline maps.
   - Added regex word-boundary guards (`\b...\b`) for keywords of length $\le 3$ in `_extract_filters` to prevent substring collisions (such as `VER` matching inside `driver` or `RB` matching inside `sergio`).
2. **`src/raceintel/chat/chat_service.py`**:
   - Injected `EntityRegistry` and `DomainGuard` into `ChatService.__init__`.
   - Added **Step 0: Early Domain & Season Validation** at the start of `ChatService.ask()` prior to filter extraction, ambiguity checks, and vector retrieval.

---

## 3. Design and Integration Explanation

### 3.1 EntityRegistry Architecture

```text
+---------------------------------------------------------------------------------+
|                                 SQLite Database                                 |
|   seasons (1)  |  events (24)  |  drivers (24)  |  constructors (10)            |
+---------------------------------------------------------------------------------+
                                        |  (read-only mode: URI ?mode=ro)
                                        v
+---------------------------------------------------------------------------------+
|                        EntityRegistry (entity_registry.py)                      |
|                                                                                 |
|   - normalize_text(): Strips NFKD diacritics, \ufffd, and punctuation           |
|   - Supported Seasons: Dynamic set from 'seasons' table ({2024})                |
|   - Events: Multi-alias inverted index (Country, Circuit, Canonical Event)      |
|   - Circuits: Canonical circuit resolution (Monza -> Italian GP, etc.)          |
|   - Drivers: Full name, surname, given name, 3-letter code, and nicknames       |
|   - Constructors: Canonical constructor names and team aliases                  |
|   - Ambiguity Detection: If an alias matches >1 entity, returns is_ambiguous   |
+---------------------------------------------------------------------------------+
```

- **Read-Only Database Connection**: `sqlite3.connect("file:path?mode=ro", uri=True)` guarantees zero accidental mutation of production SQLite records during execution or testing.
- **Circuit Resolution**: Resolves tracks like *Monza*, *Silverstone*, *Spa-Francorchamps*, *Interlagos*, *Suzuka*, and *Zandvoort* directly to canonical Grand Prix records.
- **Ambiguity Guard**: When a query references a country hosting multiple events (e.g. `Italy` hosting both Imola and Monza, or `United States` hosting Miami, Austin, and Las Vegas), `resolve_event()` sets `is_ambiguous=True` with `candidates=["Emilia Romagna Grand Prix", "Italian Grand Prix"]` rather than silently picking an arbitrary record.

---

### 3.2 Early DomainGuard Architecture

`DomainGuard` executes **before** any database or vector retrieval to prevent irrelevant queries from polluting context:

```text
User Question
      |
      v
[DomainGuard.validate(question)]
      |
      +---> 1. Explicit 4-digit Year Check (1950 - 2099):
      |        Is year in registry.get_supported_seasons()?
      |        NO  --> Return UNSUPPORTED_SEASON refusal
      |        YES --> Proceed
      |
      +---> 2. Out-of-Calendar F1 Venue Check:
      |        Matches German GP, French GP, Sochi, Sepang, Nurburgring?
      |        YES --> Return OUT_OF_CALENDAR_EVENT refusal
      |        NO  --> Proceed
      |
      +---> 3. Unrelated Motorsport Taxonomy:
      |        Matches MotoGP, NASCAR, WEC, Le Mans, Bathurst 1000, IndyCar, etc.?
      |        YES --> Is it a valid F1 Comparison?
      |                NO  --> Return OUT_OF_DOMAIN_MOTORSPORT refusal
      |                YES --> Return VALID
      |        NO  --> Proceed
      |
      v
[Return VALID] --> Proceed to Structured Services & Retrieval
```

- **Comparison Preservation**: Questions like *"How do 2024 Formula 1 cornering speeds at Silverstone compare to NASCAR?"* contain comparative markers (`compare to`) and verified F1 entities (`Silverstone`, `Formula 1`). `_is_f1_comparison` verifies these indicators and confirms that the primary clause is not asking for non-F1 results, allowing the inquiry to proceed.

---

## 4. Test Results and Verification

### 4.1 Phase 4A Isolated Test Suite (`tests/test_phase_4a.py`)

All 14 isolated test cases passed in **0.42s**:

| Test ID | Test Name | Target Capability | Result |
| :---: | :--- | :--- | :---: |
| 1 | `test_dynamic_event_loading_from_sqlite` | Dynamic event loading from temp SQLite DB | **PASS** |
| 2 | `test_dynamic_circuit_loading` | Dynamic circuit resolution (Monza, Silverstone) | **PASS** |
| 3 | `test_dynamic_driver_and_constructor_loading` | Dynamic drivers and constructors from temp DB | **PASS** |
| 4 | `test_driver_aliases_and_normalization` | Diacritics, nicknames, reserve drivers, codes | **PASS** |
| 5 | `test_valid_f1_questions_using_circuit_names` | Valid F1 questions referencing circuit names | **PASS** |
| 6 | `test_unsupported_season_handling` | Rejection of historical seasons (2020, 2018) | **PASS** |
| 7 | `test_explicit_motogp_rejection` | Interception of MotoGP questions prior to retrieval | **PASS** |
| 8 | `test_explicit_nascar_rejection` | Interception of NASCAR / Daytona 500 questions | **PASS** |
| 9 | `test_explicit_wec_rejection` | Interception of WEC / Le Mans inquiries | **PASS** |
| 10 | `test_bathurst_1000_rejection` | Interception of Bathurst 1000 / Supercars questions | **PASS** |
| 11 | `test_f1_comparison_questions_mentioning_another_motorsport` | Preservation of valid F1 comparison questions | **PASS** |
| 12 | `test_ambiguous_entity_resolution` | Detection of ambiguous aliases (e.g. Italy) | **PASS** |
| 13 | `test_domainguard_execution_before_chromadb_retrieval` | Mock verification that `retrieve()` is never called | **PASS** |
| 14 | `test_no_regressions_in_existing_structured_queries` | Weather, fastest lap, standings, and constructor points | **PASS** |

### 4.2 Full Test Suite Regression Results

Command: `pytest -q`
```text
125 passed, 22 warnings in 10.92s
```
- Total test files: 13
- Total tests: 125
- Pass rate: **100.0%** (125 / 125)

---

### 4.3 Benchmark Regression Summary

All three benchmark suites were evaluated in explicit offline mode (`--offline`) using in-process FastAPI TestClient without external API calls:

| Benchmark Suite | Total Cases | Passed | Failed | Accuracy | External API Calls |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Baseline (2024)** | 30 | 30 | 0 | **100.0%** | 0 |
| **Evaluation V2** | 75 | 75 | 0 | **100.0%** | 0 |
| **Holdout V1** | 30 | 26 | 4 | **86.7%** | 0 |

---

## 5. Examples of Valid and Rejected Queries

### 5.1 Out-of-Domain Interceptions (Pre-Retrieval)

1. **MotoGP**:
   - *Query*: *"Who won the 2024 MotoGP World Championship?"*
   - *Result*: Refused before retrieval.
   - *Output*: `"I couldn't find that information in the retrieved race data. That event is not part of the Formula 1 2024 calendar."`
2. **Bathurst 1000**:
   - *Query*: *"Who won the 2024 Bathurst 1000?"*
   - *Result*: Refused before retrieval.
   - *Output*: `"I couldn't find that information in the retrieved race data. That event is not part of the Formula 1 2024 calendar."`
3. **NASCAR**:
   - *Query*: *"What was the result of the Daytona 500?"*
   - *Result*: Refused before retrieval.
   - *Output*: `"I couldn't find that information in the retrieved race data. That event is not part of the Formula 1 2024 calendar."`
4. **Unsupported Season**:
   - *Query*: *"Who won the 2020 Italian Grand Prix?"*
   - *Result*: Refused before retrieval.
   - *Output*: `"I couldn't find that information in the retrieved race data. Historical data for season 2020 is not available."`
5. **Out-of-Calendar F1 Grand Prix**:
   - *Query*: *"What was the race result of the 2024 German Grand Prix?"*
   - *Result*: Refused before retrieval.
   - *Output*: `"I couldn't find that information in the retrieved race data. That event is not part of the Formula 1 2024 calendar."`

### 5.2 Preserved Valid F1 Queries

1. **F1 Comparison with Non-F1 Motorsport**:
   - *Query*: *"How do 2024 Formula 1 cornering speeds at Silverstone compare to NASCAR?"*
   - *Result*: Valid in-domain comparison; passed to processing.
2. **Circuit Name Query**:
   - *Query*: *"Did rainfall occur during the 2024 Italian Grand Prix at Monza?"*
   - *Result*: Valid; `Monza` resolved to `Italian Grand Prix`; routed to SQLite weather service.
   - *Output*: `"No, there was no rainfall recorded during the 2024 Italian Grand Prix. The track conditions were dry."`
3. **Reserve Driver Query**:
   - *Query*: *"Where did Oliver Bearman finish in the 2024 Saudi Arabian Grand Prix?"*
   - *Result*: Valid; `Bearman` resolved to `Oliver Bearman`; processed accurately.
   - *Output*: `"Oliver Bearman finished P7 and scored 6.0 points."`

---

## 6. Unresolved Limitations & Boundary for Next Phases

In strict adherence to the project instructions, **Phase 4A did not implement Phase 4B, 4C, 4D, or 4E**:
1. **Holdout V1 Remaining 4 Cases**:
   - Case 102 (`race_winner`): Natural phrasing *"claimed victory"* bypassing direct winner extraction and hitting the multi-line regex bug in `gemini.py`. (Scheduled for Phase 4B/4D).
   - Cases 117 & 119 (`driver_standings`): Plural possessive *"drivers' championship"* and temporal *"lead following"* bypassing rigid keywords in `_route_structured_query`. (Scheduled for Phase 4B).
   - Case 122 (`constructor_standings`): Phrasing *"highest number of points"* bypassing constructor points routing. (Scheduled for Phase 4B).
2. **Intent Classification**:
   - The modular `IntentClassifier` and slot-filling ambiguity handler will be implemented in Phase 4B.

---

## 7. Confirmation of Database Invariants

A read-only inspection confirmed that production databases remained completely intact:
- **SQLite (`data/raceintel.db`)**:
  - `seasons`: 1
  - `events`: 24
  - `drivers`: 24
  - `constructors`: 10
  - `sessions`: 24
  - `race_results`: 479
  - `laps`: 26,604
  - `weather_observations`: 3,690
- **ChromaDB (`data/chroma`)**:
  - Collection count: **503 documents**

Phase 4A is complete and ready for review.
