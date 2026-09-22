"""List the Knapheide parts (and stocked sizes) underneath the right truck body.

Owner, 2026-09-21: the parts filed on "Truck Bodies" should be listed as options
underneath the correct truck body. Reads the rules in truck_body_parts_rules.py
and writes product_accessory rows:

  * every part in Truck Bodies > Parts & Accessories that a rule places ->
    each body in the matched families (the showcase model AND the sized bodies
    of that family, so a 9' PGTB page lists gooseneck hitches too);
  * every sized body (6108D54, PGTB-96, PVMX-125 ...) -> its showcase model,
    under "Sizes & configurations".

Unmatched parts are never guessed: they stay in Parts & Accessories and are
listed in the review sheet. Re-runnable (replaces this source's rows); backs up
what it replaces. Writes discovery/manufacturer_data/truck_body_parts_mapping.csv
for review. Dry run unless --apply.

Usage:
    python app/scripts/link_truck_body_parts.py
    python app/scripts/link_truck_body_parts.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
from truck_body_parts_rules import FAMILIES, GROUP_ORDER, classify, sized_body  # noqa: E402

APP_DIR = HERE.parent.parent
ENV_FILE = APP_DIR / ".env"
DATA_DIR = APP_DIR.parent / "discovery" / "manufacturer_data"
SOURCE = "truck-body-rules"
PARTS_PATH = "Truck Equipment > Truck Bodies > Parts & Accessories"
BODIES_ROOT = "Truck Equipment > Truck Bodies"


def db_dsn() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().replace("postgresql+asyncpg://", "postgresql://")
    raise SystemExit("DATABASE_URL not found in app/.env")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = await asyncpg.connect(db_dsn())
    try:
        # showcase bodies + every Knapheide product filed anywhere under Truck Bodies
        showcase = {r["sku"]: r["id"] for r in await conn.fetch(
            "SELECT id, sku FROM product WHERE sku = ANY($1::text[])",
            [s for skus in FAMILIES.values() for s in skus])}
        under = await conn.fetch(
            "SELECT DISTINCT p.id, p.sku, p.name, c.full_path FROM product p "
            "JOIN product_category pc ON pc.product_id = p.id JOIN category c ON c.id = pc.category_id "
            "JOIN brand b ON b.id = p.brand_id "
            "WHERE b.name = 'Knapheide' AND (c.full_path = $1 OR c.full_path LIKE $1 || ' > %')", BODIES_ROOT)

        family_bodies: dict[str, set[int]] = defaultdict(set)
        for fam, skus in FAMILIES.items():
            family_bodies[fam].update(showcase[s] for s in skus if s in showcase)
        sized: list[tuple[int, str, str, str]] = []           # (id, sku, family, model sku)
        for r in under:
            hit = sized_body(r["sku"])
            if hit:
                family_bodies[hit[0]].add(r["id"])
                sized.append((r["id"], r["sku"], hit[0], hit[1]))

        parts = [r for r in under if r["full_path"] == PARTS_PATH]
        rows: list[tuple[int, int, str, int, str]] = []       # body, part, group, sort, rule
        review: list[dict] = []
        unmatched = []
        for p in sorted(parts, key=lambda r: r["sku"]):
            got = classify(p["sku"], p["name"])
            if got is None:
                unmatched.append(p)
                review.append({"part_sku": p["sku"], "part_name": p["name"], "group": "", "families": "",
                               "rule": "UNMATCHED - stays in Parts & Accessories", "bodies_linked": 0})
                continue
            group, fams, rule = got
            bodies = set().union(*(family_bodies[f] for f in fams))
            for b in bodies:
                rows.append((b, p["id"], group, GROUP_ORDER.index(group), rule))
            review.append({"part_sku": p["sku"], "part_name": p["name"], "group": group,
                           "families": ", ".join(fams), "rule": rule, "bodies_linked": len(bodies)})
        for pid, sku, fam, model in sized:
            if model in showcase:
                rows.append((showcase[model], pid, "Sizes & configurations", 0, "sized-body"))

        rows = list({(b, p): (b, p, g, s, r) for b, p, g, s, r in rows if b != p}.values())
        per_group = Counter(g for _, _, g, _, _ in rows)
        print(f"showcase bodies  : {len(showcase)}/{sum(len(v) for v in FAMILIES.values())}")
        print(f"sized bodies     : {len(sized)}")
        print(f"parts            : {len(parts)}  (matched {len(parts) - len(unmatched)}, unmatched {len(unmatched)})")
        print(f"links to write   : {len(rows)}")
        for g in GROUP_ORDER:
            print(f"   {g:<32} {per_group.get(g, 0):>6}")
        for p in unmatched:
            print(f"   UNMATCHED {p['sku']:<20} {p['name'][:60]}")

        sheet = DATA_DIR / "truck_body_parts_mapping.csv"
        with sheet.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["part_sku", "part_name", "group", "families", "rule", "bodies_linked"])
            w.writeheader()
            w.writerows(review)
        print(f"review sheet     : {sheet.name}")

        if not args.apply:
            print("\nDRY RUN - nothing written. Re-run with --apply.")
            return 0

        before = [dict(r) for r in await conn.fetch("SELECT * FROM product_accessory WHERE source=$1", SOURCE)]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (DATA_DIR / f"product_accessory_backup_{stamp}.json").write_text(
            json.dumps(before, indent=1, default=str), encoding="utf-8")
        async with conn.transaction():
            await conn.execute("DELETE FROM product_accessory WHERE source=$1", SOURCE)
            await conn.executemany(
                "INSERT INTO product_accessory (body_product_id, part_product_id, group_name, sort_order, source, rule) "
                "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (body_product_id, part_product_id) DO NOTHING",
                [(b, p, g, s, SOURCE, r) for b, p, g, s, r in rows])
        n = await conn.fetchval("SELECT count(*) FROM product_accessory WHERE source=$1", SOURCE)
        print(f"\nwrote {n} rows (replaced {len(before)}; backup product_accessory_backup_{stamp}.json)")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
