# RaceIntel — Phase 2.5: Evaluation Failure Analysis Report

## 1. Executive Summary

During the Phase 2 Evaluation V2 benchmark, 75 verified test cases were evaluated against RaceIntel, achieving an overall accuracy of **84.0% (63 passed, 12 failed, 0 errors, 0 quota errors)**. All 30 baseline cases from Phase 1 were preserved and passed at 100%.

This Phase 2.5 investigation performs a strictly read-only audit of the **12 failed evaluation cases**. Every failure was traced across the ingestion pipeline, ChromaDB vector store, deterministic rule routing, semantic fallback retrieval, and evaluation comparison logic.

### Key Findings
1. **No Application Regressions**: The 100% baseline accuracy on race winner, podium, finishing position, driver points, and team comparison categories remains completely intact.
2. **Knowledge Partitioning (50.0% of failures)**: Weather observations (3,690 rows in SQLite) are isolated in the database and REST API, and are completely absent from ChromaDB vector documents.
3. **ChatService Direct Answer Gaps (33.3% of failures)**: ChatService lacks deterministic direct-answer handlers for lap times, championship standings, and constructor-level points aggregation.
4. **Semantic Retrieval Leakage (16.7% of failures)**: When queries lack recognized entity keywords (e.g. out-of-calendar races or ambiguous questions), ChromaDB unconstrained semantic search returns nearest unrelated 2024 races, and the direct answer parser over-eagerly extracts winners from those unrelated documents.
5. **Evaluation Matcher Integrity**: The evaluation matcher operates fairly and did not create false-positive failures. However, refusal matching can be tightened to verify the absence of positive assertions alongside refusal keywords.

---

## 2. Case-by-Case Failure Investigation

Below is the exhaustive audit of all 12 failed benchmark cases:

---

### Case 48 — Driver Championship Leader
- **Question ID**: 48
- **Category**: `driver_standings`
- **Question**: *"Who leads the driver standings after the Bahrain Grand Prix?"*
- **Expected Answer**: `"Max Verstappen"`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (context was retrieved, but factual synthesis was absent).
- **Subsystem Origin**: **ChatService Logic Gap**.
- **Empirical Evidence**:
  - `Retriever._extract_filters()` extracted `{'race_name': 'Bahrain Grand Prix', 'document_type': 'driver_report'}`.
  - ChromaDB returned 20 driver reports for the Bahrain GP (2,620 characters), containing `Driver: Max Verstappen`, `Finished: P1`, `Points: 26.0`.
  - `ChatService._direct_answer()` contains rules for `how did ... perform`, `how many points`, `what position`, `who won`, `who scored points`, `podium`, `finished higher`, `most points`, and `team performance`. It has **no rule** for `standings` or `leads`.
  - `_direct_answer()` returned `None`, falling back to the default retrieval refusal.
  - The SQLite database contains the ground truth via `standings_service.get_driver_championship(session_id=2)`, but ChatService does not query relational standings.

---

### Case 49 — Fastest Lap in Bahrain Grand Prix
- **Question ID**: 49
- **Category**: `lap_time`
- **Question**: *"Who set the fastest lap in the 2024 Bahrain Grand Prix?"*
- **Expected Answer**: `"Max Verstappen"`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (data present in retrieved document, but unparsed).
- **Subsystem Origin**: **ChatService Logic Gap**.
- **Empirical Evidence**:
  - `Retriever._extract_filters()` extracted `{'season': 2024, 'race_name': 'Bahrain Grand Prix', 'document_type': 'race_report'}`.
  - ChromaDB returned document `2024_1` (731 characters), which explicitly contains:
    ```
    Fastest Lap:
    Max Verstappen
    ```
  - `ChatService._extract_race_info()` regex only extracts `Winner:` and `Podium:`. It completely ignores `Fastest Lap:`.
  - `ChatService._direct_answer()` has no handler for "fastest lap" or "lap time".
  - `_direct_answer()` returned `None`, triggering fallback refusal.

---

