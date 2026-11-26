# RaceIntel — Phase 6.1: Architecture Audit Report

**Date**: 2026-11-12  
**Target Repository**: `<repo>`  
**Phase**: Phase 6.1 — Multi-Season Data Engine + Automatic/Manual Synchronization  

---

## 1. Executive Summary

RaceIntel is currently structured as a 2024-centric Formula 1 race intelligence platform spanning an SQLite analytical database, a ChromaDB vector store (`raceintel_knowledge`), a FastAPI backend with structured SQL services, an AI Race Engineer combining RAG and deterministic SQL routing, and a Streamlit Retro Terminal race control dashboard.

This audit evaluates the codebase prior to implementing Phase 6.1, which expands RaceIntel into a multi-season intelligence system supporting **2022, 2023, 2024, 2025, and 2026**.

---

## 2. SQLite Database Architecture & Schema Audit

### 2.1 Schema Definition & Tables
SQLite database path: `data/raceintel.db` (current SHA256: `61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e`, size: `1,966,080` bytes).

The database contains 9 tables defined in `src/database/models.py`:

| Table | Primary Key | Foreign Keys | Unique Constraints & Indexes | Current Rows |
|---|---|---|---|---|
| `seasons` | `season_id` (INTEGER AUTOINCREMENT) | None | Unique index on `season_year` | 1 (`2024`) |
| `events` | `event_id` (INTEGER AUTOINCREMENT) | `season_id` -> `seasons.season_id` | Index on `event_name` | 24 |
| `sessions` | `session_id` (INTEGER AUTOINCREMENT) | `event_id` -> `events.event_id` | Index on `session_type` | 24 |
| `constructors` | `constructor_id` (INTEGER AUTOINCREMENT) | None | Unique constraint on `constructor_name` | 10 |
| `drivers` | `driver_id` (INTEGER AUTOINCREMENT) | `constructor_id` -> `constructors.constructor_id` | Unique index on `driver_code` | 24 |
| `race_results` | `race_result_id` (INTEGER AUTOINCREMENT) | `session_id`, `driver_id`, `constructor_id` | None explicit | 479 |
| `laps` | `lap_id` (INTEGER AUTOINCREMENT) | `session_id`, `driver_id` | Unique constraint `(session_id, driver_id, lap_number)`, Index on `lap_number` | 26,604 |
| `weather_observations` | `weather_observation_id` (INTEGER AUTOINCREMENT) | `session_id` | None explicit | 3,690 |
| `etl_runs` | `etl_run_id` (INTEGER AUTOINCREMENT) | None | None | 0 (unpopulated audit table) |

### 2.2 Relational Model & Multi-Season Observations
1. **Drivers & Constructor Coupling**: `drivers.constructor_id` represents a single constructor per driver. In Formula 1 across 2022–2026, drivers switch teams (e.g., Lewis Hamilton moving from Mercedes to Ferrari in 2025; Pierre Gasly, Fernando Alonso, Daniel Ricciardo). In `race_results`, `constructor_id` is recorded per race result, which correctly preserves historical team affiliation for every race. However, `drivers.constructor_id` must be treated as the *current/latest* team or made nullable without breaking single-table lookups.
2. **Session Identifiers**: `sessions.session_id` is an auto-incrementing integer. Existing queries join `sessions s JOIN events e ON s.event_id = e.event_id JOIN seasons sn ON e.season_id = sn.season_id`. To ensure idempotency and prevent duplicate sessions, unique constraints or upsert logic must check `(event_id, session_type)` or `(season_year, round_number, session_type)`.
3. **Laps Table**: Has a strict unique constraint on `(session_id, driver_id, lap_number)`. This protects against duplicate lap insertions on re-ingestion.
4. **ETL Runs Table**: The existing model defines `etl_runs` (`season_year`, `event_name`, `session_type`, `status`, `records_loaded`, `error_message`, `started_at_utc`, `completed_at_utc`), but it has never been written to (0 rows). Phase 6.1 should upgrade and utilize this table to track ingestion status, session lifecycle (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `PARTIAL`, `FAILED`, `SKIPPED`), and timestamps.

