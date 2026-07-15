"""Overlay anchor click points on truck images for debugging.

For each truck, draws a red line between bumper-L and bumper-R clicks
plus tiny crosshairs at each point. Helps diagnose scale issues by
showing exactly where the user clicked vs where the bumper actually is.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1].parent
TRUCKS = REPO / "app" / "backend" / "static" / "trucks" / "renders_3q_mirrored"
OUT = REPO / "wan_test_output" / "anchor_debug"
ANCHORS = Path.home() / "Downloads" / "plow_truck_anchors.json"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(ANCHORS.read_text(encoding="utf-8"))
    rows = []
    for cls, e in (data.get("trucks") or {}).items():
        pts = e.get("points") or []
        if len(pts) != 2:
            continue
        src = TRUCKS / f"{cls}.png"
        if not src.exists():
            continue
        img = Image.open(src).convert("RGBA")
        Tw, Th = img.size
        L = (int(pts[0]["xr"] * Tw), int(pts[0]["yr"] * Th))
        R = (int(pts[1]["xr"] * Tw), int(pts[1]["yr"] * Th))
        d = ImageDraw.Draw(img)
        d.line([L, R], fill=(255, 64, 64, 255), width=4)
        for (x, y) in (L, R):
            d.line([(x - 12, y), (x + 12, y)], fill=(255, 255, 0, 255), width=3)
            d.line([(x, y - 12), (x, y + 12)], fill=(255, 255, 0, 255), width=3)
        # Annotation
        px_w = abs(R[0] - L[0])
        d.text((10, 10), f"{cls}  L={L}  R={R}  px_w={px_w}  width_inches={e['width_inches']}",
               fill=(255, 255, 255, 255))
        out_path = OUT / f"{cls}_anchors.png"
        img.save(out_path)
        rows.append((cls, out_path.name, px_w, e["width_inches"]))
        print(f"  {cls}: pixel_w={px_w}, width_inches={e['width_inches']}, ppi={px_w/e['width_inches']:.2f}")

    cards = "".join(
        f'<div class="card"><h3>{cls} — px_w={px_w} ÷ {win}in = {px_w/win:.2f} px/in</h3>'
        f'<img src="{name}"></div>'
        for cls, name, px_w, win in rows
    )
    (OUT / "_debug.html").write_text(
        f"""<!doctype html><html><head><meta charset="utf-8">
<style>body{{margin:0;background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:14px}}
.card{{margin-bottom:14px;background:#1e293b;padding:8px;border-radius:6px}}
.card h3{{margin:0 0 6px 0;color:#10b981;font-family:ui-monospace,Consolas,monospace;font-size:13px}}
.card img{{max-width:100%;border-radius:4px}}</style></head>
<body><h1>Anchor click debug</h1><p>Red line = where you clicked. Yellow crosshair = exact click point.</p>
{cards}</body></html>""",
        encoding="utf-8",
    )
    print(f"\nopen: file:///{(OUT / '_debug.html').as_posix()}")


if __name__ == "__main__":
    main()
