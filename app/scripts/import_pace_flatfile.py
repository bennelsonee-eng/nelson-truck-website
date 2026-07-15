"""import_pace_flatfile.py — Ingest AWDA PIES *flat-file* brand exports (CSV/XLSX).

These are the `*_<BRAND>_USD_AWDA_export.csv|.xlsx` files from the AAM/AWDA
portal: one brand per file, one part per row, 61 PIES columns. They carry the
SAME product master data as the PIES XML zips (descriptions, images, pricing,
UPC, dims) but in a flat layout and WITHOUT:
  - ACES fitment (only a Y/N `ACESApplications` flag)        -> no YMM data here
  - PartTerminologyID                                        -> no auto-category
  - a generic ProductAttributes block                        -> thin faceting

So this importer is a CONTENT/IMAGE/UPC/PRICING enrichment layer. It is the
flat-file sibling of `import_pace_brand.py::ingest_pies()` and reuses the same
canonical model + DB conventions (asyncpg, port 5433, titan_web).

DESIGN — coexists safely with the XML PIES importer (run in either order):
  * ADDITIVE, never destructive. We only replace the description codes we
    write and this product's current pricing; we DO NOT touch ProductAttribute
    or ProductPackage (the XML feed owns those and the flat file can't improve
    them). Product dims/upc/weight are filled only when currently NULL.
  * Default mode is ENRICH-EXISTING-ONLY: a row is applied only if a Product
    already exists for one of the candidate SKUs. Rows with no match are
    skipped (counted). Pass --create-new to also INSERT products (they will be
    uncategorized/unfitted until the ACES XML pass — use only after ACES).

Pricing note: PIES prices land in `product_pricing` (reference: MSR/JBR/LST/
WD1...). The storefront cart price comes from the ERP-driven `product_price`
table, which this script never touches.

Usage:
    # dry-run a single brand file (no writes), show what would change
    python app/scripts/import_pace_flatfile.py --dry-run \\
        "/c/Users/Ben/Downloads/20260629153050_1158_BHWQ_USD_AWDA_export.xlsx"

    # import every today's AWDA file from a directory
    python app/scripts/import_pace_flatfile.py --dir "/c/Users/Ben/Downloads" --glob "*_AWDA_export.*"

    # also create products that don't exist yet (post-ACES only)
    python app/scripts/import_pace_flatfile.py --create-new --dir ...
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import glob as globmod
import logging
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Make the backend package importable when run as a script (mirror import_pace_brand)
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import (  # noqa: E402
    PacePart,
    Product,
    ProductDescription,
    ProductImage,
    ProductPricing,
)
from app.models.catalog import CTAMode  # noqa: E402

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("import_pace_flat")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

DCI_CSV = REPO / "app" / "data" / "mysql_dumps" / "dci_codes.csv"

# AWDA flat-column -> PIES DescriptionCode. Order matters for name fallback.
#   DES -> product name source (the main one-line product description)
#   SHO -> short
#   MKT -> marketing paragraph (also mirrored to product.description)
#   EXT -> extended (also mirrored to product.extended_description)
#   FEA -> features list (PDP "Features" tab filters on FEA, NOT FAB)
DESC_COLS = {
    "Description": "DES",
    "ShortDescription": "SHO",
    "MarketingDescription": "MKT",
    "ExtendedDescription": "EXT",
    "FeaturesAndBenefits": "FEA",
}
DESC_CODES = set(DESC_COLS.values())

# AWDA price column -> product_pricing.price_type (reference prices only).
PRICE_COLS = {
    "MSRP": "MSR",
    "JobberPrice": "JBR",
    "RetailPrice": "LST",
    "AAMCost": "WD1",
    "WholesaleMAP": "WMAP",
    "RetailMAP": "RMAP",
}

# AWDA image columns -> role. PhotoPrimary is the primary; the rest are extras.
IMAGE_COLS_PRIMARY = "PhotoPrimary"
IMAGE_COLS_SECONDARY = [
    "PhotoLifestyleView", "PhotoOutOfPackage", "PhotoInPackage",
    "PhotoCloseUp", "PhotoMounted", "PhotoUnmounted",
]

# PIES LifeCycleStatusCode values seen in the feed: "2" dominates (active),
# "8" is the next largest. The exact code list is an Auto Care PIES code set;
# we DO NOT act on it by default (the ERP controls sellability). We only log
# the distribution. Pass --skip-lifecycle "8,9" to skip those codes.


def _d(s) -> Decimal | None:
    if s in (None, ""):
        return None
    try:
        d = Decimal(str(s).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not d.is_finite() or d == 0:
        return None
    return d


def _date(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    return None


def _split_urls(cell) -> list[str]:
    """A photo cell may hold one or several comma-separated URLs."""
    if not cell:
        return []
    out = []
    for part in str(cell).split(","):
        u = part.strip()
        if u.lower().startswith("http"):
            out.append(u)
    return out


def load_dci_lookup() -> dict[str, str]:
    out: dict[str, str] = {}
    if not DCI_CSV.exists():
        return out
    with open(DCI_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ac = (r.get("aaia_code") or "").strip()
            if ac:
                out[ac] = (r.get("manu_title") or "").strip()
    return out


def iter_rows(path: Path):
    """Yield dict rows from a CSV or XLSX AWDA export (same 61-col schema)."""
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            yield from csv.DictReader(fh)
    elif path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        try:
            header = [str(h).strip() if h is not None else "" for h in next(it)]
        except StopIteration:
            wb.close()
            return
        for vals in it:
            yield {h: ("" if v is None else str(v)) for h, v in zip(header, vals)}
        wb.close()
    else:
        raise ValueError(f"Unsupported file type: {path}")


def candidate_skus(aaia: str, part_number: str) -> list[str]:
    """Mirror link_titan_inventory_v2's SKU construction so we match ERP rows."""
    pn = (part_number or "").strip()
    cands = [f"{aaia}-{pn}", f"{aaia}{pn}", pn]
    # de-dup, preserve order, cap to product.sku length
    seen, out = set(), []
    for c in cands:
        c = c[:64]
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


