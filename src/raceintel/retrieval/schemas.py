from dataclasses import dataclass
from typing import Dict


@dataclass
class RaceDocument:
    id: str
    text: str
    metadata: Dict