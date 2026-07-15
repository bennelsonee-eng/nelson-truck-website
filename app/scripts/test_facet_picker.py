"""Smoke test the iterative facet picker against 2024 Ford F-150.

Mirrors PACE's ajaxGetFacet flow:
    Y/M/M selected -> ask SubModel -> ask BedLength -> exact

Run:
    python app/scripts/test_facet_picker.py
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


async def walk_facets(db, base_vehicle_id, label, *, part_type_id=None):
    """Repeatedly call next_facet, picking the first choice each time, until done."""
    qualifiers: dict[str, int | None] = {}
    print(f"\n--- {label} (base_vehicle_id={base_vehicle_id}) ---")
    step = 1
    while True:
        facet = await pace_search.next_facet(db, base_vehicle_id, qualifiers,
                                              part_type_id=part_type_id)
        if facet is None:
            print(f"  step {step}: DONE — fitment fully qualified.")
            print(f"  final qualifiers: { {k: v for k, v in qualifiers.items() if v} }")
            break
        choices = facet["choices"]
        # Pick the FIRST choice for the smoke test
        first_id, first_name = next(iter(choices.items()))
        print(f"  step {step}: ask '{facet['label']}' ({len(choices)} options) — choosing '{first_name}' (id={first_id})")
        qualifiers[facet["name"]] = int(first_id)
        step += 1
        if step > 12:
            print("  step LIMIT — bailing")
            break

    # Now run parts-with-status
    parts = await pace_search.parts_for_vehicle_with_status(
        db, base_vehicle_id, qualifiers, part_type_id=part_type_id, limit=10
    )
    exact = sum(1 for p in parts["items"] if p["fitment_status"] == "exact")
    maybe = sum(1 for p in parts["items"] if p["fitment_status"] == "maybe")
    print(f"\n  parts: total={parts['total']}  exact={exact}  maybe={maybe}  (showing first 5)")
    for p in parts["items"][:5]:
        price = f"${p['jobber_price']:.2f}" if p.get("jobber_price") else "n/a"
        print(f"    [{p['fitment_status']:5}] [{p['brand']:25}] {p['sku']:22}  jbr={price:>10}  {p['name'][:55]}")


async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # 2024 Ford F-150
        bv_2024_f150 = 169471
        await walk_facets(db, bv_2024_f150, "2024 Ford F-150 (no category filter)")

        # Same but limited to truck-bed-cover-ish PartType — let's pick the most-populated
        # one for this vehicle to demonstrate category-scoped facet walks.
        ptypes = await pace_search.part_types_for_vehicle(db, bv_2024_f150)
        if ptypes:
            top = max(ptypes, key=lambda x: x["part_count"])
            await walk_facets(db, bv_2024_f150,
                              f"2024 Ford F-150 (PartType {top['id']}, {top['part_count']} parts)",
                              part_type_id=top["id"])

        # Show the no-qualifier baseline for comparison
        print("\n--- Baseline: no qualifiers picked (everything is 'maybe' until refined) ---")
        bare = await pace_search.parts_for_vehicle_with_status(
            db, bv_2024_f150, {}, limit=10
        )
        bare_exact = sum(1 for p in bare["items"] if p["fitment_status"] == "exact")
        bare_maybe = sum(1 for p in bare["items"] if p["fitment_status"] == "maybe")
        print(f"  total={bare['total']}  exact={bare_exact}  maybe={bare_maybe}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
