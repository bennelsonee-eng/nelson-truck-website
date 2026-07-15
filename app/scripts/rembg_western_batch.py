"""Run rembg on every clean Western plow hero and save hero_transparent.png.

Reads the manifest + the user's prior classifications JSON to filter to
Western plows that aren't tagged with problems. Writes
`hero_transparent.png` (RGBA) next to each `hero.jpg`. Idempotent — skip
if output exists and is newer than input, unless --force.

Also generates `_western_rembg_preview.html` so you can scan all 30 cutouts
on a checkerboard background to spot any rembg failures.

Usage:
    python app/scripts/rembg_western_batch.py
    python app/scripts/rembg_western_batch.py --force      # redo all
    python app/scripts/rembg_western_batch.py --model isnet-general-use
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image
from rembg import new_session, remove

ROOT = Path(__file__).resolve().parents[1]
PLOW_DIR = ROOT / "backend" / "static" / "snow-plows"
MANIFEST = PLOW_DIR / "skus" / "_manifest.json"
PREVIEW = PLOW_DIR / "_western_rembg_preview.html"

CLASSIFICATION_CANDIDATES = [
    Path.home() / "Downloads" / "plow_survey_classifications.json",
    PLOW_DIR / "plow_survey_classifications.json",
]


def load_classifications() -> dict[str, dict]:
    for p in CLASSIFICATION_CANDIDATES:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("classifications", data)
    return {}


def filter_clean_westerns() -> list[dict]:
    cls = load_classifications()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    problem_tags = {"has-truck", "watermark", "bad-angle", "unusable"}
    out = []
    for s in data.get("skus", []):
        sku = s.get("stockid_sanitized", "")
        brand = s.get("brand", "")
        if "Western" not in brand and not sku.startswith("WEST-"):
            continue
        tags = set((cls.get(sku, {}) or {}).get("tags", []))
        if tags & problem_tags:
            continue
        out.append(s)
    out.sort(key=lambda s: s.get("stockid_sanitized", ""))
    return out


def needs_rebuild(src: Path, dst: Path, force: bool) -> bool:
    if force:
        return True
    if not dst.exists():
        return True
    return dst.stat().st_mtime < src.stat().st_mtime


def write_preview(skus: list[dict]) -> None:
    cards = []
    for s in skus:
        sku = s.get("stockid_sanitized", "")
        cards.append(
            {
                "sku": sku,
                "title": s.get("title", ""),
                "orig": f"skus/{sku}/hero.jpg",
                "cut": f"skus/{sku}/hero_transparent.png",
            }
        )
    cards_json = json.dumps(cards)

    PREVIEW.write_text(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Western rembg QA ({len(cards)})</title>
<style>
  body {{ margin:0; font-family:-apple-system,system-ui,Segoe UI,sans-serif;
         background:#f5f6f8; color:#222; }}
  header {{ background:#1f2937; color:#fff; padding:12px 20px; font-size:16px;
           position:sticky; top:0; z-index:10; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(420px,1fr));
           gap:14px; padding:18px; }}
  .card {{ background:#fff; border-radius:6px; overflow:hidden;
           box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
  .pair {{ display:grid; grid-template-columns:1fr 1fr; }}
  .pair > div {{ aspect-ratio:16/10; display:flex; align-items:center;
                 justify-content:center; }}
  .pair > div.cut {{
    background: repeating-conic-gradient(#cbd5e1 0 25%, #f1f5f9 0 50%) 50% / 14px 14px;
  }}
  .pair img {{ max-width:100%; max-height:100%; object-fit:contain; }}
  .meta {{ padding:6px 10px; font-size:11px; color:#4b5563;
          display:flex; justify-content:space-between; border-top:1px solid #f3f4f6; }}
  .sku {{ font-family:ui-monospace,Consolas,monospace; color:#1f2937; }}
</style></head><body>
<header>Western rembg QA — original (left) vs transparent on checkerboard (right)</header>
<div class="grid" id="grid"></div>
<script>
const C = {cards_json};
const g = document.getElementById("grid");
C.forEach(c => {{
  const d = document.createElement("div");
  d.className = "card";
  d.innerHTML = `
    <div class="pair">
      <div><img loading="lazy" src="${{c.orig}}"></div>
      <div class="cut"><img loading="lazy" src="${{c.cut}}"></div>
    </div>
    <div class="meta"><span class="sku">${{c.sku}}</span><span>${{c.title}}</span></div>`;
  g.appendChild(d);
}});
</script></body></html>
""",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Regenerate even if up to date")
    ap.add_argument("--model", default="u2net",
                    help="rembg model (u2net | isnet-general-use | birefnet-general)")
    args = ap.parse_args()

    skus = filter_clean_westerns()
    print(f"Filtered to {len(skus)} clean Western SKUs")

    print(f"Loading rembg session (model={args.model})...")
    t0 = time.time()
    session = new_session(args.model)
    print(f"  ready in {time.time() - t0:.1f}s")

    n_done = 0
    n_skipped = 0
    n_failed = 0
    total_t0 = time.time()
    for i, s in enumerate(skus, 1):
        sku = s["stockid_sanitized"]
        src = PLOW_DIR / "skus" / sku / "hero.jpg"
        dst = PLOW_DIR / "skus" / sku / "hero_transparent.png"
        if not src.exists():
            print(f"  [{i}/{len(skus)}] {sku}: source missing, skip")
            n_failed += 1
            continue
        if not needs_rebuild(src, dst, args.force):
            print(f"  [{i}/{len(skus)}] {sku}: up to date")
            n_skipped += 1
            continue
        try:
            t = time.time()
            with src.open("rb") as f:
                input_bytes = f.read()
            output_bytes = remove(input_bytes, session=session)
            dst.write_bytes(output_bytes)
            # Verify it's a valid RGBA PNG
            with Image.open(dst) as im:
                if im.mode != "RGBA":
                    print(f"  [{i}/{len(skus)}] {sku}: WARNING got mode={im.mode}, expected RGBA")
            print(f"  [{i}/{len(skus)}] {sku}: {time.time() - t:.2f}s ({dst.stat().st_size:,} bytes)")
            n_done += 1
        except Exception as e:
            print(f"  [{i}/{len(skus)}] {sku}: FAILED — {e}")
            n_failed += 1

    print(
        f"\nDone in {time.time() - total_t0:.1f}s — "
        f"processed {n_done}, skipped {n_skipped}, failed {n_failed}"
    )

    write_preview(skus)
    print(f"\nQA preview: file:///{PREVIEW.as_posix()}")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
