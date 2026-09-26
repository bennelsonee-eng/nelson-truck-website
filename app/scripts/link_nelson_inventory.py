"""link_titan_inventory_v2.py — link TTE + NTE inventory to website products
                                  via parts_master.parts_num + brand.aaia_code.

Supersedes link_tte_inventory.py (which used a brittle prefix-strip heuristic
on ourparts_num).  This version uses the proper supplier-part-number column
from the parts master table — same identifier the catalog SKU is built from.

Algorithm:
  For each inv_days row (ourparts_num, prod_code, warehouse, onhand, …):
    1. Look up the parts_master row by ourparts_num.  Skip if missing.
    2. From it, take supplier `parts_num` + internal `prod_code`.
    3. Find the brand by prod_code → get aaia_code + brand_id.
    4. Construct candidate website SKUs:
         '{aaia_code}-{parts_num}'
         '{aaia_code}{parts_num}'         (no dash)
         '{parts_num}'                    (bare — fallback)
       Try each.  First hit wins.
    5. UPSERT product_inventory + UPDATE product.tte_ourparts_num.
    6. Track unmatched rows for the "in-stock-but-not-on-website" report.

Also imports per-product P1–P5 list/retail/cost prices into ProductPrice
since the contract pricing engine consults those.  TTE-side prices win for
products matched via tte_parts_master; NTE-side fills in the rest.

Warehouses included by default:
    10 — Spokane TTE  (from tte_inv_days)
     1 — Portland Nelson  (from nte_inv_days)
     2 — Kent Nelson      (from nte_inv_days)

Run from app/backend with venv activated:
    DATABASE_URL=postgresql://postgres:titan2026@localhost:5433/titan_web \
      .venv/bin/python ../scripts/link_titan_inventory_v2.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import asyncpg


SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
DUMPS_DIR = APP_DIR / "data" / "mysql_dumps"

# Put the backend package on the path so the post-load hook can import
# app.database / app.services (kit recompute + search reindex) even when this
# script is run standalone (e.g. by the inventory-sync timer or by hand).
_BACKEND_DIR = APP_DIR / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

TTE_PARTS_MASTER = DUMPS_DIR / "tte_parts_master.csv"
NTE_PARTS_MASTER = DUMPS_DIR / "nte_parts_master.csv"
TTE_INV_DAYS = DUMPS_DIR / "tte_inv_days.csv"
NTE_INV_DAYS = DUMPS_DIR / "nte_inv_days.csv"

# Default warehouses we accept stock from.  10 = Spokane TTE,
# 1 = Portland NTE, 2 = Kent NTE.  Customer-tier visibility rules
# (jobber vs retail per warehouse) are layered on top — out of scope here.
PROD_CODE_ALIASES = {"MYS": "MYP"}   # ERP prod code -> the brand row's prod code
TARGET_WAREHOUSES = {10, 1, 2}  # same as Titan: Spokane(10) + Portland(1) + Kent(2), loads both tte+nte_inv_days

REPORT_PATH = SCRIPT_DIR.parent / "data" / "reports" / "tte_inventory_missing_from_website.csv"


# 10-warehouse seed — adds code 2 (Kent) which the existing seed omitted.
WAREHOUSE_SEED = [
    {"code": 10, "name": "Spokane HQ", "short_name": "SPO",
     "is_active": True, "emits_own_facs_file": True, "facs_route_label": "SPO",
     "address1": "605 N. Fancher Rd.", "city": "Spokane", "state": "WA", "zip": "99212"},
    {"code": 19, "name": "Boise", "short_name": "BOISE",
     "is_active": True, "emits_own_facs_file": True, "facs_route_label": "BOISE",
     "address1": "1445 W Commerce Ave.", "city": "Boise", "state": "ID", "zip": "83705"},
    {"code": 1, "name": "Portland (Nelson Truck)", "short_name": "PORTLAND",
     "is_active": True, "emits_own_facs_file": False, "facs_route_label": "NELSON",
     "city": "Portland", "state": "OR"},
    {"code": 2, "name": "Kent (Nelson Truck)", "short_name": "KENT",
     "is_active": True, "emits_own_facs_file": True, "facs_route_label": "NELSON",
     "city": "Kent", "state": "WA"},
    {"code": 0, "name": "Nelson combined (legacy)", "short_name": "NELSON-LEGACY",
     "is_active": False, "emits_own_facs_file": False, "facs_route_label": "NELSON"},
    # TTE aux locations — small counts, kept for completeness
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
log = logging.getLogger("link_v2")


# --------------------------------------------------------------------------- #
# CSV helpers
# --------------------------------------------------------------------------- #


def parse_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def parse_decimal(val: Any) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        d = Decimal(val)
        return d if d.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def load_master(path: Path) -> dict[str, dict]:
    """ourparts_num.upper() → {parts_num, prod_code, P1..P5}"""
    out: dict[str, dict] = {}
    if not path.exists():
        log.warning("Missing %s — skipping", path.name)
        return out
    log.info("Loading %s…", path.name)
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        skipped = 0
        for r in reader:
            ou = (r.get("ourparts_num") or "").strip().upper()
            if not ou or ou in ("#", "NUMBER"):
                skipped += 1
                continue
            pn = (r.get("parts_num") or "").strip()
            pc = (r.get("prod_code") or "").strip().upper()
            # 171 part numbers appear twice in the master, one of them a
            # retired row ("USE PART #HRPPRYBAR 4", status Z) with another
            # part number and older prices. Keep the active row, then the
            # higher list price -- the ERP importer's rule (2026-09-26).
            status = (r.get("status") or "").strip().upper()
            rank = (status == "A", parse_decimal(r.get("P2")) or Decimal(0))
            if ou in out and out[ou]["_rank"] >= rank:
                continue
            out[ou] = {
                "_rank": rank,
                "parts_num": pn,
                "parts_num_upper": pn.upper(),
                "prod_code": pc,
                "P1": parse_decimal(r.get("P1")),
                "P2": parse_decimal(r.get("P2")),
                "P3": parse_decimal(r.get("P3")),
                "P4": parse_decimal(r.get("P4")),
                "P5": parse_decimal(r.get("P5")),
            }
    log.info("  %d entries (skipped %d header/placeholders)", len(out), skipped)
    return out


# --------------------------------------------------------------------------- #
# Warehouse seed
# --------------------------------------------------------------------------- #


async def seed_warehouses(conn: asyncpg.Connection) -> None:
    log.info("Seeding warehouses (adds code 2 = Kent if missing)…")
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
                city = EXCLUDED.city,
                state = EXCLUDED.state,
                updated_at = NOW()
            """,
            wh["code"], wh["name"], wh["short_name"], wh["is_active"],
            wh["emits_own_facs_file"], wh["facs_route_label"],
            wh.get("address1"), wh.get("city"), wh.get("state"), wh.get("zip"),
        )


