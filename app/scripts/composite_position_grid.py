"""Generate a 3x3 grid of (plow_width × plow_y) positioning options.

Helps eyeball the right scale and vertical placement for MVP3 on the v2-3q
2500 truck without overflowing the frame. Outputs 9 PNGs and an HTML page.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1].parent
TRUCK = REPO / "app" / "backend" / "static" / "trucks" / "renders_3q" / "2500.png"
PLOW = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUT_DIR = REPO / "wan_test_output" / "position_grid"

W_RATIOS = [0.50, 0.60, 0.70]
Y_RATIOS = [0.55, 0.60, 0.65]


def composite(truck_img: Image.Image, plow_img: Image.Image, w_ratio: float, y_ratio: float) -> Image.Image:
    Tw, Th = truck_img.size
    target_w = int(Tw * w_ratio)
    aspect = plow_img.height / plow_img.width
    target_h = int(target_w * aspect)
    plow_resized = plow_img.resize((target_w, target_h), Image.LANCZOS)
    cx = Tw // 2
    cy = int(Th * y_ratio)
    paste_x = cx - target_w // 2
    paste_y = cy - target_h // 2
    out = truck_img.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    truck = Image.open(TRUCK).convert("RGBA")
    plow = Image.open(PLOW).convert("RGBA")
    print(f"truck {truck.size}  plow {plow.size}")

    cells = []
    for w_r in W_RATIOS:
        for y_r in Y_RATIOS:
            out = composite(truck, plow, w_r, y_r)
            name = f"w{int(w_r*100)}_y{int(y_r*100)}.png"
            out.save(OUT_DIR / name)
            cells.append((w_r, y_r, name))
            print(f"  saved {name}")

    rows = ""
    for w_r in W_RATIOS:
        cards = ""
        for y_r in Y_RATIOS:
            name = f"w{int(w_r*100)}_y{int(y_r*100)}.png"
            cards += f'<div class="card"><h3>w={w_r:.2f} y={y_r:.2f}</h3><img src="{name}"></div>'
        rows += f'<div class="row">{cards}</div>'

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Position grid — MVP3 on 2500 v2-3q</title>
<style>
  body {{ margin:0; font-family:-apple-system,system-ui,sans-serif;
          background:#1f2937; color:#fff; padding:14px; }}
  h1 {{ margin:0 0 12px 0; font-size:16px; }}
  .row {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:8px; }}
  .card {{ background:#111827; padding:6px; border-radius:4px; }}
  .card h3 {{ margin:0 0 4px 0; font-size:11px; font-family:ui-monospace,Consolas,monospace; color:#10b981; }}
  .card img {{ width:100%; height:auto; display:block; border-radius:2px; }}
</style></head><body>
<h1>Position grid — MVP3 on 2500 v2-3q (rows: width ratio, cols: y ratio)</h1>
{rows}
</body></html>"""
    (OUT_DIR / "_grid.html").write_text(html, encoding="utf-8")
    print(f"\nopen: file:///{(OUT_DIR / '_grid.html').as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
