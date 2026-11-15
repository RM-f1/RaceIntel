# RaceIntel Repository Diagnostic Report

**Timestamp:** 2026-11-14T11:48:00+05:30  
**Repository Path:** `c:\Users\mehra\OneDrive\Desktop\RaceIntel`  

---

## 1. Repository Structure

```text
RaceIntel/
├── .agents/                    # Agent specifications and instructions
├── .github/                    # GitHub actions / workflows
├── .pytest_cache/              # Pytest cache directory
├── .streamlit/                 # Streamlit UI configuration and styling
├── .vscode/                    # VS Code workspace settings
├── data/                       # Primary operational datastore
│   ├── backups/                # Verified safety database backups
│   │   └── raceintel_pre_phase6_1.db
│   ├── cache/                  # FastF1 timing cache directory
│   ├── chroma/                 # ChromaDB persistent vector database
│   │   └── chroma.sqlite3
│   └── raceintel.db            # Primary analytical SQLite database
├── docs/                       # Project documentation and specifications
├── evaluation/                 # Benchmark test sets, RAGAS runs, and phase audit reports
├── frontend/                   # Streamlit Retro Terminal UI views and components
│   ├── components/             # Reusable UI widgets and retro styling
│   └── views/                  # Multi-page dashboard modules (Overview, AI Engineer, etc.)
├── notebooks/                  # Analytical exploration notebooks
├── ragas-venv/                 # Dedicated environment for RAGAS evaluation framework
├── scripts/                    # Maintenance, indexing, and validation utilities
├── src/                        # Core application source code
│   ├── analytics/              # Low-level pace, position, tyre, and weather analytics
│   ├── database/               # SQLAlchemy models (models.py) and connection factory
│   ├── etl/                    # Legacy ETL scripts
│   ├── queries/                # Analytical SQL query definitions
│   └── raceintel/              # Primary RaceIntel modular application
│       ├── analytics/          # Analytical aggregation services
│       ├── api/                # FastAPI backend routers and schemas
│       ├── chat/               # AI Race Engineer chat service, Gemini client, prompts
│       ├── data/               # Reusable Ingestion Engine (schedule, fetcher, validator, persister, ingest)
│       ├── database/           # Session management utilities
│       ├── knowledge/          # Static knowledge assets
│       ├── retrieval/          # ChromaClient, semantic Retriever, SeasonIndexer
│       ├── routing/            # DomainGuard, EntityRegistry, IntentClassifier, QueryPlanner
│       ├── services/           # Business logic services (race, standings, pace, weather, session)
│       └── sync/               # Background Synchronization Worker (worker.py)
├── tests/                      # Pytest automated test suite (319 tests)
├── venv/                       # Primary Python virtual environment
├── app.py                      # Main Streamlit web application entrypoint
├── pytest.ini                  # Pytest configuration
├── requirements.txt            # Application dependencies
└── setup.py                    # RaceIntel package configuration
```

---

## 2. Git Branch & Working-Tree Status

- **Current Branch:** `main`
- **Branch Tracking:** Ahead of `origin/main` by 2 commits
- **Git HEAD Commit:** `2acb2ab47a3abb1b4a5f9c5693a932f23a8023b4`
- **Working-Tree Status:**
  - **Modified Tracked Files (22):**
    - `.gitignore`
    - `app.py`
    - `evaluation/raceintel_eval_results.json`
    - `evaluation/raceintel_ragas_results.json`
    - `evaluation/run_evaluation.py`
    - `evaluation/run_ragas_evaluation.py`
    - `requirements.txt`
    - `scripts/validate_evaluation_set.py`
    - `src/database/models.py`
    - `src/raceintel/api/main.py`
    - `src/raceintel/chat/chat_service.py`
    - `src/raceintel/chat/gemini.py`
    - `src/raceintel/chat/prompts.py`
    - `src/raceintel/retrieval/chroma_client.py`
    - `src/raceintel/retrieval/retriever.py`
    - `src/raceintel/retrieval/season_indexer.py`
    - `src/raceintel/services/pace_service.py`
    - `src/raceintel/services/race_service.py`
    - `src/raceintel/services/session_service.py`
    - `src/raceintel/services/standings_service.py`
    - `src/raceintel/services/weather_service.py`
    - `tests/test_chroma_client.py`
  - **Key Untracked Files & Directories:**
    - `.streamlit/`
    - `data/backups/`
    - `evaluation/` (evaluation manifests and reports: `PHASE_6_1_AUDIT.md`, `PHASE_6_1_INGESTION_REPORT.md`, `PHASE_6_1_SYNC_REPORT.md`, `PHASE_6_1_RAG_REPORT.md`, etc.)
    - `frontend/`
    - `src/raceintel/api/routers/analytics.py`
    - `src/raceintel/data/`
    - `src/raceintel/routing/`
    - `src/raceintel/sync/`
    - `tests/test_phase_6_1_multi_season.py`