# --------------------------------------------------------------------------- #
# Inventory file walker
# --------------------------------------------------------------------------- #


def walk_inv_days(
    path: Path,
    master: dict,
    *,
    target_warehouses: set[int],
    brand_pc_map: dict,
    brand_partnum_map: dict,
    sku_map: dict,
    source_tag: str,
    stats: Counter,
    per_brand: Counter,
    unmatched_brands: Counter,
    missing_buckets: dict,
) -> tuple[dict, dict]:
    """Walk one inv_days file.  Returns (inventory_dict, product_links_dict).

    inventory_dict   : (product_id, warehouse_code) → aggregated row
    product_links    : product_id → ourparts_num (for tte_ourparts_num column)
    """
    inventory: dict[tuple[int, int], dict] = {}
    product_links: dict[int, str] = {}
    now = datetime.now(timezone.utc)

    if not path.exists():
        log.warning("Missing %s — skipping", path.name)
        return inventory, product_links

    log.info("Walking %s (source=%s)…", path.name, source_tag)
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            stats[f"{source_tag}_rows"] += 1
            ourparts = (row.get("ourparts_num") or "").strip().upper()
            pc = (row.get("prod_code") or "").strip().upper()
            wh_code = parse_int(row.get("warehouse"))
            if not ourparts or wh_code is None:
                stats[f"{source_tag}_skip_blank"] += 1
                continue
            if wh_code not in target_warehouses:
                stats[f"{source_tag}_skip_wh"] += 1
                continue

            onhand = parse_int(row.get("onhand")) or 0
            available = parse_int(row.get("available"))
            gl_cost = parse_decimal(row.get("gl_cost"))

            # Look up parts master entry
            m = master.get(ourparts)
            if m is None:
                stats[f"{source_tag}_no_master"] += 1
                missing_buckets["no_master"][pc] += 1
                continue

            mpc = m["prod_code"] or pc
            pn_upper = m["parts_num_upper"]
            if not mpc or not pn_upper:
                stats[f"{source_tag}_master_blank"] += 1
                continue

            brand = brand_pc_map.get(mpc)
            if brand is None:
                stats[f"{source_tag}_unknown_brand"] += 1
                unmatched_brands[mpc] += 1
                missing_buckets["no_brand"].setdefault(mpc, []).append({
                    "ourparts_num": ourparts,
                    "parts_num": m["parts_num"],
                    "warehouse": wh_code,
                    "onhand": onhand,
                })
                continue

            bid = brand["id"]

            # Match candidates: parts_num exact, parts_num no-dash, parts_num strip-leading-zeros
            candidates = [pn_upper]
            if "-" in pn_upper:
                candidates.append(pn_upper.replace("-", ""))
            stripped_zeros = pn_upper.lstrip("0")
            if stripped_zeros and stripped_zeros != pn_upper:
                candidates.append(stripped_zeros)
            # Some master rows repeat the prod code inside parts_num
            # ("KNP6108D-S" rather than "6108D-S"), which hid stock on
            # products keyed the ordinary way (found 2026-09-24).
            if mpc and pn_upper.startswith(mpc.upper()) and len(pn_upper) > len(mpc):
                candidates.append(pn_upper[len(mpc):].lstrip("-"))
            # Last in line: the ourparts_num minus its prod code, for master
            # rows whose parts_num isn't a part number at all ("NOT SOLD THIS
            # WAY" on 35 Meyer parts, "M84415-B" for MAXXM84415) (2026-09-25).
            if mpc and ourparts.startswith(mpc.upper()) and len(ourparts) > len(mpc):
                tail = ourparts[len(mpc):].lstrip("-")
                if tail and tail not in candidates:
                    candidates.append(tail)

            pid = None
            for cand in candidates:
                pid = brand_partnum_map.get((bid, cand))
                if pid:
                    break

            # Last-resort: try by full SKU '{aaia}-{partnum}' / '{aaia}{partnum}'
            if pid is None and brand.get("aaia_code"):
                aaia = brand["aaia_code"].upper()
                for cand in candidates:
                    pid = sku_map.get(f"{aaia}-{cand}") or sku_map.get(f"{aaia}{cand}")
                    if pid:
                        break

            # …and the ERP-sourced shape, where the SKU is the ourparts_num
            # itself ('TOMCVL-AA-1330EF71') or prod_code + parts_num. Without
            # this, whole lines sat on the site reading "not in stock" while
            # the stock was on the floor — every Tommy Gate liftgate, 54
            # Western parts and 208 products in all (found 2026-09-24).
            if pid is None:
                pid = sku_map.get(ourparts)
            if pid is None and mpc:
                pc_upper = mpc.upper()
                for cand in candidates:
                    pid = sku_map.get(f"{pc_upper}{cand}") or sku_map.get(f"{pc_upper}-{cand}")
                    if pid:
                        break

            if pid is None:
                stats[f"{source_tag}_unmatched_sku"] += 1
                per_brand[(mpc, "miss")] += 1
                # Track unmatched-but-brand-known for the missing-products report
                missing_buckets["unmatched_sku"].setdefault(mpc, []).append({
                    "ourparts_num": ourparts,
                    "parts_num": m["parts_num"],
                    "warehouse": wh_code,
                    "onhand": onhand,
                    "available": available,
                    "gl_cost": float(gl_cost) if gl_cost else None,
                    "brand_name": brand.get("name"),
                    "brand_id": bid,
                })
                continue

            stats[f"{source_tag}_matched"] += 1
            per_brand[(mpc, "hit")] += 1

            # Track ourparts_num for the matched product.  TTE entries go
            # to product.tte_ourparts_num.  NTE entries are tracked locally
            # for the price-import fallback below.
            product_links[pid] = row.get("ourparts_num") or ourparts

            key = (pid, wh_code)
            prev = inventory.get(key)
            if prev is None:
                inventory[key] = {
                    "product_id": pid,
                    "warehouse_code": wh_code,
                    "on_hand": onhand,
                    "available": available if available is not None else onhand,
                    "gl_cost": gl_cost,
                    "last_synced_at": now,
                }
            else:
                prev["on_hand"] += onhand
                prev["available"] = (prev.get("available") or 0) + (available if available is not None else onhand)
                if gl_cost is not None:
                    prev["gl_cost"] = gl_cost

    return inventory, product_links


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


