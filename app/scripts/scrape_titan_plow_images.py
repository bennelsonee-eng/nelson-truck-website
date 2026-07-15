"""Scrape Titan Truck Equipment's own snow-plow catalog for moldboard imagery.

Why titantruck.com instead of the manufacturer sites:
  - Titan already curated good product photos for their site
  - Single source = consistent format
  - SnowDogg manufacturer site is Cloudflare-protected; Titan isn't
  - Licensing is implicitly fine (it's Titan's own site)
  - Each Titan `product_series` keys directly to a moldboard SKU
    (`stockid`/`dealerid`), which is exactly the keying we need long-term
    for the kit-builder

User insight (Apr 27 2026): "the pictures will line up with moldboard part
numbers — we will use these later to form kit part numbers or a different
part of the website that can piece the whole complete snowplow together."

So the storage layout is keyed by SKU, not by plow_id:
    static/snow-plows/skus/<sanitized_stockid>/hero.jpg
    static/snow-plows/skus/<sanitized_stockid>/meta.json

…where sanitized_stockid replaces ':' with '-' for filesystem safety
(e.g. MYP:09338-EQP → MYP-09338-EQP).

The catalog (snow_plow_catalog.py) will reference moldboard SKUs in a
`moldboard_skus: list[str]` field so each PlowModel can have multiple
moldboards (one per blade width).  Mapping Titan series → our catalog
plow_id is partly automatic (brand + series_title fuzzy match) and partly
manual (recorded in moldboard_catalog.py — built next).

Solr endpoint:
    GET https://www.titantruck.com/solr/ttdev/select
        ?q=*:*
        &fq=product_category:7464   (= "All Snow Plows")
        &rows=500&start=N
        &wt=json
        &fl=...

20,323 docs in cat 7464 (Apr 2026).  ~50 unique series.  Pagination of
500/page = 41 requests.  Polite 0.5s delay between requests.

Usage:
    python -m app.scripts.scrape_titan_plow_images
    python -m app.scripts.scrape_titan_plow_images --dry-run
    python -m app.scripts.scrape_titan_plow_images --brand Meyer

Output manifest:
    app/backend/static/snow-plows/skus/_manifest.json
    {
      "scraped_at": "2026-04-27T...",
      "source": "https://www.titantruck.com/solr/ttdev/select",
      "skus": [
        {
          "stockid": "MYP:09338-EQP",
          "dealerid": "09338",
          "brand": "Meyer",
          "title": "Meyer | 8' Road Pro 32 Snow Plow",
          "product_series": "90716",
          "image_path": "skus/MYP-09338-EQP/hero.jpg",
          "summary_html": "...",
          "categories": [...]
        },
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


SOLR_URL = "https://www.titantruck.com/solr/ttdev/select"
IMAGE_BASE = "https://www.titantruck.com/images"
USER_AGENT = "Mozilla/5.0 (compatible; TitanTruckSiteBot/1.0; +https://titantruck.com/contact)"

# Category 7464 = "All Snow Plows"; subcategories include Straight Blades,
# V-Plows, Winged Blades.  We pull the parent so we get them all in one shot.
SNOW_PLOW_CATEGORY = 7464

# Brands we want.  Solr will return others too (eg. SnowEx, BOSS) — we filter.
KEEP_BRANDS = {"Western", "Meyer", "Buyers Snow Dogg", "SnowDogg", "Buyers"}

OUT_ROOT = Path(__file__).resolve().parent.parent / "backend" / "static" / "snow-plows"
SKUS_DIR = OUT_ROOT / "skus"
MANIFEST = SKUS_DIR / "_manifest.json"

# Polite throttling + retry — Solr returns transient 503s ~1 in 3 calls
# under load (per the recon agent).  Generous retry handles transient spikes.
PAGE_DELAY_SEC = 0.5
RETRY_PER_REQUEST = 10
RETRY_DELAY_SEC = 2.0
MAX_BACKOFF_SEC = 15.0


def sanitize_sku(stockid: str) -> str:
    """`MYP:09338-EQP` → `MYP-09338-EQP` for filesystem safety."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", stockid)


