"""Scrape product images from eccoesg.com for our ECCO catalog rows.

ECCO hosts its product images on Contentful (images.ctfassets.net). The
flow per part number:

  1. GET /us/en/SearchResults?searchText={part_number}
  2. Parse out the first RedirectToProduct link
  3. GET that redirect → product detail page
  4. Extract the og:image meta (full-res) — filename matches the
     part number (e.g. EW2403.png on the EW2403 detail page)
  5. Persist the Contentful URL as a ProductImage row

We don't re-host the images — ECCO has every incentive to keep these
Contentful URLs stable (the rest of their marketing site depends on
them) and the rest of the catalog (Husky etc.) already references
external CDNs (storage.googleapis.com/aam-files) directly.

Run from app/ with the backend venv:
    cd /home/titan/titan-truck-website/app
    backend/.venv/bin/python -m scripts.scrape_ecco_images --dry-run
    backend/.venv/bin/python -m scripts.scrape_ecco_images --limit 10
    backend/.venv/bin/python -m scripts.scrape_ecco_images        # full run

Owner ask 2026-05-17.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import Product, ProductImage  # noqa: E402


log = logging.getLogger("scrape_ecco_images")

BASE = "https://www.eccoesg.com"
SEARCH_PATH = "/us/en/SearchResults"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# Match a /redirect/RedirectToProduct/<id>/<pn> href on the search-results
# page. Captures the trailing part-number segment so we can pick the EXACT
# match instead of the first link (ECCO's search returns related products
# too, e.g. "3435A" search yields 3410CB as the first hit).
# We skip RedirectToSeries — that's a higher-level family page, not the
# specific PN.
PRODUCT_HREF_RE = re.compile(
    r'href="(redirect/RedirectToProduct/[^"]+/([^"/]+))"',
    re.IGNORECASE,
)

# og:image meta on the PDP — Contentful URL, may be protocol-relative
# (`//images.ctfassets.net/...`). The filename mirrors the SKU.
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Fallback: the first ctfassets image in the body.
CTFASSETS_IMG_RE = re.compile(
    r'(https?:)?//images\.ctfassets\.net/[^\s"\'?]+\.(?:png|jpg|jpeg|webp)',
    re.IGNORECASE,
)


def _strip_ecco_prefix(sku: str) -> str:
    return re.sub(r"^ECCO-", "", sku, flags=re.IGNORECASE)


def _absolutize(url: str) -> str:
    """Resolve protocol-relative URLs (`//images.ctfassets.net/...`) to https."""
    if url.startswith("//"):
        return "https:" + url
    return url


async def fetch_product_image(client: httpx.AsyncClient, ecco_pn: str) -> str | None:
    """Return the og:image URL for an ECCO part number, or None."""
    # 1. Search
    r = await client.get(
        f"{BASE}{SEARCH_PATH}", params={"searchText": ecco_pn},
        timeout=15.0, follow_redirects=True,
    )
    if r.status_code != 200:
        log.debug("search %s → HTTP %s", ecco_pn, r.status_code)
        return None
    # Collect every RedirectToProduct + its trailing PN. Prefer the entry
    # whose PN matches ours case-insensitively; fall back to the first
    # entry only if no exact match exists.
    matches = PRODUCT_HREF_RE.findall(r.text)
    if not matches:
        log.debug("search %s → no RedirectToProduct match", ecco_pn)
        return None
    exact = next((href for (href, pn) in matches if pn.lower() == ecco_pn.lower()), None)
    if exact is None:
        # No exact PN match. ECCO sometimes maps composite PNs (e.g. our
        # "3410-35" = "Safety Director 35' cable kit") to a single base
        # product. Skip rather than risk landing on a sibling.
        log.debug("search %s → no exact PN match in %d candidates: %s",
                  ecco_pn, len(matches), [m[1] for m in matches[:5]])
        return None
    redirect_href = exact
    # Search page is /us/en/SearchResults; the redirect href is relative
    # to that path's directory.
    detail_url = urljoin(f"{BASE}/us/en/", redirect_href)

    # 2. Detail page
    r2 = await client.get(detail_url, timeout=15.0, follow_redirects=True)
    if r2.status_code != 200:
        log.debug("detail %s → HTTP %s", ecco_pn, r2.status_code)
        return None
    body = r2.text

    # 3. og:image meta first
    og = OG_IMAGE_RE.search(body)
    if og:
        return _absolutize(og.group(1))

    # 4. Fallback — first ctfassets image
    fb = CTFASSETS_IMG_RE.search(body)
    if fb:
        return _absolutize(fb.group(0))

    return None


async def run(*, limit: int | None, dry_run: bool, sleep_ms: int) -> int:
    async with async_session() as db:
        stmt = (
            select(Product)
            .where(Product.prod_code == "ECCO")
            .where(Product.is_for_sale.is_(True))
            .where(Product.is_hidden.is_(False))
            .where(
                ~select(ProductImage.id)
                .where(ProductImage.product_id == Product.id)
                .exists()
            )
            .order_by(Product.id)
        )
        if limit:
            stmt = stmt.limit(limit)
        products = (await db.execute(stmt)).scalars().all()
        log.info("ECCO products missing images: %d (limit=%s)", len(products), limit)

        if not products:
            return 0

        headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
        found = 0
        missed = 0
        async with httpx.AsyncClient(headers=headers) as client:
            for i, p in enumerate(products, 1):
                pn = _strip_ecco_prefix(p.sku)
                try:
                    url = await fetch_product_image(client, pn)
                except Exception as e:
                    log.warning("[%d/%d] %s → error: %s", i, len(products), pn, e)
                    missed += 1
                    continue
                if not url:
                    log.info("[%d/%d] %s → no image found", i, len(products), pn)
                    missed += 1
                    continue
                log.info("[%d/%d] %s → %s", i, len(products), pn, url)
                found += 1
                if not dry_run:
                    db.add(ProductImage(
                        product_id=p.id,
                        url=url,
                        alt_text=p.name[:200] if p.name else None,
                        sort_order=0,
                        is_primary=True,
                    ))
                # Be polite — flush every 10
                if found % 10 == 0 and not dry_run:
                    await db.commit()
                # Rate limit
                if sleep_ms:
                    time.sleep(sleep_ms / 1000.0)

        if not dry_run:
            await db.commit()
        log.info("done: found=%d  missed=%d", found, missed)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of products to process this run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write ProductImage rows; just report")
    parser.add_argument("--sleep-ms", type=int, default=600,
                        help="Delay between requests (default 600ms)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(limit=args.limit, dry_run=args.dry_run, sleep_ms=args.sleep_ms))


if __name__ == "__main__":
    sys.exit(main())