async def apply_row(db, row: dict, dci_lookup: dict, *, create_new: bool,
                    skip_lifecycle: set[str], dry_run: bool, stats: dict) -> None:
    aaia = (row.get("BrandAAIAID") or "").strip()
    part_number = (row.get("PartNumber") or "").strip()
    if not aaia or not part_number:
        stats["bad_row"] += 1
        return

    lcsc = (row.get("LifeCycleStatusCode") or "").strip()
    stats["lifecycle"][lcsc] = stats["lifecycle"].get(lcsc, 0) + 1
    if lcsc in skip_lifecycle:
        stats["skip_lifecycle"] += 1
        return

    # Find existing product by any candidate SKU. Select only the columns we
    # read, so the script doesn't break if the live schema differs from the
    # model (e.g. has_no_fitment exists on newer revs but not older dev copies).
    cands = candidate_skus(aaia, part_number)
    existing = (await db.execute(
        select(Product.id, Product.brand_id, Product.upc, Product.weight_lb,
               Product.length_in, Product.width_in, Product.height_in)
        .where(Product.sku.in_(cands))
    )).first()

    if existing is None and not create_new:
        stats["no_match"] += 1
        return

    # --- description selection ---
    desc = {code_col: (row.get(code_col) or "").strip() for code_col in DESC_COLS}
    name_text = desc["Description"] or desc["ShortDescription"] or part_number
    marketing = desc["MarketingDescription"] or None
    extended = desc["ExtendedDescription"] or None
    upc_value = (row.get("ItemLevelGTIN") or "").strip()[:32] or None
    weight = _d(row.get("Weight"))
    length = _d(row.get("Length"))
    width = _d(row.get("Width"))
    height = _d(row.get("Height"))

    if existing is None:
        # create-new mode (post-ACES). brand row must exist; resolve/create it.
        prod_brand_id = await _resolve_brand(db, aaia, dci_lookup, dry_run)
        if prod_brand_id is None:
            stats["no_brand"] += 1
            return
        if dry_run:
            stats["would_create"] += 1
            return
        pid = await db.scalar(
            pg_insert(Product.__table__).values(
                sku=cands[0], brand_id=prod_brand_id, name=name_text[:500],
                description=marketing or extended, extended_description=extended,
                cta_mode=CTAMode.ADD_TO_CART, requires_shipping=True, taxable=True,
                is_hidden=False, is_for_sale=True, upc=upc_value, weight_lb=weight,
                length_in=length, width_in=width, height_in=height,
            ).returning(Product.__table__.c.id)
        )
        stats["created"] += 1
    else:
        pid = existing.id
        prod_brand_id = existing.brand_id
        stats["matched"] += 1
        if dry_run:
            stats["would_update"] += 1
            return
        vals: dict = {"name": name_text[:500]}
        if marketing:
            vals["description"] = marketing
        if extended:
            vals["extended_description"] = extended
        if existing.upc is None and upc_value:
            vals["upc"] = upc_value
        if existing.weight_lb is None and weight is not None:
            vals["weight_lb"] = weight
        if existing.length_in is None and length is not None:
            vals["length_in"] = length
        if existing.width_in is None and width is not None:
            vals["width_in"] = width
        if existing.height_in is None and height is not None:
            vals["height_in"] = height
        await db.execute(
            Product.__table__.update().where(Product.__table__.c.id == pid).values(**vals)
        )

    # --- descriptions: replace ONLY the codes we own, keep any others ---
    await db.execute(delete(ProductDescription).where(
        ProductDescription.product_id == pid,
        ProductDescription.description_code.in_(DESC_CODES),
    ))
    for col, code in DESC_COLS.items():
        txt = desc[col]
        if not txt:
            continue
        if code == "FEA":
            # features list is ";"-delimited -> one row per feature
            for i, feat in enumerate([f.strip() for f in txt.split(";") if f.strip()], 1):
                db.add(ProductDescription(product_id=pid, description_code="FEA",
                                          language_code="EN", sequence=i, text=feat))
        else:
            db.add(ProductDescription(product_id=pid, description_code=code,
                                      language_code="EN", sequence=1, text=txt))

    # --- pricing: replace this product's current pricing (PIES is the source) ---
    await db.execute(delete(ProductPricing).where(ProductPricing.product_id == pid))
    eff = _date(row.get("PriceEffectiveDate"))
    cur = (row.get("CurrencyCode") or "USD").strip()[:5] or "USD"
    for col, ptype in PRICE_COLS.items():
        val = _d(row.get(col))
        if val is None:
            continue
        db.add(ProductPricing(product_id=pid, price_type=ptype, price=val,
                              currency_code=cur, effective_date=eff, is_current=True))

    # --- images: additive (dedup by url); set primary only if none exists ---
    existing_urls = set((await db.execute(
        select(ProductImage.url).where(ProductImage.product_id == pid)
    )).scalars().all())
    has_primary = bool((await db.execute(
        select(ProductImage.id).where(ProductImage.product_id == pid,
                                      ProductImage.is_primary.is_(True))
    )).first())
    sort = len(existing_urls)
    for u in _split_urls(row.get(IMAGE_COLS_PRIMARY)):
        if u in existing_urls:
            continue
        db.add(ProductImage(product_id=pid, url=u, is_primary=not has_primary,
                            sort_order=0 if not has_primary else sort,
                            legacy_origin="aam-pies"))
        existing_urls.add(u); has_primary = True; sort += 1
        stats["images"] += 1
    for col in IMAGE_COLS_SECONDARY:
        for u in _split_urls(row.get(col)):
            if u in existing_urls:
                continue
            db.add(ProductImage(product_id=pid, url=u, is_primary=False,
                                sort_order=sort, legacy_origin="aam-pies"))
            existing_urls.add(u); sort += 1
            stats["images"] += 1

    # --- link pace_part (brand_id from the matched product) ---
    primary_image = next(iter(_split_urls(row.get(IMAGE_COLS_PRIMARY))), None)
    stmt = pg_insert(PacePart.__table__).values(
        brand_id=prod_brand_id, part_number=part_number, product_id=pid,
        primary_image_url=primary_image, short_description=name_text[:500],
    ).on_conflict_do_update(
        constraint="uq_pace_part_brand_pn",
        set_={"product_id": pid, "primary_image_url": primary_image,
              "short_description": name_text[:500]},
    )
    await db.execute(stmt)


