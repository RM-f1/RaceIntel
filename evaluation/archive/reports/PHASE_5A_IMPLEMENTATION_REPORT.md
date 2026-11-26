# RaceIntel — Phase 5A Implementation Report: Event Resolution Correctness

**Date:** 2026-11-12  
**Git HEAD at Start:** `2acb2ab47a3abb1b4a5f9c5693a932f23a8023b4` (branch `main`; pre-existing uncommitted work preserved)  
**Scope:** Multi-stage deterministic Grand Prix event resolution across `session_service.py`, `EntityRegistry`, `IntentClassifier`, and `QueryPlanner`.

---

## 1. Root Cause Addressed

Phase 4E uncovered a critical event-resolution collision between events sharing a host country — notably **United States Grand Prix** (`session_id=20`, Austin) and **Miami Grand Prix** (`session_id=7`, Miami), as well as **Italian Grand Prix** (`session_id=17`, Monza) and **Emilia Romagna Grand Prix** (`session_id=8`, Imola).

Previously, `resolve_race_session` queried sessions ordered by `session_id` and applied broad substring/country matching before exact event and explicit alias resolution. Consequently, `"United States Grand Prix"` could match `"United States"` on `session_id=7` (`Miami Grand Prix`) before reaching `session_id=20`.

---

## 2. Changes Implemented

### 2.1 Shared Normalization & Alias Definitions
- Created `event_aliases.py` (dependency-free module, preventing circular imports between `sessions` routers, `session_service`, `EntityRegistry`, and `QueryPlanner`).
- Implemented `normalize_text` (handling diacritics plus corrupted `\ufffd` replacements such as `S\ufffdo Paulo`) and `strip_gp_suffix`.
- Defined structured stage maps: `KNOWN_CIRCUIT_ALIASES`, `COUNTRY_ALIASES`, and `EXPLICIT_EVENT_ALIASES`.

### 2.2 Multi-Stage `resolve_race_session`
- Updated `resolve_race_session` with strict 5-stage deterministic matching:
  1. **Stage 1 (`exact_event`)**: exact match on normalized `event_name` or `strip_gp_suffix(event_name)`.
  2. **Stage 2 (`event_alias`)**: explicit event aliases (`US GP`, `United States GP`, `São Paulo GP`, `Dutch GP`, `Mexican GP`, `Austrian GP`, `Saudi GP`, `Abu Dhabi GP`, `British GP`, `Emilia Romagna GP`, `Italian GP`, etc.).
  3. **Stage 3 (`circuit_venue`)**: `circuit_name` / `location` / known venue aliases (`COTA`, `Miami`, `Silverstone`, `Monza`, `Imola`, `Spa`, `Suzuka`, `Interlagos`, `Silverstone`, `Marina Bay`, etc.).
  4. **Stage 4 (`country_fallback`)**: `country` / country aliases **only** if earlier stages did not match.
  5. **Ambiguity preservation**: If multiple distinct events match at the winning stage (e.g., bare `"United States"` or `"USA"` across Miami/US/Las Vegas, or bare `"Italy"` across Monza/Imola) or multiple seasons match when `season=None`, returns `status="ambiguous_event"` or `status="ambiguous_season"` with explicit candidate names instead of picking the lowest `session_id`.
- Added read-only `db_path` support via SQLite URI `mode=ro` for isolated unit and adversarial testing without touching production `data/raceintel.db`.

### 2.3 `EntityRegistry`, `IntentClassifier`, and `QueryPlanner` Alignment
- Updated `EntityRegistry` to index events by priority stage (`_exact_event_map`, `_event_alias_stage_map`, `_circuit_alias_map`, `_country_alias_map`), added `resolve_event` and `get_ambiguous_country_aliases`, and guarded fallback alias generation by actual database presence.
- Updated `IntentClassifier.extract_entities` to check exact event names, explicit event aliases, and circuit/venue names in strict priority order *before* host-country ambiguity detection, while guarding lowercase pronoun `"us"` (e.g., `"Tell us..."`) so it is not misread as `"USA"`.
- Updated `QueryPlanner` to forward `registry.db_path` (when non-default) to `resolve_race_session` and convert `ambiguous_event` / `ambiguous_season` session statuses into explicit clarification responses.

---

## 3. Verification

### 3.1 Tests Added
- Added `tests/test_phase_5a.py` (9 test functions) covering:
  - `United States Grand Prix` / `US GP` / `Austin` / `COTA` vs `Miami Grand Prix` / `Las Vegas Grand Prix`
  - Explicit event aliases outranking shared country strings
  - Bare `"United States"` / `"USA"` / `"Italy"` triggering ambiguity clarification when multiple GP events exist in SQLite
  - `Italian Grand Prix` / `Monza` vs `Emilia Romagna Grand Prix` / `Imola`
  - Circuit and venue alias resolution
  - Multi-season (`2024` vs `2025` synthetic temp SQLite DBs) resolution and seasonless ambiguity checks
  - Unknown events and unsupported seasons
  - QueryPlanner + read-only production `ChatService` end-to-end check on `"United States Grand Prix"`

### 3.2 Test Run Results
Command executed:
```powershell
.\venv\Scripts\python.exe -m pytest tests\test_phase_5a.py tests\test_phase3a_structured.py tests\test_phase_4a.py tests\test_phase_4a_adversarial.py tests\test_phase_4b.py tests\test_phase_4c.py tests\test_phase_4d.py -v
```
Result: **`151 passed, 2 warnings in 8.11s`** (`0` failures, `0` skipped, zero external Gemini API calls).

### 3.3 Post-5A File SHA256 Checksums
- `src/raceintel/services/event_aliases.py`: `97526a3408e34876dd5f32063da4d3fa72f3f6fe2623a9f88aa11e847e8a7609`
- `src/raceintel/routing/entity_registry.py`: `7479aad39b48598e76d66cb9a36a8f342921bb05e9e9e761f0ba91f9576ac028`
- `src/raceintel/services/session_service.py`: `418ce8543306fa391c727c5d1e10799890fde4cfdf3437e13a8c712f84c9e58d`
- `src/raceintel/routing/query_planner.py`: `3b0a386a1ed9b19855b1a5e41d15756cdacbaa64587baa4404da89813a447960`
- `src/raceintel/routing/intent_classifier.py`: `e2bc40a2a12a9f2cb45b2dc075fc1aa6183d180ee6ae9731bab8e887ced1c1ab`
- `tests/test_phase_5a.py`: `9507f7e5f10bf0a2d531e75b576fb73c10fe6e21f3481357e206b0b13e28580f`