### Case 50 — Fastest Lap in British Grand Prix
- **Question ID**: 50
- **Category**: `lap_time`
- **Question**: *"Who set the fastest lap in the British Grand Prix?"*
- **Expected Answer**: `"Carlos Sainz"`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (data present in retrieved document, but unparsed).
- **Subsystem Origin**: **ChatService Logic Gap**.
- **Empirical Evidence**:
  - `Retriever._extract_filters()` extracted `{'race_name': 'British Grand Prix', 'document_type': 'race_report'}`.
  - ChromaDB returned document `2024_12` (319 characters), which explicitly contains:
    ```
    Fastest Lap:
    Carlos Sainz
    ```
  - As with Case 49, `_extract_race_info()` ignores the fastest lap line, and `_direct_answer()` has no lap-time matching branch.
  - `_direct_answer()` returned `None`, falling through to fallback refusal.

---

### Case 57 — Constructor Points in Bahrain Grand Prix
- **Question ID**: 57
- **Category**: `constructor_standings`
- **Question**: *"Which constructor scored the most points in the Bahrain Grand Prix?"*
- **Expected Answer**: `"Red Bull Racing"`
- **Actual Answer**: `"Max Verstappen"`
- **Classification**: **Factually Wrong** (returned an individual driver name instead of a constructor/team name).
- **Subsystem Origin**: **ChatService Logic Bug (Pattern Collision)**.
- **Empirical Evidence**:
  - `Retriever._extract_filters()` extracted `{'race_name': 'Bahrain Grand Prix', 'document_type': 'driver_report'}`.
  - ChromaDB returned all 20 driver reports for Round 1 (2,620 characters).
  - In `chat_service.py` (lines 464–512):
    ```python
    if "most points" in q:
        ...
        candidates = [r for r in candidates if r["points"] is not None]
        if candidates:
            best = max(candidates, key=lambda r: r["points"])
            return best["driver"]
    ```
  - Because the question string contained `"most points"`, ChatService executed this branch and unconditionally returned `best["driver"]` (`Max Verstappen`), ignoring the word `"constructor"`. Points were never aggregated by constructor.

---

### Case 58 — Rainfall in Canadian Grand Prix
- **Question ID**: 58
- **Category**: `weather`
- **Question**: *"Did it rain during the 2024 Canadian Grand Prix?"*
- **Expected Answer**: `"Yes"`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (weather data missing from vector knowledge base).
- **Subsystem Origin**: **Data Availability (ChromaDB Ingestion)**.
- **Empirical Evidence**:
  - `Retriever._extract_filters()` defaulted `document_type` to `race_report`.
  - ChromaDB returned race report `2024_9` (737 characters). Document fields are limited to: `Season`, `Round`, `Grand Prix`, `Winner`, `Podium`, `Classification`, `Fastest Lap`, `Race Summary`.
  - No weather attributes (rainfall, track conditions, air/track temperature) exist in the document text or metadata.
  - In SQLite `weather_observations`, session 10 has 31 records with `rainfall = 1`.
  - Because ChromaDB lacks weather documents, ChatService returned `None`, triggering refusal.

---

### Case 59 — Rainfall in British Grand Prix
- **Question ID**: 59
- **Category**: `weather`
- **Question**: *"Did it rain during the 2024 British Grand Prix?"*
- **Expected Answer**: `"Yes"`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (weather data missing from vector knowledge base).
- **Subsystem Origin**: **Data Availability (ChromaDB Ingestion)**.
- **Empirical Evidence**:
  - `Retriever` retrieved race report `2024_12` (319 characters).
  - Summary mentions intermediate tyres (*"Hamilton won after changing to intermediate tyres"*), but contains no structured rainfall field.
  - In SQLite `weather_observations`, session 13 has 51 records with `rainfall = 1`.
  - `_direct_answer()` has no weather parsing logic; falls back to refusal.

---

