"""V3 lineup composite — per-truck tuned params from vision measurements.

User asked: "use Claude vision to match up the plows on all of the trucks".

I visually measured each truck's grille center X, bumper bar Y, and visible
size, then derived per-truck plow placement using the same RELATIVE positioning
as the locked 2500 baseline:
  - pivot_x = (shifted_grille_x) - 20    # V-pivot 20px LEFT of grille
  - pivot_y = bumper_y - 50              # V-pivot 50px ABOVE bumper bar
  - plow_width scaled to truck size      # smaller truck → smaller plow

Locked 2500 baseline (user-approved at v14 i):
  - 2500 grille at x=660 (original) → x=560 (after shift -100)
  - 2500 bumper at y=430
  - pivot = (560-20, 430-50) = (540, 380) ✓
  - plow_width = 900

Per-truck measurements + derived params:
  Class   | Grille | Bumper | Shift | Pivot         | PlowW | Notes
  --------|--------|--------|-------|---------------|-------|------
  midsize |  780   |  425   | -100  | (660, 375)    |  750  | small truck, smaller plow
  1500    |  750   |  435   | -100  | (630, 385)    |  820  | medium-small
  2500    |  660   |  430   | -100  | (540, 380)    |  900  | LOCKED baseline
  3500    |  720   |  425   | -100  | (600, 375)    |  900  | F-250 front, same plow width
  4500    |  720   |  365   | -100  | (600, 315)    |  950  | chassis cab, bumper higher
  5500    |  720   |  365   | -100  | (600, 315)    |  980  | larger chassis cab
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_DIR = REPO / "wan_test_output" / "lineup_3q"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "app" / "backend" / "static" / "trucks" / "composites_3q"

# Per-truck-tuned anchors derived from vision measurements
TRUCK_PROFILES = {
    # class:    (truck_seed,  pivot_x, pivot_y, plow_width, truck_shift_x, flip_truck)
    "mid-size": ("seed8888", 660, 375, 750, -100, False),
    "1500":     ("seed8888", 630, 385, 820, -100, False),
    "2500":     ("seed1337", 540, 380, 900, -100, False),  # LOCKED — do not change
    "3500":     ("seed8888", 600, 375, 900, -100, False),
    "4500":     ("seed8888", 600, 315, 950, -100, True),
    "5500":     ("seed1337", 600, 315, 980, -100, True),
}


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite(plow_src: Image.Image, truck_full: Image.Image,
              pivot_x: int, pivot_y: int, plow_width: int,
              truck_shift_x: int, flip_truck: bool) -> Image.Image:
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
        print(f"  saved {outpath.name}  pivot=({px},{py}) w={pw}{flip_tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
