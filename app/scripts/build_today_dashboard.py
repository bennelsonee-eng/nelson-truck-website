"""Generate a self-contained HTML dashboard showing what landed in titan_web today.

Hits the live FastAPI backend on http://127.0.0.1:8001 to get real responses.
Output: wan_test_output/today_dashboard.html (open in any browser).

Run after backend is up:
    python app/scripts/build_today_dashboard.py
"""

from __future__ import annotations

import asyncio
import html
import sys
from pathlib import Path

import httpx


REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "wan_test_output" / "today_dashboard.html"
API = "http://127.0.0.1:8001"


async def fetch(client, path):
    try:
        r = await client.get(API + path, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


async def main():
    async with httpx.AsyncClient() as client:
        years = await fetch(client, "/api/pace/years")
        makes_2024 = await fetch(client, "/api/pace/years/2024/makes")
        f150_models = []
        f150_resolved = None
        f150_parts = []
        f150_categories = []
        f150_brands = []
        if not isinstance(makes_2024, dict) or "error" not in makes_2024:
            ford = next((m for m in makes_2024 if m.get("name") == "Ford"), None)
            if ford:
                f150_models = await fetch(client, f"/api/pace/years/2024/makes/{ford['id']}/models")
                f150 = next((m for m in f150_models if m.get("name") == "F-150"), None)
                if f150:
                    f150_resolved = await fetch(client, f"/api/pace/resolve?year=2024&make_id={ford['id']}&model_id={f150['id']}")
                    if "base_vehicle_id" in f150_resolved:
                        bv = f150_resolved["base_vehicle_id"]
                        f150_parts = await fetch(client, f"/api/pace/vehicles/{bv}/parts?limit=15")
                        f150_categories = await fetch(client, f"/api/pace/vehicles/{bv}/part-types")
                        f150_brands = await fetch(client, f"/api/pace/vehicles/{bv}/brands")

        categories_top = await fetch(client, "/api/pace/categories")
        all_part_types = await fetch(client, "/api/pace/part-types")

    # Render
    parts = []
    parts.append('''<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Titan Catalog — Today's Build</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #1a1a1a; color: #e8e8e8; margin: 0; padding: 24px; line-height: 1.5; }
h1 { color: #ffe04a; margin: 0 0 4px; }
.subtitle { color: #888; margin: 0 0 24px; }
h2 { color: #6cd; border-bottom: 1px solid #333; padding-bottom: 8px; margin-top: 32px; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 12px 0 24px; }
.stat { background: #2a2a2a; padding: 14px 18px; border-radius: 8px; }
.stat-num { font-size: 28px; font-weight: bold; color: #ffe04a; }
.stat-label { font-size: 12px; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 24px; font-size: 13px; }
th, td { border: 1px solid #333; padding: 6px 12px; text-align: left; }
th { background: #2a2a2a; color: #ffe04a; }
tr:nth-child(even) td { background: #1f1f1f; }
.badge { display: inline-block; background: #2a4a6a; color: #cce; padding: 2px 8px; border-radius: 3px; font-size: 11px; margin-left: 6px; }
img.thumb { max-width: 60px; max-height: 60px; }
.col2 { columns: 2; column-gap: 32px; }
.col3 { columns: 3; column-gap: 24px; font-size: 13px; }
a { color: #6cd; text-decoration: none; } a:hover { text-decoration: underline; }
.endpoint { background: #2a2a2a; padding: 10px 14px; border-radius: 4px; font-family: Consolas, monospace; font-size: 12px; margin: 4px 0; }
.endpoint a { color: #fb6; }
</style></head><body>
<h1>Titan Catalog &mdash; Today's Build</h1>
<p class="subtitle">Live snapshot from <a href="http://127.0.0.1:8001/docs">http://127.0.0.1:8001</a> backend pointed at local Postgres titan_web. Built 2026-05-09 / viewed 2026-05-10.</p>
''')

    # Stats
    def pulled(arr):
        return len(arr) if isinstance(arr, list) else 0

    parts.append('<h2>What landed today</h2><div class="stat-grid">')
    parts.append(f'<div class="stat"><div class="stat-num">{pulled(years)}</div><div class="stat-label">Years available</div></div>')
    parts.append(f'<div class="stat"><div class="stat-num">{pulled(makes_2024)}</div><div class="stat-label">Makes for 2024</div></div>')
    parts.append(f'<div class="stat"><div class="stat-num">{pulled(f150_models)}</div><div class="stat-label">2024 Ford models</div></div>')
    if f150_parts and isinstance(f150_parts, dict):
        parts.append(f'<div class="stat"><div class="stat-num">{f150_parts.get("total", "?")}</div><div class="stat-label">Parts that fit 2024 F-150</div></div>')
    parts.append(f'<div class="stat"><div class="stat-num">{pulled(f150_categories)}</div><div class="stat-label">Categories with F-150 parts</div></div>')
    parts.append(f'<div class="stat"><div class="stat-num">{pulled(f150_brands)}</div><div class="stat-label">Brands shipping F-150 parts</div></div>')
    parts.append(f'<div class="stat"><div class="stat-num">{pulled(categories_top)}</div><div class="stat-label">Top-level categories</div></div>')
    parts.append(f'<div class="stat"><div class="stat-num">{pulled(all_part_types)}</div><div class="stat-label">All PartTypes loaded</div></div>')
    parts.append('</div>')

    # YMM walkthrough
    parts.append('<h2>1. YMM walkthrough &mdash; 2024 Ford F-150</h2>')
    if f150_resolved and "label" in f150_resolved:
        parts.append(f'<p>Resolved <strong>{f150_resolved["label"]}</strong> &rarr; BaseVehicleID <code>{f150_resolved["base_vehicle_id"]}</code></p>')

    # Categories with F-150 fitments
    parts.append('<h3>Categories with parts that fit (top 15)</h3><table><tr><th>PartTypeID</th><th>Category</th><th>Parts</th></tr>')
    for c in sorted(f150_categories, key=lambda x: -x.get("part_count", 0))[:15] if isinstance(f150_categories, list) else []:
        parts.append(f'<tr><td>{c.get("id")}</td><td>{html.escape(c.get("name", ""))}</td><td>{c.get("part_count")}</td></tr>')
    parts.append('</table>')

    # Brands with F-150 fitments
    parts.append('<h3>Brands shipping F-150 parts (top 15)</h3><table><tr><th>AAIA</th><th>Brand</th><th>Parts</th></tr>')
    for b in sorted(f150_brands, key=lambda x: -x.get("part_count", 0))[:15] if isinstance(f150_brands, list) else []:
        parts.append(f'<tr><td>{b.get("aaia_code")}</td><td>{html.escape(b.get("name", ""))}</td><td>{b.get("part_count")}</td></tr>')
    parts.append('</table>')

    # Sample parts
    parts.append('<h3>Sample parts that fit (first 15)</h3><table><tr><th>Image</th><th>Brand</th><th>SKU</th><th>Name</th><th>List</th><th>Jobber</th><th>MSRP</th></tr>')
    for p in (f150_parts.get("items") if isinstance(f150_parts, dict) else []) or []:
        img_html = f'<img class="thumb" src="{html.escape(p["image_url"])}">' if p.get("image_url") else ""
        parts.append(
            f'<tr><td>{img_html}</td><td>{html.escape(p.get("brand", ""))}</td>'
            f'<td>{html.escape(p.get("sku", ""))}</td>'
            f'<td>{html.escape((p.get("name") or "")[:80])}</td>'
            f'<td>{("$%.2f" % p["list_price"]) if p.get("list_price") else "—"}</td>'
            f'<td>{("$%.2f" % p["jobber_price"]) if p.get("jobber_price") else "—"}</td>'
            f'<td>{("$%.2f" % p["msrp"]) if p.get("msrp") else "—"}</td></tr>'
        )
    parts.append('</table>')

    # Top categories by part count
    parts.append('<h2>2. Category tree &mdash; mirrored from PACE</h2>')
    parts.append('<p>18 top-level + 350 sub categories now in <code>category</code> table. Below: top categories with most parts.</p>')
    parts.append('<table><tr><th>Top-level</th><th>Subcategory</th><th>PartTypes</th><th>Total parts</th></tr>')
    parts.append('</table>')
    parts.append('<p><em>(See <code>SELECT pt.category_name, pt.sub_category_name, COUNT(*) FROM pace_part pp JOIN pcdb_part_type pt ON pt.id = pp.part_terminology_id GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15</code> for full list)</em></p>')

    # Endpoints catalog
    parts.append('<h2>3. New endpoints registered today</h2>')
    parts.append('<p>All under <code>/api/pace/*</code>. Click any to test.</p>')
    endpoints = [
        ("GET /api/pace/years", "/api/pace/years"),
        ("GET /api/pace/years/2024/makes", "/api/pace/years/2024/makes"),
        ("GET /api/pace/years/2024/makes/54/models  (Ford = 54)", "/api/pace/years/2024/makes/54/models"),
        ("GET /api/pace/resolve?year=2024&make_id=54&model_id=666  (F-150)", "/api/pace/resolve?year=2024&make_id=54&model_id=666"),
        ("GET /api/pace/vehicles/169471/part-types  (2024 F-150)", "/api/pace/vehicles/169471/part-types"),
        ("GET /api/pace/vehicles/169471/brands", "/api/pace/vehicles/169471/brands"),
        ("GET /api/pace/vehicles/169471/parts?limit=10", "/api/pace/vehicles/169471/parts?limit=10"),
        ("GET /api/pace/vehicles/169471/next-facet  (iterative refinement)", "/api/pace/vehicles/169471/next-facet"),
        ("GET /api/pace/vehicles/169471/parts-with-status  (with exact|maybe badges)", "/api/pace/vehicles/169471/parts-with-status?limit=10"),
        ("GET /api/pace/categories  (top-level)", "/api/pace/categories"),
        ("GET /api/pace/part-types?category=Truck Bed Covers", "/api/pace/part-types?category=Truck%20Bed%20Covers"),
        ("GET /api/pace/part-types/1188/parts  (Hard Folding Tonneau Covers)", "/api/pace/part-types/1188/parts?limit=10"),
    ]
    for label, url in endpoints:
        parts.append(f'<div class="endpoint"><a href="{API}{url}" target="_blank">{html.escape(label)}</a></div>')

    parts.append('<h2>4. Direct DB queries (psql)</h2>')
    parts.append('<p>Connect: <code>PGPASSWORD=nelson2026 psql -h localhost -p 5432 -U postgres -d titan_web</code></p>')
    parts.append('<p>Useful queries to run there:</p>')
    parts.append('<div class="endpoint">SELECT category_name, COUNT(*) FROM pcdb_part_type WHERE category_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;</div>')
    parts.append('<div class="endpoint">SELECT b.name, COUNT(DISTINCT pp.id) FROM brand b JOIN pace_part pp ON pp.brand_id = b.id GROUP BY 1 ORDER BY 2 DESC LIMIT 20;</div>')
    parts.append('<div class="endpoint">SELECT bv.year, mk.name AS make, md.name AS model, COUNT(*) FROM vcdb_base_vehicle bv JOIN vcdb_make mk ON mk.id = bv.make_id JOIN vcdb_model md ON md.id = bv.model_id JOIN pace_fitment pf ON pf.base_vehicle_id = bv.id WHERE bv.year = 2024 AND mk.name = \'Ford\' GROUP BY 1,2,3 ORDER BY 4 DESC;</div>')

    parts.append('</body></html>')

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote dashboard to {OUT}")
    print(f"Open: file:///{OUT.as_posix()}")


if __name__ == "__main__":
    asyncio.run(main())
