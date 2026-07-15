"""Audit the 61 hero_transparent.png plow extracts to flag truck-contaminated ones.

Heuristic:
  - A clean plow extract has lots of TRANSPARENT pixels (alpha=0) outside
    the plow body — usually 60-80% of the image area is transparent.
  - A contaminated extract (truck still in background) has a low transparent
    fraction because the white-mask extraction failed and left the truck.

We compute the alpha-zero ratio per image and sort.  Anything below ~30%
transparency is suspect — either the extraction failed, or the plow itself
fills most of the frame.

Output:
  - Console table: SKU, transparent_pct, suspected_contaminated_flag
  - JSON file: app/backend/static/snow-plows/_extract_audit.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUTPUT_JSON = REPO / "app" / "backend" / "static" / "snow-plows" / "_extract_audit.json"


def transparency_ratio(path: Path) -> float:
    """Returns the fraction of pixels with alpha == 0 (fully transparent)."""
    img = Image.open(path).convert("RGBA")
    arr = np.asarray(img)
    alpha = arr[:, :, 3]
    return float((alpha == 0).sum()) / alpha.size


def main() -> int:
    rows = []
    for sku_dir in sorted(SKUS_DIR.iterdir()):
        if not sku_dir.is_dir() or sku_dir.name.startswith("_"):
            continue
        transparent_path = sku_dir / "hero_transparent.png"
        meta_path = sku_dir / "meta.json"
        if not transparent_path.exists():
            continue
        ratio = transparency_ratio(transparent_path)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            title = meta.get("title", "")
        except Exception:
            title = ""
        rows.append({
            "sku": sku_dir.name,
            "transparency_pct": round(ratio * 100, 1),
            "title": title[:60],
            "suspect": ratio < 0.30,
        })

    # Sort by transparency ascending — most suspect first
    rows.sort(key=lambda r: r["transparency_pct"])

    OUTPUT_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    suspect_count = sum(1 for r in rows if r["suspect"])
    print(f"Audited {len(rows)} extracts.  {suspect_count} flagged as suspect (<30% transparent).")
    print()
    print(f"{'SKU':<22}  {'trans%':>7}  {'sus?':>4}  title")
    print("-" * 95)
    for r in rows[:30]:
        flag = "❗" if r["suspect"] else "  "
        print(f"{r['sku']:<22}  {r['transparency_pct']:>6.1f}%  {flag:>4}  {r['title']}")
    print()
    print(f"Saved full audit to: {OUTPUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
