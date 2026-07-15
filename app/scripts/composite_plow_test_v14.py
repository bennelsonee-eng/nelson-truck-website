"""V14: user picked d) from v13 (truck-100, plow_pivot=500, w=960) but wants
the snowplow IN FRONT OF the truck.  Remove the depth-occlusion step.

Pure layering: truck_full (background) + plow on top, no truck-transparent
re-paste.  Plow's right blade visibly extends across the truck.

If the plow ends up extending too high over the hood, sweep position Y and
size to keep it grounded.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v14"


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    """Translate the truck-with-backdrop. Fills new space with the corner color."""
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite_plow_on_top(
    plow_src: Image.Image, truck_full: Image.Image,
    pivot_x: int, pivot_y: int, plow_width: int,
    truck_shift_x: int = 0,
) -> Image.Image:
    """No depth occlusion — plow goes fully on top of truck."""
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)
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

    # Base: d) from v13 = (pivot=500, y=335, w=960, truck_shift=-100)
    # All NO depth occlusion now. Plow is fully visible in front of truck.

    variants = [
        # (label, pivot_x, pivot_y, plow_width, truck_shift_x)
        # === Baseline (d from v13 minus depth occlusion) ===
        ("a_d_baseline",         500, 335, 960, -100),
        # === Lower Y to keep plow grounded ===
        ("b_y_360",              500, 360, 960, -100),
        ("c_y_380",              500, 380, 960, -100),
        ("d_y_400",              500, 400, 960, -100),
        # === Smaller plow + lower ===
        ("e_w_900_y_360",        500, 360, 900, -100),
        ("f_w_900_y_380",        500, 380, 900, -100),
        ("g_w_840_y_360",        500, 360, 840, -100),
        # === Plow further right (more on truck) ===
        ("h_pivot_540_y_360",    540, 360, 960, -100),
        ("i_pivot_540_y_380",    540, 380, 900, -100),
        # === Truck shifted further left, plow centered on truck nose ===
        ("j_t-150_pl_550_y360",  550, 360, 900, -150),
        ("k_t-150_pl_580_y380",  580, 380, 900, -150),
    ]

    for label, px, py, pw, ts in variants:
        out = composite_plow_on_top(plow, truck, px, py, pw, ts)
        outpath = OUTPUT_DIR / f"{label}.png"
        out.save(outpath)
        print(f"  saved {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
