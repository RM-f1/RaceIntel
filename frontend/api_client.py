"""
HTTP API Client for RaceIntel Streamlit Dashboard.

Keeps the frontend strictly decoupled from SQLite/Chroma/Gemini internals by
communicating exclusively with the FastAPI backend over HTTP.
"""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_API_URL = "http://127.0.0.1:8001"
DEFAULT_TIMEOUT_SECONDS = 12
CHAT_TIMEOUT_SECONDS = 60


def get_api_base_url() -> str:
    """Resolve FastAPI backend base URL from environment or default."""
    return os.getenv("RACEINTEL_API_URL", DEFAULT_API_URL).rstrip("/")


def _request_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    base_url: str | None = None,
) -> tuple[Any | None, str | None]:
    """Execute an HTTP request and return ``(payload, error_message)``."""
    url = f"{(base_url or get_api_base_url()).rstrip('/')}{path}"
    try:
        if method == "GET":
            resp = requests.get(url, params=params, timeout=timeout)
        elif method == "POST":
            resp = requests.post(url, json=json_body, timeout=timeout)
        else:
            return None, f"Unsupported HTTP method: {method}"
    except requests.exceptions.Timeout:
        return None, f"Request timed out after {timeout}s contacting {url}"
    except requests.exceptions.ConnectionError:
        return None, f"Backend API unreachable at {get_api_base_url()}. Start FastAPI with: uvicorn raceintel.api.main:app --port 8001"
    except requests.exceptions.RequestException as exc:
        return None, f"HTTP transport error: {exc}"

    if resp.status_code >= 400:
        detail = None
        try:
            err_json = resp.json()
            if isinstance(err_json, dict):
                detail = err_json.get("detail") or err_json.get("message")
        except ValueError:
            detail = None
        msg = detail or resp.text.strip() or f"HTTP {resp.status_code}"
        return None, f"API returned {resp.status_code}: {msg}"

    try:
        return resp.json(), None
    except ValueError:
        return None, f"Invalid JSON response received from {url}"


class RaceIntelAPIClient:
    """Lightweight typed client for RaceIntel FastAPI endpoints."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url.rstrip("/") if base_url else None

    def get_health(self) -> tuple[dict[str, Any] | None, str | None]:
        return _request_json("GET", "/health/", timeout=5, base_url=self.base_url)

    def get_sessions(self, season: int = 2024) -> tuple[list[dict[str, Any]] | None, str | None]:
        return _request_json("GET", "/sessions/", params={"season": season}, base_url=self.base_url)

    def get_drivers(self) -> tuple[list[dict[str, Any]] | None, str | None]:
        return _request_json("GET", "/drivers/", base_url=self.base_url)

    def get_constructors(self) -> tuple[list[dict[str, Any]] | None, str | None]:
        return _request_json("GET", "/constructors/", base_url=self.base_url)

    def get_race_report(self, session_id: int) -> tuple[dict[str, Any] | None, str | None]:
        return _request_json("GET", f"/races/{session_id}", base_url=self.base_url)

    def get_weather(self, session_id: int) -> tuple[dict[str, Any] | None, str | None]:
        return _request_json("GET", f"/weather/{session_id}", base_url=self.base_url)

    def get_pace(self, session_id: int) -> tuple[list[dict[str, Any]] | None, str | None]:
        return _request_json("GET", f"/pace/{session_id}", base_url=self.base_url)

    def get_race_driver_standings(self, session_id: int) -> tuple[list[dict[str, Any]] | None, str | None]:
        return _request_json("GET", f"/standings/drivers/{session_id}", base_url=self.base_url)

    def get_race_constructor_standings(self, session_id: int) -> tuple[list[dict[str, Any]] | None, str | None]:
        return _request_json("GET", f"/standings/constructors/{session_id}", base_url=self.base_url)

    def get_overview(self, season: int = 2024) -> tuple[dict[str, Any] | None, str | None]:
        return _request_json("GET", "/analytics/overview", params={"season": season}, base_url=self.base_url)

    def get_season_driver_standings(self, session_id: int, season: int = 2024) -> tuple[list[dict[str, Any]] | None, str | None]:
        return _request_json(
            "GET",
            f"/analytics/standings/drivers/season/{session_id}",
            params={"season": season},
            base_url=self.base_url,
        )

    def get_season_constructor_standings(self, session_id: int, season: int = 2024) -> tuple[list[dict[str, Any]] | None, str | None]:
        return _request_json(
            "GET",
            f"/analytics/standings/constructors/season/{session_id}",
            params={"season": season},
            base_url=self.base_url,
        )

    def get_standings_progression(self, season: int = 2024) -> tuple[dict[str, Any] | None, str | None]:
        return _request_json(
            "GET",
            "/analytics/standings/progression",
            params={"season": season},
            base_url=self.base_url,
        )

    def get_full_race_analysis(self, session_id: int) -> tuple[dict[str, Any] | None, str | None]:
        return _request_json("GET", f"/analytics/race/{session_id}/full", base_url=self.base_url)

    def get_driver_season(self, driver_id: int, season: int = 2024) -> tuple[dict[str, Any] | None, str | None]:
        return _request_json(
            "GET",
            f"/analytics/drivers/{driver_id}/season",
            params={"season": season},
            base_url=self.base_url,
        )

    def get_constructor_season(self, constructor_id: int, season: int = 2024) -> tuple[dict[str, Any] | None, str | None]:
        return _request_json(
            "GET",
            f"/analytics/constructors/{constructor_id}/season",
            params={"season": season},
            base_url=self.base_url,
        )

    def ask_race_engineer(self, question: str) -> tuple[dict[str, Any] | None, str | None]:
        clean_q = (question or "").strip()
        if not clean_q:
            return None, "Query cannot be empty."
        return _request_json(
            "POST",
            "/chat/",
            json_body={"question": clean_q},
            timeout=CHAT_TIMEOUT_SECONDS,
            base_url=self.base_url,
        )

    def get_sync_status(self, season: int | None = None) -> tuple[dict[str, Any] | None, str | None]:
        params = {"season": season} if season else None
        return _request_json("GET", "/analytics/sync/status", params=params, base_url=self.base_url)

    def trigger_manual_sync(
        self,
        season: int = 2026,
        round_number: int | None = None,
        incremental: bool = True,
        force_refresh: bool = False,
        admin_key: str | None = None,
        timeout: int = 120,
    ) -> tuple[dict[str, Any] | None, str | None]:
        params: dict[str, Any] = {
            "season": season,
            "round_number": round_number,
            "incremental": incremental,
            "force_refresh": force_refresh,
        }
        if admin_key:
            params["admin_key"] = admin_key
        return _request_json(
            "POST",
            "/analytics/sync",
            params=params,
            timeout=timeout,
            base_url=self.base_url,
        )

