"""V15: UNFLIPPED plow (so WESTERN text reads normally) — fix the mirrored
text issue from v14.

The plow image's intrinsic orientation:
  - WESTERN branding on the RIGHT blade panel, reads normally
  - Right blade is the camera-near blade (more prominently visible)
  - Left blade extends to the left, less detail

For the v1 unflipped truck (passenger side close to camera, nose pointing
slightly LEFT), the plow's operator-LEFT blade should be on the camera-near
side (truck's passenger side, image-RIGHT).

In the UNFLIPPED plow image, the IMAGE-RIGHT blade has WESTERN text. Putting
this on the truck's image-right side (passenger near-camera) means:
  - WESTERN text on the right side of plow (camera-near blade)
  - Plow's left blade extends to the IMAGE-LEFT (away from truck, in front of
    truck's nose direction)
  - V-pivot at truck's grille center

This matches REF2's geometry: V-pivot at truck grille, plow body spread
across with the WESTERN-branded blade on the truck-near side.

Trade-off: we lose the "plow body extends mostly left" look the user liked
in perm3.  Plow body now spreads left+right around V-pivot.  But text reads.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v15"


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
    """No flip, no occlusion — plow goes fully on top of truck, with text correct."""
    plow = plow_src  # NO FLIP — text reads correctly
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

    # In the UNFLIPPED plow image, the WESTERN-branded blade extends to the
    # RIGHT of V-pivot.  For the WESTERN blade to land on the truck (near-camera
    # side, image-right), we want the V-pivot to the LEFT of where the truck's
    # right side is.
    # Truck's right side (passenger) at image-right: roughly x=900 in unshifted
    # image.  V-pivot needs to be such that V-pivot + plow_width/2 lands around
    # x=900-ish.  For width 960: V-pivot = 900 - 480 = 420.
    # But user wants plow shifted right + truck shifted left.

    variants = [
        # (label, pivot_x, pivot_y, plow_width, truck_shift_x)
        # === Truck shifted -100 (user's preferred shift), unflipped plow ===
        ("a_t-100_pl420",    420, 380, 960, -100),
        ("b_t-100_pl460",    460, 380, 960, -100),
        ("c_t-100_pl500",    500, 380, 960, -100),
        ("d_t-100_pl540",    540, 380, 960, -100),
        # === Try with smaller plow ===
        ("e_t-100_pl500_w800",  500, 380, 800, -100),
        ("f_t-100_pl500_w900",  500, 380, 900, -100),
        # === Y adjustments ===
        ("g_t-100_pl500_y320",  500, 320, 960, -100),
        ("h_t-100_pl500_y400",  500, 400, 960, -100),
        # === Different truck shifts ===
        ("i_t-50_pl500",     500, 380, 960, -50),
        ("j_t-150_pl500",    500, 380, 960, -150),
    ]

    for label, px, py, pw, ts in variants:
        out = composite_unflipped(plow, truck, px, py, pw, ts)
        outpath = OUTPUT_DIR / f"{label}.png"
        out.save(outpath)
        print(f"  saved {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
