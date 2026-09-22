"""Verify the truck-body manufacturer content points only at our own server.

Scans every place the importers write for the Knapheide / CM bodies --
images (url + thumb), downloads, descriptions, feature/option text, attribute
values and spec tables -- and lists any http(s) link that isn't ours.
`product_image.source_url` and the "Source:" note on a download are provenance,
never sent to the page, so they are not links and are not checked.

Exit code 1 if anything points off-site, so it can gate a deploy.

Usage:
    python app/scripts/check_manufacturer_content_local.py
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve()
ENV_FILE = HERE.parent.parent / ".env"
DATA_DIR = HERE.parent.parent.parent / "discovery" / "manufacturer_data"
MAPS = ("kn_model_map.json", "cm_model_map.json", "rugby_model_map.json", "dal_model_map.json")
URL = re.compile(r"https?://[^\s\"'<>)]+", re.I)
# Nelson site: nelsontruck.com (launch host) and nelsontruckequipment.com (preview).
# titantruck.com counts as off-site here -- a Nelson page must not load a sister site's files.
OURS = re.compile(r"^https?://([a-z0-9-]+\.)*(nelsontruck\.com|nelsontruckequipment\.com|localhost|127\.0\.0\.1)(:\d+)?/", re.I)


def db_dsn() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().replace("postgresql+asyncpg://", "postgresql://")
    raise SystemExit("DATABASE_URL not found in app/.env")


def offsite(text: str | None) -> list[str]:
    return [u for u in URL.findall(text or "") if not OURS.match(u)]


async def main() -> int:
    pids = sorted({int(p) for m in MAPS for p in json.loads((DATA_DIR / m).read_text(encoding="utf-8"))})
    conn = await asyncpg.connect(db_dsn())
    problems: list[tuple[str, int, str]] = []
    try:
        checks = {
            "product_image.url": "SELECT product_id, url AS v FROM product_image WHERE product_id = ANY($1::int[])",
            "product_image.thumb_url": "SELECT product_id, thumb_url AS v FROM product_image WHERE product_id = ANY($1::int[])",
            "product_resource.url": "SELECT product_id, url AS v FROM product_resource WHERE product_id = ANY($1::int[])",
            "product.description": "SELECT id AS product_id, description AS v FROM product WHERE id = ANY($1::int[])",
            "product.extended_description": "SELECT id AS product_id, extended_description AS v FROM product WHERE id = ANY($1::int[])",
            "product_description.text": "SELECT product_id, text AS v FROM product_description WHERE product_id = ANY($1::int[])",
            "product_attribute.value": "SELECT product_id, attribute_value AS v FROM product_attribute WHERE product_id = ANY($1::int[])",
            "product_spec_table": "SELECT product_id, headers::text || rows::text || coalesce(note,'') AS v "
                                  "FROM product_spec_table WHERE product_id = ANY($1::int[])",
        }
        counts = {}
        for label, sql in checks.items():
            rows = await conn.fetch(sql, pids)
            counts[label] = len(rows)
            for r in rows:
                v = r["v"]
                # a stored path like /static/... is ours; only absolute URLs can leave the site
                for u in offsite(v if v and "://" in v else None):
                    problems.append((label, r["product_id"], u))
    finally:
        await conn.close()

    print(f"products checked: {len(pids)}")
    for label, n in counts.items():
        print(f"  {label:<30} {n:>5} values")
    if problems:
        print(f"\nOFF-SITE LINKS: {len(problems)}")
        for label, pid, u in problems[:50]:
            print(f"  {label:<30} product {pid}: {u}")
        return 1
    print("\nOK - nothing on these product pages points off our server.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
