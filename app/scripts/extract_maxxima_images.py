"""extract_maxxima_images.py — Add primary image URLs to the Maxxima catalog.

Re-scans the cached Maxxima category-page HTML (saved by
scrape_maxxima_catalog.py) and pulls the first `"pic":"images/...jpg"`
that appears near each SKU.  Maxxima uses image paths like:

    images/m63201ywcl_lit.jpg
    images/m20488ywcl_l.jpg
    images/mwl-54r_straight_lit_jpg.jpg

All relative to https://maxxima.com/.

Updates app/data/mysql_dumps/maxxima_catalog.json in-place.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


PAGES_DIR = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps" / "maxxima_pages"
CATALOG = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps" / "maxxima_catalog.json"
BASE_URL = "https://maxxima.com/"


def extract_images_from_page(html: str) -> dict[str, str]:
    """sku.upper() → primary image absolute URL.

    For each SKU, find the FIRST `"pic":"..."` that appears within ~5000
    chars after the SKU mention.  That's the thumbnail used on the
    category card and the first detail-page image.
    """
    out: dict[str, str] = {}
    for m in re.finditer(r'"sku":"([^"]+)"', html):
        sku = m.group(1).upper()
        if sku in out:
            continue
        chunk = html[m.end(): m.end() + 5000]
        pic = re.search(r'"pic":"([^"]+\.(?:jpg|jpeg|png|webp))"', chunk, re.I)
        if pic:
            url = pic.group(1)
            if url.startswith("http"):
                out[sku] = url
            else:
                out[sku] = BASE_URL + url.lstrip("/")
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    if not CATALOG.exists():
        print(f"missing {CATALOG} — run scrape_maxxima_catalog.py first")
        return

    pages = sorted(PAGES_DIR.glob("*.html"))
    print(f"Pages cached: {len(pages)}")
    all_images: dict[str, str] = {}
    for p in pages:
        html = p.read_text(encoding="utf-8", errors="replace")
        new_imgs = extract_images_from_page(html)
        all_images.update(new_imgs)
    print(f"Extracted images for {len(all_images)} SKUs")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    n_added = 0
    for p in catalog:
        sku = (p.get("sku") or "").upper()
        if sku in all_images and not p.get("image_url"):
            p["image_url"] = all_images[sku]
            n_added += 1
    CATALOG.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"Catalog updated: {n_added} image URLs added")


if __name__ == "__main__":
    main()
