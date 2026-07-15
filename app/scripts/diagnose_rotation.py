"""Diagnose: is the perspective rotation actually visible at the PIL
composite level, or does it disappear during Kontext post-processing?

Builds a side-by-side comparison grid for ONE plow (MVP Plus 8'6") at
multiple rotation values, both before and after Kontext.  We can then
visually verify:

  Row 1: PIL composite (before Kontext) at 0°, -30°, -60°, -90°
  Row 2: SAME composites after Kontext variant-C

If Row 1 shows clear differences but Row 2 looks similar → Kontext
is naturalizing.  If Row 1 also looks similar → our rotation math is
broken.
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
OUT_DIR = REPO / "wan_test_output" / "rotation_diagnostic"


GRILLE_CENTER_X = 560
TRUCK_PIVOT_Y = 380
TRUCK_SHIFT_X = -100
PLOW_WIDTH = 1000


# Test angles — at -90° the perspective transform becomes singular (right
# side collapses to a point), so we cap at -85°.
ANGLES = [0, -30, -60, -85]


def find_coeffs(pa, pb):
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0]*p1[0], -p2[0]*p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1]])
    A = np.matrix(matrix, dtype=np.float64)
    B = np.array(pb).reshape(8)
    res = np.dot(np.linalg.inv(A.T * A) * A.T, B)
    return np.array(res).reshape(8)


def rotate_into_page(img: Image.Image, angle_deg: float) -> Image.Image:
    W, H = img.size
    rad = np.radians(angle_deg)
    cos_a = np.cos(rad)
    sin_a = np.sin(abs(rad))
    if angle_deg < 0:
        flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
        result = rotate_into_page(flipped, -angle_deg)
        return result.transpose(Image.FLIP_LEFT_RIGHT)
    new_right_x = int(W * cos_a)
    vert_pinch = int(H * 0.3 * sin_a)
    src = [(0, 0), (W, 0), (W, H), (0, H)]
    dst = [(0, 0),
           (new_right_x, vert_pinch),
           (new_right_x, H - vert_pinch),
           (0, H)]
    coeffs = find_coeffs(dst, src)
    return img.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def grille_centered_pivot(plow_width: int, into_page_deg: float) -> int:
    if into_page_deg == 0:
        return GRILLE_CENTER_X
    rad = math.radians(abs(into_page_deg))
    compensation = int(plow_width * (1 - math.cos(rad)) / 2)
    sign = 1 if into_page_deg > 0 else -1
    return GRILLE_CENTER_X + sign * compensation


def composite(plow_src: Image.Image, truck: Image.Image, angle_deg: float) -> Image.Image:
    plow = plow_src
    if angle_deg:
        plow = rotate_into_page(plow, angle_deg)
    aspect = plow.height / plow.width
    plow_h = int(PLOW_WIDTH * aspect)
    plow_resized = plow.resize((PLOW_WIDTH, plow_h), Image.LANCZOS)
    pivot_x = grille_centered_pivot(PLOW_WIDTH, angle_deg)
    paste_x = pivot_x - PLOW_WIDTH // 2
    paste_y = TRUCK_PIVOT_Y - plow_h // 2
    truck_shifted = shift_truck_full(truck, TRUCK_SHIFT_X)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


async def kontext_pass(seed_img: Image.Image) -> Image.Image | None:
    seed_rgb = seed_img.convert("RGB")
    result = await render_plow_on_truck(
        truck_image=seed_rgb,
        plow_brand="", plow_model="",
        plow_blade_type=(
            "make this photorealistic, professional automotive product "
            "photography, matching studio lighting and shadows. "
            "Keep all text on the plow exactly as shown, brand logo and any "
            "model badge unchanged and clearly readable. "
            "PRESERVE the exact perspective angle of the plow as shown — "
            "do not make it head-on, keep the 3/4 angle."
        ),
        plow_reference_image=None, seed=42, steps=20, guidance=2.5, timeout_s=180,
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
    print(f"Truck: {truck.size}")
    print(f"Plow:  {plow.size}")

    pil_results = {}
    kontext_results = {}

    for angle in ANGLES:
        print(f"\n[angle {angle}°]")
        pil_comp = composite(plow, truck, angle)
        pil_path = OUT_DIR / f"pil_{angle:+d}deg.png"
        pil_comp.save(pil_path)
        pil_results[angle] = pil_comp.convert("RGB")
        print(f"  PIL composite saved: {pil_path.name}")

        kontext_out = await kontext_pass(pil_comp)
        if kontext_out is None:
            print(f"  Kontext FAILED")
            continue
        kontext_path = OUT_DIR / f"kontext_{angle:+d}deg.png"
        kontext_out.save(kontext_path)
        kontext_results[angle] = kontext_out
        print(f"  Kontext saved: {kontext_path.name}")

    # Build comparison grid: 2 rows × 4 cols
    TILE_W, TILE_H, LABEL_H = 640, 360, 30
    grid = Image.new("RGB", (4 * TILE_W, 2 * (TILE_H + LABEL_H) + 40), (40, 40, 40))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
        big_font = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
        big_font = font

    draw.text((20, 5), "Row 1: PIL composite (before Kontext)  |  Row 2: After Kontext variant-C",
              fill=(255, 255, 100), font=big_font)
    for i, angle in enumerate(ANGLES):
        x = i * TILE_W

        # Row 1: PIL
        y1 = 40
        if angle in pil_results:
            fitted = pil_results[angle].resize((TILE_W, TILE_H), Image.LANCZOS)
            grid.paste(fitted, (x, y1))
        draw.rectangle([x, y1 + TILE_H, x + TILE_W, y1 + TILE_H + LABEL_H], fill=(20, 20, 20))
        draw.text((x + 10, y1 + TILE_H + 7),
                  f"PIL {angle:+d}° (rotate_into_page only, no Kontext)",
                  fill=(255, 255, 255), font=font)

        # Row 2: Kontext
        y2 = 40 + TILE_H + LABEL_H
        if angle in kontext_results:
            fitted = kontext_results[angle].resize((TILE_W, TILE_H), Image.LANCZOS)
            grid.paste(fitted, (x, y2))
        draw.rectangle([x, y2 + TILE_H, x + TILE_W, y2 + TILE_H + LABEL_H], fill=(20, 20, 20))
        draw.text((x + 10, y2 + TILE_H + 7),
                  f"Kontext {angle:+d}° output",
                  fill=(255, 255, 255), font=font)

    grid_path = OUT_DIR / "rotation_diagnostic_grid.png"
    grid.save(grid_path)
    print(f"\nGrid saved: {grid_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
