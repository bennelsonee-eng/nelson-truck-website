"""Treat each plow PNG as a flat panel in 3D space and apply true 3D rotation.

vs the previous approach (Kontext text-prompt rotation):
  - No re-generation, no garbled text, no hallucinated trucks.
  - Original PNG resolution preserved.
  - Math is deterministic 3D camera projection.

For a flat plane in 3D rotated by θ around the Y-axis:
  - 4 corners at (±W/2, ±H/2, 0)
  - Rotated:    x' = x·cos(θ),  y' = y,  z' = x·sin(θ)
  - Projected back to 2D using perspective with camera at (0, 0, -d):
        x_2d = (x' / (z' - cam_z)) · |cam_z| + W/2
        y_2d = (y' / (z' - cam_z)) · |cam_z| + H/2

Where d (focal_length × W) controls how strong the perspective is.
Bigger d  = weaker perspective (looks more orthographic).
Smaller d = stronger perspective (more dramatic foreshortening).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUT_DIR = REPO / "wan_test_output" / "plow_3d_rotation"


def find_coeffs(pa, pb):
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0]*p1[0], -p2[0]*p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1]])
    A = np.matrix(matrix, dtype=np.float64)
    B = np.array(pb).reshape(8)
    res = np.dot(np.linalg.inv(A.T * A) * A.T, B)
    return np.array(res).reshape(8)


def rotate_3d(img: Image.Image, theta_y_deg: float, focal_length_factor: float = 2.5) -> Image.Image:
    """Rotate the image as a flat plane around Y-axis in 3D.

    Args:
      img: PIL Image (RGBA)
      theta_y_deg: rotation around Y-axis in degrees
                   positive → right side rotates BACK (away from camera)
                   negative → left side rotates BACK
      focal_length_factor: focal length as multiple of image width.
                          Higher = weaker perspective.  Typical 2-4.

    Returns: rotated image, same dimensions as input.
    """
    img = img.convert("RGBA")
    W, H = img.size
    theta = math.radians(theta_y_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    half_w, half_h = W / 2, H / 2

    # Camera focal length (distance from image plane in world units)
    f = focal_length_factor * W
    cam_z = -f  # camera is at z=-f, looking toward +z

    # 4 corners in 3D, centered at origin, image plane z=0
    corners_3d = [
        (-half_w, -half_h, 0),  # top-left
        ( half_w, -half_h, 0),  # top-right
        ( half_w,  half_h, 0),  # bottom-right
        (-half_w,  half_h, 0),  # bottom-left
    ]

    # Rotate each corner around Y-axis
    rotated_3d = []
    for x, y, z in corners_3d:
        x_new = x * cos_t - z * sin_t
        z_new = x * sin_t + z * cos_t
        rotated_3d.append((x_new, y, z_new))

    # Perspective project back to 2D
    # Camera at (0, 0, cam_z) = (0, 0, -f)
    # For point (X, Y, Z) in world, screen = (X/(Z-cam_z)) * f + center
    projected = []
    for x, y, z in rotated_3d:
        z_rel = z - cam_z  # always positive since cam_z is negative and z is small
        x_2d = (x / z_rel) * f + half_w
        y_2d = (y / z_rel) * f + half_h
        projected.append((x_2d, y_2d))

    # Use as destination quadrilateral for PIL PERSPECTIVE transform
    src_2d = [(0, 0), (W, 0), (W, H), (0, H)]
    coeffs = find_coeffs(projected, src_2d)

    return img.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)


def main() -> int:
    """Build a comparison grid: one plow at multiple angles + focal lengths."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Test on the OLD head-on MVP Plus (the v2_headon backup)
    test_plow_path = SKUS_DIR / "WEST-MVPPMS86-EQP" / "hero_transparent_v2_headon.png"
    if not test_plow_path.exists():
        print(f"FAIL: backup not found at {test_plow_path}")
        return 1

    plow = Image.open(test_plow_path).convert("RGBA")
    print(f"Source: {test_plow_path.name} {plow.size}")

    # Sweep angles + focal lengths
    angles = [10, 20, 30, 45, 60]
    focal_factors = [1.5, 2.5, 4.0]

    for fl in focal_factors:
        for angle in angles:
            rotated = rotate_3d(plow, angle, focal_length_factor=fl)
            out_path = OUT_DIR / f"mvpplus_3d_a{angle:+03d}_f{fl:.1f}.png"
            rotated.save(out_path)
            print(f"  saved {out_path.name}")

    # Build a 5×3 contact grid
    from PIL import Image as PILImage, ImageDraw, ImageFont
    TILE_W, TILE_H, LABEL_H = 360, 240, 24
    grid = PILImage.new("RGB", (len(angles) * TILE_W, len(focal_factors) * (TILE_H + LABEL_H)), (60, 60, 60))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font = ImageFont.load_default()

    for r, fl in enumerate(focal_factors):
        for c, angle in enumerate(angles):
            path = OUT_DIR / f"mvpplus_3d_a{angle:+03d}_f{fl:.1f}.png"
            if not path.exists():
                continue
            img = PILImage.open(path).convert("RGB")
            asp = img.size[0] / img.size[1]
            if asp > TILE_W / TILE_H:
                nw, nh = TILE_W, int(TILE_W / asp)
            else:
                nw, nh = int(TILE_H * asp), TILE_H
            fitted = img.resize((nw, nh), PILImage.LANCZOS)
            x = c * TILE_W
            y = r * (TILE_H + LABEL_H)
            ox = x + (TILE_W - nw) // 2
            oy = y + (TILE_H - nh) // 2
            grid.paste(fitted, (ox, oy))
            draw.rectangle([x, y + TILE_H, x + TILE_W, y + TILE_H + LABEL_H], fill=(20, 20, 20))
            draw.text((x + 8, y + TILE_H + 6),
                      f"angle={angle}°  focal={fl}× width", fill=(255, 255, 100), font=font)

    grid_path = OUT_DIR / "_3d_rotation_sweep_grid.png"
    grid.save(grid_path)
    print(f"\nSweep grid: {grid_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
