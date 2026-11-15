"""
Data Validation Service for RaceIntel.

Validates fetched F1 records, checking classification integrity, points,
driver codes, lap bounds, and weather plausibility before database persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from raceintel.data.fetcher import FetchedSessionData


@dataclass
class ValidationResult:
    is_valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SessionValidator:
    """Performs structural and relational sanity validation on fetched session payloads."""

    def validate(self, data: FetchedSessionData) -> ValidationResult:
        issues: list[str] = []
        warnings: list[str] = []

        if not (1950 <= data.season_year <= 2099):
            issues.append(f"Invalid season year: {data.season_year}")

        if data.round_number < 1:
            issues.append(f"Invalid round number: {data.round_number}")

        if not data.event_name or not data.event_name.strip():
            issues.append("Missing event name")

        # Result validation
        if data.has_results:
            if not data.results:
                issues.append("Results flag set but results list is empty")
            else:
                codes_seen = set()
                has_winner = False
                for idx, r in enumerate(data.results):
                    code = r.get("driver_code")
                    if not code or len(code) > 5:
                        issues.append(f"Invalid driver code at index {idx}: {code}")
                    elif code in codes_seen:
                        issues.append(f"Duplicate driver code in results: {code}")
                    codes_seen.add(code)

                    team = r.get("constructor_name")
                    if not team:
                        issues.append(f"Missing constructor name for driver {code}")

                    fin = r.get("finish_position")
                    if fin is not None:
                        if fin == 1:
                            has_winner = True
                        if fin < 1:
                            issues.append(f"Invalid finish position for {code}: {fin}")

                    pts = r.get("points_scored")
                    if pts is not None and pts < 0:
                        issues.append(f"Negative points scored for {code}: {pts}")

                if not has_winner:
                    warnings.append(f"No P1 winner found in classification for {data.event_name}")
        else:
            # If no results, this is expected for scheduled upcoming events
            pass

        # Laps validation
        if data.has_laps and data.laps:
            lap_keys_seen = set()
            for l in data.laps:
                code = l.get("driver_code")
                lnum = l.get("lap_number")
                if not code or lnum is None or lnum < 1:
                    issues.append(f"Invalid lap key: driver={code}, lap_number={lnum}")
                    break
                key = (code, lnum)
                if key in lap_keys_seen:
                    warnings.append(f"Duplicate lap record detected for {code} on lap {lnum}")
                lap_keys_seen.add(key)

                ltime = l.get("lap_time_seconds")
                if ltime is not None and ltime <= 0:
                    warnings.append(f"Suspicious lap time for {code} on lap {lnum}: {ltime}s")

        # Weather validation
        if data.has_weather and data.weather:
            for w in data.weather:
                air = w.get("air_temperature_celsius")
                if air is not None and not (-20.0 <= air <= 70.0):
                    warnings.append(f"Plausibility warning: Extreme air temperature {air}C")
                    break

        return ValidationResult(
            is_valid=len(issues) == 0,
            issues=issues,
            warnings=warnings,
        )
