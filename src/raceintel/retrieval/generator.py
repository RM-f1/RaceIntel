from raceintel.retrieval.schemas import RaceDocument


class RaceDocumentGenerator:
    

    @staticmethod
    def generate_race_report(
        season: int,
        round_number: int,
        grand_prix: str,
        winner: str,
        podium: list[str],
        fastest_lap: str,
        summary: str,
    ) -> RaceDocument:
        """
        Generate a narrative race report document.
        """

        text = f"""
Season: {season}
Round: {round_number}
Grand Prix: {grand_prix}

Winner:
{winner}

Podium:
{", ".join(podium)}

Fastest Lap:
{fastest_lap}

Race Summary

{summary}
""".strip()

        metadata = {
            "season": season,
            "round": round_number,
            "race": grand_prix,
            "source": "race_report",
        }

        return RaceDocument(
            id=f"{season}_{round_number}_race_report",
            text=text,
            metadata=metadata,
        )