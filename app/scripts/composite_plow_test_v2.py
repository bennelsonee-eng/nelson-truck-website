"""V2: corrected 3/4 anchor + scale.  Sweep around the new estimate.

Lessons from v1:
  - 3/4 truck pushes the visual centerline to ~x=660 in 1024-wide frame
    (the truck's right side is angled toward camera and fills more pixels)
  - Plow needs to be MUCH wider than v1 (real-world ratio ~1.2x bumper width
    and the bumper itself is ~360px wide here)
  - Anchor Y for the cutting edge sits ~30px below the visible bumper bar
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "f250_3q_test" / "f250_3q_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v2"


def composite(plow: Image.Image, truck: Image.Image,
              anchor_x: int, anchor_y: int, plow_width: int) -> Image.Image:
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
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

    # New baseline (corrected from v1):
    #   anchor_x = 660  (truck centerline projection in 3/4)
    #   anchor_y = 480  (cutting edge ~30px below bumper bar at y=440-460)
    #   plow_width = 520 (1.4x the visible bumper width)

    variants = [
        # (name, anchor_x, anchor_y, plow_width)
        ("a_baseline",     660, 480, 520),
        ("b_wider_540",    660, 480, 540),
        ("c_wider_580",    660, 480, 580),
        ("d_higher_460",   660, 460, 540),
        ("e_higher_440",   660, 440, 540),
        ("f_left_640",     640, 460, 540),
        ("g_left_620",     620, 460, 540),
        ("h_left_low_620", 620, 480, 540),
        ("i_lower_500",    660, 500, 540),
    ]

    for name, ax, ay, pw in variants:
        out = composite(plow, truck, ax, ay, pw)
        outpath = OUTPUT_DIR / f"{name}_x{ax}_y{ay}_w{pw}.png"
        out.save(outpath)
        print(f"  {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
