"""localize_brand_logos.py — download brand logos to local /static.

Same pattern as localize_category_images.py but scoped to brand.logo_url.
Brand logos appear on the home-page featured-brand rail, the brand list,
every brand-filtered catalog page, and every product card — they're
"visual aids that appear again and again" per Ben's hard rule that they
should live on the web server, not be hot-linked.

Walks every active brand, downloads `logo_url` to
`app/backend/static/brand-logos/<slug>.<ext>`, and rewrites the DB to
point at the local /static path.

Idempotent — already-local logos are skipped unless --force.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import Brand          # noqa: E402


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("localize_brand_logos")
logging.getLogger("httpx").setLevel(logging.WARNING)


STATIC_DIR = REPO / "app" / "backend" / "static" / "brand-logos"
LOCAL_URL_PREFIX = "/static/brand-logos"


def _safe_filename(slug: str, url: str) -> str:
    parsed = urlparse(url)
    ext = (Path(parsed.path).suffix or ".png").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"):
        ext = ".png"
    safe = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "brand"
    return f"{safe}{ext}"


async def download_one(client: httpx.AsyncClient, insecure: httpx.AsyncClient, url: str, dest: Path) -> bool:
    for c in (client, insecure):
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
        except httpx.RequestError as e:
            err = str(e)
            if c is insecure:
                log.warning("  %s -> %s", url, e)
                return False
            if "ssl" not in err.lower() and "certificate" not in err.lower():
                log.warning("  %s -> %s", url, e)
                return False
            log.info("  %s -> retrying with verify=False", url)
    return False


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        brands = (await db.execute(
            select(Brand).where(Brand.is_active.is_(True)).order_by(Brand.name)
        )).scalars().all()
        log.info("Walking %d active brands", len(brands))

        async with httpx.AsyncClient() as client, httpx.AsyncClient(verify=False) as insecure:
            stats = {"already_local": 0, "downloaded": 0, "no_logo": 0, "failed": 0}
            for b in brands:
                url = b.logo_url or ""
                if not url:
                    stats["no_logo"] += 1
                    continue
                if url.startswith(LOCAL_URL_PREFIX) and not args.force:
                    stats["already_local"] += 1
                    continue
                filename = _safe_filename(b.slug, url)
                dest = STATIC_DIR / filename
                ok = await download_one(client, insecure, url, dest)
                if not ok:
                    stats["failed"] += 1
                    continue
                local_url = f"{LOCAL_URL_PREFIX}/{filename}"
                await db.execute(update(Brand).where(Brand.id == b.id).values(logo_url=local_url))
                stats["downloaded"] += 1
                log.info("  %s: %s -> %s", b.name, url[:80], local_url)

            await db.commit()
            log.info("Done: %s", stats)

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
