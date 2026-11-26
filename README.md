# RaceIntel

RaceIntel is an AI-powered Formula 1 race intelligence platform that combines FastF1 data ingestion, multi-season SQLite analytics, vector-based retrieval and LLM-assisted question answering, with a FastAPI backend and Streamlit interface.
![Python Tests](https://github.com/RM-f1/RaceIntel/actions/workflows/python-tests.yml/badge.svg)
Local suite: 457 passed (full database) or 447 passed, 10 skipped (fixture-only); GitHub Actions execution has not yet been verified.

## Features

- **Multi-Season FastF1 Ingestion**: Automated data ingestion pipelines across Formula 1 championship seasons 2022–2026, including Sprint Shootouts and Sprint Races, with atomic SQLite persistence and session synchronization status tracking.
- **Deterministic SQL Analytics**: Zero-hallucination SQL services querying multi-season race classifications, driver and constructor championship standings, weather telemetry, lap pace distributions, and head-to-head driver race comparisons.
- **Vector Retrieval via ChromaDB**: Semantic search over structured race reports and driver performance documents stored in persistent ChromaDB collections, embedded using local SentenceTransformers (`all-MiniLM-L6-v2`).
- **Intent Routing & Domain Guard**: Rule-based intent classification and query planning that routes analytical questions directly to deterministic SQL engines, semantic RAG pipelines, or rapid out-of-domain rejections.
- **Chat Orchestration**: Integrated `ChatService` managing entity resolution, circuit/event alias disambiguation, question routing, ambiguity handling, and generative answer synthesis.
- **Analytics Dashboard**: Modular retro-terminal Streamlit frontend comprising 6 specialized consoles: Dashboard Overview, Race Analysis, Driver Intelligence, Constructor Intelligence, AI Race Engineer, and System / About.
- **Pit-Window & Degradation Analytics**: Pre-fitted within-stint tyre degradation models (`degradation v2`), circuit-specific green-flag median pit-loss estimates, empirical P95 stint-length caps, and a conditional 1-stop pit-window estimator (`GET /analytics/pit-window`).
- **Sync Worker Engine**: Background synchronization process featuring atomic lockfiles, process lifecycle verification via process creation timestamps and command-line checks, and safe graceful termination.
- **Comprehensive Test Suite**: 457 automated unit, integration, and regression tests validating offline operation, chronology integrity, API contracts, and worker termination safety.

## Architecture

The diagram below outlines the runtime request lifecycle across user interfaces, API routing, deterministic SQL execution, vector retrieval, and generative answer synthesis:

```mermaid
flowchart TD
    User([User]) -->|Browser| Streamlit[Streamlit Frontend :8501]
    Streamlit -->|HTTP POST /chat| FastAPI[FastAPI Backend /chat :8001]
    FastAPI --> ChatService[ChatService]
    ChatService --> DomainGuard{Domain Guard}
    DomainGuard -->|Out of Domain| Reject[Domain Rejection Answer]
    DomainGuard -->|In Domain| Planner[Intent Classification & Query Planning]
    Planner -->|Structured Factual Intent| SQL[SQL Analytics Services]
    SQL --> SQLite[(SQLite Database\ndata/raceintel.db)]
    Planner -->|Qualitative / Synthesis Intent| Retriever[ChromaDB Retriever]
    Retriever --> ChromaDB[(ChromaDB Knowledge Base\ndata/chroma/)]
    SQL --> Answer[Answer Formatter]
    Retriever --> Gemini[Gemini LLM / Offline Mock]
    Gemini --> Answer
    Reject --> FastAPI
    Answer --> FastAPI
    FastAPI --> Streamlit
    Streamlit --> User
```

## Quickstart

### Prerequisites
- Python 3.11 to 3.14 (Python 3.14 recommended; Python 3.10 is incompatible with pinned dependencies in requirements.txt such as `contourpy==1.3.3`)
- Git

### 1. Clone Repository & Setup Environment

#### Windows PowerShell
```powershell
git clone https://github.com/RM-f1/RaceIntel.git
cd RaceIntel
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

#### macOS / Linux
```bash
git clone https://github.com/RM-f1/RaceIntel.git
cd RaceIntel
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### 2. Environment Configuration

RaceIntel is fully functional offline without an initial `.env` file. Built-in defaults set `DATABASE_URL` to `sqlite:///data/raceintel.db`, and `GEMINI_API_KEY` defaults to `None` (offline fallback mode). **No `.env` file is required to run offline tests or explore the codebase.**

To customize settings, run administrative data syncs, or enable live Gemini LLM answer generation, copy the example configuration:

#### Windows PowerShell
```powershell
Copy-Item .env.example .env
```

#### macOS / Linux
```bash
cp .env.example .env
```

Configure the environment variables in `.env`:
```ini
# Path to local SQLite database (Optional; defaults to sqlite:///data/raceintel.db; works offline)
DATABASE_URL=sqlite:///data/raceintel.db

# Admin API authorization secret (Required for POST /api/v1/analytics/sync; fail-closed when unset; works offline)
RACEINTEL_ADMIN_KEY=your_admin_secret_here

# Google Gemini API Key (Optional; required only for live generative chat)
# When unset, empty, or when RACEINTEL_OFFLINE=1 is set, the system operates in offline mock mode.
GEMINI_API_KEY=your_gemini_api_key_here

# FastAPI backend base URL for Streamlit frontend (Optional; defaults to http://127.0.0.1:8001; works offline)
RACEINTEL_API_URL=http://127.0.0.1:8001
```

| Variable | Required | Offline Capable | Purpose |
|---|---|---|---|
| `DATABASE_URL` | Optional | Yes | Database connection string for SQLite persistence (defaults to `sqlite:///data/raceintel.db`). |
| `RACEINTEL_ADMIN_KEY` | Optional (Required to trigger sync) | Yes | Authenticates admin sync endpoints with fail-closed checks (`POST /api/v1/analytics/sync`). |
| `GEMINI_API_KEY` | Optional | **No** (Needs Key) | Powers live open-ended RAG synthesis through Google GenAI. When absent, offline deterministic mock is used. |
| `RACEINTEL_API_URL` | Optional | Yes | Backend target URL consumed by Streamlit `RaceIntelAPIClient` (defaults to `http://127.0.0.1:8001`). |

### 3. Build the Database (`data/raceintel.db`)

RaceIntel relies on a local SQLite database constructed from FastF1 session data. Build it from scratch:

1. **Initialize Database Schema** (Creates tables, views, and indexes):
   ```bash
   python -c "from database.schema import create_database; create_database()"
   ```
   *(Works offline; creates `data/raceintel.db`)*

2. **Ingest Championship Seasons**:
   ```bash
   # Ingest 2024 season (recommended baseline, 24 rounds + sprints)
   python -m raceintel.data.ingest --season 2024

   # Optionally ingest additional seasons (supports 2022, 2023, 2024, 2025, 2026)
   python -m raceintel.data.ingest --season 2023
   ```
   - **FastF1 Cache Location**: Raw telemetry and timing data downloaded from FastF1 are cached in `data/cache/`.
   - **Ingestion Duration**: Ingestion duration depends on network download speed and whether sessions are already cached locally in `data/cache/`.
   - **Key Dependency**: FastF1 ingestion requires internet access for initial download, but **does NOT require a Gemini API key**.

### 4. Build the ChromaDB Knowledge Base (`data/chroma/`)

Index structured race reports and driver performance summaries into the vector database:

```bash
# Index documents for all seasons currently in SQLite
python -m raceintel.retrieval.season_indexer --all-seasons

# Or index a single season
python -m raceintel.retrieval.season_indexer --season 2024
```
- **Embedding Model**: Chroma uses SentenceTransformers `all-MiniLM-L6-v2` locally.
- **Storage**: Vector data is stored in `data/chroma/`.
- **Key Dependency**: Completely offline; **does NOT require a Gemini API key**.

### 5. Start the Services

#### Terminal 1 — Start the FastAPI Backend:
```bash
uvicorn raceintel.api.main:app --port 8001
```
The backend initializes REST API endpoints at `http://127.0.0.1:8001` (interactive OpenAPI documentation available at `http://127.0.0.1:8001/docs`).

#### Terminal 2 — Start the Streamlit Dashboard:
```bash
streamlit run app.py
```
Open your browser to `http://localhost:8501`. The retro terminal interface includes:
- `01 // DASHBOARD`: Overall championship metrics, event schedule, and sync statuses.
- `02 // RACE ANALYSIS`: Race telemetry, lap times, finishing positions, and weather.
- `03 // DRIVER INTELLIGENCE`: Head-to-head metrics, driver progression, and career statistics.
- `04 // CONSTRUCTOR INTELLIGENCE`: Constructor points progression and teammate comparisons.
- `05 // AI RACE ENGINEER`: Natural-language chat interface for deterministic SQL queries and RAG synthesis.
- `06 // SYSTEM / ABOUT`: Health check statuses, sync worker controls, and database metrics.

## Running Tests

Execute the complete test suite using pytest:

```bash
pytest -p no:cacheprovider
```
or
```bash
python -m pytest -p no:cacheprovider
```

- **Test Suite Status**:
  - **Full local suite (with full database)**: **457 passed, 22 warnings** (`pytest -q`).
  - **Fixture-only local suite (without full database)**: **447 passed, 10 skipped, 22 warnings**.
  - **GitHub Actions CI**: Execution has not yet been verified.
- **Offline Guarantee**: The test suite executes **100% offline** with zero external network or Gemini API calls. External LLM requests are intercepted by deterministic offline mock clients (`GeminiClient._generate_mock_response`), SQLite operations use test database sandboxes or atomic rollbacks, and no network traffic is generated.
- **Database Dependency & Skip Behavior**: Database resolution (`resolve_database_path()` in [`src/database/connection.py`](src/database/connection.py)) honors `RACEINTEL_DB_PATH` first; if no explicit path is supplied, it prefers the full local database (`data/raceintel.db`) when present and non-empty, falling back to the seeded fixture database (`tests/fixtures/ci.db`). In [`tests/conftest.py`](tests/conftest.py), tests requiring a populated database are marked `@pytest.mark.requires_data` (skipped only if neither the full database nor `tests/fixtures/ci.db` is available), while tests requiring the complete five-season (`2022`–`2026`) database are marked `@pytest.mark.requires_full_data`. Under fixture-only execution, 447 tests run and 10 tests requiring the full five-season database are skipped; under full local execution, all 457 tests pass.

## Data and Provenance

- **Data Source**: FastF1 library fetching timing data, telemetry feeds, weather logs, and classifications directly from Formula 1 live timing archives.
- **Seasons Supported**: 2022, 2023, 2024, 2025, and 2026 (including Sprint formats).
- **Data Directory Storage**: All database files, vector collections, and raw FastF1 caches (`data/raceintel.db`, `data/chroma/`, `data/cache/`) are strictly gitignored to preserve clean version control. They are generated locally through the schema initialization and ingestion commands.
- **2024 Chronology Bug & Verification**:
  During multi-season scaling, an event numbering discrepancy occurred where the 2024 British Grand Prix was initially stored at Round 1 (from Phase 1 exploration), shifting Bahrain through Austria (Rounds 1–11) one round later in sequential ingestion order.
  - *Repair*: Implemented in `scripts/reconcile_chronology.py`. Exactly 21 metadata records (9 in `events` and 12 in `session_sync_status`, detailed in `evaluation/chronology_reconciliation_report.json`) were corrected to align with the official FastF1 2024 schedule.
  - *Verification*: Verified that all 24 rounds in `events` and `session_sync_status` match the FastF1 schedule exactly (Round 1 Bahrain through Round 24 Abu Dhabi), SQLite foreign keys (`PRAGMA foreign_key_check`) and database integrity (`PRAGMA integrity_check`) report zero violations, and running `python scripts/reconcile_chronology.py` in dry-run mode proposes **0 changes**.
  - *Source Consistency*: Note that this verification compares the SQLite database against FastF1's schedule, which also serves as the ingestion source.

## Evaluation

### Project-Authored Benchmark V2

RaceIntel's analytical accuracy is benchmarked against a frozen, project-authored evaluation protocol documented in [`evaluation/frozen_manifest_2026-11-15.json`](evaluation/frozen_manifest_2026-11-15.json):

- **Dataset**: [`evaluation/raceintel_independent_v2.json`](evaluation/raceintel_independent_v2.json), comprising **80 project-authored questions** across 11 analytical categories. The question set is project-authored rather than from an independent third party.
- **Scorer**: [`evaluation/run_independent_v2.py`](evaluation/run_independent_v2.py). The scoring harness was revised after inspecting earlier benchmark results to enforce strict clause co-occurrence matching (entity + position/metric in the same clause), exact position boundary guards (`P1` cannot match `P10`), and multi-entity RAG completeness metrics (`rag_complete`), unit-tested via `tests/test_phase_5d_evaluator.py`.
- **Execution Mode**: Evaluated strictly **offline** with **0 live Gemini calls attempted**. RAG answers were generated using deterministic mock extraction.
- **Benchmark Run Details**: Executed on **2026-11-15** on git commit `facd6ae` against the multi-season SQLite database (SHA256: `ac94af6a53f6509eca7022ef70b549e31018283bbc3bd2270940d7d0580eacd5`) and persistent Chroma vector store. Results are saved in [`evaluation/raceintel_independent_v2_results_2026-11-15.json`](evaluation/raceintel_independent_v2_results_2026-11-15.json). The SQLite database and Chroma collections are not tracked in the git repository, so this benchmark score is reproducible only when evaluated against a database built to the same state.
- **Benchmark Results**:
  - **Overall Answer Accuracy**: **57 / 80 (71.2%)**
  - **Entity Resolution**: **24 / 24 (100.0%)**
  - **Event & Season Resolution**: **71 / 71 (100.0%)**
  - **RAG Retrieval Source Hit Rate**: **9 / 9 (100.0%)**
  - **RAG Answerable Complete Accuracy**: **8 / 9 (88.9%)**
  - **False Abstention Rate**: **0 / 67 (0.0%)**
  - **Category Breakdown**:
    - `weather_and_conditions`: 8/8 (100.0%)
    - `rag_race_reports_and_metadata`: 8/9 (88.9%)
    - `tyres_positions_and_classification`: 7/8 (87.5%)
    - `ambiguous_or_underspecified`: 4/5 (80.0%)
    - `driver_standings_and_points`: 7/9 (77.8%)
    - `pace_and_fastest_laps`: 6/8 (75.0%)
    - `domain_rejection`: 3/4 (75.0%)
    - `race_results_and_winners`: 5/9 (55.6%)
    - `constructor_standings_and_points`: 4/8 (50.0%)
    - `multi_entity_comparisons`: 4/8 (50.0%)
    - `unanswerable_in_domain`: 1/4 (25.0%)

### Analysis of the 23 Failures

Of the 23 failed evaluation questions:
- **5 failures (`indv2_010`, `indv2_020`, `indv2_051`, `indv2_052`, `indv2_053`) are stale benchmark expectations**: The benchmark dataset expects race-only championship points, whereas the engine was upgraded in Phase 6.2.2 to return official championship totals including Sprint points. For example, Leclerc at Monaco: 138 pts (including Sprint points) vs 126 race-only points; Verstappen after Austria: 237 pts vs 229 race-only points; McLaren after Austria: 268 pts vs 254 race-only points.
- **8 failures are paraphrase-routing failures falling back to RAG**: Complex natural language phrasings that did not match structured SQL intent patterns fell back to the RAG retriever, which in offline mode returns deterministic mock answers rather than computing dynamic aggregates.
- **10 failures are edge cases**: Complex multi-entity comparisons, ambiguous phrasing edge cases, and in-domain unanswerable calibration boundaries.

### Evaluation Comparability Note
Earlier development phases recorded higher figures (e.g. 100% on Baseline 30, Eval V2 75, and Holdout 30). **These earlier scores are not comparable to Benchmark V2**:
1. Earlier benchmarks evaluated known reference sets or permitted looser substring matching rules.
2. The benchmark question set is project-authored rather than from an external independent party, and the scorer was revised after inspecting earlier benchmark failures.
3. Offline benchmark testing measures deterministic SQL execution, query routing, entity extraction, and RAG retrieval completeness, but **does not measure live Gemini LLM natural language generation quality**.

Full evaluation run records and methodology audits are preserved in [`evaluation/`](evaluation/).

## Pit-Window & Degradation Analytics

RaceIntel includes a conditional 1-stop pit-window estimator backed by pre-fitted season and circuit artifacts ([`artifacts/raceintel_artifacts.json`](artifacts/raceintel_artifacts.json), generated via `scripts/build_artifacts.py` and loaded by `raceintel.analytics.artifacts.load_artifacts`).

### Methodology & Scope

- **Fuel-adjusted net degradation proxy under the assumed fuel model.** Within-stint net pace trends (`degradation v2`) are demeaned within each `(race, driver, stint)` with clustered standard errors (`slope`, `se`, `n`). The adjusted slope `w_c(phi) = net_slope_c + phi` (where `phi` (`fuel_effect`) is the assumed global linear fuel-burn pace improvement in seconds per lap) is only a fuel-adjusted net degradation proxy under the assumed fuel model; track evolution remains included in `net_slope_c`, and pure tyre wear is not isolated.
- **Conditional 1-Stop Objective**: For race distance `N = total_laps` and a pit stop after lap `L` on a supplied `compound_1 → compound_2` sequence, the estimator minimizes cumulative stint degradation `D_1(L) + D_2(L)` over feasible integer pit laps `L ∈ [max(1, N - floor(cap_2)), min(N - 1, floor(cap_1))]`, where `cap_1` and `cap_2` are empirical 95th-percentile stint lengths (`stint_p95`).
- **Key Assumptions**: Global linear fuel progression (invariant to `L` in total), constant circuit median green-flag pit loss (`pit_loss`), no lap-0 base-pace offsets between compounds, and empirical P95 stint caps rather than physical tyre-life limits.
- **Explicit Limitations**:
  - Traffic and overtaking effects are not modelled.
  - Safety-car and virtual-safety-car effects are not modelled.
  - Undercut and overcut effects are not modelled.
  - Track evolution is not separated from tyre wear.
  - Linear within-stint modelling can underestimate tyre-performance cliffs.
  - Alternative stop counts and compound sequences are not compared.

### API Endpoint: `GET /analytics/pit-window`

Defined in [`src/raceintel/api/routers/analytics.py`](src/raceintel/api/routers/analytics.py) and implemented in [`src/raceintel/analytics/pit_window.py`](src/raceintel/analytics/pit_window.py):

| Parameter | Type | Required | Default | Constraints / Description |
|---|---|---|---|---|
| `race` | `string` | Yes | — | Circuit / Grand Prix name (`min_length=1`, e.g., `"Bahrain Grand Prix"`). |
| `total_laps` | `integer` | Yes | — | Total race distance in laps (`ge=2`). |
| `season` | `integer` | No | `2024` | Season year used to look up degradation, stint caps, and pit loss. |
| `compound_1` | `string` | No | `"SOFT"` | Stint 1 dry compound (`min_length=1`). |
| `compound_2` | `string` | No | `"HARD"` | Stint 2 dry compound (`min_length=1`). |
| `fuel_effect` | `float` | No | `0.05` | Assumed global fuel effect in s/lap (`ge=0.0`). |
| `window_tolerance_s` | `float` | No | `0.5` | Allowable degradation-cost delta above the constrained minimum in seconds (`ge=0.0`). |

### Example: 2024 Bahrain Grand Prix (`SOFT` → `HARD`, 57 Laps)

Using the 2024 artifacts (`SOFT` net slope `0.02588` s/lap, P95 cap `24` laps; `HARD` net slope `-0.020572` s/lap, P95 cap `45` laps; median pit loss `23.999` s across `40` stops; feasible 1-stop pit-lap range `12–24`):

- **Constrained Optimum**: At the default `fuel_effect=0.05`, **lap 16 is the constrained optimum for the specified `SOFT → HARD` one-stop sequence, not the globally optimal race strategy** (the model evaluates only the supplied 1-stop compound sequence and does not select optimal compounds or compare 0-stop vs. 1-stop vs. 2-stop strategies).
- **Tolerance Window**: **Laps 14–19 are within the 0.5-second tolerance** (`window_tolerance_s=0.5`), forming the primary pit window `[14, 19]`.
- **Fuel-Effect Sensitivity** (`0.03`, `0.05`, `0.07` s/lap):
  - Fuel effect `0.03`: optimum lap `12` (cap-constrained by `stint_2_cap`; unconstrained optimum lap `9`, window `12–13`).
  - Fuel effect `0.05`: optimum lap `16` (window `14–19`).
  - Fuel effect `0.07`: optimum lap `20` (window `17–22`).

## Limitations and Known Issues

- **Not a Full Race Strategy Simulator**: While RaceIntel provides a conditional 1-stop pit-window estimator based on a fuel-adjusted net degradation proxy under the assumed fuel model, it is not a predictive race-strategy simulator. It does not perform global multi-stop strategy optimization, model lap-0 compound pace offsets, or compute live undercut/overcut tactical projections.
- **Sync Status Identity Model**: The synchronization tracking model uses `(season, round_number, session_type)` combined with free-text event names. If calendar schedule names drift between FastF1 updates, duplicate tracking records may require manual reconciliation.
- **Incremental Ingestion Skips Completed Records**: The `--incremental` flag skips any session marked `COMPLETED` or `PARTIAL` in `session_sync_status` without verifying if upstream timing data was revised post-race. Use `--force-refresh` to re-fetch sessions.
- **Driver Name & Timing Code Collisions**: Driver resolution relies on surnames and 3-letter timing abbreviations. Abbreviations that collide with common English words (such as `NOR`, `PER`, `GAS`, `BOT`) require strict uppercase boundary guarding.
- **Local Deployment Only**: The system is designed for local development. Containerization (Docker), production reverse proxies, and cloud infrastructure deployments have not yet been implemented.
- **Live LLM Quality Not Systematically Evaluated**: The automated test suite and independent benchmarks execute in offline mode with deterministic mocks. Live generative quality, prompt drift, and Gemini API rate limiting are not measured in CI.

## Roadmap

- **Multi-Stop & Compound-Offset Strategy Modeling**: Extend the conditional 1-stop pit-window estimator with lap-0 compound base-pace offsets and multi-stop strategy comparison.
- **Undercut / Overcut Analysis**: Introduce comparative gap models evaluating pit-in and pit-out delta effectiveness.
- **Production Cloud Deployment**: Docker compose configuration, ASGI production server configuration, and remote database hosting.
- **Frozen Live LLM Benchmark Suite**: Pre-registered live evaluation harness with automated LLM-as-judge scoring for generative synthesis.

## Driver Photos

- Driver portrait images displayed in the Streamlit frontend are fetched by [`scripts/fetch_driver_photos.py`](scripts/fetch_driver_photos.py) directly from Wikimedia Commons.
- Image assets are stored locally in `frontend/assets/drivers/` and are **not tracked in the git repository**.
- Per-image copyright attribution, photographer credits, source URLs, and Creative Commons license details are tracked in [`frontend/driver_photos_catalog.json`](frontend/driver_photos_catalog.json).

## License

RaceIntel is distributed under the **MIT License**. Copyright (c) 2026 Ramandeep Kaur. See the [`LICENSE`](LICENSE) file for the full license text.
