"""
Phase 5D Independent Benchmark V2 Runner & Strict Evaluator.

Executes `evaluation/raceintel_independent_v2.json` end-to-end against
`ChatService(offline=True)` with zero external Gemini API calls (`0` calls).

Design constraints enforced:
- Frozen dataset & scorer verification: computes and persists SHA256 digests of
  both `raceintel_independent_v2.json` and this runner script.
- Strict anti-false-positive evaluation:
  - Clause/sentence-level co-occurrence for multi-entity comparisons & tables.
  - Exact position tokens (e.g. P1 != P10) and exact numeric extraction.
  - Safe dry/wet polarity checks (negated rainfall is not treated as wet).
  - RAG completeness (`must_mention_all`) and retrieval hit separated cleanly
    from generated answer grounding/correctness.
  - Answerable queries never pass on a refusal/abstention.
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
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["RACEINTEL_OFFLINE"] = "1"

from raceintel.chat.chat_service import ChatService  # noqa: E402
from raceintel.chat.gemini import GeminiClient  # noqa: E402

DATASET_PATH = PROJECT_ROOT / "evaluation" / "raceintel_independent_v2.json"
RESULTS_PATH = PROJECT_ROOT / "evaluation" / "raceintel_independent_v2_results.json"

KNOWN_2024_DRIVERS = [
    "Max Verstappen", "Sergio Perez", "Charles Leclerc", "Carlos Sainz",
    "Lando Norris", "Oscar Piastri", "Lewis Hamilton", "George Russell",
    "Fernando Alonso", "Lance Stroll", "Pierre Gasly", "Esteban Ocon",
    "Alexander Albon", "Logan Sargeant", "Franco Colapinto",
    "Yuki Tsunoda", "Daniel Ricciardo", "Liam Lawson",
    "Nico Hulkenberg", "Kevin Magnussen", "Valtteri Bottas", "Guanyu Zhou",
    "Oliver Bearman", "Jack Doohan",
]

REFUSAL_PHRASES = [
    "not available",
    "unavailable",
    "not included",
    "not stored",
    "cannot answer",
    "can't answer",
    "cannot determine",
    "unable to answer",
    "unable to determine",
    "unable to retrieve",
    "insufficient",
    "do not have",
    "don't have",
    "no data",
    "no records",
    "not contain",
    "does not cover",
    "outside the scope",
    "only supports",
    "only covers",
    "cannot verify",
    "not supported",
    "not found in",
    "no qualifying",
    "no pit stop",
]

AMBIGUITY_PHRASES = [
    "please clarify",
    "could you clarify",
    "please specify",
    "which race",
    "which grand prix",
    "which driver",
    "which season",
    "which event",
    "multiple",
    "did you mean",
    "ambiguous",
    "more specific",
]

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "was", "were",
    "are", "had", "has", "have", "did", "who", "what", "when", "where",
    "which", "after", "during", "around", "about", "race", "grand", "prix",
    "2024", "season", "points", "point", "position", "finished", "finish",
    "result", "results", "summary", "report", "driver", "drivers",
}


def normalize_str(text: str) -> str:
    return (
        str(text or "")
        .lower()
        .replace("ã", "a")
        .replace("á", "a")
        .replace("é", "e")
        .replace("ü", "u")
        .strip()
    )


def is_refusal(answer: str) -> bool:
    low = normalize_str(answer)
    return any(p in low for p in REFUSAL_PHRASES)


def is_clarification(answer: str) -> bool:
    low = normalize_str(answer)
    if any(p in low for p in AMBIGUITY_PHRASES):
        return True
    # Explicit question listing US/Italy race choices
    if ("?" in low) and any(tok in low for tok in ("which ", "specify", "clarify", "austin", "imola", "miami", "monza")):
        return True
    return False


def entity_variants(entity: str) -> list[str]:
    norm = normalize_str(entity)
    variants = [norm]
    parts = norm.split()
    if len(parts) >= 2 and len(parts[-1]) >= 4:
        variants.append(parts[-1])
    if norm == "red bull racing":
        variants.extend(["red bull", "red bull racing"])
    elif norm == "haas f1 team":
        variants.extend(["haas", "haas f1"])
    elif norm == "kick sauber":
        variants.extend(["sauber", "kick sauber", "stake"])
    elif norm == "rb":
        variants.extend(["racing bulls", "visa cash app rb"])
    return list(dict.fromkeys(variants))


def entity_in_text(text: str, entity: str) -> bool:
    low = normalize_str(text)
    for var in entity_variants(entity):
        if re.search(rf"(?<![a-z0-9]){re.escape(var)}(?![a-z0-9])", low):
            return True
    return False


def split_clauses(answer: str) -> list[str]:
    raw_lines = [ln.strip() for ln in str(answer or "").splitlines() if ln.strip()]
    clauses: list[str] = []
    for ln in raw_lines:
        parts = re.split(r"(?<=[.;])\s+", ln)
        for p in parts:
            p = p.strip()
            if p:
                clauses.append(p)
    return clauses or [str(answer or "")]


def extract_numbers(text: str) -> list[float]:
    # Capture decimal or integer tokens bounded away from letters (ignore P1/P2/round tags separately)
    cleaned = re.sub(r"\b2024\b", " ", str(text or ""))
    matches = re.findall(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])", cleaned)
    out: list[float] = []
    for m in matches:
        try:
            out.append(float(m))
        except ValueError:
            pass
    return out


def has_number_close(text: str, target: float, tolerance: float = 0.1) -> bool:
    for val in extract_numbers(text):
        if abs(val - target) <= tolerance:
            return True
    return False


def contains_exact_position(text: str, pos: int) -> bool:
    low = normalize_str(text)
    suffix = "th"
    if pos % 100 not in (11, 12, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(pos % 10, "th")
    patterns = [
        rf"(?<![a-z0-9])p{pos}(?![0-9a-z])",
        rf"(?<![a-z0-9]){pos}{suffix}(?![0-9a-z])",
        rf"(?:position|pos|rank|placed|finished)\s*[:#]?\s*{pos}(?![0-9.])",
        rf"(?:^|[\n;|])\s*{pos}\.(?:\s|$)",
    ]
    return any(re.search(pat, low) for pat in patterns)


def _token_support_ratio(answer: str, context: str) -> float:
    ans_toks = {
        t for t in re.findall(r"[a-z0-9]+", normalize_str(answer))
        if len(t) >= 3 and t not in _STOPWORDS
    }
    if not ans_toks:
        return 0.0
    ctx_toks = set(re.findall(r"[a-z0-9]+", normalize_str(context)))
    # Strip boilerplate mock phrasing that shouldn't penalize lexical overlap
    boilerplate = {
        "based", "retrieved", "knowledge", "summary", "race", "winner",
        "podium", "fastest", "lap", "round", "season", "consisted", "set",
        "won", "gained", "positions", "classification",
    }
    core_ans = ans_toks - boilerplate
    if not core_ans:
        core_ans = ans_toks
    hits = sum(1 for t in core_ans if t in ctx_toks)
    return hits / len(core_ans)


def _detect_weather_polarity(text: str) -> tuple[bool, bool]:
    """Return (indicates_dry, indicates_wet) without false-matching 'no rainfall' as wet."""
    low = normalize_str(text)
    # Remove explicitly negated wet statements before scanning for wet words
    stripped = re.sub(
        r"\b(?:no|not|without|zero|0)\s+(?:\d+\s+of\s+\d+\s+)?(?:rain(?:fall)?|wet(?:\s+weather)?|showers?|precipitation)\b",
        " ",
        low,
    )
    stripped = re.sub(r"\b0\s*/\s*\d+\s*(?:rain(?:fall)?|wet)\b", " ", stripped)
    has_dry = bool(re.search(r"\b(?:dry|no rain(?:fall)?|zero rain(?:fall)?|0 rainfall|rain-free)\b", low))
    has_wet = bool(re.search(r"\b(?:wet|rain(?:ed|ing|fall)?|showers?|intermittent rain|damp)\b", stripped))
    return has_dry, has_wet


def evaluate_case_answer(case: dict[str, Any], answer: str, telemetry: dict[str, Any]) -> dict[str, Any]:
    criteria = case["evaluation_criteria"]
    ctype = criteria["type"]
    ans = str(answer or "").strip()

    if not ans:
        return {"status": "FAILED", "reason": "Empty response", "evidence_grounded": False}

    # Domain rejection
    if ctype == "domain_rejection":
        blocked_guard = not telemetry.get("domain_guard_valid", True)
        if blocked_guard or is_refusal(ans):
            return {
                "status": "PASSED",
                "reason": f"Blocked/refused out-of-domain query (domain_guard_valid={telemetry.get('domain_guard_valid')})",
                "evidence_grounded": True,
            }
        return {
            "status": "FAILED",
            "reason": f"Failed to reject out-of-domain query; answered: {ans[:150]}",
            "evidence_grounded": False,
        }

    # Ambiguous clarification
    if ctype == "clarification":
        if is_clarification(ans) and not any(entity_in_text(ans, d) for d in KNOWN_2024_DRIVERS):
            return {"status": "PASSED", "reason": "Requested clarification cleanly without guessing", "evidence_grounded": True}
        return {
            "status": "FAILED",
            "reason": f"Did not ask appropriate clarification; answered: {ans[:150]}",
            "evidence_grounded": False,
        }

    # Unanswerable abstention
    if ctype == "abstention":
        if is_refusal(ans) or not telemetry.get("domain_guard_valid", True):
            return {"status": "PASSED", "reason": "Abstained appropriately on unanswerable query", "evidence_grounded": True}
        return {
            "status": "FAILED",
            "reason": f"Failed to abstain on unanswerable query; answered: {ans[:150]}",
            "evidence_grounded": False,
        }

    # Answerable queries must never pass on refusal or clarification
    if is_refusal(ans):
        return {
            "status": "FAILED",
            "reason": f"False abstention on answerable query: {ans[:150]}",
            "evidence_grounded": False,
        }
    if is_clarification(ans):
        return {
            "status": "FAILED",
            "reason": f"False clarification request on unambiguous query: {ans[:150]}",
            "evidence_grounded": False,
        }

    # 1. Single entity (winner / fastest lap)
    if ctype == "single_entity":
        ent = criteria["entity"]
        if not entity_in_text(ans, ent):
            return {"status": "FAILED", "reason": f"Missing {ent}; got: {ans[:150]}", "evidence_grounded": False}
        others = [d for d in KNOWN_2024_DRIVERS if normalize_str(d) != normalize_str(ent) and entity_in_text(ans, d)]
        if others:
            return {"status": "FAILED", "reason": f"Competing driver(s) {others} mentioned: {ans[:150]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"Matched {ent} unambiguously", "evidence_grounded": True}

    # 2. Podium (exact 3 entities and order)
    if ctype == "podium":
        entities = criteria["entities"]
        positions_in_text = []
        low = normalize_str(ans)
        for ent in entities:
            if not entity_in_text(ans, ent):
                return {"status": "FAILED", "reason": f"Missing podium driver {ent}; got: {ans[:150]}", "evidence_grounded": False}
            m = re.search(rf"(?<![a-z0-9]){re.escape(normalize_str(ent))}(?![a-z0-9])", low)
            if not m:
                m = re.search(rf"(?<![a-z0-9]){re.escape(normalize_str(ent.split()[-1]))}(?![a-z0-9])", low)
            positions_in_text.append(m.start() if m else -1)
        if positions_in_text != sorted(positions_in_text):
            return {"status": "FAILED", "reason": f"Podium order mismatch in: {ans[:150]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"Podium matched in exact order: {entities}", "evidence_grounded": True}

    # 3. Single driver finish position
    if ctype == "driver_position":
        drv = criteria["driver"]
        pos = int(criteria["position"])
        for cl in split_clauses(ans):
            if entity_in_text(cl, drv) and contains_exact_position(cl, pos):
                return {"status": "PASSED", "reason": f"Matched {drv} at P{pos}", "evidence_grounded": True}
        return {"status": "FAILED", "reason": f"Missing {drv} P{pos} in same clause; got: {ans[:150]}", "evidence_grounded": False}

    # 4. Entity + exact/close numeric value in same clause
    if ctype == "entity_and_number":
        ent = criteria["entity"]
        num = float(criteria["number"])
        tol = float(criteria.get("tolerance", 0.5))
        for cl in split_clauses(ans):
            if entity_in_text(cl, ent) and has_number_close(cl, num, tol):
                return {"status": "PASSED", "reason": f"Matched {ent} with {num}", "evidence_grounded": True}
        return {"status": "FAILED", "reason": f"Missing {ent} + {num} in same clause; got: {ans[:150]}", "evidence_grounded": False}

    # 5. Entity + exact position in same clause
    if ctype == "entity_and_position":
        ent = criteria["entity"]
        pos = int(criteria["position"])
        for cl in split_clauses(ans):
            if entity_in_text(cl, ent) and contains_exact_position(cl, pos):
                return {"status": "PASSED", "reason": f"Matched {ent} at position {pos}", "evidence_grounded": True}
        return {"status": "FAILED", "reason": f"Missing {ent} + P{pos} in same clause; got: {ans[:150]}", "evidence_grounded": False}

    # 6. Clauses (multi-driver standings, classifications, comparisons)
    if ctype == "clauses":
        cls = split_clauses(ans)
        for req in criteria["clauses"]:
            ent = req["entity"]
            matched = False
            for cl in cls:
                if not entity_in_text(cl, ent):
                    continue
                if "position" in req and not contains_exact_position(cl, int(req["position"])):
                    continue
                if "number" in req and not has_number_close(cl, float(req["number"]), float(req.get("tolerance", 0.5))):
                    continue
                matched = True
                break
            if not matched:
                return {"status": "FAILED", "reason": f"Clause mismatch for {req}; got: {ans[:160]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"All {len(criteria['clauses'])} clauses matched", "evidence_grounded": True}

    # 7. Team result
    if ctype == "team_result":
        cls = split_clauses(ans)
        for drv in criteria["drivers"]:
            name = drv["name"]
            pos = int(drv["position"])
            if not any(entity_in_text(cl, name) and contains_exact_position(cl, pos) for cl in cls):
                return {"status": "FAILED", "reason": f"Missing {name} P{pos} in team result; got: {ans[:160]}", "evidence_grounded": False}
        return {"status": "PASSED", "reason": f"Matched team {criteria['team']} results", "evidence_grounded": True}

    # 8. Dry vs wet check
    if ctype == "dry_wet":
        exp_dry = bool(criteria["expected_dry"])
        has_dry, has_wet = _detect_weather_polarity(ans)
        if exp_dry:
            if has_dry and not has_wet:
                return {"status": "PASSED", "reason": "Correctly reported dry race", "evidence_grounded": True}
            return {"status": "FAILED", "reason": f"Expected dry (has_dry={has_dry}, has_wet={has_wet}); got: {ans[:150]}", "evidence_grounded": False}
        else:
            if has_wet and not has_dry:
                return {"status": "PASSED", "reason": "Correctly reported wet/rain conditions", "evidence_grounded": True}
            return {"status": "FAILED", "reason": f"Expected wet (has_dry={has_dry}, has_wet={has_wet}); got: {ans[:150]}", "evidence_grounded": False}

    # 9. Weather summary
    if ctype == "weather_summary":
        has_dry, has_wet = _detect_weather_polarity(ans)
        pol_ok = (has_dry and not has_wet) if criteria["expected_dry"] else has_wet
        tol = float(criteria.get("tolerance", 0.5))
        air_ok = has_number_close(ans, float(criteria["avg_air"]), tol)
        trk_ok = has_number_close(ans, float(criteria["avg_track"]), tol)
        if pol_ok and air_ok and trk_ok:
            return {"status": "PASSED", "reason": "Weather summary matched rainfall, air, and track temp", "evidence_grounded": True}
        return {"status": "FAILED", "reason": f"Weather mismatch (pol={pol_ok}, air={air_ok}, trk={trk_ok}); got: {ans[:160]}", "evidence_grounded": False}

    # 10. Single weather numeric probe
    if ctype == "weather_number":
        num = float(criteria["number"])
        tol = float(criteria.get("tolerance", 0.5))
        if has_number_close(ans, num, tol):
            return {"status": "PASSED", "reason": f"Matched weather number {num} +/- {tol}", "evidence_grounded": True}
        return {"status": "FAILED", "reason": f"Missing weather number {num}; got: {ans[:150]}", "evidence_grounded": False}

    # 11. Weather min-max range
    if ctype == "weather_range":
        tol = float(criteria.get("tolerance", 0.5))
        ok_min = has_number_close(ans, float(criteria["min_val"]), tol)
        ok_max = has_number_close(ans, float(criteria["max_val"]), tol)
        if ok_min and ok_max:
            return {"status": "PASSED", "reason": f"Matched range {criteria['min_val']}-{criteria['max_val']}", "evidence_grounded": True}
        return {"status": "FAILED", "reason": f"Missing range bounds ({ok_min}/{ok_max}); got: {ans[:150]}", "evidence_grounded": False}

    # 12. Token set (tyre compounds)
    if ctype == "token_set":
        low = normalize_str(ans)
        req = [t.lower() for t in criteria["required"]]
        forb = [t.lower() for t in criteria.get("forbidden", [])]
        miss = [t for t in req if not re.search(rf"\b{re.escape(t)}\b", low)]
        extra = [t for t in forb if re.search(rf"\b{re.escape(t)}\b", low)]
        if not miss and not extra:
            return {"status": "PASSED", "reason": f"Matched exact compound set {criteria['required']}", "evidence_grounded": True}
        return {"status": "FAILED", "reason": f"Token set mismatch miss={miss}, forbidden={extra}; got: {ans[:150]}", "evidence_grounded": False}

    # 13. Entity set (points scorers / retirements)
    if ctype == "entity_set":
        hits = [e for e in criteria["must_include"] if entity_in_text(ans, e)]
        min_m = int(criteria.get("min_matches", len(criteria["must_include"])))
        if len(hits) >= min_m:
            return {"status": "PASSED", "reason": f"Matched {len(hits)}/{len(criteria['must_include'])} required entities", "evidence_grounded": True}
        return {"status": "FAILED", "reason": f"Only {len(hits)}/{min_m} matched ({hits}); got: {ans[:160]}", "evidence_grounded": False}

    # 14. RAG complete narrative / race report
    if ctype == "rag_complete":
        ret_ids = [str(x) for x in telemetry.get("retrieval_ids", [])]
        exp_ids = [str(x) for x in criteria.get("expected_source_ids", [])]
        source_hit = any(any(exp == rid or exp in rid for rid in ret_ids) for exp in exp_ids)
        raw_ctx = telemetry.get("retrieval_raw_context", "")
        support_ratio = _token_support_ratio(ans, raw_ctx)
        min_sup = float(criteria.get("min_support_ratio", 0.45))
        req_ents = criteria.get("must_mention_all", [])
        missing = [m for m in req_ents if not entity_in_text(ans, m)]
        grounded = bool(raw_ctx.strip()) and support_ratio >= min_sup and source_hit
        if source_hit and grounded and not missing:
            return {
                "status": "PASSED",
                "reason": f"Retrieved {exp_ids}, complete mentions, support={support_ratio:.2f}",
                "evidence_grounded": True,
                "support_ratio": round(support_ratio, 3),
                "source_hit": source_hit,
            }
        return {
            "status": "FAILED",
            "reason": f"source_hit={source_hit}, support={support_ratio:.2f}, missing={missing}; ans={ans[:150]}",
            "evidence_grounded": grounded,
            "support_ratio": round(support_ratio, 3),
            "source_hit": source_hit,
        }

    # 15. RAG metadata/fact probe
    if ctype == "rag_fact":
        ret_ids = [str(x) for x in telemetry.get("retrieval_ids", [])]
        exp_ids = [str(x) for x in criteria.get("expected_source_ids", [])]
        source_hit = any(any(exp == rid or exp in rid for rid in ret_ids) for exp in exp_ids)
        raw_ctx = telemetry.get("retrieval_raw_context", "")
        support_ratio = _token_support_ratio(ans, raw_ctx)
        min_sup = float(criteria.get("min_support_ratio", 0.40))
        target_num = float(criteria["must_contain_number"])
        has_num = has_number_close(ans, target_num, 0.01)
        grounded = bool(raw_ctx.strip()) and support_ratio >= min_sup and source_hit
        if source_hit and has_num and grounded:
            return {
                "status": "PASSED",
                "reason": f"Retrieved {exp_ids}, extracted fact {int(target_num)}, support={support_ratio:.2f}",
                "evidence_grounded": True,
                "support_ratio": round(support_ratio, 3),
                "source_hit": source_hit,
            }
        return {
            "status": "FAILED",
            "reason": f"source_hit={source_hit}, has_num={has_num}, support={support_ratio:.2f}; ans={ans[:150]}",
            "evidence_grounded": grounded,
            "support_ratio": round(support_ratio, 3),
            "source_hit": source_hit,
        }

    return {"status": "UNSCORABLE", "reason": f"Unknown criteria type '{ctype}'", "evidence_grounded": None}


def check_entity_resolution(case: dict[str, Any], intent_entities: dict[str, Any], plan_params: dict[str, Any]) -> bool | None:
    req = case.get("required_entities") or {}
    req_drivers = req.get("drivers") or []
    req_teams = req.get("constructors") or []
    if not req_drivers and not req_teams:
        return None
    q_norm = normalize_str(case["question"])
    expected_from_q_drivers = [
        normalize_str(d) for d in req_drivers
        if any(re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", q_norm) for v in entity_variants(d))
    ]
    expected_from_q_teams = [
        normalize_str(t) for t in req_teams
        if any(re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", q_norm) for v in entity_variants(t))
    ]
    if not expected_from_q_drivers and not expected_from_q_teams:
        return None

    resolved_drivers = {normalize_str(d) for d in (intent_entities.get("all_drivers") or [])}
    if plan_params.get("driver_name"):
        resolved_drivers.add(normalize_str(plan_params["driver_name"]))
    resolved_teams = {normalize_str(t) for t in (intent_entities.get("all_constructors") or [])}
    if plan_params.get("team_name"):
        resolved_teams.add(normalize_str(plan_params["team_name"]))

    return all(d in resolved_drivers for d in expected_from_q_drivers) and all(t in resolved_teams for t in expected_from_q_teams)


def check_event_season_resolution(
    case: dict[str, Any],
    intent_entities: dict[str, Any],
    plan_params: dict[str, Any],
    retriever_filters: dict[str, Any],
    domain_valid: bool,
) -> bool | None:
    req_ev = case.get("required_event")
    req_season = case.get("required_season")
    if not req_ev and req_season in (None, 2024):
        return None
    if not domain_valid:
        return None

    resolved_ev = plan_params.get("event_name") or intent_entities.get("race_name") or retriever_filters.get("race_name")
    resolved_season = plan_params.get("season_year") or intent_entities.get("season") or retriever_filters.get("season")

    ev_ok = (normalize_str(resolved_ev) == normalize_str(req_ev)) if req_ev else True
    season_ok = (resolved_season == req_season) if req_season else True
    return bool(ev_ok and season_ok)


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
    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    dataset = json.loads(dataset_bytes.decode("utf-8"))
    cases = dataset["cases"]

    service = ChatService(offline=True)
    per_case_results: list[dict[str, Any]] = []

    for idx, case in enumerate(cases, start=1):
        q = case["question"]
        t0 = time.time()
        calls_before = GeminiClient.get_external_call_count()

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
        ent_ok = check_entity_resolution(case, telemetry["intent_entities"], telemetry["query_plan_parameters"])
        ev_season_ok = check_event_season_resolution(
            case, telemetry["intent_entities"], telemetry["query_plan_parameters"], filters, domain_res.is_valid
        )

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
            "retrieval_source_hit": eval_out.get("source_hit"),
            "intent_matched": (actual_intent == case["expected_intent"]),
            "route_matched": (actual_route == case["expected_route"]),
            "entity_resolution_ok": ent_ok,
            "event_season_resolution_ok": ev_season_ok,
            "external_api_calls": calls_delta,
            "latency_ms": latency_ms,
            "telemetry": telemetry_clean,
        })
        print(f"[{idx:02d}/{len(cases)}] {case['id']} ({case['category']}): {eval_out['status']} | route={actual_route} (exp={case['expected_route']})")

    total = len(per_case_results)
    passed = sum(1 for r in per_case_results if r["status"] == "PASSED")
    failed = sum(1 for r in per_case_results if r["status"] == "FAILED")
    unscorable = sum(1 for r in per_case_results if r["status"] == "UNSCORABLE")

    cat_metrics: dict[str, Any] = {}
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in per_case_results:
        by_cat[r["category"]].append(r)
    for cat, items in by_cat.items():
        cat_metrics[cat] = format_ratio(sum(1 for r in items if r["status"] == "PASSED"), len(items))

    exp_sql = [r for r in per_case_results if r["expected_route"] == "SQL"]
    sql_routed = sum(1 for r in exp_sql if r["telemetry"]["actual_route"] == "SQL")
    sql_passed = sum(1 for r in exp_sql if r["status"] == "PASSED")

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

    rag_ans = [r for r in per_case_results if r["expected_route"] == "RAG" and r["answerability_status"] == "answerable"]
    rag_ret_hits = sum(1 for r in rag_ans if r.get("retrieval_source_hit") is True)
    rag_passed = sum(1 for r in rag_ans if r["status"] == "PASSED")

    abst_cases = [r for r in per_case_results if r["answerability_status"] == "unanswerable"]
    abst_correct = sum(1 for r in abst_cases if r["status"] == "PASSED")
    in_dom_unans = [r for r in abst_cases if r["category"] == "unanswerable_in_domain"]
    in_dom_unans_ok = sum(1 for r in in_dom_unans if r["status"] == "PASSED")

    answerable = [r for r in per_case_results if r["answerability_status"] == "answerable"]
    false_abst = sum(1 for r in answerable if is_refusal(r["actual_answer"]))

    metrics = {
        "counts": {"total": total, "passed": passed, "failed": failed, "unscorable": unscorable},
        "overall_answer_accuracy": format_ratio(passed, total - unscorable),
        "category_accuracy": cat_metrics,
        "sql_routing_accuracy": format_ratio(sql_routed, len(exp_sql)),
        "sql_end_to_end_accuracy": format_ratio(sql_passed, len(exp_sql)),
        "intent_classification_accuracy": format_ratio(intent_matched, total),
        "entity_resolution_accuracy": format_ratio(ent_ok_cnt, len(ent_eval)),
        "event_season_resolution_accuracy": format_ratio(ev_ok_cnt, len(ev_eval)),
        "ambiguity_handling_accuracy": format_ratio(amb_ok, len(amb_cases)),
        "domain_guard_block_accuracy": format_ratio(dg_blocked, len(dg_cases)),
        "domain_rejection_end_to_end_accuracy": format_ratio(dg_end_to_end, len(dg_cases)),
        "rag_retrieval_source_hit_rate": format_ratio(rag_ret_hits, len(rag_ans)),
        "rag_answerable_complete_accuracy": format_ratio(rag_passed, len(rag_ans)),
        "correct_abstention_all_unanswerable": format_ratio(abst_correct, len(abst_cases)),
        "correct_abstention_in_domain_unanswerable": format_ratio(in_dom_unans_ok, len(in_dom_unans)),
        "false_abstention_rate": format_ratio(false_abst, len(answerable)),
        "external_api_calls_attempted": GeminiClient.get_external_call_count(),
        "total_duration_seconds": round(time.time() - start_time, 2),
    }

    output = {
        "benchmark_name": dataset["benchmark_name"],
        "benchmark_version": dataset["benchmark_version"],
        "benchmark_sha256": dataset_sha256,
        "runner_sha256": runner_sha256,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "offline_mode": True,
        "metrics": metrics,
        "results": per_case_results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n" + "=" * 64)
    print("PHASE 5D INDEPENDENT BENCHMARK V2 SUMMARY (STRICT OFFLINE)")
    print("=" * 64)
    for k, v in metrics.items():
        if isinstance(v, dict) and "numerator" in v:
            print(f"{k:44s}: {v['numerator']}/{v['denominator']} ({v['percent']})")
    print("-" * 64)
    for cat, v in cat_metrics.items():
        print(f"  {cat:40s}: {v['numerator']}/{v['denominator']} ({v['percent']})")
    print(f"External API calls attempted: {metrics['external_api_calls_attempted']}")
    print(f"Results written to: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
