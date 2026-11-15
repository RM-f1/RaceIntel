# RaceIntel — Phase 5B Implementation Report: Intent Classification Generalisation & Routing Capability Boundaries

**Date:** 2026-11-12  
**Scope:** Structural NLP/regex intent generalisation in `IntentClassifier`, single-race two-driver comparison (`DRIVER_RACE_COMPARISON`), weather formatter generalisation, and strict SQL-to-RAG capability boundaries across `QueryPlanner` and `ChatService`.

---

## 1. Problems Addressed

Phase 4E analysis identified 12 intent-classification blind spots where valid structured SQL questions fell back to `GENERAL_RAG`, as well as brittle edge cases in entity extraction and formatter routing:
1. Natural phrasings outside narrow Phase 4B/4C templates (`"came first"`, `"track surface temperature"`, `"ambient air temp"`, `"humidity"`, `"topped the championship"`, `"failed to finish"`, `"did not see the chequered flag"`, `"compounds were fitted"`, `"ranked in the standings"`, `"top three"`, `"outscored their teammate"`, `"placed higher"`).
2. Two-driver single-race head-to-head questions (`"Between Charles Leclerc and Carlos Sainz, who achieved the stronger classification at Monza?"`) lacked a dedicated single-race SQL path and triggered 2-driver RAG fallbacks instead of deterministic SQLite resolution.
3. Single-race points tallies using phrasing such as `"championship points did <Team> tally in <Race>"` prematurely hit cumulative standings logic and returned `GENERAL_RAG`.
4. Three-letter timing codes matching common English words (`nor`, `per`, `law`, `gas`, `bot`, `str`) lacked uppercase gating in `extract_entities()`.
5. Executable non-retriever `QueryPlan` objects returning `None` from execution could fall through to RAG instead of returning a bounded unavailability response.

---

## 2. Changes Implemented

### 2.1 Deterministic Single-Race Driver Comparison (`race_service.py`, `QueryPlanner`, `ChatService`)
- Added [`compare_drivers_in_race`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/services/race_service.py#L260) and [`format_driver_race_comparison_answer`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/services/race_service.py#L285) using `get_driver_race_result()` with safe handling for `P`-prefixed positions and non-classified (`DNF`) statuses.
- Added `Intent.DRIVER_RACE_COMPARISON` to [`Intent`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/routing/intent_classifier.py#L18), planned it cleanly in [`QueryPlanner.create_plan`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/routing/query_planner.py#L202), and dispatched it in [`ChatService._execute_query_plan`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/chat/chat_service.py#L891).

### 2.2 Structural Intent Generalisation & Guards (`intent_classifier.py`)
- **Three-letter timing code guard**: English-colliding codes (`nor`, `per`, `law`, `gas`, `bot`, `str`) now match only when uppercase in the raw question (`\bNOR\b`), preventing false matches on lowercase prose while preserving uppercase timing codes (`VER`, `NOR`, `COL`, etc.).
- **Conceptual / definitional guard**: Pure conceptual questions without events or entities (`"What does DNF mean?"`, `"Explain how tyre compounds work"`) route directly to `GENERAL_RAG` rather than hitting event-bound ambiguity prompts.
- **Generalized intent rules**: Expanded structural patterns across `RACE_RETIREMENTS`, `RACE_CLASSIFICATION`, `BIGGEST_MOVERS`, `TYRE_USAGE`, `CONSTRUCTOR_STANDINGS_LEADER`, `DRIVER_STANDINGS_LEADER`, `CONSTRUCTOR_STANDINGS_COMPARISON`, `DRIVER_STANDINGS_COMPARISON`, `DRIVER_RACE_COMPARISON`, `DRIVER_CUMULATIVE_POINTS`, `DRIVER_CHAMPIONSHIP_POSITION`, `CONSTRUCTOR_STANDINGS_TABLE`, `DRIVER_STANDINGS_TABLE`, `CONSTRUCTOR_RACE_POINTS`, `FASTEST_LAP`, `WEATHER` (removing the post-pattern string filter that dropped `track surface`, `ambient`, `humidity`, etc.), `PODIUM`, `RACE_WINNER`, `DRIVER_POINTS`, `DRIVER_POSITION`, `DRIVER_PERFORMANCE`, `TEAM_COMPARISON`, `MOST_POINTS_IN_TEAM`, `TEAM_PERFORMANCE`, and `POINTS_SCORERS`.
- Fixed single-race vs cumulative points precedence so single-race tallies without `"after/following/post/standings/cumulative"` do not hit `DRIVER_CUMULATIVE_POINTS` / `GENERAL_RAG`.
- Guarded `TEAM_PERFORMANCE` against bare `"do"` so conceptual `"how/why do <team>..."` questions do not falsely classify as team race results.

### 2.3 Weather Formatter Generalisation & Capability Boundary (`weather_service.py`, `ChatService`)
- Updated [`format_weather_answer`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/services/weather_service.py#L92) to support `"track surface"`, `"track temp"`, `"asphalt"`, `"air temp"`, `"ambient"`, `"wet or dry"`, `"humidity"`, `"wind"`, and `"pressure"`.
- Tightened [`ChatService.ask`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/src/raceintel/chat/chat_service.py#L1021) so an executable non-`retriever` `QueryPlan` never silently falls through to RAG if execution yields `None`.

---

## 3. Verification

### 3.1 Tests Added
- Created [`tests/test_phase_5b.py`](file:///c:/Users/mehra/OneDrive/Desktop/RaceIntel/tests/test_phase_5b.py) (46 collected test cases covering generalised phrasings across all structured intents, conceptual RAG preservation, uppercase/lowercase 3-letter timing code safety, deterministic single-race & standings comparisons, surface temperature & humidity formatting, and SQL-to-RAG capability boundaries).

### 3.2 Test Run Results
Command executed:
```powershell
.\venv\Scripts\python.exe -m pytest tests\test_phase_5b.py tests\test_phase_5a.py tests\test_phase3a_structured.py tests\test_phase_4a.py tests\test_phase_4a_adversarial.py tests\test_phase_4b.py tests\test_phase_4c.py tests\test_phase_4d.py -v
```
Result: **`197 passed, 2 warnings in 11.33s`** (`0` failures, `0` skipped, zero external Gemini API calls).

### 3.3 Post-5B File SHA256 Checksums
- `src/raceintel/services/race_service.py`: `0370e5bf94d4053d2be5b47fe3368f48332287c240d9f086501257c4e6735dad`
- `src/raceintel/services/weather_service.py`: `1244ae74a8f6d1f0dd51964e70d3867aee1cad6812192793ee610b7ddc928949`
- `src/raceintel/routing/intent_classifier.py`: `63d581cf139aa25c80a44f98010c9349a9e0bf05a7754b3c7b0120ed8202f793`
- `src/raceintel/routing/query_planner.py`: `f755ab8684f9cef0fa7a2e2f26b7c22a4a45a051c9fc5e6b930564eb070b8ba5`
- `src/raceintel/chat/chat_service.py`: `7e1d83e54485a8d8eaf7619cc289b45cd59a0feebc2685800ccbb1fd694dddd2`
- `tests/test_phase_5b.py`: `fb60271c1168b39b1e3a7dc3adbd5d228031fde55dbf84c301c36f60a77dda5c`
