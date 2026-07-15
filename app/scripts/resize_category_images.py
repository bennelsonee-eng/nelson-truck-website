#!/usr/bin/env python3
"""Downscale category-tile images to web-appropriate size.

WHY: the subcategory tiles on /catalog?category_top=... are served straight off
the app server (uvicorn /static, no CDN). They were stored at 900-1800px wide
but the UI only ever renders them at ~206px (≈412px on a 2x display). That made
the Exterior page pull ~1.6MB of imagery it immediately downscaled in the
browser — the slow-to-render tiles the owner noticed.

WHAT: resize every image in static/category-images/ so its longest side is at
most MAX_PX, re-encode (JPEG q=85 / PNG optimized), and write back in place,
preserving filename + extension (the DB image_url references these exact names).
Originals are copied ONCE into static/category-images/_originals/ (gitignored)
before the first resize so this is reversible.

Idempotent: an image already <= MAX_PX on its longest side is skipped.

Run from anywhere:
    python app/scripts/resize_category_images.py            # do it
    python app/scripts/resize_category_images.py --dry-run  # just report
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from PIL import Image

# 600px covers the largest tile (~206px CSS) at 2x+ device-pixel-ratio with
# headroom, while keeping files tiny. Bump if tiles are ever shown larger.
MAX_PX = 600
JPEG_QUALITY = 85

IMG_DIR = Path(__file__).resolve().parent.parent / "backend" / "static" / "category-images"
BACKUP_DIR = IMG_DIR / "_originals"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    if not IMG_DIR.is_dir():
        print(f"ERROR: {IMG_DIR} not found", file=sys.stderr)
        return 1

    files = sorted(
        p for p in IMG_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not args.dry_run:
        BACKUP_DIR.mkdir(exist_ok=True)

    before_total = after_total = 0
    resized = skipped = 0

    for p in files:
        orig_size = p.stat().st_size
        before_total += orig_size
        with Image.open(p) as im:
            w, h = im.size
            longest = max(w, h)
            if longest <= MAX_PX:
                skipped += 1
                after_total += orig_size
                continue

            if args.dry_run:
                scale = MAX_PX / longest
                print(f"would resize {p.name}: {w}x{h} -> "
                      f"{int(w*scale)}x{int(h*scale)} ({orig_size//1024}KB)")
                resized += 1
                continue

            # One-time backup of the original before we overwrite it.
            bak = BACKUP_DIR / p.name
            if not bak.exists():
                shutil.copy2(p, bak)

            im = im.copy()
            im.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
            fmt = im.format or ("PNG" if p.suffix.lower() == ".png" else "JPEG")
            if p.suffix.lower() in {".jpg", ".jpeg"}:
                if im.mode in ("RGBA", "P"):
                    im = im.convert("RGB")
                im.save(p, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
            else:
                im.save(p, "PNG", optimize=True)

        new_size = p.stat().st_size
        after_total += new_size
        resized += 1
        print(f"resized {p.name}: {orig_size//1024}KB -> {new_size//1024}KB")

    verb = "would shrink" if args.dry_run else "shrank"
    print(f"\n{resized} resized, {skipped} already small. "
          f"{verb} {before_total//1024//1024}MB -> {after_total//1024//1024}MB "
          f"({100 - after_total*100//max(before_total,1)}% smaller).")
    if not args.dry_run:
        print(f"originals backed up in {BACKUP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
