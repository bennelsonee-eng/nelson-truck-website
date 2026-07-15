"""V16: from v15_c (unflipped, t-100, pl500), user wants plow moved RIGHT
and truck moved LEFT more.

Current v15_c: pivot_x=500, truck_shift=-100
Target: pivot_x=600-800 (plow moves right), truck_shift=-200 to -300 (truck moves left more)

Plow stays UNFLIPPED so WESTERN text reads correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v16"


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite_unflipped(
    plow_src: Image.Image, truck_full: Image.Image,
    pivot_x: int, pivot_y: int, plow_width: int,
    truck_shift_x: int = 0,
) -> Image.Image:
    plow = plow_src  # unflipped — WESTERN reads correctly
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

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Truck: {truck.size}")
    print(f"Plow:  {plow.size}")

    # User said: plow moves right, truck moves left.
    # Sweep along both axes.

    variants = [
        # (label, pivot_x, pivot_y, plow_width, truck_shift_x)
        # === Plow shifted right at v15_c truck shift -100 ===
        ("a_t-100_pl600",     600, 380, 960, -100),
        ("b_t-100_pl700",     700, 380, 960, -100),
        ("c_t-100_pl800",     800, 380, 960, -100),
        # === Truck shifted -200, plow varied ===
        ("d_t-200_pl600",     600, 380, 960, -200),
        ("e_t-200_pl700",     700, 380, 960, -200),
        ("f_t-200_pl800",     800, 380, 960, -200),
        # === Truck shifted -250, plow varied ===
        ("g_t-250_pl700",     700, 380, 960, -250),
        ("h_t-250_pl800",     800, 380, 960, -250),
        # === Truck shifted -300, plow varied ===
        ("i_t-300_pl700",     700, 380, 960, -300),
        ("j_t-300_pl800",     800, 380, 960, -300),
        # === Try smaller plow at extreme positions ===
        ("k_t-200_pl700_w800",   700, 380, 800, -200),
        ("l_t-300_pl750_w800",   750, 380, 800, -300),
    ]

    for label, px, py, pw, ts in variants:
        out = composite_unflipped(plow, truck, px, py, pw, ts)
        outpath = OUTPUT_DIR / f"{label}.png"
        out.save(outpath)
        print(f"  saved {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
