"""V13: shift truck LEFT and shift plow RIGHT to bring them closer together.

User feedback on v12 (20% bigger plow at v11_a position):
  "move the truck to the left and move the snowplow to the right"

Truck shift: pasted at negative X offset to translate the truck (and its
transparent counterpart) leftward.  The right side of the canvas becomes
empty backdrop where the truck used to be.

Plow shift: pivot_x increases (plow center moves right toward the truck).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from rembg import remove, new_session


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v13"
TRUCK_TRANSPARENT_CACHE = REPO / "wan_test_output" / "composite_test_v11" / "_truck_transparent_cache.png"


def get_truck_transparent(truck_path: Path) -> Image.Image:
    if TRUCK_TRANSPARENT_CACHE.exists():
        return Image.open(TRUCK_TRANSPARENT_CACHE).convert("RGBA")
    session = new_session("isnet-general-use")
    truck_rgba = Image.open(truck_path).convert("RGBA")
    truck_only = remove(truck_rgba, session=session)
    truck_only.save(TRUCK_TRANSPARENT_CACHE)
    return truck_only


def shift_image(img: Image.Image, dx: int, dy: int = 0) -> Image.Image:
    """Translate the image by (dx, dy) — fills new space with transparent."""
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (dx, dy))
    return out


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    """Shift the truck-with-backdrop image. Fills new space by extending the
    backdrop color (sampled from a corner of the source)."""
    arr_corner = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, arr_corner)
    out.paste(truck_full, (dx, 0))
    return out


def composite_with_proper_depth(
    plow_src: Image.Image, truck_full: Image.Image, truck_transparent: Image.Image,
    pivot_x: int, pivot_y: int, plow_width: int,
    truck_shift_x: int = 0,
) -> Image.Image:
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    # Shift truck (full + transparent) by truck_shift_x
    truck_shifted = shift_truck_full(truck_full, truck_shift_x)
    truck_t_shifted = shift_image(truck_transparent, truck_shift_x, 0)

    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    out.alpha_composite(truck_t_shifted, dest=(0, 0))
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")
    truck_transparent = get_truck_transparent(TRUCK_PATH)

    # Base: v11_a (440, 335, 800) + 20% bigger plow = w=960
    # Now also shifting truck left and plow right
    variants = [
        # (label, pivot_x, pivot_y, plow_width, truck_shift_x)
        # === Truck-shift sweep, plow at v11_a position ===
        ("a_truck_-50",      440, 335, 960, -50),
        ("b_truck_-100",     440, 335, 960, -100),
        ("c_truck_-150",     440, 335, 960, -150),
        # === Truck shifted -100, plow shifted right ===
        ("d_truck-100_pl500",  500, 335, 960, -100),
        ("e_truck-100_pl540",  540, 335, 960, -100),
        ("f_truck-100_pl580",  580, 335, 960, -100),
        # === Truck shifted -150, plow shifted right ===
        ("g_truck-150_pl500",  500, 335, 960, -150),
        ("h_truck-150_pl540",  540, 335, 960, -150),
        ("i_truck-150_pl580",  580, 335, 960, -150),
        # === Best-guess combo: shift both more ===
        ("j_truck-200_pl600",  600, 335, 960, -200),
        ("k_truck-200_pl640",  640, 335, 960, -200),
    ]

    for label, px, py, pw, ts in variants:
        out = composite_with_proper_depth(plow, truck, truck_transparent, px, py, pw, ts)
        outpath = OUTPUT_DIR / f"{label}.png"
        out.save(outpath)
        print(f"  saved {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
