"""Smoke test: hit the pace_search service directly to validate the YMM + category flow.

Doesn't need uvicorn running — calls the service functions directly.
After data is loaded, run:
    python app/scripts/test_pace_api.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services import pace_search


async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        print("=== /api/pace/categories (top-level part-type categories) ===")
        cats = await pace_search.list_part_type_categories(db)
        if cats:
            for c in cats[:10]:
                print(f"  {c['category']}  ({c['part_type_count']} part types)")
        else:
            print("  (no categories — pcdb_part_type rows lack category_name; needs PCdb load)")

        print("\n=== /api/pace/part-types (sample 10 most-used by part count) ===")
        pts = await pace_search.list_part_types(db)
        for pt in sorted(pts, key=lambda x: -x["part_count"])[:10]:
            print(f"  PartTypeID={pt['id']:>5} {pt['name']:40} parts={pt['part_count']}")

        print("\n=== Browsing the largest PartType (no vehicle filter) ===")
        if pts:
            top_pt = max(pts, key=lambda x: x["part_count"])
            print(f"  Browsing PartType {top_pt['id']} ({top_pt['name']}) — {top_pt['part_count']} parts")
            res = await pace_search.parts_in_part_type(db, top_pt["id"], limit=5)
            print(f"  total={res['total']}")
            for it in res["items"]:
                print(f"    [{it['brand']:30}] {it['sku']:25} {it['name'][:50]}")

        # YMM dropdowns will only have data once VCdb is loaded (placeholders have year=0)
        print("\n=== /api/pace/years (real years from loaded VCdb) ===")
        years = await pace_search.list_years(db)
        if not years:
            print("  (no real years yet — vcdb_base_vehicle has only placeholder year=0 rows)")
            print("  Will populate after Auto Care VCdb is loaded.")
        else:
            print(f"  {len(years)} years: {years[:10]}{'...' if len(years) > 10 else ''}")

        # Even without VCdb, we can still query parts for a base_vehicle id directly
        print("\n=== Direct fitment lookup by BaseVehicleID (works without VCdb) ===")
        bv_row = (await db.execute(
            __import__("sqlalchemy").text("SELECT id FROM vcdb_base_vehicle ORDER BY id LIMIT 1")
        )).first()
        if bv_row:
            bv_id = bv_row[0]
            print(f"  Using BaseVehicleID={bv_id}")
            ptypes = await pace_search.part_types_for_vehicle(db, bv_id)
            print(f"  Categories with parts for this vehicle: {len(ptypes)}")
            for pt in ptypes[:5]:
                print(f"    PartTypeID={pt['id']:>5} parts={pt['part_count']}")
            brands_v = await pace_search.brands_for_vehicle(db, bv_id)
            print(f"  Brands with parts for this vehicle: {len(brands_v)}")
            for b in brands_v[:5]:
                print(f"    [{b['name']}] aaia={b['aaia_code']} parts={b['part_count']}")
            parts = await pace_search.parts_for_vehicle(db, bv_id, limit=5)
            print(f"  All parts: total={parts['total']}, showing first 5:")
            for p in parts["items"]:
                price = f"${p['list_price']:.2f}" if p.get("list_price") else "—"
                print(f"    [{p['brand']:30}] {p['sku']:25} {p['name'][:45]:45} list={price}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
