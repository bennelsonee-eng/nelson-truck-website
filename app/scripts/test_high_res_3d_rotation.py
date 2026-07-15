"""End-to-end test of the high-res 3D rotation pipeline on MVP3.

Pipeline:
  1. Load 1270x714 manufacturer source (hero_manufacturer.jpg)
  2. rembg → high-res clean transparent
  3. Apply 3D Y-axis rotation at 30°
  4. Save as new canonical hero_transparent.png
  5. Build F-250 composite at grille center
  6. Run Kontext variant-C
  7. Save result for comparison

Compare result to:
  - Previous (low-res Kontext-rotated) hero_transparent.png we currently have
"""

from __future__ import annotations

import asyncio
import math
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image
from rembg import remove, new_session


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.services.flux_kontext_service import (  # noqa: E402
    health_check,
    render_plow_on_truck,
)


SKU = "WEST-MVP3MS86-EQP"
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
OUT_DIR = REPO / "wan_test_output" / "highres_3d_test"

ROTATION_ANGLE = 30
FOCAL_FACTOR = 2.5

GRILLE_CENTER_X = 560
TRUCK_PIVOT_Y = 380
TRUCK_SHIFT_X = -100
PLOW_WIDTH_IN_COMPOSITE = 1000


def find_coeffs(pa, pb):
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0]*p1[0], -p2[0]*p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1]])
    A = np.matrix(matrix, dtype=np.float64)
    B = np.array(pb).reshape(8)
    res = np.dot(np.linalg.inv(A.T * A) * A.T, B)
    return np.array(res).reshape(8)


def rotate_3d(img: Image.Image, theta_y_deg: float, focal_factor: float = 2.5) -> Image.Image:
    img = img.convert("RGBA")
    W, H = img.size
    theta = math.radians(theta_y_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    half_w, half_h = W / 2, H / 2
    f = focal_factor * W
    cam_z = -f
    corners_3d = [
        (-half_w, -half_h, 0),
        ( half_w, -half_h, 0),
        ( half_w,  half_h, 0),
        (-half_w,  half_h, 0),
    ]
    rotated_3d = []
    for x, y, z in corners_3d:
        rotated_3d.append((x * cos_t - z * sin_t, y, x * sin_t + z * cos_t))
    projected = []
    for x, y, z in rotated_3d:
        z_rel = z - cam_z
        projected.append((
            (x / z_rel) * f + half_w,
            (y / z_rel) * f + half_h,
        ))
    src_2d = [(0, 0), (W, 0), (W, H), (0, H)]
    coeffs = find_coeffs(projected, src_2d)
    return img.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)


def shift_truck_full(truck_full: Image.Image, dx: int) -> Image.Image:
    bg_color = truck_full.crop((0, 0, 5, 5)).resize((1, 1)).getpixel((0, 0))
    out = Image.new("RGBA", truck_full.size, bg_color)
    out.paste(truck_full, (dx, 0))
    return out


def composite(plow: Image.Image, truck: Image.Image) -> Image.Image:
    aspect = plow.height / plow.width
    plow_h = int(PLOW_WIDTH_IN_COMPOSITE * aspect)
    plow_resized = plow.resize((PLOW_WIDTH_IN_COMPOSITE, plow_h), Image.LANCZOS)
    paste_x = GRILLE_CENTER_X - PLOW_WIDTH_IN_COMPOSITE // 2
    paste_y = TRUCK_PIVOT_Y - plow_h // 2
    truck_shifted = shift_truck_full(truck, TRUCK_SHIFT_X)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/6] Loading hi-res manufacturer source...")
    src_path = SKUS_DIR / SKU / "hero_manufacturer.jpg"
    if not src_path.exists():
        print(f"   ! missing: {src_path}")
        return 1
    src = Image.open(src_path).convert("RGBA")
    print(f"   source: {src.size}")
    src.save(OUT_DIR / "step1_source.png")

    print(f"\n[2/6] rembg on hi-res source...")
    session = new_session("isnet-general-use")
    transparent = remove(src, session=session)
    transparent.save(OUT_DIR / "step2_transparent.png")
    print(f"   transparent: {transparent.size}")

    print(f"\n[3/6] 3D Y-axis rotation at {ROTATION_ANGLE}° (focal {FOCAL_FACTOR}× width)...")
    rotated = rotate_3d(transparent, ROTATION_ANGLE, focal_factor=FOCAL_FACTOR)
    rotated.save(OUT_DIR / "step3_rotated.png")
    print(f"   rotated: {rotated.size}")

    print(f"\n[4/6] Compositing onto F-250...")
    truck = Image.open(TRUCK_PATH).convert("RGBA")
    pil_composite = composite(rotated, truck)
    pil_composite.save(OUT_DIR / "step4_pil_composite.png")
    print(f"   composite: {pil_composite.size}")

    print(f"\n[5/6] Kontext variant-C...")
    if not await health_check():
        print("   ! ComfyUI not reachable")
        return 1
    result = await render_plow_on_truck(
        truck_image=pil_composite.convert("RGB"),
        plow_brand="", plow_model="",
        plow_blade_type=(
            "make this photorealistic, professional automotive product photography, "
            "matching studio lighting and shadows. Keep all text on the plow exactly "
            "as shown. WESTERN logo and MVP3 badge must remain unchanged and clearly "
            "readable. PRESERVE the exact perspective angle of the plow."
        ),
        plow_reference_image=None,
        seed=42, steps=20, guidance=2.5, timeout_s=200,
    )
    if not result.ok or not result.image_bytes:
        print(f"   ! Kontext failed: {result.error}")
        return 1
    final = Image.open(BytesIO(result.image_bytes)).convert("RGB")
    final.save(OUT_DIR / "step5_kontext_final.png")
    print(f"   final: {final.size} ({result.duration_ms}ms)")

    print(f"\n[6/6] Saved all outputs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
