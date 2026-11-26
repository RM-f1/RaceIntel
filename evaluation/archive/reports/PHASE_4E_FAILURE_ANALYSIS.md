# Phase 4E — Failure Analysis Report

## 1. Failure Overview

Out of **80** cases in the frozen independent benchmark (`evaluation/raceintel_independent_benchmark_v1.json`), executed strictly offline (`0` external Gemini calls) against the frozen RaceIntel codebase:

- **Passed**: `61 / 80` (`76.2%`)
- **Failed**: `19 / 80` (`23.8%`)
- **Unscorable / Skipped**: `0 / 80` (`0.0%`)

Every failure (`19/19`) and all RAG-routed cases (`15/15`) were manually inspected against exact system telemetry and source code paths.

---

## 2. Failure Taxonomy Summary

| Taxonomy Category | Count | Case IDs | Severity Range | System Defect vs Limitation |
|---|---:|---|---|---|
| **Event resolution failure** (Wrong event SQL collision) | 4 | `IND-007`, `IND-024`, `IND-041`, `IND-048` | **Critical** | System defect |
| **Incorrect intent** + **Incorrect route** (false abstention via RAG) | 6 | `IND-001`, `IND-002`, `IND-011`, `IND-014`, `IND-034`, `IND-039` | **Medium** | System defect |
| **Incorrect intent** + **Incorrect route** + **Wrong/Unsupported answer** | 5 | `IND-006`, `IND-020`, `IND-051`, `IND-059`, `IND-060` | **High** | System defect |
| **Incorrect intent** + **Incorrect route** + **Retrieval filter collision** | 1 | `IND-043` | **Medium** | System defect (dual) |
| **Offline mock LLM limitation** (Retrieval succeeded; mock could not synthesise) | 3 | `IND-063`, `IND-066`, `IND-067` | **Low / Mode Limit** | Offline evaluation limitation |
| **Total Failures** | **19** | | | **16 system defects, 3 offline mock limits** |

*(Note: During initial runner construction, 3 parser regex bugs in `evaluation/run_independent_benchmark.py` — clause splitting on `"1."`/`"P1."`, `\b` failure on `"21.6°C"`, and missing `"rainfall was recorded"` — mis-scored 8 true system passes (`IND-017`, `023`, `031`, `032`, `033`, `035`, `036`, `052`) as `Evaluator limitation` false negatives (`53/80`). After fixing only those 3 regexes in the runner without altering the dataset or system, all 8 verified cleanly as true passes, isolating the 19 genuine failures above at `61/80`.)*

---

## 3. Root Cause Deep-Dives

### Root Cause A — Critical SQL Event Collision: `United States Grand Prix` -> `Miami Grand Prix` (`4` cases)

- **Location**: `src/raceintel/services/session_service.py` (`resolve_race_session`, lines `87–125`)
- **Mechanism**:
  1. `IntentClassifier` and `EntityRegistry` accurately resolved `"Austin"` / `"United States Grand Prix"` to `event_name = "United States Grand Prix"`.
  2. `resolve_race_session()` fetches all 2024 Race sessions ordered chronologically (`ORDER BY s.session_id ASC`) and loops row-by-row with an unprioritized `OR` condition combining exact event name (`clean_target == ev_clean`) and country equality (`country and clean_target == country`).
  3. `Miami Grand Prix` (`session_id = 7`, `country_name = "United States"`) appears earlier in chronological order than `United States Grand Prix` (`session_id = 20`). When `clean_target == "united states"`, the `clean_target == country` clause matches row `7` (`Miami Grand Prix`) first and returns immediately before reaching row `20`.
- **Impact**: Every SQL query targeting Austin / United States Grand Prix (`race_podium`, `constructor_race_points`, `fastest_lap`, `biggest_movers`) silently returned confident, plausible statistics from the **wrong Grand Prix (`Miami Grand Prix`)** with zero error or warning. (Only `IND-014` escaped this bug because its intent was misclassified to RAG!)

