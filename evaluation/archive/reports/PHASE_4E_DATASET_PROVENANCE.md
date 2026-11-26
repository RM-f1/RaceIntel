# Phase 4E — Independent Dataset Generation & Provenance Report

## 1. Purpose and Overview

To validate whether RaceIntel genuinely generalises beyond historical regression datasets that shaped Phases 1–4D, a new 80-question independent validation benchmark (`evaluation/raceintel_independent_benchmark_v1.json`) was constructed directly from authoritative data stores (`data/raceintel.db` and `data/chroma`) without reusing existing benchmark questions or expected-answer templates.

- **Dataset path**: `evaluation/raceintel_independent_benchmark_v1.json`
- **Locked Pre-Execution SHA256**: `0407af561d13e9dde7d6dd8fe550cf2b3cba4e09bdcbd656c3925f0a584112a1`
- **Total cases**: `80` (`IND-001` through `IND-080`)
- **Unique exact questions**: `80` (`0` duplicates)
- **Dataset immutability guarantee**: Zero edits made to `evaluation/raceintel_independent_benchmark_v1.json` after first executing it against RaceIntel (`benchmark_sha256` verified identical in `evaluation/raceintel_independent_benchmark_v1_results.json`).

---

## 2. Authoritative Data Sources & Corpus Inventory

All ground-truth expectations were derived independently from the frozen data layer:

1. **Structured Database (`data/raceintel.db`)**
   - **SHA256**: `61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e`
   - Contains 2024 Formula 1 Grand Prix **Race sessions only** (`session_type = 'Race'`, `session_id` `2` through `25` chronologically ordered across 24 Grands Prix; note `event_id=1` in `events` corresponds to the British Grand Prix while `session_id` defines round chronology).
   - Because SQLite stores Race sessions only (no Sprint results), cumulative standings gold truths reflect Grand Prix points only (e.g., Max Verstappen cumulative points after Abu Dhabi = `399.0`, McLaren = `609.0`, Ferrari = `595.0`).
   - Weather telemetry in `weather`: Spanish Grand Prix (`session_id=11`) and Austrian Grand Prix (`session_id=12`) each contain `rain_observations = 1`, which the deterministic SQL service classifies as `Wet`.

2. **Vector Knowledge Store (`data/chroma`, collection `raceintel_knowledge`)**
   - **Chroma SQLite SHA256**: `2a87b264e3b0052f9cfea0b71f69f50fae3d012aa094b0e9d8a7993af0cc5f9e`
   - **Document count**: `503` documents total (`24` `race_report` documents, `479` `driver_report` documents)
   - **Embedding model**: `all-MiniLM-L6-v2` (`SentenceTransformerEmbeddingFunction`)
   - **Content-level SHA256** (sorted `(id, document, metadata)`): `a6af7d37f4ecf25bbff71215c184ad2dc00637d692a139188e4b506144a35a5a`

### Corpus-Driven Category Adaptation

Inspecting the actual ChromaDB inventory revealed that `raceintel_knowledge` contains **only** structured per-race summaries (`24` `race_report` docs) and per-driver finishing records (`479` `driver_report` docs), and contains **zero** general F1 regulatory, sporting, aerodynamic, or pit-strategy documents.

In accordance with the requirement *"Do not invent gold answers unsupported by the actual corpus"* and *"Adapt the distribution only when actual data availability requires it. Document deviations"*:

- The recommended 10 `General F1 explanatory/document questions` were adapted to:
  - **7 `rag_document_grounded` questions (`IND-061`–`IND-067`)**: race narrative/overview queries verifiable directly against ChromaDB `race_report` documents, plus `IND-067` testing a ChromaDB-resident fact (`Round: 13` for the 2024 Hungarian Grand Prix, present in `2024_13` text).
  - **3 technical/corpus-gap abstention probes (`IND-073`–`IND-075`)** placed in `unsupported_or_unanswerable`: F1 undercut strategy (`IND-073`), 2024 Italian GP Ferrari aerodynamic upgrades (`IND-074`), and Norris's 2024 British GP pit-stop duration (`IND-075`), testing calibrated refusal on genuinely absent technical facts.

---

## 3. Benchmark Composition

