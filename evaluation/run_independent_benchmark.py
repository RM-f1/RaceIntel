"""
Independent Validation Benchmark Runner for RaceIntel (Phase 4E).

Executes the frozen independent benchmark dataset
(`evaluation/raceintel_independent_benchmark_v1.json`) against the frozen
RaceIntel application pipeline in strict offline mode (0 live Gemini calls),
captures intermediate routing/retrieval/entity telemetry without modifying
application code, evaluates each answer with strict anti-false-positive
criteria, and writes machine-readable results to
`evaluation/raceintel_independent_benchmark_v1_results.json`.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Enforce strict offline mode before importing or instantiating services
os.environ["RACEINTEL_OFFLINE"] = "1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from raceintel.chat.chat_service import ChatService  # noqa: E402
from raceintel.chat.gemini import GeminiClient  # noqa: E402

DATASET_PATH = PROJECT_ROOT / "evaluation" / "raceintel_independent_benchmark_v1.json"
RESULTS_PATH = PROJECT_ROOT / "evaluation" / "raceintel_independent_benchmark_v1_results.json"

REFUSAL_PHRASES = [
    "i couldn't find that information in the retrieved race data",
    "could not find that information",
    "only supports 2024",
    "not part of the formula 1 2024 calendar",
    "historical data for season",
    "historical weather data for season",
    "i can only answer questions about formula 1",
    "not part of the f1 2024",
    "cannot verify",
    "unavailable",
    "outside the scope",
    "do not have information",
    "no data available",
    "could not verify",
]

AMBIGUITY_PHRASES = [
    "the question is ambiguous",
    "please specify",
    "please clarify",
    "please provide more details",
    "which grand prix",
    "which race",
    "which driver",
    "which team",
    "after which grand prix",
    "multiple grands prix",
    "multiple drivers",
    "multiple teams",
]

KNOWN_2024_DRIVERS = [
    "Max Verstappen",
    "Sergio Perez",
    "Charles Leclerc",
    "Carlos Sainz",
    "Lando Norris",
    "Oscar Piastri",
    "Lewis Hamilton",
    "George Russell",
    "Fernando Alonso",
    "Lance Stroll",
    "Pierre Gasly",
    "Esteban Ocon",
    "Alexander Albon",
    "Logan Sargeant",
    "Franco Colapinto",
    "Yuki Tsunoda",
    "Daniel Ricciardo",
    "Liam Lawson",
    "Valtteri Bottas",
    "Zhou Guanyu",
    "Nico Hulkenberg",
    "Kevin Magnussen",
    "Oliver Bearman",
    "Jack Doohan",
]


def normalize_str(text: str) -> str:
    """Lowercase, strip diacritics to ASCII, and collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def is_refusal(text: str) -> bool:
    norm = normalize_str(text)
    return any(p in norm for p in REFUSAL_PHRASES)


def is_clarification(text: str) -> bool:
    norm = normalize_str(text)
    return any(p in norm for p in AMBIGUITY_PHRASES)


def extract_numbers(text: str) -> list[float]:
    """Extract numeric tokens (integers and floats), excluding P-prefixed ranks."""
    norm = normalize_str(text)
    matches = re.findall(r"(?<![a-z\d.])\d+(?:\.\d+)?(?![\d.])", norm)
    nums: list[float] = []
    for m in matches:
        try:
            nums.append(float(m))
        except ValueError:
            pass
    return nums


def has_number_close(text: str, target: float, tolerance: float = 0.05) -> bool:
    return any(abs(n - target) <= tolerance for n in extract_numbers(text))


def contains_exact_position(text: str, pos: str) -> bool:
    """Match P1/P9/P10/etc. cleanly without matching P10 against P1."""
    norm = normalize_str(text)
    pos_l = normalize_str(pos)
    num_m = re.search(r"\d+", pos_l)
    if not num_m:
        return pos_l in norm
    n = num_m.group(0)
    patterns = [
        rf"\bp{n}\b",
        rf"\bposition\s*{n}\b",
        rf"\b{n}(?:st|nd|rd|th)\b",
    ]
    return any(re.search(pat, norm) for pat in patterns)


def split_clauses(text: str) -> list[str]:
    """Split multiline/delimited structured output without breaking '1.' or 'P1.' prefixes."""
    raw_parts = re.split(r"[\n;|]+|(?<=[a-z]{2}[.!?])\s+", text or "", flags=re.IGNORECASE)
    return [p.strip() for p in raw_parts if p.strip()]


def entity_variants(name: str) -> list[str]:
    """Return normalized acceptable textual forms for a driver/team/compound."""
    n = normalize_str(name)
    variants = [n]
    aliases = {
        "red bull racing": ["red bull"],
        "haas f1 team": ["haas"],
        "rb": ["racing bulls", "vcarb"],
        "kick sauber": ["sauber"],
        "alex albon": ["alexander albon"],
        "alexander albon": ["alex albon"],
        "sergio perez": ["checo perez"],
    }
    variants.extend(aliases.get(n, []))
    return variants


