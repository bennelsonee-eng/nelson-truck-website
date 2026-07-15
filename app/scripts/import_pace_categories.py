"""Import PACE's category taxonomy into our `category` table.

Sources the 18 top-level + 288 sub-categories from
https://titan.pacesystems.com/catalog/categories (publicly accessible).
Each category becomes a row in the existing `category` table with
parent_id wired up via the URL path.

Usage:
    python app/scripts/import_pace_categories.py            # full import
    python app/scripts/import_pace_categories.py --dry-run  # parse only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import Category  # noqa: E402


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("import_pace_categories")


PACE_CATEGORIES_URL = "https://titan.pacesystems.com/catalog/categories"


async def fetch_categories_html(client: httpx.AsyncClient) -> str:
    r = await client.get(PACE_CATEGORIES_URL, timeout=30.0)
    r.raise_for_status()
    return r.text


def parse_categories(html: str) -> list[dict]:
    """Extract (slug, title, depth, parent_slug) tuples from PACE categories page."""
    pattern = re.compile(r'href="catalog/browse/([a-z0-9/-]+)"[^>]*title="([^"]+)"')
    matches = pattern.findall(html)
    seen: dict[str, str] = {}
    for slug, title in matches:
        if slug not in seen:
            seen[slug] = title

    # Build the structured list
    rows: list[dict] = []
    for slug, title in seen.items():
        depth = slug.count("/") + 1
        # Display name = the part after last " > "
        if " > " in title:
            display_name = title.split(" > ")[-1].strip()
        else:
            display_name = title.strip()
        # Parent slug = everything before the last "/"
        if "/" in slug:
            parent_slug = slug.rsplit("/", 1)[0]
        else:
            parent_slug = None
        rows.append({
            "slug": slug,
            "name": display_name,
            "full_path": title,  # the full breadcrumb-style title
            "depth": depth,
            "parent_slug": parent_slug,
        })
    # Sort so depth-1 lands before depth-2 (parents must exist before children)
    rows.sort(key=lambda r: (r["depth"], r["slug"]))
    return rows


async def upsert_categories(db, rows: list[dict]) -> dict[str, int]:
    """Insert/update each row. Returns slug -> category_id map."""
    slug_to_id: dict[str, int] = {}

    # First pass: depth=1 rows (no parent)
    for r in rows:
        if r["depth"] != 1:
            continue
        existing = (await db.execute(
            select(Category).where(Category.slug == r["slug"])
        )).scalar_one_or_none()
        if existing:
            existing.name = r["name"]
            existing.full_path = r["full_path"]
            existing.depth = 1
            existing.parent_id = None
            existing.is_active = True
            await db.flush()
            slug_to_id[r["slug"]] = existing.id
        else:
            cat = Category(
                slug=r["slug"],
                name=r["name"],
                full_path=r["full_path"],
                depth=1,
                parent_id=None,
                sort_order=1000,
                is_featured=False,
                is_active=True,
            )
            db.add(cat)
            await db.flush()
            slug_to_id[r["slug"]] = cat.id

    # Second pass: depth>1 rows
    for r in rows:
        if r["depth"] == 1:
            continue
        parent_id = slug_to_id.get(r["parent_slug"])
        if parent_id is None:
            log.warning("Orphan category %s (parent %s missing)", r["slug"], r["parent_slug"])
            continue
        existing = (await db.execute(
            select(Category).where(Category.slug == r["slug"])
        )).scalar_one_or_none()
        if existing:
            existing.name = r["name"]
            existing.full_path = r["full_path"]
            existing.depth = r["depth"]
            existing.parent_id = parent_id
            existing.is_active = True
            await db.flush()
            slug_to_id[r["slug"]] = existing.id
        else:
            cat = Category(
                slug=r["slug"],
                name=r["name"],
                full_path=r["full_path"],
                depth=r["depth"],
                parent_id=parent_id,
                sort_order=1000,
                is_featured=False,
                is_active=True,
            )
            db.add(cat)
            await db.flush()
            slug_to_id[r["slug"]] = cat.id

    await db.commit()
    return slug_to_id


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Parse only, don't write to DB")
    args = ap.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with httpx.AsyncClient(verify=False) as client:
        log.info("Fetching %s ...", PACE_CATEGORIES_URL)
        html = await fetch_categories_html(client)
        log.info("Got %d KB of HTML", len(html) // 1024)

    rows = parse_categories(html)
    log.info("Parsed %d unique categories", len(rows))
    by_depth = {}
    for r in rows:
        by_depth[r["depth"]] = by_depth.get(r["depth"], 0) + 1
    log.info("By depth: %s", by_depth)

    if args.dry_run:
        log.info("--dry-run: not writing to DB. First 10 parsed rows:")
        for r in rows[:10]:
            log.info("  %s", r)
        return 0

    async with Session() as db:
        slug_to_id = await upsert_categories(db, rows)
        log.info("Upserted %d category rows", len(slug_to_id))

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
