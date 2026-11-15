"""
Driver photograph catalog and retro terminal portrait rendering for RaceIntel.

Provides genuine Wikimedia Commons / public domain photographs for F1 drivers,
caches portraits locally, tracks attribution and licenses, and provides
clean retro terminal fallback avatars when a portrait is unavailable.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Any

import streamlit as st

CATALOG_PATH = Path(__file__).resolve().parent / "driver_photos_catalog.json"
ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "drivers"

# Driver code to ID mapping for stability
DRIVER_CODE_BY_ID: dict[int, str] = {
    1: "HAM",
    2: "VER",
    3: "NOR",
    4: "PIA",
    5: "SAI",
    6: "HUL",
    7: "STR",
    8: "ALO",
    9: "ALB",
    10: "TSU",
    11: "SAR",
    12: "MAG",
    13: "RIC",
    14: "LEC",
    15: "BOT",
    16: "OCO",
    17: "PER",
    18: "ZHO",
    19: "RUS",
    20: "GAS",
    21: "BEA",
    22: "COL",
    23: "LAW",
    24: "DOO",
    25: "MSC",
    26: "LAT",
    27: "DEV",
    28: "VET",
    29: "ANT",
    30: "BOR",
    31: "HAD",
    32: "LIN",
    33: "HIR",
    34: "CAM",
}


def load_catalog() -> dict[str, dict[str, Any]]:
    if CATALOG_PATH.exists():
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


DRIVER_CATALOG = load_catalog()


def get_driver_photo_info(
    driver_code: str | None = None,
    driver_id: int | None = None,
) -> dict[str, Any]:
    """Look up photo metadata by driver_code or driver_id."""
    code = (driver_code or "").upper().strip()
    if not code and driver_id and driver_id in DRIVER_CODE_BY_ID:
        code = DRIVER_CODE_BY_ID[driver_id]

    entry = DRIVER_CATALOG.get(code, {})
    local_file = ASSETS_DIR / f"{code}.jpg"
    has_file = local_file.exists() and local_file.stat().st_size > 1000

    return {
        "driver_code": code,
        "has_image": has_file,
        "local_path": str(local_file) if has_file else None,
        "author": entry.get("author") or "Wikimedia Contributor",
        "license": entry.get("license") or "CC BY-SA",
        "license_url": entry.get("license_url") or "https://creativecommons.org/licenses/",
        "source_url": entry.get("source_url") or "https://commons.wikimedia.org/",
    }


def _get_image_base64(file_path: str) -> str | None:
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def render_driver_portrait(
    driver_code: str | None,
    driver_name: str = "",
    driver_number: int | str | None = None,
    constructor_name: str | None = None,
    width: int = 160,
    height: int = 160,
    show_caption: bool = True,
) -> None:
    """Render a driver portrait or a styled retro fallback avatar."""
    info = get_driver_photo_info(driver_code)
    code_display = html.escape(str(driver_code or "F1"))
    num_str = f"#{driver_number}" if driver_number else ""
    team_str = html.escape(str(constructor_name or ""))

    if info["has_image"] and info["local_path"]:
        b64 = _get_image_base64(info["local_path"])
        if b64:
            caption_html = ""
            if show_caption:
                auth = html.escape(info["author"][:26])
                lic = html.escape(info["license"])
                src = html.escape(info["source_url"])
                caption_html = f"""
                <div style="font-family:'Consolas','Courier New',monospace; font-size:0.62rem; color:#A7B89C; margin-top:4px; line-height:1.2;">
                    PHOTO: <a href="{src}" target="_blank" style="color:#D5E8B5; text-decoration:none;">{auth}</a> [{lic}]
                </div>
                """

            st.markdown(
                f"""
                <div style="display:inline-block; vertical-align:top; margin-bottom:0.5rem;">
                    <div style="width:{width}px; height:{height}px; border:2px solid #D5E8B5; background:#101B14; overflow:hidden; box-shadow:0 0 10px rgba(213,232,181,0.15);">
                        <img src="data:image/jpeg;base64,{b64}" 
                             alt="{code_display}" 
                             style="width:100%; height:100%; object-fit:cover; object-position:center 15%; display:block; filter:contrast(1.05) brightness(0.96);" />
                    </div>
                    {caption_html}
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

    # Graceful fallback avatar for missing images (retro terminal wireframe)
    st.markdown(
        f"""
        <div style="display:inline-block; vertical-align:top; margin-bottom:0.5rem;">
            <div style="width:{width}px; height:{height}px; border:2px dashed #D5E8B5; background:#17251D; display:flex; flex-direction:column; align-items:center; justify-content:center; box-sizing:border-box; padding:8px; text-align:center;">
                <div style="font-family:'Consolas',monospace; font-size:0.65rem; color:#A7B89C; letter-spacing:0.1em;">
                    [ DOSSIER ]
                </div>
                <div style="font-family:'Consolas',monospace; font-size:1.6rem; font-weight:800; color:#FFFFFF; margin:6px 0;">
                    {code_display}
                </div>
                <div style="font-family:'Consolas',monospace; font-size:0.75rem; color:#D5E8B5; font-weight:600;">
                    {num_str}
                </div>
                <div style="font-family:'Consolas',monospace; font-size:0.62rem; color:#A7B89C; margin-top:4px; max-width:90%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                    {team_str}
                </div>
            </div>
            <div style="font-family:'Consolas',monospace; font-size:0.62rem; color:#A7B89C; margin-top:4px;">
                GENUINE ARCHIVE // WIKIMEDIA
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
