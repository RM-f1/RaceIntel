"""Compatibility tests for canonical ``raceintel.analytics`` and legacy shims.

Verifies that:
- ``raceintel.analytics.<module>``
- ``analytics.<module>``
- ``src.analytics.<module>``
all resolve to the exact same module object in ``sys.modules``, regardless of
import order, and that monkeypatching through any path is visible through all
three paths.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULES = [
    "artifacts",
    "degradation",
    "degradation_v2",
    "pace",
    "pit_loss",
    "pit_window",
    "position",
    "race_report",
    "sql",
    "standings",
    "stints",
    "tyre",
    "weather",
]


@pytest.mark.parametrize("mod_name", MODULES)
def test_all_three_import_paths_share_exact_module_identity(mod_name: str):
    """Canonical and both legacy paths resolve to the exact same module object."""
    canonical = importlib.import_module(f"raceintel.analytics.{mod_name}")
    legacy_short = importlib.import_module(f"analytics.{mod_name}")
    legacy_src = importlib.import_module(f"src.analytics.{mod_name}")

    assert canonical is legacy_short
    assert canonical is legacy_src
    assert sys.modules[f"raceintel.analytics.{mod_name}"] is canonical
    assert sys.modules[f"analytics.{mod_name}"] is canonical
    assert sys.modules[f"src.analytics.{mod_name}"] is canonical


def test_package_level_reexports_match_canonical():
    """Package-level attributes on analytics and src.analytics match raceintel.analytics."""
    import analytics
    import raceintel.analytics
    import src.analytics

    for mod_name in MODULES:
        assert getattr(analytics, mod_name) is getattr(raceintel.analytics, mod_name)
        assert getattr(src.analytics, mod_name) is getattr(raceintel.analytics, mod_name)


@pytest.mark.parametrize(
    "order",
    [
        ("raceintel.analytics.pit_window", "analytics.pit_window", "src.analytics.pit_window"),
        ("analytics.pit_window", "src.analytics.pit_window", "raceintel.analytics.pit_window"),
        ("src.analytics.pit_window", "analytics.pit_window", "raceintel.analytics.pit_window"),
    ],
)
def test_import_orders_in_isolated_subprocess(order: tuple[str, str, str]):
    """Subprocess import-order test: canonical-first and legacy-first both yield identical module objects."""
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(repo_root), str(src_dir)])

    code = (
        "import importlib, sys; "
        f"paths = {list(order)!r}; "
        "mods = [importlib.import_module(p) for p in paths]; "
        "assert mods[0] is mods[1] is mods[2], 'Module identity mismatch'; "
        "assert sys.modules[paths[0]] is sys.modules[paths[1]] is sys.modules[paths[2]]; "
        "print('ORDER_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ORDER_OK" in proc.stdout


@pytest.mark.parametrize(
    "patch_path",
    [
        "raceintel.analytics.pit_window",
        "analytics.pit_window",
        "src.analytics.pit_window",
    ],
)
def test_monkeypatch_visibility_across_all_three_paths(monkeypatch, patch_path: str):
    """Patching an attribute through any one path is visible through the other two."""
    sentinel = object()
    target_mod = importlib.import_module(patch_path)
    monkeypatch.setattr(target_mod, "DEFAULT_FUEL_EFFECT", sentinel)

    m_canonical = importlib.import_module("raceintel.analytics.pit_window")
    m_short = importlib.import_module("analytics.pit_window")
    m_src = importlib.import_module("src.analytics.pit_window")

    assert m_canonical.DEFAULT_FUEL_EFFECT is sentinel
    assert m_short.DEFAULT_FUEL_EFFECT is sentinel
    assert m_src.DEFAULT_FUEL_EFFECT is sentinel
