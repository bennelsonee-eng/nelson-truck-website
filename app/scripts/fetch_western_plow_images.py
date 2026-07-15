"""Pull press-quality plow images straight from westernplows.com.

User insight Apr 27 2026: "the great images are on the western snow plow
website at the bottom" — the WordPress media library at /wp-content/uploads/
hosts the manufacturer's own product photography (1270x714 typ., CMYK JPEGs
or PNGs).  Way higher fidelity than what Titan WSM scraped.

Per Western catalog plow:
  1. Download the best front-angle image
  2. Convert CMYK -> RGB if needed
  3. Run rembg isnet-general-use for clean transparent PNG
  4. Replicate into every SKU folder under that plow family
     (e.g. PRO PLUS image goes to WEST:PPMS86, WEST:PPMS8, WEST:PPMS9, WEST:PPHD10)

Output replaces hero_transparent.png in each affected SKU folder.

Usage:
    python -m app.scripts.fetch_western_plow_images
    python -m app.scripts.fetch_western_plow_images --dry-run
    python -m app.scripts.fetch_western_plow_images --plow western-pro-plus
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


SKUS_DIR = Path(__file__).resolve().parent.parent / "backend" / "static" / "snow-plows" / "skus"

# Map catalog plow_id -> (manufacturer image URL, list of moldboard SKUs to apply to)
# Image URLs gathered from Western WordPress media library by parsing each
# product page's image references.  Highest-resolution variant chosen.
WESTERN_PLOWS: dict[str, dict] = {
    "western-pro-plus": {
        "image_url": "https://westernplows.com/wp-content/uploads/2021/05/ProPlusHD_front_13.jpeg",
        "skus": ["WEST:PPMS86-EQP", "WEST:PPMS8-EQP", "WEST:PPMS9-EQP", "WEST:PPHD10-EQP"],
    },
    "western-pro-plow-3": {
        "image_url": "https://westernplows.com/wp-content/uploads/2024/05/WP_PRO-PLOW3_non-truck-application-hero.jpg",
        "skus": ["WEST:PPS2MS86-EQP", "WEST:PPS2MS8-EQP", "WEST:PPS2MS76-EQP",
                 "WEST:PPS2PLY8-EQP", "WEST:PPS2PLY76-EQP"],
    },
    "western-mvp-3": {
        # Was using WSTRN__HeroImage_MVP3.jpeg but that's a lifestyle/scene
        # shot with snow particles + sky background that rembg correctly
        # tries to keep, producing snow-spotted output.  MVP3_Front_Nav_LED
        # is the clean studio shot with the V in mid-attack position.
        "image_url": "https://westernplows.com/wp-content/uploads/2021/05/MVP3_Front_Nav_LED.png",
        "skus": ["WEST:MVP3MS86-EQP", "WEST:MVP3MS96-EQP", "WEST:MVP3MS106-EQP",
                 "WEST:MVP3SS86-EQP", "WEST:MVP3SS96-EQP", "WEST:MVP3SS106-EQP",
                 "WEST:MVP3PLY86-EQP", "WEST:MVP3PLY96-EQP"],
    },
    "western-hts": {
        "image_url": "https://westernplows.com/wp-content/uploads/2021/05/WESTRN_HTS_LED_studio_front_1270x714_72_v0r1.jpeg",
        "skus": ["WEST:HTS76-EQP"],
    },
    "western-wideout": {
        "image_url": "https://westernplows.com/wp-content/uploads/2021/05/WIDE-OUT_front_22.jpeg",
        "skus": ["WEST:WIDE810-EQP", "WEST:WIDEXL-EQP"],
    },
    "western-defender": {
        "image_url": "https://westernplows.com/wp-content/uploads/2021/03/defender-product-hero.jpg",
        "skus": ["WEST:DEF68-EQP", "WEST:DEF72-EQP"],
    },
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537"


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def sanitize(stockid: str) -> str:
    return stockid.replace(":", "-")


def process_plow(plow_id: str, info: dict, session, dry_run: bool) -> dict:
    url = info["image_url"]
    skus = info["skus"]
    print(f"\n[{plow_id}]  ({len(skus)} SKUs)")
    print(f"  source: {url}")

    # Download
    t0 = time.time()
    try:
        raw = download(url)
    except Exception as e:
        return {"plow_id": plow_id, "ok": False, "error": f"download failed: {e}"}
    print(f"  downloaded: {len(raw):,} bytes in {time.time() - t0:.1f}s")

    # Open + CMYK->RGB
    img = Image.open(BytesIO(raw))
    print(f"  source: mode={img.mode}, size={img.size}")
    if img.mode in ("CMYK", "P"):
        img = img.convert("RGB")
        print(f"  converted to RGB")
    elif img.mode == "RGBA":
        # already has alpha — flatten on white before rembg so isnet sees a
        # clean foreground instead of the existing alpha mess
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg

    # Run isnet
    t0 = time.time()
    transparent = remove(
        img, session=session,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=20,
        alpha_matting_erode_size=10,
    )
    print(f"  isnet: {time.time() - t0:.1f}s -> {transparent.size} {transparent.mode}")

    if dry_run:
        return {"plow_id": plow_id, "ok": True, "would_write": [
            str(SKUS_DIR / sanitize(s) / "hero_transparent.png") for s in skus
        ]}

    # Write to each SKU folder
    written = []
    for sku in skus:
        sku_dir = SKUS_DIR / sanitize(sku)
        sku_dir.mkdir(parents=True, exist_ok=True)
        out_path = sku_dir / "hero_transparent.png"
        transparent.save(out_path, "PNG")
        # Also stash the raw source jpg next to it so we have provenance
        src_path = sku_dir / "hero_manufacturer.jpg"
        img.save(src_path, "JPEG", quality=92)
        written.append(out_path.name)
    print(f"  wrote {len(skus)} SKU folders")

    return {"plow_id": plow_id, "ok": True, "written_to_skus": skus}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plow", help="Run for a single catalog plow id")
    p.add_argument("--dry-run", action="store_true", help="Walk + download + extract but don't write")
    args = p.parse_args(argv)

    targets = {args.plow: WESTERN_PLOWS[args.plow]} if args.plow else WESTERN_PLOWS
    if args.plow and args.plow not in WESTERN_PLOWS:
        print(f"Unknown plow: {args.plow}")
        return 2

    print(f"Processing {len(targets)} Western plow(s) -> {SKUS_DIR}")
    print("Loading rembg isnet-general-use session...")
    session = new_session("isnet-general-use")
    print("Ready.\n")

    results = [process_plow(pid, info, session, args.dry_run) for pid, info in targets.items()]

    print(f"\n=== SUMMARY ===")
    for r in results:
        if r["ok"]:
            n = len(r.get("written_to_skus") or r.get("would_write") or [])
            print(f"  OK   {r['plow_id']:<22s} -> {n} SKU folder(s)")
        else:
            print(f"  FAIL {r['plow_id']:<22s} {r.get('error')}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
