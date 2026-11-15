"""Tests for raceintel.config and offline fallback behavior."""
import importlib
import os
import subprocess
import sys


def test_import_config_without_env_vars(monkeypatch, tmp_path):
    """Verify raceintel.config imports cleanly with DATABASE_URL and GEMINI_API_KEY unset."""
    import raceintel.config

    # Remove variables from environment
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # In a clean environment with empty env file, Settings uses the defaults without exception
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    s = raceintel.config.Settings(_env_file=str(empty_env))
    assert s.database_url == "sqlite:///data/raceintel.db"
    assert s.GEMINI_API_KEY is None

    # Reloading module raises no exception
    reloaded_config = importlib.reload(raceintel.config)
    assert reloaded_config.settings.database_url is not None


def test_import_config_subprocess(tmp_path):
    """Verify in a clean subprocess without .env that raceintel.config imports without error."""
    code = (
        "import raceintel.config\n"
        "assert raceintel.config.settings.database_url == 'sqlite:///data/raceintel.db'\n"
        "assert raceintel.config.settings.GEMINI_API_KEY is None\n"
        "from raceintel.chat.gemini import GeminiClient\n"
        "client = GeminiClient()\n"
        "assert client.offline is True\n"
    )
    clean_env = {
        k: v for k, v in os.environ.items()
        if k not in ("DATABASE_URL", "GEMINI_API_KEY")
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=clean_env,
    )
    assert result.returncode == 0, f"Subprocess failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"


def test_gemini_client_falls_back_to_offline_when_key_unset(monkeypatch):
    """Verify GeminiClient falls back to offline mock client when GEMINI_API_KEY is None or empty."""
    from raceintel import config
    from raceintel.chat.gemini import GeminiClient, _BlockedGenAIClient

    monkeypatch.setattr(config.settings, "GEMINI_API_KEY", None)
    GeminiClient.set_global_offline(None)

    client = GeminiClient()
    assert client.offline is True
    assert isinstance(client.client, _BlockedGenAIClient)
