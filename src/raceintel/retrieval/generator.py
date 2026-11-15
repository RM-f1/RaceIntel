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
        country,
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
            "race_name": grand_prix,
            "document_type": "race_report",
            "country": country,
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
        country: str,
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
            "race_name": grand_prix,
            "driver": driver,
            "team": constructor,
            "country": country,
            "document_type": "driver_report",
        }

        return RaceDocument(
            id=f"{season}_{round_number}_{driver.replace(' ', '_')}",
            text=text,
            metadata=metadata,
        )

    @staticmethod
    def generate_sprint_report(
        season: int,
        round_number: int,
        grand_prix: str,
        winner: str,
        podium: list[str],
        classification: str,
        summary: str,
        country: str,
    ) -> RaceDocument:
        text = f"""
Season: {season}

Round: {round_number}

Grand Prix: {grand_prix}

Session: Sprint

Sprint Winner:
{winner}

Sprint Podium:
1. {podium[0]}
2. {podium[1]}
3. {podium[2]}

Sprint Classification:
{classification}

Sprint Summary:
{summary}
""".strip()

        metadata = {
            "season": season,
            "round": round_number,
            "race_name": grand_prix,
            "session_type": "Sprint",
            "document_type": "sprint_report",
            "country": country,
        }

        return RaceDocument(
            id=f"{season}_{round_number}_sprint",
            text=text,
            metadata=metadata,
        )

    @staticmethod
    def generate_driver_sprint_summary(
        season: int,
        round_number: int,
        grand_prix: str,
        driver: str,
        constructor: str,
        finish_position: int,
        points: float,
        country: str,
    ) -> RaceDocument:
        text = f"""
Season: {season}

Round: {round_number}

Grand Prix: {grand_prix}

Session: Sprint

Driver:
{driver}

Constructor:
{constructor}

Sprint Finished:
P{finish_position}

Sprint Points:
{points}
""".strip()

        metadata = {
            "season": season,
            "round": round_number,
            "race_name": grand_prix,
            "session_type": "Sprint",
            "driver": driver,
            "team": constructor,
            "country": country,
            "document_type": "driver_sprint_report",
        }

        return RaceDocument(
            id=f"{season}_{round_number}_sprint_{driver.replace(' ', '_')}",
            text=text,
            metadata=metadata,
        )