### Case 60 — Rainfall in Bahrain Grand Prix
- **Question ID**: 60
- **Category**: `weather`
- **Question**: *"Did it rain during the 2024 Bahrain Grand Prix?"*
- **Expected Answer**: `"No"`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (weather data missing from vector knowledge base).
- **Subsystem Origin**: **Data Availability (ChromaDB Ingestion)**.
- **Empirical Evidence**:
  - ChromaDB race report `2024_1` contains no weather data.
  - In SQLite `weather_observations`, session 2 has 0 records with `rainfall = 1` (dry session).
  - Neither ChromaDB nor ChatService supports weather retrieval; falls back to refusal.

---

### Case 61 — Air Temperature in Bahrain Grand Prix
- **Question ID**: 61
- **Category**: `weather`
- **Question**: *"What was the average air temperature during the 2024 Bahrain Grand Prix?"*
- **Expected Answer**: `18.2`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (temperature missing from vector knowledge base).
- **Subsystem Origin**: **Data Availability (ChromaDB Ingestion)**.
- **Empirical Evidence**:
  - In SQLite `weather_observations`, session 2 has `ROUND(AVG(air_temperature_celsius), 1) = 18.2`.
  - ChromaDB contains zero temperature documents.
  - No direct answer rule exists; falls back to refusal.

---

### Case 62 — Rainfall in São Paulo Grand Prix
- **Question ID**: 62
- **Category**: `weather`
- **Question**: *"Did it rain during the 2024 São Paulo Grand Prix?"*
- **Expected Answer**: `"Yes"`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (weather data missing from vector knowledge base).
- **Subsystem Origin**: **Data Availability (ChromaDB Ingestion)**.
- **Empirical Evidence**:
  - In SQLite `weather_observations`, session 22 has 117 records with `rainfall = 1` (notoriously wet race).
  - ChromaDB race report `2024_21` contains classification and summary, but no rainfall field.
  - Falls back to refusal.

---

### Case 63 — Air Temperature in Italian Grand Prix
- **Question ID**: 63
- **Category**: `weather`
- **Question**: *"What was the average air temperature during the 2024 Italian Grand Prix?"*
- **Expected Answer**: `33.1`
- **Actual Answer**: `"I couldn't find that information in the retrieved race data."`
- **Classification**: **Unsupported** (temperature missing from vector knowledge base).
- **Subsystem Origin**: **Data Availability (ChromaDB Ingestion)**.
- **Empirical Evidence**:
  - In SQLite `weather_observations`, session 17 has `ROUND(AVG(air_temperature_celsius), 1) = 33.1`.
  - ChromaDB contains zero temperature documents.
  - Falls back to refusal.

---

### Case 64 — Out-of-Calendar Race (Indianapolis 500)
- **Question ID**: 64
- **Category**: `unanswerable`
- **Question**: *"Who won the 2024 Indianapolis 500?"*
- **Expected Answer**: `"UNANSWERABLE"` (Refusal / indication of out-of-scope)
- **Actual Answer**: `"Oscar Piastri won the Hungarian Grand Prix in 2024."`
- **Classification**: **Factually Wrong & Hallucinatory** (fabricated a response about the Hungarian GP).
- **Subsystem Origin**: **Retrieval Leakage + ChatService Over-eagerness**.
- **Empirical Evidence**:
  - "Indianapolis 500" is not in `Retriever.RACES`.
  - Filter extraction: `{'season': 2024, 'document_type': 'race_report'}`. `race_name` was `None`.
  - Fallback semantic search: `client.collection.query(query_texts=["Who won the 2024 Indianapolis 500?"], where={"$and": [{"season": 2024}, {"document_type": "race_report"}]})`.
  - ChromaDB returned the 5 closest race reports, with Round 13 (Hungarian Grand Prix) as top match.
  - `ChatService._direct_answer()` checked `if "who won" in q:`.
  - It found `Winner: Oscar Piastri` in the retrieved Hungarian GP document and output: `"Oscar Piastri won the Hungarian Grand Prix in 2024."`.
  - System failed to detect that the user asked about an IndyCar event, not an F1 race.

---