async def main(dry_run: bool, seed_wh: bool, write_prices: bool, zero_out: bool = True) -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        if seed_wh:
            await seed_warehouses(conn)

        # --- Build lookup tables -----------------------------------------
        log.info("Building brand map (prod_code → id + aaia_code)…")
        brand_rows = await conn.fetch(
            "SELECT id, prod_code, aaia_code, name FROM brand "
            "WHERE prod_code IS NOT NULL AND prod_code != ''"
        )
        brand_pc_map: dict[str, dict] = {}
        for r in brand_rows:
            brand_pc_map[r["prod_code"].upper()] = {
                "id": r["id"],
                "aaia_code": r["aaia_code"],
                "name": r["name"],
            }
        # One maker, two ERP prod codes: the ERP files Meyer spreaders under
        # MYS and Meyer plows under MYP, but shoppers see a single Meyer brand
        # (same part-number space, so the SKU forms can't collide).
        for alias, target in PROD_CODE_ALIASES.items():
            if target in brand_pc_map and alias not in brand_pc_map:
                brand_pc_map[alias] = brand_pc_map[target]
        log.info("  %d brands have prod_code", len(brand_pc_map))
        brand_aaia_by_id = {r["id"]: (r["aaia_code"] or "").upper() for r in brand_rows}

        log.info("Building warehouse map (code → id)…")
        wh_rows = await conn.fetch("SELECT id, code FROM warehouse")
        wh_to_id = {r["code"]: r["id"] for r in wh_rows}
        for wc in TARGET_WAREHOUSES:
            if wc not in wh_to_id:
                log.error("Target warehouse %d not seeded — run with --seed-warehouses", wc)
                return

        log.info("Indexing products by SKU + by (brand_id, parts_num)…")
        # Hidden products are indexed too (visible ones listed last so they
        # win a shared key): leaving them out meant stock could never reach a
        # hidden page, so it could never be seen to need showing — 16 Buyers
        # and 2 SnowDogg parts sat hidden with stock on the floor (2026-09-25).
        prod_rows = await conn.fetch(
            "SELECT id, brand_id, sku, is_hidden FROM product WHERE is_for_sale"
            " ORDER BY is_hidden DESC, id"
        )
        sku_map: dict[str, int] = {}
        brand_partnum_map: dict[tuple[int, str], int] = {}
        for p in prod_rows:
            sku_u = p["sku"].upper()
            sku_map[sku_u] = p["id"]
            aaia = brand_aaia_by_id.get(p["brand_id"], "")
            if aaia and sku_u.startswith(aaia + "-"):
                pn = sku_u[len(aaia) + 1:]
            elif aaia and sku_u.startswith(aaia):
                pn = sku_u[len(aaia):]
            else:
                pn = sku_u
            brand_partnum_map[(p["brand_id"], pn)] = p["id"]
            if "-" in pn:
                brand_partnum_map[(p["brand_id"], pn.replace("-", ""))] = p["id"]
            # SKUs with a space ('BGZX-OE38-37 CHARC') against a master
            # parts_num without one ('OE38-37CHARC').
            if " " in pn:
                brand_partnum_map[(p["brand_id"], pn.replace(" ", ""))] = p["id"]
                brand_partnum_map[(p["brand_id"], pn.replace(" ", "").replace("-", ""))] = p["id"]
        hidden_pids = {p["id"] for p in prod_rows if p["is_hidden"]}
        log.info("  %d products indexed (%d hidden), %d (brand,parts_num) keys",
                 len(sku_map), len(hidden_pids), len(brand_partnum_map))

        # --- Load parts masters ------------------------------------------
        tte_master = load_master(TTE_PARTS_MASTER)
        nte_master = load_master(NTE_PARTS_MASTER)

        # --- Walk inv_days files -----------------------------------------
        stats: Counter = Counter()
        per_brand: Counter = Counter()
        unmatched_brands: Counter = Counter()
        missing_buckets: dict = {
            "no_master": Counter(),     # prod_code → count
            "no_brand": {},             # prod_code → list of dicts
            "unmatched_sku": {},        # prod_code → list of dicts
        }

        tte_inv, tte_links = walk_inv_days(
            TTE_INV_DAYS, tte_master,
            target_warehouses=TARGET_WAREHOUSES,
            brand_pc_map=brand_pc_map,
            brand_partnum_map=brand_partnum_map,
            sku_map=sku_map,
            source_tag="tte",
            stats=stats, per_brand=per_brand,
            unmatched_brands=unmatched_brands,
            missing_buckets=missing_buckets,
        )
        nte_inv, nte_links = walk_inv_days(
            NTE_INV_DAYS, nte_master,
            target_warehouses=TARGET_WAREHOUSES,
            brand_pc_map=brand_pc_map,
            brand_partnum_map=brand_partnum_map,
            sku_map=sku_map,
            source_tag="nte",
            stats=stats, per_brand=per_brand,
            unmatched_brands=unmatched_brands,
            missing_buckets=missing_buckets,
        )

        # Merge: TTE wins on overlap (it's the Titan website primary)
        inventory: dict[tuple[int, int], dict] = {**nte_inv, **tte_inv}

        # --- Prepare price upserts ---------------------------------------
        # Nelson's prices come from NELSON's parts master (nte), never Titan's:
        # the two companies price the same part differently (Ben, 2026-09-25;
        # IMS200 becomes the source once that feed is back). Only rows whose
        # P1-P5 actually changed are written. A 0.00 tier is stored as NULL:
        # a logged-in retail customer is charged the stored tier verbatim, so
        # 0.00 sold at $0.00 (24 live products found 2026-09-25). A list price
        # below cost is taken for a data error and skipped.
        price_rows: dict[int, dict] = {}
        if write_prices:
            def _tier(v):
                return v if v is not None and v > 0 else None

            def _row_from_master(m: dict | None) -> dict | None:
                if not m:
                    return None
                row = {
                    "suggested_retail_price": _tier(m["P1"]),   # MSRP
                    "retail_price": _tier(m["P2"]),             # List
                    "jobber_price": _tier(m["P3"]),
                    "dealer_price": _tier(m["P4"]),
                    "cost": _tier(m["P5"]),
                }
                return row if any(v is not None for v in row.values()) else None

            candidates: dict[int, dict] = {}
            below_cost = 0
            for pid, ou in {**tte_links, **nte_links}.items():
                pr = _row_from_master(nte_master.get(ou.upper()))
                if not pr:
                    continue
                if pr["retail_price"] and pr["cost"] and pr["retail_price"] < pr["cost"]:
                    below_cost += 1
                    continue
                candidates[pid] = pr
            current = {r["product_id"]: r for r in await conn.fetch(
                "SELECT product_id, suggested_retail_price, retail_price, jobber_price, "
                "dealer_price, cost FROM product_price WHERE product_id = ANY($1::int[])",
                list(candidates))}
            cols = ("suggested_retail_price", "retail_price", "jobber_price", "dealer_price", "cost")
            up = down = 0
            for pid, pr in candidates.items():
                cur = current.get(pid)
                if cur and all(cur[c] == pr[c] for c in cols):
                    continue
                price_rows[pid] = pr
                old, new_ = (cur["retail_price"] if cur else None), pr["retail_price"]
                if old and new_:
                    up += new_ > old
                    down += new_ < old
            log.info("Prices (Nelson master): %d products checked, %d changed (list up %d, down %d), "
                     "%d skipped with list below cost", len(candidates), len(price_rows), up, down, below_cost)

        # --- Stats summary -----------------------------------------------
        total_rows = stats["tte_rows"] + stats["nte_rows"]
        total_matched = stats["tte_matched"] + stats["nte_matched"]
        log.info("---- Summary ----")
        log.info("TTE rows: %d (matched=%d, unknown_brand=%d, no_master=%d, "
                 "unmatched_sku=%d, skip_wh=%d, skip_blank=%d)",
                 stats["tte_rows"], stats["tte_matched"], stats["tte_unknown_brand"],
                 stats["tte_no_master"], stats["tte_unmatched_sku"],
                 stats["tte_skip_wh"], stats["tte_skip_blank"])
        log.info("NTE rows: %d (matched=%d, unknown_brand=%d, no_master=%d, "
                 "unmatched_sku=%d, skip_wh=%d, skip_blank=%d)",
                 stats["nte_rows"], stats["nte_matched"], stats["nte_unknown_brand"],
                 stats["nte_no_master"], stats["nte_unmatched_sku"],
                 stats["nte_skip_wh"], stats["nte_skip_blank"])
        log.info("Combined inventory rows to upsert: %d", len(inventory))
        log.info("Unique products with stock: %d", len({k[0] for k in inventory.keys()}))
        hidden_stocked = sorted({pid for (pid, _), r in inventory.items()
                                 if pid in hidden_pids and (r.get("on_hand") or 0) > 0})
        if hidden_stocked:
            log.warning("%d HIDDEN products have stock on hand (not shown on the site): %s",
                        len(hidden_stocked), hidden_stocked[:20])

        # Per-brand top 20
        brand_totals: Counter = Counter()
        for (pc, kind), n in per_brand.items():
            brand_totals[pc] += n
        log.info("Top-20 brand match rates (TTE+NTE combined):")
        for pc, total in brand_totals.most_common(20):
            hits = per_brand.get((pc, "hit"), 0)
            rate = (hits / total * 100.0) if total else 0.0
            log.info("    %-10s %d rows  hit=%d  (%.0f%%)", pc, total, hits, rate)

        # --- Missing-products report -------------------------------------
        # The user wants this: items in stock on TTE side but NOT on website,
        # prioritized by brands that have OTHER products on the website.
        report_rows: list[dict] = []
        for pc, entries in missing_buckets["unmatched_sku"].items():
            brand = brand_pc_map.get(pc, {})
            for e in entries:
                report_rows.append({
                    "prod_code": pc,
                    "brand_name": e.get("brand_name") or "(unknown)",
                    "brand_on_website": "YES",  # brand row exists by definition
                    "ourparts_num": e["ourparts_num"],
                    "parts_num": e["parts_num"],
                    "warehouse": e["warehouse"],
                    "onhand": e["onhand"],
                    "available": e.get("available"),
                    "gl_cost": e.get("gl_cost"),
                    "reason": "brand_known_sku_not_in_catalog",
                })
        for pc, entries in missing_buckets["no_brand"].items():
            for e in entries:
                report_rows.append({
                    "prod_code": pc,
                    "brand_name": "(no brand row)",
                    "brand_on_website": "NO",
                    "ourparts_num": e["ourparts_num"],
                    "parts_num": e["parts_num"],
                    "warehouse": e["warehouse"],
                    "onhand": e["onhand"],
                    "available": None,
                    "gl_cost": None,
                    "reason": "brand_prod_code_unknown_to_website",
                })
        # Sort: brand-on-website first, then by onhand desc
        report_rows.sort(key=lambda r: (r["brand_on_website"] != "YES", -(r["onhand"] or 0)))

        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        if report_rows:
            with REPORT_PATH.open("w", encoding="utf-8", newline="") as fp:
                w = csv.DictWriter(fp, fieldnames=list(report_rows[0].keys()))
                w.writeheader()
                w.writerows(report_rows)
            log.info("Wrote missing-products report: %s (%d rows)", REPORT_PATH, len(report_rows))

        if dry_run:
            log.info("Dry-run — no DB writes.")
            return

        # --- Write phase -------------------------------------------------
        # Clear stale tte_ourparts_num that aren't in this round (so re-runs
        # don't carry forward false matches from the previous prefix-strip).
        if tte_links:
            log.info("Updating product.tte_ourparts_num for %d products…", len(tte_links))
            async with conn.transaction():
                pids = list(tte_links.keys())
                ous = [tte_links[p] for p in pids]
                await conn.execute(
                    """
                    UPDATE product p
                    SET tte_ourparts_num = u.ou,
                        updated_at = NOW()
                    FROM (SELECT UNNEST($1::int[]) AS id, UNNEST($2::text[]) AS ou) u
                    WHERE p.id = u.id
                    """,
                    pids, ous,
                )

        # Resolve warehouse code → id at write time
        log.info("Upserting %d product_inventory rows…", len(inventory))
        async with conn.transaction():
            rows_list = list(inventory.values())
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
                    [(r["product_id"], wh_to_id[r["warehouse_code"]],
                      r["on_hand"], r["available"], r["gl_cost"], r["last_synced_at"])
                     for r in chunk],
                )

        # Zero-out: the feed is authoritative — any product NOT present for a
        # target warehouse this load has 0 on hand there (sold out / pulled from
        # the feed). GUARDED against an empty/partial feed (which would wipe all
        # stock): a warehouse whose present-count is implausibly low is skipped.
        # Kit (package) products are virtual — stock is derived, never in the
        # feed — so they're always excluded.
        zeroed_pids: set[int] = set()
        if not dry_run and zero_out:
            present_by_wh: dict[int, set[int]] = defaultdict(set)
            for r in inventory.values():
                wid = wh_to_id.get(r["warehouse_code"])
                if wid is not None:
                    present_by_wh[wid].add(r["product_id"])
            kit_pids = [r["product_id"] for r in await conn.fetch(
                "SELECT product_id FROM kit WHERE product_id IS NOT NULL")]
            MIN_PER_WH = 100  # safety floor; real feeds carry thousands per warehouse
            for wc in TARGET_WAREHOUSES:
                wid = wh_to_id.get(wc)
                if wid is None:
                    continue
                present = list(present_by_wh.get(wid, set()))
                if len(present) < MIN_PER_WH:
                    log.warning("Zero-out SKIPPED for warehouse %s: only %d products in feed "
                                "(< %d) — looks partial/empty, not wiping stock",
                                wc, len(present), MIN_PER_WH)
                    continue
                rows = await conn.fetch(
                    """
                    UPDATE product_inventory
                    SET on_hand = 0, available = 0, last_synced_at = NOW(), updated_at = NOW()
                    WHERE warehouse_id = $1
                      AND (on_hand <> 0 OR available <> 0)
                      AND NOT (product_id = ANY($2::int[]))
                      AND NOT (product_id = ANY($3::int[]))
                    RETURNING product_id
                    """,
                    wid, present, kit_pids,
                )
                zeroed_pids.update(r["product_id"] for r in rows)
            log.info("Zero-out: %d product-warehouse rows set to 0 (absent from feed)",
                     len(zeroed_pids))

        # Prices (P1-P5) — only for TTE-matched products this pass.
        if write_prices and price_rows:
            log.info("Upserting %d product_price rows (P1-P5)…", len(price_rows))
            async with conn.transaction():
                items = list(price_rows.items())
                for i in range(0, len(items), 1000):
                    chunk = items[i:i+1000]
                    await conn.executemany(
                        """
                        INSERT INTO product_price
                            (product_id, suggested_retail_price, retail_price,
                             jobber_price, dealer_price, cost,
                             created_at, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                        ON CONFLICT (product_id) DO UPDATE
                        SET suggested_retail_price = EXCLUDED.suggested_retail_price,
                            retail_price = EXCLUDED.retail_price,
                            jobber_price = EXCLUDED.jobber_price,
                            dealer_price = EXCLUDED.dealer_price,
                            cost = EXCLUDED.cost,
                            updated_at = NOW()
                        """,
                        [(pid, d["suggested_retail_price"], d["retail_price"],
                          d["jobber_price"], d["dealer_price"], d["cost"])
                         for pid, d in chunk],
                    )

        log.info("Done.")

        # After writing inventory, keep the rest of the site consistent with it:
        #  1. recompute kit (package) stock from the components we just loaded;
        #  2. re-index every product whose stock changed (plus kits) so the
        #     Typesense-backed catalog grid + search in-stock match the fresh
        #     numbers — otherwise the grid would lag until the nightly reindex.
        # All best-effort: an inventory load must never fail on a search hiccup.
        if not dry_run:
            try:
                from app.database import async_session
                from app.services.catalog_visibility import refresh_instock_only
                from app.services.kit_inventory import recompute_and_reindex_kits
                from app.services.search import index_products
                changed_pids = sorted({r["product_id"] for r in inventory.values()
                                       if r.get("product_id")} | zeroed_pids)
                async with async_session() as session:
                    ks = await recompute_and_reindex_kits(session)
                    # Blowout ("Hidden except in-stock") items: flip
                    # is_hidden_<channel> to match the fresh stock (hidden iff
                    # on_hand<=0) BEFORE re-indexing, so listings/search follow
                    # stock within one sync cycle. Cart/checkout are the instant
                    # gate; this keeps the shelf tidy.
                    flipped = await refresh_instock_only(session, changed_pids)
                    if flipped:
                        await session.commit()
                    if price_rows:
                        # The catalog sorts and filters on this cached price.
                        from app.services.pricing_service import recompute_resolved_retail
                        await recompute_resolved_retail(session, list(price_rows))
                    n_idx = await index_products(session, sorted(set(changed_pids) | set(price_rows)))
                log.info("Post-load: kit recompute=%s, in_stock_only flipped=%d, reindexed %d changed products",
                         ks, len(flipped), n_idx)
            except Exception:
                log.exception("Post-inventory-load recompute/reindex failed (non-fatal)")

    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed-warehouses", action="store_true",
                    help="UPSERT warehouse seed (adds code 2 = Kent if missing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Walk inputs + write report, but don't touch DB")
    ap.add_argument("--no-prices", action="store_true",
                    help="Skip ProductPrice upserts (inventory only)")
    ap.add_argument("--no-zero-out", action="store_true",
                    help="Don't zero products absent from the feed (default: zero them, "
                         "treating the feed as the authoritative full list)")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main(
        dry_run=args.dry_run,
        seed_wh=args.seed_warehouses,
        write_prices=not args.no_prices,
        zero_out=not args.no_zero_out,
    ))
