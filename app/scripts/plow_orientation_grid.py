"""Build a labeled 3x4 contact grid of the 12 plow orientation candidates."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[2]
SRC_DIR = REPO / "wan_test_output" / "plow_orientations"
OUT_PATH = REPO / "wan_test_output" / "plow_orientation_grid.png"


TILE_W, TILE_H = 640, 360
LABEL_H = 28
COLS = 4
ANGLES = ["headon", "op_right", "op_left"]
SEEDS = [42, 1337, 8888, 31415]


def main() -> int:
    rows = len(ANGLES)
    sheet = Image.new("RGB", (COLS * TILE_W, rows * (TILE_H + LABEL_H)), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    for r, angle in enumerate(ANGLES):
        for c, seed in enumerate(SEEDS):
            path = SRC_DIR / f"{angle}_seed{seed}.png"
            x = c * TILE_W
            y = r * (TILE_H + LABEL_H)
            if path.exists():
                img = Image.open(path).convert("RGB")
                aspect = img.size[0] / img.size[1]
                if aspect > TILE_W / TILE_H:
                    new_w, new_h = TILE_W, int(TILE_W / aspect)
                else:
                    new_w, new_h = int(TILE_H * aspect), TILE_H
                fitted = img.resize((new_w, new_h), Image.LANCZOS)
                ox = x + (TILE_W - new_w) // 2
                oy = y + (TILE_H - new_h) // 2
                sheet.paste(fitted, (ox, oy))
            label = f"{angle} / seed {seed}"
            draw.rectangle([x, y + TILE_H, x + TILE_W, y + TILE_H + LABEL_H], fill=(20, 20, 20))
            draw.text((x + 8, y + TILE_H + 6), label, fill=(255, 255, 100), font=font)

    sheet.save(OUT_PATH)
    print(f"saved: {OUT_PATH} ({sheet.size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
