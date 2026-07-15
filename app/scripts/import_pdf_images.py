"""Import PDF part images into the product_image table.

Supports multiple brands via --brand flag:
  BUY   (default) — Buyers Products  (SKU: BUY-{pn} or SNOW-{pn})
  WEST            — Western Plows    (SKU: WEST-{pn})

Steps:
1. Read manifest.json from the extraction output
2. Match part numbers to product SKUs
3. Copy images to the static brand_images directory
4. Delete old pdf_extraction rows from product_image for that brand
5. Insert new rows

Usage:
    python import_pdf_images.py                        # Buyers (default)
    python import_pdf_images.py --brand WEST           # Western
    python import_pdf_images.py --brand WEST --dry-run # preview
    python import_pdf_images.py --pn 16061031          # one part
"""
from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("ERROR: pip install psycopg2-binary"); sys.exit(1)

STATIC_DIR = Path("/home/titan/titan-truck-website/app/backend/static/brand_images")
DB_DSN = "host=localhost port=5433 dbname=titan_web user=postgres password=titan2026"

# Brand configurations: manifest path, SKU prefixes, static subdir
BRAND_CONFIG = {
    "BUY": {
        "manifest": Path("/tmp/buyers_pdf_images/manifest.json"),
        "sku_query": "sku LIKE 'BUY-%%' OR sku LIKE 'SNOW-%%'",
        "strip_prefix": {"BUY-": 4, "SNOW-": 5},
        "static_subdir": "BUY",
        "label": "Buyers Products",
    },
    "WEST": {
        "manifest": Path("/tmp/western_pdf_images/manifest.json"),
        "sku_query": "sku LIKE 'WEST-%%'",
        "strip_prefix": {"WEST-": 5},
        "static_subdir": "WEST",
        "label": "Western Plows",
    },
}


def get_sku_map(conn, brand="BUY"):
    """Build part_number -> (product_id, sku) map for a brand."""
    cfg = BRAND_CONFIG[brand]
    cur = conn.cursor()
    cur.execute(f"SELECT id, sku FROM product WHERE {cfg['sku_query']}")
    sku_map = {}
    for pid, sku in cur.fetchall():
        for prefix, length in cfg["strip_prefix"].items():
            if sku.startswith(prefix):
                pn = sku[length:]
                sku_map[pn] = (pid, sku)
                break
    cur.close()
    return sku_map


def import_images(dry_run=False, target_pn=None, brand="BUY"):
    cfg = BRAND_CONFIG[brand]
    manifest_path = cfg["manifest"]
    brand_prefix = cfg["static_subdir"]

    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found. Run extract_pdf_part_images.py first.")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    print(f"Manifest entries: {len(manifest)}")

    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False

    sku_map = get_sku_map(conn, brand)
    print(f"Products in DB: {len(sku_map)} {cfg['label']} SKUs")

    # Match manifest entries to products, deduplicating by part number
    # When a part appears in multiple PDFs, pick the one with most curves
    candidates = {}  # pn -> best entry
    unmatched_pns = set()
    for entry in manifest:
        pn = entry["part_number"]
        if target_pn and pn != target_pn:
            continue

        if pn not in sku_map:
            unmatched_pns.add(pn)
            continue

        # Keep the entry with the most outline curves (best highlight)
        if pn not in candidates or entry["outline_curves"] > candidates[pn]["outline_curves"]:
            pid, sku = sku_map[pn]
            candidates[pn] = {**entry, "product_id": pid, "sku": sku}

    matched = list(candidates.values())
    print(f"Matched to products: {len(matched)} (deduplicated from {len(manifest)} entries)")
    if unmatched_pns:
        print(f"Unmatched part numbers: {len(unmatched_pns)}")
        if len(unmatched_pns) <= 20:
            for pn in sorted(unmatched_pns):
                print(f"  {pn}")

    if dry_run:
        print("\n[DRY RUN] Would import:")
        for m in matched[:10]:
            print(f"  {m['sku']:<20} <- {m['part_number']}")
        if len(matched) > 10:
            print(f"  ... and {len(matched)-10} more")
        conn.close()
        return

    # Delete old pdf_extraction images for this brand only
    cur = conn.cursor()
    if target_pn:
        if target_pn in sku_map:
            pid = sku_map[target_pn][0]
            cur.execute(
                "DELETE FROM product_image WHERE product_id = %s AND legacy_origin = 'pdf_extraction'",
                (pid,))
            print(f"\nDeleted {cur.rowcount} old images for {target_pn}")
    else:
        # Delete only for products belonging to this brand
        product_ids = [v[0] for v in sku_map.values()]
        if product_ids:
            cur.execute(
                "DELETE FROM product_image WHERE legacy_origin = 'pdf_extraction' "
                "AND product_id = ANY(%s)", (product_ids,))
            print(f"\nDeleted {cur.rowcount} old pdf_extraction images ({cfg['label']})")

    # Copy files and insert rows
    inserted = 0
    errors = 0
    for m in matched:
        sku = m["sku"]
        sku_dir = STATIC_DIR / brand_prefix / sku.replace("-", "")
        sku_dir.mkdir(parents=True, exist_ok=True)

        # Copy main image
        main_src = Path(m["main_image"])
        if main_src.exists():
            main_dst = sku_dir / "00_pdf_outline.png"
            shutil.copy2(str(main_src), str(main_dst))
            main_url = f"/static/brand_images/{brand_prefix}/{sku.replace('-', '')}/00_pdf_outline.png"

            cur.execute("""
                INSERT INTO product_image
                    (product_id, url, alt_text, sort_order, is_primary, legacy_origin)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (m["product_id"], main_url,
                  f"{m['description']} - highlighted on exploded view",
                  90, False, "pdf_extraction"))
            inserted += 1
        else:
            errors += 1

        # Copy secondary (full page) image
        sec_src = Path(m["secondary_image"])
        if sec_src.exists():
            sec_dst = sku_dir / "01_pdf_exploded.png"
            shutil.copy2(str(sec_src), str(sec_dst))
            sec_url = f"/static/brand_images/{brand_prefix}/{sku.replace('-', '')}/01_pdf_exploded.png"

            cur.execute("""
                INSERT INTO product_image
                    (product_id, url, alt_text, sort_order, is_primary, legacy_origin)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (m["product_id"], sec_url,
                  f"{m['description']} - exploded view",
                  91, False, "pdf_extraction"))
            inserted += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nImported {inserted} images for {len(matched)} products")
    if errors:
        print(f"  ({errors} source files missing)")


def main():
    parser = argparse.ArgumentParser(
        description="Import PDF part images into product_image table")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pn", help="Import one part number only")
    parser.add_argument("--brand", choices=["BUY", "WEST"], default="BUY",
                        help="Brand: BUY (Buyers, default) or WEST (Western)")
    args = parser.parse_args()

    import_images(dry_run=args.dry_run, target_pn=args.pn, brand=args.brand)


if __name__ == "__main__":
    main()
