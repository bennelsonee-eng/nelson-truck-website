"""Swap the 'VXX II' logo on SNOW-16020724 with the 'VXF' logo from the
VXFII-with-truck source image.

VXX is the 10'6" version of VXF — same physical plow, different size.
The user wants the SNOW-16020724 SKU (a VXF II) to display the VXF logo
instead of the VXX II logo that's on the cleaner source image.

Approach: crop the VXF logo region (a tight box around the 'VXF' text on
the left wing of the head-on shot), scale it to match the VXX text region's
size, and composite it over the existing VXX II text.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1].parent
SRC_VXF = Path("C:/Users/Ben/Pictures/Snowdogg front facing VXFII V-plow with truck.png")
DST = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "SNOW-16020724-EQP" / "hero_transparent.png"
DEBUG_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "_logo_debug"

# Crop box on the VXFII source (730x520 RGB) — the VXF logo + a margin of wing surface
VXF_CROP = (95, 295, 290, 385)  # (x0, y0, x1, y1)

# Where on the VXX cleaned plow (852x338 RGBA) the new VXF stamp should land
# This is the "VXX II" text region we're covering
VXX_TARGET = (50, 130, 220, 215)  # (x0, y0, x1, y1)


def main() -> int:
    if not SRC_VXF.exists():
        print(f"missing source: {SRC_VXF}")
        return 1
    if not DST.exists():
        print(f"missing target: {DST}")
        return 1

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    # Backup the existing VXX cleaned image (only first time)
    backup = DST.with_name("hero_transparent_PRE_VXFSWAP.png")
    if not backup.exists():
        shutil.copy2(DST, backup)
        print(f"backed up -> {backup.name}")

    src = Image.open(SRC_VXF).convert("RGBA")
    dst = Image.open(DST).convert("RGBA")

    # Crop the VXF logo
    vxf_stamp = src.crop(VXF_CROP)
    print(f"cropped VXF stamp: {vxf_stamp.size}")
    vxf_stamp.save(DEBUG_DIR / "vxf_stamp_raw.png")

    # Resize to match the VXX target box
    target_w = VXX_TARGET[2] - VXX_TARGET[0]
    target_h = VXX_TARGET[3] - VXX_TARGET[1]
    vxf_resized = vxf_stamp.resize((target_w, target_h), Image.LANCZOS)
    vxf_resized.save(DEBUG_DIR / "vxf_stamp_resized.png")

    # Composite over the VXX text region
    out = dst.copy()
    out.paste(vxf_resized, (VXX_TARGET[0], VXX_TARGET[1]))
    out.save(DST)
    print(f"saved {DST.name}")

    # Side-by-side preview
    preview = Image.new("RGBA", (dst.width, dst.height * 2 + 20), (30, 41, 59, 255))
    preview.paste(dst, (0, 0))
    preview.paste(out, (0, dst.height + 20))
    preview.save(DEBUG_DIR / "vxx_to_vxf_before_after.png")
    print(f"preview: {DEBUG_DIR / 'vxx_to_vxf_before_after.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
