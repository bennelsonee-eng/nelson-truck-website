"""reclassify_van_accessories.py — split the flat "Van Accessories" bucket
into product-type subcategories.

Background
----------
"Van Equipment > Van Accessories" had grown into a 1,595-product catch-all.
It's dominated by Legend Fleet Solutions van-interior product lines (DuraTherm
/ EconoLite wall, ceiling & door liners; StabiliGrip / AutoMat flooring;
TempShield insulation) plus Flatline Van Co. upfit hardware and Weatherguard
storage accessories. Customers couldn't drill down by what the part actually
is. Owner-approved 2026-06-09 ("recommended product-type split").

What this does
--------------
1. Creates 7 subcategories under Van Accessories (idempotent — reuses any that
   already exist by full_path):
       Wall Liners & Paneling
       Ceiling Liners
       Door Panels & Liners
       Floor Liners & Mats
       Thermal Insulation & Sound Deadening
       Steps & Running Boards
       Roof Racks & Ladders
2. Re-points the PRIMARY product_category row of each classifiable product
   from Van Accessories to the matching subcategory.
3. Moves shelving / cabinet / storage items into the EXISTING sibling
   category "Van Equipment > Van Shelving" (where they belong).
4. Leaves genuine misc accessories (VanFan, hardware kits, grab handles,
   lights, wheel-well covers, bare SKU-code rows) in Van Accessories.

Idempotent: only rows still mapped to Van Accessories are considered, so a
second run is a no-op. A backup CSV of every move is written before applying
so the change is fully reversible.

Usage
-----
    # dry run — prints the plan, writes nothing
    python app/scripts/reclassify_van_accessories.py

    # apply for real (writes backup CSV first)
    python app/scripts/reclassify_van_accessories.py --apply

DSN comes from $DATABASE_URL (the +asyncpg prefix is stripped automatically),
falling back to the local dev default.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("van_reclassify")

VAN_ACCESSORIES_PATH = "Van Equipment > Van Accessories"
VAN_SHELVING_PATH = "Van Equipment > Van Shelving"

# Subcategories to create under Van Accessories. (name, slug, description)
SUBCATS: list[tuple[str, str, str]] = [
    ("Wall Liners & Paneling", "van-wall-liners",
     "Wall liner kits and paneling for cargo vans — DuraTherm and EconoLite "
     "wall liners, KK Plus systems, and aluminum top-sill trim."),
    ("Ceiling Liners", "van-ceiling-liners",
     "Ceiling liner kits for cargo vans, including DuraTherm insulated ceiling "
     "liners."),
    ("Door Panels & Liners", "van-door-panels",
     "Rear- and side-door liner panels — DuraTherm and EconoLite door liners."),
    ("Floor Liners & Mats", "van-floor-liners",
     "Van flooring: StabiliGrip and AutoMat floor kits, EconoMat, decking "
     "panels, floor sills and thresholds."),
    ("Thermal Insulation & Sound Deadening", "van-thermal-insulation",
     "Standalone thermal insulation and sound-deadening kits — TempShield."),
    ("Steps & Running Boards", "van-steps",
     "Side steps, rear steps and running boards for cargo vans."),
    ("Roof Racks & Ladders", "van-roof-racks-ladders",
     "Roof rack bar kits, crossbars, decking and access ladders for cargo "
     "vans."),
]

# Bucket name that routes to the EXISTING Van Shelving category instead of a
# new subcategory.
SHELVING_BUCKET = "Shelving & Storage"


def classify(name: str, brand: str) -> str | None:
    """Return the target bucket for a Van Accessories product, or None to
    leave it in place. Order matters — first match wins. Keep this in sync
    with the bucket names in SUBCATS / SHELVING_BUCKET.
    """
    n = name.lower()
    has = lambda *ws: any(w in n for w in ws)

    # Lights are not liners — keep them out of Ceiling Liners.
    if has("light kit", "ceiling light", "motion sensor", "led ") or n.strip().endswith("light"):
        return None
    if has("stabiligrip", "automat", "economat", "floor mat", "bed mat",
           "floor liner", "flooring", "decking", "floor"):
        return "Floor Liners & Mats"
    if has("ceiling"):
        return "Ceiling Liners"
    if has("door liner", "doorliner", "door panel") or (
        has("door") and has("duratherm", "econolite", "insulated")
    ):
        return "Door Panels & Liners"
    # Wall liners win over the generic "insulated" keyword: a DuraTherm
    # INSULATED Wall Liner is a wall liner, not standalone insulation.
    # "Top Sill" = aluminum trim that frames wall/ceiling liner panels.
    if has("wall liner", "wallliner", "wall panel", "econolite", "kk plus",
           " kk ", "duratherm", "partition liner", "top sill") or has("wall"):
        return "Wall Liners & Paneling"
    # Reserve Thermal for the dedicated insulation / sound-deadening lines.
    if has("tempshield", "sound", "deaden", "acoustic") or (has("insulat") and "liner" not in n):
        return "Thermal Insulation & Sound Deadening"
    if has("side step", "running board", "step well") or n.strip().endswith(("steps", "step")):
        return "Steps & Running Boards"
    if has("roof rack", "ladder", "roof bar", "bar kit for roof", "high bar",
           "crossbar", "cross bar", "cross rail", "roof tray", "load bar"):
        return "Roof Racks & Ladders"
    if has("shelf", "shelv", "cabinet", "drawer", "divider", "parts box",
           "tool organizer", "organizer", "locker", "work top", "bin ", "tray"):
        return SHELVING_BUCKET
    # Remaining Weatherguard in this bucket are van-storage accessories.
    if brand == "Weatherguard":
        return SHELVING_BUCKET
    return None


async def ensure_subcategory(conn, parent_id: int, parent_path: str,
                             parent_depth: int, name: str, slug: str,
                             description: str) -> int:
    full_path = f"{parent_path} > {name}"
    existing = await conn.fetchval("SELECT id FROM category WHERE full_path = $1", full_path)
    if existing:
        await conn.execute(
            "UPDATE category SET description = $1, updated_at = NOW() WHERE id = $2",
            description, existing,
        )
        log.info("Subcategory exists: %s (id=%d)", full_path, existing)
        return existing
    new_id = await conn.fetchval(
        """
        INSERT INTO category (name, slug, parent_id, full_path, depth,
                              description, sort_order, is_featured, is_active,
                              created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, 100, FALSE, TRUE, NOW(), NOW())
        RETURNING id
        """,
        name, slug, parent_id, full_path, parent_depth + 1, description,
    )
    log.info("Created subcategory: %s (id=%d)", full_path, new_id)
    return new_id


def resolve_dsn() -> str:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    return dsn


async def main(apply: bool) -> None:
    conn = await asyncpg.connect(resolve_dsn())
    try:
        va = await conn.fetchrow(
            "SELECT id, full_path, depth FROM category WHERE full_path = $1",
            VAN_ACCESSORIES_PATH,
        )
        if va is None:
            log.error("Category not found: %s — aborting.", VAN_ACCESSORIES_PATH)
            return
        shelving_id = await conn.fetchval(
            "SELECT id FROM category WHERE full_path = $1", VAN_SHELVING_PATH
        )
        if shelving_id is None:
            log.error("Category not found: %s — aborting.", VAN_SHELVING_PATH)
            return

        va_id = va["id"]

        # 1. Ensure subcategories exist (created even in dry-run? no — only on apply).
        bucket_to_id: dict[str, int] = {}
        if apply:
            for name, slug, desc in SUBCATS:
                bucket_to_id[name] = await ensure_subcategory(
                    conn, va_id, va["full_path"], va["depth"], name, slug, desc
                )
        else:
            # Dry run: reuse any that already exist; mark the rest as NEW.
            for name, slug, desc in SUBCATS:
                fp = f"{va['full_path']} > {name}"
                bucket_to_id[name] = await conn.fetchval(
                    "SELECT id FROM category WHERE full_path = $1", fp
                )
        bucket_to_id[SHELVING_BUCKET] = shelving_id

        # 2. Classify every product currently primary-mapped to Van Accessories.
        rows = await conn.fetch(
            """
            SELECT p.id, p.name, b.name AS brand
            FROM product_category pc
            JOIN product p ON p.id = pc.product_id
            JOIN brand b ON b.id = p.brand_id
            WHERE pc.category_id = $1 AND pc.is_primary
            ORDER BY p.name
            """,
            va_id,
        )
        moves: list[tuple[int, int, str, str]] = []  # (product_id, dest_cat_id, bucket, name)
        counts: Counter = Counter()
        for r in rows:
            bucket = classify(r["name"], r["brand"])
            if bucket is None:
                counts["(stays in Van Accessories)"] += 1
                continue
            dest = bucket_to_id.get(bucket)
            counts[bucket] += 1
            if dest is not None:  # None only in dry-run when subcat not yet created
                moves.append((r["id"], dest, bucket, r["name"]))

        # 3. Report.
        log.info("Van Accessories (id=%d): %d primary products", va_id, len(rows))
        for bucket, _slug, _desc in SUBCATS:
            log.info("  %5d  ->  %s", counts.get(bucket, 0), bucket)
        log.info("  %5d  ->  %s (existing Van Shelving id=%d)",
                 counts.get(SHELVING_BUCKET, 0), SHELVING_BUCKET, shelving_id)
        log.info("  %5d  ->  (stays in Van Accessories)",
                 counts.get("(stays in Van Accessories)", 0))

        if not apply:
            log.info("DRY RUN — no changes written. Re-run with --apply to commit.")
            return

        # 4. Backup CSV of every move (reversal path).
        backups_dir = Path(__file__).resolve().parents[2] / "backups" / "van_reclassify"
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backups_dir / f"van_accessories_moves_{stamp}.csv"
        with backup_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["product_id", "from_category_id", "to_category_id", "bucket", "product_name"])
            for pid, dest, bucket, name in moves:
                w.writerow([pid, va_id, dest, bucket, name])
        log.info("Backup written: %s (%d moves)", backup_path, len(moves))

        # 5. Apply the moves in one transaction.
        async with conn.transaction():
            applied = 0
            for pid, dest, _bucket, _name in moves:
                res = await conn.execute(
                    """
                    UPDATE product_category
                    SET category_id = $1
                    WHERE product_id = $2 AND category_id = $3 AND is_primary
                    """,
                    dest, pid, va_id,
                )
                # res like "UPDATE 1"
                applied += int(res.split()[-1]) if res.split()[-1].isdigit() else 0
        log.info("Applied %d primary-category moves.", applied)
        log.info("Done. Reindex Typesense if search category facets need to reflect this.")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Split Van Accessories into product-type subcategories.")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry run).")
    args = ap.parse_args()
    asyncio.run(main(args.apply))
