"""copy_nelson_images_to_hetzner.py — Copy Nelson ERP brand images to Titan.

Nelson ERP has Bing-scraped product images at:
    C:/Users/Ben/nelson-erp/backend/uploads/parts/{ourparts_num}/bing_*.jpg

For each Nelson image whose ourparts_num matches a Titan product via
tte_ourparts_num (set by import_brand_catalog.py / link_titan_inventory_v2.py),
we:
  1. Copy the file to the Titan-side asset dir
       app/backend/static/brand_images/{prod_code}/{ourparts_num}/{filename}
  2. INSERT a product_image row pointing at the serve URL
       /static/brand_images/{prod_code}/{ourparts_num}/{filename}

Reads nelson_erp_image_paths.csv (dumped from Nelson ERP earlier today).
Run from a host that has BOTH Nelson ERP filesystem access AND can write
to the Hetzner static dir.  Practically: run locally, then rsync the
static dir up; OR rsync the images dir up first and run on Hetzner.

This script implements the LOCAL phase (copy from Nelson to a staging
dir we'll rsync up).
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path
from collections import defaultdict


CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps" / "nelson_erp_image_paths.csv"
# Stage on local disk; rsync up after.
STAGE = Path(__file__).resolve().parent.parent / "data" / "stage_brand_images"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    if not CSV_PATH.exists():
        print(f"missing {CSV_PATH}")
        return

    by_part: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as fp:
        for r in csv.DictReader(fp):
            key = (r["prod_code"], r["ourparts_num"])
            by_part[key].append({
                "image_path": r["image_path"],
                "is_primary": (r["is_primary"].lower() == "t"),
                "sort_order": int(r["sort_order"] or 0),
            })

    copied = 0
    missing = 0
    bytes_copied = 0
    for (prod_code, ou), images in by_part.items():
        # Sanitize ourparts_num for filesystem use
        safe_ou = ou.replace("/", "_").replace("\\", "_").replace(" ", "_")
        # Limit to top 3 images per part (primary + 2 alts) to keep transfer small
        images.sort(key=lambda i: (not i["is_primary"], i["sort_order"]))
        for idx, img in enumerate(images[:3]):
            # Nelson ERP image path uses Windows-style separators inconsistently
            src_str = img["image_path"].replace("\\", "/").replace("C:/", "C:/")
            src = Path(src_str)
            if not src.exists():
                missing += 1
                continue
            dest_dir = STAGE / prod_code / safe_ou
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_name = f"{idx:02d}_{src.name}"
            dest = dest_dir / dest_name
            if dest.exists():
                continue
            shutil.copy2(src, dest)
            copied += 1
            bytes_copied += dest.stat().st_size

    mb = bytes_copied / (1024 * 1024)
    print(f"Done: copied={copied}, missing={missing}, total {mb:.1f} MB")
    print(f"Stage dir: {STAGE}")
    print(f"Next: rsync {STAGE} to Hetzner /home/titan/titan-truck-website/app/backend/static/brand_images/")


if __name__ == "__main__":
    main()
