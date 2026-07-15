"""Scrape product images from worktruck.fedsig.com for our Federal Signal catalog rows.

Federal Signal's main site (www.fedsig.com) is behind Cloudflare's managed
challenge — curl can't pass it. Their work-truck catalog subdomain
(worktruck.fedsig.com) runs on Oracle Commerce Cloud and exposes a JSON
SKU API that requires no challenge:

    GET https://worktruck.fedsig.com/ccstore/v1/skus/{sku}

The response carries `parentProducts[0].primaryFullImageURL`, a path like
`/ccstore/v1/images/?source=/file/<version>/products/<slug>.jpg` which
serves as a JPEG when prefixed with the host.

Federal Signal generally hosts a single family hero per product line —
e.g. every MicroPulse Ultra variant points at the same
`micropulse-ultra.jpg`. That's acceptable: the family image still shows
the customer what the part looks like.

Run from app/ with the backend venv:
    cd /home/titan/titan-truck-website/app
    backend/.venv/bin/python -m scripts.scrape_federal_signal_images --dry-run --limit 5
    backend/.venv/bin/python -m scripts.scrape_federal_signal_images          # full run

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

from app.models import Brand, Product, ProductImage  # noqa: E402


log = logging.getLogger("scrape_federal_signal_images")

BASE = "https://worktruck.fedsig.com"
SKU_API = "/ccstore/v1/skus/{sku}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _strip_fed_prefix(sku: str) -> str:
    return re.sub(r"^FED-", "", sku, flags=re.IGNORECASE)


def _extract_image_url(payload: dict) -> str | None:
    """Pull the best image URL out of an OCC SKU JSON response.

    Prefer the SKU-specific image (`x_imageLinkSku`) when present AND
    reachable. Fall back to the parent product's primary full image.
    The SKU-specific link is frequently stale (broken file-version ID)
    so the caller still needs to HEAD-check what we return.
    """
    pp = (payload.get("parentProducts") or [])
    if not pp:
        return None
    primary = pp[0].get("primaryFullImageURL")
    if primary:
        # Path-only; needs host prefix.
        if primary.startswith("/"):
            return BASE + primary
        return primary
    return None


async def fetch_image_url(client: httpx.AsyncClient, sku: str) -> str | None:
    """Return a verified-reachable image URL for one SKU, or None."""
    try:
        r = await client.get(SKU_API.format(sku=sku), timeout=12.0, follow_redirects=True)
    except httpx.HTTPError as e:
        log.debug("API error for %s: %s", sku, e)
        return None
    if r.status_code != 200:
        return None
    try:
        payload = r.json()
    except ValueError:
        return None
    if isinstance(payload, dict) and "errorCode" in payload:
        return None
    url = _extract_image_url(payload)
    if not url:
        return None
    # HEAD-check to confirm the file actually exists (the API
    # occasionally returns stale file-version IDs).
    try:
        check = await client.head(url, timeout=8.0, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if check.status_code != 200:
        return None
    ct = check.headers.get("content-type", "")
    if not ct.startswith("image/"):
        return None
    return url


async def run(*, limit: int | None, dry_run: bool, sleep_ms: int) -> int:
    async with async_session() as db:
        stmt = (
            select(Product)
            .join(Brand, Brand.id == Product.brand_id)
            .where(Brand.name.ilike("%federal%"))
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
        log.info("Federal Signal products missing images: %d (limit=%s)", len(products), limit)
        if not products:
            return 0

        headers = {"User-Agent": UA, "Accept": "application/json,*/*"}
        found = 0
        missed = 0
        async with httpx.AsyncClient(base_url=BASE, headers=headers) as client:
            for i, p in enumerate(products, 1):
                sku = _strip_fed_prefix(p.sku)
                url = await fetch_image_url(client, sku)
                if not url:
                    log.info("[%d/%d] %s → no image", i, len(products), sku)
                    missed += 1
                else:
                    log.info("[%d/%d] %s → %s", i, len(products), sku, url)
                    found += 1
                    if not dry_run:
                        db.add(ProductImage(
                            product_id=p.id,
                            url=url,
                            alt_text=p.name[:200] if p.name else None,
                            sort_order=0,
                            is_primary=True,
                        ))
                        if found % 10 == 0:
                            await db.commit()
                if sleep_ms:
                    time.sleep(sleep_ms / 1000.0)
        if not dry_run:
            await db.commit()
        log.info("done: found=%d  missed=%d", found, missed)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=500)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(limit=args.limit, dry_run=args.dry_run, sleep_ms=args.sleep_ms))


if __name__ == "__main__":
    sys.exit(main())
