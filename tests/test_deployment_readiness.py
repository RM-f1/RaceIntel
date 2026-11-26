"""Tests for deployment readiness: lazy embedding loading and safe health checks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from raceintel.api.dependencies import get_db
from raceintel.api.main import app
from raceintel.retrieval.chroma_client import LazySentenceTransformerEmbeddingFunction
from raceintel.retrieval.embeddings import EmbeddingModel


def test_app_import_does_not_load_embedding_model():
    """Importing raceintel.api.main must not import sentence_transformers or load the model."""
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["RACEINTEL_DB_PATH"] = str(repo_root / "tests" / "fixtures" / "ci.db")
    env["RACEINTEL_OFFLINE"] = "1"

    code = (
        "import sys; "
        "import raceintel.api.main; "
        "from raceintel.retrieval.embeddings import EmbeddingModel; "
        "assert 'sentence_transformers' not in sys.modules, 'sentence_transformers loaded at import'; "
        "assert EmbeddingModel._model is None, 'EmbeddingModel._model loaded at import'; "
        "print('LAZY_IMPORT_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "LAZY_IMPORT_OK" in proc.stdout


def test_lazy_embedding_function_loads_once_on_first_call():
    """LazySentenceTransformerEmbeddingFunction defers model creation until first use and caches it."""
    lazy_fn = LazySentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    assert lazy_fn._fn is None

    mock_inner = MagicMock(return_value=[[0.1, 0.2]])
    mock_inner.embed_query.return_value = [[0.3, 0.4]]
    mock_cls = MagicMock(return_value=mock_inner)

    with patch(
        "chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction",
        mock_cls,
    ):
        res1 = lazy_fn(["first doc"])
        res2 = lazy_fn(["second doc"])
        res_q = lazy_fn.embed_query(["query"])

    assert np.allclose(res1, [[0.1, 0.2]])
    assert np.allclose(res2, [[0.1, 0.2]])
    assert np.allclose(res_q, [[0.3, 0.4]])
    assert mock_cls.call_count == 1
    assert lazy_fn._fn is mock_inner


def test_embedding_model_get_model_caches_instance():
    """EmbeddingModel.get_model() loads on first call and reuses the cached instance."""
    orig_model = EmbeddingModel._model
    EmbeddingModel._model = None
    try:
        fake_model = object()
        mock_st = MagicMock(return_value=fake_model)
        with patch.dict("sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=mock_st)}):
            first = EmbeddingModel.get_model()
            second = EmbeddingModel.get_model()
        assert first is fake_model
        assert second is fake_model
        assert mock_st.call_count == 1
    finally:
        EmbeddingModel._model = orig_model


def test_health_returns_503_for_missing_database_without_creating_file(tmp_path: Path):
    """GET /health/ must return 503 and not create a 0-byte SQLite file when DB is missing."""
    missing_db = tmp_path / "does_not_exist.db"
    assert not missing_db.exists()

    test_engine = create_engine(f"sqlite:///{missing_db}", future=True)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        client = TestClient(app)
        resp = client.get("/health/")
        assert resp.status_code == 503
        assert "Database unavailable" in resp.json()["detail"]
        assert not missing_db.exists()
    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()
