"""
Unit tests for safe worker termination and verified process inspection.

Validates that `stop_running_worker`:
1. Terminates verified worker when create_time matches lock.
2. Does NOT terminate when create_time mismatches (even if PID is live).
3. Does NOT terminate when create_time is missing (legacy lock format).
4. Cleans lock file when PID is dead.
5. All termination/kill calls are mocked so no test process is ever killed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from raceintel.data.status import acquire_worker_lock, is_worker_running, release_worker_lock
from raceintel.sync.worker import stop_running_worker


def test_lock_acquisition_stores_create_time_and_cmdline(tmp_path: Path):
    """Verify that acquire_worker_lock stores create_time and cmdline."""
    lock_file = tmp_path / "sync_worker.lock"
    assert acquire_worker_lock(lock_file) is True

    assert lock_file.exists() is True
    data = json.loads(lock_file.read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert "create_time" in data
    assert isinstance(data["create_time"], (float, int))
    assert "cmdline" in data
    assert isinstance(data["cmdline"], list)

    release_worker_lock(lock_file)
    assert lock_file.exists() is False


def test_stop_running_worker_matching_create_time(tmp_path: Path):
    """Case 1: Process exists AND create_time matches lock -> Terminates safely."""
    lock_file = tmp_path / "sync_worker.lock"
    dummy_pid = 54321
    dummy_time = 1700000000.0

    payload = {
        "pid": dummy_pid,
        "create_time": dummy_time,
        "cmdline": ["python", "-m", "raceintel.sync.worker"],
    }
    lock_file.write_text(json.dumps(payload), encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.create_time.return_value = dummy_time + 0.2  # within 1.0 second
    mock_proc.wait.return_value = None

    with patch("psutil.pid_exists", return_value=True), patch("psutil.Process", return_value=mock_proc):
        result = stop_running_worker(lock_file)

    assert result is True
    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_not_called()
    assert lock_file.exists() is False


def test_stop_running_worker_mismatched_create_time_live_pid(tmp_path: Path):
    """Case 2: Live PID of test process with mismatched create_time -> Must NOT terminate."""
    lock_file = tmp_path / "sync_worker.lock"
    live_pid = os.getpid()
    live_create_time = psutil.Process(live_pid).create_time()

    # Create lock with a create_time far off in the past
    payload = {
        "pid": live_pid,
        "create_time": live_create_time - 3600.0,  # 1 hour mismatch
        "cmdline": ["python", "-m", "raceintel.sync.worker"],
    }
    lock_file.write_text(json.dumps(payload), encoding="utf-8")

    mock_terminate = MagicMock()
    mock_kill = MagicMock()

    with patch.object(psutil.Process, "terminate", mock_terminate), patch.object(psutil.Process, "kill", mock_kill):
        result = stop_running_worker(lock_file)

    assert result is False
    mock_terminate.assert_not_called()
    mock_kill.assert_not_called()
    # Stale lock must be cleaned up
    assert lock_file.exists() is False


def test_stop_running_worker_missing_create_time(tmp_path: Path):
    """Case 3: Legacy lock without create_time -> Must NOT terminate, releases stale lock."""
    lock_file = tmp_path / "sync_worker.lock"
    live_pid = os.getpid()

    # Old lock format lacks create_time
    payload = {
        "pid": live_pid,
        "started_at": "2026-11-15T10:00:00Z",
    }
    lock_file.write_text(json.dumps(payload), encoding="utf-8")

    mock_terminate = MagicMock()
    mock_kill = MagicMock()

    with patch.object(psutil.Process, "terminate", mock_terminate), patch.object(psutil.Process, "kill", mock_kill):
        result = stop_running_worker(lock_file)

    assert result is False
    mock_terminate.assert_not_called()
    mock_kill.assert_not_called()
    # Stale lock must be cleaned up
    assert lock_file.exists() is False


def test_stop_running_worker_dead_pid(tmp_path: Path):
    """Case 4: Dead PID -> Cleans lock and returns False."""
    lock_file = tmp_path / "sync_worker.lock"
    dead_pid = 99_999_999

    payload = {
        "pid": dead_pid,
        "create_time": 1700000000.0,
    }
    lock_file.write_text(json.dumps(payload), encoding="utf-8")

    result = stop_running_worker(lock_file)
    assert result is False
    assert lock_file.exists() is False


def test_stop_running_worker_escalation_to_kill(tmp_path: Path):
    """Safety test: When proc.wait() times out, escalates to proc.kill()."""
    lock_file = tmp_path / "sync_worker.lock"
    dummy_pid = 11223
    dummy_time = 1700000000.0

    payload = {
        "pid": dummy_pid,
        "create_time": dummy_time,
    }
    lock_file.write_text(json.dumps(payload), encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.create_time.return_value = dummy_time
    # First wait times out, second wait succeeds after kill
    mock_proc.wait.side_effect = [psutil.TimeoutExpired(3), None]

    with patch("psutil.pid_exists", return_value=True), patch("psutil.Process", return_value=mock_proc):
        result = stop_running_worker(lock_file)

    assert result is True
    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()
    assert lock_file.exists() is False
