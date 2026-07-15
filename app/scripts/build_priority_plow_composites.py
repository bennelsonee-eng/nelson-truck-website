"""Build F-250 composites for all priority plows we verified clean.

For each clean SKU, paste the plow at the locked v6 anchor on the F-250
3/4 render.  Saves to wan_test_output/priority_plows/<sku>_on_f250.png

Then we'll batch these through Kontext variant-C and build a comparison grid.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUT_DIR = REPO / "wan_test_output" / "priority_plows"


# Confirmed clean priority plows (from this session's audit).
# Each entry is (sku, friendly name, plow_width override or None for default 1000)
PRIORITY_CLEAN = [
    ("WEST-MVP3MS86-EQP",   "Western MVP3 8'6\" V-plow MS",          None),
    ("WEST-MVPPMS86-EQP",   "Western MVP Plus 8'6\" V-plow",         None),
    ("WEST-MVPPMS96-EQP",   "Western MVP Plus 9'6\" V-plow",         1050),
    ("WEST-ENFMS76-EQP",    "Western Enforcer 7'6\" V-plow MS",      900),
    ("WEST-ENFSS76-EQP",    "Western Enforcer 7'6\" V-plow SS",      900),
    ("WEST-HTS76-EQP",      "Western HTS 7'6\" Straight",            900),
    ("MYP-09275-EQP",       "Meyer Lot Pro LD 7'6\" Straight",       950),
    ("SNOW-16020412-EQP",   "SnowDogg MD68II Straight",              900),
    ("SNOW-16020724-EQP",   "SnowDogg VXF85II V-plow",               1050),
    ("SNOW-16020922-EQP",   "SnowDogg XP810II Wing-plow",            1050),
]


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite(plow_src: Image.Image, truck: Image.Image,
              pivot_x: int = 540, pivot_y: int = 380, plow_width: int = 1000,
              truck_shift_x: int = -100) -> Image.Image:
    aspect = plow_src.height / plow_src.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow_src.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    truck_shifted = shift_truck_full(truck, truck_shift_x)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    truck = Image.open(TRUCK_PATH).convert("RGBA")
    print(f"Truck: {truck.size}")

    for sku, name, width_override in PRIORITY_CLEAN:
        plow_path = SKUS_DIR / sku / "hero_transparent.png"
        if not plow_path.exists():
            print(f"  ! missing {sku}")
            continue
        plow = Image.open(plow_path).convert("RGBA")
        pw = width_override if width_override else 1000
        out = composite(plow, truck, plow_width=pw)
        outpath = OUT_DIR / f"{sku}_on_f250.png"
        out.save(outpath)
        print(f"  saved {outpath.name}  ({name}, w={pw})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
