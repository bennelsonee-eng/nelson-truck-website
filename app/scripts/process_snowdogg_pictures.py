"""Crop front-view halves from user-downloaded SnowDogg images, run rembg,
and drop the results into the SNOW-* SKU folders.

Source folder: C:/Users/Ben/Pictures/
Each input is a PNG with usually both front and back views stacked (top/bottom);
a couple have only the front view. Front-position per image is hardcoded
below from manual visual inspection.

Output: hero_transparent.png in each matching SKU folder + a side-by-side
review HTML at app/backend/static/snow-plows/_snowdogg_review.html
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PIL import Image
from rembg import new_session, remove

REPO = Path(__file__).resolve().parents[1].parent
SRC = Path("C:/Users/Ben/Pictures")
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
REVIEW_HTML = REPO / "app" / "backend" / "static" / "snow-plows" / "_snowdogg_review.html"

# (source_filename, sku, front_crop_strategy, label)
# front_crop_strategy:
#   "whole"  : the whole image is the front view
#   "top"    : crop top half
#   "bottom" : crop bottom half
#   tuple (x_pct, y_pct, x2_pct, y2_pct) : custom bbox in 0..1 coords
JOBS = [
    ("Snowdogg front and back CMII blade no vehicle.png",
     "SNOW-16020820-EQP", (0.0, 0.0, 0.62, 0.58),
     "CM II 120\" blade"),
    ("Snowdogg front and back facing MDII snowplow no vehicle.png",
     "SNOW-16020412-EQP", "bottom",
     "MD II blade"),
    ("Snowdogg XPII front straight on no vehicle.png",
     "SNOW-16020922-EQP", "whole",
     "XP 810 II wing-plow (head-on)"),
    ("Snowdogg VXX almost straight on front and back no vehicle.png",
     "SNOW-16020724-EQP", "top",
     "VXF II V-plow (uses VXX image — VXX is the 10'6\" version of VXF)"),
    ("Snowdogg VMXII front and back facing straight on no vehicle.png",
     "SNOW-16020712-EQP", "bottom",
     "VMD75 II V-plow"),
    ("Snowdogg front and back of HDII blade.png",
     "SNOW-16020522-EQP", "bottom",
     "HD II blade"),
    ("front and back of Snowdogg EXII snowplow.png",
     "SNOW-16020612-EQP", "bottom",
     "EX II blade"),
    # SNOW-16020312 (TE II) — Titan does not sell. Skipped permanently.
]


def crop_strategy(img: Image.Image, strategy) -> Image.Image:
    """Return the front-view portion of the source image."""
    W, H = img.size
    if isinstance(strategy, tuple) and len(strategy) == 4:
        x0, y0, x1, y1 = strategy
        return img.crop((int(W * x0), int(H * y0), int(W * x1), int(H * y1)))
    if strategy == "whole":
        return img
    if strategy == "top":
        return img.crop((0, 0, W, H // 2 + 20))
    if strategy == "bottom":
        return img.crop((0, H // 2 - 20, W, H))
    raise ValueError(f"unknown strategy {strategy!r}")


def trim_to_alpha(img: Image.Image) -> Image.Image:
    """Trim to non-transparent bbox so the saved file is tight around the plow."""
    if img.mode != "RGBA":
        return img
    bbox = img.split()[-1].getbbox()
    if bbox is None:
        return img
    return img.crop(bbox)


def process(session, src_path: Path, sku: str, strategy: str, label: str) -> dict | None:
    if not src_path.exists():
        print(f"  ! missing source: {src_path.name}")
        return None
    sku_dir = SKUS_DIR / sku
    if not sku_dir.exists():
        print(f"  ! missing sku dir: {sku_dir}")
        return None

    t0 = time.time()
    src_img = Image.open(src_path).convert("RGBA")
    front = crop_strategy(src_img, strategy)
    crop_t = time.time() - t0

    t1 = time.time()
    # rembg works on PNG bytes — re-encode the crop
    import io as _io
    buf = _io.BytesIO()
    front.save(buf, format="PNG")
    rembg_bytes = remove(buf.getvalue(), session=session)
    rembg_t = time.time() - t1

    out_img = Image.open(_io.BytesIO(rembg_bytes)).convert("RGBA")
    out_img = trim_to_alpha(out_img)

    dst = sku_dir / "hero_transparent.png"
    # Back up the existing rembg if it exists (from prior overnight run)
    if dst.exists():
        backup = sku_dir / "hero_transparent_OLD_isnet.png"
        if not backup.exists():
            dst.rename(backup)
    out_img.save(dst)
    print(f"  {sku}: cropped {crop_t:.2f}s, rembg {rembg_t:.2f}s, "
          f"out {out_img.size} -> {dst.name}")
    return {
        "sku": sku, "label": label, "src": src_path.name,
        "out_path": f"skus/{sku}/hero_transparent.png",
        "size": list(out_img.size),
    }


def write_review(results: list[dict]) -> None:
    cards_json = json.dumps(results)
    REVIEW_HTML.write_text(f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>SnowDogg cleanup review</title>
<style>
  body {{ margin:0; font-family:-apple-system,system-ui,sans-serif;
          background:#0f172a; color:#e2e8f0; padding:14px; }}
  h1 {{ margin:0 0 4px 0; font-size:18px; }}
  p {{ margin:0 0 14px 0; color:#94a3b8; font-size:13px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(380px,1fr));
           gap:14px; }}
  .card {{ background:#1e293b; padding:10px; border-radius:6px; }}
  .card h3 {{ margin:0 0 4px 0; font-size:13px;
             font-family:ui-monospace,Consolas,monospace; color:#10b981; }}
  .card p {{ margin:0 0 6px 0; font-size:11px; color:#94a3b8; }}
  .card .imgwrap {{
    background: repeating-conic-gradient(#334155 0 25%,#475569 0 50%) 50%/14px 14px;
    border-radius:4px; padding:8px;
    display:flex; align-items:center; justify-content:center;
    aspect-ratio:16/10;
  }}
  .card img {{ max-width:100%; max-height:100%; object-fit:contain; display:block; }}
</style></head><body>
<h1>SnowDogg plow cleanup — review</h1>
<p>Front-view crop + isnet rembg per SKU. Old rembg results are backed up as <code>hero_transparent_OLD_isnet.png</code>.</p>
<div class="grid" id="grid"></div>
<script>
const C = {cards_json};
const g = document.getElementById("grid");
C.forEach(c => {{
  const d = document.createElement("div");
  d.className = "card";
  d.innerHTML = `
    <h3>${{c.sku}}</h3>
    <p>${{c.label}} &mdash; ${{c.size[0]}}x${{c.size[1]}}px <br>source: ${{c.src}}</p>
    <div class="imgwrap"><img src="${{c.out_path}}"></div>
  `;
  g.appendChild(d);
}});
</script></body></html>""", encoding="utf-8")


def main() -> int:
    print(f"Loading rembg session (isnet-general-use)...")
    session = new_session("isnet-general-use")

    results = []
    for src_name, sku, strategy, label in JOBS:
        src_path = SRC / src_name
        r = process(session, src_path, sku, strategy, label)
        if r:
            results.append(r)

    write_review(results)
    print(f"\n{len(results)}/{len(JOBS)} processed")
    print(f"review: file:///{REVIEW_HTML.as_posix()}")
    print(f"or: http://localhost:8765/snow-plows/_snowdogg_review.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
