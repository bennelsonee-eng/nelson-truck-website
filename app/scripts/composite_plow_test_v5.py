"""V5: composite math derived from the OFFICIAL Western MVP3 SS marketing photo
(REF2_western_mvp3ss_optimized.jpg).

Reference measurements (from a 1270x714 photo):
  - Truck grille center horizontal: x=690 (54% of width)
  - Plow V-pivot horizontal:        x=510 (40% of width)
  - Offset = pivot is 180px LEFT of grille center (~14% of image width)
  - Plow visible body width:        880px (69% of image width)
  - V-pivot vertical:               y=400 (56% of image height)
  - Cutting edge vertical:          y=560 (78% of image height)
  - Truck rotation in reference:    ~20-25° 3/4

Scaled to our 1024x576 truck render:
  - Plow V-pivot anchor:    x=410, y=322
  - Plow body width:        ~707px
  - Cutting edge ends at:   y=~436

We test BOTH v1 (35°) and v2 (15°) trucks since the reference falls between
them — pick whichever composite reads as more natural.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v5"

# Source plow image is 1270x714.  V-pivot in the source is at image center
# (the dark column where the wings hinge — about (635, 357) absolute).
PLOW_PIVOT_FRAC_X = 0.50
PLOW_PIVOT_FRAC_Y = 0.50


def composite_at_pivot(plow: Image.Image, truck: Image.Image,
                       pivot_x: int, pivot_y: int, plow_width: int) -> Image.Image:
    """Place plow so its V-pivot lands at (pivot_x, pivot_y) on the truck."""
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)

    pivot_offset_x = int(plow_width * PLOW_PIVOT_FRAC_X)
    pivot_offset_y = int(plow_h * PLOW_PIVOT_FRAC_Y)
    paste_x = pivot_x - pivot_offset_x
    paste_y = pivot_y - pivot_offset_y

    out = truck.copy().convert("RGBA")
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


TRUCK_VARIANTS = {
    "v1_35deg":  REPO / "wan_test_output" / "lineup_3q"    / "2500_seed1337.png",
    "v2_15deg":  REPO / "wan_test_output" / "lineup_3q_v2" / "2500_seed1337.png",
}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    plow = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Plow source: {plow.size}")

    # Reference-derived defaults: pivot=(410, 322), plow_width=707
    # Sweep around them to find best fit
    composites = [
        ("a_ref_default",  410, 322, 707),
        ("b_pivot_left",   380, 322, 707),
        ("c_pivot_right",  440, 322, 707),
        ("d_higher",       410, 290, 707),
        ("e_lower",        410, 360, 707),
        ("f_bigger",       410, 322, 800),
        ("g_smaller",      410, 322, 600),
    ]

    for tname, tpath in TRUCK_VARIANTS.items():
        truck = Image.open(tpath).convert("RGBA")
        print(f"\n=== {tname} ({truck.size}) ===")
        for label, px, py, pw in composites:
            out = composite_at_pivot(plow, truck, px, py, pw)
            outpath = OUTPUT_DIR / f"{tname}_{label}_pivot{px}x{py}_w{pw}.png"
            out.save(outpath)
            print(f"  {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
