"""Generate _truck_curation.html — pick the cleanest ControlNet render per
(truck_class, angle) pair from the 3 seeds we generated.

Each card shows the 3 seeds for that (class, angle). User clicks the best
one to mark it as the chosen variant. Choices saved to localStorage and
exported as JSON; the engine reads that JSON to know which truck PNG to use.

Output: app/backend/static/trucks/_truck_curation.html (served by the local
http server at http://localhost:8765/trucks/_truck_curation.html).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRUCKS_DIR = ROOT / "backend" / "static" / "trucks"
RENDERS_DIR = TRUCKS_DIR / "renders_by_angle"
OUT = TRUCKS_DIR / "_truck_curation.html"

CLASSES = ["mid-size", "1500", "2500", "3500", "4500", "5500"]
ANGLES = ["0deg", "30deg"]
SEEDS = [1337, 4242, 8888]


def main() -> None:
    rows = []
    for cls in CLASSES:
        for angle in ANGLES:
            seed_options = []
            for seed in SEEDS:
                fname = f"{cls}_seed{seed}.png"
                if (RENDERS_DIR / angle / fname).exists():
                    seed_options.append({
                        "seed": seed,
                        "img": f"renders_by_angle/{angle}/{fname}",
                    })
            if seed_options:
                rows.append({"cls": cls, "angle": angle, "seeds": seed_options})

    rows_json = json.dumps(rows)

    OUT.write_text(f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Truck Render Curation</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,system-ui,sans-serif;
          background:#0f172a; color:#e2e8f0; padding:0; }}
  header {{ position:sticky; top:0; z-index:10;
            background:#020617; padding:10px 16px;
            display:flex; gap:14px; align-items:center; flex-wrap:wrap;
            border-bottom:1px solid #1e293b; }}
  header h1 {{ margin:0; font-size:15px; font-weight:600; }}
  .stats {{ display:flex; gap:8px; font-size:12px; flex-wrap:wrap; }}
  .stats span {{ background:rgba(255,255,255,0.08); padding:3px 9px; border-radius:999px; }}
  .stats span.ok {{ background:#047857; }}
  .controls {{ margin-left:auto; display:flex; gap:6px; }}
  .controls button {{ background:#374151; color:#fff; border:1px solid #4b5563;
                      padding:5px 11px; border-radius:5px; cursor:pointer; font-size:12px; }}
  .help {{ background:#0c1424; padding:8px 16px; font-size:12px;
          color:#94a3b8; border-bottom:1px solid #1e293b; }}
  .row {{ background:#1e293b; border-bottom:2px solid #0f172a;
          padding:10px 16px; }}
  .row h2 {{ margin:0 0 8px 0; font-size:13px;
            font-family:ui-monospace,Consolas,monospace; color:#10b981; }}
  .seeds {{ display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; }}
  .seed {{ background:#0f172a; border:3px solid transparent; border-radius:6px;
          cursor:pointer; overflow:hidden; transition:border-color 0.15s; }}
  .seed:hover {{ border-color:#3b82f6; }}
  .seed.picked {{ border-color:#10b981; }}
  .seed .label {{ font-size:11px; color:#94a3b8;
                 padding:4px 8px; display:flex; justify-content:space-between;
                 font-family:ui-monospace,Consolas,monospace; }}
  .seed.picked .label {{ color:#10b981; }}
  .seed .label .check {{ color:#10b981; font-weight:bold; }}
  .seed img {{ width:100%; display:block; }}
</style></head><body>

<header>
  <h1>Truck Render Curation</h1>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <button id="export">Export Picks</button>
    <button id="reset">Reset</button>
  </div>
</header>
<div class="help">
  Click the seed that looks cleanest for each (truck-class, angle) pair.
  Looking for: legible Ford/Toyota badge text (no &quot;SUPER FURY&quot; typos),
  natural proportions, no doubled features, no AI artifacts.
</div>

<div id="grid"></div>

<script>
const ROWS = {rows_json};
const KEY = "truck-curation-v1";
let picks = JSON.parse(localStorage.getItem(KEY) || "{{}}");

function rowKey(r) {{ return `${{r.cls}}__${{r.angle}}`; }}

function save() {{
  localStorage.setItem(KEY, JSON.stringify(picks));
  renderStats();
}}

function pick(r, seed) {{
  const key = rowKey(r);
  if (picks[key] === seed) delete picks[key];
  else picks[key] = seed;
  save();
  applyClasses(r);
}}

function applyClasses(r) {{
  const key = rowKey(r);
  const chosen = picks[key];
  document.querySelectorAll(`[data-row-key="${{key}}"] .seed`).forEach(el => {{
    const seed = parseInt(el.dataset.seed, 10);
    el.classList.toggle("picked", chosen === seed);
    const check = el.querySelector(".check");
    if (check) check.textContent = chosen === seed ? "✓" : "";
  }});
}}

function renderStats() {{
  const total = ROWS.length;
  const done = ROWS.filter(r => picks[rowKey(r)] !== undefined).length;
  document.getElementById("stats").innerHTML =
    `<span class="${{done === total ? 'ok' : ''}}">Picked <b>${{done}}/${{total}}</b></span>`;
}}

function build() {{
  const grid = document.getElementById("grid");
  ROWS.forEach(r => {{
    const div = document.createElement("div");
    div.className = "row";
    div.dataset.rowKey = rowKey(r);
    div.innerHTML = `
      <h2>${{r.cls}} @ ${{r.angle}}</h2>
      <div class="seeds">
        ${{r.seeds.map(s =>
          `<div class="seed" data-seed="${{s.seed}}">
            <img src="${{s.img}}">
            <div class="label"><span>seed ${{s.seed}}</span><span class="check"></span></div>
          </div>`
        ).join("")}}
      </div>
    `;
    grid.appendChild(div);
    div.querySelectorAll(".seed").forEach(el => {{
      el.addEventListener("click", () => pick(r, parseInt(el.dataset.seed, 10)));
    }});
    applyClasses(r);
  }});
}}

document.getElementById("export").addEventListener("click", () => {{
  const out = {{
    exported_at: new Date().toISOString(),
    picks: picks,
  }};
  const blob = new Blob([JSON.stringify(out, null, 2)], {{type:"application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "truck_curation_picks.json"; a.click();
  URL.revokeObjectURL(url);
}});
document.getElementById("reset").addEventListener("click", () => {{
  if (!confirm("Clear all picks?")) return;
  picks = {{}}; save();
  ROWS.forEach(applyClasses);
}});

build(); renderStats();
</script>
</body></html>
""", encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Open: http://localhost:8765/trucks/_truck_curation.html")


if __name__ == "__main__":
    main()
