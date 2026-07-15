"""V7: re-do with truck UNFLIPPED + try mirroring the entire composite.

User feedback on v6 perm1: "no the whole picture flipped. plow is facing to
the right and truck is facing to the left"

That means perm1 had it backwards.  User wants:
  - Truck facing LEFT (nose pointing left, body extends right)
  - Plow facing RIGHT (V opening toward right)

In our v1 truck render (lineup_3q/2500_seed1337.png):
  - WITHOUT any flip: truck nose points to the RIGHT, body extends LEFT
  - With horizontal flip:  truck nose points to the LEFT, body extends RIGHT

The user's description "truck facing left" matches the FLIPPED truck.

For the plow:
  - Without flip: WESTERN branding readable, V opens toward camera, plow's
    "near blade" (one with WESTERN text) is on the RIGHT
  - With flip: WESTERN mirrored, near blade on LEFT

User says "plow facing right" — interpret as: the plow's near-camera (front)
face on the RIGHT side.  That's the UNFLIPPED plow image.

So target combo is: TRUCK FLIPPED + PLOW UNFLIPPED  (= perm 2 from v6)

But perm 2 had WESTERN backwards... wait, that was because I flipped the
plow.  In perm 2, plow was UNFLIPPED — WESTERN should read normally.  Let me
re-verify by regenerating the 4 permutations at the same fine-tune position
that worked best.

Also testing: "mirror the whole composite at the end" — generate perm1 and
flip the final image.  Geometrically equivalent to perm4 (TU+PU) but verifies
my flip-logic understanding.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"  # v1 35° F-250
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v7"


def composite_at_pivot(plow_src: Image.Image, truck_src: Image.Image,
                       pivot_x: int, pivot_y: int, plow_width: int,
                       flip_truck: bool, flip_plow: bool,
                       flip_final: bool = False) -> Image.Image:
    truck = truck_src.transpose(Image.FLIP_LEFT_RIGHT) if flip_truck else truck_src.copy()
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT) if flip_plow else plow_src

    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)

    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    out = truck.copy().convert("RGBA")
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))

    if flip_final:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    truck_src = Image.open(TRUCK_PATH).convert("RGBA")
    plow_src  = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Truck source: {truck_src.size}")
    print(f"Plow source:  {plow_src.size}")

    # Original v1 truck has grille at x~660 (right side).
    # If we DON'T flip the truck (leave nose on right), plow should be LEFT
    # of grille:  pivot_x = 660 - 143 = 517.
    # If we FLIP the truck (nose on left), plow should be LEFT of new grille
    # (which is now at x=1024-660=364), so pivot_x = 364 - 143 = 221.

    # Use the perm1_low fine-tune position (Y=360 for low cutting edge).

    variants = [
        # (label, flip_truck, flip_plow, pivot_x, pivot_y, plow_width, flip_final)
        # Re-do perm1 (TF+PF) for reference
        ("perm1_TF_PF_LOW",     True,  True,  221, 360, 707, False),
        # Try the alternative: truck flipped, plow UNFLIPPED
        ("perm2_TF_PU_LOW",     True,  False, 221, 360, 707, False),
        # Also re-do perm4 (TU+PU = "no flips at all") at the right anchor
        # for the unflipped truck
        ("perm4_TU_PU_LOW",     False, False, 517, 360, 707, False),
        # And perm3 (TU+PF) at the unflipped truck anchor
        ("perm3_TU_PF_LOW",     False, True,  517, 360, 707, False),
        # Mirror the entire perm1 final image
        ("perm1_FINAL_MIRROR",  True,  True,  221, 360, 707, True),
        # Mirror perm4 at the end too (should be same as perm1 visually)
        ("perm4_FINAL_MIRROR",  False, False, 517, 360, 707, True),
    ]

    for label, ft, fp, px, py, pw, ff in variants:
        out = composite_at_pivot(plow_src, truck_src, px, py, pw,
                                 flip_truck=ft, flip_plow=fp, flip_final=ff)
        outpath = OUTPUT_DIR / f"{label}.png"
        out.save(outpath)
        print(f"  {outpath.name}  truck_flip={ft}  plow_flip={fp}  final_flip={ff}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
