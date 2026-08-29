from raceintel.retrieval.chroma_client import ChromaClient
from raceintel.retrieval.generator import RaceDocumentGenerator


def test_add_document():

    client = ChromaClient()

    document = RaceDocumentGenerator.generate_race_report(
        season=2024,
        round_number=12,
        grand_prix="British Grand Prix",
        winner="Lewis Hamilton",
        podium=[
            "Lewis Hamilton",
            "Max Verstappen",
            "Lando Norris",
        ],
        classification="1. Lewis Hamilton\n2. Max Verstappen\n3. Lando Norris",
        fastest_lap="Carlos Sainz",
        summary="Hamilton won after changing to intermediate tyres late in the race.",
        country="United Kingdom",
    )

    client.add_document(document)

    assert client.count() > 0