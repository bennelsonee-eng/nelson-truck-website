"""link_tte_inventory.py — link tte_inv_days CSV rows to website products.

Background:
  The website catalog uses PIES/AAIA brand-prefixed SKUs like 'GBKR-09-12006A'
  (where GBKR is Race Sport's AAIA code).  The legacy TigerTech MySQL system
  uses internal prod_code-prefixed SKUs like 'RSP09-12006A' (where RSP is
  TigerTech's brand code for the same brand).  These two namespaces don't
  match by string, but every brand row in our `brand` table carries BOTH the
  `aaia_code` and the `prod_code`, so we can translate.

Algorithm:
  For each row in tte_inv_days.csv (ourparts_num + prod_code + warehouse +
  onhand/available/gl_cost):
    1. Look up brand by prod_code (case-insensitive).  Skip if no match.
    2. Strip prod_code from the front of ourparts_num → supplier-part suffix.
    3. Construct candidate website SKU = '{brand.aaia_code}-{suffix}' (and a
       no-dash fallback '{brand.aaia_code}{suffix}').  Skip if neither hits.
    4. UPDATE product.tte_ourparts_num so future runs can short-circuit.
    5. UPSERT product_inventory(product_id, warehouse_id) with on_hand,
       available, gl_cost, last_synced_at.

Warehouses:
  The script assumes Warehouse rows exist for the codes referenced in the
  CSV (10, 11, 12, 13, 14, 96, 99).  Code 10 (Spokane HQ) is the bulk of
  TTE inventory.  This script will seed the standard 4-warehouse layout
  before importing if --seed-warehouses is passed; otherwise it errors on
  missing warehouse codes (so silent data loss is impossible).

Usage:
    cd /home/titan/titan-truck-website/app/backend
    .venv/bin/python ../scripts/link_tte_inventory.py \\
        --csv ../data/mysql_dumps/tte_inv_days.csv \\
        --seed-warehouses

Idempotent — re-running with the same CSV refreshes inventory + cost on the
existing rows.  Re-running with a fresher CSV updates everything.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import asyncpg


SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
DEFAULT_CSV = APP_DIR / "data" / "mysql_dumps" / "tte_inv_days.csv"

# Warehouse seed — same layout as scripts/import_initial_data.py.  TTE
# inventory mostly hits code 10 (Spokane HQ); other codes are present in
# the CSV but with single-digit row counts.
WAREHOUSE_SEED = [
    {"code": 10, "name": "Spokane HQ", "short_name": "SPO",
     "is_active": True, "emits_own_facs_file": True, "facs_route_label": "SPO",
     "address1": "605 N. Fancher Rd.", "city": "Spokane", "state": "WA", "zip": "99212"},
    {"code": 19, "name": "Boise", "short_name": "BOISE",
     "is_active": True, "emits_own_facs_file": True, "facs_route_label": "BOISE",
     "address1": "1445 W Commerce Ave.", "city": "Boise", "state": "ID", "zip": "83705"},
    {"code": 1, "name": "Portland (rolls into NELSON file)", "short_name": "PORTLAND",
     "is_active": True, "emits_own_facs_file": False, "facs_route_label": "NELSON"},
    {"code": 0, "name": "Nelson Truck Equipment (Kent + Portland combined)", "short_name": "NELSON",
     "is_active": True, "emits_own_facs_file": True, "facs_route_label": "NELSON"},
    # Codes 11-14, 96, 99 appear in TTE CSV with single-digit row counts.
    # Seed as generic so import doesn't drop them on the floor.
    {"code": 11, "name": "TTE Aux 11", "short_name": "TTE11",
     "is_active": True, "emits_own_facs_file": False, "facs_route_label": "SPO"},
    {"code": 12, "name": "TTE Aux 12", "short_name": "TTE12",
     "is_active": True, "emits_own_facs_file": False, "facs_route_label": "SPO"},
    {"code": 13, "name": "TTE Aux 13", "short_name": "TTE13",
     "is_active": True, "emits_own_facs_file": False, "facs_route_label": "SPO"},
    {"code": 14, "name": "TTE Aux 14", "short_name": "TTE14",
     "is_active": True, "emits_own_facs_file": False, "facs_route_label": "SPO"},
    {"code": 96, "name": "TTE In-Transit", "short_name": "TTE96",
     "is_active": True, "emits_own_facs_file": False, "facs_route_label": "SPO"},
    {"code": 99, "name": "TTE Special", "short_name": "TTE99",
     "is_active": True, "emits_own_facs_file": False, "facs_route_label": "SPO"},
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("link_tte")


def parse_int(val: str | None) -> int | None:
    if not val:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def parse_decimal(val: str | None) -> Decimal | None:
    if not val:
        return None
    try:
        return Decimal(val)
    except (InvalidOperation, TypeError, ValueError):
        return None


async def seed_warehouses(conn: asyncpg.Connection) -> None:
    log.info("Seeding warehouses…")
    for wh in WAREHOUSE_SEED:
        await conn.execute(
            """
            INSERT INTO warehouse (code, name, short_name, is_active,
                                   emits_own_facs_file, facs_route_label,
                                   address1, city, state, zip,
                                   created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), NOW())
            ON CONFLICT (code) DO UPDATE
            SET name = EXCLUDED.name,
                short_name = EXCLUDED.short_name,
                is_active = EXCLUDED.is_active,
                emits_own_facs_file = EXCLUDED.emits_own_facs_file,
                facs_route_label = EXCLUDED.facs_route_label,
                updated_at = NOW()
            """,
            wh["code"], wh["name"], wh["short_name"], wh["is_active"],
            wh["emits_own_facs_file"], wh["facs_route_label"],
            wh.get("address1"), wh.get("city"), wh.get("state"), wh.get("zip"),
        )
    rows = await conn.fetch("SELECT code, short_name FROM warehouse ORDER BY code")
    log.info("  %d warehouses present: %s", len(rows),
             ", ".join(f"{r['code']}:{r['short_name']}" for r in rows))


async def link(csv_path: Path, *, seed_wh: bool, dry_run: bool) -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])  # don't log creds
    conn = await asyncpg.connect(dsn)
    try:
        if seed_wh:
            await seed_warehouses(conn)

        # Build lookup tables once
        log.info("Building brand map (prod_code → brand_id, aaia_code)…")
        brand_rows = await conn.fetch(
            "SELECT id, prod_code, aaia_code, name FROM brand "
            "WHERE prod_code IS NOT NULL AND prod_code != ''"
        )
        # prod_code is sometimes lowercase / mixed-case; normalize to uppercase
        pc_to_brand = {r["prod_code"].upper(): r for r in brand_rows}
        log.info("  %d brands have prod_code", len(pc_to_brand))

        log.info("Building warehouse map (code → id)…")
        wh_rows = await conn.fetch("SELECT id, code FROM warehouse")
        wh_to_id = {r["code"]: r["id"] for r in wh_rows}
        log.info("  %d warehouses present", len(wh_to_id))

        log.info("Loading SKU index (this can take ~10s on a 300K-row product table)…")
        sku_rows = await conn.fetch(
            "SELECT id, brand_id, sku FROM product WHERE is_for_sale AND NOT is_hidden"
        )
        # (brand_id, sku-upper) → product_id  (sku-upper for case-insensitive match)
        skus_by_brand: dict[int, dict[str, int]] = defaultdict(dict)
        for r in sku_rows:
            skus_by_brand[r["brand_id"]][r["sku"].upper()] = r["id"]
        log.info("  %d products indexed across %d brands",
                 len(sku_rows), len(skus_by_brand))

        # Walk the CSV
        log.info("Reading %s…", csv_path)
        if not csv_path.exists():
            log.error("CSV not found: %s", csv_path)
            return

        stats = Counter()
        per_brand = Counter()
        unmatched_brands: Counter = Counter()
        # buffer of inventory upserts:  (product_id, wh_id) → row dict
        inv_rows: dict[tuple[int, int], dict] = {}
        # buffer of product.tte_ourparts_num updates:  product_id → ourparts_num
        prod_links: dict[int, str] = {}

        now = datetime.now(timezone.utc)
        with csv_path.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                stats["rows"] += 1
                ourparts = (row.get("ourparts_num") or "").strip()
                pc = (row.get("prod_code") or "").strip().upper()
                wh_code = parse_int(row.get("warehouse"))
                onhand = parse_int(row.get("onhand")) or 0
                available = parse_int(row.get("available"))
                gl_cost = parse_decimal(row.get("gl_cost"))

                if not ourparts or not pc or wh_code is None:
                    stats["skip_blank"] += 1
                    continue
                if wh_code not in wh_to_id:
                    stats["skip_no_warehouse"] += 1
                    continue

                brand = pc_to_brand.get(pc)
                if brand is None:
                    stats["skip_unknown_brand"] += 1
                    unmatched_brands[pc] += 1
                    continue

                aaia = (brand["aaia_code"] or "").strip().upper()
                brand_id = brand["id"]

                # Strip prod_code prefix from ourparts_num to get supplier suffix.
                # TigerTech doesn't use a dash between prefix and suffix, so a
                # plain startswith is correct.
                ou = ourparts.upper()
                if ou.startswith(pc):
                    suffix = ou[len(pc):]
                else:
                    # Some rows have the prod_code embedded weirdly (e.g. ourparts
                    # has its own prefix that doesn't match prod_code).  Try
                    # using the whole ourparts as the suffix as a last resort.
                    suffix = ou
                # Drop a leading dash if present (rare in TTE feed)
                suffix = suffix.lstrip("-").lstrip("_")

                # Candidate SKUs to try, in order
                candidates = []
                if aaia:
                    candidates.append(f"{aaia}-{suffix}")
                    candidates.append(f"{aaia}{suffix}")
                candidates.append(suffix)  # bare suffix (for brands w/o aaia_code)

                pid = None
                matched_sku = None
                bucket = skus_by_brand.get(brand_id, {})
                for cand in candidates:
                    pid = bucket.get(cand.upper())
                    if pid is not None:
                        matched_sku = cand
                        break

                if pid is None:
                    stats["unmatched_sku"] += 1
                    per_brand[(pc, "miss")] += 1
                    continue

                stats["matched"] += 1
                per_brand[(pc, "hit")] += 1
                prod_links[pid] = ourparts

                key = (pid, wh_to_id[wh_code])
                # Sum onhand across duplicate rows for the same (product,
                # warehouse) — TigerTech sometimes has split rows by serial
                # number for the same SKU.  Take MAX(available) and the cost
                # from the row with the highest onhand.
                prev = inv_rows.get(key)
                if prev is None:
                    inv_rows[key] = {
                        "product_id": pid,
                        "warehouse_id": wh_to_id[wh_code],
                        "on_hand": onhand,
                        "available": available,
                        "gl_cost": gl_cost,
                        "last_synced_at": now,
                    }
                else:
                    prev["on_hand"] += onhand
                    if available is not None:
                        prev["available"] = (prev.get("available") or 0) + available
                    if gl_cost is not None and (prev.get("gl_cost") is None or onhand >= 1):
                        prev["gl_cost"] = gl_cost

        # ----- Stats summary -----
        log.info("CSV walk done.")
        log.info("  Rows read:              %d", stats["rows"])
        log.info("  Matched to a product:   %d", stats["matched"])
        log.info("  Unique products linked: %d", len(prod_links))
        log.info("  Inventory upserts:      %d", len(inv_rows))
        log.info("  Skipped (blank):        %d", stats["skip_blank"])
        log.info("  Skipped (no warehouse): %d", stats["skip_no_warehouse"])
        log.info("  Skipped (unknown brand prod_code):  %d", stats["skip_unknown_brand"])
        log.info("  Unmatched SKU (brand known, SKU not): %d", stats["unmatched_sku"])

        if unmatched_brands:
            log.info("Top brand prod_codes with NO matching brand row (need brand.prod_code populated):")
            for pc, n in unmatched_brands.most_common(15):
                log.info("    %-10s %d rows", pc, n)

        # Per-brand hit-rate (top 20 by total rows)
        brand_totals: Counter = Counter()
        for (pc, kind), n in per_brand.items():
            brand_totals[pc] += n
        log.info("Per-brand match rate (top 20):")
        for pc, total in brand_totals.most_common(20):
            hits = per_brand.get((pc, "hit"), 0)
            misses = per_brand.get((pc, "miss"), 0)
            rate = (hits / total * 100.0) if total else 0.0
            log.info("    %-10s %d rows  hit=%d  miss=%d  (%.0f%%)", pc, total, hits, misses, rate)

        if dry_run:
            log.info("Dry-run — not writing to DB.")
            return

        # ----- Write phase -----
        log.info("Writing product.tte_ourparts_num (%d rows)…", len(prod_links))
        # Batched via UNNEST for speed on Hetzner Postgres
        async with conn.transaction():
            pids = list(prod_links.keys())
            ous = [prod_links[p] for p in pids]
            await conn.execute(
                """
                UPDATE product p
                SET tte_ourparts_num = u.ourparts_num,
                    updated_at = NOW()
                FROM (SELECT UNNEST($1::int[]) AS id, UNNEST($2::text[]) AS ourparts_num) u
                WHERE p.id = u.id
                """,
                pids, ous,
            )

        log.info("Upserting product_inventory (%d rows)…", len(inv_rows))
        rows_list = list(inv_rows.values())
        # Chunk to keep parameter list size sane
        async with conn.transaction():
            for i in range(0, len(rows_list), 1000):
                chunk = rows_list[i:i+1000]
                await conn.executemany(
                    """
                    INSERT INTO product_inventory
                        (product_id, warehouse_id, on_hand, available, gl_cost,
                         last_synced_at, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                    ON CONFLICT (product_id, warehouse_id) DO UPDATE
                    SET on_hand = EXCLUDED.on_hand,
                        available = EXCLUDED.available,
                        gl_cost = EXCLUDED.gl_cost,
                        last_synced_at = EXCLUDED.last_synced_at,
                        updated_at = NOW()
                    """,
                    [(r["product_id"], r["warehouse_id"], r["on_hand"],
                      r["available"], r["gl_cost"], r["last_synced_at"])
                     for r in chunk],
                )

        log.info("Done.  Verify with:")
        log.info("  SELECT b.name, p.sku, p.tte_ourparts_num, pi.on_hand, pi.gl_cost")
        log.info("    FROM product_inventory pi JOIN product p ON p.id=pi.product_id")
        log.info("    JOIN brand b ON b.id=p.brand_id ORDER BY pi.on_hand DESC LIMIT 20;")

    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV,
                    help="Path to tte_inv_days.csv (defaults to ../data/mysql_dumps/tte_inv_days.csv)")
    ap.add_argument("--seed-warehouses", action="store_true",
                    help="UPSERT the standard 10-warehouse seed before importing")
    ap.add_argument("--dry-run", action="store_true",
                    help="Walk the CSV + report stats, but don't write to DB")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    asyncio.run(link(args.csv, seed_wh=args.seed_warehouses, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
