"""Rebuild Truck Equipment > Truck Bodies on Knapheide's category list.

Owner, 2026-09-21: the old buckets (Flatbeds / Service-Utility / Dump / Stake /
Van-Box, ingested from titantruck.com in May) mixed body types -- line bodies
and gooseneck bodies under Flatbeds, skirted pickup beds and a crane body under
Service, and forestry, saw and dump bodies under Stake. Knapheide's own list
"has it right", with two owner changes:

  * No "Stake Bodies": a stake body is a platform body with stake sides, and
    stake racks/sides are already listed as an option on the platform bodies.
  * "Landscape Bodies" is its own category (Knapheide files it under Platform).

Crane bodies go to Mechanics Trucks, not Service Bodies -- a crane
reinforcement kit is an option on a standard service body.

Also: 255 Knapheide parts were filed directly on "Truck Bodies". The sized
bodies among them (600-series service bodies, PGT gooseneck, PVMX / PCON
platforms) move to their body category; everything else moves to
Truck Bodies > Parts & Accessories. Nothing stays filed on the parent itself --
browsing a category already includes everything beneath it.

Everything is matched by category path and product SKU, never by id, so the
same script runs on local and prod. Category tiles are files committed under
static/category-images/truck-bodies/ (they ship with the code). Backs up every
row it touches first. Dry run unless --apply.

Usage:
    python app/scripts/restructure_truck_body_categories.py
    python app/scripts/restructure_truck_body_categories.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve()
APP_DIR = HERE.parent.parent
ENV_FILE = APP_DIR / ".env"
TILE_DIR = APP_DIR / "backend" / "static" / "category-images" / "truck-bodies"
BACKUP_DIR = APP_DIR.parent / "discovery" / "manufacturer_data"
PARENT = "Truck Equipment > Truck Bodies"
# Bump when a tile file changes: /static is served with a 7-day public max-age, so
# browsers and Cloudflare keep the old picture until the URL itself changes.
TILE_VERSION = 2

# (name, slug, sort) in Knapheide's order, Landscape Bodies after Platform.
# `was` renames an existing category in place (keeps its id and anything tied to it).
CATEGORIES = [
    {"name": "Service Bodies",          "slug": "service-bodies",          "sort": 10,  "was": "Service / Utility Bodies"},
    {"name": "Enclosed Service Bodies", "slug": "enclosed-service-bodies", "sort": 20},
    {"name": "Platform Bodies",         "slug": "platform-bodies",         "sort": 30,  "was": "Flatbeds"},
    {"name": "Landscape Bodies",        "slug": "landscape-bodies",        "sort": 40},
    {"name": "Gooseneck Bodies",        "slug": "gooseneck-bodies",        "sort": 50},
    {"name": "Dump Bodies",             "slug": "dump-bodies",             "sort": 60},
    {"name": "Forestry Bodies",         "slug": "forestry-bodies",         "sort": 70},
    {"name": "KUV Vans",                "slug": "kuv-vans",                "sort": 80},
    {"name": "Mechanics Trucks",        "slug": "mechanics-trucks",        "sort": 90},
    {"name": "Fuel Lube Trucks",        "slug": "fuel-lube-trucks",        "sort": 100},
    {"name": "Saw Trucks",              "slug": "saw-trucks",              "sort": 110},
    {"name": "Water Trucks",            "slug": "water-trucks",            "sort": 120},
    {"name": "Van / Box Bodies",        "slug": "van-box-bodies",          "sort": 130},
    {"name": "Parts & Accessories",     "slug": "truck-body-parts-accessories", "sort": 140},
]
RETIRE = ["Stake Bodies", "Body Hoists"]

# The 66 body products, by SKU.
BODIES = {
    "Service Bodies": [
        "KNP-S15002", "KNP-S15006", "KNP-S204958", "KNP-S15035", "KNP-S15008", "KNP-S204945",
        "KNP-S15007", "KNP-S91165", "KNP-S91164", "CMT-S17888", "CMT-S17889"],
    "Enclosed Service Bodies": ["KNP-S91149", "KNP-S204963"],
    "KUV Vans": ["KNP-S91148"],
    "Platform Bodies": [
        "KNP-S15781", "KNP-S15031", "KNP-S15030", "KNP-S204984", "KNP-S15033", "KNP-S91142",
        "KNP-S91141", "CMT-S17878", "CMT-S17879", "CMT-S17877", "CMT-S17885", "CMT-S17890",
        # Rugby files the Rancher under Platform ("carbon steel platform body"), and
        # Series 2000 is Rugby's old name for the Vari-Class platform.
        "CMT-S17876", "RUG-S124955", "RUG-S13157"],
    "Landscape Bodies": ["KNP-S91161", "CMT-S17892", "RUG-S13153"],
    # CM's pickup beds carry a gooseneck hitch -- same class as Knapheide's PGN bodies.
    "Gooseneck Bodies": [
        "KNP-S91146", "KNP-S91145", "KNP-S91144", "KNP-S91137", "CMT-S17870", "CMT-S17872",
        "CMT-S17884", "CMT-S17886", "CMT-S17874", "CMT-S17887", "CMT-S17871", "CMT-S17873",
        "CMT-S17875", "CMT-S17881", "CMT-S17869", "CMT-S17868", "CMT-S17883", "CMT-S17882"],
    "Dump Bodies": [
        "KNP-S91162", "KNP-S204985", "KNP-S91163", "CMT-S17880", "RUG-S13154", "RUG-S13156",
        "EZD-S9535", "EZD-S90827"],
    "Forestry Bodies": ["KNP-S91155"],
    "Saw Trucks": ["KNP-S204986"],
    "Mechanics Trucks": ["KNP-S15013"],
    "Van / Box Bodies": ["MOR-S283010"],
    "Parts & Accessories": ["EZD-S90828", "EZD-S90830", "EZD-S90834", "EZD-S90832"],
}

# Sized Knapheide bodies among the parts, by SKU. Everything else -> Parts & Accessories.
SIZED = [
    # 500/600/700-series service bodies: 682, 696, 6108, 6132 ... (not 8-digit part numbers)
    (re.compile(r"^KNP-(?:KNP)?[567](?:\d{2}|1\d{2})(?:[A-Z]|-|$)"), "Service Bodies"),
    (re.compile(r"^KNP-(?:KNP)?PVMX"), "Platform Bodies"),
    (re.compile(r"^KNP-(?:KNP)?PCON-"), "Platform Bodies"),
    (re.compile(r"^KNP-(?:KNP)?PGT[A-E]\d|^KNP-(?:KNP)?PGT[A-E]-|^KNP-NGB-"), "Gooseneck Bodies"),
]


def db_dsn() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().replace("postgresql+asyncpg://", "postgresql://")
    raise SystemExit("DATABASE_URL not found in app/.env")


def tile_url(slug: str) -> str | None:
    for ext in ("png", "jpg"):
        if (TILE_DIR / f"{slug}.{ext}").exists():
            return f"/static/category-images/truck-bodies/{slug}.{ext}?v={TILE_VERSION}"
    return None


def sized_target(sku: str) -> str | None:
    for rx, cat in SIZED:
        if rx.search(sku):
            return cat
    return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = await asyncpg.connect(db_dsn())
    try:
        parent = await conn.fetchrow("SELECT id, depth FROM category WHERE full_path=$1", PARENT)
        if not parent:
            raise SystemExit(f"'{PARENT}' not found")
        kids = {r["name"]: r for r in await conn.fetch(
            "SELECT id, name, slug, full_path, is_active, curated_image_url FROM category WHERE parent_id=$1",
            parent["id"])}

        # -- plan products --------------------------------------------------
        body_target = {sku: cat for cat, skus in BODIES.items() for sku in skus}
        skus = await conn.fetch("SELECT id, sku FROM product WHERE sku = ANY($1::text[])", list(body_target))
        found = {r["sku"]: r["id"] for r in skus}
        missing = sorted(set(body_target) - set(found))

        direct = await conn.fetch(
            "SELECT p.id, p.sku, p.name FROM product_category pc JOIN product p ON p.id=pc.product_id "
            "WHERE pc.category_id=$1", parent["id"])
        moves: dict[int, str] = {found[s]: c for s, c in body_target.items() if s in found}
        sized = parts = 0
        for r in direct:
            if r["id"] in moves:
                continue
            tgt = sized_target(r["sku"])
            if tgt:
                sized += 1
            else:
                parts += 1
            moves[r["id"]] = tgt or "Parts & Accessories"

        print(f"parent            : {PARENT} (id {parent['id']})")
        print(f"body SKUs         : {len(found)}/{len(body_target)} found" + (f"  MISSING {missing}" if missing else ""))
        print(f"filed on parent   : {len(direct)} -> {sized} sized bodies + {parts} parts & accessories")
        for c in CATEGORIES:
            n = sum(1 for v in moves.values() if v == c["name"])
            state = "rename from " + c["was"] if c.get("was") in kids else ("keep" if c["name"] in kids else "create")
            print(f"  {c['name']:<26} {n:>4} products   [{state}]  tile={'ok' if tile_url(c['slug']) else 'MISSING'}")
        print(f"retire            : {', '.join(RETIRE)}")
        if not args.apply:
            print("\nDRY RUN - nothing written. Re-run with --apply.")
            return 0

        # -- backup -----------------------------------------------------------
        sub_ids = [r["id"] for r in kids.values()]
        backup = {
            "category": [dict(r) for r in await conn.fetch(
                "SELECT * FROM category WHERE id = ANY($1::int[]) OR id=$2", sub_ids, parent["id"])],
            "product_category": [dict(r) for r in await conn.fetch(
                "SELECT * FROM product_category WHERE category_id = ANY($1::int[]) OR category_id=$2",
                sub_ids, parent["id"])],
        }
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bfile = BACKUP_DIR / f"truck_body_categories_backup_{stamp}.json"
        bfile.write_text(json.dumps(backup, indent=1, default=str), encoding="utf-8")
        print(f"\nbacked up {len(backup['category'])} categories + {len(backup['product_category'])} links -> {bfile.name}")

        async with conn.transaction():
            ids: dict[str, int] = {}
            for c in CATEGORIES:
                path = f"{PARENT} > {c['name']}"
                row = kids.get(c.get("was")) or kids.get(c["name"])
                if row:
                    await conn.execute(
                        "UPDATE category SET name=$2, slug=$3, full_path=$4, sort_order=$5, is_active=true, "
                        "curated_image_url=COALESCE($6, curated_image_url), updated_at=now() WHERE id=$1",
                        row["id"], c["name"], c["slug"], path, c["sort"], tile_url(c["slug"]))
                    ids[c["name"]] = row["id"]
                else:
                    ids[c["name"]] = await conn.fetchval(
                        "INSERT INTO category (name, slug, parent_id, full_path, depth, sort_order, is_featured, "
                        "is_active, curated_image_url) VALUES ($1,$2,$3,$4,$5,$6,false,true,$7) RETURNING id",
                        c["name"], c["slug"], parent["id"], path, parent["depth"] + 1, c["sort"], tile_url(c["slug"]))
            if tile_url("truck-bodies"):
                await conn.execute("UPDATE category SET curated_image_url=$2, updated_at=now() WHERE id=$1",
                                   parent["id"], tile_url("truck-bodies"))

            all_sub = list(ids.values()) + [r["id"] for n, r in kids.items() if n in RETIRE]
            pids = list(moves)
            # every placement under Truck Bodies is rebuilt: drop the parent + subcategory links, re-add one leaf
            await conn.execute(
                "DELETE FROM product_category WHERE product_id = ANY($1::int[]) "
                "AND (category_id = ANY($2::int[]) OR category_id=$3)", pids, all_sub, parent["id"])
            # The new leaf becomes the primary category (breadcrumb) unless the
            # product keeps a primary placement somewhere else in the catalog.
            await conn.executemany(
                "INSERT INTO product_category (product_id, category_id, is_primary) "
                "VALUES ($1, $2, NOT EXISTS (SELECT 1 FROM product_category x "
                "                            WHERE x.product_id=$1 AND x.is_primary)) "
                "ON CONFLICT (product_id, category_id) DO NOTHING",
                [(pid, ids[cat]) for pid, cat in moves.items()])

            for name in RETIRE:
                if name in kids:
                    left = await conn.fetchval("SELECT count(*) FROM product_category WHERE category_id=$1",
                                               kids[name]["id"])
                    if left:
                        raise RuntimeError(f"{name} still has {left} products - not retiring")
                    await conn.execute("UPDATE category SET is_active=false, updated_at=now() WHERE id=$1",
                                       kids[name]["id"])

        rows = await conn.fetch(
            "SELECT c.name, c.is_active, count(pc.product_id) n FROM category c "
            "LEFT JOIN product_category pc ON pc.category_id=c.id WHERE c.parent_id=$1 "
            "GROUP BY c.name, c.is_active, c.sort_order ORDER BY c.sort_order", parent["id"])
        left_on_parent = await conn.fetchval("SELECT count(*) FROM product_category WHERE category_id=$1", parent["id"])
        print("\nresult:")
        for r in rows:
            print(f"  {r['name']:<26} {r['n']:>4}  {'active' if r['is_active'] else 'RETIRED'}")
        print(f"  (filed directly on Truck Bodies: {left_on_parent})")
        print("\nNext: reindex_typesense.py so search facets match the new tree.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
