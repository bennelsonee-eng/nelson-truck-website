"""V2 VXF logo swap — render fresh text instead of crop+paste.

The VXF source image (Snowdogg front facing VXFII V-plow with truck.png)
has a tan/gold wing color. The VXX cleaned plow has a silver/stainless
wing. Crop+paste leaves a visible color patch.

V2 approach:
  1. Restore from PRE_VXFSWAP backup so we start clean.
  2. Sample the wing's actual silver color from adjacent pixels.
  3. Fill the VXX text region with that silver (covers existing VXX text).
  4. Render fresh "VXFII" text in black using Impact (or Arial Black fallback).

Result: silver wing with new VXF II branding, matching the rest of the plow.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parents[1].parent
DST = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "SNOW-16020724-EQP" / "hero_transparent.png"
BACKUP = DST.with_name("hero_transparent_PRE_VXFSWAP.png")
DEBUG_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "_logo_debug"

# Cover bbox: enlarged so the VXX text sits well inside the SOLID interior
# (not in the feathered edge zone). The feather=24 means text needs to be
# at least 30px inside any edge of cover_bbox to be fully covered.
VXX_TEXT_BBOX = (10, 100, 270, 280)
# VXFII text matched to VMXII size from the VMD75 II plow image
# (~14.7% width × 16.4% height of plow image dimensions).
# For 852x338: ~125 wide × 55 tall, centered around the original VXX position.
VXFII_TEXT_BBOX = (75, 155, 200, 210)
COVER_FEATHER_PX = 24

# A nearby clean area of the wing surface, for color sampling.
# x=230-280 had the dark V-pivot column. The silver wing is FURTHER LEFT,
# but the VXX text dominates that area. Sample BELOW the text instead.
WING_SAMPLE_BBOX = (60, 240, 200, 285)

# Candidate font paths on Windows; first one that exists wins.
FONT_CANDIDATES = [
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/ariblk.ttf",     # Arial Black
    "C:/Windows/Fonts/bahnschrift.ttf",
]


def find_font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def sample_wing_color(img: Image.Image, bbox: tuple) -> tuple:
    """Median RGB color of the sample region — robust to small artifacts."""
    region = img.crop(bbox).convert("RGB")
    pixels = list(region.getdata())
    # Use simple average
    n = len(pixels)
    r = sum(p[0] for p in pixels) // n
    g = sum(p[1] for p in pixels) // n
    b = sum(p[2] for p in pixels) // n
    return (r, g, b, 255)


def main() -> int:
    if not BACKUP.exists():
        print(f"missing backup: {BACKUP}")
        print("Cannot revert; aborting before destructive edit.")
        return 1
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Restore from backup so we start clean
    shutil.copy2(BACKUP, DST)
    print(f"restored from backup: {BACKUP.name}")

    img = Image.open(DST).convert("RGBA")
    print(f"plow image: {img.size}")

    # 2. Cover the VXX text region with a clean wing-color fill, blended
    # smoothly into the surrounding wing via a feathered mask. This is the
    # most reliable way to eliminate VXX letterforms — paint over them
    # entirely with sampled clean color, then soften the edges.
    cover_bbox = VXX_TEXT_BBOX
    feather = COVER_FEATHER_PX

    # Sample clean wing color from below the text area
    sample_bbox = WING_SAMPLE_BBOX
    wing_color = sample_wing_color(img, sample_bbox)
    print(f"sampled wing color: RGB{wing_color[:3]}")

    # Make a SOLID FILL image of the wing color (full image size, single color)
    fill = Image.new("RGBA", img.size, wing_color)

    # Mask: solid white inside cover_bbox + feathered to 0 over `feather` pixels OUT
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rectangle(cover_bbox, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))

    # Composite the solid fill over the original using the soft mask
    img = Image.composite(fill, img, mask)

    d = ImageDraw.Draw(img)

    # 4. Render fresh "VXFII" in black, sized to fit a SMALLER inner box (the
    # cover patch is generous to hide the VXX text; the text itself is smaller).
    text_bbox = VXFII_TEXT_BBOX
    box_w = text_bbox[2] - text_bbox[0]
    box_h = text_bbox[3] - text_bbox[1]

    # Try font sizes until the text fits the box width
    text = "VXFII"
    best_size = 12
    for size in range(20, 200, 2):
        font = find_font(size)
        # Pillow >=10: use textbbox; older: use textsize
        try:
            tb = d.textbbox((0, 0), text, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except AttributeError:
            tw, th = d.textsize(text, font=font)
        if tw > box_w * 0.92 or th > box_h * 0.85:
            break
        best_size = size

    font = find_font(best_size)
    print(f"chose font size: {best_size}")

    # Center the text in the box
    try:
        tb = d.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        # textbbox might return non-zero origin offsets — adjust
        offset_x = tb[0]
        offset_y = tb[1]
    except AttributeError:
        tw, th = d.textsize(text, font=font)
        offset_x = offset_y = 0

    text_x = text_bbox[0] + (box_w - tw) // 2 - offset_x
    text_y = text_bbox[1] + (box_h - th) // 2 - offset_y
    d.text((text_x, text_y), text, fill=(0, 0, 0, 255), font=font)

    img.save(DST)
    print(f"saved {DST.name}")

    # Save before/after for review
    before = Image.open(BACKUP).convert("RGBA")
    preview = Image.new("RGBA", (img.width, img.height * 2 + 20), (30, 41, 59, 255))
    preview.paste(before, (0, 0))
    preview.paste(img, (0, img.height + 20))
    preview.save(DEBUG_DIR / "vxx_to_vxf_v2_before_after.png")
    print(f"preview: {DEBUG_DIR / 'vxx_to_vxf_v2_before_after.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