### Case 67 — Ambiguous Winner Query
- **Question ID**: 67
- **Category**: `ambiguous`
- **Question**: *"Who won the race?"*
- **Expected Answer**: `"AMBIGUOUS"` (Refusal / request for clarification)
- **Actual Answer**: `"Max Verstappen won the Emilia Romagna Grand Prix in 2024."`
- **Classification**: **Factually Wrong & Hallucinatory** (arbitrarily selected a race instead of clarifying).
- **Subsystem Origin**: **Retrieval Leakage + ChatService Over-eagerness**.
- **Empirical Evidence**:
  - The query lacks any race, round, circuit, or driver.
  - Filter extraction: `{'document_type': 'race_report'}`.
  - Semantic query `Who won the race?` matched Round 7 (Emilia Romagna Grand Prix) as the top vector.
  - `ChatService._direct_answer()` saw `"who won"` in the query and matched `Winner: Max Verstappen`.
  - System answered with an arbitrary race without prompting the user to specify which Grand Prix.

---

## 3. Root-Cause Classification & Quantitative Analysis

### Root-Cause Categories

| Root Cause | Description | Affected Case IDs | Failure Count | % of Total Failures |
| :--- | :--- | :--- | :---: | :---: |
| **Root Cause 1: Knowledge Partitioning** | SQLite holds structured data (weather, sessions), but ChromaDB lacks corresponding text documents. | 58, 59, 60, 61, 62, 63 | **6** | **50.0%** |
| **Root Cause 2: ChatService Logic Gaps** | Document exists in ChromaDB, but `_extract_race_info()` or `_direct_answer()` lacks rules to parse and return it. | 48, 49, 50, 57 | **4** | **33.3%** |
| **Root Cause 3: Semantic Retrieval Leakage** | Missing entity filters trigger unconstrained semantic search, returning unrelated docs which `_direct_answer` blindly accepts. | 64, 67 | **2** | **16.7%** |
| **Total** | | | **12** | **100.0%** |

### Category-Level Failure Breakdown

| Evaluation Category | Total Cases | Failed Cases | Failure Rate (%) | Contribution to Failures (%) |
| :--- | :---: | :---: | :---: | :---: |
| `weather` | 6 | 6 | 100.0% | 50.0% (6/12) |
| `lap_time` | 2 | 2 | 100.0% | 16.7% (2/12) |
| `driver_standings` | 1 | 1 | 100.0% | 8.3% (1/12) |
| `constructor_standings` | 1 | 1 | 100.0% | 8.3% (1/12) |
| `unanswerable` | 3 | 1 | 33.3% | 8.3% (1/12) |
| `ambiguous` | 3 | 1 | 33.3% | 8.3% (1/12) |
| `race_winner` | 10 | 0 | 0.0% | 0.0% (0/12) |
| `race_result` | 5 | 0 | 0.0% | 0.0% (0/12) |
| `finishing_position` | 7 | 0 | 0.0% | 0.0% (0/12) |
| `points` | 9 | 0 | 0.0% | 0.0% (0/12) |
| `driver_performance` | 11 | 0 | 0.0% | 0.0% (0/12) |
| `team_performance` | 6 | 0 | 0.0% | 0.0% (0/12) |
| `team_comparison` | 5 | 0 | 0.0% | 0.0% (0/12) |
| `season_awareness` | 6 | 0 | 0.0% | 0.0% (0/12) |
| **Total** | **75** | **12** | **16.0%** | **100.0%** |

---

## 4. Deep-Dive on Known Architectural Issues

### A. Knowledge Base Partitioning (SQLite vs ChromaDB)
RaceIntel has a dual-architecture disparity:
- **Relational Layer (`raceintel.db`)**: 
  - 3,690 weather observations across air temp, track temp, humidity, rainfall, and pressure.
  - 26,604 lap records with individual lap times, sector splits, and tyre compounds.
  - 479 driver race classifications and standings.
  - Operational analytics services: `weather_service.py`, `pace_service.py`, `standings_service.py`.
- **Vector Layer (`data/chroma`, 503 documents)**:
  - 24 `race_report` documents.
  - 479 `driver_report` documents.
  - **Zero** weather, pace, or standings documents.
