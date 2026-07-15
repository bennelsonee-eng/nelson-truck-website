"""V5 lineup composite — chassis cabs get a TRUE 3D-style perspective rotation
(not just a flat 2D tilt) so the plow's right side recedes into the scene.

User feedback: "needs to be rotated into the page another 25 degrees"

Approach: PIL perspective transform that maps the source rectangle's right
side INWARD (toward center) and slightly compresses vertically, simulating
Y-axis rotation in 3D space.

For 25° "into-page" rotation:
  - Right side foreshortened by cos(25°) ≈ 0.906
  - Right edge slightly pinched vertically (vanishing-point effect)
  - Left side unchanged (stays in foreground)
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
    """Compute the 8 PIL perspective coefficients.

    pa = destination corners (output coords)
    pb = source corners (input coords)
    """
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0]*p1[0], -p2[0]*p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1]])
    A = np.matrix(matrix, dtype=np.float64)
    B = np.array(pb).reshape(8)
    res = np.dot(np.linalg.inv(A.T * A) * A.T, B)
    return np.array(res).reshape(8)


def rotate_into_page(img: Image.Image, angle_deg: float) -> Image.Image:
    """Y-axis 3D rotation effect. Positive angle: right side rotates INTO page.

    Right side of image is:
      - Horizontally foreshortened (compressed inward)
      - Vertically pinched (vanishing point)
    Left side stays in the foreground.
    """
    W, H = img.size
    rad = np.radians(angle_deg)
    cos_a = np.cos(rad)
    sin_a = np.sin(abs(rad))

    # Output canvas keeps original W (we don't shrink overall width)
    # but the source's right side is mapped to a compressed trapezoid.
    new_right_x = int(W * cos_a)              # right edge moves inward by foreshortening
    vert_pinch = int(H * 0.3 * sin_a)         # right edge pinches vertically
    if angle_deg < 0:
        # Negative angle: flip the effect to LEFT side (left rotates into page)
        # mirror, transform, mirror back
        flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
        result = rotate_into_page(flipped, -angle_deg)
        return result.transpose(Image.FLIP_LEFT_RIGHT)

    # Source: full rectangle
    src = [(0, 0), (W, 0), (W, H), (0, H)]
    # Destination: trapezoid (right side compressed inward and pinched)
    dst = [(0, 0),
           (new_right_x, vert_pinch),
           (new_right_x, H - vert_pinch),
           (0, H)]
    coeffs = find_coeffs(dst, src)
    out = img.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    return out


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

    # Plow pipeline: flip → into-page perspective → flat 2D rotate → resize
    plow = plow_src.transpose(Image.FLIP_LEFT_RIGHT)
    if into_page_deg:
        # After flip, the plow's NEAR-camera blade is on the left.
        # "Into the page" = the FAR side (right of flipped plow) recedes.
        # Positive into_page_deg sends right side back.
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


# Per-truck params:
# (truck_seed, pivot_x, pivot_y, plow_width, truck_shift_x, flip_truck,
#  flat_rotate_deg, into_page_deg, source_dir)
TRUCK_PROFILES = {
    "mid-size": ("seed8888", 660, 375, 850,  -100, False, 0,   0,  TRUCK_DIR),
    "1500":     ("seed8888", 630, 385, 920,  -100, False, 0,   0,  TRUCK_DIR),
    "2500":     ("seed1337", 540, 380, 1000, -100, False, 0,   0,  TRUCK_DIR),
    "3500":     ("seed7777", 600, 375, 900,  -100, False, 0,   0,  TRUCK_DIR_3500),
    # Chassis cabs: -5° flat tilt (was -15, +10 CCW) + 25° into-page perspective
    "4500":     ("seed8888", 600, 315, 960,  -100, True,  -5,  25, TRUCK_DIR),  # -15 + 10 CCW = -5
    "5500":     ("seed1337", 600, 315, 984,  -100, True,  -5,  25, TRUCK_DIR),  # -15 + 10 CCW = -5
}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plow = Image.open(PLOW_PATH).convert("RGBA")

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