def entity_in_text(text: str, entity: str) -> bool:
    norm = normalize_str(text)
    for var in entity_variants(entity):
        if re.search(rf"\b{re.escape(var)}\b", norm):
            return True
    return False


def _clause_matches_entity_and_points(text: str, entity: str, points: float) -> bool:
    """Verify entity and points co-occur cleanly in the same clause/line."""
    clauses = split_clauses(text)
    for cl in clauses:
        if entity_in_text(cl, entity) and has_number_close(cl, points, tolerance=0.05):
            return True
    # Also handle single-sentence format where entity and points share the full response
    if len(clauses) <= 2 and entity_in_text(text, entity) and has_number_close(text, points, tolerance=0.05):
        return True
    return False


def _token_support_ratio(answer: str, context: str) -> float:
    """Compute share of meaningful answer content tokens present in retrieved context."""
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "was", "were", "are",
        "had", "has", "have", "into", "their", "they", "his", "her", "who", "what",
        "when", "where", "which", "about", "after", "before", "during", "over",
        "under", "race", "grand", "prix", "2024", "formula", "season",
    }
    ans_tokens = [
        t for t in re.findall(r"[a-z0-9]+", normalize_str(answer))
        if len(t) >= 3 and t not in stopwords
    ]
    if not ans_tokens:
        return 0.0
    ctx_norm = normalize_str(context)
    supported = sum(1 for t in ans_tokens if t in ctx_norm)
    return supported / len(ans_tokens)


