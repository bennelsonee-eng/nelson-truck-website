"""V2 priority plow composites — all plows centered on the F-250 grille.

User direction: "all plows should try to be in the middle of the grill"

Math:
  - F-250 truck grille center (after truck_shift -100): x ≈ 560
  - Base pivot_x for any plow = 560 (puts plow's V-pivot/center at grille)
  - For plows with into-page rotation: add compensation
    pivot_x = 560 + plow_width * (1 - cos(angle_deg)) / 2
    (rotation shifts visual center LEFT; compensation shifts paste position RIGHT)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUT_DIR = REPO / "wan_test_output" / "priority_plows"

GRILLE_CENTER_X = 560  # F-250 grille center after truck_shift_x=-100
TRUCK_PIVOT_Y = 380
TRUCK_SHIFT_X = -100


# (sku, friendly name, plow_width, into_page_deg)
# - Base v3 priority plows (head-on source) — into_page=0 means no rotation
# - Per-plow rotation values to be tuned per user feedback
PRIORITY_CLEAN = [
    # All priority plows now have rotation BAKED INTO their source images
    # via Kontext rotation pass (fix_priority_plows.py).  No PIL into_page
    # rotation needed — Kontext won't naturalize away an angle that's
    # already in the source.
    # (SNOW-16020412 + SNOW-16020724 kept as head-on because Kontext
    # rotation failed for them — added trucks/morphed shape.)
    ("WEST-MVP3MS86-EQP",   "Western MVP3 8'6\" V-plow MS",          1000, 0),
    ("WEST-MVPPMS86-EQP",   "Western MVP Plus 8'6\" V-plow",         1000, 0),
    ("WEST-MVPPMS96-EQP",   "Western MVP Plus 9'6\" V-plow",         1050, 0),
    ("WEST-ENFMS76-EQP",    "Western Enforcer 7'6\" V-plow MS",      900,  0),
    ("WEST-ENFSS76-EQP",    "Western Enforcer 7'6\" V-plow SS",      900,  0),
    ("WEST-HTS76-EQP",      "Western HTS 7'6\" Straight",            900,  0),
    ("MYP-09275-EQP",       "Meyer Lot Pro LD 7'6\" Straight",       950,  0),
    ("SNOW-16020412-EQP",   "SnowDogg MD68II Straight (head-on)",    900,  0),
    ("SNOW-16020724-EQP",   "SnowDogg VXF85II V-plow (head-on)",     1050, 0),
    ("SNOW-16020922-EQP",   "SnowDogg XP810II Wing-plow",            1050, 0),
]


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
    """Compute pivot_x so the rotated plow's visual center lands at GRILLE_CENTER_X.

    Positive into_page_deg compresses image-right → visual center shifts LEFT
    → compensate by adding to pivot.
    Negative into_page_deg compresses image-left → visual center shifts RIGHT
    → compensate by subtracting from pivot.
    """
    if into_page_deg == 0:
        return GRILLE_CENTER_X
    rad = math.radians(abs(into_page_deg))
    compensation = int(plow_width * (1 - math.cos(rad)) / 2)
    sign = 1 if into_page_deg > 0 else -1
    return GRILLE_CENTER_X + sign * compensation


def composite(plow_src: Image.Image, truck: Image.Image,
              plow_width: int, into_page_deg: float = 0) -> Image.Image:
    plow = plow_src
    if into_page_deg:
        plow = rotate_into_page(plow, into_page_deg)
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    pivot_x = grille_centered_pivot(plow_width, into_page_deg)
    paste_x = pivot_x - plow_width // 2
    paste_y = TRUCK_PIVOT_Y - plow_h // 2

    truck_shifted = shift_truck_full(truck, TRUCK_SHIFT_X)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    truck = Image.open(TRUCK_PATH).convert("RGBA")
    print(f"Truck: {truck.size}")
    print(f"Grille center: x={GRILLE_CENTER_X} (after truck_shift_x={TRUCK_SHIFT_X})")
    print()

    for sku, name, width, into_page in PRIORITY_CLEAN:
        plow_path = SKUS_DIR / sku / "hero_transparent.png"
        if not plow_path.exists():
            print(f"  ! missing {sku}")
            continue
        plow = Image.open(plow_path).convert("RGBA")
        out = composite(plow, truck, plow_width=width, into_page_deg=into_page)
        outpath = OUT_DIR / f"{sku}_on_f250.png"
        out.save(outpath)
        pivot = grille_centered_pivot(width, into_page)
        print(f"  saved {outpath.name}  pivot_x={pivot} w={width} into_page={into_page}°")

    return 0


if __name__ == "__main__":
    sys.exit(main())
