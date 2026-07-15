"""End-to-end smoke test for the YMM flow.

After XML ingest + VCdb backfill, this exercises the full path:
  1. List years
  2. List makes for 2024
  3. List models for 2024 + Ford
  4. Resolve to a base_vehicle_id
  5. List part-types fitting that vehicle
  6. List brands fitting that vehicle
  7. List actual parts (with prices, images)

Run after restart_erp.bat or:
  python app/scripts/test_ymm_e2e.py
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
        print("=" * 70)
        print("STEP 1: years available")
        print("=" * 70)
        years = await pace_search.list_years(db)
        print(f"  {len(years)} years from {min(years)} to {max(years)}")
        print(f"  newest 10: {years[:10]}")

        print()
        print("=" * 70)
        print("STEP 2: makes available for 2024")
        print("=" * 70)
        makes = await pace_search.list_makes_for_year(db, 2024)
        print(f"  {len(makes)} makes for 2024")
        for m in makes[:20]:
            print(f"    [{m['id']:>5}] {m['name']}")
        if len(makes) > 20:
            print(f"    ... and {len(makes) - 20} more")

        # Find Ford
        ford = next((m for m in makes if m["name"] == "Ford"), None)
        if not ford:
            print("\n  Ford not in 2024 list?? Picking first make instead.")
            ford = makes[0]

        print()
        print("=" * 70)
        print(f"STEP 3: models available for 2024 {ford['name']}")
        print("=" * 70)
        models = await pace_search.list_models_for_year_make(db, 2024, ford["id"])
        for mod in models:
            print(f"    [{mod['id']:>6}] {mod['name']}")

        # Find F-150
        f150 = next((m for m in models if m["name"] == "F-150"), None) or (models[0] if models else None)
        if not f150:
            print("  No models — backfill not done yet?")
            return

        print()
        print("=" * 70)
        print(f"STEP 4: resolve 2024 {ford['name']} {f150['name']}")
        print("=" * 70)
        resolved = await pace_search.resolve_base_vehicle(db, 2024, ford["id"], f150["id"])
        if not resolved:
            print(f"  Couldn't resolve — base_vehicle row missing")
            return
        bv_id = resolved["base_vehicle_id"]
        print(f"  Label: {resolved['label']}")
        print(f"  base_vehicle_id: {bv_id}")

        print()
        print("=" * 70)
        print(f"STEP 5: categories with parts that fit base_vehicle {bv_id}")
        print("=" * 70)
        ptypes = await pace_search.part_types_for_vehicle(db, bv_id)
        ptypes.sort(key=lambda x: -x["part_count"])
        for pt in ptypes[:15]:
            print(f"    [{pt['id']:>5}] {pt['name']:42}  ({pt['part_count']} parts)")
        if len(ptypes) > 15:
            print(f"    ... and {len(ptypes) - 15} more part-types")

        print()
        print("=" * 70)
        print(f"STEP 6: brands with parts that fit base_vehicle {bv_id}")
        print("=" * 70)
        brands_v = await pace_search.brands_for_vehicle(db, bv_id)
        brands_v.sort(key=lambda x: -x["part_count"])
        for b in brands_v[:15]:
            print(f"    [{b['aaia_code']}] {b['name']:35}  ({b['part_count']} parts)")
        if len(brands_v) > 15:
            print(f"    ... and {len(brands_v) - 15} more brands")

        print()
        print("=" * 70)
        print(f"STEP 7: top 10 parts that fit {resolved['label']}")
        print("=" * 70)
        parts = await pace_search.parts_for_vehicle(db, bv_id, limit=10)
        print(f"  total parts: {parts['total']}")
        for p in parts["items"]:
            price = f"${p['list_price']:.2f}" if p.get("list_price") else "n/a"
            jobber = f"${p['jobber_price']:.2f}" if p.get("jobber_price") else "n/a"
            print(f"    [{p['brand']:25}] {p['sku']:22}  list={price:>9}  jbr={jobber:>9}  {p['name'][:50]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
