"""Rebuild specific plow composites with per-plow into-page perspective rotation.

User feedback: Meyer Lot Pro yellow needs ~30° into page; Western HTS red
needs ~60° into page.  Same rotate_into_page perspective transform we built
for chassis cabs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_PATH = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUT_DIR = REPO / "wan_test_output" / "priority_plows"


# (sku, plow_width, into_page_deg, pivot_x_override)
# pivot_x_override compensates for the LEFT shift of plow content caused by
# rotate_into_page (only the right side recedes, so visual center moves left).
# Compensation = plow_width * (1 - cos(angle)) / 2
#   30° on w=950: shift = 950 * (1 - 0.866) / 2 = ~64 → pivot 540+64 = 604
#   60° on w=900: shift = 900 * (1 - 0.500) / 2 = ~225 → pivot 540+225 = 765
# (using None means default pivot_x=540 — only override when rotation is applied)
PLOWS = [
    ("MYP-09275-EQP",  950, 30, 604),  # Meyer Lot Pro 30° → pivot shifted right to align center w/ grille
    ("WEST-HTS76-EQP", 900, 60, 765),  # Western HTS 60° → pivot shifted right
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
    """Y-axis 3D-style rotation. Positive angle = right side rotates AWAY from camera."""
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


def composite(plow_src: Image.Image, truck: Image.Image,
              pivot_x: int = 540, pivot_y: int = 380, plow_width: int = 1000,
              truck_shift_x: int = -100, into_page_deg: int = 0) -> Image.Image:
    plow = plow_src
    if into_page_deg:
        plow = rotate_into_page(plow, into_page_deg)
    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    truck_shifted = shift_truck_full(truck, truck_shift_x)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    truck = Image.open(TRUCK_PATH).convert("RGBA")

    for sku, width, into_page, pivot_x_override in PLOWS:
        plow_path = SKUS_DIR / sku / "hero_transparent.png"
        plow = Image.open(plow_path).convert("RGBA")
        pivot_x = pivot_x_override if pivot_x_override else 540
        out = composite(plow, truck, pivot_x=pivot_x, plow_width=width, into_page_deg=into_page)
        outpath = OUT_DIR / f"{sku}_on_f250.png"
        out.save(outpath)
        print(f"  saved {outpath.name}  pivot_x={pivot_x} w={width} into_page={into_page}°")

    return 0


if __name__ == "__main__":
    sys.exit(main())
