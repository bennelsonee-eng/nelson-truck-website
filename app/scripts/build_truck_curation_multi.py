"""Generate _truck_curation.html — pick cleanest seed per (make, angle) cell.

Auto-discovers what files exist in renders_by_angle/<angle>/ and renders a
grid: rows = makes (grouped by class with collapsible headers), columns = angles.
Each cell shows seed thumbnails; click the cleanest to mark it.

Output: app/backend/static/trucks/_truck_curation.html
        served at http://localhost:8765/trucks/_truck_curation.html
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRUCKS_DIR = ROOT / "backend" / "static" / "trucks"
RENDERS_DIR = TRUCKS_DIR / "renders_by_angle"
OUT = TRUCKS_DIR / "_truck_curation.html"

# Mirror MAKES from the renderer so the curation matches what was rendered
CLASSES = {
    "mid-size": [
        ("toyota_tacoma",  "Toyota Tacoma TRD"),
        ("chevy_colorado", "Chevy Colorado"),
        ("ford_ranger",    "Ford Ranger"),
        ("jeep_liberty",   "Jeep Liberty"),
        ("jeep_renegade",  "Jeep Renegade"),
        ("chevy_tahoe",    "Chevy Tahoe"),
    ],
    "1500": [
        ("chevy_1500",     "Chevy Silverado 1500"),
        ("ford_f150",      "Ford F-150"),
        ("toyota_tundra",  "Toyota Tundra"),
        ("ram_1500",       "Ram 1500"),
        ("nissan_titan",   "Nissan Titan"),
        ("gmc_1500",       "GMC Sierra 1500"),
    ],
    "2500": [
        ("chevy_3500",     "Chevy 3500 HD"),
        ("ford_f250",      "Ford F-250 SD"),
        ("ram_2500",       "Ram 2500 HD"),
        ("gmc_2500",       "GMC 2500 HD"),
    ],
}
ANGLES = ["-30deg", "-15deg", "0deg", "+15deg", "+30deg"]
SEEDS = [1337, 4242, 8888]


def main() -> int:
    grid_data = []
    for cls, makes in CLASSES.items():
        for slug, label in makes:
            row = {"slug": slug, "label": label, "cls": cls, "angles": {}}
            for angle in ANGLES:
                seed_options = []
                for seed in SEEDS:
                    fname = f"{slug}_seed{seed}.png"
                    rel = f"renders_by_angle/{angle}/{fname}"
                    if (TRUCKS_DIR / rel).exists():
                        seed_options.append({"seed": seed, "img": rel})
                row["angles"][angle] = seed_options
            grid_data.append(row)

    grid_json = json.dumps(grid_data)
    angles_json = json.dumps(ANGLES)

    OUT.write_text(f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Truck Multi-Angle Curation</title>
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
  .class-section {{ background:#1e293b; border-bottom:2px solid #0f172a;
                    padding:12px 16px; }}
  .class-section h2 {{ margin:0 0 10px 0; font-size:14px; color:#fde047;
                       text-transform:uppercase; letter-spacing:0.5px;
                       cursor:pointer; user-select:none; }}
  .class-section h2::before {{ content:"▼ "; font-size:10px; }}
  .class-section.collapsed h2::before {{ content:"▶ "; }}
  .class-section.collapsed .makes {{ display:none; }}
  .makes {{ display:flex; flex-direction:column; gap:14px; }}
  .make-row {{ background:#111827; padding:10px; border-radius:6px; }}
  .make-row h3 {{ margin:0 0 8px 0; font-size:12px;
                 font-family:ui-monospace,Consolas,monospace; color:#10b981; }}
  .angle-grid {{ display:grid; grid-template-columns:repeat(5, 1fr); gap:6px; }}
  .angle-cell {{ background:#0f172a; border-radius:4px; padding:4px; }}
  .angle-cell h4 {{ margin:0 0 4px 0; font-size:10px; color:#94a3b8;
                   font-family:ui-monospace,Consolas,monospace; text-align:center; }}
  .seeds {{ display:flex; flex-direction:column; gap:3px; }}
  .seed {{ position:relative; cursor:pointer; border:2px solid transparent;
          border-radius:3px; overflow:hidden; transition:border-color 0.1s;
          background:#1e293b; }}
  .seed:hover {{ border-color:#3b82f6; }}
  .seed.picked {{ border-color:#10b981; }}
  .seed img {{ width:100%; display:block; }}
  .seed .badge {{ position:absolute; top:2px; right:2px;
                  background:rgba(0,0,0,0.7); color:#94a3b8;
                  font-size:9px; padding:1px 4px; border-radius:2px;
                  font-family:ui-monospace,Consolas,monospace; }}
  .seed.picked .badge {{ background:#10b981; color:#022c22; }}
  .empty {{ color:#64748b; font-size:10px; text-align:center; padding:20px 4px;
            background:#0a0f1a; border-radius:3px; }}
</style></head><body>

<header>
  <h1>Truck Multi-Angle Curation</h1>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <button id="export">Export Picks</button>
    <button id="reset">Reset</button>
    <button id="reload">Reload</button>
  </div>
</header>
<div class="help">
  Pick the cleanest seed for each (make, angle) cell. Look for: legible badge text,
  natural proportions, no doubled features. Empty cells = render not yet finished.
  Click a class header to collapse.
</div>

<div id="grid"></div>

<script>
const GRID = {grid_json};
const ANGLES = {angles_json};
const KEY = "truck-curation-multi-v1";
let picks = JSON.parse(localStorage.getItem(KEY) || "{{}}");

function rowKey(slug, angle) {{ return `${{slug}}__${{angle}}`; }}

function save() {{
  localStorage.setItem(KEY, JSON.stringify(picks));
  renderStats();
}}

function pick(slug, angle, seed) {{
  const k = rowKey(slug, angle);
  if (picks[k] === seed) delete picks[k];
  else picks[k] = seed;
  save();
  applyClasses(slug, angle);
}}

function applyClasses(slug, angle) {{
  const k = rowKey(slug, angle);
  const chosen = picks[k];
  document.querySelectorAll(`[data-key="${{k}}"] .seed`).forEach(el => {{
    const seed = parseInt(el.dataset.seed, 10);
    el.classList.toggle("picked", chosen === seed);
  }});
}}

function renderStats() {{
  let total = 0, picked = 0;
  GRID.forEach(row => {{
    ANGLES.forEach(angle => {{
      const seeds = (row.angles && row.angles[angle]) || [];
      if (seeds.length > 0) {{
        total++;
        if (picks[rowKey(row.slug, angle)] !== undefined) picked++;
      }}
    }});
  }});
  document.getElementById("stats").innerHTML =
    `<span class="${{picked === total && total > 0 ? 'ok' : ''}}">Picked <b>${{picked}}/${{total}}</b></span>`;
}}

function build() {{
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  // Group by class
  const byClass = {{}};
  GRID.forEach(row => {{
    if (!byClass[row.cls]) byClass[row.cls] = [];
    byClass[row.cls].push(row);
  }});

  Object.entries(byClass).forEach(([cls, rows]) => {{
    const section = document.createElement("div");
    section.className = "class-section";
    section.dataset.cls = cls;
    section.innerHTML = `
      <h2>${{cls}}</h2>
      <div class="makes"></div>
    `;
    const makesEl = section.querySelector(".makes");
    section.querySelector("h2").addEventListener("click", () => {{
      section.classList.toggle("collapsed");
    }});
    rows.forEach(row => {{
      const mk = document.createElement("div");
      mk.className = "make-row";
      mk.innerHTML = `
        <h3>${{row.label}} <small style="color:#94a3b8">(${{row.slug}})</small></h3>
        <div class="angle-grid">
          ${{ANGLES.map(angle => {{
            const seeds = (row.angles && row.angles[angle]) || [];
            const inner = seeds.length === 0
              ? '<div class="empty">no renders yet</div>'
              : seeds.map(s =>
                  `<div class="seed" data-seed="${{s.seed}}">
                    <img src="${{s.img}}" loading="lazy">
                    <span class="badge">${{s.seed}}</span>
                  </div>`
                ).join("");
            return `<div class="angle-cell" data-key="${{rowKey(row.slug, angle)}}">
                      <h4>${{angle}}</h4>
                      <div class="seeds">${{inner}}</div>
                    </div>`;
          }}).join("")}}
        </div>
      `;
      makesEl.appendChild(mk);
      // Wire seed clicks
      mk.querySelectorAll(".angle-cell").forEach(cell => {{
        const [slug, angle] = cell.dataset.key.split("__");
        cell.querySelectorAll(".seed").forEach(el => {{
          el.addEventListener("click", () => pick(slug, angle, parseInt(el.dataset.seed, 10)));
        }});
      }});
      // Apply existing picks
      ANGLES.forEach(angle => applyClasses(row.slug, angle));
    }});
    grid.appendChild(section);
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
  a.href = url; a.download = "truck_curation_multi_picks.json"; a.click();
  URL.revokeObjectURL(url);
}});
document.getElementById("reset").addEventListener("click", () => {{
  if (!confirm("Clear all picks?")) return;
  picks = {{}}; save();
  GRID.forEach(row => ANGLES.forEach(angle => applyClasses(row.slug, angle)));
}});
document.getElementById("reload").addEventListener("click", () => {{
  // Reload page to re-discover newly-rendered files
  location.reload();
}});

build(); renderStats();
</script>
</body></html>
""", encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Open: http://localhost:8765/trucks/_truck_curation.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
