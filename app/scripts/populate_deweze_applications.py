"""populate_deweze_applications.py — Load deweze_kits.json into deweze_application table.

The JSON was produced by scrape_deweze_catalog.py and contains 293
unique kits with full YMM applicability.  Some kits' `make` field has
comma-joined values (e.g., "Chevy, Chevy") from our scrape dedup —
we split those into multiple rows per kit so the drill-down can match
on any individual make.  Same for engine_or_model.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

import asyncpg


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("deweze_app")

DATA = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps"
KITS_JSON = DATA / "deweze_kits.json"


def split_field(val: str | None) -> list[str]:
    """Split a comma-joined dedup field into distinct values, preserving order."""
    if not val:
        return [""]
    parts = [p.strip() for p in val.split(",")]
    seen = set()
    out = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out or [""]


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        data = json.loads(KITS_JSON.read_text(encoding="utf-8"))
        kits = data["kits"]
        log.info("Loaded %d kits from %s", len(kits), KITS_JSON.name)

        # Clear and rebuild
        await conn.execute(
            "DELETE FROM deweze_application WHERE product_id IN "
            "(SELECT id FROM product WHERE brand_id = 91)"
        )

        # Build SKU → product_id map for fast lookup
        rows = await conn.fetch(
            "SELECT id, sku FROM product WHERE brand_id = 91"
        )
        sku_to_pid = {r["sku"]: r["id"] for r in rows}
        log.info("Mapping %d DewEze products by SKU", len(sku_to_pid))

        inserted = 0
        missing = 0
        for kit in kits:
            num = kit["number"]
            sku = f"DWZ-{num}"
            pid = sku_to_pid.get(sku)
            if pid is None:
                missing += 1
                continue
            # Split comma-joined makes + engines (from scrape dedup)
            makes = split_field(kit.get("make"))
            engines = split_field(kit.get("engine_or_model"))
            year_start = kit.get("engine_start_year")
            year_end = kit.get("engine_end_year")
            engine_size = (kit.get("engine_size") or "").strip()
            engine_fuel = (kit.get("engine_fuel") or "").strip()
            pump_short = (kit.get("pump_type_short") or "").strip()
            pump_name = (kit.get("pump_type_name") or "").strip()
            pump_port = (kit.get("pump_port") or "").strip()
            belt = (kit.get("belt") or "").strip()
            clutch_cfg = (kit.get("clutch_configuration") or "").strip()
            obsolete = bool(kit.get("obsolete"))

            # Cartesian product of makes × engines (often 1×1 = 1 row)
            for make in makes:
                for engine in engines:
                    await conn.execute(
                        """
                        INSERT INTO deweze_application (
                            product_id, make, engine_or_model, engine_size,
                            engine_fuel, year_start, year_end,
                            pump_type_short, pump_type_name, pump_port,
                            belt, clutch_configuration, obsolete)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        """,
                        pid, make, engine[:200], engine_size[:20],
                        engine_fuel[:20], year_start, year_end,
                        pump_short[:10], pump_name[:200], pump_port[:30],
                        belt[:80], clutch_cfg[:80], obsolete,
                    )
                    inserted += 1

        log.info("inserted=%d rows (skipped %d kits w/ no matching product)", inserted, missing)
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
