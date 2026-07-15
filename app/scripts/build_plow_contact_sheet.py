"""Build a single contact-sheet image showing all 61 plow extracts in a grid.

Each tile is the plow's hero_transparent.png on a checker pattern (so we can
clearly see what's plow vs background) with the SKU label below.

Output: wan_test_output/plow_contact_sheet.png

Usage: open the contact sheet, visually flag truck-contaminated tiles, build
the whitelist by editing the WHITELIST list at the bottom of this script.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUTPUT_PATH = REPO / "wan_test_output" / "plow_contact_sheet.png"


TILE_W = 320
TILE_H = 200
LABEL_H = 26
COLS = 5


def make_checker_bg(w: int, h: int, square: int = 16) -> Image.Image:
    """Light/dark grey checker so transparent areas are visible."""
    bg = Image.new("RGB", (w, h), (200, 200, 200))
    draw = ImageDraw.Draw(bg)
    for y in range(0, h, square):
        for x in range(0, w, square):
            if ((x // square) + (y // square)) % 2 == 0:
                draw.rectangle([x, y, x + square, y + square], fill=(170, 170, 170))
    return bg


def fit_into_tile(plow: Image.Image, tile_w: int, tile_h: int) -> Image.Image:
    """Fit plow image into tile while preserving aspect ratio."""
    src_w, src_h = plow.size
    scale = min(tile_w / src_w, tile_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    return plow.resize((new_w, new_h), Image.LANCZOS)


def main() -> int:
    sku_dirs = []
    for sku_dir in sorted(SKUS_DIR.iterdir()):
        if not sku_dir.is_dir() or sku_dir.name.startswith("_"):
            continue
        if (sku_dir / "hero_transparent.png").exists():
            sku_dirs.append(sku_dir)

    n = len(sku_dirs)
    rows = math.ceil(n / COLS)
    sheet_w = COLS * TILE_W
    sheet_h = rows * (TILE_H + LABEL_H)

    sheet = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    for i, sku_dir in enumerate(sku_dirs):
        row, col = divmod(i, COLS)
        tile_x = col * TILE_W
        tile_y = row * (TILE_H + LABEL_H)

        # Background checker pattern
        bg = make_checker_bg(TILE_W, TILE_H)
        sheet.paste(bg, (tile_x, tile_y))

        # Plow image, fit-to-tile
        plow = Image.open(sku_dir / "hero_transparent.png").convert("RGBA")
        fitted = fit_into_tile(plow, TILE_W - 8, TILE_H - 8)
        # Center it in the tile
        offset_x = tile_x + (TILE_W - fitted.width) // 2
        offset_y = tile_y + (TILE_H - fitted.height) // 2
        sheet.paste(fitted, (offset_x, offset_y), mask=fitted.split()[-1])

        # Label below
        label_y = tile_y + TILE_H
        draw.rectangle([tile_x, label_y, tile_x + TILE_W, label_y + LABEL_H],
                       fill=(40, 40, 40))
        draw.text((tile_x + 6, label_y + 5), sku_dir.name, fill=(255, 255, 255), font=font)

    sheet.save(OUTPUT_PATH)
    print(f"Built contact sheet of {n} plows in a {COLS}x{rows} grid")
    print(f"Saved: {OUTPUT_PATH}")
    print(f"Size: {sheet_w}x{sheet_h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
