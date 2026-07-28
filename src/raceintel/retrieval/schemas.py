from dataclasses import dataclass
from typing import Any


@dataclass
class RaceDocument:

    id: str
    text: str
    metadata: dict[str, Any]