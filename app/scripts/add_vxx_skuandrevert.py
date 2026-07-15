"""Revert SNOW-16020724 (VXF II) to original VXX II logo, and create a new
SNOW-VXX-EQP SKU for the 10'6" VXX V-plow that Titan also sells.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1].parent
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
MANIFEST = SKUS_DIR / "_manifest.json"


def main() -> int:
    # 1. Restore SNOW-16020724 (VXF II) to original VXXII branding
    vxf_dir = SKUS_DIR / "SNOW-16020724-EQP"
    backup = vxf_dir / "hero_transparent_PRE_VXFSWAP.png"
    target = vxf_dir / "hero_transparent.png"
    if not backup.exists():
        print(f"! missing backup: {backup}")
        return 1
    shutil.copy2(backup, target)
    print(f"restored {target.name} from PRE_VXFSWAP backup")

    # 2. Create a new SNOW-VXX-EQP SKU folder
    vxx_dir = SKUS_DIR / "SNOW-VXX-EQP"
    vxx_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, vxx_dir / "hero_transparent.png")
    print(f"created {vxx_dir.name}/hero_transparent.png")

    # 3. Add SNOW-VXX-EQP to the manifest if not already there
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    skus = data.get("skus", [])
    have_vxx = any(s.get("stockid_sanitized") == "SNOW-VXX-EQP" for s in skus)
    if not have_vxx:
        new_entry = {
            "stockid": "SNOW:VXX-EQP",
            "stockid_sanitized": "SNOW-VXX-EQP",
            "dealerid": "VXX10",
            "brand": "SNOWDOGG®",
            "title": "SNOWDOGG® | VXX 10'6\" V-Plow Snow Plow; 126\" Snow Plow",
            "product_series": "VXX10",
            "product_series_title": "SNOWDOGG® | VXX V-Plow",
            "image_filename": "hero_transparent.png",
            "image_path": "snow-plows/skus/SNOW-VXX-EQP/hero_transparent.png",
            "image_size": (vxx_dir / "hero_transparent.png").stat().st_size,
            "summary_html": "10'6\" VXX V-plow — the wider variant of the VXF II.",
            "categories": [
                "2926|Truck Equipment",
                "2926-3033|Snow & Ice Control",
                "3033-7464|All Snow Plows",
                "3033-7466|V-Plows",
            ],
            "category_tree": [
                "-2926|Truck Equipment",
                "2926-3033|Snow & Ice Control",
                "3033-7464|All Snow Plows",
                "3033-7466|V-Plows",
            ],
        }
        skus.append(new_entry)
        data["skus"] = skus
        MANIFEST.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print("added SNOW-VXX-EQP entry to manifest")
    else:
        print("SNOW-VXX-EQP already in manifest")

    return 0


if __name__ == "__main__":
    sys.exit(main())
