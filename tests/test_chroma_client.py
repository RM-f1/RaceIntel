from pathlib import Path
import pytest

pytestmark = pytest.mark.requires_data

from raceintel.retrieval.chroma_client import ChromaClient
from raceintel.retrieval.generator import RaceDocumentGenerator


@pytest.fixture
def isolated_chroma(tmp_path: Path) -> ChromaClient:
    """Fixture providing a ChromaClient pointing to an isolated temporary directory."""
    temp_dir = tmp_path / "chroma_isolated"
    return ChromaClient(persist_directory=str(temp_dir))


def test_add_document(isolated_chroma: ChromaClient):
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

    isolated_chroma.add_document(document)

    assert isolated_chroma.count() == 1


def test_chroma_client_isolation(tmp_path: Path):
    """Regression test: verify that isolated test client operations do not alter production data/chroma."""
    prod_path = Path("data/chroma")
    prod_mtimes = {}
    if prod_path.exists():
        for p in prod_path.glob("**/*"):
            if p.is_file():
                prod_mtimes[p] = p.stat().st_mtime

    temp_dir = tmp_path / "regression_chroma"
    isolated_client = ChromaClient(persist_directory=str(temp_dir))

    doc = RaceDocumentGenerator.generate_driver_summary(
        season=2024,
        round_number=99,
        grand_prix="Test Isolation GP",
        driver="Test Driver",
        constructor="Test Team",
        finish_position=1,
        points=25.0,
        country="Test Country",
    )
    isolated_client.add_document(doc)

    assert isolated_client.count() == 1
    assert temp_dir.exists()

    # Verify no files in production data/chroma were modified or added
    if prod_path.exists():
        for p, mtime in prod_mtimes.items():
            assert p.stat().st_mtime == mtime, f"Production file {p} was modified by test!"