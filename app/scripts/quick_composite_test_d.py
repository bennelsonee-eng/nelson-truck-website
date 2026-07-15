"""Quick "option D" sanity composite — does a 15-20 deg plow on a 0 deg truck actually look bad?

Drops the MVP3 transparent on three different 2500 trucks at the same
position and scale, so the only variable is the truck's camera angle.
Outputs three PNGs plus an HTML page showing them side by side.

Trucks compared:
  v3-head-on  : flux_truck_15deg_v3/2500_seed1337.png  (~ 0 deg, fresh render)
  v2-3q       : trucks/renders_3q/2500.png             (~30 deg, current 3/4)
  original-h  : trucks/renders/2500.png                (~ 0 deg, original head-on)

Plow:
  WEST-MVP3MS86-EQP/hero_transparent.png   (~15-20 deg, baked into source)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1].parent
SKUS = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
TRUCKS_OLD = REPO / "app" / "backend" / "static" / "trucks"
TRUCKS_NEW = REPO / "wan_test_output" / "flux_truck_15deg_v3"
OUT_DIR = REPO / "wan_test_output" / "option_d_comparison"

PLOW = SKUS / "WEST-MVP3MS86-EQP" / "hero_transparent.png"

# (label, truck_path)
TRUCK_VARIANTS = [
    ("v3-head-on (~0 deg)",  TRUCKS_NEW / "2500_seed1337.png"),
    ("v2-3q (~30 deg)",      TRUCKS_OLD / "renders_3q" / "2500.png"),
    ("original-h (~0 deg)",  TRUCKS_OLD / "renders" / "2500.png"),
]

# Plow placement (uniform across all trucks for fair angle comparison)
# Truck images are 1024x576. The grille bottom is around y=400, plow centered horizontally.
PLOW_CENTER_X_RATIO = 0.50   # horizontal center
PLOW_CENTER_Y_RATIO = 0.72   # below bumper line
PLOW_WIDTH_RATIO    = 0.55   # 55% of truck width — 8'6" plow on a Ford F-250 reads about right


def composite_plow_on_truck(truck_path: Path, plow_path: Path, label: str) -> Image.Image:
    truck = Image.open(truck_path).convert("RGBA")
    plow = Image.open(plow_path).convert("RGBA")

    Tw, Th = truck.size
    target_w = int(Tw * PLOW_WIDTH_RATIO)
    aspect = plow.height / plow.width
    target_h = int(target_w * aspect)
    plow_resized = plow.resize((target_w, target_h), Image.LANCZOS)

    cx = int(Tw * PLOW_CENTER_X_RATIO)
    cy = int(Th * PLOW_CENTER_Y_RATIO)
    paste_x = cx - target_w // 2
    paste_y = cy - target_h // 2

    out = truck.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    if not PLOW.exists():
        print(f"missing plow: {PLOW}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for label, truck_path in TRUCK_VARIANTS:
        if not truck_path.exists():
            print(f"  ! missing truck: {truck_path}")
            continue
        result = composite_plow_on_truck(truck_path, PLOW, label)
        slug = label.split()[0].replace("(", "").replace(")", "").replace("~", "")
        out_path = OUT_DIR / f"composite_{slug}.png"
        result.save(out_path)
        saved.append((label, out_path))
        print(f"  saved {out_path.name}  ({result.size[0]}x{result.size[1]})")

    # Build a comparison HTML
    html_path = OUT_DIR / "_compare.html"
    cards = "".join(
        f'<div class="card"><h3>{label}</h3>'
        f'<img src="{p.name}"><div class="path">{p.name}</div></div>'
        for label, p in saved
    )
    html_path.write_text(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>Option D — angle mismatch sanity check</title>
<style>
  body {{ margin:0; font-family:-apple-system,system-ui,Segoe UI,sans-serif;
          background:#1f2937; color:#fff; padding:20px; }}
  h1 {{ margin:0 0 8px 0; font-size:18px; font-weight:600; }}
  p  {{ margin:0 0 18px 0; color:#9ca3af; font-size:13px; }}
  .grid {{ display:grid; grid-template-columns:1fr; gap:18px; max-width:1200px; }}
  .card {{ background:#111827; border-radius:6px; padding:10px;
           box-shadow:0 1px 3px rgba(0,0,0,0.4); }}
  .card h3 {{ margin:0 0 8px 0; font-size:14px; font-weight:600; color:#10b981; }}
  .card img {{ width:100%; height:auto; border-radius:4px; display:block; }}
  .path {{ margin-top:6px; font-family:ui-monospace,Consolas,monospace;
           font-size:11px; color:#6b7280; }}
</style></head><body>
<h1>Option D — does a 15-20 deg plow look bad on a 0 deg truck?</h1>
<p>MVP3 transparent at identical position and scale on three Ford F-250 variants. Only variable: truck camera angle.</p>
<div class="grid">{cards}</div>
</body></html>""",
        encoding="utf-8",
    )
    print(f"\nopen: file:///{html_path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
