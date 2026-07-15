"""V9: tune to user's new (tighter-cropped) reference.

User uploaded a tighter-cropped version of REF2.  Key differences:
  - Plow + truck FILL the frame (very little white space at edges)
  - Plow's cutting edge near image bottom
  - Plow's snow markers reach top of image
  - Plow body LARGER relative to frame than the original REF2 (which had
    significant white margin all around)

Re-measured user's tight crop (rough %s):
  - V-pivot horizontal:  ~43% of width
  - V-pivot vertical:    ~58% of height
  - Truck grille center: ~47% of width
  - Plow body width:     ~58% of width (visible portion only)
  - Cutting edge:        ~92% of height
  - Plow top (with markers): touches y=0

Scaled to our 1024x576:
  - V-pivot:             (440, 335)
  - Truck grille (in unflipped v1 truck): x=660 (we already know)
  - That means V-pivot is 220px LEFT of truck grille
  - Plow body width:     ~600 visible, but plow image bbox ~800 (includes white)
  - Cutting edge:        y~530

So the right answer is: pivot_x ~= 440 (NOT 660 like I had in v8 — I was
anchoring at truck grille, but reference shows V-pivot is offset left of grille
by ~220px, with the plow blocking the truck's grille area visually).

Plow_width ~= 800 (BIG plow, body fills LEFT 60% of frame).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v9"


def composite_perm3(plow_src: Image.Image, truck_src: Image.Image,
                    pivot_x: int, pivot_y: int, plow_width: int) -> Image.Image:
    """Truck unflipped, plow FLIPPED.  Place V-pivot at (pivot_x, pivot_y)."""
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2
    out = truck_src.copy().convert("RGBA")
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Truck: {truck.size}")
    print(f"Plow:  {plow.size}")

    variants = [
        # (label, pivot_x, pivot_y, plow_width)
        # === USER-REFERENCE-EXACT (tight crop) ===
        ("a_user_ref_exact",   440, 335, 800),
        # === SIZE SWEEPS at user-ref position ===
        ("b_w_750",            440, 335, 750),
        ("c_w_850",            440, 335, 850),
        ("d_w_900",            440, 335, 900),
        # === Y SWEEPS ===
        ("e_y_300",            440, 300, 800),
        ("f_y_360",            440, 360, 800),
        ("g_y_390",            440, 390, 800),  # cutting edge near image bottom
        # === X SWEEPS ===
        ("h_x_400",            400, 335, 800),  # V-pivot further LEFT
        ("i_x_480",            480, 335, 800),
        ("j_x_520",            520, 335, 800),  # V-pivot closer to truck grille
        # === COMBINATIONS ===
        ("k_combo_lower_big",  440, 380, 850),  # bigger AND lower (cutting edge bottom-aligned)
        ("l_combo_left_big",   400, 360, 850),  # plow shifted left + bigger
        ("m_combo_right_big",  480, 360, 850),  # plow shifted right + bigger
    ]

    for label, px, py, pw in variants:
        out = composite_perm3(plow, truck, px, py, pw)
        outpath = OUTPUT_DIR / f"{label}_x{px}_y{py}_w{pw}.png"
        out.save(outpath)
        print(f"  {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
