"""Run rembg on every Meyer + SnowDogg plow hero, plus a side-by-side survey.

Tries TWO models per SKU (isnet-general-use and birefnet-general) so the
user can pick whichever gave a cleaner cutout per plow. Outputs into
hero_isnet.png and hero_birefnet.png next to each hero.jpg.

Builds _meyer_snowdogg_survey.html showing original + both rembg variants
in a 3-column row, with click-to-pick winner buttons that save to
localStorage and export JSON.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PIL import Image
from rembg import new_session, remove

ROOT = Path(__file__).resolve().parents[1]
PLOW_DIR = ROOT / "backend" / "static" / "snow-plows"
MANIFEST = PLOW_DIR / "skus" / "_manifest.json"
SURVEY = PLOW_DIR / "_meyer_snowdogg_survey.html"

MODELS = ["isnet-general-use"]  # birefnet blocked by Windows SSL


def filter_targets() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = []
    for s in data.get("skus", []):
        sku = s.get("stockid_sanitized", "")
        brand = s.get("brand", "")
        if sku.startswith("MYP-") or "Meyer" in brand:
            out.append(s)
        elif sku.startswith("SNOW-") or "SNOWDOGG" in brand.upper():
            out.append(s)
    out.sort(key=lambda s: s.get("stockid_sanitized", ""))
    return out


def run_model(skus: list[dict], model_name: str, suffix: str, force: bool) -> int:
    print(f"\n--- {model_name} ---")
    session = new_session(model_name)
    n_done = 0
    n_skip = 0
    for i, s in enumerate(skus, 1):
        sku = s["stockid_sanitized"]
        src = PLOW_DIR / "skus" / sku / "hero.jpg"
        dst = PLOW_DIR / "skus" / sku / f"hero_{suffix}.png"
        if not src.exists():
            print(f"  [{i}/{len(skus)}] {sku}: missing source")
            continue
        if dst.exists() and not force and dst.stat().st_mtime >= src.stat().st_mtime:
            n_skip += 1
            continue
        try:
            t = time.time()
            out = remove(src.read_bytes(), session=session)
            dst.write_bytes(out)
            print(f"  [{i}/{len(skus)}] {sku}: {time.time()-t:.2f}s ({dst.stat().st_size:,}B)")
            n_done += 1
        except Exception as e:
            print(f"  [{i}/{len(skus)}] {sku}: FAILED — {e}")
    print(f"  done={n_done} skipped={n_skip}")
    return n_done


def write_survey(skus: list[dict]) -> None:
    cards = []
    for s in skus:
        sku = s.get("stockid_sanitized", "")
        cards.append({
            "sku": sku,
            "brand": s.get("brand", ""),
            "title": s.get("title", ""),
            "orig": f"skus/{sku}/hero.jpg",
            "isnet": f"skus/{sku}/hero_isnet.png",
        })
    cards_json = json.dumps(cards)

    SURVEY.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Meyer + SnowDogg rembg triage ({len(cards)})</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,system-ui,Segoe UI,sans-serif;
          background:#f5f6f8; color:#222; }}
  header {{ position:sticky; top:0; z-index:10;
            background:#1f2937; color:#fff; padding:12px 20px;
            display:flex; gap:18px; align-items:center; flex-wrap:wrap; }}
  header h1 {{ margin:0; font-size:16px; font-weight:600; }}
  .stats {{ display:flex; gap:10px; font-size:12px; flex-wrap:wrap; }}
  .stats span {{ background:rgba(255,255,255,0.1); padding:3px 8px; border-radius:999px; }}
  .controls {{ margin-left:auto; display:flex; gap:6px; }}
  .controls button, .controls select {{
    background:#374151; color:#fff; border:1px solid #4b5563;
    padding:5px 10px; border-radius:5px; cursor:pointer; font-size:12px; }}
  .help {{ background:#fff; padding:10px 20px; border-bottom:1px solid #e5e7eb;
          font-size:12px; color:#4b5563; }}
  .help kbd {{ background:#f3f4f6; border:1px solid #d1d5db; border-radius:3px;
              padding:1px 5px; font-family:ui-monospace,Consolas,monospace; font-size:11px; }}
  .row {{ display:grid; grid-template-columns:1fr 200px;
          gap:10px; margin:10px 14px; padding:8px;
          background:#fff; border-radius:6px;
          box-shadow:0 1px 3px rgba(0,0,0,0.06);
          border-left:4px solid #d1d5db; }}
  .row.pick-isnet {{ border-left-color:#10b981; }}
  .row.pick-partial {{ border-left-color:#f59e0b; }}
  .row.failed {{ border-left-color:#ef4444; }}
  .imgs {{ display:grid; grid-template-columns:repeat(2,1fr); gap:6px; }}
  .imgs > div {{ aspect-ratio:16/10; background:repeating-conic-gradient(#e5e7eb 0 25%,#f9fafb 0 50%) 50%/12px 12px;
                 display:flex; align-items:center; justify-content:center;
                 position:relative; border-radius:4px; overflow:hidden;
                 cursor:pointer; transition:outline 0.15s; outline:2px solid transparent; }}
  .imgs > div:hover {{ outline-color:#9ca3af; }}
  .imgs > div.selected {{ outline-color:#10b981; outline-width:3px; }}
  .imgs img {{ max-width:100%; max-height:100%; object-fit:contain; }}
  .imgs .label {{ position:absolute; top:3px; left:5px; font-size:10px;
                 background:rgba(0,0,0,0.7); color:#fff; padding:1px 5px;
                 border-radius:3px; font-family:ui-monospace,Consolas,monospace; }}
  .meta {{ font-size:11px; }}
  .meta .sku {{ font-family:ui-monospace,Consolas,monospace; color:#1f2937; font-weight:600; }}
  .meta .brand {{ color:#6b7280; margin-top:2px; }}
  .meta .title {{ color:#4b5563; margin-top:4px; line-height:1.35; font-size:11px; }}
  .actions {{ margin-top:6px; display:flex; flex-direction:column; gap:3px; }}
  .actions button {{ font-size:10px; padding:3px 6px; cursor:pointer;
                    background:#f3f4f6; border:1px solid #d1d5db; border-radius:3px;
                    text-align:left; }}
  .actions button.partial-btn.active {{ background:#fef3c7; border-color:#f59e0b; color:#92400e; }}
  .actions button.failed-btn.active {{ background:#fee2e2; border-color:#ef4444; color:#991b1b; }}
</style></head><body>

<header>
  <h1>Meyer + SnowDogg rembg triage</h1>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <select id="filter"><option value="">All</option><option value="untriaged">Untriaged</option><option value="clean">Clean</option><option value="partial">Partial</option><option value="failed">Failed</option></select>
    <button id="export">Export JSON</button>
  </div>
</header>

<div class="help">
  Click an image to pick it as the winner for that SKU. Click again to deselect.
  Use <kbd>F</kbd> to mark "all failed - need different approach".
  Stats update live; export when done.
</div>

<div id="grid"></div>

<script>
const CARDS = {cards_json};
const KEY = "meyer-snowdogg-triage-v1";
let state = JSON.parse(localStorage.getItem(KEY) || "{{}}");

function save() {{ localStorage.setItem(KEY, JSON.stringify(state)); renderStats(); }}

function setPick(sku, choice) {{
  if (state[sku]?.pick === choice) {{ delete state[sku]; }}
  else {{ state[sku] = {{ pick: choice }}; }}
  save(); applyClasses(sku);
}}

function applyClasses(sku) {{
  const row = document.querySelector(`[data-sku="${{sku}}"]`);
  if (!row) return;
  row.classList.remove("pick-isnet", "pick-partial", "failed");
  row.querySelectorAll(".imgs > div").forEach(d => d.classList.remove("selected"));
  row.querySelectorAll(".partial-btn,.failed-btn").forEach(b => b.classList.remove("active"));
  const p = state[sku]?.pick;
  if (p === "isnet") {{
    row.classList.add("pick-isnet");
    row.querySelector(`[data-which="isnet"]`).classList.add("selected");
  }} else if (p === "partial") {{
    row.classList.add("pick-partial");
    row.querySelector(".partial-btn").classList.add("active");
  }} else if (p === "failed") {{
    row.classList.add("failed");
    row.querySelector(".failed-btn").classList.add("active");
  }}
}}

function renderStats() {{
  const t = CARDS.length;
  let clean = 0, partial = 0, failed = 0;
  CARDS.forEach(c => {{
    const p = state[c.sku]?.pick;
    if (p === "isnet") clean++;
    else if (p === "partial") partial++;
    else if (p === "failed") failed++;
  }});
  const u = t - clean - partial - failed;
  document.getElementById("stats").innerHTML =
    `<span>Total <b>${{t}}</b></span>` +
    `<span style="background:#047857">clean <b>${{clean}}</b></span>` +
    `<span style="background:#b45309">partial <b>${{partial}}</b></span>` +
    `<span style="background:#dc2626">failed <b>${{failed}}</b></span>` +
    `<span>untriaged <b>${{u}}</b></span>`;
}}

function applyFilter() {{
  const f = document.getElementById("filter").value;
  CARDS.forEach(c => {{
    const row = document.querySelector(`[data-sku="${{c.sku}}"]`);
    const p = state[c.sku]?.pick;
    let show = true;
    if (f === "untriaged" && p) show = false;
    if (f === "clean" && p !== "isnet") show = false;
    if (f === "partial" && p !== "partial") show = false;
    if (f === "failed" && p !== "failed") show = false;
    row.style.display = show ? "" : "none";
  }});
}}

function build() {{
  const grid = document.getElementById("grid");
  CARDS.forEach(c => {{
    const row = document.createElement("div");
    row.className = "row";
    row.dataset.sku = c.sku;
    row.innerHTML = `
      <div class="imgs">
        <div data-which="orig"><span class="label">orig</span><img loading="lazy" src="${{c.orig}}"></div>
        <div data-which="isnet"><span class="label">isnet rembg</span><img loading="lazy" src="${{c.isnet}}"></div>
      </div>
      <div>
        <div class="meta">
          <div class="sku">${{c.sku}}</div>
          <div class="brand">${{c.brand}}</div>
          <div class="title">${{c.title}}</div>
        </div>
        <div class="actions">
          <button class="partial-btn">Partial — needs cleanup</button>
          <button class="failed-btn">Failed — need new source</button>
        </div>
      </div>
    `;
    grid.appendChild(row);
    row.querySelectorAll(".imgs > div").forEach(d => {{
      d.addEventListener("click", () => {{
        if (d.dataset.which === "isnet") setPick(c.sku, "isnet");
      }});
    }});
    row.querySelector(".partial-btn").addEventListener("click", () => setPick(c.sku, "partial"));
    row.querySelector(".failed-btn").addEventListener("click", () => setPick(c.sku, "failed"));
    applyClasses(c.sku);
  }});
}}

document.getElementById("export").addEventListener("click", () => {{
  const out = {{
    exported_at: new Date().toISOString(),
    n_total: CARDS.length,
    picks: state,
  }};
  const blob = new Blob([JSON.stringify(out, null, 2)], {{type:"application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "meyer_snowdogg_picks.json"; a.click();
  URL.revokeObjectURL(url);
}});
document.getElementById("filter").addEventListener("change", applyFilter);

build(); renderStats();
</script>
</body></html>""", encoding="utf-8")


def main() -> int:
    skus = filter_targets()
    print(f"Targets: {len(skus)} SKUs (Meyer + SnowDogg)")
    if not skus:
        return 1
    for model_name in MODELS:
        suffix = model_name.replace("-general-use", "").replace("-general", "")
        # isnet-general-use -> isnet
        # birefnet-general -> birefnet
        run_model(skus, model_name, suffix, force=False)
    write_survey(skus)
    print(f"\nsurvey: file:///{SURVEY.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
