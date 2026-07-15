"""Generate _eraser.html — manual eraser tool for plow transparent PNGs.

Loads each plow's hero_transparent (or _x4) into a canvas, lets the user
paint over artifacts with a brush that sets alpha to 0. Undo / redo / brush
size / reset / download buttons. The download saves a corrected PNG that
the user drops into the SKU folder, replacing the previous file.

Usage: open `http://localhost:8765/snow-plows/_eraser.html` in a browser.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLOW_DIR = ROOT / "backend" / "static" / "snow-plows"
MANIFEST = PLOW_DIR / "skus" / "_manifest.json"
OUT = PLOW_DIR / "_eraser.html"


def load_plows() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    plows = []
    deny = {"SNOW-16020312-EQP"}
    for s in data.get("skus", []):
        sku = s.get("stockid_sanitized", "")
        if sku in deny:
            continue
        if not (sku.startswith("WEST-") or sku.startswith("SNOW-")):
            continue
        x4 = PLOW_DIR / "skus" / sku / "hero_transparent_x4.png"
        std = PLOW_DIR / "skus" / sku / "hero_transparent.png"
        if x4.exists():
            img_path = f"skus/{sku}/hero_transparent_x4.png"
            kind = "x4"
        elif std.exists():
            img_path = f"skus/{sku}/hero_transparent.png"
            kind = "std"
        else:
            continue
        plows.append({
            "sku": sku,
            "title": s.get("title", ""),
            "img": img_path,
            "kind": kind,
        })
    plows.sort(key=lambda p: (
        0 if p["sku"].startswith("SNOW-") else 1,  # SnowDoggs first since user wants to fix them
        p["sku"],
    ))
    return plows


def render(plows: list[dict]) -> str:
    plows_json = json.dumps(plows)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Plow Eraser</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,system-ui,Segoe UI,sans-serif;
          background:#0f172a; color:#e2e8f0; height:100vh;
          display:grid; grid-template-rows:auto 1fr; }}
  header {{ background:#020617; padding:8px 14px;
            display:flex; gap:14px; align-items:center; flex-wrap:wrap;
            border-bottom:1px solid #1e293b; }}
  header h1 {{ margin:0; font-size:14px; font-weight:600; }}
  header .info {{ font-size:11px; color:#94a3b8;
                 font-family:ui-monospace,Consolas,monospace; }}
  main {{ display:grid; grid-template-columns:280px 1fr; min-height:0; }}
  aside {{ background:#1e293b; overflow-y:auto; border-right:1px solid #334155; }}
  aside .item {{ display:flex; align-items:center; gap:8px;
                padding:6px 10px; cursor:pointer;
                border-bottom:1px solid #0f172a; }}
  aside .item:hover {{ background:#334155; }}
  aside .item.active {{ background:#1d4ed8; }}
  aside .item .thumb {{ width:36px; height:24px; flex:0 0 36px;
                       background:repeating-conic-gradient(#475569 0 25%,#64748b 0 50%) 50%/8px 8px;
                       border-radius:3px; overflow:hidden;
                       display:flex; align-items:center; justify-content:center; }}
  aside .item .thumb img {{ max-width:100%; max-height:100%; object-fit:contain; }}
  aside .item .label {{ flex:1; min-width:0; }}
  aside .item .sku {{ font-family:ui-monospace,Consolas,monospace;
                     font-size:11px; color:#e2e8f0; }}
  aside .item .title {{ font-size:10px; color:#94a3b8;
                       white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .editor {{ display:grid; grid-template-rows:auto 1fr auto;
             min-height:0; }}
  .toolbar {{ background:#0f172a; padding:8px 12px;
              display:flex; gap:14px; align-items:center; flex-wrap:wrap;
              border-bottom:1px solid #1e293b; font-size:12px; color:#94a3b8; }}
  .toolbar label {{ display:flex; align-items:center; gap:6px; }}
  .toolbar button {{ background:#374151; color:#e2e8f0; border:1px solid #4b5563;
                     padding:4px 10px; border-radius:4px; cursor:pointer; font-size:12px; }}
  .toolbar button:hover {{ background:#4b5563; }}
  .toolbar button.primary {{ background:#10b981; border-color:#10b981; color:#022c22; }}
  .toolbar button.danger {{ background:#7f1d1d; border-color:#991b1b; color:#fee2e2; }}
  .toolbar input[type=range] {{ width:130px; }}
  .canvas-wrap {{ background:repeating-conic-gradient(#1e293b 0 25%,#334155 0 50%) 50%/16px 16px;
                  display:flex; align-items:center; justify-content:center;
                  overflow:auto; padding:12px; min-height:0; position:relative; }}
  canvas#editor {{ max-width:100%; max-height:100%; cursor:crosshair;
                  box-shadow:0 0 24px rgba(0,0,0,0.5); }}
  canvas#editor.disabled {{ cursor:default; opacity:0.5; }}
  .footer {{ background:#0f172a; padding:6px 12px; border-top:1px solid #1e293b;
             font-size:11px; color:#94a3b8;
             display:flex; gap:14px; align-items:center; flex-wrap:wrap; }}
  .footer kbd {{ background:#1e293b; border:1px solid #334155;
                padding:1px 5px; border-radius:3px;
                font-family:ui-monospace,Consolas,monospace; font-size:10px; }}
  .empty {{ color:#64748b; padding:40px; text-align:center; font-size:13px; }}
</style></head>
<body>

<header>
  <h1>Plow Eraser</h1>
  <span class="info" id="active-info">Select a plow on the left to start editing</span>
</header>

<main>
  <aside id="plow-list"></aside>

  <div class="editor">
    <div class="toolbar">
      <label>brush:
        <input type="range" id="brush-size" min="2" max="120" value="20">
        <span id="brush-size-val">20</span>px
      </label>
      <label>
        <input type="checkbox" id="restore-mode">
        <span title="Toggle to paint pixels back from the original (undo a region)">restore mode</span>
      </label>
      <button id="undo">Undo (Z)</button>
      <button id="redo">Redo (Y)</button>
      <button id="reset" class="danger">Reset to original</button>
      <span style="flex:1"></span>
      <span style="font-size:11px; color:#94a3b8" id="dims"></span>
      <button id="download" class="primary">Download corrected PNG</button>
    </div>
    <div class="canvas-wrap">
      <div class="empty" id="empty">Select a plow on the left to start editing</div>
      <canvas id="editor" style="display:none"></canvas>
    </div>
    <div class="footer">
      <span>Drag to erase pixels. <kbd>[</kbd>/<kbd>]</kbd> brush size.
      <kbd>Z</kbd> undo, <kbd>Y</kbd> redo, <kbd>R</kbd> toggle restore mode.</span>
      <span style="margin-left:auto">Save the downloaded PNG into <code>app/backend/static/snow-plows/skus/&lt;SKU&gt;/</code> with the original filename to replace.</span>
    </div>
  </div>
</main>

<script>
const PLOWS = {plows_json};

// ---- Plow list ------------------------------------------------------------
const list = document.getElementById("plow-list");
PLOWS.forEach(p => {{
  const div = document.createElement("div");
  div.className = "item";
  div.dataset.sku = p.sku;
  div.innerHTML = `
    <div class="thumb"><img src="${{p.img}}"></div>
    <div class="label">
      <div class="sku">${{p.sku}}</div>
      <div class="title">${{p.title}}</div>
    </div>
  `;
  div.addEventListener("click", () => loadPlow(p));
  list.appendChild(div);
}});

// ---- Editor state ---------------------------------------------------------
const canvas = document.getElementById("editor");
const ctx = canvas.getContext("2d", {{ willReadFrequently: true }});
const empty = document.getElementById("empty");
const activeInfo = document.getElementById("active-info");
const dimsEl = document.getElementById("dims");

let currentPlow = null;
let originalImageData = null;  // ImageData of the source for "restore mode" + reset
let history = [];  // stack of ImageData snapshots
let historyIdx = -1;
const HISTORY_MAX = 30;

let brushSize = 20;
let restoreMode = false;
let drawing = false;
let lastPos = null;

// ---- Loading + history ----------------------------------------------------
async function loadPlow(plow) {{
  currentPlow = plow;
  document.querySelectorAll("aside .item").forEach(it =>
    it.classList.toggle("active", it.dataset.sku === plow.sku)
  );

  const img = new Image();
  img.crossOrigin = "anonymous";
  await new Promise((res, rej) => {{
    img.onload = res;
    img.onerror = rej;
    img.src = plow.img + "?t=" + Date.now();  // bust browser cache
  }});

  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);
  originalImageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  history = [cloneImageData(originalImageData)];
  historyIdx = 0;

  empty.style.display = "none";
  canvas.style.display = "block";
  activeInfo.textContent = `${{plow.sku}}  —  ${{plow.title}}`;
  dimsEl.textContent = `${{canvas.width}} x ${{canvas.height}}px (${{plow.kind}})`;
}}

function cloneImageData(d) {{
  return new ImageData(new Uint8ClampedArray(d.data), d.width, d.height);
}}

function saveHistory() {{
  // truncate redo branch
  history = history.slice(0, historyIdx + 1);
  history.push(cloneImageData(ctx.getImageData(0, 0, canvas.width, canvas.height)));
  if (history.length > HISTORY_MAX) {{
    history.shift();
  }} else {{
    historyIdx++;
  }}
}}

function applyHistoryAt(idx) {{
  if (idx < 0 || idx >= history.length) return;
  ctx.putImageData(history[idx], 0, 0);
  historyIdx = idx;
}}

document.getElementById("undo").addEventListener("click", () => applyHistoryAt(historyIdx - 1));
document.getElementById("redo").addEventListener("click", () => applyHistoryAt(historyIdx + 1));
document.getElementById("reset").addEventListener("click", () => {{
  if (!originalImageData) return;
  ctx.putImageData(originalImageData, 0, 0);
  history = [cloneImageData(originalImageData)];
  historyIdx = 0;
}});

// ---- Brush ----------------------------------------------------------------
const brushSlider = document.getElementById("brush-size");
const brushVal = document.getElementById("brush-size-val");
brushSlider.addEventListener("input", () => {{
  brushSize = parseInt(brushSlider.value, 10);
  brushVal.textContent = brushSize;
}});
document.getElementById("restore-mode").addEventListener("change", e => {{
  restoreMode = e.target.checked;
}});

// Compute canvas-pixel coords from a pointer event
function getPos(ev) {{
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return [(ev.clientX - rect.left) * scaleX, (ev.clientY - rect.top) * scaleY];
}}

function drawDot(x, y) {{
  if (restoreMode) {{
    // Restore: copy a circular region from originalImageData
    if (!originalImageData) return;
    const r = brushSize;
    const x0 = Math.max(0, Math.floor(x - r));
    const y0 = Math.max(0, Math.floor(y - r));
    const x1 = Math.min(canvas.width, Math.ceil(x + r));
    const y1 = Math.min(canvas.height, Math.ceil(y + r));
    const w = x1 - x0;
    const h = y1 - y0;
    if (w <= 0 || h <= 0) return;
    // Read current canvas region
    const cur = ctx.getImageData(x0, y0, w, h);
    // For each pixel inside the brush circle, copy from original
    const od = originalImageData.data;
    const cd = cur.data;
    const stride = canvas.width * 4;
    for (let py = 0; py < h; py++) {{
      for (let px = 0; px < w; px++) {{
        const dx = (x0 + px) - x;
        const dy = (y0 + py) - y;
        if (dx * dx + dy * dy > r * r) continue;
        const ci = (py * w + px) * 4;
        const oi = (y0 + py) * stride + (x0 + px) * 4;
        cd[ci] = od[oi];
        cd[ci + 1] = od[oi + 1];
        cd[ci + 2] = od[oi + 2];
        cd[ci + 3] = od[oi + 3];
      }}
    }}
    ctx.putImageData(cur, x0, y0);
  }} else {{
    // Erase
    ctx.save();
    ctx.globalCompositeOperation = "destination-out";
    ctx.beginPath();
    ctx.arc(x, y, brushSize, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }}
}}

function strokeTo(x, y) {{
  // Interpolate between lastPos and (x,y) so fast drags don't gap
  if (lastPos) {{
    const dx = x - lastPos[0];
    const dy = y - lastPos[1];
    const dist = Math.hypot(dx, dy);
    const steps = Math.max(1, Math.ceil(dist / (brushSize * 0.4)));
    for (let i = 1; i <= steps; i++) {{
      const t = i / steps;
      drawDot(lastPos[0] + dx * t, lastPos[1] + dy * t);
    }}
  }} else {{
    drawDot(x, y);
  }}
  lastPos = [x, y];
}}

canvas.addEventListener("pointerdown", ev => {{
  if (!currentPlow) return;
  ev.preventDefault();
  drawing = true;
  canvas.setPointerCapture(ev.pointerId);
  lastPos = null;
  const [x, y] = getPos(ev);
  strokeTo(x, y);
}});
canvas.addEventListener("pointermove", ev => {{
  if (!drawing) return;
  const [x, y] = getPos(ev);
  strokeTo(x, y);
}});
function endStroke(ev) {{
  if (!drawing) return;
  drawing = false;
  lastPos = null;
  try {{ canvas.releasePointerCapture(ev.pointerId); }} catch (e) {{}}
  saveHistory();
}}
canvas.addEventListener("pointerup", endStroke);
canvas.addEventListener("pointercancel", endStroke);

document.addEventListener("keydown", ev => {{
  if (ev.target.tagName === "INPUT") return;
  const k = ev.key.toLowerCase();
  if (k === "z") {{ ev.preventDefault(); applyHistoryAt(historyIdx - 1); }}
  else if (k === "y") {{ ev.preventDefault(); applyHistoryAt(historyIdx + 1); }}
  else if (k === "r") {{
    const cb = document.getElementById("restore-mode");
    cb.checked = !cb.checked;
    restoreMode = cb.checked;
  }}
  else if (k === "[") {{ brushSize = Math.max(2, brushSize - 4); brushSlider.value = brushSize; brushVal.textContent = brushSize; }}
  else if (k === "]") {{ brushSize = Math.min(120, brushSize + 4); brushSlider.value = brushSize; brushVal.textContent = brushSize; }}
}});

// ---- Download -------------------------------------------------------------
document.getElementById("download").addEventListener("click", () => {{
  if (!currentPlow) return;
  canvas.toBlob(blob => {{
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // Match the filename the SKU folder expects (hero_transparent.png or _x4.png)
    const filename = currentPlow.kind === "x4"
      ? "hero_transparent_x4.png"
      : "hero_transparent.png";
    a.download = `${{currentPlow.sku}}__${{filename}}`;
    a.click();
    URL.revokeObjectURL(url);
  }}, "image/png");
}});
</script>
</body></html>
"""


def main() -> None:
    plows = load_plows()
    OUT.write_text(render(plows), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"  {len(plows)} plows")
    print(f"open: http://localhost:8765/snow-plows/_eraser.html")


if __name__ == "__main__":
    main()
