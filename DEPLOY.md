# RaceIntel Deployment Guide

This guide covers local production-style startup, Docker packaging, database configuration, environment variables, health checks, and troubleshooting.

---

## 1. Runtime & Installation Requirements

- **Python**: 3.11 to 3.14 (Python 3.12 recommended; Python 3.10 is incompatible with pinned dependencies in `requirements.txt` such as `contourpy==1.3.3`).
- **Install dependencies**:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

On macOS / Linux, replace `.\venv\Scripts\Activate.ps1` with `source venv/bin/activate`.

---

## 2. Database Configuration

Database path resolution (`resolve_database_path()` in `src/database/connection.py`) follows this priority order:

1. `RACEINTEL_DB_PATH` environment variable (if set and non-empty).
2. `data/raceintel.db` (if present and non-empty).
3. `tests/fixtures/ci.db` (seeded fallback fixture database, if present and non-empty).
4. `data/raceintel.db` (default target path if none of the above exist).

### Safe Startup Behavior

- **No automatic overwrite or copy**: Starting the application when `data/raceintel.db` is absent never copies `tests/fixtures/ci.db` over `data/raceintel.db` and never modifies the fixture database.
- **Missing database guard**: `GET /health/` verifies that the resolved SQLite file exists, is non-empty, and contains the `seasons` table before reporting healthy. If the database is missing or uninitialized, `/health/` returns HTTP `503` without creating an empty `0`-byte SQLite file.
- **Full database vs. fixture database**:
  - Use `data/raceintel.db` (or set `RACEINTEL_DB_PATH` to a full 5-season SQLite file) for complete 2022–2026 analytics.
  - Omit `data/raceintel.db` or set `RACEINTEL_DB_PATH=tests/fixtures/ci.db` for read-only smoke/CI startup.

---

## 3. Environment Variables & Secret Management

Copy `.env.example` to `.env` for local configuration, or inject variables via your container/process manager. **Never commit real API keys or `.env` files to version control.**

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `RACEINTEL_DB_PATH` | No | Auto-resolved (`data/raceintel.db` then `tests/fixtures/ci.db`) | Explicit path to the SQLite database file. |
| `RACEINTEL_ADMIN_KEY` | Required for sync | Unset | Admin secret checked on `POST /analytics/sync` (returns `503` if unset, `403` on mismatch). |
| `GEMINI_API_KEY` | No | Unset | Google Gemini API key for live RAG synthesis. Leave unset for offline deterministic mock mode. |
| `RACEINTEL_OFFLINE` | No | `0` | Set to `1` to force offline mock LLM mode even if `GEMINI_API_KEY` is set. |
| `RACEINTEL_API_URL` | No | `http://127.0.0.1:8001` | FastAPI backend URL consumed by the Streamlit frontend. |
| `HF_HUB_OFFLINE` | No | `1` (set by `chroma_client.py`) | Prevents network calls to HuggingFace Hub when loading cached embedding models. |
| `TRANSFORMERS_OFFLINE` | No | `1` (set by `chroma_client.py`) | Prevents network calls in `transformers` when loading cached embedding models. |

---

## 4. Model & Cache Considerations

- **Lazy Embedding Initialization**: Importing `raceintel.api.main:app` and serving non-RAG routes (`/health/`, `/analytics/pit-window`, `/races/...`, `/standings/...`) does **not** load `all-MiniLM-L6-v2`.
- `ChromaClient` uses `LazySentenceTransformerEmbeddingFunction`, and `EmbeddingModel.get_model()` defers importing/loading `SentenceTransformer` until an embedding or retrieval call actually executes, then caches the loaded model in memory.
- For offline RAG/retrieval in containers or air-gapped hosts, pre-populate or mount the HuggingFace cache directory (e.g. `~/.cache/huggingface`) containing `all-MiniLM-L6-v2` and keep `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.
- Pre-fitted pit-window artifacts are loaded from `artifacts/raceintel_artifacts.json`.

---

## 5. Local Production-Style Startup

### Start the FastAPI Backend (Port `8001`)

```powershell
$env:RACEINTEL_DB_PATH = "tests/fixtures/ci.db"
$env:RACEINTEL_OFFLINE = "1"
uvicorn raceintel.api.main:app --host 0.0.0.0 --port 8001
```

To run against the full local database instead, omit `RACEINTEL_DB_PATH` (when `data/raceintel.db` is present) or set `RACEINTEL_DB_PATH=data/raceintel.db`.

### Start the Streamlit Frontend (Port `8501`, Optional)

```powershell
$env:RACEINTEL_API_URL = "http://127.0.0.1:8001"
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

---

## 6. Docker Build & Run

> **Note**: Docker CLI/daemon is not installed in the local development environment used to prepare this configuration; Docker build and runtime execution have not been tested locally.

The provided `Dockerfile` packages the FastAPI service on port `8001`, defaulting to `tests/fixtures/ci.db` and offline mode:

```bash
# Build image
docker build -t raceintel-api:latest .

# Run with built-in fixture database
docker run --rm -p 8001:8001 raceintel-api:latest

# Run with an external full database mounted read-only (or read-write if sync is used)
docker run --rm -p 8001:8001 \
  -v /path/to/data:/app/data \
  -e RACEINTEL_DB_PATH=/app/data/raceintel.db \
  -e RACEINTEL_ADMIN_KEY=your-secret-key \
  raceintel-api:latest
```

---

## 7. Health-Check Verification

Verify the API and database connection:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8001/health/
```

Expected response (`200 OK`):

```json
{
  "status": "healthy",
  "database": "connected"
}
```

Verify core analytics route (`GET /analytics/pit-window`):

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/analytics/pit-window?race=Bahrain%20Grand%20Prix&total_laps=57"
```

---

## 8. Troubleshooting Common Startup Failures

- **HTTP `503` on `GET /health/` (`Database unavailable at ...`)**:
  The resolved SQLite file does not exist or is `0` bytes. Set `RACEINTEL_DB_PATH` to `tests/fixtures/ci.db` or a built `data/raceintel.db`, or initialize the schema with `python -c "from database.schema import create_database; create_database()"`.
- **HTTP `503` on `GET /health/` (`Database schema check failed: no such table: seasons`)**:
  The SQLite file exists but has not been initialized with the RaceIntel schema. Run schema creation / ingestion or point `RACEINTEL_DB_PATH` to a populated database.
- **HTTP `503` on `GET /analytics/pit-window`**:
  `artifacts/raceintel_artifacts.json` is missing. Generate it with `python scripts/build_artifacts.py`.
- **Embedding download failure in offline environments**:
  Ensure `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are set and `~/.cache/huggingface` contains `all-MiniLM-L6-v2`, or avoid invoking `/chat/` RAG endpoints if only SQL/analytics endpoints are needed.
- **Port `8001` or `8501` already in use**:
  Stop the existing process or pass a different `--port` to `uvicorn` and update `RACEINTEL_API_URL` for Streamlit.

---

## 9. Known Deployment Limitations

- **Single-service container**: `Dockerfile` runs the FastAPI backend (`8001`); the Streamlit frontend (`8501`) is started separately if needed.
- **SQLite concurrency**: SQLite is suited for single-node / read-heavy analytical workloads rather than high-concurrency multi-writer deployments.
- **ChromaDB persistence**: Vector retrieval (`data/chroma/`) is not bundled in the Docker image; mount `data/chroma/` and a cached `all-MiniLM-L6-v2` model directory if live RAG retrieval is required in production.
- **Docker unverified locally**: Docker build/run commands were written against standard `python:3.12-slim` conventions but not executed locally because Docker is not installed on the host.
