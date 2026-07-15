"""scrape_duralift_catalog.py — Scrape Dur-A-Lift's 22-product model lineup.

Dur-A-Lift makes aerial bucket trucks / lift platforms.  Their public
catalog lives at /products/{slug}/ on dur-a-lift.com — 22 product
pages, each with:
   * H1 model name
   * Open-Graph description (short marketing line)
   * Main content with "Product Overview", "Product Specifications",
     "Standard Features" sections
   * 1-3 hero images per model (other images on page are gallery thumbs)

Output:
   app/data/mysql_dumps/duralift_catalog.json   one record per model

Owner ask 2026-05-14: "This will primarily be for Dur-a-lift products.
If you want to bring in Dur-a-lift products from https://dur-a-lift.com/
that would be fine."
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
SITEMAP = "https://dur-a-lift.com/product-sitemap.xml"
DATA = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps"
OUT = DATA / "duralift_catalog.json"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def scrape_product(url: str) -> dict | None:
    html = fetch(url)

    # H1 = canonical model name
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    name = re.sub(r"<[^>]+>", "", h1_m.group(1)).strip() if h1_m else ""
    if not name:
        return None

    # Open-Graph fields
    og = {}
    for m in re.finditer(r'<meta property="og:(\w+)"[^>]*content="([^"]+)"', html):
        og[m.group(1)] = unescape(m.group(2))

    # Main content — between H1 and <footer or </main>.
    # We use the "entry-content" div if present, else fall back to <main>.
    main_m = (
        re.search(r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</main>', html, re.S)
        or re.search(r'<main[^>]*>(.*?)</main>', html, re.S)
    )
    main_text = ""
    if main_m:
        text = re.sub(r"</?(p|h[1-6]|li|ul|ol|br|div|tr|td)[^>]*>", "\n", main_m.group(1), flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        main_text = text[:6000]

    # Hero images — exclude site logos / wp icons.  Prefer images in the
    # /wp-content/uploads/ tree that ARE NOT thumbnails (no `-200x140` etc.)
    # The Open-Graph image is usually the primary; use that first.
    #
    # URL-encode any U+202F NARROW NO-BREAK SPACE (and ASCII space) in
    # the filename — dur-a-lift.com's newer "Screenshot-2024-..." uploads
    # have a U+202F between time and AM/PM, and Apache serves them
    # only with the %E2%80%AF UTF-8-encoded form (literal char or %20
    # both 404).  Discovered 2026-05-14 audit.
    def _normalize(url: str) -> str:
        return (url
                .replace(" ", "%E2%80%AF")  # narrow no-break space
                .replace(" ", "%20"))            # ASCII space
    images: list[str] = []
    if og.get("image"):
        images.append(_normalize(og["image"]))
    # Walk inline imgs and keep large uploads
    for m in re.finditer(r'src="(https?://dur-a-lift\.com/wp-content/uploads/[^"]+\.(?:jpg|jpeg|png|webp))"', html, re.I):
        url2 = _normalize(m.group(1))
        if any(skip in url2 for skip in ["logo", "icon", "favicon"]):
            continue
        if url2 in images:
            continue
        # Drop tiny thumbs (`-XXXxYYY` size suffix where XXX < 600)
        thumb_m = re.search(r"-(\d+)x(\d+)\.(?:jpg|jpeg|png|webp)", url2, re.I)
        if thumb_m and int(thumb_m.group(1)) < 600:
            continue
        images.append(url2)
        if len(images) >= 5:
            break

    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "slug": slug,
        "url": url,
        "name": name,
        "og_description": og.get("description", ""),
        "og_image": og.get("image", ""),
        "main_text": main_text,
        "images": images,
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    raw = fetch(SITEMAP)
    urls = re.findall(r"<loc>([^<]+)</loc>", raw)
    print(f"Sitemap: {len(urls)} product URLs")

    catalog = []
    for i, url in enumerate(urls, start=1):
        try:
            entry = scrape_product(url)
            if entry:
                catalog.append(entry)
                print(f"  [{i:>2}/{len(urls)}]  {entry['slug']:<35s}  {entry['name']}  ({len(entry['images'])} imgs, {len(entry['main_text'])} chars)")
            else:
                print(f"  [{i:>2}/{len(urls)}]  {url}  SKIP (no H1)")
            time.sleep(0.4)
        except Exception as e:
            print(f"  [{i:>2}/{len(urls)}]  {url}  ERROR: {e}")

    DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT}")
    print(f"Total products: {len(catalog)}")


if __name__ == "__main__":
    main()