### 2.3 2024 Column Coverage & Grounded Factuality
In SQLite `laps`:
- Total laps: `26,604`
- Non-null `lap_time_seconds`: `26,381`
- `track_position`: `26,578`
- `tyre_compound`: `26,604`
- `sector_1_time_seconds`, `sector_2_time_seconds`, `sector_3_time_seconds`: `0` (null in current DB)
- `is_pit_out_lap`, `is_personal_best`: `0` (defaulted to False)
- High-frequency car telemetry (speed traces, throttle/brake channels, RPM) is **not** stored in SQLite.

---

## 3. FastF1 Multi-Season Support Audit (2022–2026)

We executed live diagnostic probes against FastF1 `3.8.3` across 2022, 2023, 2024, 2025, and 2026. The findings are critical:

| Season | Calendar Events | Status / Availability | Results (`session.results`) | Laps (`session.laps`) | Weather (`weather_data`) |
|---|---|---|---|---|---|
| **2022** | 22 championship rounds | Completed historical | Fully available (20 drivers) | Fully available (~800–1150 laps/race) | Fully available (~150 obs/race) |
| **2023** | 22 championship rounds | Completed historical | Fully available (20 drivers) | Live timing stream unavailable (`DataNotLoadedError`) | Live timing stream unavailable (`DataNotLoadedError`) |
| **2024** | 24 championship rounds | Completed historical | Fully available (in SQLite) | Fully available (in SQLite) | Fully available (in SQLite) |
| **2025** | 24 championship rounds | Completed historical | Fully available (20 drivers) | Live timing stream unavailable (`DataNotLoadedError`) | Live timing stream unavailable (`DataNotLoadedError`) |
| **2026** | 23 championship rounds | In-progress season (as of 2026-11-12) | Rounds 1–20 completed (22 drivers); Rounds 21–23 upcoming/scheduled | Live timing stream unavailable (`DataNotLoadedError`) | Live timing stream unavailable (`DataNotLoadedError`) |

### Critical Technical Findings:
1. **Live Timing Mirror Deprecation**: For 2023, 2025, and 2026, FastF1's live-timing stream endpoint (`https://livetiming.formula1.com/static/.../WeatherData.jsonStream`) returns HTTP 401 and the mirror (`livetiming-mirror.fastf1.dev`) returns HTTP 404. FastF1 raises `DataNotLoadedError` when accessing `session.laps` or `session.weather_data` if timing streams are missing.
2. **Result Classifications Are Solid**: In all seasons (2022, 2023, 2024, 2025, and completed rounds 1–20 of 2026), `session.results` is completely populated with drivers, constructors, positions, points, grid positions, and classified status.
3. **2026 Upcoming Events**: Rounds 21 (Las Vegas, Nov 21), 22 (Qatar, Nov 29), and 23 (Abu Dhabi, Dec 06) return 0 results and must be classified as `SCHEDULED` / `UPCOMING` rather than completed races.
4. **Graceful Fallback & Honest Logging**: Ingestion must gracefully handle missing lap/weather streams when FastF1 only provides results, marking the session `COMPLETED` for results and `PARTIAL` for telemetry without throwing fatal exceptions or corrupting the database.

---

## 4. ChromaDB & RAG Architecture Audit

- Collection Name: `raceintel_knowledge` (persist directory: `data/chroma`)
- Total Documents: `503`
- Current Document Types:
  - `race_report`: 24 documents (one per 2024 round, ID pattern: `2024_{round}`)
  - `driver_report`: 479 documents (one per driver per 2024 round, ID pattern: `2024_{round}_{driver_name}`)
- Metadata Schema: `["country", "document_type", "driver", "race_name", "round", "season", "team"]`
- Ingestion Scripts:
  - `scripts/index_races.py`: Hard-coded to 2024 with a hard-coded dictionary `ROUND_NUMBERS_2024`, and invokes `client.reset_collection()`, which destroys the index on rebuild.
  - `src/raceintel/retrieval/season_indexer.py`: Incomplete placeholder class.
- RAG Retriever (`src/raceintel/retrieval/retriever.py`):
  - Already supports season extraction and building Chroma filters `{"season": target_season}` when present.
  - However, several fallback routines and domain guard messages default to 2024 text.

---

## 5. Hardcoded 2024 Assumptions Audit

A repository-wide search identified explicit 2024 assumptions across backend, routing, and frontend:

1. **`app.py`**:
   - Line 72: `season = st.selectbox("ACTIVE SEASON", options=[2024], index=0, key="global_season")`
