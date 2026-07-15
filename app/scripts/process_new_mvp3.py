"""Process the new MVP3 plow rotation: rembg → new transparent → v5 composite.

Steps:
  1. Run rembg on PLOW_ROTATED_p3_op_right_view.png to make it transparent
  2. Save as new reference: WEST-MVP3MS86-EQP_v2_oprright.png
  3. Build new F-250 composite using the new plow at proper anchor
  4. Save to composites_3q/ (variant naming: _v2)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from rembg import remove, new_session


REPO = Path(__file__).resolve().parents[2]
SRC_PLOW = REPO / "wan_test_output" / "PLOW_ROTATED_p3_op_right_view.png"
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
NEW_PLOW_REF = REPO / "wan_test_output" / "MVP3_v2_op_right_transparent.png"
COMPOSITE_OUT = REPO / "wan_test_output" / "f250_with_mvp3_v2.png"


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def main() -> int:
    # 1. rembg the new plow
    print("[1/3] Running rembg on new MVP3 plow...")
    session = new_session("isnet-general-use")
    src = Image.open(SRC_PLOW).convert("RGBA")
    print(f"  source: {src.size}")
    transparent = remove(src, session=session)
    transparent.save(NEW_PLOW_REF)
    print(f"  saved: {NEW_PLOW_REF.name}")

    # 2. Composite onto F-250 using the same anchor logic as v5
    # Now the plow is UNFLIPPED (correct orientation) so we don't need
    # PIL.transpose. Use the locked v5 anchors for 2500 (pivot 540, 380; w=1000)
    # but adjust if the new plow has different intrinsic proportions.
    print("\n[2/3] Building new F-250 composite...")
    truck = Image.open(TRUCK_PATH).convert("RGBA")
    print(f"  truck: {truck.size}")
    plow = Image.open(NEW_PLOW_REF).convert("RGBA")
    print(f"  plow:  {plow.size}")

    # New plow anchor params (we may need to iterate)
    pivot_x, pivot_y = 540, 380
    plow_width = 1000
    truck_shift_x = -100

    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    truck_shifted = shift_truck_full(truck, truck_shift_x)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    out.save(COMPOSITE_OUT)
    print(f"  saved: {COMPOSITE_OUT.name}")

    print("\n[3/3] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
