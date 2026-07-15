"""V4 lineup composite — user feedback on v3:

  1, 2, 3 (mid-size, 1500, 2500): plow needs to be a bit bigger
  4 (3500): switch to seed 7777 (new render — clean 3/4 front)
  5, 6 (4500, 5500): plow needs to be smaller AND rotated CCW 15°

The CCW rotation makes the plow lean back/up on the chassis cab — useful
because the chassis cab is taller and the plow looks oddly upright otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_DIR = REPO / "wan_test_output" / "lineup_3q"
TRUCK_DIR_3500 = REPO / "wan_test_output" / "3500_new_seeds"  # new 3500 seeds
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "app" / "backend" / "static" / "trucks" / "composites_3q"

# Per-truck-tuned anchors with v4 adjustments
TRUCK_PROFILES = {
    # class:    (truck_seed, pivot_x, pivot_y, plow_width, truck_shift_x, flip_truck, rotate_deg, source_dir)
    # === Pickups: bigger plows ===
    "mid-size": ("seed8888", 660, 375, 850,  -100, False, 0,  TRUCK_DIR),       # 750 -> 850
    "1500":     ("seed8888", 630, 385, 920,  -100, False, 0,  TRUCK_DIR),       # 820 -> 920
    "2500":     ("seed1337", 540, 380, 1000, -100, False, 0,  TRUCK_DIR),       # 900 -> 1000
    # === 3500: switch to new seed 7777 ===
    "3500":     ("seed7777", 600, 375, 900,  -100, False, 0,  TRUCK_DIR_3500),
    # === Chassis cabs: smaller + rotated CW -15 (into the picture) ===
    "4500":     ("seed8888", 600, 315, 800,  -100, True,  -15, TRUCK_DIR),      # 950 -> 800, -15° CW (into picture)
    "5500":     ("seed1337", 600, 315, 820,  -100, True,  -15, TRUCK_DIR),      # 980 -> 820, -15° CW (into picture)
}


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite(plow_src: Image.Image, truck_full: Image.Image,
              pivot_x: int, pivot_y: int, plow_width: int,
              truck_shift_x: int, flip_truck: bool, rotate_deg: int) -> Image.Image:
    if flip_truck:
        truck_full = truck_full.transpose(Image.FLIP_LEFT_RIGHT)

    # Plow: flip first, then rotate (PIL rotate positive = CCW)
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)
    if rotate_deg:
        plow = plow.rotate(rotate_deg, expand=True, resample=Image.BICUBIC)

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

    for cls, (seed, px, py, pw, ts, flip, rot, src_dir) in TRUCK_PROFILES.items():
        truck_path = src_dir / f"{cls}_{seed}.png"
        if not truck_path.exists():
            print(f"  ! missing truck render: {truck_path}")
            continue
        truck = Image.open(truck_path).convert("RGBA")
        out = composite(plow, truck, px, py, pw, ts, flip, rot)
        outpath = OUTPUT_DIR / f"{cls}_with_mvp3.png"
        out.save(outpath)
        flip_tag = " [FLIPPED]" if flip else ""
        rot_tag = f" [+{rot}° CCW]" if rot else ""
        print(f"  saved {outpath.name}  pivot=({px},{py}) w={pw}{flip_tag}{rot_tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
