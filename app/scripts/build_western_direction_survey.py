"""Generate _western_direction.html — direction classifier for clean Western plow heroes.

Reads `app/backend/static/snow-plows/skus/_manifest.json` and (optionally)
`plow_survey_classifications.json` from the user's Downloads folder. Filters
to Western plows that aren't already flagged with problems, then renders a
big-thumbnail grid where each card asks: which side of the plow is forward
toward the camera?

Usage:
    python app/scripts/build_western_direction_survey.py
"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLOW_DIR = ROOT / "backend" / "static" / "snow-plows"
MANIFEST = PLOW_DIR / "skus" / "_manifest.json"
OUT = PLOW_DIR / "_western_direction.html"

# Possible locations for the prior classifications export
CLASSIFICATION_CANDIDATES = [
    Path.home() / "Downloads" / "plow_survey_classifications.json",
    PLOW_DIR / "plow_survey_classifications.json",
]


def load_classifications() -> dict[str, dict]:
    for p in CLASSIFICATION_CANDIDATES:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            print(f"Loaded prior classifications from {p}")
            return data.get("classifications", data)
    print("No prior classifications JSON found — including ALL Western SKUs.")
    return {}


def load_skus() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data.get("skus", [])


def filter_clean_westerns(skus: list[dict], cls: dict[str, dict]) -> list[dict]:
    out = []
    problem_tags = {"has-truck", "watermark", "bad-angle", "unusable"}
    for s in skus:
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


def render(skus: list[dict]) -> str:
    cards = []
    for s in skus:
        sku = s.get("stockid_sanitized", "")
        brand = s.get("brand", "Western")
        title = s.get("title", "")
        img = f"skus/{sku}/hero.jpg"
        cards.append({"sku": sku, "brand": brand, "title": title, "img": img})
    cards_json = json.dumps(cards)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Western Plow Direction Survey ({len(cards)} SKUs)</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: -apple-system, system-ui, Segoe UI, sans-serif;
    background: #f5f6f8; color: #222;
  }}
  header {{
    position: sticky; top: 0; z-index: 10;
    background: #1f2937; color: #fff; padding: 12px 20px;
    display: flex; gap: 20px; align-items: center; flex-wrap: wrap;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
  }}
  header h1 {{ margin: 0; font-size: 18px; font-weight: 600; }}
  .stats {{ display: flex; gap: 14px; font-size: 13px; flex-wrap: wrap; }}
  .stats span {{ background: rgba(255,255,255,0.1); padding: 4px 10px; border-radius: 999px; }}
  .stats span.warn {{ background: #b45309; }}
  .stats span.ok {{ background: #047857; }}
  .stats span.left {{ background: #1d4ed8; }}
  .stats span.right {{ background: #be185d; }}
  .controls {{ display: flex; gap: 8px; flex-wrap: wrap; margin-left: auto; }}
  .controls button {{
    background: #374151; color: #fff; border: 1px solid #4b5563;
    padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
  }}
  .controls button:hover {{ background: #4b5563; }}
  .help {{
    background: #fff; padding: 12px 20px; border-bottom: 1px solid #e5e7eb;
    font-size: 13px; color: #4b5563;
  }}
  .help b {{ color: #1f2937; }}
  .help kbd {{
    background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 3px;
    padding: 1px 5px; font-family: ui-monospace, Consolas, monospace; font-size: 11px;
  }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px; padding: 20px;
  }}
  .card {{
    background: #fff; border-radius: 8px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 3px solid transparent;
    display: flex; flex-direction: column; transition: border-color 0.15s, transform 0.15s;
  }}
  .card.left  {{ border-color: #3b82f6; }}
  .card.right {{ border-color: #ec4899; }}
  .card.unclear {{ border-color: #9ca3af; }}
  .card.focus {{ box-shadow: 0 0 0 4px rgba(99,102,241,0.35); transform: scale(1.01); }}
  .img-wrap {{
    background: repeating-conic-gradient(#e5e7eb 0 25%, #f9fafb 0 50%) 50% / 16px 16px;
    aspect-ratio: 16/10; display: flex; align-items: center; justify-content: center;
    overflow: hidden;
  }}
  .img-wrap img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
  .meta {{ padding: 8px 12px; font-size: 12px; }}
  .meta .sku {{ font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: #6b7280; }}
  .meta .title {{ color: #4b5563; line-height: 1.35; margin-top: 2px; }}
  .buttons {{
    display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px;
    padding: 8px 12px; border-top: 1px solid #f3f4f6;
  }}
  .buttons button {{
    border: 1px solid #d1d5db; background: #f9fafb; color: #374151;
    padding: 6px 8px; border-radius: 6px; cursor: pointer;
    font-size: 12px; font-weight: 500;
  }}
  .buttons button .key {{
    font-family: ui-monospace, Consolas, monospace; opacity: 0.5; margin-right: 4px;
  }}
  .buttons button:hover {{ background: #f3f4f6; }}
  .buttons button.active.left  {{ background: #3b82f6; color: #fff; border-color: #3b82f6; }}
  .buttons button.active.right {{ background: #ec4899; color: #fff; border-color: #ec4899; }}
  .buttons button.active.unclear {{ background: #6b7280; color: #fff; border-color: #6b7280; }}
  .saved-indicator {{
    position: fixed; bottom: 16px; right: 16px;
    background: #065f46; color: #fff; padding: 8px 14px; border-radius: 6px;
    font-size: 13px; opacity: 0; transition: opacity 0.3s;
    pointer-events: none;
  }}
  .saved-indicator.visible {{ opacity: 1; }}
</style>
</head>
<body>

<header>
  <h1>Western Plow Direction</h1>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <button id="export">Export JSON</button>
    <button id="reset">Reset</button>
  </div>
</header>

<div class="help">
  <b>Question:</b> Which side of the plow is forward toward the camera?
  <br>
  Click a card to focus it, then press <kbd>1</kbd> Left side forward &nbsp;
  <kbd>2</kbd> Right side forward &nbsp; <kbd>3</kbd> Straight / unclear &nbsp;
  &middot; <kbd>J</kbd>/<kbd>K</kbd> next/prev
</div>

<div class="grid" id="grid"></div>
<div class="saved-indicator" id="saved">Saved</div>

<script>
const CARDS = {cards_json};
const STORAGE_KEY = "western-direction-v1";
const OPTIONS = [
  {{ key: "1", id: "left",    label: "← Left side fwd" }},
  {{ key: "2", id: "right",   label: "Right side fwd →" }},
  {{ key: "3", id: "unclear", label: "Straight / ?" }},
];

let state = loadState();
let focusIdx = 0;

function loadState() {{
  try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}"); }}
  catch (e) {{ return {{}}; }}
}}
function saveState() {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  const ind = document.getElementById("saved");
  ind.classList.add("visible");
  clearTimeout(ind._t);
  ind._t = setTimeout(() => ind.classList.remove("visible"), 600);
}}

function setDirection(sku, dir) {{
  // Toggle off if the same button is clicked again
  if (state[sku] === dir) {{
    delete state[sku];
  }} else {{
    state[sku] = dir;
  }}
  saveState();
  renderCard(sku);
  renderStats();
}}

function renderCard(sku) {{
  const card = document.querySelector(`[data-sku="${{sku}}"]`);
  if (!card) return;
  const dir = state[sku];
  card.classList.remove("left", "right", "unclear");
  if (dir) card.classList.add(dir);
  OPTIONS.forEach((o) => {{
    const btn = card.querySelector(`[data-dir="${{o.id}}"]`);
    btn.classList.toggle("active", dir === o.id);
  }});
}}

function renderStats() {{
  const total = CARDS.length;
  const counts = {{ left: 0, right: 0, unclear: 0 }};
  CARDS.forEach((c) => {{
    const d = state[c.sku];
    if (d) counts[d] = (counts[d] || 0) + 1;
  }});
  const tagged = counts.left + counts.right + counts.unclear;
  const remaining = total - tagged;
  const html = [
    `<span>Total <b>${{total}}</b></span>`,
    `<span class="${{remaining ? "warn" : "ok"}}">Untagged <b>${{remaining}}</b></span>`,
    `<span class="left">← Left <b>${{counts.left}}</b></span>`,
    `<span class="right">Right → <b>${{counts.right}}</b></span>`,
    `<span>Unclear <b>${{counts.unclear}}</b></span>`,
  ].join("");
  document.getElementById("stats").innerHTML = html;
}}

function buildGrid() {{
  const grid = document.getElementById("grid");
  CARDS.forEach((c, idx) => {{
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.sku = c.sku;
    card.dataset.idx = idx;
    card.innerHTML = `
      <div class="img-wrap"><img loading="lazy" src="${{c.img}}" alt="${{c.sku}}"></div>
      <div class="meta">
        <div class="sku">${{c.sku}}</div>
        <div class="title">${{c.title}}</div>
      </div>
      <div class="buttons">
        ${{OPTIONS.map((o) =>
          `<button class="${{o.id}}" data-dir="${{o.id}}"><span class="key">${{o.key}}</span>${{o.label}}</button>`
        ).join("")}}
      </div>
    `;
    grid.appendChild(card);
    card.querySelectorAll(".buttons button").forEach((btn) => {{
      btn.addEventListener("click", (ev) => {{
        ev.stopPropagation();
        setDirection(c.sku, btn.dataset.dir);
      }});
    }});
    card.addEventListener("click", () => setFocus(idx));
    renderCard(c.sku);
  }});
}}

function setFocus(idx) {{
  document.querySelectorAll(".card.focus").forEach((c) => c.classList.remove("focus"));
  focusIdx = idx;
  const card = document.querySelector(`[data-idx="${{idx}}"]`);
  if (card) {{
    card.classList.add("focus");
    card.scrollIntoView({{ behavior: "smooth", block: "center" }});
  }}
}}

document.addEventListener("keydown", (ev) => {{
  if (ev.target.tagName === "TEXTAREA" || ev.target.tagName === "INPUT") return;
  const k = ev.key.toLowerCase();
  const sku = CARDS[focusIdx]?.sku;
  if (k === "1" && sku) setDirection(sku, "left");
  else if (k === "2" && sku) setDirection(sku, "right");
  else if (k === "3" && sku) setDirection(sku, "unclear");
  else if (k === "j") setFocus(Math.min(focusIdx + 1, CARDS.length - 1));
  else if (k === "k") setFocus(Math.max(focusIdx - 1, 0));
}});

document.getElementById("export").addEventListener("click", () => {{
  const out = {{
    exported_at: new Date().toISOString(),
    n_total: CARDS.length,
    directions: state,
  }};
  const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: "application/json" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "western_direction.json"; a.click();
  URL.revokeObjectURL(url);
}});

document.getElementById("reset").addEventListener("click", () => {{
  if (!confirm("Clear all direction labels? This cannot be undone.")) return;
  state = {{}};
  saveState();
  CARDS.forEach((c) => renderCard(c.sku));
  renderStats();
}});

buildGrid();
renderStats();
setFocus(0);
</script>
</body>
</html>
"""


def main() -> None:
    cls = load_classifications()
    skus = load_skus()
    westerns = filter_clean_westerns(skus, cls)
    OUT.write_text(render(westerns), encoding="utf-8")
    print(f"Wrote {OUT} ({len(westerns)} clean Western SKUs)")
    print(f"Open: file:///{OUT.as_posix()}")


if __name__ == "__main__":
    main()
