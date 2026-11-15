# RaceIntel — Phase 6: Dashboard Development Report

**Repository**: `C:\Users\mehra\OneDrive\Desktop\RaceIntel`  
**Phase**: Phase 6 — Retro Terminal Dashboard Development  
**Status**: Completed & Verified

---

## 1. Initial Architecture Audit Summary

Prior to making changes, the RaceIntel codebase was audited across the frontend, FastAPI backend, analytical modules, database, and dependencies:

- **Previous Frontend**: `app.py` was a 62-line single-page Streamlit chat box sending `POST /chat/` requests to `http://127.0.0.1:8001`. There was no `.streamlit/config.toml`, no multipage navigation, and no visual analytics views.
- **FastAPI Backend (`src/raceintel/api/main.py`)**: Mounted 9 routers (`health`, `sessions`, `drivers`, `constructors`, `races`, `weather`, `pace`, `standings`, `chat`) with CORS enabled. Note: `src/raceintel/api/chat.py` existed as an unmounted legacy module; active chat routing uses `src/raceintel/api/routers/chat.py`.
- **Available Analytical Capabilities**: `src/analytics/` (`pace.py`, `position.py`, `tyre.py`, `weather.py`, `standings.py`, `race_report.py`) and `src/raceintel/services/` already provided deterministic race-level classification, grid-vs-finish deltas, lap consistency, average/best pace, tyre compound usage/stints, weather observation trends, and cumulative season standings. Several of these (`cumulative standings`, `lap consistency`, `compound performance`, `weather temperature/wind series`, and `season driver/constructor profiles`) were not previously exposed over FastAPI.
- **Dependencies & Environment**: Installed in `venv`: `streamlit==1.61.1`, `fastapi==0.140.0`, `uvicorn==0.51.0`, `pandas==2.3.3`, `requests==2.34.2`, `altair==6.2.2`, `matplotlib==3.11.1`. `plotly` was not installed, so Altair was selected for interactive monochrome charts.
- **Data Integrity Baseline**: SQLite (`data/raceintel.db`, SHA256 `61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e`) indexes the 2024 F1 Season (24 race sessions) alongside ChromaDB collection `raceintel_knowledge` (`data/chroma`, 503 documents).

---

## 2. Files Created & Modified

### Created Files
- `.streamlit/config.toml` — Native Streamlit dark monospace configuration (`#17251D` background, `#1E2F25` secondary background, `#D5E8B5` text/primary accent).
- `src/raceintel/api/routers/analytics.py` — Additive, read-only FastAPI `/analytics/*` router exposing season overview, cumulative driver/constructor standings, season progression trajectories, consolidated full race breakdown, and driver/constructor season profiles with JSON-safe `NaN`/`Inf` sanitization.
- `frontend/__init__.py` — Frontend package marker.
- `frontend/theme.py` — Retro Terminal design system (`#17251D` primary background, `#D5E8B5` primary display ink, `#A7B89C` secondary/bezel tone, `#FFFFFF` light text, `0px` square borders, CRT scanline texture, pixel/monospace typography, KPI cards, status badges, error boxes, and Altair chart styling).
- `frontend/api_client.py` — Typed HTTP client (`RaceIntelAPIClient`) keeping SQLite/Chroma/Gemini decoupled from Streamlit and returning safe `(payload, error)` tuples on timeouts, connection failures, HTTP errors, and malformed JSON.
- `frontend/views/__init__.py` — Views package marker.
- `frontend/views/dashboard.py` — `01 // DASHBOARD` view.
- `frontend/views/race_analysis.py` — `02 // RACE ANALYSIS` view.
- `frontend/views/driver_intel.py` — `03 // DRIVER INTELLIGENCE` view.
- `frontend/views/constructor_intel.py` — `04 // CONSTRUCTOR INTELLIGENCE` view.
- `frontend/views/ai_engineer.py` — `05 // AI RACE ENGINEER` view.
- `frontend/views/system_about.py` — `06 // SYSTEM / ABOUT` view.
- `tests/test_phase_6_dashboard.py` — Automated pytest suite covering FastAPI `/analytics/*`, backward compatibility of existing routes, API client failure paths, Retro Terminal theme checks, and headless Streamlit `AppTest` navigation/offline recovery.
- `evaluation/PHASE_6_DASHBOARD_REPORT.md` — This engineering report.

### Modified Files
- `src/raceintel/api/main.py` — Imported and registered `analytics.router` cleanly alongside the 9 existing routers.
- `app.py` — Replaced the minimal 62-line chat prototype with the Retro Terminal multipage console shell, live `/health/` indicator, season selector, sidebar module switcher, and graceful offline error handling.

