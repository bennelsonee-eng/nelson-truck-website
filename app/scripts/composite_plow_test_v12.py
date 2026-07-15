"""V12: user picked v11 'a_user_ref_exact' (440, 335, w=800) and wants the
plow 20% BIGGER to start.  20% bigger = 800 * 1.20 = 960.

Iterating from there with small position adjustments to dial alignment in.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from rembg import remove, new_session


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v12"
TRUCK_TRANSPARENT_CACHE = REPO / "wan_test_output" / "composite_test_v11" / "_truck_transparent_cache.png"


def get_truck_transparent(truck_path: Path) -> Image.Image:
    if TRUCK_TRANSPARENT_CACHE.exists():
        print(f"  using cached truck transparent: {TRUCK_TRANSPARENT_CACHE.name}")
        return Image.open(TRUCK_TRANSPARENT_CACHE).convert("RGBA")
    print(f"  running rembg on {truck_path.name}...")
    session = new_session("isnet-general-use")
    truck_rgba = Image.open(truck_path).convert("RGBA")
    truck_only = remove(truck_rgba, session=session)
    truck_only.save(TRUCK_TRANSPARENT_CACHE)
    return truck_only


def composite_with_proper_depth(
    plow_src: Image.Image, truck_full: Image.Image, truck_transparent: Image.Image,
    pivot_x: int, pivot_y: int, plow_width: int,
) -> Image.Image:
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    out = truck_full.copy().convert("RGBA")
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    out.alpha_composite(truck_transparent, dest=(0, 0))
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")
    truck_transparent = get_truck_transparent(TRUCK_PATH)
    print(f"Truck: {truck.size}")
    print(f"Plow:  {plow.size}")

    # Base: 20% bigger than user pick (800 * 1.20 = 960)
    # Position sweep around (440, 335) with the new size
    variants = [
        # (label, pivot_x, pivot_y, plow_width)
        # === Anchor unchanged, 20% BIGGER ===
        ("a_baseline_960",      440, 335, 960),
        # === Slight Y adjustments ===
        ("b_y_360",             440, 360, 960),  # slightly lower
        ("c_y_320",             440, 320, 960),  # slightly higher
        ("d_y_380",             440, 380, 960),  # cutting edge near bottom
        # === Slight X adjustments ===
        ("e_x_410",             410, 335, 960),  # plow shifted left
        ("f_x_470",             470, 335, 960),  # plow shifted right
        # === Combination tweaks ===
        ("g_lower_left",        420, 360, 960),  # left + lower
        ("h_lower_right",       470, 360, 960),  # right + lower
        # === ALSO go a tad bigger and a tad smaller for size feel ===
        ("i_size_900",          440, 335, 900),  # smaller (12.5% bigger than v11 pick)
        ("j_size_1000",         440, 335, 1000), # bigger (25% bigger)
        ("k_size_1040",         440, 335, 1040), # 30% bigger
    ]

    for label, px, py, pw in variants:
        out = composite_with_proper_depth(plow, truck, truck_transparent, px, py, pw)
        outpath = OUTPUT_DIR / f"{label}_x{px}_y{py}_w{pw}.png"
        out.save(outpath)
        print(f"  saved {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
