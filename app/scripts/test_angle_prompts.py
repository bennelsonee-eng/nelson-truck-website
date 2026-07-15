"""Test whether explicit angle-instruction prompts to Kontext can produce
the perspective change without needing PIL rotation.

User's idea: instead of pre-rotating the plow image (which Kontext washes
out), TELL Kontext the plow's current angle and desired target angle.
Kontext is instruction-following, so it might actually do the rotation when
explicitly asked.

Input: PIL composite of head-on MVP Plus on F-250 (NO rotation applied)
Variants: 4 different prompt strategies that name the angles explicitly.
"""

from __future__ import annotations

import asyncio
import math
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.services.flux_kontext_service import (  # noqa: E402
    health_check,
    render_plow_on_truck,
)


TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVPPMS86-EQP" / "hero_transparent.png"
OUT_DIR = REPO / "wan_test_output" / "angle_prompt_test"


GRILLE_CENTER_X = 560
TRUCK_PIVOT_Y = 380
TRUCK_SHIFT_X = -100
PLOW_WIDTH = 1000


PROMPTS = {
    "A_default": (
        "make this photorealistic, professional automotive product photography, "
        "matching studio lighting and shadows. Keep all text on the plow exactly "
        "as shown."
    ),
    "B_match_truck": (
        "Rotate the plow's perspective to match the truck's three-quarter angle. "
        "The truck is shown at a 3/4 view with passenger side close to camera. "
        "The plow currently appears head-on (perpendicular to the camera) — "
        "rotate it so its perspective matches the truck. Photorealistic, "
        "preserve all branding text."
    ),
    "C_explicit_angles": (
        "The plow in this image is currently at 0 degrees (head-on, camera "
        "straight on). The truck behind it is at approximately 30 degrees "
        "three-quarter rotation. Rotate the plow to 30 degrees to match the "
        "truck. The plow's operator-left blade should be camera-near (foreground); "
        "the operator-right blade should recede back into the scene. "
        "Photorealistic automotive product photography. Keep WESTERN logo readable."
    ),
    "D_describe_what_change": (
        "Render this scene as a real photograph of a V-plow mounted on the "
        "front of the truck. The plow should NOT appear head-on — it should "
        "have the same 3/4 perspective as the truck, with one blade closer to "
        "camera (left side, foreground) and one blade receding back (right side, "
        "background). Plow body extends forward of bumper. Keep WESTERN logo "
        "readable."
    ),
}


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite_headon(plow: Image.Image, truck: Image.Image) -> Image.Image:
    """Head-on plow (no rotation) onto truck, centered on grille."""
    aspect = plow.height / plow.width
    plow_h = int(PLOW_WIDTH * aspect)
    plow_resized = plow.resize((PLOW_WIDTH, plow_h), Image.LANCZOS)
    paste_x = GRILLE_CENTER_X - PLOW_WIDTH // 2
    paste_y = TRUCK_PIVOT_Y - plow_h // 2
    truck_shifted = shift_truck_full(truck, TRUCK_SHIFT_X)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


async def kontext_with_prompt(seed: Image.Image, prompt: str) -> Image.Image | None:
    result = await render_plow_on_truck(
        truck_image=seed.convert("RGB"),
        plow_brand="", plow_model="",
        plow_blade_type=prompt,
        plow_reference_image=None,
        seed=42, steps=20, guidance=2.5, timeout_s=180,
    )
    if not result.ok or not result.image_bytes:
        return None
    return Image.open(BytesIO(result.image_bytes)).convert("RGB")


async def main() -> int:
    if not await health_check():
        print("ComfyUI not reachable")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    truck = Image.open(TRUCK_PATH).convert("RGBA")
    plow = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Truck: {truck.size}, Plow: {plow.size}")

    seed = composite_headon(plow, truck)
    seed_path = OUT_DIR / "_seed_headon.png"
    seed.save(seed_path)
    print(f"Seed (head-on): {seed_path.name}")

    results = {}
    for label, prompt in PROMPTS.items():
        print(f"\n[{label}]")
        print(f"  prompt: {prompt[:90]}...")
        out = await kontext_with_prompt(seed, prompt)
        if out is None:
            print(f"  FAILED")
            continue
        out_path = OUT_DIR / f"{label}.png"
        out.save(out_path)
        print(f"  saved {out_path.name}")
        results[label] = out

    # Build a 1+4 grid: [seed | A | B | C | D]
    TILE_W, TILE_H, LABEL_H = 720, 405, 50
    grid = Image.new("RGB", (5 * TILE_W, TILE_H + LABEL_H + 30), (40, 40, 40))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        big_font = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
        big_font = font

    draw.text((20, 5), "Same head-on PIL seed → 4 different angle-instruction prompts to Kontext",
              fill=(255, 255, 100), font=big_font)

    # Tile 0: seed
    fitted = seed.resize((TILE_W, TILE_H), Image.LANCZOS)
    grid.paste(fitted, (0, 30))
    draw.rectangle([0, 30 + TILE_H, TILE_W, 30 + TILE_H + LABEL_H], fill=(20, 20, 20))
    draw.text((10, 30 + TILE_H + 8), "SEED — head-on plow on truck (no rotation)",
              fill=(255, 255, 255), font=font)

    # Tiles 1-4: prompted variants
    for i, label in enumerate(["A_default", "B_match_truck", "C_explicit_angles", "D_describe_what_change"]):
        x = (i + 1) * TILE_W
        if label in results:
            fitted = results[label].resize((TILE_W, TILE_H), Image.LANCZOS)
            grid.paste(fitted, (x, 30))
        draw.rectangle([x, 30 + TILE_H, x + TILE_W, 30 + TILE_H + LABEL_H], fill=(20, 20, 20))
        draw.text((x + 10, 30 + TILE_H + 8), label, fill=(255, 255, 255), font=font)

    grid.save(OUT_DIR / "angle_prompt_grid.png")
    print(f"\nGrid: {OUT_DIR / 'angle_prompt_grid.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