### Untouched Protected Modules
Zero edits were made to `src/raceintel/api/routers/chat.py`, `src/raceintel/chat/`, `src/raceintel/routing/`, `src/raceintel/retrieval/`, `src/raceintel/services/`, `data/raceintel.db`, or `data/chroma/`.

---

## 3. Features Implemented

- **Retro Terminal UI System**: Nokia Snake-inspired monochrome phosphor console aesthetic (`#17251D`, `#D5E8B5`, `#A7B89C`, `#FFFFFF`), monospace fonts, square corners (`border-radius: 0px`), hard offset shadows, blinking terminal cursor, and themed monochrome Altair visualizations.
- **01 // Dashboard (`frontend/views/dashboard.py`)**: Season KPI strip (indexed races, total laps, latest GP winner, driver & constructor championship leaders), interactive round checkpoint selector with podium/fastest-lap/biggest-mover cards, cumulative Driver & Constructor championship bar charts and tables, Top-5 constructor trajectory chart, selected race Top-10 finishers, and full 24-round race winners matrix.
- **02 // Race Analysis (`frontend/views/race_analysis.py`)**: Grand Prix session selector and 4 analytical tabs backed by `/analytics/race/{session_id}/full`:
  1. *Classification & Movers*: Grid-vs-Finish delta bar chart, constructor points breakdown, full classification table.
  2. *Lap Pace*: Fastest lap per driver, average race pace bar charts, and lap-time consistency (`lap_time_std_dev_seconds`).
  3. *Tyre Strategy*: Stacked tyre compound usage per driver, compound pace summary table, driver stint breakdown.
  4. *Weather*: Air/track temperature, humidity, wind/wet observation KPIs, air & track temperature line chart, and wind speed area profile.
- **03 // Driver Intelligence (`frontend/views/driver_intel.py`)**: Primary driver selector + optional second driver Head-to-Head selector, season KPIs (points, wins, podiums, best finish/grid, avg finish, DNF/NC count, net positions gained), race-by-race points bar chart, inverted finishing-position trend line, full race log table, and H2H points differential + cumulative trajectory comparison.
- **04 // Constructor Intelligence (`frontend/views/constructor_intel.py`)**: Team selector, championship rank & team KPIs (total points, wins, podiums, double-points finishes, lead driver), per-round & cumulative points charts, internal teammate points split & roster table, all-constructors championship trajectory with selected team highlighted, and race-by-race driver log.
- **05 // AI Race Engineer (`frontend/views/ai_engineer.py`)**: Preserves the existing `POST /chat/` RAG + SQL pipeline inside a terminal chat interface with 6 one-click quick telemetry prompts, loading spinner, session chat log, clear-log button, explicit error panels, and optional citation rendering if provided in API JSON.
- **06 // System / About (`frontend/views/system_about.py`)**: Live `/health/` status, SQLite/Chroma corpus diagnostics (`24 races`, `503` documents in `raceintel_knowledge`), active endpoint inventory, explicit data scope disclosures, and verified Phase 5 regression/independent benchmark metrics.

---

## 4. Features Intentionally Not Implemented & Why

1. **Car Speed / Throttle / Brake / Gear Telemetry Traces**: Not implemented because RaceIntel SQLite `laps` only stores lap numbers, lap times, sector times, and tyre metadata (`tyre_compound`, `tyre_age_laps`). High-frequency FastF1 telemetry channels are not persisted in SQLite and were never fabricated.
2. **Live Timing / Real-Time Broadcast Polling**: Not implemented because RaceIntel is an indexed 2024 historical archive (`24` completed race sessions), not a live F1 timing WebSocket feed.
3. **Multi-Season Switching (e.g., 2022–2023)**: The UI season selector is populated with `2024` only because only the 2024 F1 season is currently ingested in `data/raceintel.db`.
4. **Custom PDF/CSV Export & Auth Login Gates**: Omitted to keep the operational surface focused on authentic RaceIntel intelligence without unrequested backend auth/storage complexity.

---

## 5. Verification Results (Observed After Final Code Edits)

### Automated Pytest Suite
- Command: `$env:RACEINTEL_OFFLINE='1'; .\venv\Scripts\python.exe -m pytest -q`
- Result: **311 passed, 22 warnings in 46.54s** (`tests/test_phase_6_dashboard.py` contributed 9 passing tests covering `/analytics/*`, backward compatibility of existing endpoints, `api_client` fault handling, Retro Terminal CSS/Altair config, headless `AppTest` navigation across all 6 pages, AI chat submission/clear, and API-offline graceful degradation).