- **Consequence**: The Chat/RAG pipeline exclusively queries ChromaDB. Any query about weather or standalone standings is mathematically unanswerable by the RAG pipeline regardless of how intelligent the LLM is, because the context passed to the LLM will never contain weather data.

### B. Unconstrained Semantic Retrieval & Template Over-eagerness
When a query contains a recognizable race name (e.g., "Monaco", "Canada"), the retriever uses **deterministic filtering**:
`where = {'race_name': 'Monaco Grand Prix', 'document_type': 'race_report'}`.
This deterministic path is 100% reliable.

However, when a user asks about an unknown race ("Indianapolis 500") or asks an ambiguous question ("Who won the race?"):
1. Filter extraction yields `race_name = None`.
2. The retriever falls back to:
   `collection.query(query_texts=[question], n_results=5, where={'document_type': 'race_report'})`.
3. ChromaDB vector search calculates cosine distances across all 24 race reports. Even if the nearest document has poor similarity (e.g., Hungarian GP), ChromaDB still returns it because there is **no minimum similarity threshold**.
4. `ChatService._direct_answer()` inspects the question string. If `"who won"` is present anywhere in the string, it extracts the `Winner:` line from the top retrieved document and asserts:
   `f"{race_info['winner']} won the {race_match} in {season_match}."`
5. This creates a severe hallucination loop: out-of-domain queries receive deterministic answers asserting an unrelated race.

---

## 5. Fairness of Robustness & Refusal Evaluation

Task 5 requires auditing whether passing unanswerable and ambiguous cases passed fairly or merely by superficial keyword presence.

### Audited Passing Cases
1. **Case 65 (*"How did Ayrton Senna perform in the 2024 Monaco Grand Prix?"*)**:
   - Retrieved Monaco GP race report.
   - `_direct_answer()` searched driver list for "Ayrton Senna". Found none; returned `None`.
   - Response: `"I couldn't find that information in the retrieved race data."`
   - *Verdict*: **Fair Pass**. The system made zero unsupported claims about Senna and correctly declared the information absent.
2. **Case 66 (*"What was the result of the 2024 French Grand Prix?"*)**:
   - Semantic retrieval pulled 5 race reports. `_direct_answer()` found no winner/podium pattern matching "what was the result of"; returned `None`.
   - Response: `"I couldn't find that information in the retrieved race data."`
   - *Verdict*: **Fair Pass**. Correctly avoided fabricating a French GP result.
3. **Case 68 (*"What position did he finish?"*) & Case 69 (*"How many points did the driver score in Canada?"*)**:
   - `_direct_answer()` could not resolve "he" or "the driver" to a valid driver; returned `None`.
   - Response: Refusal text.
   - *Verdict*: **Acceptable Pass**. While a conversational system should ideally respond with a clarifying prompt (*"Which driver are you referring to?"*), returning an honest refusal is strictly safe and avoids hallucination.
4. **Cases 74 & 75 (*"Who won the 2023 Monaco / 2022 Canadian GP?"*)**:
   - Retrieved context was empty (`0 chars`) because season filters (`2023`, `2022`) matched no ChromaDB documents.
   - Response: Refusal text.
   - *Verdict*: **Fair Pass**. Correctly identified that historical season data is absent.

### Matcher Vulnerability Identified
The current evaluation matcher implementation in `run_evaluation.py`:
```python
def compare_unanswerable(actual: str) -> bool:
    if not actual:
        return True
    actual_lower = actual.lower()
    return any(p in actual_lower for p in REFUSAL_PHRASES)
```
- **Vulnerability**: If an LLM generated a hallucination with an appended caveat (e.g., *"Max Verstappen won the 2024 Indy 500, but official confirmation is not available."*), the matcher would match `"not available"` and flag the response as **PASS**, despite the hallucination.
- In the Phase 2 test suite, this vulnerability did **not** trigger because offline responses were either pure direct-answer templates or pure refusal strings. However, for Phase 3 live LLM evaluations, the matcher must be hardened.

---

## 6. Evaluation-Matcher Accuracy Sensitivity Analysis

