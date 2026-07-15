"""Apply the winning recipe to all priority plows that have hi-res sources.

Recipe:
  1. Load hero_manufacturer.jpg (high-res source)
  2. rembg -> clean transparent
  3. 3D Y-axis rotation at 30° (focal 2.5× width)
  4. Save as new canonical hero_transparent.png
     (back up old transparent as hero_transparent_v3_kontext_rot.png)
  5. The composite + Kontext step happens later via existing scripts.

Currently runs on the 6 SKUs with hi-res sources.
"""

from __future__ import annotations

import math
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rembg import remove, new_session


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"


# SKUs with hi-res manufacturer sources (audited this session)
PRIORITY_HIRES = [
    # Skip MVP3 — already done as test case
    # ("WEST-MVP3MS86-EQP", 30),
    ("WEST-HTS76-EQP",      30),
    ("MYP-09275-EQP",       30),
    ("SNOW-16020412-EQP",   30),
    ("SNOW-16020724-EQP",   30),
    ("SNOW-16020922-EQP",   30),
]

# 3D rotation params
FOCAL_FACTOR = 2.5


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
    corners_3d = [(-half_w, -half_h, 0), (half_w, -half_h, 0),
                  (half_w, half_h, 0), (-half_w, half_h, 0)]
    rotated_3d = [(x * cos_t - z * sin_t, y, x * sin_t + z * cos_t)
                  for x, y, z in corners_3d]
    projected = []
    for x, y, z in rotated_3d:
        z_rel = z - cam_z
        projected.append(((x / z_rel) * f + half_w,
                          (y / z_rel) * f + half_h))
    src_2d = [(0, 0), (W, 0), (W, H), (0, H)]
    coeffs = find_coeffs(projected, src_2d)
    return img.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)


def main() -> int:
    rembg_sess = new_session("isnet-general-use")

    for sku, angle in PRIORITY_HIRES:
        print(f"\n=== {sku} (rotate {angle}°) ===")
        sku_dir = SKUS_DIR / sku
        manuf = sku_dir / "hero_manufacturer.jpg"
        canonical = sku_dir / "hero_transparent.png"
        old_backup = sku_dir / "hero_transparent_v3_kontext_rot.png"

        if not manuf.exists():
            print(f"  ! missing hero_manufacturer.jpg")
            continue

        # Backup current canonical (the Kontext-rotated v3) if not yet backed up
        if canonical.exists() and not old_backup.exists():
            shutil.copy(canonical, old_backup)
            print(f"  backed up existing transparent -> {old_backup.name}")

        print(f"  [1/3] Loading hi-res source: {manuf.name}")
        src = Image.open(manuf).convert("RGBA")
        print(f"        source size: {src.size}")

        print(f"  [2/3] rembg + 3D rotate {angle}°...")
        transparent = remove(src, session=rembg_sess)
        rotated = rotate_3d(transparent, angle, focal_factor=FOCAL_FACTOR)
        print(f"        rotated size: {rotated.size}")

        print(f"  [3/3] Save as canonical hero_transparent.png")
        rotated.save(canonical)

    print(f"\nDone — {len(PRIORITY_HIRES)} plows processed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
