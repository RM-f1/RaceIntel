"""
Race report service.
"""

from analytics.race_report import generate_race_report


def get_race_report(session_id: int) -> dict:
   

    return generate_race_report(session_id)