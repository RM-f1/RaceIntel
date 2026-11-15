"""
Regression test for PID liveness check.

Prevents regression where `os.kill(pid, 0)` on Windows sent CTRL_C_EVENT
to the console process, interrupting pytest execution with KeyboardInterrupt.
"""

from __future__ import annotations

import os
import signal
import sys
import pytest

from raceintel.data.status import _pid_is_alive, _pid_exists


def test_pid_is_alive_current_process_and_nonexistent():
    """Assert _pid_is_alive(os.getpid()) is True and _pid_is_alive(99_999_999) is False,

    and that neither call raises or sends a signal.
    """
    signal_received = []

    def sigint_handler(signum, frame):
        signal_received.append(signum)

    old_handler = None
    try:
        old_handler = signal.signal(signal.SIGINT, sigint_handler)
    except (ValueError, AttributeError):
        pass

    try:
        # Check current process PID
        current_pid = os.getpid()
        alive_result = _pid_is_alive(current_pid)
        assert alive_result is True

        # Check non-existent PID
        dead_result = _pid_is_alive(99_999_999)
        assert dead_result is False

        # Check invalid/boundary PIDs
        assert _pid_is_alive(0) is False
        assert _pid_is_alive(-1) is False
        assert _pid_is_alive(None) is False

        # Check backward compatibility alias
        assert _pid_exists(current_pid) is True
        assert _pid_exists(99_999_999) is False

        # Assert no signal was received during these checks
        assert len(signal_received) == 0, f"Unexpected signal received: {signal_received}"
    finally:
        if old_handler is not None:
            try:
                signal.signal(signal.SIGINT, old_handler)
            except (ValueError, AttributeError):
                pass
