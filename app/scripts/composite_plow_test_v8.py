"""V8: fine-tune around perm3 (TU+PF) which user picked as "close".

User feedback:
  1. perm3 is the right flip combo (truck unflipped, plow flipped)
  2. Needs slight alignment
  3. Size of plow vs size of truck should match the reference (REF2 official Western)

Re-measured REF2 (1270x714):
  - Truck grille center horizontal:    x=470 (37% of width)
  - V-pivot horizontal:                x=470 (SAME as grille — no offset)
  - Plow body visible width:           750px (59% of width)
  - V-pivot vertical:                  y=420 (59% of height) — just below bumper bar
  - Cutting edge vertical:             y=620 (87% of height) — at ground line
  - Truck bumper bar visible:          y=350 (49% of height)

Scaled to our 1024x576 truck render:
  - V-pivot anchor:    x=660 (at truck grille center), y=340 (just below bumper)
  - Plow body width:   ~604px
  - Cutting edge ends at:  y=~500 (at front wheel base)
  - Hmm, but unflipped v1 truck has grille at x=660 — that's our anchor.

Sweep variants to find the right look.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v8"


def composite_perm3(plow_src: Image.Image, truck_src: Image.Image,
                    pivot_x: int, pivot_y: int, plow_width: int) -> Image.Image:
    """Truck unflipped, plow FLIPPED.  Place V-pivot at (pivot_x, pivot_y)."""
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)  # perm3: flip plow only

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

    # Reference-derived target: pivot=(660, 340), width=604
    # But let's sweep around it because v1 truck's grille might be at a
    # different exact position than the reference's Silverado grille.

    variants = [
        # (label, pivot_x, pivot_y, plow_width)
        # === REFERENCE-EXACT (per re-measured REF2) ===
        ("a_ref_exact",      660, 340, 604),
        # === SIZE SWEEPS at ref position ===
        ("b_size_660",       660, 340, 660),
        ("c_size_700",       660, 340, 700),
        ("d_size_750",       660, 340, 750),
        ("e_size_550",       660, 340, 550),
        # === Y SWEEPS at ref size (find right vertical) ===
        ("f_y_300",          660, 300, 604),
        ("g_y_380",          660, 380, 604),
        ("h_y_420",          660, 420, 604),  # cutting edge near ground
        # === X SWEEPS (find right horizontal anchor) ===
        ("i_x_580",          580, 340, 604),  # V-pivot LEFT of grille
        ("j_x_620",          620, 340, 604),
        ("k_x_700",          700, 340, 604),  # V-pivot RIGHT of grille
        # === BEST-GUESS COMBO: bigger + lower ===
        ("l_combo_700_400",  660, 400, 700),  # bigger AND lower (cutting edge at ground)
        ("m_combo_660_400",  660, 400, 660),
    ]

    for label, px, py, pw in variants:
        out = composite_perm3(plow, truck, px, py, pw)
        outpath = OUTPUT_DIR / f"{label}_x{px}_y{py}_w{pw}.png"
        out.save(outpath)
        print(f"  {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
