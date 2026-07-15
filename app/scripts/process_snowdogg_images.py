"""Download SnowDogg plow images from the open PIM CDN + run rembg.

The product detail pages on www.buyersproducts.com are Cloudflare-protected
(scripted requests get the JS challenge), but the image CDN at
pimimages.buyersproducts.com is OPEN — once we know the image filenames
(harvested via Chrome MCP per page), we can download + process them in pure
Python with no browser involvement.

For each catalog SnowDogg plow this script:
  1. Downloads the hero image from pimimages.buyersproducts.com/products/Documents/
  2. If the image is a 2-up composite (rear + front like the MDII NS shot),
     crops to bottom half (front view)
  3. Runs rembg isnet for transparent PNG
  4. Writes to manufacturer_data/snowdogg/<slug>/media/hero/
  5. Replicates to every catalog SKU folder for that plow

Run after collecting image URLs via Chrome MCP per-page recon.

Usage:
    python -m app.scripts.process_snowdogg_images
    python -m app.scripts.process_snowdogg_images --plow snowdogg-mdii
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image
from rembg import new_session, remove


SKUS_ROOT = (
    Path(__file__).resolve().parent.parent
    / "backend" / "static" / "snow-plows" / "skus"
)
DATA_ROOT = (
    Path(__file__).resolve().parent.parent
    / "backend" / "static" / "snow-plows" / "manufacturer_data" / "snowdogg"
)
PIM_BASE = "https://pimimages.buyersproducts.com/products/Documents"

# Discovered via Chrome MCP recon of each detail page.  Add as each plow
# is verified.  The "is_2up" flag means the image is a vertical composite
# (rear+front stacked) and we need to crop the bottom half before rembg.
SNOWDOGG_PLOWS: dict[str, dict] = {
    # All 12 SnowDogg truck/UTV plows — image filenames discovered via
    # Chrome MCP recon Apr 28 2026.  Many models offer dedicated "moldboard"
    # studio shots in addition to lifestyle hero images; we prefer those.
    "snowdogg-mdii": {
        "model": "MDII",
        "image": "MDII-moldboard-combined-NS.jpg",
        "is_2up": True,
        "skus": ["SNOW:16020412-EQP"],   # catalog snowdogg-md-series
    },
    "snowdogg-vxxii": {
        "model": "VXXII",
        "image": "VXXII_HeroImage.jpg",
        "is_2up": False,
        "skus": [],
    },
    "snowdogg-vxfii": {
        "model": "VXFII",
        # VXFII250_FRONT.jpg is a clean front view; the *_Hero-Image is the
        # lifestyle banner.
        "image": "VXFII250_FRONT.jpg",
        "is_2up": False,
        "skus": ["SNOW:16020724-EQP"],   # catalog snowdogg-vxf-series
    },
    "snowdogg-exii": {
        "model": "EXII",
        "image": "EXII_Hero-Image-(1326-x-451).jpg",
        "is_2up": False,
        "skus": ["SNOW:16020612-EQP"],   # catalog snowdogg-ex-series
    },
    "snowdogg-hdii": {
        "model": "HDII",
        "image": "HD-SERIES.jpg",
        "is_2up": False,
        "skus": [],
    },
    "snowdogg-teii": {
        "model": "TEII",
        "image": "TEII_front.jpg",
        "is_2up": False,
        "skus": [],
    },
    "snowdogg-vmxii": {
        "model": "VMXII",
        "image": "VMXII_Hero-Image-1326x451.jpg",
        "is_2up": False,
        "skus": ["SNOW:16020712-EQP"],   # catalog snowdogg-vx-series (V-plow MD-class)
    },
    "snowdogg-mxii": {
        "model": "MXII",
        "image": "MXII_Hero-Image-(1326-x-451).jpg",
        "is_2up": False,
        "skus": [],
    },
    "snowdogg-xpii": {
        "model": "XPII",
        # XPII_Moldboard-(2000-x-1540).jpg is the 2-up composite (rear + front)
        # at the same 2000x1540 resolution as the MDII NS.  Treat the same way.
        "image": "XPII_Moldboard-(2000-x-1540).jpg",
        "is_2up": True,
        "skus": ["SNOW:16020922-EQP"],   # catalog snowdogg-xp-series
    },
    "snowdogg-cmii": {
        "model": "CMII",
        "image": "CMII-moldboard.jpg",
        "is_2up": False,   # likely a clean single shot — verify
        "skus": [],
    },
    "snowdogg-vut": {
        "model": "VUT",
        "image": "VUT-Moldboard.jpg",
        "is_2up": False,
        "skus": [],
    },
    "snowdogg-mut": {
        "model": "MUT",
        "image": "MUT-Moldboard.jpg",
        "is_2up": False,
        "skus": [],
    },
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537"


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def process_plow(slug: str, info: dict, session) -> dict:
    image_filename = info["image"]
    url = f"{PIM_BASE}/{image_filename}"
    print(f"\n[{slug}]  {url}")
    try:
        raw = http_get(url)
    except Exception as e:
        return {"slug": slug, "ok": False, "error": str(e)}

    img = Image.open(BytesIO(raw)).convert("RGB")
    print(f"  source: {img.size}, {len(raw):,} bytes")

    # Crop if 2-up composite
    if info.get("is_2up"):
        w, h = img.size
        img = img.crop((0, int(h * 0.45), w, h))
        print(f"  cropped to front half: {img.size}")

    # rembg
    t0 = time.time()
    transparent = remove(
        img, session=session,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=20,
        alpha_matting_erode_size=10,
    )
    print(f"  isnet: {time.time() - t0:.1f}s")

    # Save into manufacturer_data
    plow_media = DATA_ROOT / slug / "media" / "hero"
    plow_media.mkdir(parents=True, exist_ok=True)
    img.save(plow_media / "front_manufacturer.jpg", "JPEG", quality=92)
    transparent.save(plow_media / "front_transparent.png", "PNG")

    # Replicate to SKU folders
    for sku in info.get("skus", []):
        sku_dir = SKUS_ROOT / sku.replace(":", "-")
        sku_dir.mkdir(parents=True, exist_ok=True)
        transparent.save(sku_dir / "hero_transparent.png", "PNG")
        img.save(sku_dir / "hero_manufacturer.jpg", "JPEG", quality=92)
    return {"slug": slug, "ok": True, "skus_written": len(info.get("skus", []))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plow")
    args = p.parse_args(argv)

    targets = (
        {args.plow: SNOWDOGG_PLOWS[args.plow]} if args.plow
        else {k: v for k, v in SNOWDOGG_PLOWS.items() if v.get("image")}
    )
    print(f"Processing {len(targets)} SnowDogg plow(s)")
    print("Loading rembg isnet session...")
    session = new_session("isnet-general-use")
    print("Ready.\n")
    results = [process_plow(s, info, session) for s, info in targets.items()]
    print()
    print("=== SUMMARY ===")
    for r in results:
        if r["ok"]:
            print(f"  OK   {r['slug']:<25s}  {r.get('skus_written',0)} SKU(s)")
        else:
            print(f"  FAIL {r['slug']:<25s}  {r.get('error')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
