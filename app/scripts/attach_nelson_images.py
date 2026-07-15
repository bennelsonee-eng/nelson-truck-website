"""attach_nelson_images.py — Insert ProductImage rows for the brand-image files
already copied to the Hetzner static dir at:

    app/backend/static/brand_images/{prod_code}/{ourparts_num}/{filename}

For each file, finds the Titan product via product.tte_ourparts_num and
inserts a ProductImage row pointing at /static/brand_images/... URL.

Idempotent — skips if a product_image row already exists for that URL.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("attach_nelson")

STATIC_DIR = Path(__file__).resolve().parent.parent / "backend" / "static" / "brand_images"


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        if not STATIC_DIR.exists():
            log.error("Missing %s", STATIC_DIR)
            return

        # Walk the staged file tree
        files_per_part: dict[str, list[Path]] = {}
        for prod_dir in STATIC_DIR.iterdir():
            if not prod_dir.is_dir():
                continue
            for ou_dir in prod_dir.iterdir():
                if not ou_dir.is_dir():
                    continue
                files = sorted(ou_dir.glob("*"))
                files_per_part[ou_dir.name] = files

        log.info("Image-bearing ourparts dirs: %d", len(files_per_part))

        # Resolve each ourparts_num → product_id via tte_ourparts_num
        # (we use case-insensitive match because the linker normalized to upper).
        ous = list(files_per_part.keys())
        log.info("Resolving %d ourparts_num to Titan products…", len(ous))
        rows = await conn.fetch(
            "SELECT id, tte_ourparts_num FROM product "
            "WHERE UPPER(tte_ourparts_num) = ANY($1::text[])",
            [o.upper() for o in ous],
        )
        # Map: ourparts_upper → product_id
        pid_by_ou: dict[str, int] = {}
        for r in rows:
            pid_by_ou[r["tte_ourparts_num"].upper()] = r["id"]
        log.info("Matched %d / %d", len(pid_by_ou), len(ous))

        inserted = 0
        for ou, files in files_per_part.items():
            pid = pid_by_ou.get(ou.upper())
            if pid is None:
                continue
            # Find the prod_code dir this lives under (parent of ou_dir)
            prod_code = files[0].parent.parent.name if files else "?"
            for idx, fp in enumerate(sorted(files)):
                # Serve URL: /static/brand_images/{prod_code}/{ou}/{filename}
                url = f"/static/brand_images/{prod_code}/{ou}/{fp.name}"
                existing = await conn.fetchval(
                    "SELECT 1 FROM product_image WHERE product_id = $1 AND url = $2",
                    pid, url,
                )
                if existing:
                    continue
                await conn.execute(
                    "INSERT INTO product_image (product_id, url, alt_text, sort_order, "
                    "is_primary, created_at, updated_at) "
                    "VALUES ($1, $2, $3, $4, $5, NOW(), NOW())",
                    pid, url, ou[:200], idx, idx == 0,
                )
                inserted += 1

        log.info("Done: inserted=%d ProductImage rows", inserted)
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
