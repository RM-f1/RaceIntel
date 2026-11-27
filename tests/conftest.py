from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from database.connection import DATABASE_PATH, resolve_database_path
from raceintel.api.main import app

client = TestClient(app)


def _active_db_path() -> Path:
    return resolve_database_path()


def _data_is_present() -> bool:
    db_path = _active_db_path()
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM events LIMIT 1;")
        res = cur.fetchone()
        conn.close()
        return res is not None
    except Exception:
        return False


def _is_full_database() -> bool:
    db_path = _active_db_path()
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
        seasons = {r[0] for r in conn.execute("SELECT season_year FROM seasons;").fetchall()}
        conn.close()
        return {2022, 2023, 2024, 2025, 2026}.issubset(seasons)
    except Exception:
        return False


def pytest_report_header(config):
    db_path = _active_db_path()
    mode = "full" if _is_full_database() else ("fixture" if _data_is_present() else "none")
    return f"raceintel-db: {db_path} (mode={mode}, module_db={DATABASE_PATH})"


def pytest_runtest_setup(item):
    """Skip tests marked with requires_data if neither full nor fixture DB is built."""
    if "requires_data" in item.keywords:
        if not _data_is_present():
            pytest.skip("requires built database or tests/fixtures/ci.db")
    if "requires_full_data" in item.keywords:
        if not _is_full_database():
            pytest.skip("requires full local data/raceintel.db (not in CI fixture)")


@pytest.fixture
def requires_data():
    """Fixture that skips when built database and fixture are both absent."""
    if not _data_is_present():
        pytest.skip("requires built database or tests/fixtures/ci.db")

# ragas/datasets are not in requirements-dev.txt; skip RAGAS tests where they are absent (e.g. CI).
import importlib.util

collect_ignore = []
if importlib.util.find_spec("datasets") is None:
    collect_ignore += ["test_evaluation_v2.py", "test_ragas_cache.py"]