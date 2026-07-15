"""V2 lineup composite — fixes user feedback:

  1. mid-size + 1500: plow needs to move right → pivot_x increased
  3. (no change — 2500 was the locked baseline)
  4. 3500 'two fronts' — likely V-pivot hardware visually competing with grille,
     try shifting plow right too
  5. 4500 'truck facing wrong way' — chassis cabs render with grille on LEFT
     in FLUX, opposite of pickups. FIX: flip truck horizontally before composite.
  6. 5500 'truck facing wrong way' — same fix.

Locked composite math (from v14 i):
  - Plow FLIPPED horizontally
  - plow_width = 900
  - truck_shift_x = -100
  - NO depth occlusion
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_DIR = REPO / "wan_test_output" / "lineup_3q"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "app" / "backend" / "static" / "trucks" / "composites_3q"

# Per-class anchor + truck-flip flag
TRUCK_PROFILES = {
    # class:    (truck_seed,  pivot_x, pivot_y, plow_width, truck_shift_x, flip_truck)
    # mid-size, 1500: same orientation as 2500, just move plow RIGHT
    "mid-size": ("seed8888", 600, 360, 900, -100, False),
    "1500":     ("seed8888", 600, 370, 900, -100, False),
    # 2500 is the locked baseline (pivot_x=540)
    "2500":     ("seed1337", 540, 380, 900, -100, False),
    # 3500 also move plow right to address "two fronts"
    "3500":     ("seed8888", 600, 380, 900, -100, False),
    # 4500, 5500 chassis cabs render facing wrong way — FLIP TRUCK first
    "4500":     ("seed8888", 540, 360, 900, -100, True),
    "5500":     ("seed1337", 540, 360, 900, -100, True),
}


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite(plow_src: Image.Image, truck_full: Image.Image,
              pivot_x: int, pivot_y: int, plow_width: int,
              truck_shift_x: int, flip_truck: bool) -> Image.Image:
    """Locked composite logic + optional truck flip for chassis cabs."""
    if flip_truck:
        truck_full = truck_full.transpose(Image.FLIP_LEFT_RIGHT)

    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)  # plow always flipped (locked)
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    truck_shifted = shift_truck_full(truck_full, truck_shift_x)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plow = Image.open(PLOW_PATH).convert("RGBA")

    for cls, (seed, px, py, pw, ts, flip) in TRUCK_PROFILES.items():
        truck_path = TRUCK_DIR / f"{cls}_{seed}.png"
        if not truck_path.exists():
            print(f"  ! missing truck render: {truck_path}")
            continue
        truck = Image.open(truck_path).convert("RGBA")
        out = composite(plow, truck, px, py, pw, ts, flip)
        outpath = OUTPUT_DIR / f"{cls}_with_mvp3.png"
        out.save(outpath)
        flip_tag = " [FLIPPED]" if flip else ""
        print(f"  saved {outpath.name}  (seed={seed}, pivot=({px},{py}), w={pw}, shift={ts}){flip_tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
