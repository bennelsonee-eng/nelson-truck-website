"""V6: flip the truck horizontally, then composite.

Key insight from last session: the reference photos (Cliffside Silverado +
official Western MVP3 SS) both show the truck angled with its NOSE pointing
toward camera-LEFT (driver side close to camera).  Our FLUX truck renders
all came back with the OPPOSITE orientation — nose pointing camera-RIGHT
(passenger side close).  That mirror mismatch is why every v3-v5 composite
fought the geometry.

V6 fixes by flipping the truck horizontally before compositing.  After the
flip:
  - Truck nose points LEFT (matches reference)
  - Truck grille center moves from x~660 to x~364 (1024-660)
  - Plow extends LEFT, past the truck's nose

Reference geometry, MIRRORED for the flipped truck:
  - Reference: pivot is 14% LEFT of grille (pivot_x=410, grille=556 in 1024)
  - Mirrored: pivot is 14% RIGHT of grille... wait no.
  - The plow image and the reference photo BOTH have plow extending LEFT of
    grille.  So if we flip the truck, the plow STILL extends LEFT of grille
    in the original plow image's frame, BUT we may also need to flip the
    plow so that its near-camera blade lines up with the truck's near side.

Try four flip permutations:
  1. Truck UNFLIPPED, plow UNFLIPPED        (= v5 baseline)
  2. Truck FLIPPED,   plow UNFLIPPED        (truck rotated 180 in mirror)
  3. Truck UNFLIPPED, plow FLIPPED          (plow rotated 180 in mirror)
  4. Truck FLIPPED,   plow FLIPPED          (both flipped — should match
                                             reference closely IF plow's
                                             original orientation already
                                             matched our unflipped truck)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"  # v1 35° F-250
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v6"


def composite_at_pivot(plow: Image.Image, truck: Image.Image,
                       pivot_x: int, pivot_y: int, plow_width: int,
                       flip_truck: bool, flip_plow: bool) -> Image.Image:
    """Optionally flip both, then place plow's V-pivot at (pivot_x, pivot_y)."""
    if flip_truck:
        truck = truck.transpose(Image.FLIP_LEFT_RIGHT)
    if flip_plow:
        plow = plow.transpose(Image.FLIP_LEFT_RIGHT)

    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)

    pivot_offset_x = plow_width // 2
    pivot_offset_y = plow_h // 2
    paste_x = pivot_x - pivot_offset_x
    paste_y = pivot_y - pivot_offset_y

    out = truck.copy().convert("RGBA")
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Truck: {truck.size}  (v1 35° F-250)")
    print(f"Plow:  {plow.size}  (Western MVP3 MS 86\")")

    # When truck is FLIPPED, the grille that was at x=660 moves to 1024-660=364.
    # Reference convention: plow V-pivot is 14% of image-width LEFT of grille.
    #   On flipped truck (grille=364): pivot = 364 - 143 = 221  (extends FAR LEFT)
    #   On unflipped truck (grille=660): pivot = 660 - 143 = 517 (already tested in v5)
    #
    # But the reference also shows plow extending FORWARD-of-truck.  When the
    # truck is angled left (flipped), forward-of-truck is the LEFT direction,
    # so pivot LEFT of grille is correct.

    variants = [
        # (label, flip_truck, flip_plow, pivot_x, pivot_y, plow_width)
        # PERMUTATIONS at sane defaults
        ("perm1_TF_PF",   True,  True,  221, 322, 707),
        ("perm2_TF_PU",   True,  False, 221, 322, 707),
        ("perm3_TU_PF",   False, True,  517, 322, 707),
        ("perm4_TU_PU",   False, False, 517, 322, 707),
        # On the most-likely-correct combo (truck flipped + plow flipped),
        # also try a slight reposition + a slight resize
        ("perm1_low",     True,  True,  221, 360, 707),
        ("perm1_higher",  True,  True,  221, 290, 707),
        ("perm1_right",   True,  True,  280, 322, 707),
        ("perm1_bigger",  True,  True,  221, 322, 800),
        ("perm1_smaller", True,  True,  221, 322, 600),
        # And plow-only flip variants for completeness
        ("perm3_low",     False, True,  517, 360, 707),
    ]

    for label, ft, fp, px, py, pw in variants:
        out = composite_at_pivot(plow, truck, px, py, pw,
                                 flip_truck=ft, flip_plow=fp)
        outpath = OUTPUT_DIR / f"{label}_pivot{px}x{py}_w{pw}.png"
        out.save(outpath)
        print(f"  {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
