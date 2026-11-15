from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from raceintel.api.main import app

client = TestClient(app)


def _data_is_present() -> bool:
    db_path = Path("data/raceintel.db")
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM events LIMIT 1;")
        res = cur.fetchone()
        conn.close()
        return res is not None
    except Exception:
        return False


def pytest_runtest_setup(item):
    """Skip tests marked with requires_data if the database is not built."""
    if "requires_data" in item.keywords:
        if not _data_is_present():
            pytest.skip("requires built database: see README Quickstart")


@pytest.fixture
def requires_data():
    """Fixture that skips when built database is absent."""
    if not _data_is_present():
        pytest.skip("requires built database: see README Quickstart")