"""scrape_maxxima_catalog.py — Scrape Maxxima's full product catalog.

Maxxima's category pages embed every product's full data in an inline JSON
blob (the React app rehydrates from it).  We can extract:

   sku                         e.g. "M63201YWCL"
   description (HTML)          long marketing copy + features + benefits
   key (CDN asset id)
   category (page name)

Output:
   app/data/mysql_dumps/maxxima_catalog.json  (full extracted catalog)
   app/data/reports/maxxima_full_catalog.xlsx (rolled up for human review)

Method:
   1. Fetch sitemap.xml → 39 category URLs.
   2. For each category page, fetch HTML, extract the embedded JSON object
      (search for the product-list array around a known structure).
   3. Dedupe by SKU; capture category(ies) each SKU appears under.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
import ssl
from html import unescape
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
SITEMAP = "https://maxxima.com/sitemap.xml"

DATA = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps"
OUT_JSON = DATA / "maxxima_catalog.json"
OUT_HTML_DIR = DATA / "maxxima_pages"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,*/*",
    })
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def category_urls() -> list[str]:
    raw = fetch(SITEMAP)
    urls = re.findall(r"<loc>([^<]+)</loc>", raw)
    return [u for u in urls if "/category/" in u]


def extract_products(html: str, category_url: str) -> list[dict]:
    """Find every product record in the inline JSON blob.

    We look for the structure:  {"key": "...", "sku": "...", ..., "description": "..."}
    Each product record is a JSON object literal inside the page.  We use a
    regex to find all `{"key":..."sku":..."description":...}` blocks and JSON-
    parse them.  We accept partial captures and fix up trailing commas as
    needed.
    """
    products: list[dict] = []
    # Match each {"key":"...","sku":"...",..., "description":"..."} object.
    # The regex is greedy across keys but not across braces, and we cap the
    # capture at ~8KB so it doesn't run away on a malformed page.
    # We rely on the fact that the JSON objects don't nest braces inside
    # string keys we care about (children/inventory are siblings we capture).
    pat = re.compile(
        r'\{"key":"([0-9A-F]{32})"[^{}]{0,40}?,"sku":"([^"]{2,60})"'
        r'(?:[^{}]|"children":\[[^\]]*\]|"inventory":\{[^{}]*\}|"addOns":\[[^\]]*\]){0,8000}?'
        r',"description":"([^"]*)"',
        re.S,
    )
    for m in pat.finditer(html):
        key, sku, desc_html_escaped = m.group(1), m.group(2), m.group(3)
        # The description is HTML-encoded as JSON-string contents (so the
        # JSON-string-escape is already de-escaped by the regex; just unescape
        # the HTML entities inside).
        desc_html = (
            desc_html_escaped
            .replace("\\/", "/")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\u0026", "&")
        )
        desc_text = unescape(re.sub(r"<[^>]+>", " ", desc_html))
        desc_text = re.sub(r"\s+", " ", desc_text).strip()
        # Drop massive ones (>3K chars often = a different field caught accidentally)
        if len(desc_text) > 5000:
            desc_text = desc_text[:5000] + "..."
        products.append({
            "sku": sku,
            "key": key,
            "description_html": desc_html,
            "description_text": desc_text,
            "category_url": category_url,
        })
    return products


def main() -> None:
    print("Fetching Maxxima sitemap…")
    cats = category_urls()
    print(f"  {len(cats)} category URLs")

    OUT_HTML_DIR.mkdir(parents=True, exist_ok=True)

    all_products: dict[str, dict] = {}
    cat_count: dict[str, list[str]] = {}

    for i, cat in enumerate(cats, start=1):
        try:
            slug = cat.rstrip("/").rsplit("/", 1)[-1] or "root"
            cache_path = OUT_HTML_DIR / f"{slug}.html"
            if cache_path.exists() and cache_path.stat().st_size > 50_000:
                html = cache_path.read_text(encoding="utf-8", errors="replace")
            else:
                html = fetch(cat)
                cache_path.write_text(html, encoding="utf-8")
                time.sleep(0.4)  # polite
            prods = extract_products(html, cat)
            for p in prods:
                sku = p["sku"]
                if sku not in all_products:
                    all_products[sku] = p
                    cat_count[sku] = [slug]
                else:
                    cat_count[sku].append(slug)
            print(f"  [{i:>2}/{len(cats)}]  {slug:<55s} found {len(prods):>4d} products  (catalog: {len(all_products)})")
        except Exception as e:
            print(f"  [{i:>2}/{len(cats)}]  {cat}  ERROR: {e}")

    # Attach category list to each product
    for sku, cats_list in cat_count.items():
        all_products[sku]["categories"] = sorted(set(cats_list))

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(list(all_products.values()), indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}")
    print(f"Total unique products: {len(all_products)}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    main()
