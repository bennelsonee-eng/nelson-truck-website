"""V2 audit: identify truly-clean "floating" plow extracts vs truck-contaminated.

The user's insight: a clean floating plow has TRANSPARENT borders all around
its body.  A truck-contaminated extract has truck pixels extending to the
image edges (truck cab/roof at top, fenders at sides, etc.).

Heuristics layered:
  1. EDGE TRANSPARENCY — fraction of edge-row/col pixels that are alpha=0
     - Clean floating plow: >85% transparent borders (truck cab/snow markers
       OK if very thin)
     - Truck-contaminated: lower (truck body touching edges)
  2. TOP-ROW TRANSPARENCY — top of image specifically (where truck cab usually
     contaminates).  >80% transparent = good.
  3. CENTER-MASS LOCATION — clean plow body centered in lower-middle; truck-
     contaminated has center-of-mass shifted toward where the truck is

Output: detailed JSON + console table sorted by likely-contamination.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUTPUT_JSON = REPO / "app" / "backend" / "static" / "snow-plows" / "_extract_audit_v2.json"


def audit_image(path: Path) -> dict:
    img = Image.open(path).convert("RGBA")
    arr = np.asarray(img)
    alpha = arr[:, :, 3]
    h, w = alpha.shape

    # Overall transparency
    overall_trans = float((alpha == 0).sum()) / alpha.size

    # Edge transparency — top, bottom, left, right rows/cols
    border_w = max(1, h // 30)  # ~3% margin
    top_band = alpha[:border_w, :]
    bot_band = alpha[-border_w:, :]
    left_band = alpha[:, :border_w]
    right_band = alpha[:, -border_w:]
    top_trans = float((top_band == 0).sum()) / top_band.size
    bot_trans = float((bot_band == 0).sum()) / bot_band.size
    left_trans = float((left_band == 0).sum()) / left_band.size
    right_trans = float((right_band == 0).sum()) / right_band.size
    avg_edge_trans = (top_trans + bot_trans + left_trans + right_trans) / 4

    # Suspicion score — high score = likely contaminated
    # Top of image is the strongest signal (truck cab there)
    suspicion = 0.0
    if top_trans < 0.5:
        suspicion += 3.0  # truck cab at top is the smoking gun
    elif top_trans < 0.75:
        suspicion += 1.0
    if avg_edge_trans < 0.6:
        suspicion += 2.0
    if overall_trans < 0.40:
        suspicion += 1.0

    return {
        "overall_trans_pct": round(overall_trans * 100, 1),
        "top_trans_pct": round(top_trans * 100, 1),
        "bottom_trans_pct": round(bot_trans * 100, 1),
        "left_trans_pct": round(left_trans * 100, 1),
        "right_trans_pct": round(right_trans * 100, 1),
        "avg_edge_trans_pct": round(avg_edge_trans * 100, 1),
        "suspicion_score": round(suspicion, 1),
        "verdict": (
            "contaminated" if suspicion >= 3.0
            else "questionable" if suspicion >= 1.0
            else "clean"
        ),
    }


def main() -> int:
    rows = []
    for sku_dir in sorted(SKUS_DIR.iterdir()):
        if not sku_dir.is_dir() or sku_dir.name.startswith("_"):
            continue
        transparent_path = sku_dir / "hero_transparent.png"
        meta_path = sku_dir / "meta.json"
        if not transparent_path.exists():
            continue
        audit = audit_image(transparent_path)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            title = meta.get("title", "")
        except Exception:
            title = ""
        rows.append({
            "sku": sku_dir.name,
            **audit,
            "title": title[:50],
        })

    rows.sort(key=lambda r: (-r["suspicion_score"], r["overall_trans_pct"]))
    OUTPUT_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    contaminated = [r for r in rows if r["verdict"] == "contaminated"]
    questionable = [r for r in rows if r["verdict"] == "questionable"]
    clean = [r for r in rows if r["verdict"] == "clean"]

    print(f"Audited {len(rows)} extracts.")
    print(f"  CONTAMINATED: {len(contaminated)}")
    print(f"  QUESTIONABLE: {len(questionable)}")
    print(f"  CLEAN:        {len(clean)}")
    print()

    print("--- CONTAMINATED (likely truck attached) ---")
    print(f"{'SKU':<22} {'top':>6} {'avg_edge':>9} {'overall':>8} {'sus':>4}  title")
    for r in contaminated:
        print(f"{r['sku']:<22} {r['top_trans_pct']:>5.1f}% {r['avg_edge_trans_pct']:>8.1f}% "
              f"{r['overall_trans_pct']:>7.1f}% {r['suspicion_score']:>4.1f}  {r['title']}")
    print()
    print("--- QUESTIONABLE ---")
    for r in questionable:
        print(f"{r['sku']:<22} {r['top_trans_pct']:>5.1f}% {r['avg_edge_trans_pct']:>8.1f}% "
              f"{r['overall_trans_pct']:>7.1f}% {r['suspicion_score']:>4.1f}  {r['title']}")
    print()
    print(f"Saved full audit to: {OUTPUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
