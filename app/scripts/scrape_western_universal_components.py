"""Download the universal (non-YMM-specific) component images for kit
building: LED headlight, Halogen headlight, Handheld + Joystick controls,
FleetFlex system overview.

The owner's framing 2026-05-21: "head light pictures (should only be 2),
controller pics(I think only 2 or 3)" — these are universal, not per-YMM.

Output:
    refs/western_components/headlamp/led.jpeg
    refs/western_components/headlamp/halogen.jpeg
    refs/western_components/control/handheld_joystick_combined.jpeg
    refs/western_components/control/fleetflex.jpeg
    refs/western_components/_index.json
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_ROOT = REPO_ROOT / "refs" / "western_components"
INDEX_PATH = OUT_ROOT / "_index.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


# Hand-curated 2026-05-21 from westernplows.com/products/mvp-3/ +
# /products/enforcer/.  Western uses these same image URLs across all
# their plow product pages for the universal lighting / control options.
COMPONENTS = [
    {
        "role": "headlamp",
        "variant": "LED",
        "skus": ["72525"],   # Plow Headlight Kit, LED — universal per BOM
        "description": "Western LED Headlight Kit (NIGHTHAWK™ style)",
        "image_url": "https://westernplows.com/wp-content/uploads/2021/05/MVP3-LED-1_1270x714_722-1.jpeg",
        "filename": "led.jpeg",
    },
    {
        "role": "headlamp",
        "variant": "Halogen",
        "skus": ["72530"],   # Plow Headlight Kit, Halogen — universal per BOM
        "description": "Western Halogen Headlight Kit (Dual-Halogen)",
        "image_url": "https://westernplows.com/wp-content/uploads/2021/05/IMGL2042_Bkgd_HalogenHeadlamps_1270x714_72.jpeg",
        "filename": "halogen.jpeg",
    },
    {
        "role": "control",
        "variant": "FleetFlex System Overview",
        "skus": [],
        "description": "FleetFlex marketing overview (system overview, both control options visible)",
        "image_url": "https://westernplows.com/wp-content/uploads/2021/05/fleetflex.jpeg",
        "filename": "fleetflex_overview.jpeg",
    },
    {
        "role": "control",
        "variant": "Universal Control Options",
        "skus": ["35500", "35600", "96400"],
        "description": "Composite shot of all Western FleetFlex control options "
                       "(Handheld, Joystick, alt Joystick) used in the kit builder",
        "image_url": "https://westernplows.com/wp-content/uploads/2021/05/Universal_ControlOptions-ENFORCER.jpeg",
        "filename": "all_control_options.jpeg",
    },
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> int:
    index: list[dict] = []
    for comp in COMPONENTS:
        role_dir = OUT_ROOT / comp["role"]
        role_dir.mkdir(parents=True, exist_ok=True)
        local = role_dir / comp["filename"]
        url = comp["image_url"]
        # Try uncropped first; if 404, fall back to -640x360 variant
        candidates = [url]
        if "-640x" not in url:
            stem, _, ext = url.rpartition(".")
            candidates.append(f"{stem}-640x360.{ext}")
        saved = False
        for candidate in candidates:
            try:
                data = fetch(candidate)
                local.write_bytes(data)
                comp["downloaded_from"] = candidate
                comp["size_bytes"] = len(data)
                saved = True
                print(f"[{comp['role']}/{comp['variant']}] saved {local.name} "
                      f"({len(data)//1024} KB) from {candidate}", flush=True)
                break
            except Exception as e:
                print(f"  fail: {candidate}: {e}", flush=True)
                continue
        if not saved:
            comp["error"] = "all candidates failed"
        comp["local_path"] = str(local.relative_to(REPO_ROOT)).replace("\\", "/")
        index.append(comp)
        time.sleep(0.4)

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
    have = sum(1 for c in index if c.get("size_bytes"))
    print(f"\n=== {have}/{len(index)} component images saved ===", flush=True)
    print(f"  index: {INDEX_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
