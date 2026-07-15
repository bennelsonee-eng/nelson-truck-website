"""Phase 2 of category mapping: scrape every PACE leaf category page using a
borrowed browser session cookie, extract data-aaia + data-pn pairs from product
cards, look up part_terminology_id in our pace_part table, aggregate, and update
pcdb_part_type with category_name + sub_category_name.

Cookie comes from a logged-in PACE browser tab (HttpOnly so JS can't read it,
but visible in DevTools Network → request headers). Pass via env PACE_COOKIE.

Usage:
    PACE_COOKIE='fd548...=...; pace-ordering-mode=1' \\
      python app/scripts/scrape_pace_categories_python.py
"""

from __future__ import annotations

import asyncio
import json
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
log = logging.getLogger("scrape_pace_categories")
logging.getLogger("httpx").setLevel(logging.WARNING)


PACE_BASE = "https://titan.pacesystems.com/catalog/browse"
CONCURRENCY = 4  # high concurrency triggered 302 redirects, dial down
# Loose regex: PACE's product cards have data-aaia and data-pn within ~500
# chars of each other but separated by newlines + other attributes.
PRODUCT_RE = re.compile(
    r'data-aaia="([A-Z0-9]+)"[^>]{0,500}?data-pn="([^"]+)"',
    re.IGNORECASE | re.DOTALL,
)


async def fetch_one(client: httpx.AsyncClient, slug: str) -> dict:
    """Fetch one category page, return {status, parts: [(aaia, pn), ...], fallback_top_only: bool}.

    PACE redirects (302) when this account has no inventory in the exact
    subcategory — destination URL ends in `/all-subcategories/all-brands`,
    which lists parts across the WHOLE top category. We follow that redirect
    and attribute results to the TOP category only.
    """
    try:
        r = await client.get(f"{PACE_BASE}/{slug}", timeout=30.0,
                              follow_redirects=False)
        if r.status_code == 200:
            parts = PRODUCT_RE.findall(r.text)
            return {"status": 200, "parts": parts, "fallback_top_only": False}
        if r.status_code == 302:
            # Follow the fallback to harvest top-level category parts
            redirect_url = r.headers.get("location", "")
            if "all-subcategories" in redirect_url:
                r2 = await client.get(redirect_url, timeout=30.0, follow_redirects=False)
                if r2.status_code == 200:
                    parts = PRODUCT_RE.findall(r2.text)
                    return {"status": 200, "parts": parts, "fallback_top_only": True}
            return {"status": r.status_code, "parts": [], "fallback_top_only": False}
        return {"status": r.status_code, "parts": [], "fallback_top_only": False}
    except Exception as e:
        return {"status": 0, "parts": [], "error": str(e), "fallback_top_only": False}


async def scrape_all(slugs: list[str], cookie: str) -> dict:
    """Concurrently fetch all category pages."""
    headers = {
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 Titan-Catalog-Mapper/1.0",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        # NOTE: omit "br" — httpx doesn't decompress Brotli without the optional brotli dep
        "Accept-Encoding": "gzip, deflate",
    }
    sem = asyncio.Semaphore(CONCURRENCY)
    results: dict[str, dict] = {}
    completed = 0
    t0 = time.time()

    async with httpx.AsyncClient(verify=False, headers=headers) as client:
        async def runner(slug: str):
            nonlocal completed
            async with sem:
                r = await fetch_one(client, slug)
                results[slug] = r
                completed += 1
                if completed % 50 == 0:
                    log.info("  scraped %d/%d (%.0fs elapsed)", completed,
                             len(slugs), time.time() - t0)

        await asyncio.gather(*(runner(s) for s in slugs))

    return results