| Category | Target | Actual | Variance |
|---|---:|---:|---:|
| `race_results_and_winners` | 10 | 10 | 0 |
| `driver_standings_and_points` | 10 | 10 | 0 |
| `constructor_standings_and_points` | 8 | 8 | 0 |
| `weather_and_conditions` | 8 | 8 | 0 |
| `pace_and_fastest_laps` | 8 | 8 | 0 |
| `tyres_position_and_classification` | 8 | 8 | 0 |
| `multi_entity_comparisons` | 8 | 8 | 0 |
| `rag_document_grounded` (adapted from General F1/doc) | 10 | 7 | -3 (moved to unanswerable) |
| `ambiguous_or_underspecified` | 5 | 5 | 0 |
| `unsupported_or_unanswerable` | 5 | 8 | +3 (absent F1 doc probes) |
| **Total** | **80** | **80** | **0** |

### Expected Routing & Intent Coverage

- **Expected Routes**: `SQL` (`60`), `RAG` (`11`: `7` answerable grounded + `4` unanswerable abstention probes), `clarification` (`5`), `domain_rejection` (`4`).
- **Expected Intents (`26` distinct labels covered)**:
  `race_winner` (`5`), `podium` (`3`), `driver_position` (`1`), `driver_performance` (`1`), `driver_standings_leader` (`2`), `driver_championship_position` (`2`), `driver_cumulative_points` (`2`), `driver_standings_table` (`1`), `driver_points` (`2`), `points_scorers` (`1`), `constructor_standings_leader` (`2`), `constructor_standings_table` (`1`), `constructor_race_points` (`3`), `team_performance` (`2`), `weather` (`8`), `fastest_lap` (`8`), `tyre_usage` (`3`), `biggest_movers` (`2`), `race_retirements` (`2`), `race_classification` (`1`), `driver_standings_comparison` (`3`), `constructor_standings_comparison` (`3`), `team_comparison` (`2`), `general_rag` (`11`), `ambiguous` (`5`), `domain_rejection` (`4`).

---

## 4. Schema & Verification Rigor

Every case in `evaluation/raceintel_independent_benchmark_v1.json` includes all 13 verified fields:
`id`, `question`, `expected_intent`, `expected_route`, `expected_answer`, `required_entities`, `required_season`, `required_event`, `expected_evidence`, `answerability_status`, `evaluation_criteria`, `category`, `difficulty`.

Structured gold truths were cross-checked by executing SQL verification queries directly against `data/raceintel.db` before running any RaceIntel code. Unanswerable cases explicitly record the evidentiary reason neither SQLite nor ChromaDB supports an answer (`2019` unsupported season, out-of-calendar Grands Prix such as `German` / `Argentine`, non-F1 championship `Formula E`, retired driver `Michael Schumacher`, and missing technical telemetry such as pit-stop durations and aero upgrades). Ambiguous cases explicitly record the missing slot (`grand prix`, `driver`, or `Emilia Romagna` vs `Italian` host disambiguation).

---

## 5. Independence Safeguards & Overlap Audit

The following safeguards were strictly enforced:

1. **Zero Question Copying**: Questions were authored using natural paraphrasing, circuit aliases (`Suzuka`, `Spielberg`, `Baku`, `Hungaroring`, `Marina Bay`, `Spa-Francorchamps`, `Austin`), varied sentence syntax (`came first`, `victor`, `topped the drivers' championship`, `failed to finish`, `walked away with championship points`, `asphalt track surface`), and unseen combinations of events/drivers/teams.
2. **Pre-Run Jaccard Similarity Screen**: Prior to executing the benchmark against RaceIntel, an automated overlap check ran against `155` existing questions from `raceintel_eval_2024.json`, `raceintel_eval_v2.json`, `raceintel_holdout_v1.json`, and Phase 4D probes in `evaluation/run_rag_calibration.py`. Eleven candidate questions initially exhibiting token Jaccard similarity `>= 0.65` were rewritten cleanly before execution.
3. **Final Pre-Run Overlap Metrics**:
   - Exact case-insensitive matches against all `155` existing questions/probes: **`0`**
   - Internal question pairs with Jaccard `>= 0.70`: **`0`**
   - Maximum token Jaccard against any existing dataset question: **`0.636`** (`IND-030` `"Did it rain at the 2024 Qatar Grand Prix?"` vs V2 `"Did it rain during the 2024 Canadian Grand Prix?"`)
4. **Post-Execution Dataset & System Freeze**: After executing the benchmark against RaceIntel, **zero** modifications were made to `evaluation/raceintel_independent_benchmark_v1.json`, and **zero** changes were made to application code (`src/`), prompts, thresholds, or routing rules.
