"""V3: push plow scale up significantly. V1 was too small; V2 was small.

Real-world: MVP3 86" plow is 102" wide on an 82" bumper, so plow extends
~25% past bumper on each side.  In our 1024-wide F-250 render the visible
bumper is ~380px, so plow should be ~480px MINIMUM, possibly larger due
to the perspective foreshortening of the bumper at 3/4.

Also testing: slight Y adjustments to put the cutting edge below the bumper.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "f250_3q_test" / "f250_3q_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v3"


def composite(plow: Image.Image, truck: Image.Image,
              anchor_x: int, anchor_y: int, plow_width: int,
              flip: bool = False) -> Image.Image:
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    if flip:
        plow_resized = plow_resized.transpose(Image.FLIP_LEFT_RIGHT)
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

    variants = [
        # (name, anchor_x, anchor_y, plow_width, flip)
        ("a_w650",         660, 480, 650, False),
        ("b_w750",         660, 490, 750, False),
        ("c_w850",         660, 500, 850, False),
        ("d_w750_high",    660, 460, 750, False),
        ("e_w750_low",     660, 510, 750, False),
        # mirror flip — the MVP3 might be 3/4 from opposite side from truck
        ("f_w750_flipped", 660, 490, 750, True),
        ("g_w850_flipped", 660, 500, 850, True),
        # try shifting plow slightly left toward truck's visual front
        ("h_w750_left",    600, 490, 750, False),
        ("i_w750_left_flip",   600, 490, 750, True),
    ]

    for name, ax, ay, pw, flip in variants:
        out = composite(plow, truck, ax, ay, pw, flip)
        flip_tag = "_flip" if flip else ""
        outpath = OUTPUT_DIR / f"{name}{flip_tag}_x{ax}_y{ay}_w{pw}.png"
        out.save(outpath)
        print(f"  {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
