"""V11: depth occlusion using rembg ML segmentation for the truck mask.

V10's chroma-key mask failed because the FLUX truck is silver/white on a light
grey backdrop — too similar in luminance to threshold cleanly.  Using rembg
(isnet-general-use model) instead — proper neural segmentation that handles
this trivially.

Process:
  1. Run rembg on the truck render once -> truck-only transparent PNG (cached)
  2. Composite plow on truck (PIL alpha_composite)
  3. Paste truck-only on top with its own alpha mask -> proper depth ordering
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from rembg import remove, new_session


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v11"
TRUCK_TRANSPARENT_CACHE = OUTPUT_DIR / "_truck_transparent_cache.png"


def get_truck_transparent(truck_path: Path) -> Image.Image:
    """Run rembg on the truck once, cache result on disk."""
    if TRUCK_TRANSPARENT_CACHE.exists():
        print(f"  using cached truck transparent: {TRUCK_TRANSPARENT_CACHE.name}")
        return Image.open(TRUCK_TRANSPARENT_CACHE).convert("RGBA")
    print(f"  running rembg on {truck_path.name}...")
    session = new_session("isnet-general-use")
    truck_rgba = Image.open(truck_path).convert("RGBA")
    truck_only = remove(truck_rgba, session=session)
    truck_only.save(TRUCK_TRANSPARENT_CACHE)
    print(f"  saved {TRUCK_TRANSPARENT_CACHE.name}")
    return truck_only


def composite_with_proper_depth(
    plow_src: Image.Image, truck_full: Image.Image, truck_transparent: Image.Image,
    pivot_x: int, pivot_y: int, plow_width: int,
) -> Image.Image:
    """Composite with depth ordering: truck IN FRONT, plow visible only where
    truck doesn't cover."""
    # Flip plow (perm3 setup)
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    # Step 1: backdrop = truck_full (with backdrop)
    out = truck_full.copy().convert("RGBA")
    # Step 2: plow on top of backdrop (plow extends into truck region)
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    # Step 3: truck transparent on top — covers any plow pixels that overlap truck
    out.alpha_composite(truck_transparent, dest=(0, 0))
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Truck:           {truck.size}")
    print(f"Plow:            {plow.size}")

    truck_transparent = get_truck_transparent(TRUCK_PATH)
    print(f"Truck transparent: {truck_transparent.size}")

    # Try the v9 winners + the user-reference-tuned positions, all with proper
    # depth occlusion this time.
    variants = [
        # (label, pivot_x, pivot_y, plow_width)
        ("a_user_ref_exact",  440, 335, 800),
        ("k_v9_winner",       440, 380, 850),
        ("ref_match_1",       500, 360, 800),
        ("ref_match_2",       480, 380, 850),
        ("ref_match_3",       460, 360, 750),
        # additional positions trying to nail the user reference
        ("ref_match_4",       420, 370, 820),
        ("ref_match_5",       450, 370, 800),
        ("ref_match_6",       470, 360, 820),
    ]

    for label, px, py, pw in variants:
        out = composite_with_proper_depth(plow, truck, truck_transparent, px, py, pw)
        outpath = OUTPUT_DIR / f"{label}_x{px}_y{py}_w{pw}.png"
        out.save(outpath)
        print(f"  saved {outpath.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