async def _resolve_brand(db, aaia: str, dci_lookup: dict, dry_run: bool):
    from app.models import Brand
    bid = await db.scalar(select(Brand.id).where(Brand.aaia_code == aaia))
    if bid is not None:
        return bid
    name = dci_lookup.get(aaia)
    if not name:
        log.warning("  brand %s has no name (not in dci_codes, no DB row) — skipping create-new rows", aaia)
        return None
    if dry_run:
        return -1
    slug = name.lower().replace(" ", "-").replace("/", "-")[:200] or aaia.lower()
    b = Brand(name=name, slug=slug, aaia_code=aaia, is_active=True,
              is_featured=False, sort_order=1000)
    db.add(b)
    await db.flush()
    log.info("  created Brand id=%s name=%s aaia=%s", b.id, name, aaia)
    return b.id


async def process_file(db, path: Path, dci_lookup: dict, *, create_new: bool,
                       skip_lifecycle: set[str], dry_run: bool, limit: int | None) -> dict:
    m = re.search(r"_1158_([A-Z]{4})_USD", path.name)
    code = m.group(1) if m else "????"
    stats = {k: 0 for k in ("matched", "no_match", "created", "would_create",
                            "would_update", "images", "bad_row", "no_brand",
                            "skip_lifecycle")}
    stats["lifecycle"] = {}
    n = 0
    for row in iter_rows(path):
        await apply_row(db, row, dci_lookup, create_new=create_new,
                        skip_lifecycle=skip_lifecycle, dry_run=dry_run, stats=stats)
        n += 1
        if limit and n >= limit:
            break
        if not dry_run and n % 500 == 0:
            await db.commit()
            log.info("  %s: %d rows committed", code, n)
    if not dry_run:
        await db.commit()
    name = dci_lookup.get(code, "")
    log.info("%s %-28s rows=%d matched=%d no_match=%d created=%d would_upd=%d would_new=%d imgs=%d",
             code, name, n, stats["matched"], stats["no_match"], stats["created"],
             stats["would_update"], stats["would_create"], stats["images"])
    stats["_code"] = code
    stats["_rows"] = n
    return stats


