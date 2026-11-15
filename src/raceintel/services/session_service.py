from sqlalchemy.orm import Session

from database.models import Event
from database.models import Season
from database.models import Session as RaceSession


def get_sessions(
    db: Session,
    season: int | None = None,
):
   

    query = (
        db.query(RaceSession)
        .join(Event)
        .join(Season)
    )

    if season is not None:
        query = query.filter(
            Season.season_year == season
        )

    return query.order_by(
        Season.season_year.desc(),
        Event.event_name,
        RaceSession.session_name,
    ).all()


from pathlib import Path
import re
import sqlite3
import pandas as pd

from database.connection import query_to_dataframe
from raceintel.services.event_aliases import (
    COUNTRY_ALIASES,
    EXPLICIT_EVENT_ALIASES,
    KNOWN_CIRCUIT_ALIASES,
    normalize_text,
    strip_gp_suffix,
)


def _strip_accents(text: str) -> str:
    """Normalize and remove diacritics / replacement artifacts for robust string matching."""
    return normalize_text(text)


def _query_sessions_df(query: str, params: dict, db_path: Path | str | None = None) -> pd.DataFrame:
    """Execute session lookup against either default engine or an isolated SQLite db_path."""
    if db_path is None:
        return query_to_dataframe(query, params)

    path_obj = Path(db_path)
    try:
        conn = sqlite3.connect(f"file:{path_obj.resolve().as_posix()}?mode=ro", uri=True)
    except Exception:
        conn = sqlite3.connect(str(path_obj))
    try:
        cur = conn.execute(query, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    finally:
        conn.close()


def _match_candidates(
    target_norm: str,
    alias_to_rows: dict[str, list[dict]],
) -> list[dict]:
    """
    Match target_norm against candidate alias->rows mapping.
    Checks exact normalized key equality first, then non-overlapping word-boundary
    matches sorted by descending alias specificity (length).
    """
    if target_norm in alias_to_rows:
        return list(alias_to_rows[target_norm])

    matched: list[dict] = []
    occupied_spans: list[tuple[int, int]] = []
    for alias_key in sorted(alias_to_rows.keys(), key=len, reverse=True):
        if not alias_key:
            continue
        for m in re.finditer(rf"\b{re.escape(alias_key)}\b", target_norm):
            start, end = m.span()
            if any(not (end <= s or start >= e) for s, e in occupied_spans):
                continue
            occupied_spans.append((start, end))
            matched.extend(alias_to_rows[alias_key])
    return matched


def _dedupe_session_rows(rows: list[dict]) -> list[dict]:
    """Deduplicate matched session rows by session_id preserving order."""
    seen: set[int] = set()
    unique: list[dict] = []
    for row in rows:
        sid = int(row["session_id"])
        if sid not in seen:
            seen.add(sid)
            unique.append(row)
    return unique


def resolve_race_session(
    race_name: str,
    season: int | None = 2024,
    session_type: str = "Race",
    db_path: Path | str | None = None,
) -> dict | None:
    """
    Resolve a user-provided race, circuit, alias, or country name (and optional season)
    to a verified SQLite session record using deterministic multi-stage priority:
      Priority 1 — Exact event name
      Priority 2 — Event-specific aliases
      Priority 3 — Circuit and venue aliases
      Priority 4 — Season-aware filtering & disambiguation
      Priority 5 — Country fallback (only when no event/circuit matches)

    Never allows a country alias to override an explicit event name or circuit,
    and never arbitrarily selects the first matching session when multiple events match.
    """
    if not race_name or not str(race_name).strip():
        return None

    target_norm = normalize_text(str(race_name))
    if not target_norm:
        return None

    if re.search(r"\bsprints?\b", target_norm):
        session_type = "Sprint"
        target_norm = re.sub(r"\bsprints?\b", "", target_norm).strip()
        target_norm = re.sub(r"\s+", " ", target_norm)

    # Check available seasons (Priority 4 pre-check)
    season_df = _query_sessions_df("SELECT season_id, season_year FROM seasons;", {}, db_path=db_path)
    available_seasons = (
        {int(y) for y in season_df["season_year"].tolist()} if not season_df.empty else set()
    )

    if season is not None and available_seasons and season not in available_seasons:
        return {
            "found": False,
            "reason": "season_not_found",
            "season": season,
            "available_seasons": sorted(list(available_seasons)),
        }

    q = """
        SELECT
            s.session_id,
            s.session_type,
            e.event_id,
            e.event_name,
            e.country_name,
            e.circuit_name,
            se.season_year
        FROM sessions s
        JOIN events e ON s.event_id = e.event_id
        JOIN seasons se ON e.season_id = se.season_id
        WHERE (:season IS NULL OR se.season_year = :season)
          AND s.session_type = :session_type
        ORDER BY se.season_year DESC, s.session_id ASC;
    """
    df = _query_sessions_df(
        q,
        {"season": season, "session_type": session_type},
        db_path=db_path,
    )
    if df.empty:
        return {
            "found": False,
            "reason": "no_sessions",
            "season": season,
        }

    rows = [dict(row) for _, row in df.iterrows()]
    country_norm_set = {
        normalize_text(str(r["country_name"]))
        for r in rows
        if r.get("country_name")
    }

    has_gp_qualifier = bool(re.search(r"\b(?:grand\s+prix|grandprix|gp)\b", target_norm))
    target_stem = strip_gp_suffix(target_norm)

    # Build stage candidate maps strictly scoped to the rows retrieved for the active season
    exact_event_map: dict[str, list[dict]] = {}
    event_alias_map: dict[str, list[dict]] = {}
    circuit_map: dict[str, list[dict]] = {}
    country_map: dict[str, list[dict]] = {}

    def _add(m: dict[str, list[dict]], key: str, row: dict) -> None:
        if key:
            m.setdefault(key, []).append(row)

    for row in rows:
        ev_norm = normalize_text(str(row["event_name"]))
        ev_stem = strip_gp_suffix(ev_norm)

        # Priority 1: Exact normalized event name & explicit "<stem> gp/grand prix"
        _add(exact_event_map, ev_norm, row)
        if ev_stem:
            _add(exact_event_map, f"{ev_stem} grand prix", row)
            _add(exact_event_map, f"{ev_stem} gp", row)
            # Bare event stem counts as an event alias only when not equal to a country name
            # (or when no country collisions exist). Country strings go to Priority 5.
            if ev_stem not in country_norm_set:
                _add(event_alias_map, ev_stem, row)

        # Priority 2: Event-specific aliases
        for canon_ev_norm, ev_aliases in EXPLICIT_EVENT_ALIASES.items():
            if ev_norm == canon_ev_norm:
                for alias in ev_aliases:
                    _add(event_alias_map, normalize_text(alias), row)

        # Priority 3: Circuit and venue aliases
        raw_circuit = str(row.get("circuit_name") or "")
        circuit_norm = normalize_text(raw_circuit)
        if circuit_norm:
            _add(circuit_map, circuit_norm, row)
            if ev_stem and ev_stem == circuit_norm:
                # Circuit-named Grands Prix (e.g., Miami, Monaco) retain circuit association
                pass
            for base_circ, circ_aliases in KNOWN_CIRCUIT_ALIASES.items():
                norm_base = normalize_text(base_circ)
                if (
                    norm_base == circuit_norm
                    or re.search(rf"\b{re.escape(norm_base)}\b", circuit_norm)
                    or re.search(rf"\b{re.escape(circuit_norm)}\b", norm_base)
                ):
                    for alias in circ_aliases:
                        _add(circuit_map, normalize_text(alias), row)

        # Priority 5: Country fallback
        raw_country = str(row.get("country_name") or "")
        country_norm = normalize_text(raw_country)
        if country_norm:
            _add(country_map, country_norm, row)
            for base_country, c_aliases in COUNTRY_ALIASES.items():
                if normalize_text(base_country) == country_norm:
                    for alias in c_aliases:
                        _add(country_map, normalize_text(alias), row)

    # Stage 1: Exact event name (with special care for explicit "<stem> gp" vs bare country)
    stage_name: str | None = None
    matched_rows: list[dict] = []

    if target_norm in exact_event_map:
        matched_rows = list(exact_event_map[target_norm])
        stage_name = "exact_event"
    elif has_gp_qualifier and target_stem:
        gp_query = f"{target_stem} grand prix"
        if gp_query in exact_event_map:
            matched_rows = list(exact_event_map[gp_query])
            stage_name = "exact_event"

    if not matched_rows:
        exact_contains = _match_candidates(target_norm, exact_event_map)
        if exact_contains:
            matched_rows = exact_contains
            stage_name = "exact_event"

    # Stage 2: Event aliases
    if not matched_rows:
        alias_matches = _match_candidates(target_norm, event_alias_map)
        if alias_matches:
            matched_rows = alias_matches
            stage_name = "event_alias"

    # Stage 3: Circuit & venue aliases
    if not matched_rows:
        circuit_matches = _match_candidates(target_norm, circuit_map)
        if circuit_matches:
            matched_rows = circuit_matches
            stage_name = "circuit_venue"

    # Stage 5: Country fallback (lowest priority)
    if not matched_rows:
        country_matches = _match_candidates(target_norm, country_map)
        if country_matches:
            matched_rows = country_matches
            stage_name = "country_fallback"

    unique_matches = _dedupe_session_rows(matched_rows)
    if not unique_matches:
        return {
            "found": False,
            "reason": "event_not_found",
            "race_name": race_name,
            "season": season,
        }

    # Priority 4: Verify unambiguous resolution across events & seasons
    if len(unique_matches) == 1:
        row = unique_matches[0]
        return {
            "found": True,
            "session_id": int(row["session_id"]),
            "session_type": str(row.get("session_type", session_type)),
            "event_id": int(row["event_id"]),
            "event_name": str(row["event_name"]),
            "season_year": int(row["season_year"]),
            "country_name": str(row["country_name"]) if row["country_name"] else None,
            "circuit_name": str(row["circuit_name"]) if row["circuit_name"] else None,
            "resolution_stage": stage_name,
        }

    distinct_event_names = list(dict.fromkeys(str(r["event_name"]) for r in unique_matches))
    distinct_seasons = sorted({int(r["season_year"]) for r in unique_matches})

    if season is None and len(distinct_event_names) == 1 and len(distinct_seasons) > 1:
        return {
            "found": False,
            "reason": "ambiguous_season",
            "race_name": race_name,
            "event_name": distinct_event_names[0],
            "available_seasons": distinct_seasons,
            "candidates": [f"{int(r['season_year'])} {r['event_name']}" for r in unique_matches],
        }

    return {
        "found": False,
        "reason": "ambiguous_event",
        "race_name": race_name,
        "season": season,
        "candidates": distinct_event_names,
    }