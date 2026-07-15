"""localize_category_images.py — download category images locally.

Ben's hard rule: no dead images on the website. PACE's Google Cloud
Storage URLs (storage.googleapis.com/aam-files/...) can change or 404
without warning, and even when they work the user pays third-party DNS
+ TLS handshake every product page load.

This script walks the entire `category` table, fetches each row's
representative image (resolved via the same tier chain the API uses),
downloads it to /static/category-images/<slug>.<ext>, and rewrites the
category's `curated_image_url` to the local /static path.

Run periodically (after PACE reingest, after category structure
changes). Idempotent — re-downloads only categories whose curated_image
points off-site or is empty.

Output: app/backend/static/category-images/<slug>.<jpg|png|webp>
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings   # noqa: E402
from app.models import Category       # noqa: E402


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("localize_images")
logging.getLogger("httpx").setLevel(logging.WARNING)


STATIC_DIR = REPO / "app" / "backend" / "static" / "category-images"
LOCAL_URL_PREFIX = "/static/category-images"


def _safe_filename(slug: str, url: str) -> str:
    """Build a safe filename: <slug>.<ext>. Falls back to .jpg if ext unknown."""
    parsed = urlparse(url)
    ext = (Path(parsed.path).suffix or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    safe = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "category"
    return f"{safe}{ext}"


async def resolve_image_for_category(db, cat_id: int) -> str | None:
    """Use the same tier chain the catalog router uses to pick an image
    for this category (curated -> stocked -> top-seller -> name-match ->
    own-direct -> descendant -> brand logo). Returns the URL or None."""
    row = (await db.execute(text("""
        WITH RECURSIVE descendants AS (
          SELECT id AS root_id, id AS desc_id FROM category WHERE id = :cid
          UNION ALL
          SELECT d.root_id, c.id FROM category c JOIN descendants d ON c.parent_id = d.desc_id
        ),
        cat_keywords AS (
          SELECT id AS cat_id, LOWER(word) AS word FROM (
            SELECT c.id, regexp_split_to_table(regexp_replace(c.name, ' and Accessories$', '', 'i'), ' ') AS word
            FROM category c WHERE c.id = :cid
          ) x
          WHERE LOWER(word) NOT IN
            ('and','or','the','of','a','an','for','with','to','accessories','replacement','part','parts','kit','kits','&')
            AND LENGTH(word) >= 4
        ),
        cat_namematch AS (
          SELECT DISTINCT ON (pc.category_id) pi.url FROM product_category pc
          JOIN product p ON p.id = pc.product_id
          JOIN product_image pi ON pi.product_id = p.id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            AND pc.category_id = :cid
            AND EXISTS (SELECT 1 FROM cat_keywords ck WHERE LOWER(p.name) LIKE '%' || ck.word || '%')
          ORDER BY pc.category_id, pi.id DESC LIMIT 1
        ),
        cat_own AS (
          SELECT pi.url FROM product_category pc
          JOIN product_image pi ON pi.product_id = pc.product_id
          WHERE pc.category_id = :cid AND pi.is_primary = true
            AND pi.url IS NOT NULL AND pi.url <> ''
          ORDER BY pi.id DESC LIMIT 1
        ),
        cat_desc AS (
          SELECT pi.url FROM descendants d
          JOIN product_category pc ON pc.category_id = d.desc_id
          JOIN product_image pi ON pi.product_id = pc.product_id
          WHERE d.root_id <> d.desc_id AND pi.is_primary = true
            AND pi.url IS NOT NULL AND pi.url <> ''
          ORDER BY pi.id DESC LIMIT 1
        )
        SELECT COALESCE(
          (SELECT curated_image_url FROM category WHERE id = :cid),
          (SELECT url FROM cat_namematch),
          (SELECT url FROM cat_own),
          (SELECT url FROM cat_desc)
        ) AS url
    """), {"cid": cat_id})).first()
    return row.url if row else None


async def download_one(client: httpx.AsyncClient, insecure_client: httpx.AsyncClient,
                       url: str, dest: Path) -> bool:
    """Fetch URL, write to dest. Falls back to an SSL-verify=False client on
    cert errors (Windows cert store sometimes lacks roots for
    curtmfg.com / dometic.com etc.). Returns True on success."""
    for c in (client, insecure_client):
        try:
            r = await c.get(url, follow_redirects=True, timeout=20.0)
            if r.status_code != 200:
                log.warning("  %s -> HTTP %s", url, r.status_code)
                return False
            if not r.content or len(r.content) < 200:
                log.warning("  %s -> only %d bytes, probably placeholder", url, len(r.content))
                return False
            dest.write_bytes(r.content)
            return True
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteError) as e:
            log.warning("  %s -> %s", url, e)
            return False
        except httpx.RequestError as e:
            # Retry insecure on cert / SSL issues
            err = str(e)
            if c is insecure_client or "ssl" not in err.lower() and "certificate" not in err.lower():
                log.warning("  %s -> %s", url, e)
                return False
            log.info("  %s -> retrying with verify=False (%s)", url, type(e).__name__)
    return False


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="Only this category slug (debug)")
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if already localized")
    args = ap.parse_args()

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        q = select(Category).where(Category.is_active.is_(True))
        if args.only:
            q = q.where(Category.slug == args.only)
        cats = (await db.execute(q.order_by(Category.full_path))).scalars().all()
        log.info("Walking %d active categories", len(cats))

        async with httpx.AsyncClient() as client, httpx.AsyncClient(verify=False) as insecure_client:
            stats = {"already_local": 0, "downloaded": 0, "no_image": 0, "failed": 0}
            for c in cats:
                current = c.curated_image_url or ""
                if current.startswith(LOCAL_URL_PREFIX) and not args.force:
                    stats["already_local"] += 1
                    continue

                url = await resolve_image_for_category(db, c.id)
                if not url:
                    stats["no_image"] += 1
                    continue
                if url.startswith(LOCAL_URL_PREFIX) and not args.force:
                    stats["already_local"] += 1
                    continue

                filename = _safe_filename(c.slug, url)
                dest = STATIC_DIR / filename
                ok = await download_one(client, insecure_client, url, dest)
                if not ok:
                    stats["failed"] += 1
                    continue
                local_url = f"{LOCAL_URL_PREFIX}/{filename}"
                await db.execute(update(Category).where(Category.id == c.id).values(curated_image_url=local_url))
                stats["downloaded"] += 1
                log.info("  [%s] %s -> %s", c.full_path, url[:80], local_url)

            await db.commit()
            log.info("Done: %s", stats)

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
