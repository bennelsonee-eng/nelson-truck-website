"""Import WSM image URLs + category trees + extended descriptions per product.

Reads `app/data/wsm_export/product-*.csv` and for each row:
  * Parses STOCKID like "BGND:38302" → wsm_prefix=BGND, suffix=38302
  * Looks up brand by legacy_wsm_prefix → finds product where sku ends with suffix
  * Pulls IMAGE column (semicolon-separated URLs) → ProductImage rows
  * Pulls CATEGORYTREE column (>-separated path) → Category tree + ProductCategory link
  * Optionally backfills extended_description, meta fields, legacy_wsm_stockid

Idempotent: re-running deletes existing rows for matched products and re-inserts
(simpler than diff-merge for the first pass).

Run: python -m app.scripts.import_wsm_details                  # all CSVs
     python -m app.scripts.import_wsm_details --limit 5000     # for smoke test
     python -m app.scripts.import_wsm_details --files 1,2      # only those CSV indexes
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
import sys
from pathlib import Path
from typing import Iterator

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Make the backend package importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import Brand, Category, Product, ProductCategory, ProductImage  # noqa: E402


csv.field_size_limit(2**31 - 1)


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("import_wsm_details")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


WSM_DIR = Path(__file__).resolve().parents[1] / "data" / "wsm_export"


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s[:200] or "unnamed"


def _split_stockid(stockid: str) -> tuple[str, str] | None:
    """`'BGND:38302'` → `('BGND', '38302')`.  Returns None if malformed."""
    if not stockid or ":" not in stockid:
        return None
    prefix, _, suffix = stockid.partition(":")
    return prefix.strip(), suffix.strip()


def _parse_image_urls(image_field: str) -> list[str]:
    """`'url1;url2;url3'` → `['url1', 'url2', 'url3']` (drops empties)."""
    if not image_field:
        return []
    return [u.strip() for u in image_field.split(";") if u.strip()]


async def _build_product_index(db: AsyncSession) -> dict[tuple[str, str], int]:
    """Build `(legacy_wsm_prefix, part_suffix) -> product_id` lookup.

    `part_suffix` is the SKU with the brand's prod_code prefix stripped, lowercased
    (since WSM STOCKIDs are case-flexible).  We skip any product whose brand has
    no `legacy_wsm_prefix` set (can't link to WSM rows for those).
    """
    log.info("Building product index from DB…")
    rows = (await db.execute(
        select(Product.id, Product.sku, Product.prod_code, Brand.legacy_wsm_prefix)
        .join(Brand, Brand.id == Product.brand_id)
        .where(Brand.legacy_wsm_prefix.is_not(None))
    )).all()

    index: dict[tuple[str, str], int] = {}
    for prod_id, sku, prod_code, wsm_prefix in rows:
        if prod_code and sku.startswith(prod_code):
            suffix = sku[len(prod_code):]
        else:
            suffix = sku
        key = (wsm_prefix.upper(), suffix.upper())
        # Don't overwrite — if there's a collision, first-write-wins
        index.setdefault(key, prod_id)
    log.info("  Indexed %d products across %d brands with WSM prefix",
             len(index), len(set(k[0] for k in index.keys())))
    return index


def _iter_csv_rows(paths: list[Path], limit: int | None = None) -> Iterator[dict[str, str]]:
    """Yield row dicts from each CSV, with normalized header names.

    The WSM exports come split across several files with different schemas; we
    silently skip any file that doesn't have STOCKID.  utf-8-sig strips a BOM
    if present (it confuses csv.DictReader's quote handling otherwise).
    """
    total = 0
    for path in paths:
        log.info("Reading %s (%.1f MB)…", path.name, path.stat().st_size / 1024 / 1024)
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            cols = set(reader.fieldnames or [])
            if "STOCKID" not in cols:
                log.info("  (skip — no STOCKID column; cols=%s)", sorted(cols)[:6])
                continue
            has_image = "IMAGE" in cols or "IMAGES" in cols
            has_cat = "CATEGORYTREE" in cols
            log.info("  STOCKID present; has_image=%s, has_categorytree=%s", has_image, has_cat)
            for row in reader:
                # Normalize: WSM uses both IMAGE and IMAGES across different exports
                if "IMAGES" in row and "IMAGE" not in row:
                    row["IMAGE"] = row["IMAGES"]
                yield row
                total += 1
                if limit and total >= limit:
                    return


async def _ensure_categories(db: AsyncSession, paths_seen: set[str]) -> dict[str, int]:
    """Materialize the category hierarchy from a set of `>`-delimited path strings.

    Returns `path_string -> category_id` for fast lookup during product linking.
    Idempotent: existing categories are left alone and reused.
    """
    log.info("Materializing %d unique category paths…", len(paths_seen))
    # Collect every prefix (so 'A>B>C' creates A, A>B, A>B>C)
    all_prefixes: set[str] = set()
    for full in paths_seen:
        parts = [p.strip() for p in full.split(">") if p.strip()]
        for i in range(1, len(parts) + 1):
            all_prefixes.add(">".join(parts[:i]))

    # Existing categories indexed by full_path
    existing = {
        p: cid for cid, p in (await db.execute(select(Category.id, Category.full_path))).all()
    }
    inserted = 0
    # Insert in depth order so parent_id can be resolved on the fly
    for path in sorted(all_prefixes, key=lambda p: p.count(">")):
        if path in existing:
            continue
        parts = [p.strip() for p in path.split(">") if p.strip()]
        name = parts[-1]
        depth = len(parts) - 1
        parent_path = ">".join(parts[:-1])
        parent_id = existing.get(parent_path) if parent_path else None
        cat = Category(
            name=name,
            slug=_slugify(name),
            full_path=path,
            depth=depth,
            parent_id=parent_id,
        )
        db.add(cat)
        await db.flush()
        existing[path] = cat.id
        inserted += 1
    if inserted:
        await db.commit()
    log.info("  Inserted %d new categories (total: %d)", inserted, len(existing))
    return existing


async def import_wsm_details(
    db: AsyncSession,
    *,
    files: list[int] | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Run the full import.  Returns a stats dict."""
    csv_paths = sorted(WSM_DIR.glob("product-*.csv"))
    if files:
        csv_paths = [p for i, p in enumerate(csv_paths) if i in set(files)]
    if not csv_paths:
        raise RuntimeError(f"No product-*.csv found in {WSM_DIR}")

    product_index = await _build_product_index(db)

    # Pass 1: walk all rows, collect category paths + matched-product details.
    # We hold the matched-row records in memory (~120K rows × small dict each
    # = ~30 MB at most — fine).
    matched_rows: list[dict] = []
    category_paths: set[str] = set()
    rows_total = rows_matched = rows_with_image = rows_with_cat = 0

    for row in _iter_csv_rows(csv_paths, limit=limit):
        rows_total += 1
        stockid = (row.get("STOCKID") or "").strip()
        parsed = _split_stockid(stockid)
        if parsed is None:
            continue
        wsm_prefix, suffix = parsed
        product_id = product_index.get((wsm_prefix.upper(), suffix.upper()))
        if product_id is None:
            continue
        rows_matched += 1
        images = _parse_image_urls(row.get("IMAGE") or "")
        cat_path = (row.get("CATEGORYTREE") or "").strip()
        if cat_path:
            category_paths.add(cat_path)
            rows_with_cat += 1
        if images:
            rows_with_image += 1
        matched_rows.append({
            "product_id": product_id,
            "stockid": stockid,
            "images": images,
            "cat_path": cat_path,
            "extended_desc": (row.get("EXTENDEDDESCRIPTION") or "").strip() or None,
            "meta_title": (row.get("METATITLE") or "").strip() or None,
            "meta_description": (row.get("METADESCRIPTION") or "").strip() or None,
            "meta_keywords": (row.get("METAKEYWORDS") or "").strip() or None,
        })

    log.info("Scan complete: %d total rows, %d matched, %d with images, %d with categories",
             rows_total, rows_matched, rows_with_image, rows_with_cat)
    if not matched_rows:
        log.warning("No matched rows — nothing to write")
        return dict(rows_total=rows_total, rows_matched=0)

    # Pass 2: ensure all category nodes exist and get id lookup
    cat_id_by_path = await _ensure_categories(db, category_paths)

    # Pass 3: for each matched product, wipe its old images + category links and re-insert
    log.info("Wiping existing images + category links for %d matched products…", len(matched_rows))
    matched_pids = list({r["product_id"] for r in matched_rows})
    BATCH = 1000
    for i in range(0, len(matched_pids), BATCH):
        chunk = matched_pids[i:i + BATCH]
        await db.execute(delete(ProductImage).where(ProductImage.product_id.in_(chunk)))
        await db.execute(delete(ProductCategory).where(ProductCategory.product_id.in_(chunk)))
    await db.commit()

    log.info("Inserting new images + category links + meta backfill…")
    images_to_insert: list[dict] = []
    cat_links_to_insert: list[dict] = []
    meta_updates: list[dict] = []

    seen_pid_for_meta: set[int] = set()  # only update meta once per product (first match wins)
    for r in matched_rows:
        pid = r["product_id"]
        for sort_idx, url in enumerate(r["images"]):
            images_to_insert.append({
                "product_id": pid,
                "url": url,
                "alt_text": None,
                "sort_order": sort_idx,
                "is_primary": sort_idx == 0,
                "legacy_origin": "nelsontruck.com" if "nelsontruck.com" in url else None,
            })
        if r["cat_path"]:
            cid = cat_id_by_path.get(r["cat_path"])
            if cid is not None:
                cat_links_to_insert.append({
                    "product_id": pid,
                    "category_id": cid,
                    "is_primary": True,
                })
        if pid not in seen_pid_for_meta and (r["extended_desc"] or r["meta_title"] or r["meta_description"]):
            meta_updates.append({
                "id": pid,
                "extended_description": r["extended_desc"],
                "meta_title": r["meta_title"],
                "meta_description": r["meta_description"],
                "meta_keywords": r["meta_keywords"],
                "legacy_wsm_stockid": r["stockid"],
            })
            seen_pid_for_meta.add(pid)

    log.info("  %d image rows, %d category links, %d meta updates",
             len(images_to_insert), len(cat_links_to_insert), len(meta_updates))

    # Bulk insert images
    for i in range(0, len(images_to_insert), 5000):
        chunk = images_to_insert[i:i + 5000]
        await db.execute(pg_insert(ProductImage), chunk)
    # Bulk insert category links (with ON CONFLICT DO NOTHING in case dupes from re-runs)
    for i in range(0, len(cat_links_to_insert), 5000):
        chunk = cat_links_to_insert[i:i + 5000]
        stmt = pg_insert(ProductCategory).values(chunk).on_conflict_do_nothing(
            index_elements=["product_id", "category_id"],
        )
        await db.execute(stmt)
    # Bulk update product meta — use individual UPDATEs (PG doesn't have a clean
    # bulk-UPDATE-from-VALUES with ORM; in-the-loop is fine for a one-off import)
    for upd in meta_updates:
        await db.execute(
            Product.__table__.update()
            .where(Product.id == upd["id"])
            .values(
                extended_description=upd["extended_description"],
                meta_title=upd["meta_title"],
                meta_description=upd["meta_description"],
                meta_keywords=upd["meta_keywords"],
                legacy_wsm_stockid=upd["legacy_wsm_stockid"],
            )
        )
    await db.commit()

    return dict(
        rows_total=rows_total,
        rows_matched=rows_matched,
        rows_with_image=rows_with_image,
        rows_with_cat=rows_with_cat,
        images_inserted=len(images_to_insert),
        categories_total=len(cat_id_by_path),
        category_links=len(cat_links_to_insert),
        meta_updates=len(meta_updates),
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Stop after N total rows (smoke test)")
    parser.add_argument("--files", default=None, help="Comma-separated CSV file indexes (0-based)")
    args = parser.parse_args()

    files = [int(x) for x in args.files.split(",")] if args.files else None
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        stats = await import_wsm_details(db, files=files, limit=args.limit)
    await engine.dispose()
    log.info("Done: %s", stats)


if __name__ == "__main__":
    asyncio.run(main())
