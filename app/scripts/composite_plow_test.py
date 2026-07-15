"""Composite the Western MVP3 MS 8'6" V-plow onto the F-250 3/4 render.

This is the proof-of-concept for Path A:
  - 3/4 plow shot (existing transparent extract) onto 3/4 truck render
  - Tune scale + anchor until it looks right
  - Once correct, this composite is the input to the rotation step
    (3/4 -> head-on via FLUX Kontext or Wan 2.2 I2V)

Output:
  wan_test_output/composite_test/<variant>.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "f250_3q_test" / "f250_3q_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test"


def composite(plow: Image.Image, truck: Image.Image,
              anchor_x: int, anchor_y: int, plow_width: int) -> Image.Image:
    """Place plow centered at (anchor_x, anchor_y) on truck.

    anchor_y is the bottom edge of the plow blade (where the cutting edge sits).
    plow_width is the desired pixel width of the plow.
    """
    # Resize plow proportionally to plow_width
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)

    # Composite — plow centered horizontally at anchor_x, with bottom at anchor_y
    out = truck.copy().convert("RGBA")
    paste_x = anchor_x - plow_width // 2
    paste_y = anchor_y - plow_h
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")

    print(f"Truck: {truck.size}")
    print(f"Plow:  {plow.size}")

    # F-250 seed 1337 visual bumper estimates (eyeball from the 1024x576 image):
    #   - Visible bumper bar centered around x~560, vertical y~395-425
    #   - Bumper visible width ~280px due to 3/4 perspective compression
    #
    # Plow should be slightly wider than the bumper (real plows are 102" wide
    # on a ~84" wide bumper), and the cutting edge should sit ~30px below the
    # bumper bar (lowered position ~12" below bumper level).
    #
    # Try a sweep of scales + anchors so we can pick the best fit visually.

    variants = [
        # (name, anchor_x, anchor_y, plow_width)
        ("a_default",   560, 460, 360),
        ("b_wider",     560, 460, 420),
        ("c_narrower",  560, 460, 320),
        ("d_lower",     560, 490, 380),
        ("e_higher",    560, 430, 380),
        ("f_left",      520, 460, 380),
        ("g_right",     600, 460, 380),
    ]

    for name, ax, ay, pw in variants:
        out = composite(plow, truck, ax, ay, pw)
        outpath = OUTPUT_DIR / f"{name}_x{ax}_y{ay}_w{pw}.png"
        out.save(outpath)
        print(f"  {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
