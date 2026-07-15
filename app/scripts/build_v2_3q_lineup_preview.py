"""Apply the recommended w=0.60/y=0.65 positioning to MVP3 on all 6 v2-3q trucks.

Output: 6 composite PNGs + 1 HTML page. This is the "ship now" baseline
the user can approve in the morning if no further angle work is wanted.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1].parent
TRUCKS = REPO / "app" / "backend" / "static" / "trucks" / "renders_3q"
PLOW = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
OUT_DIR = REPO / "wan_test_output" / "v2_3q_lineup_preview"

W_RATIO = 0.60
Y_RATIO = 0.65

CLASSES = ["mid-size", "1500", "2500", "3500", "4500", "5500"]


def composite(truck_path: Path, plow_img: Image.Image) -> Image.Image:
    truck = Image.open(truck_path).convert("RGBA")
    Tw, Th = truck.size
    target_w = int(Tw * W_RATIO)
    aspect = plow_img.height / plow_img.width
    target_h = int(target_w * aspect)
    plow_resized = plow_img.resize((target_w, target_h), Image.LANCZOS)
    cx = Tw // 2
    cy = int(Th * Y_RATIO)
    paste_x = cx - target_w // 2
    paste_y = cy - target_h // 2
    out = truck.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plow = Image.open(PLOW).convert("RGBA")
    saved = []
    for cls in CLASSES:
        truck_path = TRUCKS / f"{cls}.png"
        if not truck_path.exists():
            print(f"  ! missing {truck_path}")
            continue
        result = composite(truck_path, plow)
        out_path = OUT_DIR / f"{cls}_with_mvp3.png"
        result.save(out_path)
        saved.append((cls, out_path.name))
        print(f"  saved {out_path.name}")

    import json as _json
    cards_data = [{"cls": cls, "img": name} for cls, name in saved]
    (OUT_DIR / "_lineup.html").write_text(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>v2-3q lineup preview — MVP3 at w=0.60/y=0.65</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,system-ui,Segoe UI,sans-serif;
          background:#1f2937; color:#fff; padding:0; }}
  header {{ position:sticky; top:0; z-index:10;
            background:#0b1220; padding:10px 16px;
            display:flex; gap:14px; align-items:center; flex-wrap:wrap;
            border-bottom:1px solid #1f2937; }}
  header h1 {{ margin:0; font-size:15px; font-weight:600; }}
  .stats {{ display:flex; gap:8px; font-size:12px; flex-wrap:wrap; }}
  .stats span {{ background:rgba(255,255,255,0.08); padding:3px 8px; border-radius:999px; }}
  .stats span.ok {{ background:#047857; }}
  .stats span.warn {{ background:#b45309; }}
  .stats span.bad {{ background:#dc2626; }}
  .controls {{ margin-left:auto; display:flex; gap:6px; }}
  .controls button {{ background:#374151; color:#fff; border:1px solid #4b5563;
                      padding:5px 10px; border-radius:5px; cursor:pointer; font-size:12px; }}
  .help {{ background:#0f172a; padding:8px 16px; font-size:12px;
          color:#9ca3af; border-bottom:1px solid #1f2937; }}
  .help kbd {{ background:#1e293b; border:1px solid #334155; border-radius:3px;
              padding:1px 5px; font-family:ui-monospace,Consolas,monospace;
              font-size:11px; color:#e5e7eb; }}
  .grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:14px;
           padding:14px; }}
  .card {{ background:#111827; padding:10px; border-radius:6px;
           border:3px solid transparent; transition:border-color 0.15s; }}
  .card.approve {{ border-color:#10b981; }}
  .card.adjust  {{ border-color:#f59e0b; }}
  .card.reject  {{ border-color:#ef4444; }}
  .card.focus   {{ box-shadow:0 0 0 3px rgba(99,102,241,0.4); }}
  .card-head {{ display:flex; justify-content:space-between; align-items:center;
                margin-bottom:6px; }}
  .card-head h3 {{ margin:0; color:#10b981; font-size:14px;
                  font-family:ui-monospace,Consolas,monospace; }}
  .verdict {{ font-size:11px; padding:2px 8px; border-radius:999px;
              background:#374151; color:#9ca3af; }}
  .card.approve .verdict {{ background:#065f46; color:#d1fae5; }}
  .card.adjust  .verdict {{ background:#92400e; color:#fef3c7; }}
  .card.reject  .verdict {{ background:#991b1b; color:#fee2e2; }}
  .card img {{ width:100%; border-radius:4px; display:block; }}
  .verdicts {{ display:grid; grid-template-columns:repeat(3,1fr); gap:4px;
               margin-top:8px; }}
  .verdicts button {{ font-size:11px; padding:5px 6px; cursor:pointer;
                      background:#1f2937; border:1px solid #374151;
                      border-radius:4px; color:#e5e7eb; }}
  .verdicts button.active.approve {{ background:#10b981; border-color:#10b981; color:#022c22; }}
  .verdicts button.active.adjust  {{ background:#f59e0b; border-color:#f59e0b; color:#451a03; }}
  .verdicts button.active.reject  {{ background:#ef4444; border-color:#ef4444; color:#450a0a; }}
  .tags {{ display:flex; flex-wrap:wrap; gap:3px; margin-top:6px; }}
  .tag {{ font-size:10px; padding:3px 7px; border-radius:999px;
          background:#1f2937; border:1px solid #374151; color:#9ca3af;
          cursor:pointer; user-select:none; }}
  .tag.active {{ background:#1d4ed8; border-color:#3b82f6; color:#dbeafe; }}
  .notes {{ width:100%; margin-top:6px; background:#0f172a;
           border:1px solid #334155; border-radius:4px;
           padding:6px 8px; font-size:11px; color:#e5e7eb;
           font-family:inherit; resize:vertical; min-height:30px; }}
  .notes:focus {{ outline:none; border-color:#3b82f6; }}
  .saved-indicator {{ position:fixed; bottom:16px; right:16px;
                     background:#065f46; color:#fff;
                     padding:8px 14px; border-radius:6px; font-size:13px;
                     opacity:0; transition:opacity 0.3s; pointer-events:none; }}
  .saved-indicator.visible {{ opacity:1; }}
</style></head><body>

<header>
  <h1>v2-3q lineup preview — MVP3 at w=0.60/y=0.65</h1>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <button id="export">Export JSON</button>
    <button id="reset">Reset</button>
  </div>
</header>
<div class="help">
  Click verdict (Approve / Adjust / Reject), then optionally tag what to change. Notes capture anything specific.
  Keyboard: <kbd>1</kbd> Approve <kbd>2</kbd> Adjust <kbd>3</kbd> Reject
  &middot; <kbd>J</kbd>/<kbd>K</kbd> next/prev <kbd>N</kbd> notes
</div>
<div class="grid" id="grid"></div>
<div class="saved-indicator" id="saved">Saved</div>

<script>
const CARDS = {_json.dumps(cards_data)};
const KEY = "v2-3q-lineup-feedback-v1";
const VERDICTS = [
  {{key: "1", id: "approve", label: "✓ Approve"}},
  {{key: "2", id: "adjust",  label: "⚙ Adjust"}},
  {{key: "3", id: "reject",  label: "✗ Reject"}},
];
const TAGS = [
  "plow too high", "plow too low",
  "plow too left", "plow too right",
  "plow too big", "plow too small",
  "truck artifacts", "plow artifacts",
];

let state = JSON.parse(localStorage.getItem(KEY) || "{{}}");
let focusIdx = 0;

function getEntry(cls) {{
  if (!state[cls]) state[cls] = {{ verdict: null, tags: [], notes: "" }};
  return state[cls];
}}
function save() {{
  localStorage.setItem(KEY, JSON.stringify(state));
  const ind = document.getElementById("saved");
  ind.classList.add("visible");
  clearTimeout(ind._t);
  ind._t = setTimeout(() => ind.classList.remove("visible"), 600);
  renderStats();
}}

function setVerdict(cls, v) {{
  const e = getEntry(cls);
  if (e.verdict === v) e.verdict = null;
  else e.verdict = v;
  save(); applyClasses(cls);
}}
function toggleTag(cls, tag) {{
  const e = getEntry(cls);
  const i = e.tags.indexOf(tag);
  if (i >= 0) e.tags.splice(i, 1); else e.tags.push(tag);
  save(); applyClasses(cls);
}}

function applyClasses(cls) {{
  const card = document.querySelector(`[data-cls="${{cls}}"]`);
  if (!card) return;
  const e = state[cls] || {{}};
  card.classList.remove("approve", "adjust", "reject");
  if (e.verdict) card.classList.add(e.verdict);
  card.querySelectorAll(".verdicts button").forEach(b => {{
    b.classList.toggle("active", e.verdict === b.dataset.v);
  }});
  card.querySelectorAll(".tag").forEach(t => {{
    t.classList.toggle("active", (e.tags || []).includes(t.dataset.tag));
  }});
  const v = e.verdict;
  card.querySelector(".verdict").textContent =
    v === "approve" ? "✓ Approved"
    : v === "adjust" ? "⚙ Needs adjustment"
    : v === "reject" ? "✗ Rejected"
    : "untagged";
}}

function renderStats() {{
  const t = CARDS.length;
  let a=0, j=0, r=0;
  CARDS.forEach(c => {{
    const v = state[c.cls]?.verdict;
    if (v === "approve") a++;
    else if (v === "adjust") j++;
    else if (v === "reject") r++;
  }});
  const u = t - a - j - r;
  document.getElementById("stats").innerHTML =
    `<span>Total <b>${{t}}</b></span>` +
    `<span class="ok">Approve <b>${{a}}</b></span>` +
    `<span class="warn">Adjust <b>${{j}}</b></span>` +
    `<span class="bad">Reject <b>${{r}}</b></span>` +
    `<span>Untagged <b>${{u}}</b></span>`;
}}

function setFocus(idx) {{
  document.querySelectorAll(".card.focus").forEach(c => c.classList.remove("focus"));
  focusIdx = Math.max(0, Math.min(idx, CARDS.length - 1));
  const card = document.querySelector(`[data-idx="${{focusIdx}}"]`);
  if (card) {{
    card.classList.add("focus");
    card.scrollIntoView({{behavior:"smooth", block:"center"}});
  }}
}}

function build() {{
  const grid = document.getElementById("grid");
  CARDS.forEach((c, idx) => {{
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.cls = c.cls;
    card.dataset.idx = idx;
    card.innerHTML = `
      <div class="card-head">
        <h3>${{c.cls}}</h3>
        <span class="verdict">untagged</span>
      </div>
      <img src="${{c.img}}">
      <div class="verdicts">
        ${{VERDICTS.map(v =>
          `<button class="${{v.id}}" data-v="${{v.id}}">${{v.label}}</button>`
        ).join("")}}
      </div>
      <div class="tags">
        ${{TAGS.map(t => `<span class="tag" data-tag="${{t}}">${{t}}</span>`).join("")}}
      </div>
      <textarea class="notes" placeholder="Notes (specifics: 'shift plow 20px right', 'truck has FORD typo', etc.)"></textarea>
    `;
    grid.appendChild(card);
    const e = getEntry(c.cls);
    card.querySelector(".notes").value = e.notes || "";
    card.querySelector(".notes").addEventListener("input", ev => {{
      e.notes = ev.target.value; save();
    }});
    card.querySelectorAll(".verdicts button").forEach(b => {{
      b.addEventListener("click", ev => {{ ev.stopPropagation(); setVerdict(c.cls, b.dataset.v); }});
    }});
    card.querySelectorAll(".tag").forEach(t => {{
      t.addEventListener("click", ev => {{ ev.stopPropagation(); toggleTag(c.cls, t.dataset.tag); }});
    }});
    card.addEventListener("click", () => setFocus(idx));
    applyClasses(c.cls);
  }});
}}

document.addEventListener("keydown", ev => {{
  if (ev.target.tagName === "TEXTAREA" || ev.target.tagName === "INPUT") {{
    if (ev.key === "Escape") ev.target.blur();
    return;
  }}
  const k = ev.key.toLowerCase();
  const cls = CARDS[focusIdx]?.cls;
  if (k === "1" && cls) setVerdict(cls, "approve");
  else if (k === "2" && cls) setVerdict(cls, "adjust");
  else if (k === "3" && cls) setVerdict(cls, "reject");
  else if (k === "j") setFocus(focusIdx + 1);
  else if (k === "k") setFocus(focusIdx - 1);
  else if (k === "n") {{
    document.querySelector(`[data-idx="${{focusIdx}}"] .notes`)?.focus();
    ev.preventDefault();
  }}
}});

document.getElementById("export").addEventListener("click", () => {{
  const out = {{
    exported_at: new Date().toISOString(),
    n_total: CARDS.length,
    feedback: state,
  }};
  const blob = new Blob([JSON.stringify(out, null, 2)], {{type:"application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "v2_3q_lineup_feedback.json"; a.click();
  URL.revokeObjectURL(url);
}});
document.getElementById("reset").addEventListener("click", () => {{
  if (!confirm("Clear all feedback?")) return;
  state = {{}}; save();
  CARDS.forEach(c => {{ applyClasses(c.cls); }});
  document.querySelectorAll(".notes").forEach(n => n.value = "");
}});

build(); renderStats(); setFocus(0);
</script>
</body></html>""",
        encoding="utf-8",
    )
    print(f"\nopen: file:///{(OUT_DIR / '_lineup.html').as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