def fetch_with_retry(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    last_err: Exception | None = None
    for i in range(RETRY_PER_REQUEST):
        try:
            r = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0, **kwargs)
            if r.status_code in (503, 502):
                # Solr shard rebalance; back off and try again
                last_err = httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                wait = min(RETRY_DELAY_SEC * (i + 1), MAX_BACKOFF_SEC)
                if i >= 3:
                    print(f"    ... 503 retry {i+1}/{RETRY_PER_REQUEST}, waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:
            last_err = e
            wait = min(RETRY_DELAY_SEC * (i + 1), MAX_BACKOFF_SEC)
            time.sleep(wait)
    raise RuntimeError(f"Gave up after {RETRY_PER_REQUEST} retries: {url} ({last_err})")


def page_solr(client: httpx.Client, start: int, rows: int = 500) -> dict:
    fields = "productid,product_series,product_series_title,stockid,dealerid,brand,title,image,summary2,category,category_tree"
    params = {
        "q": "*:*",
        "fq": f"product_category:{SNOW_PLOW_CATEGORY}",
        "rows": str(rows),
        "start": str(start),
        "wt": "json",
        "fl": fields,
        "sort": "product_series asc",  # stable order so dedupe is deterministic
    }
    r = fetch_with_retry(client, SOLR_URL, params=params)
    return r.json()


def collect_unique_series(client: httpx.Client) -> dict[str, dict]:
    """Walk all snow-plow docs, dedupe by product_series, return one rep per series."""
    by_series: dict[str, dict] = {}
    start = 0
    rows = 500
    page = 0
    while True:
        page += 1
        data = page_solr(client, start=start, rows=rows)
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            break
        n_new = 0
        for doc in docs:
            series = str(doc.get("product_series", ""))
            if series and series not in by_series:
                by_series[series] = doc
                n_new += 1
        total = data["response"]["numFound"]
        print(f"  page {page:>3}: docs {start:>5}-{start+len(docs):>5}  "
              f"({n_new} new series, {len(by_series)} total)")
        start += rows
        if start >= total:
            break
        time.sleep(PAGE_DELAY_SEC)
    return by_series


def is_keep_brand(brand: str) -> bool:
    if not brand:
        return False
    bn = brand.strip().lower()
    return any(b.lower() in bn or bn in b.lower() for b in KEEP_BRANDS)


def download_hero(client: httpx.Client, image_filename: str, dest: Path, dry_run: bool) -> tuple[bool, int]:
    """Download a Titan product image; return (ok, bytes)."""
    url = f"{IMAGE_BASE}/{image_filename}"
    if dry_run:
        return True, 0
    try:
        r = fetch_with_retry(client, url)
        dest.write_bytes(r.content)
        return True, len(r.content)
    except Exception as e:
        print(f"    image fetch failed: {e}")
        return False, 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Filter to a single brand (Western / Meyer / SnowDogg)")
    p.add_argument("--dry-run", action="store_true", help="Walk Solr, but don't download images")
    p.add_argument("--limit", type=int, help="Only download N series (testing)")
    args = p.parse_args(argv)

    SKUS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Source:    {SOLR_URL}")
    print(f"Category:  {SNOW_PLOW_CATEGORY} (All Snow Plows)")
    print(f"Output:    {SKUS_DIR}")
    print(f"Mode:      {'DRY RUN (no downloads)' if args.dry_run else 'LIVE'}")
    if args.brand:
        print(f"Brand:     {args.brand} only")
    if args.limit:
        print(f"Limit:     {args.limit} series")
    print()

    with httpx.Client(verify=True) as client:
        print("=== Step 1: walking Solr to collect unique series ===")
        by_series = collect_unique_series(client)
        print(f"\nFound {len(by_series)} unique product_series in the snow-plow category.")

        # Filter
        kept: dict[str, dict] = {}
        skipped_brand: dict[str, int] = {}
        for series, doc in by_series.items():
            brand = doc.get("brand") or ""
            if not is_keep_brand(brand):
                skipped_brand[brand] = skipped_brand.get(brand, 0) + 1
                continue
            if args.brand and args.brand.lower() not in brand.lower():
                continue
            stockid = doc.get("stockid") or ""
            if not stockid:
                continue
            kept[series] = doc

        print(f"After brand filter: keeping {len(kept)} series")
        if skipped_brand:
            print(f"Skipped brands: {dict(sorted(skipped_brand.items(), key=lambda x:-x[1]))}")

        if args.limit:
            kept = dict(list(kept.items())[: args.limit])

        # Step 2: download images
        print(f"\n=== Step 2: downloading hero images ===")
        manifest_entries: list[dict] = []
        downloaded = 0
        skipped_no_img = 0
        already_exist = 0

        for i, (series, doc) in enumerate(kept.items(), 1):
            stockid = doc["stockid"]
            sanitized = sanitize_sku(stockid)
            sku_dir = SKUS_DIR / sanitized
            hero_path = sku_dir / "hero.jpg"

            image_files = doc.get("image") or []
            if not image_files:
                print(f"  [{i:>3}/{len(kept)}] {stockid}: no image field")
                skipped_no_img += 1
                continue
            image_filename = image_files[0]

            sku_dir.mkdir(parents=True, exist_ok=True)

            if hero_path.exists() and hero_path.stat().st_size > 0:
                # Skip if we've already grabbed this one
                size = hero_path.stat().st_size
                already_exist += 1
                ok = True
            else:
                print(f"  [{i:>3}/{len(kept)}] {doc.get('brand','?'):<10s} {stockid:<22s} -> {image_filename}")
                ok, size = download_hero(client, image_filename, hero_path, args.dry_run)
                if ok and not args.dry_run:
                    downloaded += 1
                time.sleep(PAGE_DELAY_SEC)

            entry = {
                "stockid": stockid,
                "stockid_sanitized": sanitized,
                "dealerid": doc.get("dealerid") or "",
                "brand": doc.get("brand") or "",
                "title": doc.get("title") or doc.get("product_series_title") or "",
                "product_series": series,
                "product_series_title": doc.get("product_series_title") or "",
                "image_filename": image_filename,
                "image_path": f"snow-plows/skus/{sanitized}/hero.jpg",
                "image_size": size,
                "summary_html": doc.get("summary2") or "",
                "categories": doc.get("category") or [],
                "category_tree": doc.get("category_tree") or [],
            }
            manifest_entries.append(entry)

            # Per-SKU meta file too — handy for later kit-builder pulls
            if not args.dry_run:
                (sku_dir / "meta.json").write_text(json.dumps(entry, indent=2))

        # Manifest
        manifest = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "source": SOLR_URL,
            "category": SNOW_PLOW_CATEGORY,
            "n_series_in_category": len(by_series),
            "n_kept": len(kept),
            "n_downloaded_this_run": downloaded,
            "n_already_present": already_exist,
            "n_skipped_no_image": skipped_no_img,
            "skus": manifest_entries,
        }
        if not args.dry_run:
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            print(f"\nManifest written: {MANIFEST}")

        # Summary
        print(f"\n=== SUMMARY ===")
        print(f"  Series in cat 7464:    {len(by_series)}")
        print(f"  Kept (after brand):    {len(kept)}")
        print(f"  Downloaded this run:   {downloaded}")
        print(f"  Already on disk:       {already_exist}")
        print(f"  Skipped (no image):    {skipped_no_img}")

        # Per-brand breakdown
        from collections import Counter
        per_brand = Counter(e["brand"] for e in manifest_entries)
        for brand, n in per_brand.most_common():
            print(f"    {brand:<20s} {n} SKUs")

    return 0


if __name__ == "__main__":
    sys.exit(main())