---

## 3. Python Version & Virtual Environment

- **Python Version:** `Python 3.14.6`
- **Active Virtual Environment:** `c:\Users\mehra\OneDrive\Desktop\RaceIntel\venv`
- **Python Executable:** `C:\Users\mehra\OneDrive\Desktop\RaceIntel\venv\Scripts\python.exe`
- **Secondary Environment:** `c:\Users\mehra\OneDrive\Desktop\RaceIntel\ragas-venv` (reserved for RAGAS evaluation dependencies)

---

## 4. SQLite Database Location & Table Inventory

- **Database Path:** `data/raceintel.db` (`C:\Users\mehra\OneDrive\Desktop\RaceIntel\data\raceintel.db`)
- **Database Size:** `4,366,336` bytes
- **Integrity Status:** `PRAGMA integrity_check` -> `ok`
- **Pre-Ingestion Backup:** `data/backups/raceintel_pre_phase6_1.db` (SHA256: `61b1a5b2917eb38d47f2fb964328fd08b521b6d33441a275af2468dcd73fbb6e`, `1,966,080` bytes)

### Table Schema & Row Counts (11 Tables Total)

| # | Table Name | Row Count | Primary Purpose |
|---|---|---:|---|
| 1 | `seasons` | 5 | Championship seasons registered (`2022, 2023, 2024, 2025, 2026`) |
| 2 | `constructors` | 14 | Canonical constructor entities |
| 3 | `etl_runs` | 0 | Legacy ETL execution tracking table |
| 4 | `events` | 115 | Grand Prix championship rounds across 5 seasons |
| 5 | `drivers` | 34 | Drivers on the F1 grid across 2022–2026 |
| 6 | `sessions` | 115 | Session records linked to events |
| 7 | `race_results` | 2,278 | Classified race finishes, positions, and points |
| 8 | `laps` | 50,181 | Timing laps (`26,604` for 2024; `23,577` for 2022) |
| 9 | `weather_observations` | 7,333 | Track/air weather telemetry (`3,690` for 2024; `3,643` for 2022) |
| 10 | `session_sync_status` | 115 | Ingestion lifecycle state log (`COMPLETED, PARTIAL, SKIPPED, FAILED`) |
| 11 | `sqlite_sequence` | 1 | Internal SQLite autoincrement sequence tracker |

---

## 5. ChromaDB Collections & Document Counts

- **Chroma Storage Path:** `data/chroma` (`C:\Users\mehra\OneDrive\Desktop\RaceIntel\data\chroma`)
- **Active Collections:** 1 (`raceintel_knowledge`)
- **Total Document Count:** `2,393`

### Document Breakdown by Championship Season

| Season | Total Documents | Race Reports | Driver Reports | Ingestion & Integrity Status |
|---|---:|---:|---:|---|
| **2022** | 462 | 22 | 440 | Completed historical season |
| **2023** | 462 | 22 | 440 | Completed historical season |
| **2024** | 506 | 24 | 482 | Original 503 baseline documents 100% preserved |
| **2025** | 503 | 24 | 479 | Completed historical season |
| **2026** | 460 | 20 | 440 | Completed Rounds 1–20; Upcoming Rounds 21–23 strictly omitted |
| **Total** | **2,393** | **112** | **2,281** | Vector store intact, 0 ungrounded/fabricated records |
