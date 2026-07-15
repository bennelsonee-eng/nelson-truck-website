"""V4: subtler 3/4 truck (v2 lineup) + bigger plow.

User feedback on v3 POC:
  1. Truck angle too aggressive (35° vs plow's 22°) — fixed in v2 lineup
  2. Plow looks too small — fixed by pushing plow_width up significantly

V4 sweeps both seeds (1337, 8888) of v2 F-250 with multiple plow scales
+ anchor positions to find the best fit.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_DIR = REPO / "wan_test_output" / "lineup_3q_v2"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v4"


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

    plow = Image.open(PLOW_PATH).convert("RGBA")

    # Try both seeds + a range of plow widths.
    # The v2 truck centerline is closer to image center (less aggressive 3/4),
    # so anchor_x is closer to 540-580 instead of 660.
    truck_seeds = [1337, 8888]
    variants = [
        # (plow_width, anchor_x, anchor_y, label)
        (900,  540, 480, "w900_centered"),
        (1000, 540, 490, "w1000_centered"),
        (1100, 540, 500, "w1100_centered"),
        (1200, 540, 510, "w1200_extends"),
        (1100, 540, 480, "w1100_higher"),
        (1100, 580, 500, "w1100_right"),
    ]

    for seed in truck_seeds:
        truck_path = TRUCK_DIR / f"2500_seed{seed}.png"
        truck = Image.open(truck_path).convert("RGBA")
        print(f"\n=== seed {seed} ({truck.size}) ===")
        for pw, ax, ay, label in variants:
            out = composite(plow, truck, ax, ay, pw)
            outpath = OUTPUT_DIR / f"seed{seed}_{label}_x{ax}_y{ay}_w{pw}.png"
            out.save(outpath)
            print(f"  {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
