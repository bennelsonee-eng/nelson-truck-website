"""scrape_duralift_landings.py — Pull all Dur-A-Lift category landing pages
                                  + page-2 pagination + intro copy.

dur-a-lift.com organizes their product catalog into 4 sub-categories
plus the master "All Products" page:

   /products/category/products/        master "All Products" page (paginated)
   /products/articulated-aerial-lifts/   articulated lifts category
   /products/category/telescopic-bucket-trucks/
   /products/category/telescopic-bucket-van/
   /products/category/tracked-lifts/

Each landing page has:
   * A section header + intro paragraph (1-2KB of marketing copy)
   * A breadcrumb
   * A grid of product cards (image + title link + short paragraph + Read More)
   * Pagination at bottom

This scraper pulls all of those and saves:
   * landing copy per category (for the Titan category description field)
   * sub-category → product slugs mapping (so each product can carry its
     sub-category for sidebar drill-down on the Titan site)
   * any additional hero/marketing images we don't already have

Output:
   app/data/mysql_dumps/duralift_landings.json
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
DATA = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps"
OUT_JSON = DATA / "duralift_landings.json"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


LANDING_URLS = [
    ("all_products",       "https://dur-a-lift.com/products/category/products/"),
    ("articulated",        "https://dur-a-lift.com/products/articulated-aerial-lifts/"),
    ("telescopic_trucks",  "https://dur-a-lift.com/products/category/telescopic-bucket-trucks/"),
    ("telescopic_van",     "https://dur-a-lift.com/products/category/telescopic-bucket-van/"),
    ("tracked",            "https://dur-a-lift.com/products/category/tracked-lifts/"),
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def normalize_url(url: str) -> str:
    """Apply the U+202F space fix we discovered for some Screenshot- filenames."""
    return url.replace(" ", "%E2%80%AF").replace(" ", "%20")


def extract_intro(html: str) -> tuple[str, str, str]:
    """Pull title, lead paragraph, and any hero/marketing intro copy."""
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""

    # The intro block is everything between the H1 and the breadcrumb section.
    intro_m = re.search(
        r'<h1[^>]*>.*?</h1>(.*?)<section class="section section--breadcrumbs',
        html, re.S,
    )
    intro_html = ""
    intro_text = ""
    if intro_m:
        intro_html = intro_m.group(1)
        # Strip inline styles + scripts + image tags, keep paragraph text
        cleaned = re.sub(r"<script[^>]*>.*?</script>", "", intro_html, flags=re.S)
        cleaned = re.sub(r"<style[^>]*>.*?</style>", "", cleaned, flags=re.S)
        cleaned = re.sub(r"<img[^>]*>", "", cleaned)
        text = re.sub(r"</?(p|div|h[1-6]|li|ul|br|em|strong)[^>]*>", "\n", cleaned, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        intro_text = text[:5000]

    return title, intro_text, intro_html


def extract_product_cards(html: str) -> list[dict]:
    """Find every product card on the page.

    Card structure (per the audit):
      <div class="product-card panel ...">
        <div class="product-card__img ..."><img ...></div>
        <h3 class="product-card__title ..."><a href="...">{name}</a></h3>
        <div class="product-card__content"><p>{copy}</p>
          <a href="..." class="arrow-link ...">Read More</a>
        </div>
      </div>
    """
    cards: list[dict] = []
    for m in re.finditer(
        r'<div class="product-card[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        html, re.S,
    ):
        block = m.group(1)
        # Hero image
        img_m = re.search(r'<img[^>]+src="([^"]+)"', block)
        hero_img = normalize_url(img_m.group(1)) if img_m else ""
        # Bigger image from srcset (prefer 1024w if available)
        srcset_m = re.search(r'srcset="([^"]+)"', block)
        if srcset_m:
            for entry in srcset_m.group(1).split(","):
                entry = entry.strip()
                if " 1024w" in entry:
                    hero_img = normalize_url(entry.replace(" 1024w", "").strip())
                    break
                if " 1200w" in entry or " 1500w" in entry:
                    hero_img = normalize_url(entry.split(" ")[0])
                    break
        # Title + link
        title_m = re.search(r'<h3[^>]*>\s*<a href="([^"]+)"[^>]*>([^<]+)</a>', block, re.S)
        if not title_m:
            continue
        product_url = title_m.group(1)
        product_name = title_m.group(2).strip()
        # Body paragraph
        p_m = re.search(r'<div class="product-card__content[^"]*">.*?<p[^>]*>(.*?)</p>', block, re.S)
        copy = ""
        if p_m:
            copy = re.sub(r"<[^>]+>", "", p_m.group(1))
            copy = unescape(copy).strip()
            copy = re.sub(r"\s+", " ", copy)

        slug = product_url.rstrip("/").rsplit("/", 1)[-1]
        cards.append({
            "slug": slug,
            "url": product_url,
            "name": product_name,
            "card_copy": copy,
            "hero_image": hero_img,
        })
    return cards


def scrape_landing(key: str, url: str) -> dict:
    print(f"  fetching {key}: {url}")
    html = fetch(url)
    title, intro_text, intro_html = extract_intro(html)
    cards = extract_product_cards(html)

    # Pagination — look for page/2 link
    page2_url = ""
    page2_m = re.search(r'href="(' + re.escape(url) + r'page/2/?)"', html)
    if page2_m:
        page2_url = page2_m.group(1)
    else:
        # Generic match for the same /page/2/ anchor
        gen = re.search(r'href="(https?://dur-a-lift\.com/products/category/[^"]+page/2/?)"', html)
        if gen:
            page2_url = gen.group(1)

    page2_cards = []
    if page2_url:
        try:
            print(f"    fetching page 2: {page2_url}")
            html2 = fetch(page2_url)
            page2_cards = extract_product_cards(html2)
        except Exception as e:
            print(f"    page 2 failed: {e}")

    return {
        "key": key,
        "url": url,
        "title": title,
        "intro_text": intro_text,
        "products": cards + page2_cards,
        "page2_url": page2_url or None,
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    DATA.mkdir(parents=True, exist_ok=True)
    print(f"Scraping {len(LANDING_URLS)} Dur-A-Lift landing pages…")
    landings = {}
    for key, url in LANDING_URLS:
        try:
            landings[key] = scrape_landing(key, url)
            print(f"    title={landings[key]['title']!r}  "
                  f"intro={len(landings[key]['intro_text'])}ch  "
                  f"products={len(landings[key]['products'])}")
            time.sleep(0.4)
        except Exception as e:
            print(f"    ERROR: {e}")

    # Aggregate unique product slugs across all landings, with which
    # sub-cat(s) each appears under.
    by_slug: dict[str, dict] = {}
    for lkey, ldata in landings.items():
        for p in ldata.get("products", []):
            slug = p["slug"]
            if slug not in by_slug:
                by_slug[slug] = {
                    **p,
                    "appears_in": [lkey],
                }
            else:
                by_slug[slug]["appears_in"].append(lkey)

    OUT_JSON.write_text(json.dumps({
        "landings": landings,
        "products_by_slug": by_slug,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}")
    print(f"  {len(landings)} landings, {len(by_slug)} unique products")


if __name__ == "__main__":
    main()
