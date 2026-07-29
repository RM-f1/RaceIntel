from raceintel.retrieval.schemas import RaceDocument


class RaceDocumentGenerator:
    """
    Generates documents that will be stored in ChromaDB.
    """

    @staticmethod
    def generate_race_report(
        season,
        round_number,
        grand_prix,
        winner,
        podium,
        classification,
        fastest_lap,
        summary,
    ) -> RaceDocument:

        text = f"""
Season: {season}

Round: {round_number}

Grand Prix: {grand_prix}

Winner:
{winner}

Podium:
1. {podium[0]}
2. {podium[1]}
3. {podium[2]}

Classification:
{classification}

Fastest Lap:
{fastest_lap}

Race Summary:
{summary}
""".strip()

        metadata = {
            "season": season,
            "round": round_number,
            "grand_prix": grand_prix,
            "winner": winner,
            "source": "race_report",
        }

        return RaceDocument(
            id=f"{season}_{round_number}",
            text=text,
            metadata=metadata,
        )

    @staticmethod
    def generate_driver_summary(
        season: int,
        round_number: int,
        grand_prix: str,
        driver: str,
        constructor: str,
        finish_position: int,
        points: float,
    ) -> RaceDocument:

        text = f"""
Season: {season}

Round: {round_number}

Grand Prix: {grand_prix}

Driver:
{driver}

Constructor:
{constructor}

Finished:
P{finish_position}

Points:
{points}
""".strip()

        metadata = {
            "season": season,
            "round": round_number,
            "grand_prix": grand_prix,
            "driver": driver,
            "constructor": constructor,
            "source": "driver_summary",
        }

        return RaceDocument(
            id=f"{season}_{round_number}_{driver.replace(' ', '_')}",
            text=text,
            metadata=metadata,
        )