2. **`frontend/views/ai_engineer.py`**:
   - Lines 16–21: Example prompts refer exclusively to 2024 races.
3. **`src/raceintel/routing/domain_guard.py`**:
   - Rejection strings explicitly mention "Formula 1 2024 calendar".
   - `OUT_OF_CALENDAR_F1_VENUES`: Discontinued venues must be checked against the *requested* season's calendar rather than 2024 alone.
4. **`src/raceintel/routing/intent_classifier.py`**:
   - Lines 90, 130–135: Default season fallback is `2024`.
5. **`src/raceintel/routing/query_planner.py`**:
   - Line 73: `season = entities.get("season", 2024)`
   - Error messages: "That event is not part of the Formula 1 2024 calendar."
6. **`src/raceintel/chat/chat_service.py`**:
   - Lines 754, 862, 912, 954, 962, 1062, 1078: Default season `2024` and explicit 2024 error strings.
7. **`src/raceintel/services/*.py`**:
   - Functions in `race_service.py`, `standings_service.py`, `pace_service.py`, and `weather_service.py` default `season: int = 2024`.
8. **`src/raceintel/api/routers/*.py`**:
   - FastAPI routers (`sessions.py`, `analytics.py`, `standings.py`) use `season: int = Query(default=2024)`. These parameters should default to the latest season or accept 2022–2026 dynamically.

---

## 6. Proposed Implementation Architecture

### 6.1 Database Safety & Migration
1. Verified backup of `data/raceintel.db` saved to `data/backups/raceintel_pre_phase6_1.db` with recorded SHA256.
2. Upgrade `etl_runs` table or add an `ingestion_status` table to track session synchronization status, timestamps, and row counts.
3. Keep `drivers` table records unique by `driver_code`, updating `constructor_id` to the latest observed team, while `race_results` records the exact historical constructor per race.
4. Wrap all writes in transactional sessions with atomic rollback on failure.

### 6.2 Reusable Ingestion Architecture (`raceintel.data.ingest`)
Implement a unified package `src/raceintel/data/`:
- `schedule.py` — Discovers event schedules for any season (2022–2026), distinguishing completed vs upcoming events.
- `fetcher.py` — Fetches FastF1 session data with adaptive degradation (results, laps, weather, pit stops).
- `validator.py` — Validates result schemas, finish positions, driver codes, points, and integrity before persistence.
- `persister.py` — Idempotent transactional loader inserting/updating seasons, events, sessions, constructors, drivers, race results, laps, weather, and sync status without duplicate records.
- `status.py` — Manages per-session lifecycle (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `PARTIAL`, `FAILED`, `SKIPPED`) and execution locks.
- `cli.py` (`python -m raceintel.data.ingest`) — Unified CLI supporting `--season`, `--round`, `--incremental`, `--force-refresh`, `--dry-run`, `--status`.

### 6.3 Background Synchronization Worker
- `src/raceintel/sync/worker.py` — Dedicated background synchronization worker.
- Single-worker execution lock via a persistent file lock or SQLite status.
- Configurable interval: daily for active season (2026), weekly for historical/off-season.
- Graceful termination via SIGINT/SIGTERM handlers and clean lock release.

### 6.4 Manual Synchronization & Dashboard Integration
- Secure admin API endpoint: `POST /analytics/sync` requiring an authorization token (`X-RaceIntel-Admin-Key` or configured admin secret).
- In Streamlit sidebar & System/About view: Add season sync controls, progress bar, last sync timestamp, and status tables.
- Prevent unauthenticated arbitrary sync triggers.

### 6.5 Incremental ChromaDB RAG Knowledge Base
- Upgrade `RaceDocumentGenerator` and `SeasonIndexer` to generate race and driver reports for any season.
- Use deterministic stable document IDs: `{season}_{round}` for race reports, `{season}_{round}_{driver_code}` for driver summaries.
- Check existing Chroma document IDs and upsert only missing/updated documents. Zero deletion of 2024 documents.

### 6.6 Multi-Season Analytics & AI Race Engineer
- Make `DomainGuard`, `IntentClassifier`, and `QueryPlanner` season-dynamic based on `EntityRegistry.supported_seasons`.
- Update dashboard season selector to `[2026, 2025, 2024, 2023, 2022]`.
- Provide upcoming race countdown/indicators for uncompleted rounds in 2026.
