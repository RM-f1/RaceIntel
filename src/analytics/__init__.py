"""
Backward-compatibility shim package for ``raceintel.analytics``.

Preserves legacy ``analytics.*`` and ``src.analytics.*`` imports by
lazily re-exporting the canonical modules from ``raceintel.analytics``.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
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


def __getattr__(name: str) -> Any:
    if name in __all__:
        mod = importlib.import_module(f"raceintel.analytics.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