Does the reported **84.0% accuracy** accurately reflect reality, or is it distorted by matcher rules?

### Potential Accuracy Deflation (-2.7%)
- **Cases 49 & 50 (Fastest Lap)**: The text `Fastest Lap: Max Verstappen` and `Fastest Lap: Carlos Sainz` was present in the retrieved ChromaDB race report. Because the offline benchmark used the deterministic direct answer path (which lacks a fastest-lap regex), these cases failed.
- In a live Gemini deployment, Gemini Flash reading the retrieved context would easily see `Fastest Lap: Max Verstappen` and answer correctly.
- If live Gemini answers these 2 cases, true live RAG accuracy would be **86.7% (65/75)**.

### Weather Deflation (0.0% — Genuine Failure)
- Cases 58–63 (Weather) failed because weather data is completely missing from ChromaDB. Even with a live LLM, Gemini is prompt-instructed not to use outside knowledge. Therefore, Gemini would also refuse these cases. The 0/6 weather failure is **100% genuine**.

### Potential Accuracy Inflation (0.0% in current run)
- Substring matching in `compare_string_answer()` could theoretically match short driver names inside unrelated words. Because all ground truth strings in the benchmark are full names (*"Charles Leclerc"*, *"Max Verstappen"*), no false-positive passes occurred.

---

## 7. Prioritized Engineering Fixes for Phase 3

| Priority | Fix Description | Target Subsystem | Estimated Impact |
| :---: | :--- | :--- | :--- |
| **P0** | **ChromaDB Weather Ingestion**<br>Create `RaceDocumentGenerator.generate_weather_report()` and index all 24 sessions from `weather_observations` into ChromaDB. | Retrieval / Indexer | Resolves 6 failures (+8.0% accuracy). |
| **P1** | **Semantic Retrieval Distance Gating**<br>In `Retriever.retrieve()`, check ChromaDB cosine distance. If distance $> 0.35$ or no recognized entity is present, return empty context instead of unrelated races. | Retrieval | Resolves Case 64 & 67 (+2.7% accuracy). |
| **P1** | **Fastest Lap Direct Answer Handler**<br>Add `Fastest Lap:\s*(.+)` extraction to `_extract_race_info()` and add fastest lap rule in `_direct_answer()`. | ChatService Logic | Resolves Cases 49 & 50 (+2.7% accuracy). |
| **P2** | **Constructor Points Direct Rule**<br>In `_direct_answer()`, check if `constructor` or `team` is in query when `most points` matches, and aggregate points by constructor. | ChatService Logic | Resolves Case 57 (+1.3% accuracy). |
| **P2** | **Championship Standings Ingestion**<br>Generate `standings_report` documents in ChromaDB or add relational fallback tool in ChatService. | Ingestion / ChatService | Resolves Case 48 (+1.3% accuracy). |
| **P2** | **Evaluation Matcher Hardening**<br>Ensure `compare_unanswerable()` verifies that no positive entity assertions (e.g. `P1`, `won the race`, points values) exist alongside refusal phrases. | Evaluation Matcher | Eliminates hallucination false-positive risk. |

**Cumulative Impact**: Implementing P0 + P1 + P2 will raise Evaluation V2 benchmark accuracy from **84.0% to 100.0% (75/75)**.

---

## 8. Recommended Phase 3 Scope

1. **Sprint 3.1: Vector Knowledge Base Unification**
   - Ingest SQLite `weather_observations` into ChromaDB as `document_type = "weather_report"`.
   - Ingest SQLite `standings` and `pace` into ChromaDB.
2. **Sprint 3.2: Retrieval Gating & Ambiguity Guards**
   - Enforce distance thresholds on ChromaDB semantic queries.
   - If query lacks known entities and distance is weak, return explicit disambiguation prompt.
3. **Sprint 3.3: ChatService Direct Answer Hardening**
   - Implement fastest lap regex parser.
   - Implement constructor-level points aggregation.
4. **Sprint 3.4: RAGAS Live Scoring Pilot**
   - Execute the 8-case genuine RAGAS pilot upon explicit user authorization.
