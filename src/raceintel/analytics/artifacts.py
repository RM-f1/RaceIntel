"""Load and validate pre-fitted RaceIntel analytics artifacts.

The artifacts JSON is built by scripts/build_artifacts.py and stored in
artifacts/raceintel_artifacts.json.  This module provides typed load
functions and raises clear errors when the file is absent or malformed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "artifacts" / "raceintel_artifacts.json"

_REQUIRED_META_KEYS = {"build_date", "sign_convention", "note"}
_REQUIRED_DEG_KEYS = {"season", "compound", "slope", "se", "n"}
_REQUIRED_PIT_KEYS = {"season", "race", "median_pit_loss_s", "n_stops"}
_REQUIRED_STINT_KEYS = {"compound", "p95_stint_length"}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Artifacts file not found: {path}\n"
            "Run  python scripts/build_artifacts.py  to generate it."
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _check_keys(record: dict, required: set[str], label: str) -> None:
    missing = required - record.keys()
    if missing:
        raise ValueError(f"Artifact record '{label}' is missing keys: {missing}")


def load_artifacts(path: Path | str | None = None) -> dict[str, Any]:
    """Load the full artifacts JSON and return it as a plain dict.

    Parameters
    ----------
    path:
        Override the default path (``artifacts/raceintel_artifacts.json``).

    Raises
    ------
    FileNotFoundError
        When the artifacts file does not exist.
    ValueError
        When required top-level sections or record keys are absent.
    """
    resolved = Path(path) if path is not None else _DEFAULT_PATH
    data = _load_json(resolved)

    for section in ("metadata", "degradation", "pit_loss", "stint_p95"):
        if section not in data:
            raise ValueError(f"Artifacts file is missing section '{section}'.")

    _check_keys(data["metadata"], _REQUIRED_META_KEYS, "metadata")

    for rec in data["degradation"]:
        _check_keys(rec, _REQUIRED_DEG_KEYS, f"degradation[{rec}]")

    for rec in data["pit_loss"]:
        _check_keys(rec, _REQUIRED_PIT_KEYS, f"pit_loss[{rec}]")

    for rec in data["stint_p95"]:
        _check_keys(rec, _REQUIRED_STINT_KEYS, f"stint_p95[{rec}]")

    return data


def load_degradation(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return the degradation section of the artifacts as a list of dicts."""
    return load_artifacts(path)["degradation"]


def load_pit_loss(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return the pit_loss section of the artifacts as a list of dicts."""
    return load_artifacts(path)["pit_loss"]


def load_stint_p95(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return the stint_p95 section of the artifacts as a list of dicts."""
    return load_artifacts(path)["stint_p95"]
