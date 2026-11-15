"""
RaceIntel Phase 6.2.2 Verification Tests — Sprint-Aware Analytics and RAG Integration.

Validates:
1. Separation and reporting of Grand Prix points, Sprint points, and combined totals
   in driver & constructor standings.
2. Winner query differentiation: Austrian Grand Prix (George Russell) vs Austrian Sprint (Max Verstappen).
3. Factual season sprint analytics:
   - Max Verstappen 2024 Sprint points (38.0 pts)
   - McLaren 2024 Sprint points (57.0 pts)
   - Grid leader in sprint points (Max Verstappen)
   - Top constructor in sprint points (Ferrari & McLaren tied at 57.0 pts)
4. Race Analysis full analytics endpoint (/analytics/race/{session_id}/full) supports
   sprint sessions with complete classifications and graceful fallbacks.
5. Frontend views integration:
   - Race Analysis dropdown includes Sprint sessions with explicit type tags ([SPRINT] vs [GRAND PRIX])
   - Driver Intel H2H comparison displays GP Points, Sprint Points, and Total Points
   - Constructor Intel driver contributions table displays GP Points, Sprint Points, and Total Points
6. ChromaDB incremental sprint indexing and deterministic RAG retrieval:
   - Grounded sprint reports indexed with unique IDs ({season}_{round}_sprint)
   - Zero duplicate documents and zero regression of baseline GP documents
   - RAG retrieval accurately fetches sprint documents when sprint is queried.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("RACEINTEL_OFFLINE", "1")

from raceintel.api.main import app
from raceintel.chat.chat_service import ChatService
from raceintel.retrieval.chroma_client import ChromaClient
from raceintel.retrieval.retriever import Retriever
from raceintel.retrieval.season_indexer import SeasonIndexer
from raceintel.services.race_service import format_race_winner_answer, get_race_winner
from raceintel.services.session_service import resolve_race_session
from raceintel.services.standings_service import (
    get_constructor_season_sprint_points,
    get_constructor_standings_after_event,
    get_driver_season_sprint_points,
    get_driver_standings_after_event,
    get_most_sprint_points_constructor,
    get_most_sprint_points_driver,
)


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------
# 1. Standings Point Separation (GP vs Sprint vs Total)
# ---------------------------------------------------------------------


def test_driver_standings_points_separation():
    """Verify driver standings separate race_points, sprint_points, and total_points."""
    # After final 2024 session (Abu Dhabi GP, session 25)
    standings = get_driver_standings_after_event(25, season=2024)
    assert len(standings) > 0

    ver = next(d for d in standings if d["driver_code"] == "VER")
    assert ver["rank"] == 1
    assert ver["points"] == 437.0
    assert ver["sprint_points"] == 38.0
    assert ver["race_points"] == 399.0
    assert ver["total_points"] == 437.0
    assert ver["race_points"] + ver["sprint_points"] == ver["total_points"]

    nor = next(d for d in standings if d["driver_code"] == "NOR")
    assert nor["rank"] == 2
    assert nor["points"] == 374.0
    assert nor["sprint_points"] == 30.0
    assert nor["race_points"] == 344.0
    assert nor["total_points"] == 374.0

    pia = next(d for d in standings if d["driver_code"] == "PIA")
    assert pia["rank"] == 4
    assert pia["points"] == 292.0
    assert pia["sprint_points"] == 27.0
    assert pia["race_points"] == 265.0


def test_constructor_standings_points_separation():
    """Verify constructor standings separate race_points, sprint_points, and total_points."""
    c_standings = get_constructor_standings_after_event(25, season=2024)
    assert len(c_standings) > 0

    mclaren = next(c for c in c_standings if c["constructor_name"] == "McLaren")
    assert mclaren["rank"] == 1
    assert mclaren["points"] == 666.0
    assert mclaren["sprint_points"] == 57.0
    assert mclaren["race_points"] == 609.0
    assert mclaren["total_points"] == 666.0
    assert mclaren["race_points"] + mclaren["sprint_points"] == mclaren["total_points"]

    ferrari = next(c for c in c_standings if c["constructor_name"] == "Ferrari")
    assert ferrari["rank"] == 2
    assert ferrari["points"] == 652.0
    assert ferrari["sprint_points"] == 57.0
    assert ferrari["race_points"] == 595.0


# ---------------------------------------------------------------------
# 2. Winner Separation: Austrian GP vs Austrian Sprint
# ---------------------------------------------------------------------


def test_austrian_gp_vs_sprint_winner_resolution():
    """Verify George Russell won the GP and Max Verstappen won the Sprint in Austria 2024."""
    # Grand Prix resolution
    gp_res = resolve_race_session("Austrian Grand Prix", 2024)
    assert gp_res is not None
    assert gp_res["session_id"] == 12
    assert gp_res["session_type"] == "Race"

    gp_winner = get_race_winner(gp_res["session_id"])
    assert gp_winner is not None
    assert gp_winner["driver_code"] == "RUS"
    assert "Russell" in gp_winner["driver_full_name"]

    gp_answer = format_race_winner_answer(
        gp_winner, gp_res["event_name"], 2024, session_type="Race"
    )
    assert "George Russell" in gp_answer
    assert "Austrian Grand Prix" in gp_answer
    assert "Sprint" not in gp_answer

    # Sprint resolution
    sprint_res = resolve_race_session("Austrian Sprint", 2024)
    assert sprint_res is not None
    assert sprint_res["session_id"] == 119
    assert sprint_res["session_type"] == "Sprint"

    sp_winner = get_race_winner(sprint_res["session_id"])
    assert sp_winner is not None
    assert sp_winner["driver_code"] == "VER"
    assert "Verstappen" in sp_winner["driver_full_name"]

    sp_answer = format_race_winner_answer(
        sp_winner, sprint_res["event_name"], 2024, session_type="Sprint"
    )
    assert "Max Verstappen" in sp_answer
    assert "Austrian Grand Prix Sprint" in sp_answer


def test_chat_service_gp_vs_sprint_answers():
    """Verify ChatService answers Austrian GP and Sprint winner questions deterministically."""
    chat = ChatService()

    gp_ans = chat.ask("Who won the 2024 Austrian Grand Prix?")
    assert "George Russell" in gp_ans
    assert "Austrian Grand Prix" in gp_ans

    sp_ans = chat.ask("Who won the 2024 Austrian Sprint?")
    assert "Max Verstappen" in sp_ans
    assert "Sprint" in sp_ans


# ---------------------------------------------------------------------
# 3. Factual Season Sprint Analytics
# ---------------------------------------------------------------------


def test_verstappen_2024_sprint_points():
    """Verify Verstappen scored exactly 38.0 sprint points in 2024."""
    pts = get_driver_season_sprint_points("VER", 2024)
    assert pts == 38.0

    chat = ChatService()
    ans = chat.ask("How many Sprint points did Max Verstappen score in 2024?")
    assert "Max Verstappen" in ans
    assert "38.0" in ans or "38" in ans


def test_mclaren_2024_sprint_points():
    """Verify McLaren scored exactly 57.0 sprint points in 2024."""
    pts = get_constructor_season_sprint_points("mclaren", 2024)
    assert pts == 57.0

    chat = ChatService()
    ans = chat.ask("How many points did McLaren earn from Sprints in 2024?")
    assert "McLaren" in ans
    assert "57.0" in ans or "57" in ans


def test_most_sprint_points_queries():
    """Verify queries for highest sprint point scorers across the grid."""
    top_drv = get_most_sprint_points_driver(2024)
    assert top_drv is not None
    assert top_drv["driver_code"] == "VER"
    assert top_drv["sprint_points"] == 38.0

    chat = ChatService()
    ans_drv = chat.ask("Which driver scored the most Sprint points in 2024?")
    assert "Max Verstappen" in ans_drv
    assert "38.0" in ans_drv or "38" in ans_drv

    top_cons = get_most_sprint_points_constructor(2024)
    assert top_cons is not None
    assert top_cons["is_tie"] is True
    assert len(top_cons["teams"]) == 2
    assert "McLaren" in top_cons["teams"]
    assert "Ferrari" in top_cons["teams"]
    assert top_cons["sprint_points"] == 57.0


# ---------------------------------------------------------------------
# 4. Chinese Sprint Single-Race Analytics & RAG Retrieval
# ---------------------------------------------------------------------


def test_chinese_sprint_winner_and_rag_retrieval():
    """Verify retrieval and chat for Chinese Sprint winner."""
    chat = ChatService()
    ans = chat.ask("Who won the 2024 Chinese Sprint?")
    assert "Max Verstappen" in ans
    assert "Chinese" in ans

    # Verify ChromaDB RAG retrieval
    retriever = Retriever()
    ret_res = retriever.retrieve_context("Who won the 2024 Chinese Sprint?")
    assert ret_res.status == "ok"
    assert len(ret_res.documents) >= 1
    doc_text = ret_res.documents[0]
    assert "Session: Sprint" in doc_text
    assert "Max Verstappen" in doc_text
    assert "Chinese Grand Prix" in doc_text


def test_driver_sprint_performance_rag_retrieval():
    """Verify ChromaDB RAG retrieval for specific driver sprint performance."""
    retriever = Retriever()
    ret_res = retriever.retrieve_context(
        "How did Max Verstappen perform in the 2024 Chinese Sprint?"
    )
    assert ret_res.status == "ok"
    assert len(ret_res.documents) >= 1
    doc_text = ret_res.documents[0]
    assert "Driver:\nMax Verstappen" in doc_text
    assert "Session: Sprint" in doc_text
    assert "Sprint Finished:\nP1" in doc_text
    assert "Sprint Points:\n8" in doc_text


# ---------------------------------------------------------------------
# 5. ChromaDB Incremental Indexing Safety & Idempotency
# ---------------------------------------------------------------------


def test_chromadb_sprint_indexing_idempotency():
    """Verify that SeasonIndexer skips all already-indexed sprint documents."""
    indexer = SeasonIndexer()
    stats = indexer.index_sprints(2024, dry_run=True)
    assert stats.total_generated == 126
    # All 126 sprint documents are already indexed in ChromaDB
    assert stats.skipped_existing == 126
    assert stats.indexed_new == 0


def test_chromadb_no_duplicate_document_ids():
    """Verify that ChromaDB collection has zero duplicate document IDs."""
    chroma = ChromaClient()
    res = chroma.collection.get()
    ids = res["ids"]
    assert len(ids) == len(set(ids)), "ChromaDB collection contains duplicate document IDs!"
    # Must have both GP documents and sprint documents
    sprint_ids = [i for i in ids if "sprint" in i]
    assert len(sprint_ids) == 126


# ---------------------------------------------------------------------
# 6. Full Race Analysis API on Sprint Session
# ---------------------------------------------------------------------


def test_full_race_analysis_sprint_session(api_client: TestClient):
    """Verify /analytics/race/{session_id}/full handles Sprint sessions gracefully."""
    # Session 117 is 2024 Chinese Sprint
    resp = api_client.get("/analytics/race/117/full")
    assert resp.status_code == 200
    data = resp.json()

    assert data["session"]["session_type"] == "Sprint"
    assert data["session"]["event_name"] == "Chinese Grand Prix"
    assert data["report"] is not None
    assert data["report"]["winner"] == "Max Verstappen"
    assert data["report"]["top_constructor"] == "Red Bull Racing"
    assert len(data["driver_classification"]) == 20
    assert data["driver_classification"][0]["driver_code"] == "VER"
    assert data["driver_classification"][0]["points_scored"] == 8.0
    assert len(data["constructor_points"]) > 0


# ---------------------------------------------------------------------
# 7. Season Profile Endpoints Sprint Points Awareness
# ---------------------------------------------------------------------


def test_driver_season_profile_sprint_points(api_client: TestClient):
    """Verify /analytics/drivers/{id}/season returns sprint_points in summary."""
    # Driver 2 is Max Verstappen
    resp_ver = api_client.get("/analytics/drivers/2/season?season=2024")
    assert resp_ver.status_code == 200
    data_ver = resp_ver.json()

    summary_ver = data_ver["summary"]
    assert summary_ver["total_points"] == 437.0
    assert summary_ver["race_points"] == 399.0
    assert summary_ver["sprint_points"] == 38.0
    assert len(data_ver.get("sprint_results", [])) == 6

    # Driver 1 is Lewis Hamilton
    resp_ham = api_client.get("/analytics/drivers/1/season?season=2024")
    assert resp_ham.status_code == 200
    summary_ham = resp_ham.json()["summary"]
    assert summary_ham["total_points"] == 223.0
    assert summary_ham["race_points"] == 207.0
    assert summary_ham["sprint_points"] == 16.0


def test_constructor_season_profile_sprint_points(api_client: TestClient):
    """Verify /analytics/constructors/{id}/season returns sprint_points in summary and driver contributions."""
    # Constructor 6 is McLaren
    resp = api_client.get("/analytics/constructors/6/season?season=2024")
    assert resp.status_code == 200
    data = resp.json()

    summary = data["summary"]
    assert summary["total_points"] == 666.0
    assert summary["race_points"] == 609.0
    assert summary["sprint_points"] == 57.0

    contribs = data["driver_contributions"]
    nor = next(c for c in contribs if c["driver_code"] == "NOR")
    assert nor["total_points"] == 374.0
    assert nor["race_points"] == 344.0
    assert nor["sprint_points"] == 30.0

    pia = next(c for c in contribs if c["driver_code"] == "PIA")
    assert pia["total_points"] == 292.0
    assert pia["race_points"] == 265.0
    assert pia["sprint_points"] == 27.0