async def main() -> int:
    cookie = os.environ.get("PACE_COOKIE")
    if not cookie:
        log.error("PACE_COOKIE env var required")
        return 1

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # Get all leaf categories: depth 2 OR depth 1 with no children
        rows = (await db.execute(
            select(Category.id, Category.slug, Category.full_path,
                   Category.depth, Category.parent_id)
            .where(Category.is_active == True)  # noqa: E712
        )).all()

        children_count: dict[int, int] = defaultdict(int)
        for r in rows:
            if r.parent_id:
                children_count[r.parent_id] += 1

        leaves: list = [r for r in rows
                        if r.depth >= 2 or (r.depth == 1 and children_count[r.id] == 0)]
        log.info("Will scrape %d leaf categories", len(leaves))

        results = await scrape_all([leaf.slug for leaf in leaves], cookie)
        log.info("Scrape complete: %d results, %d total parts extracted",
                 len(results), sum(len(r["parts"]) for r in results.values()))

        # Save raw scrape for debugging
        out_dir = Path(r"C:\Users\Ben\AppData\Local\Temp\pace_leaves")
        out_dir.mkdir(exist_ok=True)
        (out_dir / "scrape_results.json").write_text(json.dumps(results))
        log.info("Saved raw scrape to %s", out_dir / "scrape_results.json")

        # Aggregate: for each (aaia, pn), count which slugs they appear in.
        # Track separately whether the appearance was at the leaf (specific sub) or
        # at the top-only fallback — leaf appearances get higher confidence.
        part_to_slug_specific: dict[tuple[str, str], set[str]] = defaultdict(set)
        part_to_slug_fallback: dict[tuple[str, str], set[str]] = defaultdict(set)
        for slug, r in results.items():
            if r.get("status") != 200:
                continue
            target = part_to_slug_fallback if r.get("fallback_top_only") else part_to_slug_specific
            for aaia, pn in r["parts"]:
                target[(aaia, pn)].add(slug)
        # Combined view for resolution
        part_to_slugs = defaultdict(set)
        for k, v in part_to_slug_specific.items():
            part_to_slugs[k] |= v
        for k, v in part_to_slug_fallback.items():
            part_to_slugs[k] |= v

        # Lookup PartTypeIDs for each part
        log.info("Looking up part_terminology_id for %d parts...", len(part_to_slugs))
        part_to_ptype: dict[tuple[str, str], int] = {}
        # Batch the lookup
        all_pairs = list(part_to_slugs.keys())
        for i in range(0, len(all_pairs), 500):
            batch = all_pairs[i:i+500]
            batch_aaia = {b[0] for b in batch}
            # Get all relevant brand_ids
            brand_rows = (await db.execute(
                select(Brand.id, Brand.aaia_code).where(Brand.aaia_code.in_(batch_aaia))
            )).all()
            aaia_to_bid = {a: i for i, a in brand_rows}
            for aaia, pn in batch:
                bid = aaia_to_bid.get(aaia)
                if bid is None:
                    continue
                row = (await db.execute(
                    select(PacePart.part_terminology_id)
                    .where(PacePart.brand_id == bid, PacePart.part_number == pn)
                )).first()
                if row and row[0]:
                    part_to_ptype[(aaia, pn)] = row[0]

        log.info("Resolved %d/%d parts to part_terminology_ids",
                 len(part_to_ptype), len(part_to_slugs))

        # Build slug → full_path map
        slug_to_full: dict[str, str] = {leaf.slug: leaf.full_path for leaf in leaves}

        # Vote: leaf appearances weighted by 10/n_slugs (specificity reward)
        # Fallback (top-only) appearances weighted by 1.0 — get top-cat confirmation
        # but never beat a real leaf signal.
        ptype_votes: dict[int, Counter] = defaultdict(Counter)
        for (aaia, pn), pt_id in part_to_ptype.items():
            specific_slugs = part_to_slug_specific.get((aaia, pn), set())
            fallback_slugs = part_to_slug_fallback.get((aaia, pn), set())
            if specific_slugs:
                weight = max(0.5, 10.0 / len(specific_slugs))
                for slug in specific_slugs:
                    full_path = slug_to_full.get(slug, "")
                    if not full_path:
                        continue
                    if " > " in full_path:
                        top, sub = full_path.split(" > ", 1)
                    else:
                        top, sub = full_path, None
                    ptype_votes[pt_id][(top, sub)] += weight
            # Fallback gives only top-cat assignment with sub=None
            for slug in fallback_slugs:
                # Fallback URL is "<top>/all-subcategories/all-brands"
                top_slug = slug.split("/")[0] if "/" in slug else slug
                # Look up the human name for this top slug
                top_name = None
                for s, fp in slug_to_full.items():
                    if s == top_slug:
                        top_name = fp.split(" > ")[0] if " > " in fp else fp
                        break
                if top_name:
                    ptype_votes[pt_id][(top_name, None)] += 1.0

        # Locked part types carry a manual taxonomy override (issues #13/#14);
        # a re-scrape must NOT clobber them. Skip and report.
        locked_ids = set((await db.execute(
            select(PcdbPartType.id).where(PcdbPartType.category_locked == True)  # noqa: E712
        )).scalars().all())

        # Take winning category per PartTypeID
        log.info("Aggregating PartTypeID → category votes...")
        updates = 0
        skipped_locked = 0
        for pt_id, counts in ptype_votes.items():
            if pt_id in locked_ids:
                skipped_locked += 1
                continue
            (top, sub), winning_score = counts.most_common(1)[0]
            await db.execute(
                update(PcdbPartType)
                .where(PcdbPartType.id == pt_id)
                .values(category_name=top, sub_category_name=sub)
            )
            updates += 1
        await db.commit()
        log.info("Updated %d PartTypeIDs with category mapping (%d locked, skipped)",
                 updates, skipped_locked)

        # Coverage report
        total_ptypes = (await db.execute(select(PcdbPartType.id))).all()
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
