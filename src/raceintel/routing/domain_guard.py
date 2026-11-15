"""
Early Domain Guard for RaceIntel.

Validates questions BEFORE semantic retrieval and query processing:
1. Detects explicit out-of-domain motorsport inquiries (MotoGP, NASCAR, WEC, Bathurst 1000, IndyCar, etc.).
2. Distinguishes valid F1 comparison/context questions from explicit out-of-domain inquiries.
3. Validates season support against EntityRegistry, providing distinct historical season refusal.
4. Detects out-of-calendar F1 events (e.g., German Grand Prix, French Grand Prix).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from raceintel.routing.entity_registry import EntityRegistry, normalize_text


class DomainStatus(str, Enum):
    VALID = "valid"
    UNSUPPORTED_SEASON = "unsupported_season"
    OUT_OF_DOMAIN_MOTORSPORT = "out_of_domain_motorsport"
    OUT_OF_CALENDAR_EVENT = "out_of_calendar_event"


@dataclass
class DomainValidationResult:
    is_valid: bool
    status: DomainStatus
    reason: str
    season: int | None = None
    refusal_message: str | None = None


class DomainGuard:
    """
    Early boundary validation guard.
    Executed before ChromaDB vector retrieval and structured query routing.
    """

    # Unrelated motorsport series and signature non-F1 events
    UNRELATED_MOTORSPORTS: dict[str, list[str]] = {
        "motorcycle": [
            r"\bmotogp\b",
            r"\bmoto2\b",
            r"\bmoto3\b",
            r"\bsuperbike\b",
            r"\bworldsbk\b",
            r"\bwsbk\b",
            r"\bisle of man\b",
            r"\bisle of man tt\b",
        ],
        "stock_car": [
            r"\bnascar\b",
            r"\bcup series\b",
            r"\bxfinity\b",
            r"\bdaytona 500\b",
            r"\btalladega\b",
        ],
        "endurance_sports_car": [
            r"\bwec\b",
            r"\bworld endurance championship\b",
            r"\ble mans\b",
            r"\b24 hours of le mans\b",
            r"\bbathurst\b",
            r"\bbathurst 1000\b",
            r"\bimsa\b",
            r"\b12 hours of sebring\b",
            r"\bsebring 12\b",
            r"\brolex 24\b",
            r"\b24 hours of daytona\b",
            r"\baustralian supercars\b",
            r"\bsupercars championship\b",
        ],
        "other_open_wheel": [
            r"\bindycar\b",
            r"\bindy 500\b",
            r"\bindianapolis 500\b",
            r"\bformula e\b",
            r"\bsuper formula\b",
        ],
        "rally": [
            r"\bwrc\b",
            r"\bworld rally championship\b",
            r"\bdakar rally\b",
            r"\brallycross\b",
        ],
    }

    # Historical / discontinued Grand Prix events not in the 2024 calendar
    OUT_OF_CALENDAR_F1_VENUES: list[str] = [
        "german grand prix",
        "french grand prix",
        "russian grand prix",
        "turkish grand prix",
        "portuguese grand prix",
        "malaysian grand prix",
        "korean grand prix",
        "indian grand prix",
        "south african grand prix",
        "nurburgring",
        "hockenheim",
        "sepang",
        "sochi",
        "magny cours",
        "paul ricard",
        "estoril",
        "kyalami",
    ]

    # Comparison and contextual markers indicating cross-discipline analysis
    COMPARISON_MARKERS: list[str] = [
        "compared to",
        "compare to",
        "compare with",
        "compared with",
        "comparing to",
        "in comparison to",
        "in comparison with",
        "comparison",
        "versus",
        "vs",
        "faster than",
        "slower than",
        "better than",
        "more than",
        "less than",
        "as fast as",
        "relative to",
        "difference between",
        "unlike",
        "differ from",
        "ever raced in",
        "participated in",
        "career in",
        "former driver in",
        "transition from",
        "moved to",
        "compete against",
    ]

    def __init__(self, registry: EntityRegistry | None = None):
        self.registry = registry if registry is not None else EntityRegistry()

    def validate(self, question: str) -> DomainValidationResult:
        """
        Validate whether a question is an in-domain Formula 1 query for supported seasons.
        Returns DomainValidationResult with refusal message if out of domain.
        """
        if not question or not question.strip():
            return DomainValidationResult(
                is_valid=False,
                status=DomainStatus.OUT_OF_DOMAIN_MOTORSPORT,
                reason="Empty question",
                refusal_message="I couldn't find that information in the retrieved race data.",
            )

        q_norm = normalize_text(question)

        # ------------------------------------------------------------
        # 1. Season Validation
        # ------------------------------------------------------------
        # Extract explicit 4-digit years (1950 - 2099)
        season_matches = re.findall(r"\b(19\d{2}|20\d{2})\b", q_norm)
        if season_matches:
            for season_str in season_matches:
                season = int(season_str)
                if not self.registry.is_season_supported(season):
                    return DomainValidationResult(
                        is_valid=False,
                        status=DomainStatus.UNSUPPORTED_SEASON,
                        reason=f"Season {season} is not supported in the database.",
                        season=season,
                        refusal_message=(
                            f"I couldn't find that information in the retrieved race data. "
                            f"Historical data for season {season} is not available."
                        ),
                    )

        # ------------------------------------------------------------
        # 2. Out-of-Calendar F1 Events
        # ------------------------------------------------------------
        q_season = int(season_matches[0]) if season_matches else None
        ref_season = season_matches[0] if season_matches else "2024"
        for ooc_venue in self.OUT_OF_CALENDAR_F1_VENUES:
            if ooc_venue in q_norm:
                # Check if this venue is supported in the requested season (e.g. French GP in 2022)
                # or across any supported season if season is unspecified
                matched_ev = self.registry.resolve_event(ooc_venue, season=q_season)
                if matched_ev.matched or (q_season is None and (matched_ev.is_ambiguous or bool(matched_ev.candidates))):
                    continue

                return DomainValidationResult(
                    is_valid=False,
                    status=DomainStatus.OUT_OF_CALENDAR_EVENT,
                    reason=f"Event '{ooc_venue}' is not on the supported Formula 1 calendar.",
                    refusal_message=(
                        f"I couldn't find that information in the retrieved race data. "
                        f"That event is not part of the Formula 1 {ref_season} calendar."
                    ),
                )

        # ------------------------------------------------------------
        # 3. Unrelated Motorsport Validation
        # ------------------------------------------------------------
        unrelated_match = None
        matched_category = None
        for category, patterns in self.UNRELATED_MOTORSPORTS.items():
            for pat in patterns:
                if re.search(pat, q_norm, re.IGNORECASE):
                    unrelated_match = pat
                    matched_category = category
                    break
            if unrelated_match:
                break

        if unrelated_match:
            # Check if this is a genuine F1 question merely mentioning the series for comparison
            if self._is_f1_comparison(q_norm, question):
                return DomainValidationResult(
                    is_valid=True,
                    status=DomainStatus.VALID,
                    reason="In-domain Formula 1 query with comparative motorsport reference.",
                )

            return DomainValidationResult(
                is_valid=False,
                status=DomainStatus.OUT_OF_DOMAIN_MOTORSPORT,
                reason=f"Explicit inquiry regarding unrelated motorsport ({matched_category}).",
                refusal_message=(
                    "I couldn't find that information in the retrieved race data. "
                    f"That event is not part of the Formula 1 {ref_season} calendar."
                ),
            )

        # ------------------------------------------------------------
        # 3b. Dynamic Unrecognized Named Grand Prix Check
        # ------------------------------------------------------------
        generic_gp_tokens = {
            "the", "a", "an", "in", "at", "on", "of", "for", "to", "from", "about",
            "this", "that", "these", "those", "which", "what", "any", "each",
            "every", "next", "last", "first", "final", "sprint", "season", "year",
            "f1", "formula", "one", "1", "grand", "prix", "gp", "winning", "race",
            "world", "championship", "motorsport", "opening", "typical", "modern",
            "average", "wet", "dry", "inaugural",
        }
        for gp_match in re.finditer(r"\b([a-z0-9]+(?:\s+[a-z0-9]+)?)\s+grand\s+prix\b", q_norm):
            venue_words = [
                w for w in gp_match.group(1).split()
                if w not in generic_gp_tokens and not re.fullmatch(r"(?:19|20)\d{2}", w)
            ]
            if not venue_words:
                continue
            cand_phrase = " ".join(venue_words)
            full_phrase = f"{cand_phrase} grand prix"
            ev_full = self.registry.resolve_event(full_phrase, season=q_season)
            ev_cand = self.registry.resolve_event(cand_phrase, season=q_season)
            is_full_valid = ev_full.matched or (q_season is None and (ev_full.is_ambiguous or bool(ev_full.candidates)))
            is_cand_valid = ev_cand.matched or (q_season is None and (ev_cand.is_ambiguous or bool(ev_cand.candidates)))
            if not is_full_valid and not is_cand_valid:
                return DomainValidationResult(
                    is_valid=False,
                    status=DomainStatus.OUT_OF_CALENDAR_EVENT,
                    reason=f"Named event '{full_phrase}' is not on the supported Formula 1 calendar.",
                    refusal_message=(
                        f"I couldn't find that information in the retrieved race data. "
                        f"That event is not part of the Formula 1 {ref_season} calendar."
                    ),
                )

        # ------------------------------------------------------------
        # 4. In-Domain Valid Query
        # ------------------------------------------------------------
        return DomainValidationResult(
            is_valid=True,
            status=DomainStatus.VALID,
            reason="Query is in-domain.",
        )

    def _is_f1_comparison(self, q_norm: str, original_question: str) -> bool:
        """
        Determine whether a query mentioning an unrelated motorsport is
        actually a valid Formula 1 comparative inquiry.
        """
        # 1. Must contain comparison or cross-discipline markers
        has_comparison_marker = any(marker in q_norm for marker in self.COMPARISON_MARKERS)
        if not has_comparison_marker:
            return False

        # 2. Must reference Formula 1 entities (F1 keywords, Grand Prix, or verified drivers/circuits)
        f1_explicit_terms = [
            r"\bformula 1\b",
            r"\bformula one\b",
            r"\bf1\b",
            r"\bgrand prix\b",
        ]
        has_f1_term = any(re.search(term, q_norm) for term in f1_explicit_terms)

        # Check for verified F1 circuits or events from registry
        has_f1_event = False
        for ev in self.registry.events:
            ev_name = normalize_text(ev["event_name"])
            clean_name = ev_name.replace("grand prix", "").strip()
            circ_name = normalize_text(ev.get("circuit_name") or "")
            if (clean_name and clean_name in q_norm) or (circ_name and circ_name in q_norm):
                has_f1_event = True
                break

        # Check for verified F1 drivers from registry
        has_f1_driver = False
        for d in self.registry.drivers:
            d_name = normalize_text(d["driver_full_name"])
            surname = d_name.split()[-1] if d_name else ""
            if (d_name and d_name in q_norm) or (len(surname) > 3 and surname in q_norm):
                has_f1_driver = True
                break

        # Check for verified F1 constructors from registry
        has_f1_constructor = False
        for c in self.registry.constructors:
            c_name = normalize_text(c["constructor_name"])
            if c_name and c_name in q_norm:
                has_f1_constructor = True
                break

        if not (has_f1_term or has_f1_event or has_f1_driver or has_f1_constructor):
            return False

        # 3. Ensure the core inquiry clause is not directly requesting non-F1 results/winner/standings
        direct_non_f1_patterns = [
            r"who won the (?:20\d{2}\s+)?(?:motogp|nascar|wec|bathurst|indy|le mans)",
            r"who was (?:declared )?the winner of (?:the )?(?:20\d{2}\s+)?(?:motogp|nascar|wec|bathurst|indy|le mans)",
            r"who took the (?:chequered flag|victory) (?:at|in) (?:the )?(?:20\d{2}\s+)?(?:motogp|nascar|wec|bathurst|indy|le mans)",
            r"who is leading the (?:motogp|nascar|wec|indycar) (?:championship|standings)",
        ]
        if any(re.search(pat, q_norm) for pat in direct_non_f1_patterns):
            return False

        return True
