"""
Shared text normalization and Formula 1 event/circuit/country alias definitions.

Kept dependency-free so both services (session_service) and routing (EntityRegistry)
can share a single canonical source of truth without circular imports.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    """
    Normalize text for robust comparison:
    - Strip accents/diacritics (e.g., 'São Paulo' -> 'Sao Paulo', 'Montréal' -> 'Montreal')
    - Handle legacy Latin-1 replacement characters (e.g. S\ufffdo Paulo -> Sao Paulo, Montr\ufffdal -> Montreal)
    - Lowercase
    - Replace punctuation with single spaces
    - Collapse repeated whitespace
    """
    if not text:
        return ""
    text = re.sub(r"s\ufffdo", "sao", text, flags=re.IGNORECASE)
    text = re.sub(r"montr\ufffdal", "montreal", text, flags=re.IGNORECASE)
    text = text.replace("\ufffd", "")
    nfkd_form = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd_form if not unicodedata.combining(c))
    cleaned = re.sub(r"[\?,\.\-\/\\_\'\"]+", " ", stripped)
    cleaned = cleaned.lower()
    return " ".join(cleaned.split())


def strip_gp_suffix(norm_text: str) -> str:
    """Remove 'grand prix' / 'gp' qualifier tokens from normalized event text."""
    if not norm_text:
        return ""
    stripped = re.sub(r"\b(?:grand\s+prix|grandprix|gp)\b", " ", norm_text)
    return " ".join(stripped.split())


KNOWN_CIRCUIT_ALIASES: dict[str, list[str]] = {
    "silverstone": ["silverstone"],
    "sakhir": ["sakhir", "bahrain international circuit"],
    "jeddah": ["jeddah", "jeddah corniche", "corniche"],
    "melbourne": ["melbourne", "albert park"],
    "suzuka": ["suzuka"],
    "shanghai": ["shanghai", "shanghai international circuit"],
    "miami": ["miami", "miami international autodrome"],
    "imola": ["imola", "autodromo enzo e dino ferrari"],
    "monaco": ["monaco", "monte carlo"],
    "montreal": ["montreal", "circuit gilles villeneuve", "gilles villeneuve"],
    "barcelona": ["barcelona", "catalunya", "circuit de barcelona catalunya"],
    "spielberg": ["spielberg", "red bull ring"],
    "budapest": ["budapest", "hungaroring"],
    "spa francorchamps": ["spa", "spa francorchamps", "circuit de spa francorchamps"],
    "zandvoort": ["zandvoort", "circuit zandvoort"],
    "monza": ["monza", "autodromo nazionale monza"],
    "baku": ["baku", "baku city circuit"],
    "marina bay": ["marina bay", "marina bay street circuit"],
    "austin": ["austin", "cota", "circuit of the americas"],
    "mexico city": ["mexico city", "autodromo hermanos rodriguez", "hermanos rodriguez"],
    "sao paulo": ["sao paulo", "interlagos", "autodromo jose carlos pace"],
    "las vegas": ["las vegas", "las vegas strip", "vegas"],
    "lusail": ["lusail", "losail", "lusail international circuit"],
    "yas island": ["yas island", "yas marina", "yas marina circuit"],
}

COUNTRY_ALIASES: dict[str, list[str]] = {
    "united kingdom": ["british", "britain", "uk", "great britain"],
    "bahrain": ["bahraini", "bahrain"],
    "saudi arabia": ["saudi", "saudi arabian"],
    "australia": ["australian", "australia"],
    "japan": ["japanese", "japan"],
    "china": ["chinese", "china"],
    "united states": ["usa", "us", "united states", "american"],
    "italy": ["italy"],
    "monaco": ["monegasque", "monaco"],
    "canada": ["canadian", "canada"],
    "spain": ["spanish", "spain"],
    "austria": ["austrian", "austria"],
    "hungary": ["hungarian", "hungary"],
    "belgium": ["belgian", "belgium"],
    "netherlands": ["dutch", "netherlands", "holland"],
    "azerbaijan": ["azerbaijani", "azerbaijan"],
    "singapore": ["singapore"],
    "mexico": ["mexican", "mexico"],
    "brazil": ["brazilian", "brazil"],
    "qatar": ["qatari", "qatar"],
    "united arab emirates": ["uae", "emirati", "abu dhabi"],
}

# Explicit event-specific aliases mapped to canonical event names (checked before circuit/country).
EXPLICIT_EVENT_ALIASES: dict[str, list[str]] = {
    "united states grand prix": ["us grand prix", "us gp", "usa grand prix", "usa gp"],
    "british grand prix": ["uk grand prix", "uk gp", "great britain grand prix", "great britain gp"],
    "emilia romagna grand prix": ["emilia romagna", "emilia"],
    "sao paulo grand prix": ["brazilian grand prix", "brazil gp"],
    "las vegas grand prix": ["vegas gp", "las vegas gp"],
    "abu dhabi grand prix": ["uae grand prix", "uae gp"],
}