def check_event_and_season_consistency(answer: str, case: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Detect if an answer explicitly states the wrong Grand Prix or wrong season
    when expected season/event are known.
    """
    req_season = case.get("required_season")
    norm = normalize_str(answer)
    if req_season:
        years = [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", norm)]
        if years and all(y != req_season for y in years):
            return False, f"Year mismatch in answer: {years} vs required {req_season}"

    req_event = case.get("required_event")
    if req_event:
        req_norm = normalize_str(req_event)
        # Check if answer names some *other* Grand Prix
        gp_mentions = re.findall(r"([a-z\s]+?\s+grand prix)", norm)
        for gp in gp_mentions:
            gp_clean = gp.strip()
            # strip leading season/article words
            gp_clean = re.sub(r"^(?:the|in|at|of|during|after|\d{4})\s+", "", gp_clean).strip()
            if gp_clean and req_norm not in gp_clean and gp_clean not in req_norm:
                # Allow "emilia romagna" vs "italian" mismatch detection
                return False, f"Event mismatch in answer: '{gp_clean}' vs required '{req_event}'"
    return True, None


def evaluate_case_answer(
    case: dict[str, Any],
    answer: str,
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate an application response strictly against the case's evaluation_criteria.
    Returns dict with keys:
      status: 'PASSED' | 'FAILED' | 'UNSCORABLE' | 'MANUAL_REVIEW'
      reason: str
      evidence_grounded: bool | None
    """
    criteria = case["evaluation_criteria"]
    ctype = criteria["type"]
    ans_norm = normalize_str(answer)

    # 1. Domain rejection cases
    if ctype == "domain_rejection":
        refused = is_refusal(answer)
        blocked_by_dg = not telemetry["domain_guard_valid"]
        if refused and (blocked_by_dg or telemetry["actual_route"] in ("domain_rejection", "sql_unexecutable_refusal", "RAG")):
            # Check if response wrongly names an answer alongside refusal? No, refusal phrases suffice if clean
            return {
                "status": "PASSED",
                "reason": (
                    f"Blocked by DomainGuard ({telemetry['domain_guard_reason']})"
                    if blocked_by_dg
                    else "Refused downstream without fabricating an answer"
                ),
                "evidence_grounded": True,
            }
        return {
            "status": "FAILED",
            "reason": f"Expected refusal/domain rejection, got: {answer[:140]}",
            "evidence_grounded": False,
        }

    # 2. Abstention cases
    if ctype == "abstention":
        if is_refusal(answer) and not is_clarification(answer):
            return {
                "status": "PASSED",
                "reason": "Correctly abstained on unanswerable question",
                "evidence_grounded": True,
            }
        return {
            "status": "FAILED",
            "reason": f"Failed to abstain cleanly (or emitted clarification/unsupported claim): {answer[:140]}",
            "evidence_grounded": False,
        }

    # 3. Clarification cases
    if ctype == "clarification":
        if not is_clarification(answer):
            return {
                "status": "FAILED",
                "reason": f"Expected clarification question, got: {answer[:140]}",
                "evidence_grounded": None,
            }
        missing_terms = criteria.get("must_request_missing", [])
        if missing_terms and not any(normalize_str(t) in ans_norm for t in missing_terms):
            return {
                "status": "FAILED",
                "reason": f"Clarification did not request missing slot {missing_terms}: {answer[:140]}",
                "evidence_grounded": None,
            }
        return {
            "status": "PASSED",
            "reason": "Asked appropriate clarification naming missing information",
            "evidence_grounded": None,
        }

    # For all answerable cases below, refusal or clarification is an immediate FAIL
    if is_refusal(answer):
        return {
            "status": "FAILED",
            "reason": f"False abstention on answerable question: {answer[:140]}",
            "evidence_grounded": False,
        }
    if is_clarification(answer):
        return {
            "status": "FAILED",
            "reason": f"False clarification on answerable question: {answer[:140]}",
            "evidence_grounded": None,
        }

    # Event & season consistency guard
    consistent, mismatch_msg = check_event_and_season_consistency(answer, case)
    if not consistent:
        return {
            "status": "FAILED",
            "reason": mismatch_msg or "Event/season mismatch",
            "evidence_grounded": False,
        }

    # 4. Race winner
    if ctype == "race_winner":
        expected = criteria["must_contain_all"][0]
        if not entity_in_text(answer, expected):
            return {"status": "FAILED", "reason": f"Missing winner {expected}: {answer[:140]}", "evidence_grounded": True}
        if criteria.get("must_not_claim_other_winner"):
            other_drivers = [
                d for d in KNOWN_2024_DRIVERS
                if normalize_str(d) != normalize_str(expected) and entity_in_text(answer, d)
            ]
            if other_drivers:
                return {
                    "status": "FAILED",
                    "reason": f"Answer also mentions non-winner driver(s) {other_drivers}: {answer[:140]}",
                    "evidence_grounded": False,
                }
        return {"status": "PASSED", "reason": f"Correct winner {expected}", "evidence_grounded": True}

    # 5. Entity list (podium, points scorers, tyres, retirements)
    if ctype == "entity_list":
        required_items = criteria.get("must_contain_all", [])
        missing = [item for item in required_items if not entity_in_text(answer, item)]
        if missing:
            return {
                "status": "FAILED",
                "reason": f"Missing required items {missing} in: {answer[:160]}",
                "evidence_grounded": False,
            }
        forbidden = criteria.get("must_not_contain", [])
        present_forbidden = [item for item in forbidden if entity_in_text(answer, item)]
        if present_forbidden:
            return {
                "status": "FAILED",
                "reason": f"Incorrectly included forbidden items {present_forbidden}: {answer[:160]}",
                "evidence_grounded": False,
            }
        # For podiums & retirements, reject answers claiming unexpected extra drivers
        if case.get("expected_intent") in ("podium", "race_retirements", "points_scorers"):
            expected_set = {normalize_str(x) for x in required_items}
            extra_drivers = [
                d for d in KNOWN_2024_DRIVERS
                if normalize_str(d) not in expected_set and entity_in_text(answer, d)
            ]
            if extra_drivers:
                return {
                    "status": "FAILED",
                    "reason": f"Included incorrect extra drivers {extra_drivers}: {answer[:160]}",
                    "evidence_grounded": False,
                }
        return {"status": "PASSED", "reason": f"All {len(required_items)} required items matched cleanly", "evidence_grounded": True}

    # 6. Driver position
    if ctype == "driver_position":
        driver = criteria["driver"]
        pos = criteria["position"]
        if not entity_in_text(answer, driver):
            return {"status": "FAILED", "reason": f"Missing driver {driver}", "evidence_grounded": False}
        if not contains_exact_position(answer, pos):
            return {"status": "FAILED", "reason": f"Missing exact position {pos}: {answer[:140]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"Matched {driver} at {pos}", "evidence_grounded": True}

    # 7. Driver performance (driver + position + points)
    if ctype == "driver_performance":
        driver = criteria["driver"]
        pos = criteria["position"]
        pts = float(criteria["points"])
        if not (entity_in_text(answer, driver) and contains_exact_position(answer, pos) and has_number_close(answer, pts, 0.05)):
            return {
                "status": "FAILED",
                "reason": f"Expected {driver} {pos} with {pts} pts; got: {answer[:160]}",
                "evidence_grounded": False,
            }
        return {"status": "PASSED", "reason": f"Matched {driver} {pos} ({pts} pts)", "evidence_grounded": True}

    # 8. Entity and points (must co-occur cleanly in same clause)
    if ctype == "entity_and_points":
        entity = criteria["entity"]
        pts = float(criteria["points"])
        if not _clause_matches_entity_and_points(answer, entity, pts):
            return {
                "status": "FAILED",
                "reason": f"Expected '{entity}' paired with {pts} points; got: {answer[:160]}",
                "evidence_grounded": False,
            }
        return {"status": "PASSED", "reason": f"Paired {entity} with {pts} points", "evidence_grounded": True}

    # 9. Standings table
    if ctype == "standings_table":
        clauses = split_clauses(answer)
        missing_rows = []
        for entry in criteria["top_entries"]:
            rank_str = f"P{entry['rank']}"
            name = entry["name"]
            pts = float(entry["points"])
            found = any(
                (contains_exact_position(cl, rank_str) or re.search(rf"^\s*{entry['rank']}\b", normalize_str(cl)))
                and entity_in_text(cl, name)
                and has_number_close(cl, pts, 0.05)
                for cl in clauses
            )
            if not found:
                missing_rows.append(entry)
        if missing_rows:
            return {
                "status": "FAILED",
                "reason": f"Standings rows missing/mismatched: {missing_rows[:2]}; got: {answer[:180]}",
                "evidence_grounded": False,
            }
        return {"status": "PASSED", "reason": "All top standings rows matched with rank, name, and points", "evidence_grounded": True}

    # 10. Team performance
    if ctype == "team_performance":
        clauses = split_clauses(answer)
        for d_spec in criteria["drivers"]:
            d_name = d_spec["driver"]
            pos = d_spec["position"]
            pts = float(d_spec["points"])
            found = any(
                entity_in_text(cl, d_name)
                and contains_exact_position(cl, pos)
                and has_number_close(cl, pts, 0.05)
                for cl in clauses
            )
            if not found:
                # Fallback if single combined sentence binds each driver near its own position/points
                return {
                    "status": "FAILED",
                    "reason": f"Missing paired team result for {d_name} ({pos}, {pts} pts): {answer[:180]}",
                    "evidence_grounded": False,
                }
        return {"status": "PASSED", "reason": "Matched all teammate positions and points", "evidence_grounded": True}

    # 11. Weather condition
    if ctype == "weather_condition":
        expected = criteria["expected"].lower()
        if expected == "wet":
            is_wet_affirm = (
                (
                    "wet" in ans_norm
                    or "rain was recorded" in ans_norm
                    or "rainfall was recorded" in ans_norm
                    or "yes, rainfall" in ans_norm
                    or "yes, there was rain" in ans_norm
                    or "rain occurred" in ans_norm
                )
                and "no rain" not in ans_norm
                and "did not rain" not in ans_norm
                and "(dry)" not in ans_norm
            )
            if is_wet_affirm:
                return {"status": "PASSED", "reason": "Correctly reported Wet/rain conditions", "evidence_grounded": True}
            return {"status": "FAILED", "reason": f"Expected Wet/rain affirmation; got: {answer[:140]}", "evidence_grounded": False}
        else:
            is_dry_affirm = (
                ("dry" in ans_norm or "no rain" in ans_norm or "did not rain" in ans_norm or "no, it did not rain" in ans_norm)
                and "(wet)" not in ans_norm
                and "yes, there was rain" not in ans_norm
            )
            if is_dry_affirm:
                return {"status": "PASSED", "reason": "Correctly reported Dry/no-rain conditions", "evidence_grounded": True}
            return {"status": "FAILED", "reason": f"Expected Dry/no-rain affirmation; got: {answer[:140]}", "evidence_grounded": False}

    # 12. Weather summary
    if ctype == "weather_summary":
        cond = criteria["condition"].lower()
        if cond not in ans_norm:
            return {"status": "FAILED", "reason": f"Missing condition '{cond}': {answer[:160]}", "evidence_grounded": False}
        for num in criteria["numbers"]:
            if not has_number_close(answer, float(num), 0.15):
                return {"status": "FAILED", "reason": f"Missing number {num} in weather summary: {answer[:160]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": "Matched condition and temperatures", "evidence_grounded": True}

    # 13. Temperature
    if ctype == "temperature":
        val = float(criteria["value"])
        tol = float(criteria.get("tolerance", 0.1)) + 0.01
        if not has_number_close(answer, val, tol):
            return {"status": "FAILED", "reason": f"Expected temp ~{val}; got: {answer[:150]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"Matched temperature ~{val}", "evidence_grounded": True}

    # 14. Number set
    if ctype == "number_set":
        for val in criteria["values"]:
            if not has_number_close(answer, float(val), 0.15):
                return {"status": "FAILED", "reason": f"Missing numeric value {val}: {answer[:150]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": "Matched all required numbers", "evidence_grounded": True}

    # 15. Fastest lap
    if ctype == "fastest_lap":
        driver = criteria["driver"]
        lap_time = criteria["lap_time"]
        if not entity_in_text(answer, driver):
            return {"status": "FAILED", "reason": f"Missing fastest-lap driver {driver}: {answer[:150]}", "evidence_grounded": False}
        if lap_time not in answer:
            return {"status": "FAILED", "reason": f"Missing exact lap time {lap_time}: {answer[:150]}", "evidence_grounded": False}
        other_drivers = [
            d for d in KNOWN_2024_DRIVERS
            if normalize_str(d) != normalize_str(driver) and entity_in_text(answer, d)
        ]
        if other_drivers:
            return {"status": "FAILED", "reason": f"Unexpected competing driver(s) {other_drivers}: {answer[:150]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"Matched {driver} ({lap_time})", "evidence_grounded": True}

    # 16. Entity and number (e.g., biggest movers)
    if ctype == "entity_and_number":
        entity = criteria["entity"]
        num = float(criteria["number"])
        if not _clause_matches_entity_and_points(answer, entity, num):
            return {
                "status": "FAILED",
                "reason": f"Expected '{entity}' paired with {num}: {answer[:160]}",
                "evidence_grounded": False,
            }
        return {"status": "PASSED", "reason": f"Paired {entity} with {int(num)}", "evidence_grounded": True}

    # 17. Full race classification checks
    if ctype == "classification":
        clauses = split_clauses(answer)
        missing = []
        for chk in criteria["ordered_checks"]:
            pos = chk["position"]
            drv = chk["driver"]
            found = any(contains_exact_position(cl, pos) and entity_in_text(cl, drv) for cl in clauses)
            if not found:
                missing.append(chk)
        if missing:
            return {"status": "FAILED", "reason": f"Classification mismatch on {missing}: {answer[:180]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": "All sampled classification rows verified", "evidence_grounded": True}

    # 18. Comparison (two drivers or two constructors)
    if ctype == "comparison":
        clauses = split_clauses(answer)
        for ent in criteria["entities"]:
            name = ent["name"]
            rank = ent["rank"]
            pts = float(ent["points"])
            found = any(
                entity_in_text(cl, name)
                and (contains_exact_position(cl, rank) or has_number_close(cl, pts, 0.05))
                for cl in clauses
            )
            if not found:
                return {"status": "FAILED", "reason": f"Comparison missing {ent} in: {answer[:180]}", "evidence_grounded": False}
            if not has_number_close(answer, pts, 0.05):
                return {"status": "FAILED", "reason": f"Comparison missing points {pts} for {name}", "evidence_grounded": False}
        # Verify the ahead entity actually appears ranked ahead / winning comparison
        ahead = criteria["ahead"]
        other = [e["name"] for e in criteria["entities"] if normalize_str(e["name"]) != normalize_str(ahead)][0]
        # Check rank/points ordering or explicit "ahead of" / "leads" phrasing
        ahead_pos = ans_norm.find(normalize_str(ahead))
        other_pos = ans_norm.find(normalize_str(other))
        explicit_ahead = (
            f"{normalize_str(ahead)} leads" in ans_norm
            or f"{normalize_str(ahead)} is ahead" in ans_norm
            or f"ahead of {normalize_str(other)}" in ans_norm
            or (0 <= ahead_pos < other_pos)
        )
        if not explicit_ahead:
            return {"status": "FAILED", "reason": f"Comparison failed to establish {ahead} ahead of {other}: {answer[:180]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"Verified comparison with {ahead} ahead and exact points", "evidence_grounded": True}

    # 19. Single entity (team comparison)
    if ctype == "single_entity":
        entity = criteria["entity"]
        if not entity_in_text(answer, entity):
            return {"status": "FAILED", "reason": f"Missing {entity}; got: {answer[:140]}", "evidence_grounded": False}
        others = [d for d in KNOWN_2024_DRIVERS if normalize_str(d) != normalize_str(entity) and entity_in_text(answer, d)]
        if others:
            return {"status": "FAILED", "reason": f"Ambiguous or competing driver(s) {others}: {answer[:140]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"Matched {entity} unambiguously", "evidence_grounded": True}

    # 20. RAG grounded narrative / document answer
    if ctype == "rag_grounded":
        ret_ids = telemetry.get("retrieval_ids", [])
        expected_ids = criteria.get("expected_source_ids", [])
        source_hit = any(any(str(exp) in str(rid) for rid in ret_ids) for exp in expected_ids)
        raw_ctx = telemetry.get("retrieval_raw_context", "")
        support_ratio = _token_support_ratio(answer, raw_ctx)
        grounded = bool(raw_ctx.strip()) and support_ratio >= 0.45 and source_hit
        must_any = criteria.get("must_mention_any", [])
        mentions_key = any(entity_in_text(answer, m) for m in must_any) if must_any else True
        if source_hit and grounded and mentions_key:
            return {
                "status": "PASSED",
                "reason": f"Retrieved expected source {expected_ids}, support_ratio={support_ratio:.2f}, mentions key entity",
                "evidence_grounded": True,
                "support_ratio": round(support_ratio, 3),
                "source_hit": source_hit,
            }
        return {
            "status": "FAILED",
            "reason": f"source_hit={source_hit}, support_ratio={support_ratio:.2f}, mentions_key={mentions_key}; answer={answer[:150]}",
            "evidence_grounded": grounded,
            "support_ratio": round(support_ratio, 3),
            "source_hit": source_hit,
        }

    # 21. RAG metadata/fact probe (e.g., Round 13)
    if ctype == "rag_fact":
        ret_ids = telemetry.get("retrieval_ids", [])
        expected_ids = criteria.get("expected_source_ids", [])
        source_hit = any(any(str(exp) in str(rid) for rid in ret_ids) for exp in expected_ids)
        raw_ctx = telemetry.get("retrieval_raw_context", "")
        target_num = float(criteria["must_contain_number"])
        support_ratio = _token_support_ratio(answer, raw_ctx)
        has_num = has_number_close(answer, target_num, 0.01)
        if source_hit and has_num and support_ratio >= 0.40:
            return {
                "status": "PASSED",
                "reason": f"Retrieved {expected_ids} and answered target number {int(target_num)}",
                "evidence_grounded": True,
                "support_ratio": round(support_ratio, 3),
                "source_hit": source_hit,
            }
        return {
            "status": "FAILED",
            "reason": f"source_hit={source_hit}, has_num={has_num}, support_ratio={support_ratio:.2f}; answer={answer[:150]}",
            "evidence_grounded": bool(raw_ctx.strip()) and support_ratio >= 0.40,
            "support_ratio": round(support_ratio, 3),
            "source_hit": source_hit,
        }

    return {"status": "UNSCORABLE", "reason": f"Unsupported criteria type '{ctype}'", "evidence_grounded": None}


def check_entity_resolution(case: dict[str, Any], intent_entities: dict[str, Any], plan_params: dict[str, Any]) -> bool | None:
    """Return True/False if case requires drivers or constructors; None if none required."""
    req = case.get("required_entities") or {}
    req_drivers = req.get("drivers") or []
    req_teams = req.get("constructors") or []
    if not req_drivers and not req_teams:
        return None
    # Note: for multi-driver standings table / points_scorers / retirements, question may only name event
    # rather than listing all 10 drivers in the prompt! Only test resolution when entity is named in question
    # OR expected as a single/pair target resolved from question.
    q_norm = normalize_str(case["question"])
    expected_from_q_drivers = []
    for d in req_drivers:
        parts = normalize_str(d).split()
        if normalize_str(d) in q_norm or any(p in q_norm for p in parts if len(p) >= 4):
            expected_from_q_drivers.append(normalize_str(d))
    expected_from_q_teams = [
        normalize_str(t) for t in req_teams
        if any(v in q_norm for v in entity_variants(t))
    ]
    if not expected_from_q_drivers and not expected_from_q_teams:
        return None

    resolved_drivers = {normalize_str(d) for d in (intent_entities.get("all_drivers") or [])}
    if plan_params.get("driver_name"):
        resolved_drivers.add(normalize_str(plan_params["driver_name"]))
    resolved_teams = {normalize_str(t) for t in (intent_entities.get("all_constructors") or [])}
    if plan_params.get("team_name"):
        resolved_teams.add(normalize_str(plan_params["team_name"]))

    d_ok = all(d in resolved_drivers for d in expected_from_q_drivers)
    t_ok = all(t in resolved_teams for t in expected_from_q_teams)
    return d_ok and t_ok


def check_event_season_resolution(
    case: dict[str, Any],
    intent_entities: dict[str, Any],
    plan_params: dict[str, Any],
    retriever_filters: dict[str, Any],
    domain_valid: bool,
) -> bool | None:
    """Verify event/season resolution for cases expecting a supported event or explicit season."""
    req_ev = case.get("required_event")
    req_season = case.get("required_season")
    if not req_ev and req_season in (None, 2024):
        return None
    if not domain_valid:
        # e.g., unsupported 2019 season or out_of_calendar caught at DomainGuard
        return None

    resolved_ev = plan_params.get("event_name") or intent_entities.get("race_name") or retriever_filters.get("race_name")
    resolved_season = plan_params.get("season_year") or intent_entities.get("season") or retriever_filters.get("season")

    ev_ok = True
    if req_ev:
        ev_ok = bool(resolved_ev and normalize_str(resolved_ev) == normalize_str(req_ev))
    season_ok = True
    if req_season:
        season_ok = (resolved_season == req_season)
    return ev_ok and season_ok


def format_ratio(num: int, den: int) -> dict[str, Any]:
    return {
        "numerator": num,
        "denominator": den,
        "rate": round((num / den) if den else 0.0, 4),
        "percent": f"{(100.0 * num / den):.1f}%" if den else "N/A",
    }


def main() -> int:
    start_time = time.time()
    GeminiClient.set_global_offline(True)
    GeminiClient.reset_external_call_count()

    dataset_bytes = DATASET_PATH.read_bytes()
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    dataset = json.loads(dataset_bytes.decode("utf-8"))
    cases = dataset["cases"]

    service = ChatService(offline=True)

    per_case_results: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        q = case["question"]
        t0 = time.time()
        calls_before = GeminiClient.get_external_call_count()

        # Read-only telemetry trace matching ChatService.ask() order
        domain_res = service.domain_guard.validate(q)
        intent_res = None
        plan = None
        filters: dict[str, Any] = {}
        retrieval_res = None
        legacy_hit = False

        if not domain_res.is_valid:
            actual_route = "domain_rejection"
            actual_intent = "domain_rejection"
        else:
            intent_res = service.intent_classifier.classify(q)
            actual_intent = intent_res.intent.value
            if intent_res.is_ambiguous:
                actual_route = "clarification"
            else:
                plan = service.query_planner.create_plan(q, intent_res)
                if not plan.is_executable:
                    if plan.unresolved_reason in (
                        "season_not_supported", "season_not_found",
                        "event_not_found", "session_not_found", "no_sessions",
                    ):
                        actual_route = "abstention"
                    else:
                        actual_route = "clarification"
                elif plan.service_name and plan.service_name != "retriever":
                    actual_route = "SQL"
                else:
                    filters = service.retriever._extract_filters(q)
                    legacy_ans = service._route_structured_query(q, filters)
                    if legacy_ans is not None:
                        actual_route = "SQL"
                        legacy_hit = True
                    else:
                        actual_route = "RAG"
                        retrieval_res = service._retrieve_with_safety(q)

        # Execute full end-to-end ask() pipeline
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            actual_answer = service.ask(q)

        latency_ms = round((time.time() - t0) * 1000.0, 1)
        calls_delta = GeminiClient.get_external_call_count() - calls_before

        telemetry = {
            "domain_guard_valid": domain_res.is_valid,
            "domain_guard_status": domain_res.status.value,
            "domain_guard_reason": domain_res.reason,
            "intent": actual_intent,
            "intent_confidence": round(intent_res.confidence, 3) if intent_res else None,
            "intent_is_ambiguous": intent_res.is_ambiguous if intent_res else False,
            "intent_entities": intent_res.entities if intent_res else {},
            "query_plan_service": plan.service_name if plan else None,
            "query_plan_operation": plan.operation if plan else None,
            "query_plan_executable": plan.is_executable if plan else None,
            "query_plan_unresolved_reason": plan.unresolved_reason if plan else None,
            "query_plan_parameters": plan.parameters if plan else {},
            "legacy_sql_fallback_used": legacy_hit,
            "actual_route": actual_route,
            "retrieval_status": retrieval_res.status if retrieval_res else None,
            "retrieval_ids": retrieval_res.ids if retrieval_res else [],
            "retrieval_distances": [round(d, 4) for d in retrieval_res.distances] if retrieval_res else [],
            "retrieval_sources": retrieval_res.sources if retrieval_res else [],
            "retrieval_conflict_detected": retrieval_res.conflict_detected if retrieval_res else False,
            "retrieval_raw_context": retrieval_res.raw_context if retrieval_res else "",
        }

        eval_out = evaluate_case_answer(case, actual_answer, telemetry)
        ent_ok = check_entity_resolution(
            case,
            telemetry["intent_entities"],
            telemetry["query_plan_parameters"],
        )
        ev_season_ok = check_event_season_resolution(
            case,
            telemetry["intent_entities"],
            telemetry["query_plan_parameters"],
            filters,
            domain_res.is_valid,
        )

        # Do not persist huge retrieval_raw_context in results JSON; keep excerpt + IDs
        telemetry_clean = {k: v for k, v in telemetry.items() if k != "retrieval_raw_context"}
        telemetry_clean["retrieval_context_chars"] = len(telemetry["retrieval_raw_context"])

        per_case_results.append({
            "id": case["id"],
            "category": case["category"],
            "difficulty": case["difficulty"],
            "question": q,
            "expected_intent": case["expected_intent"],
            "expected_route": case["expected_route"],
            "answerability_status": case["answerability_status"],
            "expected_answer": case["expected_answer"],
            "actual_answer": actual_answer,
            "status": eval_out["status"],
            "evaluation_reason": eval_out["reason"],
            "evidence_grounded": eval_out.get("evidence_grounded"),
            "intent_matched": (actual_intent == case["expected_intent"]),
            "route_matched": (actual_route == case["expected_route"]),
            "entity_resolution_ok": ent_ok,
            "event_season_resolution_ok": ev_season_ok,
            "external_api_calls": calls_delta,
            "latency_ms": latency_ms,
            "telemetry": telemetry_clean,
        })
        print(f"[{idx:02d}/{len(cases)}] {case['id']} ({case['category']}): {eval_out['status']} | route={actual_route} (exp={case['expected_route']}) | intent={actual_intent} (exp={case['expected_intent']})")

    # Compute exact metrics with numerators and denominators
    total = len(per_case_results)
    passed = sum(1 for r in per_case_results if r["status"] == "PASSED")
    failed = sum(1 for r in per_case_results if r["status"] == "FAILED")
    unscorable = sum(1 for r in per_case_results if r["status"] == "UNSCORABLE")
    skipped = sum(1 for r in per_case_results if r["status"] == "SKIPPED")
    manual_review = sum(1 for r in per_case_results if r["status"] == "MANUAL_REVIEW")

    cat_metrics: dict[str, Any] = {}
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in per_case_results:
        by_cat[r["category"]].append(r)
    for cat, items in by_cat.items():
        cat_pass = sum(1 for r in items if r["status"] == "PASSED")
        cat_metrics[cat] = format_ratio(cat_pass, len(items))

    exp_sql = [r for r in per_case_results if r["expected_route"] == "SQL"]
    sql_routed = sum(1 for r in exp_sql if r["telemetry"]["actual_route"] == "SQL")

    intent_matched = sum(1 for r in per_case_results if r["intent_matched"])

    ent_eval = [r for r in per_case_results if r["entity_resolution_ok"] is not None]
    ent_ok_cnt = sum(1 for r in ent_eval if r["entity_resolution_ok"] is True)

    ev_eval = [r for r in per_case_results if r["event_season_resolution_ok"] is not None]
    ev_ok_cnt = sum(1 for r in ev_eval if r["event_season_resolution_ok"] is True)

    amb_cases = [r for r in per_case_results if r["expected_route"] == "clarification"]
    amb_ok = sum(1 for r in amb_cases if r["status"] == "PASSED")

    dg_cases = [r for r in per_case_results if r["expected_route"] == "domain_rejection"]
    dg_blocked = sum(1 for r in dg_cases if not r["telemetry"]["domain_guard_valid"])
    dg_end_to_end = sum(1 for r in dg_cases if r["status"] == "PASSED")

    rag_answerable = [r for r in per_case_results if r["expected_route"] == "RAG" and r["answerability_status"] == "answerable"]
    rag_answered = [r for r in rag_answerable if not is_refusal(r["actual_answer"])]
    rag_grounded_on_answered = sum(1 for r in rag_answered if r["evidence_grounded"] is True)
    rag_grounded_overall = sum(1 for r in rag_answerable if r["evidence_grounded"] is True)
    rag_retrieval_failures = sum(
        1 for r in rag_answerable
        if r["telemetry"]["retrieval_status"] != "ok"
    )

    abst_cases = [r for r in per_case_results if r["answerability_status"] == "unanswerable"]
    abst_correct = sum(1 for r in abst_cases if r["status"] == "PASSED")
    rag_abst_only = [r for r in abst_cases if r["expected_route"] == "RAG"]
    rag_abst_correct = sum(1 for r in rag_abst_only if r["status"] == "PASSED")

    answerable_cases = [r for r in per_case_results if r["answerability_status"] == "answerable"]
    false_abst = sum(1 for r in answerable_cases if is_refusal(r["actual_answer"]))

    # Unsupported answers: non-refusal, non-clarification responses that made unsupported/wrong claims
    non_refusal_evaluated = [
        r for r in per_case_results
        if r["evidence_grounded"] is not None
        and not is_refusal(r["actual_answer"])
        and not is_clarification(r["actual_answer"])
    ]
    unsupported_cnt = sum(
        1 for r in non_refusal_evaluated
        if r["evidence_grounded"] is False
    )

    metrics = {
        "counts": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "unscorable": unscorable,
            "skipped": skipped,
            "manually_reviewed": manual_review,
        },
        "overall_answer_accuracy": format_ratio(passed, total - unscorable - skipped),
        "category_accuracy": cat_metrics,
        "sql_routing_accuracy": format_ratio(sql_routed, len(exp_sql)),
        "intent_classification_accuracy": format_ratio(intent_matched, total),
        "entity_resolution_accuracy": format_ratio(ent_ok_cnt, len(ent_eval)),
        "event_season_resolution_accuracy": format_ratio(ev_ok_cnt, len(ev_eval)),
        "ambiguity_handling_accuracy": format_ratio(amb_ok, len(amb_cases)),
        "domain_rejection_end_to_end_accuracy": format_ratio(dg_end_to_end, len(dg_cases)),
        "domain_guard_block_accuracy": format_ratio(dg_blocked, len(dg_cases)),
        "rag_evidence_grounding_rate_answered": format_ratio(rag_grounded_on_answered, len(rag_answered)),
        "rag_evidence_grounding_rate_overall": format_ratio(rag_grounded_overall, len(rag_answerable)),
        "correct_abstention_rate_all_unanswerable": format_ratio(abst_correct, len(abst_cases)),
        "correct_abstention_rate_rag_unanswerable": format_ratio(rag_abst_correct, len(rag_abst_only)),
        "false_abstention_rate": format_ratio(false_abst, len(answerable_cases)),
        "unsupported_answer_rate": format_ratio(unsupported_cnt, len(non_refusal_evaluated)),
        "retrieval_failure_rate": format_ratio(rag_retrieval_failures, len(rag_answerable)),
        "external_api_calls_attempted": GeminiClient.get_external_call_count(),
        "total_duration_seconds": round(time.time() - start_time, 2),
    }

    output = {
        "benchmark_name": dataset["benchmark_name"],
        "benchmark_sha256": dataset_sha256,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "offline_mode": True,
        "metrics": metrics,
        "results": per_case_results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n" + "=" * 60)
    print("PHASE 4E INDEPENDENT BENCHMARK SUMMARY")
    print("=" * 60)
    for key, val in metrics.items():
        if isinstance(val, dict) and "numerator" in val:
            print(f"{key:42s}: {val['numerator']}/{val['denominator']} ({val['percent']})")
    print("-" * 60)
    print("Category accuracy:")
    for cat, val in cat_metrics.items():
        print(f"  {cat:38s}: {val['numerator']}/{val['denominator']} ({val['percent']})")
    print(f"External API calls attempted: {metrics['external_api_calls_attempted']}")
    print(f"Saved results to: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