async def run(files: list[Path], *, create_new: bool, skip_lifecycle: set[str],
              dry_run: bool, limit: int | None):
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    dci_lookup = load_dci_lookup()
    log.info("DCI lookup: %d codes | files: %d | mode: %s%s",
             len(dci_lookup), len(files),
             "DRY-RUN" if dry_run else "WRITE",
             " +create-new" if create_new else " (enrich-existing-only)")

    totals = {k: 0 for k in ("matched", "no_match", "created", "would_update",
                             "would_create", "images")}
    life: dict[str, int] = {}
    async with Session() as db:
        for path in files:
            s = await process_file(db, path, dci_lookup, create_new=create_new,
                                   skip_lifecycle=skip_lifecycle, dry_run=dry_run,
                                   limit=limit)
            for k in totals:
                totals[k] += s.get(k, 0)
            for lc, c in s["lifecycle"].items():
                life[lc] = life.get(lc, 0) + c
    await engine.dispose()

    log.info("=" * 70)
    log.info("TOTALS  matched=%d  no_match=%d  created=%d  would_update=%d  would_create=%d  images=%d",
             totals["matched"], totals["no_match"], totals["created"],
             totals["would_update"], totals["would_create"], totals["images"])
    log.info("LifeCycleStatusCode distribution: %s",
             dict(sorted(life.items(), key=lambda kv: -kv[1])))
    if not dry_run:
        log.info("NEXT: run app/scripts/refresh_catalog.sh (relink categories + reindex Typesense)")


def collect_files(args) -> list[Path]:
    paths: list[Path] = []
    for p in args.files:
        paths.append(Path(p))
    if args.dir:
        paths.extend(Path(p) for p in sorted(globmod.glob(str(Path(args.dir) / args.glob))))
    # keep only AWDA exports, de-dup
    seen, out = set(), []
    for p in paths:
        if p.exists() and re.search(r"_AWDA_export\.(csv|xlsx|xlsm)$", p.name, re.I):
            rp = str(p.resolve())
            if rp not in seen:
                seen.add(rp); out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*", help="AWDA export file path(s)")
    ap.add_argument("--dir", help="directory to scan")
    ap.add_argument("--glob", default="*_AWDA_export.*", help="glob within --dir")
    ap.add_argument("--create-new", action="store_true",
                    help="also INSERT products with no existing SKU match (post-ACES only)")
    ap.add_argument("--skip-lifecycle", default="",
                    help='comma-separated LifeCycleStatusCode values to skip, e.g. "8,9"')
    ap.add_argument("--dry-run", action="store_true", help="no writes; report what would change")
    ap.add_argument("--limit", type=int, help="cap rows per file (testing)")
    args = ap.parse_args()

    files = collect_files(args)
    if not files:
        log.error("No AWDA export files found. Pass paths or --dir.")
        return 1
    skip = {s.strip() for s in args.skip_lifecycle.split(",") if s.strip()}
    asyncio.run(run(files, create_new=args.create_new, skip_lifecycle=skip,
                    dry_run=args.dry_run, limit=args.limit))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    sys.exit(main())
