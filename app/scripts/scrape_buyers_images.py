"""Scrape product images for Buyers Products + SnowDogg/SaltDogg via Playwright.

buyersproducts.com is behind Cloudflare's interactive Turnstile challenge —
plain curl/httpx can't get past it. We use playwright-stealth + the full
Chromium build to clear the challenge once, then call their search
autocomplete API for each SKU:

    GET /api/v2/search/autocomplete/{pn}/abandoncart/30

The response carries `products[0].image` which is a URL like:
    https://pimimages.buyersproducts.com/products/SM/<PN>.jpg

We swap "/SM/" → "/LG/" for the full-resolution variant when available
and HEAD-check before persisting. Products whose API result points at
"SM_NotFound.jpg" are skipped (Buyers' own catalog admits no image
exists yet).

Run from app/ with the backend venv:
    cd /home/titan/titan-truck-website/app
    backend/.venv/bin/python -m scripts.scrape_buyers_images --dry-run --limit 5
    backend/.venv/bin/python -m scripts.scrape_buyers_images        # full

Owner ask 2026-05-18.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx  # noqa: E402
from sqlalchemy import select, or_  # noqa: E402

from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import Brand, Product, ProductImage  # noqa: E402


log = logging.getLogger("scrape_buyers_images")

BASE = "https://www.buyersproducts.com"
PN_RE = re.compile(r"^(?:BUY|SNOW|BUSH)-", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"SM_NotFound\.jpg$", re.IGNORECASE)


def _strip_prefix(sku: str) -> str:
    return PN_RE.sub("", sku)


def _to_large(url: str) -> str:
    """Swap /products/SM/ → /products/LG/ for full-resolution."""
    return re.sub(r"/products/SM/", "/products/LG/", url, count=1)


async def run(*, limit: int | None, dry_run: bool, sleep_ms: int) -> int:
    # Sync Playwright lives in its own thread because the rest of the
    # backend is asyncio. We run the DB work + the scrape interleaved
    # via threadpool calls so we don't import asyncio Playwright.
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    async with async_session() as db:
        stmt = (
            select(Product)
            .join(Brand, Brand.id == Product.brand_id)
            .where(
                or_(
                    Brand.name.ilike("%buyers%products%"),
                    Brand.name.ilike("%snowdogg%"),
                    Brand.name.ilike("%saltdogg%"),
                )
            )
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
        log.info("Buyers/SnowDogg products missing images: %d (limit=%s)", len(products), limit)
        if not products:
            return 0

        loop = asyncio.get_event_loop()

        # Scrape in batches, committing incrementally so a CF rate-limit
        # mid-run doesn't lose all the prior work. The previous "scrape
        # everything in one thread then commit once" pattern wedged at
        # SKU 120/241 and we lost the in-memory results when we killed
        # the wedged Playwright session.
        BATCH = 25
        product_map = {p.id: p for p in products}
        found = 0
        missed = 0
        for batch_start in range(0, len(products), BATCH):
            batch = products[batch_start : batch_start + BATCH]

            def scrape_batch(_batch=batch, _start=batch_start) -> list[tuple[int, str | None]]:
                out: list[tuple[int, str | None]] = []
                stealth = Stealth()
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        channel="chromium",
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    ctx = browser.new_context(
                        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        viewport={"width": 1920, "height": 1080},
                        locale="en-US",
                    )
                    stealth.apply_stealth_sync(ctx)
                    page = ctx.new_page()
                    page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(4000)
                    if "Just a moment" in page.title():
                        log.warning("CF still challenging — aborting batch")
                        browser.close()
                        return out

                    with httpx.Client(timeout=10) as http:
                        for j, prod in enumerate(_batch, 1):
                            i = _start + j
                            pn = _strip_prefix(prod.sku)
                            try:
                                with page.expect_response(
                                    lambda r, _pn=pn: f"/api/v2/search/autocomplete/{_pn}/" in r.url
                                                      and r.status == 200,
                                    timeout=15000,
                                ) as resp_info:
                                    page.goto(
                                        f"{BASE}/search?criteria={pn}",
                                        wait_until="domcontentloaded",
                                        timeout=30000,
                                    )
                                data = resp_info.value.json()
                            except Exception as e:
                                log.info("[%d/%d] %s → autocomplete error (%s)",
                                         i, len(products), pn, type(e).__name__)
                                out.append((prod.id, None))
                                continue
                            items = (data or {}).get("products") or []
                            url: str | None = None
                            for it in items:
                                raw = (it or {}).get("image") or ""
                                if not raw or PLACEHOLDER_RE.search(raw):
                                    continue
                                if raw.startswith("//"):
                                    raw = "https:" + raw
                                elif raw.startswith("/"):
                                    raw = BASE + raw
                                lg = _to_large(raw)
                                try:
                                    r = http.head(lg, follow_redirects=True)
                                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                                        url = lg
                                        break
                                    r2 = http.head(raw, follow_redirects=True)
                                    if r2.status_code == 200 and r2.headers.get("content-type", "").startswith("image/"):
                                        url = raw
                                        break
                                except httpx.HTTPError:
                                    continue
                            if url:
                                log.info("[%d/%d] %s → %s", i, len(products), pn, url)
                            else:
                                log.info("[%d/%d] %s → no image", i, len(products), pn)
                            out.append((prod.id, url))
                            if sleep_ms:
                                time.sleep(sleep_ms / 1000.0)
                    browser.close()
                return out

            results = await loop.run_in_executor(None, scrape_batch)
            for pid, url in results:
                if not url:
                    missed += 1
                    continue
                found += 1
                if not dry_run:
                    prod = product_map.get(pid)
                    db.add(ProductImage(
                        product_id=pid,
                        url=url,
                        alt_text=(prod.name[:200] if prod and prod.name else None),
                        sort_order=0,
                        is_primary=True,
                    ))
            if not dry_run:
                await db.commit()
                log.info("--- committed batch ending at %d (found so far: %d) ---",
                         batch_start + len(batch), found)
        log.info("done: found=%d  missed=%d", found, missed)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=400,
                        help="Delay between SKU requests (browser session is shared)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(limit=args.limit, dry_run=args.dry_run, sleep_ms=args.sleep_ms))


if __name__ == "__main__":
    sys.exit(main())
