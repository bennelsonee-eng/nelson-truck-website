"""Build a labeled contact sheet of each priority plow's CURRENT canonical
hero_transparent.png with its target angle annotation.

Shows the user exactly what each plow's source image looks like AFTER our
Kontext rotation pass (or head-on for the failures).  Each tile shows:
  - The plow image (transparent, on checker bg so transparency is obvious)
  - SKU + friendly name
  - Status: ROTATED (success) vs HEAD-ON (rotation failed)
  - Target angle: ~25° op-right (rotated) or 0° (head-on)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUT_PATH = REPO / "wan_test_output" / "plow_sources_with_angles.png"


# (sku, name, status, angle_label)
PLOWS = [
    ("WEST-MVP3MS86-EQP",   "Western MVP3 8'6\" V-plow MS",        "ROTATED", "~25° op-right"),
    ("WEST-MVPPMS86-EQP",   "Western MVP Plus 8'6\" V-plow",       "ROTATED", "~25° op-right"),
    ("WEST-MVPPMS96-EQP",   "Western MVP Plus 9'6\" V-plow",       "ROTATED", "~25° op-right"),
    ("WEST-ENFMS76-EQP",    "Western Enforcer 7'6\" V-plow MS",    "ROTATED", "~25° op-right"),
    ("WEST-ENFSS76-EQP",    "Western Enforcer 7'6\" V-plow SS",    "ROTATED", "~25° op-right"),
    ("WEST-HTS76-EQP",      "Western HTS 7'6\" Straight",          "ROTATED", "~25° op-right"),
    ("MYP-09275-EQP",       "Meyer Lot Pro LD 7'6\" Straight",     "ROTATED", "~25° op-right"),
    ("SNOW-16020922-EQP",   "SnowDogg XP810II Wing-plow",          "ROTATED", "~25° op-right"),
    ("SNOW-16020412-EQP",   "SnowDogg MD68II Straight",            "HEAD-ON", "0° (rotation failed)"),
    ("SNOW-16020724-EQP",   "SnowDogg VXF85II V-plow",             "HEAD-ON", "0° (rotation failed)"),
]


TILE_W = 380
TILE_H = 240
LABEL_H = 60
COLS = 5


def make_checker_bg(w: int, h: int, square: int = 16) -> Image.Image:
    bg = Image.new("RGB", (w, h), (200, 200, 200))
    draw = ImageDraw.Draw(bg)
    for y in range(0, h, square):
        for x in range(0, w, square):
            if ((x // square) + (y // square)) % 2 == 0:
                draw.rectangle([x, y, x + square, y + square], fill=(170, 170, 170))
    return bg


def fit_into_tile(img: Image.Image, w: int, h: int) -> Image.Image:
    sw, sh = img.size
    scale = min(w / sw, h / sh)
    return img.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)


def main() -> int:
    rows = (len(PLOWS) + COLS - 1) // COLS
    sheet_w = COLS * TILE_W
    sheet_h = rows * (TILE_H + LABEL_H) + 50
    sheet = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
        big_font = ImageFont.truetype("arial.ttf", 22)
        bold_font = ImageFont.truetype("arialbd.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
        big_font = font
        bold_font = font

    draw.text((20, 12), "Priority plow source images (hero_transparent.png) + target angle",
              fill=(20, 20, 20), font=big_font)

    for i, (sku, name, status, angle_label) in enumerate(PLOWS):
        row, col = divmod(i, COLS)
        tile_x = col * TILE_W
        tile_y = 50 + row * (TILE_H + LABEL_H)

        # Checker background to show transparency
        bg = make_checker_bg(TILE_W, TILE_H)
        sheet.paste(bg, (tile_x, tile_y))

        # Plow image
        plow_path = SKUS_DIR / sku / "hero_transparent.png"
        if plow_path.exists():
            plow = Image.open(plow_path).convert("RGBA")
            fitted = fit_into_tile(plow, TILE_W - 8, TILE_H - 8)
            ox = tile_x + (TILE_W - fitted.width) // 2
            oy = tile_y + (TILE_H - fitted.height) // 2
            sheet.paste(fitted, (ox, oy), mask=fitted.split()[-1])

        # Label box below
        label_y = tile_y + TILE_H
        status_color = (40, 130, 60) if status == "ROTATED" else (180, 80, 30)
        draw.rectangle([tile_x, label_y, tile_x + TILE_W, label_y + LABEL_H],
                       fill=(40, 40, 40))
        draw.text((tile_x + 8, label_y + 4), sku, fill=(255, 255, 100), font=bold_font)
        draw.text((tile_x + 8, label_y + 22), name[:48], fill=(220, 220, 220), font=font)
        draw.text((tile_x + 8, label_y + 38),
                  f"{status}  ·  {angle_label}",
                  fill=status_color, font=bold_font)

    sheet.save(OUT_PATH)
    print(f"saved: {OUT_PATH}")
    print(f"size:  {sheet.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
