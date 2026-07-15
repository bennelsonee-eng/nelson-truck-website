"""Map our PartTypeIDs to PACE's category taxonomy.

Walks every leaf category in our `category` table, fetches the PACE
catalog page via the authenticated session, extracts the data-aaia +
data-pn pairs from the rendered product cards, looks up the corresponding
pace_part rows in our DB to get their part_terminology_id, and aggregates
to determine: which PartTypeID belongs to which category.

Then upserts pcdb_part_type with category_name + sub_category_name.

This script needs an authenticated PACE session cookie. The simplest path:
copy the session cookie from your logged-in browser into env var PACE_COOKIE,
or pass --cookie on the command line.

    PACE_COOKIE='fd548b...=...; pace-ordering-mode=1' python app/scripts/map_part_types_to_categories.py

Cookie expires periodically — re-grab it from a logged-in browser if you
get 302 redirects mid-run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import Brand, Category, PacePart, PcdbPartType  # noqa: E402


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("map_part_types")
logging.getLogger("httpx").setLevel(logging.WARNING)


PACE_BROWSE_BASE = "https://titan.pacesystems.com/catalog/browse"
RATE_LIMIT_PER_SEC = 4  # be polite to PACE


# Pattern to extract aaia + pn from product cards
PRODUCT_PATTERN = re.compile(
    r'<div\s+id="product-[A-Z0-9]+"[^>]*\bdata-aaia="([A-Z0-9]+)"[^>]*\bdata-pn="([^"]+)"',
    re.IGNORECASE,
)


async def fetch_category_page(client: httpx.AsyncClient, slug: str) -> tuple[int, str]:
    """Returns (status_code, html). 302 = auth expired."""
    try:
        r = await client.get(f"{PACE_BROWSE_BASE}/{slug}", timeout=20.0,
                              follow_redirects=False)
        return r.status_code, r.text
    except httpx.RequestError as e:
        log.warning("fetch failed for %s: %s", slug, e)
        return 0, ""


def extract_parts(html: str) -> list[tuple[str, str]]:
    """Returns list of (aaia_code, part_number) tuples from product cards."""
    return [(m[0], m[1]) for m in PRODUCT_PATTERN.findall(html)]


async def lookup_part_type(db, aaia: str, part_number: str) -> int | None:
    """Returns part_terminology_id for the given (aaia, pn) or None."""
    row = (await db.execute(
        select(PacePart.part_terminology_id)
        .join(Brand, Brand.id == PacePart.brand_id)
        .where(Brand.aaia_code == aaia, PacePart.part_number == part_number)
    )).first()
    return row[0] if row else None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookie", default=os.environ.get("PACE_COOKIE"),
                    help="PACE session cookie (required for authenticated category pages)")
    ap.add_argument("--limit", type=int, help="Cap leaf categories (smoke test)")
    ap.add_argument("--depth-only", type=int, default=2,
                    help="Only walk leaves at this depth (default 2; use 1 to also include depth-1 leaves)")
    args = ap.parse_args()

    if not args.cookie:
        log.error("--cookie or env PACE_COOKIE required")
        return 1

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # Pull leaf categories: depth 2 OR depth 1 with no children
        all_cats = (await db.execute(
            select(Category.id, Category.slug, Category.name, Category.full_path,
                   Category.depth, Category.parent_id)
            .where(Category.is_active == True)  # noqa: E712
            .order_by(Category.depth, Category.slug)
        )).all()

        # Find depth-1 with no children
        children_count: dict[int, int] = defaultdict(int)
        for cat in all_cats:
            if cat.parent_id:
                children_count[cat.parent_id] += 1

        leaves: list = []
        for cat in all_cats:
            if cat.depth >= args.depth_only:
                leaves.append(cat)
            elif cat.depth == 1 and children_count[cat.id] == 0:
                leaves.append(cat)

        if args.limit:
            leaves = leaves[:args.limit]

        log.info("Will scrape %d leaf categories", len(leaves))

        # part_type_id -> Counter({(top_cat_name, sub_cat_name): count})
        ptype_to_categories: dict[int, Counter] = defaultdict(Counter)
        api_calls = 0
        rate_t0 = time.time()
        scraped = 0
        skipped = 0

        async with httpx.AsyncClient(
            verify=False,
            headers={
                "Cookie": args.cookie,
                "User-Agent": "Mozilla/5.0 Titan-Catalog-Mapper/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        ) as client:
            for i, cat in enumerate(leaves, 1):
                # Throttle
                elapsed = time.time() - rate_t0
                target = api_calls / RATE_LIMIT_PER_SEC
                if elapsed < target:
                    await asyncio.sleep(target - elapsed)

                status, html = await fetch_category_page(client, cat.slug)
                api_calls += 1

                if status == 302:
                    log.error("Got 302 redirect — session cookie expired. Re-grab from browser. Aborting.")
                    return 2
                if status != 200 or not html:
                    log.warning("  [%d/%d] %s -> status=%s, skipping", i, len(leaves), cat.slug, status)
                    skipped += 1
                    continue

                pairs = extract_parts(html)
                if not pairs:
                    log.warning("  [%d/%d] %s -> no products found", i, len(leaves), cat.slug)
                    skipped += 1
                    continue

                # Top + sub names from full_path
                if " > " in cat.full_path:
                    top_name, sub_name = cat.full_path.split(" > ", 1)
                else:
                    top_name, sub_name = cat.full_path, None

                # For each part, look up its PartTypeID
                hits = 0
                for aaia, pn in pairs:
                    pt_id = await lookup_part_type(db, aaia, pn)
                    if pt_id is not None:
                        ptype_to_categories[pt_id][(top_name, sub_name)] += 1
                        hits += 1
                scraped += 1
                if i % 25 == 0 or i == len(leaves):
                    log.info("  [%d/%d] scraped, %d ptype mappings collected so far. Last: %s -> %d/%d hits",
                             i, len(leaves), len(ptype_to_categories), cat.slug, hits, len(pairs))

        log.info("Scrape done: %d scraped / %d skipped / %d api calls / %.0fs elapsed",
                 scraped, skipped, api_calls, time.time() - rate_t0)

        # Locked part types carry a manual taxonomy override (issues #13/#14);
        # a re-scrape must NOT clobber them. Skip and report.
        locked_ids = set((await db.execute(
            select(PcdbPartType.id).where(PcdbPartType.category_locked == True)  # noqa: E712
        )).scalars().all())

        # Aggregate: for each PartTypeID, pick the most common category
        log.info("Updating pcdb_part_type rows with category names...")
        updates = 0
        skipped_locked = 0
        for pt_id, counts in ptype_to_categories.items():
            if pt_id in locked_ids:
                skipped_locked += 1
                continue
            (top_name, sub_name), _count = counts.most_common(1)[0]
            await db.execute(
                update(PcdbPartType)
                .where(PcdbPartType.id == pt_id)
                .values(category_name=top_name, sub_category_name=sub_name)
            )
            updates += 1
        await db.commit()
        log.info("Updated %d PartTypeIDs with category mapping (%d locked, skipped)",
                 updates, skipped_locked)

        # Coverage report
        total_ptypes = (await db.execute(
            select(PcdbPartType.id).where(PcdbPartType.id.is_not(None))
        )).all()
        with_cat = (await db.execute(
            select(PcdbPartType.id).where(PcdbPartType.category_name.is_not(None))
        )).all()
        log.info("Coverage: %d of %d PartTypeIDs now have categories (%.0f%%)",
                 len(with_cat), len(total_ptypes),
                 100 * len(with_cat) / max(1, len(total_ptypes)))

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
