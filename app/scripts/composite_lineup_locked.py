"""Apply the locked F-250 composite to all 6 truck classes.

Locked params (v14 i):
  - Plow image: WEST-MVP3MS86-EQP/hero_transparent.png
  - Plow FLIPPED horizontally (WESTERN text reads mirrored — accepted trade-off)
  - V-pivot at (540, 380) for the F-250 (2500)
  - plow_width = 900 (about 88% of 1024 frame width)
  - truck_shift_x = -100 (truck pushed 100px left)
  - NO depth occlusion (plow fully on top of truck)

Per-class adjustments:
  Each truck has a different grille height (Tacoma sits lowest, F-550 highest).
  We use the same plow_width and truck_shift for all classes, but adjust the
  pivot_y so the V-pivot lines up with each truck's bumper.

Eye-measured pivot_y per class (based on visible bumper bar in each render):
  mid-size (Tacoma): bumper higher in frame? smaller truck overall.
  1500 (F-150):       lower bumper than F-250
  2500 (F-250):       baseline 380
  3500 (F-350 dually): similar to 2500
  4500 (F-450 chassis): slightly higher bumper
  5500 (F-550 chassis): highest bumper

Output: app/backend/static/trucks/composites_3q/<class>_with_mvp3.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_DIR = REPO / "wan_test_output" / "lineup_3q"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "app" / "backend" / "static" / "trucks" / "composites_3q"

# Per-class anchor: same X + width + shift, only Y differs (per truck's grille
# height in the v1 35deg 3/4 render).
TRUCK_PROFILES = {
    # class:  (truck_seed, pivot_x, pivot_y, plow_width, truck_shift_x)
    "mid-size": ("seed8888", 540, 360, 900, -100),  # Tacoma sits lower, plow higher
    "1500":     ("seed8888", 540, 370, 900, -100),  # F-150 mid
    "2500":     ("seed1337", 540, 380, 900, -100),  # F-250 — locked baseline
    "3500":     ("seed8888", 540, 380, 900, -100),  # F-350 dually similar to F-250
    "4500":     ("seed8888", 540, 360, 900, -100),  # F-450 chassis cab — bumper a bit higher
    "5500":     ("seed1337", 540, 360, 900, -100),  # F-550 chassis cab
}


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite(plow_src: Image.Image, truck_full: Image.Image,
              pivot_x: int, pivot_y: int, plow_width: int,
              truck_shift_x: int) -> Image.Image:
    """Locked composite logic — flip plow, no occlusion, plow on top of shifted truck."""
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)  # FLIP plow (locked)
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

    for cls, (seed, px, py, pw, ts) in TRUCK_PROFILES.items():
        truck_path = TRUCK_DIR / f"{cls}_{seed}.png"
        if not truck_path.exists():
            print(f"  ! missing truck render: {truck_path}")
            continue
        truck = Image.open(truck_path).convert("RGBA")
        out = composite(plow, truck, px, py, pw, ts)
        outpath = OUTPUT_DIR / f"{cls}_with_mvp3.png"
        out.save(outpath)
        print(f"  saved {outpath.name}  (seed={seed}, pivot=({px},{py}), w={pw}, shift={ts})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
