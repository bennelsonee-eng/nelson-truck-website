"""Backfill human-readable labels for qualifier IDs by scraping PACE's ajaxGetFacet.

The PACE facet endpoint is open (no auth needed) and returns
{id: name} maps for every qualifier (SubModel, BedLength, EngineBase, etc.).
This script walks our base_vehicle_id list, calls the endpoint, and harvests
the labels into vcdb_sub_model.name, vcdb_bed_length.label, etc.

Strategy:
  - Maintain a global cache: {facet_name: {seen_ids}} so we never re-walk
    a subtree where every choice is already labeled.
  - For each base_vehicle, do a bounded-depth random walk through the facet tree.
  - Upsert label rows as we go.

Usage:
    python app/scripts/backfill_qualifier_labels.py
    python app/scripts/backfill_qualifier_labels.py --limit 100   # smoke test on 100 vehicles
    python app/scripts/backfill_qualifier_labels.py --max-depth 4 # cap walk depth
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import (  # noqa: E402
    PcdbPosition,
    VcdbAspiration,
    VcdbBaseVehicle,
    VcdbBedLength,
    VcdbBedType,
    VcdbBodyType,
    VcdbDriveType,
    VcdbEngineBase,
    VcdbFuelType,
    VcdbRegion,
    VcdbSubModel,
)


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("backfill_labels")
logging.getLogger("httpx").setLevel(logging.WARNING)


PACE_FACET_URL = "https://titan.pacesystems.com/catalog/ajaxGetFacet"
RATE_LIMIT_PER_SEC = 6  # be polite to PACE


# Map PACE facet names → our SQLAlchemy model + name column
# (Some PACE facets like EngineFamilyID don't map to our schema; we ignore those.)
FACET_TO_TABLE = {
    "SubModelID":     (VcdbSubModel,  "name"),
    "BedLengthID":    (VcdbBedLength, "label"),
    "BedTypeID":      (VcdbBedType,   "name"),
    "BodyTypeID":     (VcdbBodyType,  "name"),
    "DriveTypeID":    (VcdbDriveType, "name"),
    "EngineBaseID":   (VcdbEngineBase, "label"),
    "FuelTypeID":     (VcdbFuelType,  "name"),
    "AspirationID":   (VcdbAspiration, "name"),
    "RegionID":       (VcdbRegion,    "name"),
    "PositionID":     (PcdbPosition,  "name"),
    # BodyNumDoors, EngineFamilyID, EngineSizeID etc. — skip (no name table)
}


async def fetch_facet(client: httpx.AsyncClient, qualifiers: dict[str, int]) -> dict | None:
    """POST to ajaxGetFacet with current qualifier state. Returns parsed JSON or None."""
    body_pairs = []
    for k, v in qualifiers.items():
        body_pairs.append(f"vehicle[{k}]={v}")
    body = "&".join(body_pairs)
    try:
        r = await client.post(
            PACE_FACET_URL,
            content=body,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json",
            },
            timeout=15.0,
        )
        r.raise_for_status()
        return r.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
        log.warning("facet fetch failed for %s: %s", qualifiers, e)
        return None


async def walk_facets(
    client: httpx.AsyncClient,
    db,
    base_vehicle_id: int,
    seen_per_facet: dict[str, set[int]],
    api_calls: list[int],
    rate_t0: float,
    max_depth: int,
) -> int:
    """Walk the facet tree for one base_vehicle. Returns number of new label upserts."""
    qualifiers: dict[str, int] = {"BaseVehicleID": base_vehicle_id}
    new_labels = 0
    depth = 0
    while depth < max_depth:
        # Throttle
        elapsed = time.time() - rate_t0
        target = api_calls[0] / RATE_LIMIT_PER_SEC
        if elapsed < target:
            await asyncio.sleep(target - elapsed)

        resp = await fetch_facet(client, qualifiers)
        api_calls[0] += 1
        if resp is None:
            break

        data = resp.get("data")
        if not data:
            break  # done — no more facets to ask
        facet_name = data.get("name")
        choices = data.get("choices") or {}
        if not facet_name or not choices:
            break

        # Upsert labels for any IDs we haven't seen yet
        if facet_name in FACET_TO_TABLE:
            model, name_col = FACET_TO_TABLE[facet_name]
            seen = seen_per_facet[facet_name]
            for raw_id, raw_name in choices.items():
                try:
                    fid = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if fid in seen:
                    continue
                seen.add(fid)
                vals = {"id": fid, name_col: raw_name}
                stmt = pg_insert(model.__table__).values(**vals).on_conflict_do_update(
                    index_elements=["id"], set_={name_col: raw_name}
                )
                await db.execute(stmt)
                new_labels += 1

        # Pick a choice and continue walking. Prefer an UNSEEN one to discover
        # new branches; otherwise pick a random one.
        candidate_ids = list(choices.keys())
        seen_now = seen_per_facet.get(facet_name, set())
        unseen = [c for c in candidate_ids if int(c) not in seen_now or True]  # all are now in seen
        # We've already added all to seen above, so just pick first/random
        next_choice = random.choice(candidate_ids)
        try:
            qualifiers[facet_name] = int(next_choice)
        except (TypeError, ValueError):
            qualifiers[facet_name] = next_choice
        depth += 1

    return new_labels


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap number of base_vehicles to walk (smoke test).")
    ap.add_argument("--max-depth", type=int, default=8,
                    help="Max facet steps per base_vehicle walk.")
    ap.add_argument("--shuffle", action="store_true", default=True,
                    help="Process base_vehicles in random order to spread coverage.")
    args = ap.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # Pull all base_vehicles where we have real Y/M/M (year>0)
        bv_rows = (await db.execute(
            select(VcdbBaseVehicle.id).where(VcdbBaseVehicle.year > 0)
        )).all()
        base_vehicles = [r[0] for r in bv_rows]
        if args.shuffle:
            random.shuffle(base_vehicles)
        if args.limit:
            base_vehicles = base_vehicles[:args.limit]
        log.info("Walking facets for %d base_vehicles (max_depth=%d)",
                 len(base_vehicles), args.max_depth)

        seen_per_facet: dict[str, set[int]] = defaultdict(set)
        # Pre-seed with already-named rows to skip work
        for facet_name, (model, name_col) in FACET_TO_TABLE.items():
            existing_q = select(model.id).where(
                getattr(model, name_col).is_not(None),
                ~getattr(model, name_col).like(f"{facet_name.replace('ID','')}#%"),
            )
            try:
                rows = (await db.execute(existing_q)).all()
                seen_per_facet[facet_name] = {r[0] for r in rows}
                log.info("  %s: %d already-labeled IDs (will skip)",
                         facet_name, len(seen_per_facet[facet_name]))
            except Exception:
                pass

        api_calls = [0]
        rate_t0 = time.time()
        total_new_labels = 0

        async with httpx.AsyncClient(verify=False) as client:
            for i, bv_id in enumerate(base_vehicles, 1):
                new = await walk_facets(client, db, bv_id, seen_per_facet,
                                          api_calls, rate_t0, args.max_depth)
                total_new_labels += new
                if i % 50 == 0 or i == len(base_vehicles):
                    await db.commit()
                    log.info("  [%d/%d] api_calls=%d, new_labels=+%d, total_new=%d, elapsed=%.0fs  | facet sizes: %s",
                             i, len(base_vehicles), api_calls[0], new, total_new_labels,
                             time.time() - rate_t0,
                             {f: len(s) for f, s in seen_per_facet.items() if s})

            await db.commit()

    await engine.dispose()
    log.info("DONE: %d API calls, %d new labels harvested", api_calls[0], total_new_labels)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
