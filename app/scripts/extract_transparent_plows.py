"""Convert plow hero images to transparent-background PNGs for the configurator.

Strategy: simple white-pixel removal via PIL.  Works great for clean studio
shots (most Western SKUs) where the plow sits on a flat white background.
For images that already have a truck or scenery in the background (the
SnowDogg/Meyer "lifestyle" shots), the result will be muddy — those need
rembg-style ML segmentation later.

Heuristic: if the corner regions are mostly white, run the removal.
Otherwise, skip and flag for manual / ML processing.

Output:  static/snow-plows/skus/<sku>/hero_transparent.png   (if processed)

Usage:
    python -m app.scripts.extract_transparent_plows
    python -m app.scripts.extract_transparent_plows --sku WEST-PPMS86-EQP
    python -m app.scripts.extract_transparent_plows --force   # re-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image


SKUS_DIR = Path(__file__).resolve().parent.parent / "backend" / "static" / "snow-plows" / "skus"

# White-detection tolerance — anything within (255-T, 255-T, 255-T) to (255,255,255)
# becomes transparent.  Higher = more aggressive removal.
WHITE_TOLERANCE = 18

# Edge feathering — pixels close to the threshold get partial transparency.
# Helps anti-aliased edges blend rather than fringing.
FEATHER_BAND = 12

# How "white" must the corners be, on average, for us to consider this a clean
# studio shot vs a lifestyle shot we shouldn't auto-remove.
CORNER_WHITE_THRESHOLD = 240
CORNER_PROBE_FRACTION = 0.08   # 8% of width/height


def is_studio_shot(img: Image.Image) -> tuple[bool, float]:
    """Check if all four corners are predominantly white.  Returns (yes, score)."""
    w, h = img.size
    px = img.convert("RGB").load()
    cw = max(1, int(w * CORNER_PROBE_FRACTION))
    ch = max(1, int(h * CORNER_PROBE_FRACTION))

    samples = []
    for x_start, y_start in [(0, 0), (w - cw, 0), (0, h - ch), (w - cw, h - ch)]:
        for x in range(x_start, x_start + cw):
            for y in range(y_start, y_start + ch):
                r, g, b = px[x, y]
                samples.append((r + g + b) / 3.0)
    avg = sum(samples) / len(samples)
    return (avg >= CORNER_WHITE_THRESHOLD), avg


def remove_white_bg(img: Image.Image) -> Image.Image:
    """Replace near-white pixels with full transparency, with a feathered edge."""
    img = img.convert("RGBA")
    w, h = img.size
    pixels = img.load()
    threshold_solid = 255 - WHITE_TOLERANCE
    threshold_feather = threshold_solid - FEATHER_BAND
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            min_chan = min(r, g, b)
            if min_chan >= threshold_solid:
                # Fully white → fully transparent
                pixels[x, y] = (r, g, b, 0)
            elif min_chan >= threshold_feather:
                # Edge band → partial transparency proportional to whiteness
                t = (min_chan - threshold_feather) / FEATHER_BAND
                pixels[x, y] = (r, g, b, int(a * (1 - t)))
            # else: leave as-is (real plow pixel)
    return img


def process_one(sku_dir: Path, force: bool = False) -> dict:
    hero = sku_dir / "hero.jpg"
    out = sku_dir / "hero_transparent.png"
    if not hero.exists():
        return {"sku": sku_dir.name, "status": "no-hero"}
    if out.exists() and not force:
        return {"sku": sku_dir.name, "status": "already-done"}

    try:
        img = Image.open(hero)
    except Exception as e:
        return {"sku": sku_dir.name, "status": "read-error", "error": str(e)}

    is_studio, corner_avg = is_studio_shot(img)
    if not is_studio:
        return {
            "sku": sku_dir.name,
            "status": "skipped-lifestyle-shot",
            "corner_avg": corner_avg,
        }

    transparent = remove_white_bg(img)
    transparent.save(out, "PNG")
    return {
        "sku": sku_dir.name,
        "status": "extracted",
        "corner_avg": corner_avg,
        "size_in": hero.stat().st_size,
        "size_out": out.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sku", help="Process a single SKU directory (e.g. WEST-PPMS86-EQP)")
    p.add_argument("--force", action="store_true", help="Re-run even if hero_transparent.png exists")
    args = p.parse_args(argv)

    if not SKUS_DIR.exists():
        print(f"No skus dir: {SKUS_DIR}")
        return 2

    if args.sku:
        targets = [SKUS_DIR / args.sku]
    else:
        targets = [d for d in SKUS_DIR.iterdir() if d.is_dir()]

    print(f"Processing {len(targets)} SKU dir(s)...")
    print()

    by_status: dict[str, list[dict]] = {}
    for d in sorted(targets):
        result = process_one(d, force=args.force)
        by_status.setdefault(result["status"], []).append(result)
        if result["status"] == "extracted":
            print(f"  EXTRACTED  {result['sku']:<24s}  corner={result['corner_avg']:.0f}  "
                  f"{result['size_in']:>6} -> {result['size_out']:>6} bytes")
        elif result["status"] == "skipped-lifestyle-shot":
            print(f"  SKIP-LIFE  {result['sku']:<24s}  corner={result['corner_avg']:.0f}  (not studio shot)")
        elif result["status"] == "already-done":
            print(f"  EXISTS     {result['sku']:<24s}")

    print(f"\n=== SUMMARY ===")
    for status, items in sorted(by_status.items()):
        print(f"  {status:<28s} {len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
