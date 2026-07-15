"""Fetch Meyer plow product images from meyerproducts.com.

Downloads thumbnails first; we'll fetch full hero images by parsing each
family page in a separate pass once we see what's good.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import certifi
import httpx

OUT_DIR = Path(__file__).resolve().parents[1].parent / "wan_test_output" / "meyer_sourced"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://meyerproducts.com"

# Family slug -> (canonical name, landing thumbnail URL, family page path)
FAMILIES = {
    "lot-pro": (
        "Lot Pro",
        "/MeyerProducts/media/MeyerMediaLibrary/Lot%20Pro/LotPro_23-(22)-456x250.jpg",
        "/snow-plows/contractor-truck-plows/lot-pro-(1)",
    ),
    "lot-pro-ld": (
        "Lot Pro LD",
        "/MeyerProducts/media/MeyerMediaLibrary/Press/LPLD.jpg",
        "/snow-plows/contractor-truck-plows/lot-pro-ld-(1)",
    ),
    "super-v3": (
        "Super-V3",
        "/MeyerProducts/media/MeyerMediaLibrary/Super-V(2)/SuperV3_Crossfire_23-(38)-456x250.jpg",
        "/snow-plows/contractor-truck-plows/super-v3-(1)",
    ),
    "super-v-ld": (
        "Super-V LD",
        "/MeyerProducts/media/MeyerMediaLibrary/Press/psld.jpg",
        "/snow-plows/contractor-truck-plows/super-v-ld-(1)",
    ),
    "drive-pro": (
        "Drive Pro",
        "/MeyerProducts/media/MeyerMediaLibrary/Drive%20Pro/DrivePro_Blaster_23-(32)-456x250.jpg",
        "/snow-plows/contractor-truck-plows/drive-pro-homeowner",
    ),
    "super-blade": (
        "Super Blade",
        "/MeyerProducts/media/MeyerMediaLibrary/Road%20Pro/SuperBlade_Crossfire_23-(16)-456.jpg",
        "/snow-plows/contractor-truck-plows/super-blade",
    ),
    "diamond-edge": (
        "Diamond Edge",
        "/MeyerProducts/media/MeyerMediaLibrary/Base%20Line%20960/DiamondEdge_Contractor-Landing-Page_456x250.jpg",
        "/snow-plows/contractor-truck-plows/diamond-edge-(1)",
    ),
    "road-pro-32": (
        "Road Pro 32-Series",
        "/MeyerProducts/media/MeyerMediaLibrary/WingMan/RoadPro_landing-page.jpg",
        "/snow-plows/contractor-truck-plows/road-pro-32-series",
    ),
    "road-pro-36": (
        "Road Pro 36-Series",
        "/MeyerProducts/media/MeyerMediaLibrary/Base%20Line%20960/RoadPro36_Contractor-Landing-Page_456x250.jpg",
        "/snow-plows/contractor-truck-plows/road-pro-36-series",
    ),
}


def fetch(client: httpx.Client, url: str, dest: Path) -> bool:
    try:
        r = client.get(url, timeout=20.0, follow_redirects=True)
        if r.status_code != 200:
            print(f"  [{r.status_code}] {url}")
            return False
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"  [err] {url}: {e}")
        return False


def main() -> int:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    saved = 0
    with httpx.Client(headers=headers, timeout=20.0, verify=certifi.where()) as client:
        for slug, (name, thumb_path, page_path) in FAMILIES.items():
            url = BASE + thumb_path
            ext = thumb_path.rsplit(".", 1)[-1]
            dest = OUT_DIR / f"{slug}__landing.{ext}"
            print(f"  [{slug}] {url}")
            if fetch(client, url, dest):
                saved += 1
                print(f"    saved {dest.name} ({dest.stat().st_size:,}B)")
            time.sleep(0.5)
    print(f"\nDone. {saved}/{len(FAMILIES)} thumbnails saved to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