### Root Cause B — Rule-Based `IntentClassifier` Generalization Gaps (`12` cases)

- **Location**: `src/raceintel/routing/intent_classifier.py`
- **Mechanism**: Intent classification relies on exact keyword/regex phrases tailored to V2/Holdout phrasings rather than semantic or compositional phrasing coverage:
  - `winner_patterns` requires `"who"` or `"which driver"` immediately before `"came first"` (fails `"Which Formula 1 driver came first..."` in `IND-001`) and omits `"victor"` (`IND-002`).
  - `podium_patterns` checks `"podium"` / `"podium finishers"` (fails `"top three finishers"` in `IND-006`).
  - Championship leader/rank checks omit `"topped the drivers' championship"` (`IND-011`) and `"rank in the driver standings following..."` (`IND-014`).
  - `points_scorers` omits `"walked away with championship points"` (`IND-020`).
  - `weather` checks explicit `"temperature"` / `"weather"` terms and misses `"How hot was the asphalt track surface on average"` (`IND-034`).
  - `fastest_lap` checks adjacent `"fastest lap"` / `"quickest lap"` / `"best lap"` and misses intervening modifiers (`"quickest single lap"` in `IND-039`, `"quickest race lap"` in `IND-043`).
  - `race_retirements` omits `"failed to finish"` (`IND-051`).
  - `team_comparison` misses `"achieved the stronger classification"` (`IND-059`) and `"placed ahead of their teammate"` (`IND-060`).

### Root Cause C — Unsafe RAG Fallback Output on Misrouted SQL Queries (`5` high-severity cases)

- **Location**: `src/raceintel/chat/chat_service.py` (`_direct_answer`) and `src/raceintel/chat/gemini.py` (`_generate_mock_response`, lines `260–280`)
- **Mechanism**:
  1. When `IND-006`, `IND-020`, `IND-051` missed SQL routing and fell into RAG, ChromaDB deterministic filter retrieval returned all `20` `driver_report` docs for that race (`distances = [0.0, ...]`, `status = "ok"`).
  2. `_generate_mock_response` matched broad tokens (`"finish"`, `"point"`) and extracted stats from the **first retrieved driver document alphabetically** (`Alexander Albon` in `IND-006`/`IND-051`, or an empty driver line `"scored 6.0 points, finishing P7."` in `IND-020`), producing a wrong/nonsensical answer instead of abstaining.
  3. On `IND-059` and `IND-060`, `_direct_answer` dumped both teammates' positions/points (`Piastri: P1\nNorris: P2`) without directly answering which single driver finished ahead.

### Root Cause D — Legacy `Retriever._extract_filters()` Substring Driver Collision (`IND-043`)

- **Location**: `src/raceintel/retrieval/retriever.py` (`_extract_filters`)
- **Mechanism**: Even though `IntentClassifier` resolved `"Spa-Francorchamps"` cleanly to `Belgian Grand Prix` with `drivers = []`, legacy `Retriever._extract_filters()` matched `"franc"` inside `"spa-francorchamps"` as `"Franco Colapinto"`, building Chroma filter `{'race_name': 'Belgian Grand Prix', 'driver': 'Franco Colapinto', 'document_type': 'driver_report'}`. Because Colapinto did not compete in the Belgian Grand Prix, retrieval returned `empty`.

### Root Cause E — Offline Mock LLM Synthesis Limit (`3` RAG cases: `IND-063`, `IND-066`, `IND-067`)

