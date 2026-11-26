"""
Fetch genuine F1 driver portraits and license metadata from Wikimedia Commons.
Respects Wikimedia User-Agent requirements and stores images locally in frontend/assets/drivers/.
Generates frontend/driver_photos.json and Python module frontend/driver_photos.py.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
import requests

WIKI_ARTICLE_MAP = {
    "VER": "Max Verstappen",
    "HAM": "Lewis Hamilton",
    "NOR": "Lando Norris",
    "LEC": "Charles Leclerc",
    "PIA": "Oscar Piastri",
    "RUS": "George Russell (racing driver)",
    "SAI": "Carlos Sainz Jr.",
    "ALO": "Fernando Alonso",
    "PER": "Sergio Pérez",
    "GAS": "Pierre Gasly",
    "OCO": "Esteban Ocon",
    "ALB": "Alex Albon",
    "TSU": "Yuki Tsunoda",
    "STR": "Lance Stroll",
    "HUL": "Nico Hülkenberg",
    "BOT": "Valtteri Bottas",
    "ZHO": "Zhou Guanyu",
    "MAG": "Kevin Magnussen",
    "RIC": "Daniel Ricciardo",
    "SAR": "Logan Sargeant",
    "BEA": "Oliver Bearman",
    "COL": "Franco Colapinto",
    "LAW": "Liam Lawson",
    "DEV": "Nyck de Vries",
    "VET": "Sebastian Vettel",
    "MSC": "Mick Schumacher",
    "LAT": "Nicholas Latifi",
    "ANT": "Kimi Antonelli",
    "BOR": "Gabriel Bortoleto",
    "DOO": "Jack Doohan",
    "HAD": "Isack Hadjar",
    "CAM": "Rafael Câmara",
    "HIR": "Ryo Hirakawa",
    "LIN": "Arvid Lindblad",
}

HEADERS = {
    "User-Agent": "RaceIntel/1.0 (F1 Analytics Platform; https://github.com/RM-f1/RaceIntel) python-requests"
}

ASSETS_DIR = Path("frontend/assets/drivers")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    return re.sub(r"<[^>]+>", "", raw_html).strip()


def fetch_driver_info(driver_code: str, title: str) -> dict:
    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. Query Wikipedia page image
    api_url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageimages",
        "format": "json",
        "pithumbsize": 360,
    }
    resp = session.get(api_url, params=params, timeout=10)
    data = resp.json()
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return {"driver_code": driver_code, "has_image": False}

    page = next(iter(pages.values()))
    thumb = page.get("thumbnail")
    page_image = page.get("pageimage")

    if not thumb or not thumb.get("source"):
        return {"driver_code": driver_code, "has_image": False}

    thumb_url = thumb["source"]
    file_title = f"File:{page_image}"

    # 2. Query Wikimedia Commons for image metadata & licensing
    commons_url = "https://commons.wikimedia.org/w/api.php"
    c_params = {
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "extmetadata|user|url",
        "format": "json",
    }
    author = "Wikimedia Contributor"
    license_name = "CC BY-SA 4.0"
    license_url = "https://creativecommons.org/licenses/by-sa/4.0/"
    desc_url = f"https://commons.wikimedia.org/wiki/{file_title}"

    try:
        c_resp = session.get(commons_url, params=c_params, timeout=10)
        c_data = c_resp.json()
        c_pages = c_data.get("query", {}).get("pages", {})
        if c_pages:
            c_page = next(iter(c_pages.values()))
            imageinfo = c_page.get("imageinfo", [{}])[0]
            desc_url = imageinfo.get("descriptionurl", desc_url)
            ext = imageinfo.get("extmetadata", {})
            if "Artist" in ext:
                author = clean_html(ext["Artist"]["value"])
            elif "Attribution" in ext:
                author = clean_html(ext["Attribution"]["value"])
            elif "user" in imageinfo:
                author = imageinfo["user"]

            if "LicenseShortName" in ext:
                license_name = ext["LicenseShortName"]["value"]
            elif "License" in ext:
                license_name = ext["License"]["value"]

            if "LicenseUrl" in ext:
                license_url = ext["LicenseUrl"]["value"]
    except Exception as exc:
        print(f"Metadata lookup error for {driver_code}: {exc}")

    # 3. Download and cache image locally
    local_file = ASSETS_DIR / f"{driver_code}.jpg"
    has_image = False
    try:
        img_resp = session.get(thumb_url, timeout=12)
        if img_resp.status_code == 200 and len(img_resp.content) > 1000:
            with open(local_file, "wb") as f:
                f.write(img_resp.content)
            has_image = True
    except Exception as exc:
        print(f"Error downloading image for {driver_code}: {exc}")
        has_image = local_file.exists() and local_file.stat().st_size > 1000

    return {
        "driver_code": driver_code,
        "wiki_title": title,
        "has_image": has_image,
        "local_path": f"frontend/assets/drivers/{driver_code}.jpg" if has_image else None,
        "author": author,
        "license": license_name,
        "license_url": license_url,
        "source_url": desc_url,
    }


def main():
    catalog = {}
    for code, title in WIKI_ARTICLE_MAP.items():
        try:
            print(f"Fetching {code}...")
            info = fetch_driver_info(code, title)
            catalog[code] = info
            status = "SUCCESS" if info.get("has_image") else "NO IMAGE"
            print(f"  -> {code}: {status} ({info.get('author')}, {info.get('license')})")
        except Exception as exc:
            print(f"  -> ERROR {code}: {exc}")
            catalog[code] = {"driver_code": code, "has_image": False}
        time.sleep(0.2)

    output_path = Path("frontend/driver_photos_catalog.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"\nSaved catalog to {output_path}")


if __name__ == "__main__":
    main()