### Live Server & Frontend Connectivity Verification
Executed headless background `uvicorn raceintel.api.main:app --port 8011` and `streamlit run app.py --server.headless true --server.port 8511` with `RACEINTEL_OFFLINE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` (terminating both cleanly afterward):
- `GET http://127.0.0.1:8011/health/` -> `200` `{"status": "healthy", "database": "connected"}`
- `GET http://127.0.0.1:8011/analytics/overview?season=2024` -> `200` (`total_races=24`, `driver_leader=VER`)
- `GET http://127.0.0.1:8011/analytics/race/13/full` -> `200` (`winner=Lewis Hamilton`)
- `POST http://127.0.0.1:8011/chat/` (`Who won the 2024 British Grand Prix?`) -> `200` (`Lewis Hamilton won the British Grand Prix in 2024.`)
- `GET http://127.0.0.1:8511` -> `200` (`10,951` bytes served)

### Post-Edit Data & AI Regression Integrity Check
- `data/raceintel.db` SHA256: `61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e` (unchanged)
- ChromaDB collection `raceintel_knowledge` (`data/chroma`): `503` documents (unchanged)
- Regression Benchmarks (`evaluation/run_evaluation.py` in-process offline mode):
  - Baseline (`raceintel_eval_2024.json`): **30 / 30 (100.0%)**, `external_api_calls_attempted=0`
  - Evaluation V2 (`raceintel_eval_v2.json`): **75 / 75 (100.0%)**, `external_api_calls_attempted=0`
  - Holdout V1 (`raceintel_holdout_v1.json`): **30 / 30 (100.0%)**, `external_api_calls_attempted=0`

---

## 6. Known Limitations

- **Cold-Start Import Latency (`ChatService`)**: `src/raceintel/api/routers/chat.py` initializes `ChatService()` at import time, which loads `SentenceTransformer("all-MiniLM-L6-v2")` and ChromaDB. During verification on Windows, cold import took **397.17s** without offline HuggingFace flags while attempting hub checks, and **98.7s** with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. Subsequent warm HTTP calls are fast, and Streamlit renders offline error banners cleanly if started before Uvicorn finishes booting.
- **2024 Season Scope**: All analytics dashboards reflect the 2024 F1 calendar (`24` Grand Prix race sessions).
- **Offline Chat Verification**: Automated API/Streamlit verification ran with `RACEINTEL_OFFLINE=1` (testing deterministic SQL and retrieval paths without making paid live Gemini API calls).
- **Backend `/chat/` Schema**: `ChatResponse` returns `{"answer": str}` without structured source arrays; the AI Race Engineer view renders citations automatically if added later, and otherwise displays grounded textual answers cleanly.

---

## 7. Run Instructions

1. **Start the FastAPI Backend** (from `C:\Users\mehra\OneDrive\Desktop\RaceIntel`):
   ```powershell
   $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'
   .\venv\Scripts\uvicorn.exe raceintel.api.main:app --host 127.0.0.1 --port 8001
   ```
   Wait until Uvicorn logs `Application startup complete.` (allow ~1–2 minutes on initial cold load for embeddings). Ensure `GEMINI_API_KEY` is configured in `.env` if live LLM synthesis is desired for open-ended RAG queries, or set `$env:RACEINTEL_OFFLINE='1'` for deterministic offline mode.

2. **Start the Retro Terminal Dashboard** (in a second terminal):
   ```powershell
   .\venv\Scripts\streamlit.exe run app.py
   ```
   (Optional: set `$env:RACEINTEL_API_URL='http://127.0.0.1:<port>'` if running FastAPI on a non-default port.)

---

## 8. Recommended Next Steps (Phase 7 Candidates)

1. **Lazy Initialization / FastAPI Lifespan for `ChatService`**: Defer `SentenceTransformer` + `ChromaDB` loading cleanly (or add warm-up status in `/health/`) so FastAPI binds port `8001` in `<2s` instead of blocking module import for ~98s.
2. **Structured Citations in `ChatResponse`**: Optionally expose `sources` and `route_used` metadata from `ChatService` through `POST /chat/` so the Retro Terminal AI Engineer panel can display clickable document/table attribution badges.
3. **Lap-by-Lap & Stint Chart Expansion**: Expose individual `laps` progression (`lap_number` vs `lap_time_seconds` per selected driver pair) over `/analytics/race/{session_id}/laps` for deeper stint degradation curves.
4. **Multi-Season Ingestion (2025/2026)**: Populate additional seasons in SQLite/Chroma and wire `/sessions/seasons` dynamically into the sidebar `ACTIVE SEASON` selector.
