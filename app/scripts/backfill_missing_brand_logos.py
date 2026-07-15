"""backfill_missing_brand_logos.py — fill in logos for brands the
auto-localizer couldn't catch (because logo_url was NULL to start).

Strategy: a small hand-curated list mapping brand_name → known-good
public URL.  Most of these came from ariesautomotive.com /
ariesindustries.com which hosts logos for its 4 sub-brands (Aries
Offroad, CURT, Luverne, UWS) at predictable paths.  Lippert's logo is
also hosted there as a "site-wide" partner brand.

Run after seeding brand rows.  Idempotent — skips any brand that
already has a logo_url AND any brand whose target file is already
present in static/brand-logos/.

WeatherGuard is intentionally NOT in this list — its parent site
(weatherguard.com / werner.com) is behind a Cloudflare client challenge
that prevents direct download.  See OPERATIONS_NOTES for follow-up.
"""
from __future__ import annotations

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
log = logging.getLogger("backfill_missing_brand_logos")
logging.getLogger("httpx").setLevel(logging.WARNING)

STATIC_DIR = REPO / "app" / "backend" / "static" / "brand-logos"
LOCAL_URL_PREFIX = "/static/brand-logos"

# Map: exact brand.name → URL.  The `new/logo-*.png` paths on ariesautomotive
# are the "off" state of a hover toggle and render WHITE (invisible on a
# white background).  The `logo-*-on.png` versions are the colored/visible
# variants — use those.
CURATED: dict[str, str] = {
    "Aries Offroad":      "https://www.ariesautomotive.com/media/images/top-nav-logos/logo-aries-on.png",
    "Luverne":            "https://www.ariesautomotive.com/media/images/top-nav-logos/logo-luverne-on.png",
    "UWS":                "https://www.ariesautomotive.com/media/images/top-nav-logos/logo-uws-on.png",
    "Lippert Components": "https://www.ariesautomotive.com/media/images/sitewide/lippert-logo.png",
    "Yakima Products":    "https://yakimaassets.s3-us-west-2.amazonaws.com/images/Yakima_Logo_TagLine_Red.png",
    # Second pass — scraped each brand's homepage for the header-img src.
    # Three Shopify CDNs returned protocol-relative URLs (//domain/...);
    # we rewrite them as https://domain/... below.
    "Trimax":             "https://trimaxlocks.com/wp-content/uploads/2020/07/trimax-logo.png",
    "VHT":                "https://www.vhtpaint.com/wp-content/uploads/2024/06/logo_vht.png",
    "Ranch Hand":         "https://www.ranchhand.com/static/frontend/Ranchhand/ranchhand/en_US/images/logo/default/ranchhand-logo-small-new.png",
    "CARR":               "https://www.carr.com/wp-content/uploads/2022/03/logo-2022.png",
    "Superwinch":         "https://www.superwinch.com/cdn/shop/files/Superwinch_Logo_70cde96f-277d-4561-acea-0d493bf677c5.png",
    "VIAIR":              "https://viaircorp.com/cdn/shop/files/Logo.svg",
    # Third pass — broader image scrape (no 'logo' substring requirement)
    "PIAA":               "https://www.piaa.com/shared/images/PIAA-Valeo-Web-Orginal.png",
    "OVERLAND VEHICLE SYSTEMS": "https://cdn11.bigcommerce.com/s-707pax8i4u/images/stencil/240x140/download_1707305646__95827.original.png",
}


def _safe_filename(slug: str, url: str) -> str:
    parsed = urlparse(url)
    ext = (Path(parsed.path).suffix or ".png").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"):
        ext = ".png"
    safe = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "brand"
    return f"{safe}{ext}"


async def main() -> int:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # httpx.AsyncClient hits ConnectionRefused on Windows for some hosts
    # we can reach with the sync client; just use the sync client and run
    # it in a default executor so we keep the async-DB layer happy.
    sync_client = httpx.Client(
        verify=False, timeout=15.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 Chrome/120"},
    )
    async with Session() as db:
        stats = {"updated": 0, "skipped_have_logo": 0, "skipped_no_brand": 0, "failed": 0}
        for brand_name, url in CURATED.items():
            row = (await db.execute(
                select(Brand).where(Brand.name == brand_name)
            )).scalar_one_or_none()
            if not row:
                log.warning("  %s: brand row not found, skipping", brand_name)
                stats["skipped_no_brand"] += 1
                continue
            if row.logo_url and row.logo_url.startswith(LOCAL_URL_PREFIX):
                log.info("  %s: already has local logo (%s), skipping", brand_name, row.logo_url)
                stats["skipped_have_logo"] += 1
                continue
            filename = _safe_filename(row.slug, url)
            dest = STATIC_DIR / filename
            try:
                r = await asyncio.get_event_loop().run_in_executor(None, sync_client.get, url)
                if r.status_code != 200 or len(r.content) < 200:
                    log.warning("  %s: HTTP %d / %d bytes — skipping", brand_name, r.status_code, len(r.content))
                    stats["failed"] += 1
                    continue
                dest.write_bytes(r.content)
                local_url = f"{LOCAL_URL_PREFIX}/{filename}"
                await db.execute(update(Brand).where(Brand.id == row.id).values(logo_url=local_url))
                stats["updated"] += 1
                log.info("  %s -> %s (%d bytes)", brand_name, local_url, len(r.content))
            except Exception as e:
                log.warning("  %s: %s", brand_name, e)
                stats["failed"] += 1

        await db.commit()
        log.info("Done: %s", stats)

    sync_client.close()

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
