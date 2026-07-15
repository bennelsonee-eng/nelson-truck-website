"""Build the master review HTML for the TRELLIS batch.

Reads wan_test_output/trellis_batch/<SKU>/ for each priority plow, plus the
earlier MVP3 result in wan_test_output/trellis_preview_test/, and produces:
  - wan_test_output/trellis_batch_review.html   (master review page)
  - wan_test_output/trellis_batch/<SKU>/_angles_grid.png  (one grid per plow)
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[2]
BATCH_DIR = REPO / "wan_test_output" / "trellis_batch"
MVP3_DIR = REPO / "wan_test_output" / "trellis_preview_test"
REVIEW_HTML = REPO / "wan_test_output" / "trellis_batch_review.html"

ANGLES = [0, 15, 30, 45, 60, 75, 90]


def build_angle_grid(sku: str, frame_dir: Path, out_path: Path):
    TILE = 320
    LABEL_H = 32
    HEADER_H = 36
    COLS = 4
    rows = (len(ANGLES) + COLS - 1) // COLS
    grid = Image.new("RGB", (COLS * TILE, rows * (TILE + LABEL_H) + HEADER_H), (30, 30, 30))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("arialbd.ttf", 20)
        font_h = ImageFont.truetype("arialbd.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
        font_h = font
    draw.text((12, 8), sku, fill=(255, 224, 74), font=font_h)
    for i, ang in enumerate(ANGLES):
        fn = frame_dir / f"angle_{i+1:02d}.png"
        if not fn.exists():
            continue
        try:
            img = Image.open(fn).convert("RGB")
        except Exception:
            continue
        img.thumbnail((TILE, TILE))
        r, c = divmod(i, COLS)
        x = c * TILE + (TILE - img.width) // 2
        y = r * (TILE + LABEL_H) + (TILE - img.height) // 2 + HEADER_H
        grid.paste(img, (x, y))
        label_y = r * (TILE + LABEL_H) + TILE + HEADER_H
        draw.rectangle([c*TILE, label_y, (c+1)*TILE, label_y + LABEL_H], fill=(20, 20, 20))
        draw.text((c*TILE + 12, label_y + 6), f"{ang} deg", fill=(255, 224, 74), font=font)
    grid.save(out_path)


def main():
    # MVP3 first (already in trellis_preview_test, frames named angle_01 ... angle_07)
    mvp3_grid = MVP3_DIR / "_trellis_angles_grid.png"
    rows = []

    sku = "WEST-MVP3MS86-EQP"
    if mvp3_grid.exists():
        rows.append({
            "sku": sku,
            "grid_rel": f"trellis_preview_test/{mvp3_grid.name}",
            "glb_rel": "trellis_preview_test/mvp3_trellis_0.glb",
            "elapsed": 27.0,
            "status": "ok (prior session)",
        })

    # The 9 batch SKUs
    results_json = BATCH_DIR / "results.json"
    if results_json.exists():
        results = json.loads(results_json.read_text())
    else:
        results = []

    for r in results:
        sku = r["sku"]
        sku_dir = BATCH_DIR / sku
        grid_path = sku_dir / "_angles_grid.png"
        if r.get("status") == "ok" and not grid_path.exists():
            build_angle_grid(sku, sku_dir, grid_path)
        rows.append({
            "sku": sku,
            "grid_rel": f"trellis_batch/{sku}/_angles_grid.png" if grid_path.exists() else None,
            "glb_rel": f"trellis_batch/{sku}/{sku}.glb" if (sku_dir / f"{sku}.glb").exists() else None,
            "elapsed": r.get("elapsed", "-"),
            "status": r.get("status", "?"),
            "times": r.get("times", {}),
        })

    # Write review HTML
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<title>TRELLIS batch review — all priority plows</title>',
        '<style>',
        'body { font-family: Arial, sans-serif; background: #1a1a1a; color: #f0f0f0; margin: 0; padding: 24px; line-height: 1.55; }',
        'h1 { color: #ffe04a; margin-bottom: 4px; }',
        '.subtitle { color: #aaa; font-size: 14px; margin: 0 0 24px; }',
        'h2 { color: #6cd; margin-top: 32px; border-bottom: 1px solid #333; padding-bottom: 8px; }',
        'img { display: block; max-width: 100%; height: auto; border-radius: 4px; }',
        'figure { background: #2a2a2a; padding: 12px; border-radius: 8px; margin: 0 0 24px; }',
        'figcaption { color: #ddd; font-size: 13px; margin-top: 8px; line-height: 1.6; }',
        'table { border-collapse: collapse; margin: 12px 0; }',
        'td, th { border: 1px solid #444; padding: 8px 14px; text-align: left; font-size: 13px; }',
        'th { background: #333; color: #ffe04a; }',
        '.win { color: #6c6; font-weight: bold; } .fail { color: #f66; font-weight: bold; } .warn { color: #fb6; font-weight: bold; }',
        'a.glb { color: #6cd; }',
        '.callout { background: #102d10; border-left: 4px solid #6c6; padding: 14px 18px; margin: 16px 0; border-radius: 4px; }',
        '</style></head><body>',
        '<h1>TRELLIS batch — all priority plows</h1>',
        '<p class="subtitle">10 plows run through Microsoft TRELLIS HuggingFace Space. .glb mesh + 7-angle turntable per plow.</p>',
    ]

    # Summary table
    parts.append('<h2>Summary</h2><table><tr><th>SKU</th><th>Status</th><th>Elapsed (s)</th><th>preprocess</th><th>image_to_3d</th><th>extract_glb</th><th>Mesh</th></tr>')
    for r in rows:
        ok = r["status"].startswith("ok")
        cls = "win" if ok else "fail"
        t = r.get("times", {})
        glb_link = f'<a class="glb" href="{r["glb_rel"]}">.glb</a>' if r.get("glb_rel") else "-"
        parts.append(
            f'<tr><td>{r["sku"]}</td>'
            f'<td class="{cls}">{r["status"]}</td>'
            f'<td>{r["elapsed"]}</td>'
            f'<td>{t.get("preprocess", "-")}</td>'
            f'<td>{t.get("image_to_3d", "-")}</td>'
            f'<td>{t.get("extract_glb", "-")}</td>'
            f'<td>{glb_link}</td></tr>'
        )
    parts.append('</table>')

    parts.append('<div class="callout"><strong>How to spin a mesh:</strong> click any .glb link, then drag the file into <a href="https://gltf-viewer.donmccurdy.com/" target="_blank" style="color:#6cd;">https://gltf-viewer.donmccurdy.com/</a> to rotate freely in the browser.</div>')

    # Per-SKU grids
    parts.append('<h2>Per-plow turntable grids (0 / 15 / 30 / 45 / 60 / 75 / 90 deg)</h2>')
    for r in rows:
        parts.append('<figure>')
        if r.get("grid_rel"):
            parts.append(f'<img src="{r["grid_rel"]}">')
        else:
            parts.append('<p style="color:#f66;">grid not generated</p>')
        cap_status = r["status"]
        glb_extra = f' &nbsp;|&nbsp; <a class="glb" href="{r["glb_rel"]}">download .glb</a>' if r.get("glb_rel") else ""
        parts.append(f'<figcaption><strong>{r["sku"]}</strong> — {cap_status} ({r["elapsed"]}s){glb_extra}</figcaption>')
        parts.append('</figure>')

    parts.append('</body></html>')
    REVIEW_HTML.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {REVIEW_HTML}")


if __name__ == "__main__":
    main()
