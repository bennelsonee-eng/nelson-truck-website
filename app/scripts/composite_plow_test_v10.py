"""V10: depth-occlusion composite to match user reference.

Problem with v3-v9: the plow's right blade always renders ON TOP of the truck
because PIL has no depth awareness.  In the user's reference photo, the plow's
right blade is HIDDEN BEHIND the truck (occluded by grille/bumper/hood).

Fix: use the truck render's own pixels as a depth mask.
  1. Composite plow on top of truck (current behavior — plow over truck)
  2. Take the original truck image, isolate just the truck body (non-backdrop)
  3. Paste truck body back on top of step 1 — covers any plow pixels where
     they overlap with the truck

This achieves proper depth ordering: truck IN FRONT, plow extending out
the front (visible only in the empty space to the left of the truck).

For step 2, we use a simple chroma-key on the FLUX backdrop (light grey).
The backdrop is roughly uniform RGB(220, 220, 220) — we threshold pixels
that are clearly NOT background and call those "truck."
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "wan_test_output" / "composite_test_v10"


def extract_truck_body_mask(truck: Image.Image, threshold: int = 30) -> Image.Image:
    """Build an alpha mask for the truck body, removing the FLUX backdrop.

    The backdrop is a smooth grey gradient. Truck pixels are darker/more
    saturated. We use a simple per-channel deviation from the background.
    """
    arr = np.asarray(truck.convert("RGB")).astype(np.int16)
    # Sample background from corners (top-left, top-right) to estimate bg color
    bg_samples = np.concatenate([
        arr[:30, :30].reshape(-1, 3),       # top-left
        arr[:30, -30:].reshape(-1, 3),      # top-right
        arr[-30:, -30:].reshape(-1, 3),     # bottom-right
    ])
    bg_color = np.median(bg_samples, axis=0)
    diff = np.abs(arr - bg_color).max(axis=2)
    # Pixels far from bg color are truck body
    truck_mask = (diff > threshold).astype(np.uint8) * 255
    # Clean up: small holes/dust filtered with a simple dilate-erode would help
    # but keep it simple for now.
    return Image.fromarray(truck_mask, mode="L")


def composite_with_occlusion(plow_src: Image.Image, truck_src: Image.Image,
                              pivot_x: int, pivot_y: int, plow_width: int,
                              mask_threshold: int = 30) -> tuple[Image.Image, Image.Image]:
    """Returns (without_occlusion, with_occlusion) for side-by-side compare."""
    # Flip the plow (perm3 setup)
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    # Step 1: plow on top of truck (current behavior)
    naive = truck_src.copy().convert("RGBA")
    naive.alpha_composite(plow_resized, dest=(paste_x, paste_y))

    # Step 2: paste truck body back on top of naive composite
    truck_mask = extract_truck_body_mask(truck_src, threshold=mask_threshold)
    occluded = naive.copy()
    occluded.paste(truck_src.convert("RGBA"), (0, 0), mask=truck_mask)

    return naive, occluded


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Truck: {truck.size}")
    print(f"Plow:  {plow.size}")

    # Save the truck mask itself for inspection
    mask = extract_truck_body_mask(truck, threshold=30)
    mask.save(OUTPUT_DIR / "_truck_mask_threshold30.png")
    print(f"  saved _truck_mask_threshold30.png")
    mask40 = extract_truck_body_mask(truck, threshold=40)
    mask40.save(OUTPUT_DIR / "_truck_mask_threshold40.png")
    mask50 = extract_truck_body_mask(truck, threshold=50)
    mask50.save(OUTPUT_DIR / "_truck_mask_threshold50.png")

    # Try the v9 winners with occlusion + a few new positions targeting
    # the user reference proportions
    variants = [
        # (label, pivot_x, pivot_y, plow_width)
        ("k_v9_winner_occluded",  440, 380, 850),
        ("a_v9_ref_occluded",     440, 335, 800),
        ("ref_match_1",           500, 360, 800),  # closer to grille
        ("ref_match_2",           480, 380, 850),  # bigger + lower + closer
        ("ref_match_3",           460, 360, 750),  # smaller, balanced
        ("ref_match_4",           520, 380, 800),  # even closer to truck
    ]

    for label, px, py, pw in variants:
        naive, occluded = composite_with_occlusion(plow, truck, px, py, pw, mask_threshold=30)
        naive_path = OUTPUT_DIR / f"{label}_NAIVE_x{px}_y{py}_w{pw}.png"
        occ_path = OUTPUT_DIR / f"{label}_OCCLUDED_x{px}_y{py}_w{pw}.png"
        naive.save(naive_path)
        occluded.save(occ_path)
        print(f"  {label}: naive + occluded saved")

    return 0


if __name__ == "__main__":
    sys.exit(main())
