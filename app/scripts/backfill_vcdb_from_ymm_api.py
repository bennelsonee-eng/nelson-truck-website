"""Backfill VCdb (vcdb_make, vcdb_model, vcdb_base_vehicle) from AAM YMM API.

The XML PACE feeds only carry BaseVehicleID — they don't tell us
"BaseVehicleID 169471 = 2024 Ford F-150". The Auto Care VCdb dump (a
quarterly Microsoft Access database) is the canonical source.

But AAM's public YMM API at https://theaamgroup.com/api/ymm returns the
exact same mapping for free, no auth needed. This script walks
years -> makes -> models and upserts rows into our vcdb_* tables.

After this runs, every BaseVehicleID we already have in pace_fitment
will resolve to a real human-readable label.

Usage:
    python app/scripts/backfill_vcdb_from_ymm_api.py
    python app/scripts/backfill_vcdb_from_ymm_api.py --years 2020-2027
    python app/scripts/backfill_vcdb_from_ymm_api.py --years 2024,2025
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import ssl
import sys
import time
from pathlib import Path

import certifi
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import VcdbBaseVehicle, VcdbMake, VcdbModel  # noqa: E402


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("backfill_vcdb")


YMM_BASE = "https://theaamgroup.com/api/ymm"
RATE_LIMIT_PER_SEC = 8  # courteous polite limit


def parse_year_range(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            for y in range(int(a), int(b) + 1):
                out.add(y)
        else:
            out.add(int(part))
    return sorted(out, reverse=True)


async def fetch_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> list:
    """GET JSON with simple retry."""
    for attempt in range(3):
        try:
            r = await client.get(url, params=params, timeout=15.0)
            r.raise_for_status()
            return r.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)
    return []


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", help="Year filter, e.g. '2020-2027' or '2024,2025'.  Default: all.")
    ap.add_argument("--year-min", type=int, default=1985,
                    help="If --years not given, start at this year (default 1985 — pickups era).")
    args = ap.parse_args()

    # SSL note: tried ssl.create_default_context(cafile=certifi.where()) but Windows
    # httpx hits CERTIFICATE_VERIFY_FAILED regardless. Public read-only API,
    # no sensitive data — disabling verify is safe here.
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with httpx.AsyncClient(verify=False) as client:
        # 1. Get years
        log.info("Fetching available years from YMM API...")
        all_years: list[int] = await fetch_json(client, f"{YMM_BASE}/years")
        log.info("API reports %d years available (%d-%d)",
                 len(all_years), min(all_years), max(all_years))

        if args.years:
            wanted = parse_year_range(args.years)
            years = [y for y in all_years if y in set(wanted)]
        else:
            years = [y for y in all_years if y >= args.year_min]

        log.info("Backfilling %d years (%d-%d)", len(years), min(years), max(years))

        # Make/Model dedup tracking
        seen_make_ids: set[int] = set()
        seen_model_ids: set[int] = set()
        seen_base_vehicle_ids: set[int] = set()
        api_call_count = 0
        rate_t0 = time.time()

        async with Session() as db:
            for yi, year in enumerate(years, 1):
                # Throttle
                if api_call_count > 0:
                    elapsed = time.time() - rate_t0
                    target = api_call_count / RATE_LIMIT_PER_SEC
                    if elapsed < target:
                        await asyncio.sleep(target - elapsed)

                makes = await fetch_json(client, f"{YMM_BASE}/makes", {"Year": year})
                api_call_count += 1

                # Upsert makes
                for m in makes:
                    if m["MakeID"] not in seen_make_ids:
                        seen_make_ids.add(m["MakeID"])
                        await db.execute(pg_insert(VcdbMake.__table__).values(
                            id=m["MakeID"], name=m["MakeName"]
                        ).on_conflict_do_update(
                            index_elements=["id"], set_={"name": m["MakeName"]}
                        ))

                # Per make, fetch models
                for m in makes:
                    elapsed = time.time() - rate_t0
                    target = api_call_count / RATE_LIMIT_PER_SEC
                    if elapsed < target:
                        await asyncio.sleep(target - elapsed)

                    models = await fetch_json(client, f"{YMM_BASE}/models",
                                              {"Year": year, "MakeID": m["MakeID"]})
                    api_call_count += 1

                    for mod in models:
                        # Upsert model (id, make_id, name)
                        if mod["ModelID"] not in seen_model_ids:
                            seen_model_ids.add(mod["ModelID"])
                            await db.execute(pg_insert(VcdbModel.__table__).values(
                                id=mod["ModelID"], make_id=m["MakeID"], name=mod["ModelName"]
                            ).on_conflict_do_update(
                                index_elements=["id"],
                                set_={"name": mod["ModelName"], "make_id": m["MakeID"]}
                            ))

                        # Upsert base_vehicle (year, make, model, base_vehicle_id all known!)
                        bv_id = mod["BaseVehicleID"]
                        if bv_id not in seen_base_vehicle_ids:
                            seen_base_vehicle_ids.add(bv_id)
                            await db.execute(pg_insert(VcdbBaseVehicle.__table__).values(
                                id=bv_id, year=year, make_id=m["MakeID"], model_id=mod["ModelID"]
                            ).on_conflict_do_update(
                                index_elements=["id"],
                                set_={"year": year, "make_id": m["MakeID"], "model_id": mod["ModelID"]}
                            ))

                if yi % 5 == 0 or yi == len(years):
                    await db.commit()
                    log.info("Year %d done [%d/%d]: %d makes %d models %d base_vehicles cached, %d API calls",
                             year, yi, len(years), len(seen_make_ids), len(seen_model_ids),
                             len(seen_base_vehicle_ids), api_call_count)

            await db.commit()

        log.info("DONE: %d makes, %d models, %d base_vehicles upserted via %d API calls in %.1fs",
                 len(seen_make_ids), len(seen_model_ids), len(seen_base_vehicle_ids),
                 api_call_count, time.time() - rate_t0)

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