- **Location**: `src/raceintel/chat/gemini.py` (`_generate_mock_response`, lines `300–310`)
- **Mechanism**: On `IND-063` (`"Summarize..."`), `IND-066` (`"Recap..."`), and `IND-067` (`"Which round..."`), `Retriever` succeeded `3/3` (`status="ok"`, `distance=0.0`, returning exact `2024_7`, `2024_23`, and `2024_13` documents). However, offline mock LLM synthesis only recognizes 6 fixed summary substrings (`"summary"`, `"overview"`, `"tell me about"`, `"describe"`, `"what happened"`, `"result"`) — omitting `"summarize"` and `"recap"` — and has no regex handler for `"round"`, causing offline mode to return `INSUFFICIENT_EVIDENCE_RESPONSE` despite possessing the exact evidence.

---

## 4. Complete Per-Case Failure Registry (All 19 Failures)

| Case ID | Question | Expected Behaviour | Actual Behaviour | Root Cause Category | Severity | Defect vs Limitation |
|---|---|---|---|---|---|---|
| `IND-001` | Which Formula 1 driver came first at Suzuka in 2024? | SQL `race_winner` -> `Max Verstappen` | Routed `general_rag` -> RAG abstained | `Incorrect intent`, `Incorrect route`, `Incorrect abstention` | Medium | System defect |
| `IND-002` | Who was the victor of the 2024 Emilia Romagna Grand Prix? | SQL `race_winner` -> `Max Verstappen` | Routed `general_rag` -> RAG abstained | `Incorrect intent`, `Incorrect route`, `Incorrect abstention` | Medium | System defect |
| `IND-006` | List the top three finishers from the 2024 São Paulo Grand Prix. | SQL `podium` -> `Verstappen, Ocon, Gasly` | Routed `general_rag` -> `"Alexander Albon finished P18 and scored 0.0 points."` | `Incorrect intent`, `Incorrect route`, `Wrong answer`, `Unsupported answer` | **High** | System defect |
| `IND-007` | Which drivers were on the podium in Austin in 2024? | SQL `podium` (`United States GP`) -> `Leclerc, Sainz, Verstappen` | SQL resolved `Miami Grand Prix` -> `Norris, Verstappen, Leclerc` | `Event resolution failure`, `Wrong answer` | **Critical** | System defect |
| `IND-011` | After the 2024 Italian Grand Prix, who topped the drivers' championship? | SQL `driver_standings_leader` -> `Max Verstappen (279.0)` | Routed `general_rag` -> RAG abstained | `Incorrect intent`, `Incorrect route`, `Incorrect abstention` | Medium | System defect |
| `IND-014` | Where did Charles Leclerc rank in the driver standings following the 2024 United States Grand Prix? | SQL `driver_championship_position` -> `P3 (256.0)` | Routed `general_rag` -> RAG abstained | `Incorrect intent`, `Incorrect route`, `Incorrect abstention` | Medium | System defect |
| `IND-020` | Which drivers walked away with championship points from the 2024 Azerbaijan race? | SQL `points_scorers` -> 10 drivers | Routed `general_rag` -> `"scored 6.0 points, finishing P7."` | `Incorrect intent`, `Incorrect route`, `Wrong answer`, `Unsupported answer` | **High** | System defect |
| `IND-024` | How many points did Ferrari score in the 2024 United States Grand Prix? | SQL `constructor_race_points` (`United States GP`) -> `Ferrari (43.0)` | SQL resolved `Miami Grand Prix` -> `"Ferrari scored 25.0 points in the Miami Grand Prix."` | `Event resolution failure`, `Wrong answer` | **Critical** | System defect |
| `IND-034` | How hot was the asphalt track surface on average during the 2024 Hungarian Grand Prix? | SQL `weather` -> `44.9°C` | Routed `general_rag` -> RAG abstained | `Incorrect intent`, `Incorrect route`, `Incorrect abstention` | Medium | System defect |
| `IND-039` | Who put in the quickest single lap around Marina Bay in 2024? | SQL `fastest_lap` -> `Daniel Ricciardo (1:34.486)` | Routed `general_rag` -> RAG abstained | `Incorrect intent`, `Incorrect route`, `Incorrect abstention` | Medium | System defect |
| `IND-041` | Which driver had the fastest lap in the 2024 United States Grand Prix? | SQL `fastest_lap` (`United States GP`) -> `Esteban Ocon (1:37.330)` | SQL resolved `Miami Grand Prix` -> `Oscar Piastri (1:30.634, Miami GP)` | `Event resolution failure`, `Wrong answer` | **Critical** | System defect |
| `IND-043` | Which competitor logged the quickest race lap at Spa-Francorchamps in 2024? | SQL `fastest_lap` -> `Sergio Perez (1:44.701)` | Routed `general_rag` + Retriever filtered `driver='Franco Colapinto'` -> `empty` -> abstained | `Incorrect intent`, `Incorrect route`, `Entity resolution failure` (retriever filter), `Incorrect abstention` | Medium | System defect |
| `IND-048` | Who gained the most positions in the 2024 United States Grand Prix? | SQL `biggest_movers` (`United States GP`) -> `George Russell (+14)` | SQL resolved `Miami Grand Prix` -> `Fernando Alonso (+6, Miami GP)` | `Event resolution failure`, `Wrong answer` | **Critical** | System defect |
| `IND-051` | Which drivers failed to finish the 2024 Qatar Grand Prix? | SQL `race_retirements` -> 5 drivers | Routed `general_rag` -> `"Alexander Albon finished P15 and scored 0.0 points."` | `Incorrect intent`, `Incorrect route`, `Wrong answer`, `Unsupported answer` | **High** | System defect |
| `IND-059` | Among McLaren's two drivers, who achieved the stronger classification at Hungaroring in 2024? | SQL `team_comparison` -> `Oscar Piastri` | Routed `general_rag` -> `"Oscar Piastri: P1, 25.0 points\nLando Norris: P2, 18.0 points"` (fails to select winner) | `Incorrect intent`, `Incorrect route`, `Missing answer` (indirect dump) | Medium | System defect |
| `IND-060` | Out of the Red Bull pair, who placed ahead of their teammate at the 2024 Baku race? | SQL `team_comparison` -> `Max Verstappen` | Routed `general_rag` -> `"Max Verstappen: P5, 10.0 points\nSergio Perez: P17, 0.0 points"` (fails to select winner) | `Incorrect intent`, `Incorrect route`, `Missing answer` (indirect dump) | Medium | System defect |
| `IND-063` | Summarize the 2024 Emilia Romagna Grand Prix race report. | RAG `general_rag` -> grounded summary from `2024_7` | Retrieved `2024_7` (`dist=0.0`), but offline mock missed `"summarize"` -> abstained | `Incorrect abstention` (offline synthesis template gap) | Low | Offline evaluation / mock limitation |
| `IND-066` | Recap the key narrative and outcomes of the 2024 Qatar Grand Prix. | RAG `general_rag` -> grounded summary from `2024_23` | Retrieved `2024_23` (`dist=0.0`), but offline mock missed `"recap"` -> abstained | `Incorrect abstention` (offline synthesis template gap) | Low | Offline evaluation / mock limitation |
| `IND-067` | Which round of the 2024 season was the Hungarian Grand Prix? | RAG `general_rag` -> `Round 13` from `2024_13` | Retrieved `2024_13` (`dist=0.0`), but offline mock lacks `"Round:"` synthesis -> abstained | `Incorrect abstention` (live LLM required for un-templated metadata QA) | Low | Offline evaluation / mock limitation |

---

## 5. Frozen Implementation Compliance Statement

Per Phase 4E protocol, **zero** fixes were applied to `src/raceintel/services/session_service.py`, `src/raceintel/routing/intent_classifier.py`, `src/raceintel/retrieval/retriever.py`, or `src/raceintel/chat/gemini.py`. The critical `session_service.py` country-over-event priority bug and `IntentClassifier` / `Retriever` generalization defects are documented here for remediation in a dedicated future engineering phase (Phase 5).
