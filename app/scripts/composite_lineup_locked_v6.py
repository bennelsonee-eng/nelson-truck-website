"""V6 lineup — uses the new MVP3 v2 reference (Kontext-rotated to op-right
viewpoint, WESTERN + MVP3 text correctly readable).

Key change vs v5: NO MORE PLOW FLIP.  The new MVP3 v2 reference has the right
camera angle natively, so we don't need to mirror it (which broke text).

Per-truck params kept from v5 (anchors / scales / shifts / truck flips were
all correct — only the plow source was wrong).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[2]
TRUCK_DIR = REPO / "wan_test_output" / "lineup_3q"
TRUCK_DIR_3500 = REPO / "wan_test_output" / "3500_new_seeds"
PLOW_PATH = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUTPUT_DIR = REPO / "app" / "backend" / "static" / "trucks" / "composites_3q"


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


def composite(plow_src: Image.Image, truck_full: Image.Image,
              pivot_x: int, pivot_y: int, plow_width: int,
              truck_shift_x: int, flip_truck: bool,
              flat_rotate_deg: int = 0,
              into_page_deg: int = 0) -> Image.Image:
    if flip_truck:
        truck_full = truck_full.transpose(Image.FLIP_LEFT_RIGHT)

    # NO PLOW FLIP — using the v2 reference which has correct orientation natively
    plow = plow_src
    if into_page_deg:
        plow = rotate_into_page(plow, into_page_deg)
    if flat_rotate_deg:
        plow = plow.rotate(flat_rotate_deg, expand=True, resample=Image.BICUBIC)

    aspect = plow.height / plow.width
    plow_h = int(plow_width * aspect)
    plow_resized = plow.resize((plow_width, plow_h), Image.LANCZOS)
    paste_x = pivot_x - plow_width // 2
    paste_y = pivot_y - plow_h // 2

    truck_shifted = shift_truck_full(truck_full, truck_shift_x)
    out = truck_shifted.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


# Per-truck params (re-using v5 anchors)
TRUCK_PROFILES = {
    "mid-size": ("seed8888", 660, 375, 850,  -100, False, 0,   0,  TRUCK_DIR),
    "1500":     ("seed8888", 630, 385, 920,  -100, False, 0,   0,  TRUCK_DIR),
    "2500":     ("seed1337", 540, 380, 1000, -100, False, 0,   0,  TRUCK_DIR),
    "3500":     ("seed7777", 600, 375, 900,  -100, False, 0,   0,  TRUCK_DIR_3500),
    "4500":     ("seed8888", 600, 315, 960,  -100, True,  -5,  25, TRUCK_DIR),
    "5500":     ("seed1337", 600, 315, 984,  -100, True,  -5,  25, TRUCK_DIR),
}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plow = Image.open(PLOW_PATH).convert("RGBA")
    print(f"Plow source: {PLOW_PATH.name} {plow.size} (NEW v2 — UNFLIPPED)")

    for cls, (seed, px, py, pw, ts, flip, flat_rot, into_page, src_dir) in TRUCK_PROFILES.items():
        truck_path = src_dir / f"{cls}_{seed}.png"
        if not truck_path.exists():
            print(f"  ! missing truck render: {truck_path}")
            continue
        truck = Image.open(truck_path).convert("RGBA")
        out = composite(plow, truck, px, py, pw, ts, flip, flat_rot, into_page)
        outpath = OUTPUT_DIR / f"{cls}_with_mvp3.png"
        out.save(outpath)
        flip_tag = " [FLIPPED]" if flip else ""
        rot_tag = f" flat={flat_rot}° into_page={into_page}°" if (flat_rot or into_page) else ""
        print(f"  saved {outpath.name}  pivot=({px},{py}) w={pw}{flip_tag}{rot_tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
