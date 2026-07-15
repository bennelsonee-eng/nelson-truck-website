"""Generate _survey.html — a single-file classifier for plow hero images.

Reads `app/backend/static/snow-plows/skus/_manifest.json`, emits
`_survey.html` alongside it. Open the HTML directly in a browser (no
server needed). All state persists in localStorage; export/import JSON
for sharing or backup.

Usage:
    python app/scripts/build_plow_survey.py
"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLOW_DIR = ROOT / "backend" / "static" / "snow-plows"
MANIFEST = PLOW_DIR / "skus" / "_manifest.json"
OUT = PLOW_DIR / "_survey.html"


def load_skus() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    skus = data.get("skus", [])
    skus.sort(key=lambda s: (s.get("brand", ""), s.get("stockid_sanitized", "")))
    return skus


def render(skus: list[dict]) -> str:
    cards = []
    for s in skus:
        sku = s.get("stockid_sanitized", "")
        brand = s.get("brand", "Unknown")
        title = s.get("title", "")
        # Image path is relative to _survey.html (which lives in snow-plows/)
        img = f"skus/{sku}/hero.jpg"
        cards.append(
            {
                "sku": sku,
                "brand": brand,
                "title": title,
                "img": img,
            }
        )

    cards_json = json.dumps(cards)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Plow Hero Survey ({len(cards)} SKUs)</title>
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
  .controls {{ display: flex; gap: 8px; flex-wrap: wrap; margin-left: auto; }}
  .controls button {{
    background: #374151; color: #fff; border: 1px solid #4b5563;
    padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
  }}
  .controls button:hover {{ background: #4b5563; }}
  .controls select {{
    background: #374151; color: #fff; border: 1px solid #4b5563;
    padding: 6px 10px; border-radius: 6px; font-size: 13px;
  }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px; padding: 20px;
  }}
  .card {{
    background: #fff; border-radius: 8px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 2px solid transparent;
    display: flex; flex-direction: column; transition: border-color 0.15s;
  }}
  .card.tagged {{ border-color: #10b981; }}
  .card.bad {{ border-color: #ef4444; }}
  .card.focus {{ border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,0.25); }}
  .card.hidden {{ display: none; }}
  .img-wrap {{
    background: repeating-conic-gradient(#e5e7eb 0 25%, #f9fafb 0 50%) 50% / 16px 16px;
    aspect-ratio: 16/10; display: flex; align-items: center; justify-content: center;
    overflow: hidden;
  }}
  .img-wrap img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
  .meta {{ padding: 10px 12px; font-size: 12px; }}
  .meta .sku {{ font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: #6b7280; }}
  .meta .brand {{ font-weight: 600; color: #1f2937; margin: 2px 0; }}
  .meta .title {{ color: #4b5563; line-height: 1.35; }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 4px; padding: 8px 12px; border-top: 1px solid #f3f4f6; }}
  .tag {{
    font-size: 11px; padding: 4px 8px; border-radius: 999px;
    border: 1px solid #d1d5db; background: #f9fafb; cursor: pointer;
    user-select: none; white-space: nowrap;
  }}
  .tag.active.clean {{ background: #d1fae5; border-color: #10b981; color: #065f46; }}
  .tag.active.has-truck {{ background: #fee2e2; border-color: #ef4444; color: #991b1b; }}
  .tag.active.watermark {{ background: #fef3c7; border-color: #f59e0b; color: #92400e; }}
  .tag.active.bad-angle {{ background: #ede9fe; border-color: #8b5cf6; color: #5b21b6; }}
  .tag.active.unusable {{ background: #1f2937; border-color: #1f2937; color: #fff; }}
  .tag .key {{ font-family: ui-monospace, Consolas, monospace; opacity: 0.6; margin-right: 3px; }}
  .notes {{
    width: 100%; border: none; border-top: 1px solid #f3f4f6;
    padding: 8px 12px; font-size: 12px; font-family: inherit; resize: vertical; min-height: 32px;
  }}
  .notes:focus {{ outline: none; background: #fffbeb; }}
  .help {{
    background: #fff; padding: 12px 20px; border-bottom: 1px solid #e5e7eb;
    font-size: 13px; color: #4b5563;
  }}
  .help kbd {{
    background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 3px;
    padding: 1px 5px; font-family: ui-monospace, Consolas, monospace; font-size: 11px;
  }}
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
  <h1>Plow Hero Survey</h1>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <select id="filter-brand"><option value="">All brands</option></select>
    <select id="filter-tag">
      <option value="">All</option>
      <option value="untagged">Untagged only</option>
      <option value="clean">Clean only</option>
      <option value="problems">Has problems</option>
    </select>
    <button id="export">Export JSON</button>
    <button id="import">Import JSON</button>
    <input id="import-file" type="file" accept="application/json" style="display:none">
    <button id="reset">Reset</button>
  </div>
</header>

<div class="help">
  Click tags to toggle, or use keyboard: <kbd>1</kbd> Clean &nbsp;
  <kbd>2</kbd> Has truck &nbsp; <kbd>3</kbd> Watermark &nbsp;
  <kbd>4</kbd> Bad angle &nbsp; <kbd>5</kbd> Unusable &nbsp;
  &middot; <kbd>J</kbd>/<kbd>K</kbd> next/prev &nbsp; <kbd>N</kbd> focus notes
</div>

<div class="grid" id="grid"></div>
<div class="saved-indicator" id="saved">Saved</div>

<script>
const CARDS = {cards_json};
const STORAGE_KEY = "plow-survey-v1";
const TAGS = [
  {{ key: "1", id: "clean",      label: "Clean" }},
  {{ key: "2", id: "has-truck",  label: "Has truck" }},
  {{ key: "3", id: "watermark",  label: "Watermark" }},
  {{ key: "4", id: "bad-angle",  label: "Bad angle" }},
  {{ key: "5", id: "unusable",   label: "Unusable" }},
];

let state = loadState();
let focusIdx = 0;

function loadState() {{
  try {{
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}");
  }} catch (e) {{ return {{}}; }}
}}
function saveState() {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  const ind = document.getElementById("saved");
  ind.classList.add("visible");
  clearTimeout(ind._t);
  ind._t = setTimeout(() => ind.classList.remove("visible"), 600);
}}

function getEntry(sku) {{
  if (!state[sku]) state[sku] = {{ tags: [], notes: "" }};
  return state[sku];
}}

function toggleTag(sku, tagId) {{
  const e = getEntry(sku);
  const i = e.tags.indexOf(tagId);
  if (i >= 0) e.tags.splice(i, 1); else e.tags.push(tagId);
  saveState();
  renderCard(sku);
  renderStats();
  applyFilter();
}}

function renderCard(sku) {{
  const card = document.querySelector(`[data-sku="${{sku}}"]`);
  if (!card) return;
  const e = getEntry(sku);
  card.classList.toggle("tagged", e.tags.includes("clean"));
  card.classList.toggle("bad", e.tags.includes("unusable"));
  TAGS.forEach((t) => {{
    const el = card.querySelector(`[data-tag="${{t.id}}"]`);
    el.classList.toggle("active", e.tags.includes(t.id));
  }});
}}

function renderStats() {{
  const total = CARDS.length;
  const counts = {{ tagged: 0 }};
  TAGS.forEach((t) => (counts[t.id] = 0));
  CARDS.forEach((c) => {{
    const e = state[c.sku];
    if (e && e.tags && e.tags.length) {{
      counts.tagged++;
      e.tags.forEach((t) => (counts[t] = (counts[t] || 0) + 1));
    }}
  }});
  const remaining = total - counts.tagged;
  const html = [
    `<span>Total <b>${{total}}</b></span>`,
    `<span class="${{remaining ? "warn" : "ok"}}">Untagged <b>${{remaining}}</b></span>`,
    ...TAGS.map((t) => `<span>${{t.label}} <b>${{counts[t.id] || 0}}</b></span>`),
  ].join("");
  document.getElementById("stats").innerHTML = html;
}}

function applyFilter() {{
  const brand = document.getElementById("filter-brand").value;
  const tagFilter = document.getElementById("filter-tag").value;
  CARDS.forEach((c) => {{
    const card = document.querySelector(`[data-sku="${{c.sku}}"]`);
    const e = state[c.sku] || {{ tags: [] }};
    let show = true;
    if (brand && c.brand !== brand) show = false;
    if (tagFilter === "untagged" && e.tags && e.tags.length) show = false;
    if (tagFilter === "clean" && !e.tags.includes("clean")) show = false;
    if (tagFilter === "problems") {{
      const hasProblem = ["has-truck", "watermark", "bad-angle", "unusable"]
        .some((t) => e.tags.includes(t));
      if (!hasProblem) show = false;
    }}
    card.classList.toggle("hidden", !show);
  }});
}}

function buildBrandFilter() {{
  const brands = [...new Set(CARDS.map((c) => c.brand))].sort();
  const sel = document.getElementById("filter-brand");
  brands.forEach((b) => {{
    const opt = document.createElement("option");
    opt.value = b; opt.textContent = b;
    sel.appendChild(opt);
  }});
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
        <div class="brand">${{c.brand}}</div>
        <div class="title">${{c.title}}</div>
      </div>
      <div class="tags">
        ${{TAGS.map((t) =>
          `<span class="tag ${{t.id}}" data-tag="${{t.id}}"><span class="key">${{t.key}}</span>${{t.label}}</span>`
        ).join("")}}
      </div>
      <textarea class="notes" placeholder="Notes…"></textarea>
    `;
    grid.appendChild(card);
    const e = getEntry(c.sku);
    card.querySelector(".notes").value = e.notes || "";
    card.querySelector(".notes").addEventListener("input", (ev) => {{
      e.notes = ev.target.value;
      saveState();
    }});
    card.querySelectorAll(".tag").forEach((el) => {{
      el.addEventListener("click", () => toggleTag(c.sku, el.dataset.tag));
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
  if (ev.target.tagName === "TEXTAREA" || ev.target.tagName === "INPUT") {{
    if (ev.key === "Escape") ev.target.blur();
    return;
  }}
  const k = ev.key.toLowerCase();
  const visible = [...document.querySelectorAll(".card:not(.hidden)")];
  const visIdx = visible.findIndex((c) => Number(c.dataset.idx) === focusIdx);
  const sku = CARDS[focusIdx]?.sku;

  if (k >= "1" && k <= "5") {{
    const t = TAGS[Number(k) - 1];
    if (t && sku) toggleTag(sku, t.id);
  }} else if (k === "j") {{
    const next = visible[Math.min(visIdx + 1, visible.length - 1)];
    if (next) setFocus(Number(next.dataset.idx));
  }} else if (k === "k") {{
    const prev = visible[Math.max(visIdx - 1, 0)];
    if (prev) setFocus(Number(prev.dataset.idx));
  }} else if (k === "n") {{
    const card = document.querySelector(`[data-idx="${{focusIdx}}"]`);
    card?.querySelector(".notes")?.focus();
    ev.preventDefault();
  }}
}});

document.getElementById("export").addEventListener("click", () => {{
  const out = {{
    exported_at: new Date().toISOString(),
    n_total: CARDS.length,
    classifications: state,
  }};
  const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: "application/json" }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "plow_survey_classifications.json"; a.click();
  URL.revokeObjectURL(url);
}});

document.getElementById("import").addEventListener("click", () => {{
  document.getElementById("import-file").click();
}});
document.getElementById("import-file").addEventListener("change", async (ev) => {{
  const f = ev.target.files[0];
  if (!f) return;
  const data = JSON.parse(await f.text());
  state = data.classifications || data;
  saveState();
  CARDS.forEach((c) => renderCard(c.sku));
  document.querySelectorAll(".card").forEach((card) => {{
    const e = state[card.dataset.sku] || {{}};
    card.querySelector(".notes").value = e.notes || "";
  }});
  renderStats();
  applyFilter();
}});

document.getElementById("reset").addEventListener("click", () => {{
  if (!confirm("Clear all classifications? This cannot be undone.")) return;
  state = {{}};
  saveState();
  CARDS.forEach((c) => renderCard(c.sku));
  document.querySelectorAll(".notes").forEach((n) => (n.value = ""));
  renderStats();
  applyFilter();
}});

document.getElementById("filter-brand").addEventListener("change", applyFilter);
document.getElementById("filter-tag").addEventListener("change", applyFilter);

buildBrandFilter();
buildGrid();
renderStats();
setFocus(0);
</script>
</body>
</html>
"""


def main() -> None:
    skus = load_skus()
    OUT.write_text(render(skus), encoding="utf-8")
    print(f"Wrote {OUT} ({len(skus)} SKUs)")
    print(f"Open: file:///{OUT.as_posix()}")


if __name__ == "__main__":
    main()
