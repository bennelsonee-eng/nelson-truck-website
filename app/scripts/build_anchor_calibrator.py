"""Generate _anchor_calibrator.html — annotate truck and plow anchor points.

For each truck: click two points (bumper-left bottom corner, bumper-right
bottom corner) plus enter the real-world body width in inches. The midpoint
of those two clicks becomes the mount centerline; their distance maps the
real-world width to pixels.

For each plow: click one point (the mount/V-pivot) plus enter the plow's
real-world width in inches. The plow's pixel width is auto-detected from
its alpha bbox.

Saves to localStorage as you click. Export JSON when done. The composite
engine reads that JSON and places any plow on any truck automatically.

Usage:
    python app/scripts/build_anchor_calibrator.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLOW_DIR = ROOT / "backend" / "static" / "snow-plows"
TRUCK_DIR = ROOT / "backend" / "static" / "trucks" / "renders_3q_mirrored"
OUT = PLOW_DIR / "_anchor_calibrator.html"
MANIFEST = PLOW_DIR / "skus" / "_manifest.json"

# Default real-world body widths in inches (front bumper-to-bumper area).
# These are starting points users can override per asset.
TRUCK_DEFAULTS = {
    "mid-size": 75,
    "1500": 80,
    "2500": 80,
    "3500": 80,
    "4500": 96,
    "5500": 96,
}


def parse_plow_width_inches(title: str) -> int | None:
    """Extract real-world plow width in inches from a product title.

    e.g., "Meyer | 7' 6\" Lot Pro Snow Plow" -> 90
          "Western | 8'-6\" MVP3 V-Plow"     -> 102
    """
    if not title:
        return None
    # Match patterns like "7' 6"" or "8'-6"" or "10'" or "76"" etc.
    m = re.search(r"(\d+)\s*'\s*[-\s]?\s*(\d+)?", title)
    if m:
        feet = int(m.group(1))
        inches = int(m.group(2)) if m.group(2) else 0
        return feet * 12 + inches
    m2 = re.search(r"(\d+)\s*\"", title)
    if m2:
        return int(m2.group(1))
    return None


def load_plows() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    plows = []
    # SnowDogg TE II is not sold by Titan — exclude permanently.
    SKU_DENYLIST = {"SNOW-16020312-EQP"}
    for s in data.get("skus", []):
        sku = s.get("stockid_sanitized", "")
        if sku in SKU_DENYLIST:
            continue
        # Include Western (full clean catalog) and SnowDogg (cleaned via process_snowdogg_pictures.py)
        if not (sku.startswith("WEST-") or sku.startswith("SNOW-")):
            continue
        # Use upscaled if available, else regular transparent
        x4 = PLOW_DIR / "skus" / sku / "hero_transparent_x4.png"
        std = PLOW_DIR / "skus" / sku / "hero_transparent.png"
        if x4.exists():
            img_path = f"skus/{sku}/hero_transparent_x4.png"
        elif std.exists():
            img_path = f"skus/{sku}/hero_transparent.png"
        else:
            continue
        plows.append({
            "sku": sku,
            "title": s.get("title", ""),
            "img": img_path,
            "default_width_inches": parse_plow_width_inches(s.get("title", "")) or 102,
            "facing": "left",  # both Western and SnowDogg currently shot left-side-forward
        })
    plows.sort(key=lambda p: p["sku"])
    return plows


def load_trucks() -> list[dict]:
    trucks = []
    for cls, default_w in TRUCK_DEFAULTS.items():
        png = TRUCK_DIR / f"{cls}.png"
        if not png.exists():
            continue
        # Path relative to OUT (which is in snow-plows/) -> ../trucks/renders_3q_mirrored/
        rel = f"../trucks/renders_3q_mirrored/{cls}.png"
        trucks.append({
            "cls": cls,
            "img": rel,
            "default_width_inches": default_w,
            "facing": "left",  # mirrored set is canonical-left
        })
    return trucks


def render(trucks: list[dict], plows: list[dict]) -> str:
    trucks_json = json.dumps(trucks)
    plows_json = json.dumps(plows)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Anchor Calibrator — trucks + plows</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,system-ui,Segoe UI,sans-serif;
          background:#0f172a; color:#e2e8f0; padding:0; }}
  header {{ position:sticky; top:0; z-index:30;
            background:#020617; padding:10px 16px;
            display:flex; gap:14px; align-items:center; flex-wrap:wrap;
            border-bottom:1px solid #1e293b; }}
  header h1 {{ margin:0; font-size:15px; font-weight:600; }}
  .tabs {{ display:flex; gap:4px; }}
  .tabs button {{ background:#1e293b; color:#94a3b8; border:none;
                 padding:5px 14px; cursor:pointer; font-size:13px;
                 border-radius:5px; }}
  .tabs button.active {{ background:#3b82f6; color:#fff; }}
  .stats {{ display:flex; gap:8px; font-size:12px; flex-wrap:wrap; }}
  .stats span {{ background:rgba(255,255,255,0.06); padding:3px 9px; border-radius:999px; }}
  .stats span.ok {{ background:#047857; }}
  .controls {{ margin-left:auto; display:flex; gap:6px; }}
  .controls button {{ background:#374151; color:#fff; border:1px solid #4b5563;
                      padding:5px 11px; border-radius:5px; cursor:pointer; font-size:12px; }}
  .controls input[type=file] {{ display:none; }}
  .help {{ background:#0c1424; padding:8px 16px; font-size:12px;
          color:#94a3b8; border-bottom:1px solid #1e293b; }}
  .help b {{ color:#e2e8f0; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(700px,1fr));
           gap:16px; padding:16px; }}
  .card {{ background:#1e293b; border-radius:8px; padding:10px;
           border:2px solid transparent; }}
  .card.calibrated {{ border-color:#10b981; }}
  .card.partial {{ border-color:#f59e0b; }}
  .card-head {{ display:flex; justify-content:space-between; margin-bottom:6px;
                align-items:baseline; }}
  .card-head h3 {{ margin:0; font-size:13px;
                  font-family:ui-monospace,Consolas,monospace; color:#10b981; }}
  .card-head .status {{ font-size:11px; color:#94a3b8; }}
  .card-head .status.ok {{ color:#10b981; }}
  .card-head .status.partial {{ color:#f59e0b; }}
  .imgwrap {{ position:relative; background:repeating-conic-gradient(#334155 0 25%,#475569 0 50%) 50%/14px 14px;
             border-radius:4px; cursor:crosshair; user-select:none;
             overflow:visible; }}
  .imgwrap img.truck-img {{ display:block; width:100%; pointer-events:none; }}
  /* Plow tab: imgwrap contains a single bare <img> with no class.
     Give it the same display + sizing treatment so cards render correctly. */
  .imgwrap > img:not(.plow-overlay) {{ display:block; width:100%; }}
  .imgwrap img.plow-overlay {{ position:absolute; pointer-events:auto;
                              cursor:grab; touch-action:none;
                              transform-origin:center center; will-change:transform;
                              filter:drop-shadow(0 1px 2px rgba(0,0,0,0.4)); }}
  .imgwrap img.plow-overlay.dragging {{ cursor:grabbing;
                                        filter:drop-shadow(0 0 6px #3b82f6); }}
  .imgwrap .preview-status {{ position:absolute; bottom:6px; left:6px;
                              background:rgba(0,0,0,0.7); color:#fff;
                              font-size:10px; padding:2px 6px; border-radius:3px;
                              font-family:ui-monospace,Consolas,monospace;
                              pointer-events:none; max-width:90%; }}
  .marker {{ position:absolute; width:18px; height:18px;
             border:2px solid #fff; border-radius:50%;
             transform:translate(-50%, -50%); pointer-events:none;
             box-shadow:0 0 0 2px rgba(0,0,0,0.5); }}
  .marker.m0 {{ background:#3b82f6; }}
  .marker.m1 {{ background:#ec4899; }}
  .marker.m2 {{ background:#f59e0b; }}
  .marker .lbl {{ position:absolute; top:-22px; left:50%; transform:translateX(-50%);
                 font-size:10px; background:rgba(0,0,0,0.8); color:#fff;
                 padding:1px 6px; border-radius:3px; white-space:nowrap;
                 font-family:ui-monospace,Consolas,monospace; }}
  .controls-row {{ display:flex; gap:8px; align-items:center; margin-top:8px;
                  flex-wrap:wrap; }}
  .controls-row label {{ font-size:11px; color:#94a3b8; }}
  .controls-row input[type=number] {{ background:#0f172a; border:1px solid #334155;
                                       color:#e2e8f0; padding:4px 8px; border-radius:4px;
                                       font-size:12px; width:70px; }}
  .controls-row .meta {{ font-size:11px; color:#94a3b8; flex:1; }}
  .controls-row button {{ font-size:11px; background:#374151; color:#fff;
                         border:1px solid #4b5563; padding:4px 10px;
                         border-radius:4px; cursor:pointer; }}
  .controls-row button.danger {{ background:#7f1d1d; border-color:#991b1b; }}
  .saved-indicator {{ position:fixed; bottom:16px; right:16px;
                     background:#065f46; color:#fff; padding:8px 14px;
                     border-radius:6px; font-size:13px; opacity:0;
                     transition:opacity 0.3s; pointer-events:none; }}
  .saved-indicator.visible {{ opacity:1; }}
  .hidden {{ display:none !important; }}
</style></head><body>

<header>
  <h1>Anchor Calibrator</h1>
  <div class="tabs">
    <button id="tab-trucks" class="active">Trucks</button>
    <button id="tab-plows">Plows</button>
  </div>
  <label style="font-size:12px; color:#94a3b8;">Preview plow:
    <select id="preview-plow" style="background:#1e293b; color:#e2e8f0; border:1px solid #334155; padding:3px 8px; border-radius:4px; font-size:12px;"></select>
  </label>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <button id="export">Export JSON</button>
    <button id="import-btn">Import JSON</button>
    <input id="import-file" type="file" accept="application/json">
    <button id="reset" class="danger">Reset</button>
  </div>
</header>

<div class="help" id="help-trucks">
  <b>Trucks:</b> drag the plow overlay to position it on the truck.
  Use the <b>scale</b> slider to size it, the <b>rotation</b> slider to
  tilt it. The plow you're previewing comes from the dropdown above; once
  one truck looks right, others can use the same sliders independently.
</div>
<div class="help hidden" id="help-plows">
  <b>Plows:</b> click ONE point — the mount/pivot where this plow attaches to a
  truck (V-pivot back-center for V-plows; rear-center for straight blades).
  Width-in-inches is parsed from the product title; override if wrong. Click an
  existing marker to remove it.
</div>

<div class="grid hidden" id="grid-trucks"></div>
<div class="grid hidden" id="grid-plows"></div>

<div class="saved-indicator" id="saved">Saved</div>

<script>
const TRUCKS = {trucks_json};
const PLOWS  = {plows_json};
const KEY = "anchor-calibrator-v1";
let state = JSON.parse(localStorage.getItem(KEY) || "{{}}");
if (!state.trucks) state.trucks = {{}};
if (!state.plows)  state.plows  = {{}};

let activeTab = "trucks";

function save() {{
  localStorage.setItem(KEY, JSON.stringify(state));
  const ind = document.getElementById("saved");
  ind.classList.add("visible");
  clearTimeout(ind._t);
  ind._t = setTimeout(() => ind.classList.remove("visible"), 600);
  renderStats();
}}

// REFERENCE_INCHES used for relative-plow scaling: at plow_scale_pct = 100,
// a plow this wide displays at 100% of the truck's natural width.
const REFERENCE_INCHES = 102;

function migrateLegacyTruck(e) {{
  // If we have legacy L+R clicks + width_inches + scale_boost_pct + manual_offset,
  // compute mount_xr/yr + plow_scale_pct so user keeps their work.
  if (e.mount_xr !== undefined && e.plow_scale_pct !== undefined) return;
  const pts = e.points || [];
  if (pts.length === 2 && e.width_inches) {{
    const midX = (pts[0].xr + pts[1].xr) / 2 + (e.manual_offset_xr || 0);
    const midY = (pts[0].yr + pts[1].yr) / 2 + (e.manual_offset_yr || 0);
    e.mount_xr = midX;
    e.mount_yr = midY;
    // Effective plow display width as a fraction of truck width:
    // ppi = (Rxr - Lxr) / width_inches  (in fractions of truck width per inch)
    // plow_w_frac = REFERENCE_INCHES * ppi * scale_boost/100
    const dxr = Math.abs(pts[1].xr - pts[0].xr);
    const ppi_frac = dxr / e.width_inches;  // truck-width-fractions per inch
    const boost = (e.scale_boost_pct ?? 100) / 100;
    const plow_w_frac = REFERENCE_INCHES * ppi_frac * boost;
    e.plow_scale_pct = Math.round(plow_w_frac * 100);
  }}
}}

function getTruckEntry(cls) {{
  if (!state.trucks[cls]) {{
    state.trucks[cls] = {{
      mount_xr: 0.30,
      mount_yr: 0.78,
      plow_scale_pct: 50,
      plow_rotation_deg: 0,
      plow_perspective_deg: 0,
    }};
  }} else {{
    migrateLegacyTruck(state.trucks[cls]);
    const e = state.trucks[cls];
    if (e.mount_xr === undefined) e.mount_xr = 0.30;
    if (e.mount_yr === undefined) e.mount_yr = 0.78;
    if (e.plow_scale_pct === undefined) e.plow_scale_pct = 50;
    if (e.plow_rotation_deg === undefined) e.plow_rotation_deg = 0;
    if (e.plow_perspective_deg === undefined) e.plow_perspective_deg = 0;
  }}
  return state.trucks[cls];
}}
function getPlowEntry(sku) {{
  if (!state.plows[sku]) {{
    const p = PLOWS.find(x => x.sku === sku);
    state.plows[sku] = {{
      points: [],
      width_inches: p?.default_width_inches ?? 102,
      rotation_offset_deg: 0,
      perspective_offset_deg: 0,
      scale_offset_pct: 0,
    }};
  }} else {{
    const e = state.plows[sku];
    if (e.rotation_offset_deg === undefined) e.rotation_offset_deg = 0;
    if (e.perspective_offset_deg === undefined) e.perspective_offset_deg = 0;
    if (e.scale_offset_pct === undefined) e.scale_offset_pct = 0;
  }}
  return state.plows[sku];
}}

function isCalibrated(kind, id) {{
  if (kind === "trucks") {{
    const e = state.trucks[id];
    return e && e.mount_xr !== undefined && e.plow_scale_pct !== undefined;
  }}
  return (state.plows[id]?.points?.length ?? 0) === 1;
}}
function isPartial(kind, id) {{
  if (kind === "trucks") return false;  // trucks default to a starting position; never "partial"
  const n = state.plows[id]?.points?.length;
  return (n ?? 0) > 0 && !isCalibrated(kind, id);
}}

function renderStats() {{
  let tcal = 0, tpart = 0;
  TRUCKS.forEach(t => {{
    if (isCalibrated("trucks", t.cls)) tcal++;
    else if (isPartial("trucks", t.cls)) tpart++;
  }});
  let pcal = 0, ppart = 0;
  PLOWS.forEach(p => {{
    if (isCalibrated("plows", p.sku)) pcal++;
    else if (isPartial("plows", p.sku)) ppart++;
  }});
  document.getElementById("stats").innerHTML =
    `<span class="${{tcal === TRUCKS.length ? 'ok' : ''}}">Trucks ${{tcal}}/${{TRUCKS.length}}</span>` +
    (tpart ? `<span>Trucks partial ${{tpart}}</span>` : '') +
    `<span class="${{pcal === PLOWS.length ? 'ok' : ''}}">Plows ${{pcal}}/${{PLOWS.length}}</span>` +
    (ppart ? `<span>Plows partial ${{ppart}}</span>` : '');
}}

function applyCardClass(kind, id) {{
  const card = document.querySelector(`[data-${{kind === 'trucks' ? 'cls' : 'sku'}}="${{id}}"]`);
  if (!card) return;
  card.classList.remove("calibrated", "partial");
  if (isCalibrated(kind, id)) card.classList.add("calibrated");
  else if (isPartial(kind, id)) card.classList.add("partial");
  const status = card.querySelector(".status");
  if (isCalibrated(kind, id)) {{ status.className = "status ok"; status.textContent = "✓ calibrated"; }}
  else if (isPartial(kind, id)) {{ status.className = "status partial"; status.textContent = "partial"; }}
  else {{ status.className = "status"; status.textContent = "pending"; }}
  renderMarkers(kind, id);
  if (kind === "trucks") drawTruckPreview(id);
}}

// --- Live preview canvas ----------------------------------------------------
const PLOW_IMG_CACHE = {{}};
function loadPlowImg(sku) {{
  if (PLOW_IMG_CACHE[sku]) return Promise.resolve(PLOW_IMG_CACHE[sku]);
  const p = PLOWS.find(x => x.sku === sku);
  if (!p) return Promise.resolve(null);
  return new Promise(res => {{
    const im = new Image();
    im.onload = () => {{ PLOW_IMG_CACHE[sku] = im; res(im); }};
    im.onerror = e => {{ console.warn("plow img load failed", sku, e); res(null); }};
    im.src = p.img;
  }});
}}

function getAlphaBbox(img) {{
  // Compute non-zero alpha bbox; falls back to full image dimensions if
  // canvas readback is blocked (e.g., CORS-tainted on file:// origin).
  try {{
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    let minX = c.width, minY = c.height, maxX = -1, maxY = -1;
    // Sample every 2nd pixel for speed
    for (let y = 0; y < c.height; y += 2) {{
      for (let x = 0; x < c.width; x += 2) {{
        const a = d[(y * c.width + x) * 4 + 3];
        if (a > 8) {{
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        }}
      }}
    }}
    if (maxX < 0) throw new Error("no opaque pixels");
    return {{x:minX, y:minY, w:maxX-minX+1, h:maxY-minY+1}};
  }} catch (err) {{
    console.warn("getAlphaBbox falling back to full image:", err.message);
    return {{x:0, y:0, w:img.naturalWidth, h:img.naturalHeight}};
  }}
}}

const ALPHA_BBOX_CACHE = {{}};
function getCachedBbox(sku, img) {{
  if (!ALPHA_BBOX_CACHE[sku]) ALPHA_BBOX_CACHE[sku] = getAlphaBbox(img);
  return ALPHA_BBOX_CACHE[sku];
}}

function setStatusMsg(card, msg) {{
  const el = card.querySelector(".preview-status");
  if (el) el.textContent = msg || "";
}}

async function drawTruckPreview(cls) {{
  const card = document.querySelector(`[data-cls="${{cls}}"]`);
  if (!card) return;
  const truckImg = card.querySelector("img.truck-img");
  const overlay = card.querySelector("img.plow-overlay");
  if (!truckImg || !overlay) return;

  const t = getTruckEntry(cls);
  const sku = document.getElementById("preview-plow").value;
  const plow = state.plows[sku];
  const plowMeta = PLOWS.find(p => p.sku === sku) || {{}};
  if (!plow || (plow.points || []).length !== 1) {{
    overlay.style.display = "none";
    setStatusMsg(card, `preview plow "${{sku}}": click mount point on Plows tab first`);
    return;
  }}

  // Set the overlay image src if changed (browser caches across cards)
  if (overlay.dataset.sku !== sku) {{
    overlay.dataset.sku = sku;
    overlay.src = plowMeta.img;
  }}

  // Wait for the overlay image to load if it isn't already
  if (!overlay.complete || !overlay.naturalWidth) {{
    overlay.addEventListener("load", () => drawTruckPreview(cls), {{once: true}});
    setStatusMsg(card, "loading plow image...");
    return;
  }}

  // Need the truck displayed dimensions to position the overlay correctly.
  // Use clientWidth/clientHeight (CSS-display size) for positioning since
  // the overlay sits in the same flow.
  const truckRect = truckImg.getBoundingClientRect();
  const wrapRect  = card.querySelector(".imgwrap").getBoundingClientRect();
  const displayedTw = truckRect.width;
  const displayedTh = truckRect.height;
  if (displayedTw < 1 || displayedTh < 1) {{
    setStatusMsg(card, "truck image still sizing");
    setTimeout(() => drawTruckPreview(cls), 50);
    return;
  }}

  // Mount point in displayed truck coords (purely from drag-positioned mount)
  const mountX = (t.mount_xr ?? 0.30) * displayedTw;
  const mountY = (t.mount_yr ?? 0.78) * displayedTh;

  // Direction handling
  const truckFacing = "left";
  const plowFacing = plowMeta.facing || "left";
  const flip = truckFacing !== plowFacing;
  let mountXr = plow.points[0].xr;
  const mountYr = plow.points[0].yr;
  if (flip) mountXr = 1.0 - mountXr;

  // Plow displayed width in DISPLAY pixels.
  // plow_scale_pct is "what % of truck width a 102in plow displays at".
  // For other plow sizes, scale relative to 102in.
  // Per-plow scale offset is added on top of the truck's value.
  const effectiveScalePct = (t.plow_scale_pct ?? 50) + (plow.scale_offset_pct ?? 0);
  const plowScalePct = effectiveScalePct / 100;
  const plowInches = plow.width_inches || REFERENCE_INCHES;
  const plowDisplayW = displayedTw * plowScalePct * (plowInches / REFERENCE_INCHES);
  // Plow's natural aspect — use full image dims (alpha-bbox refinement is
  // done server-side in the engine; the preview doesn't need it because the
  // user can see the actual silhouette via the transparent PNG)
  const Pw = overlay.naturalWidth, Ph = overlay.naturalHeight;
  const aspect = Ph / Pw;
  const plowDisplayH = plowDisplayW * aspect;

  // Where to place the overlay's TOP-LEFT corner so its mount anchor
  // (mountXr, mountYr inside the plow image) lands on (mountX, mountY)
  const anchorOffsetX = mountXr * plowDisplayW;
  const anchorOffsetY = mountYr * plowDisplayH;
  const leftPx = mountX - anchorOffsetX;
  const topPx  = mountY - anchorOffsetY;

  // Style the overlay — relative to .imgwrap (which contains both truck-img and overlay)
  // Since .imgwrap is position:relative, overlay's absolute coords are relative to it,
  // and truck-img sits at (0,0) of imgwrap.
  overlay.style.display = "block";
  overlay.style.left = leftPx + "px";
  overlay.style.top = topPx + "px";
  overlay.style.width = plowDisplayW + "px";
  overlay.style.height = plowDisplayH + "px";

  // Apply mirror + flat rotation + perspective. All pivot around the mount anchor.
  // Per-plow offsets are added on top of truck values.
  const rotDeg = (t.plow_rotation_deg || 0) + (plow.rotation_offset_deg || 0);
  const perspDeg = (t.plow_perspective_deg || 0) + (plow.perspective_offset_deg || 0);
  overlay.style.transformOrigin = `${{anchorOffsetX}}px ${{anchorOffsetY}}px`;
  // CSS perspective rotateY simulates the 3D tilt-into-page effect.
  // 900px perspective distance gives a moderate, photographically natural tilt.
  let xform = "";
  if (perspDeg !== 0) xform += `perspective(900px) rotateY(${{perspDeg}}deg) `;
  xform += `rotate(${{rotDeg}}deg)`;
  if (flip) xform += ` scaleX(-1)`;
  overlay.style.transform = xform;

  // Status: show truck + plow offset values explicitly so user knows what's combining
  const tScale = t.plow_scale_pct ?? 50;
  const tRot = t.plow_rotation_deg || 0;
  const tPersp = t.plow_perspective_deg || 0;
  const pScale = plow.scale_offset_pct || 0;
  const pRot = plow.rotation_offset_deg || 0;
  const pPersp = plow.perspective_offset_deg || 0;
  setStatusMsg(card,
    `${{sku.replace("WEST-", "").replace("-EQP", "")}} ` +
    `${{Math.round(plowDisplayW)}}x${{Math.round(plowDisplayH)}}px ` +
    `scale ${{tScale}}${{pScale ? (pScale > 0 ? '+' + pScale : pScale) : ''}}% ` +
    `rot ${{tRot}}${{pRot ? (pRot > 0 ? '+' + pRot : pRot) : ''}}° ` +
    `persp ${{tPersp}}${{pPersp ? (pPersp > 0 ? '+' + pPersp : pPersp) : ''}}°`);
}}

// --- Drag plow overlay to adjust per-truck manual offset --------------------
function attachPlowDrag(card, cls) {{
  const overlay = card.querySelector("img.plow-overlay");
  const wrap = card.querySelector(".imgwrap");
  const truckImg = card.querySelector("img.truck-img");
  if (!overlay || !wrap || !truckImg) return;

  let dragging = false;
  let startClientX = 0, startClientY = 0;
  let startMountXr = 0, startMountYr = 0;

  overlay.addEventListener("pointerdown", ev => {{
    if (overlay.style.display === "none") return;
    ev.stopPropagation();
    ev.preventDefault();
    dragging = true;
    overlay.classList.add("dragging");
    overlay.setPointerCapture(ev.pointerId);
    startClientX = ev.clientX;
    startClientY = ev.clientY;
    const e = getTruckEntry(cls);
    startMountXr = e.mount_xr ?? 0.30;
    startMountYr = e.mount_yr ?? 0.78;
  }});

  overlay.addEventListener("pointermove", ev => {{
    if (!dragging) return;
    ev.stopPropagation();
    const truckRect = truckImg.getBoundingClientRect();
    if (truckRect.width < 1 || truckRect.height < 1) return;
    const dxr = (ev.clientX - startClientX) / truckRect.width;
    const dyr = (ev.clientY - startClientY) / truckRect.height;
    const e = getTruckEntry(cls);
    e.mount_xr = startMountXr + dxr;
    e.mount_yr = startMountYr + dyr;
    drawTruckPreview(cls);
  }});

  function endDrag(ev) {{
    if (!dragging) return;
    ev.stopPropagation();
    dragging = false;
    overlay.classList.remove("dragging");
    try {{ overlay.releasePointerCapture(ev.pointerId); }} catch (e) {{}}
    save();
  }}
  overlay.addEventListener("pointerup", endDrag);
  overlay.addEventListener("pointercancel", endDrag);
  // The synthesized click event after pointerup also bubbles — stop it so it
  // doesn't trigger the imgwrap anchor-click handler.
  overlay.addEventListener("click", ev => ev.stopPropagation());
}}

function refreshAllTruckPreviews() {{
  TRUCKS.forEach(t => drawTruckPreview(t.cls));
}}

function renderMarkers(kind, id) {{
  if (kind === "trucks") return;  // trucks now use drag + sliders only
  const card = document.querySelector(`[data-${{kind === 'trucks' ? 'cls' : 'sku'}}="${{id}}"]`);
  if (!card) return;
  const wrap = card.querySelector(".imgwrap");
  wrap.querySelectorAll(".marker").forEach(m => m.remove());
  const entry = state.plows[id];
  const points = entry?.points || [];
  const labels = ["mount"];
  points.forEach((pt, i) => {{
    const m = document.createElement("div");
    m.className = `marker m${{i}}`;
    m.style.left = (pt.xr * 100) + "%";
    m.style.top  = (pt.yr * 100) + "%";
    m.innerHTML = `<span class="lbl">${{labels[i] || ('p'+i)}}</span>`;
    wrap.appendChild(m);
  }});
}}

function handleClick(kind, id, ev) {{
  const wrap = ev.currentTarget;
  const rect = wrap.getBoundingClientRect();
  const xr = (ev.clientX - rect.left) / rect.width;
  const yr = (ev.clientY - rect.top)  / rect.height;
  const max = kind === "trucks" ? 2 : 1;
  const entry = kind === "trucks" ? getTruckEntry(id) : getPlowEntry(id);
  // Tolerance: if click near an existing marker, remove it
  for (let i = 0; i < entry.points.length; i++) {{
    const dx = entry.points[i].xr - xr;
    const dy = entry.points[i].yr - yr;
    const dpx = Math.hypot(dx * rect.width, dy * rect.height);
    if (dpx < 14) {{
      entry.points.splice(i, 1);
      save(); applyCardClass(kind, id);
      return;
    }}
  }}
  if (entry.points.length >= max) {{
    // Replace oldest
    entry.points.shift();
  }}
  entry.points.push({{xr, yr}});
  save(); applyCardClass(kind, id);
}}

function buildTruckCards() {{
  const grid = document.getElementById("grid-trucks");
  grid.innerHTML = "";
  TRUCKS.forEach(t => {{
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.cls = t.cls;
    card.innerHTML = `
      <div class="card-head">
        <h3>${{t.cls}}</h3>
        <span class="status">pending</span>
      </div>
      <div class="imgwrap">
        <img src="${{t.img}}" alt="${{t.cls}}" class="truck-img">
        <img class="plow-overlay" alt="" style="display:none">
        <span class="preview-status"></span>
      </div>
      <div class="controls-row">
        <label>scale:</label>
        <input type="range" min="10" max="200" step="1" data-scale style="flex:1; min-width:140px;">
        <input type="number" min="10" max="200" step="1" data-scale-num style="width:60px;">
        <span class="meta">% of truck width (for a 102" plow)</span>
      </div>
      <div class="controls-row">
        <label>rotation:</label>
        <input type="range" min="-30" max="30" step="1" data-rot style="flex:1; min-width:140px;">
        <input type="number" min="-30" max="30" step="1" data-rot-num style="width:60px;">
        <span class="meta">deg (flat 2D — positive = CCW)</span>
      </div>
      <div class="controls-row">
        <label>perspective:</label>
        <input type="range" min="-45" max="45" step="1" data-persp style="flex:1; min-width:140px;">
        <input type="number" min="-45" max="45" step="1" data-persp-num style="width:60px;">
        <span class="meta">deg (3D tilt-into-page; matches truck angle)</span>
        <button data-reset-pos>Reset position</button>
      </div>
    `;
    grid.appendChild(card);
    const e = getTruckEntry(t.cls);
    const rotR = card.querySelector("[data-rot]");
    const rotN = card.querySelector("[data-rot-num]");
    rotR.value = e.plow_rotation_deg ?? 0;
    rotN.value = e.plow_rotation_deg ?? 0;
    rotR.addEventListener("input", ev => {{
      const v = parseInt(ev.target.value, 10) || 0;
      e.plow_rotation_deg = v; rotN.value = v; save();
      drawTruckPreview(t.cls);
    }});
    rotN.addEventListener("change", ev => {{
      const v = parseInt(ev.target.value, 10) || 0;
      e.plow_rotation_deg = v; rotR.value = v; save();
      drawTruckPreview(t.cls);
    }});
    const scR = card.querySelector("[data-scale]");
    const scN = card.querySelector("[data-scale-num]");
    scR.value = e.plow_scale_pct ?? 50;
    scN.value = e.plow_scale_pct ?? 50;
    scR.addEventListener("input", ev => {{
      const v = parseInt(ev.target.value, 10) || 50;
      e.plow_scale_pct = v; scN.value = v; save();
      drawTruckPreview(t.cls);
    }});
    scN.addEventListener("change", ev => {{
      const v = parseInt(ev.target.value, 10) || 50;
      e.plow_scale_pct = v; scR.value = v; save();
      drawTruckPreview(t.cls);
    }});
    const pR = card.querySelector("[data-persp]");
    const pN = card.querySelector("[data-persp-num]");
    pR.value = e.plow_perspective_deg ?? 0;
    pN.value = e.plow_perspective_deg ?? 0;
    pR.addEventListener("input", ev => {{
      const v = parseInt(ev.target.value, 10) || 0;
      e.plow_perspective_deg = v; pN.value = v; save();
      drawTruckPreview(t.cls);
    }});
    pN.addEventListener("change", ev => {{
      const v = parseInt(ev.target.value, 10) || 0;
      e.plow_perspective_deg = v; pR.value = v; save();
      drawTruckPreview(t.cls);
    }});
    card.querySelector("[data-reset-pos]").addEventListener("click", () => {{
      e.mount_xr = 0.30; e.mount_yr = 0.78; save();
      drawTruckPreview(t.cls);
    }});
    // Re-draw preview once the truck image has loaded (need natural dimensions)
    const truckImgEl = card.querySelector("img.truck-img");
    truckImgEl.addEventListener("load", () => drawTruckPreview(t.cls));
    if (truckImgEl.complete) drawTruckPreview(t.cls);
    attachPlowDrag(card, t.cls);
    applyCardClass("trucks", t.cls);
  }});
}}

function buildPlowCards() {{
  const grid = document.getElementById("grid-plows");
  grid.innerHTML = "";
  PLOWS.forEach(p => {{
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.sku = p.sku;
    card.innerHTML = `
      <div class="card-head">
        <h3>${{p.sku}}</h3>
        <span class="status">pending</span>
      </div>
      <div class="imgwrap"><img src="${{p.img}}" alt="${{p.sku}}"></div>
      <div class="controls-row">
        <label>width (inches):</label>
        <input type="number" min="48" max="144" step="1" data-w>
        <span class="meta">${{p.title}}</span>
        <button data-clear>Clear</button>
      </div>
      <div class="controls-row">
        <label>rotation offset:</label>
        <input type="range" min="-30" max="30" step="1" data-rot-off style="flex:1; min-width:120px;">
        <input type="number" min="-30" max="30" step="1" data-rot-off-num style="width:60px;">
        <span class="meta">deg (added to truck)</span>
      </div>
      <div class="controls-row">
        <label>perspective offset:</label>
        <input type="range" min="-45" max="45" step="1" data-persp-off style="flex:1; min-width:120px;">
        <input type="number" min="-45" max="45" step="1" data-persp-off-num style="width:60px;">
        <span class="meta">deg (added to truck)</span>
      </div>
      <div class="controls-row">
        <label>scale offset:</label>
        <input type="range" min="-50" max="50" step="1" data-scale-off style="flex:1; min-width:120px;">
        <input type="number" min="-50" max="50" step="1" data-scale-off-num style="width:60px;">
        <span class="meta">% (added to truck)</span>
      </div>
    `;
    grid.appendChild(card);
    const e = getPlowEntry(p.sku);
    const winput = card.querySelector("[data-w]");
    winput.value = e.width_inches;
    winput.addEventListener("change", ev => {{
      e.width_inches = parseInt(ev.target.value, 10) || e.width_inches;
      save();
    }});
    card.querySelector(".imgwrap").addEventListener("click", ev => {{
      handleClick("plows", p.sku, ev);
      // If this is the currently-previewed plow, refresh truck previews so the
      // new mount point shows up immediately
      if (document.getElementById("preview-plow").value === p.sku) {{
        refreshAllTruckPreviews();
      }}
    }});
    card.querySelector("[data-clear]").addEventListener("click", () => {{
      e.points = []; save(); applyCardClass("plows", p.sku);
      if (document.getElementById("preview-plow").value === p.sku) {{
        refreshAllTruckPreviews();
      }}
    }});

    // Offset sliders — each refreshes truck previews live
    function bindOffset(rangeAttr, numAttr, field, defaultVal) {{
      const r = card.querySelector(`[data-${{rangeAttr}}]`);
      const n = card.querySelector(`[data-${{numAttr}}]`);
      r.value = e[field] ?? defaultVal;
      n.value = e[field] ?? defaultVal;
      r.addEventListener("input", ev => {{
        const v = parseInt(ev.target.value, 10) || 0;
        e[field] = v; n.value = v; save();
        if (document.getElementById("preview-plow").value === p.sku) refreshAllTruckPreviews();
      }});
      n.addEventListener("change", ev => {{
        const v = parseInt(ev.target.value, 10) || 0;
        e[field] = v; r.value = v; save();
        if (document.getElementById("preview-plow").value === p.sku) refreshAllTruckPreviews();
      }});
    }}
    bindOffset("rot-off", "rot-off-num", "rotation_offset_deg", 0);
    bindOffset("persp-off", "persp-off-num", "perspective_offset_deg", 0);
    bindOffset("scale-off", "scale-off-num", "scale_offset_pct", 0);

    applyCardClass("plows", p.sku);
  }});
}}

function showTab(tab) {{
  activeTab = tab;
  document.getElementById("tab-trucks").classList.toggle("active", tab === "trucks");
  document.getElementById("tab-plows").classList.toggle("active", tab === "plows");
  document.getElementById("help-trucks").classList.toggle("hidden", tab !== "trucks");
  document.getElementById("help-plows").classList.toggle("hidden", tab !== "plows");
  document.getElementById("grid-trucks").classList.toggle("hidden", tab !== "trucks");
  document.getElementById("grid-plows").classList.toggle("hidden", tab !== "plows");
}}

document.getElementById("tab-trucks").addEventListener("click", () => showTab("trucks"));
document.getElementById("tab-plows").addEventListener("click", () => showTab("plows"));

// Populate the preview-plow selector
(function populatePreviewSelector() {{
  const sel = document.getElementById("preview-plow");
  PLOWS.forEach(p => {{
    const opt = document.createElement("option");
    opt.value = p.sku;
    opt.textContent = p.sku + (p.title ? " — " + p.title.slice(0, 40) : "");
    sel.appendChild(opt);
  }});
  // Default to MVP3 8'6" if available
  const def = "WEST-MVP3MS86-EQP";
  if (PLOWS.find(p => p.sku === def)) sel.value = def;
  sel.addEventListener("change", () => refreshAllTruckPreviews());
}})();
document.getElementById("export").addEventListener("click", () => {{
  const out = {{
    exported_at: new Date().toISOString(),
    trucks: state.trucks,
    plows:  state.plows,
  }};
  const blob = new Blob([JSON.stringify(out, null, 2)], {{type:"application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "plow_truck_anchors.json"; a.click();
  URL.revokeObjectURL(url);
}});
document.getElementById("import-btn").addEventListener("click", () => {{
  document.getElementById("import-file").click();
}});
document.getElementById("import-file").addEventListener("change", async ev => {{
  const f = ev.target.files[0];
  if (!f) return;
  const data = JSON.parse(await f.text());
  if (data.trucks) state.trucks = data.trucks;
  if (data.plows)  state.plows  = data.plows;
  save(); buildTruckCards(); buildPlowCards();
}});
document.getElementById("reset").addEventListener("click", () => {{
  if (!confirm("Clear all calibration data?")) return;
  state = {{trucks:{{}}, plows:{{}}}};
  save(); buildTruckCards(); buildPlowCards();
}});

buildTruckCards(); buildPlowCards();
showTab("trucks");
renderStats();
</script>
</body></html>
"""


def main() -> None:
    trucks = load_trucks()
    plows = load_plows()
    OUT.write_text(render(trucks, plows), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"  {len(trucks)} trucks (defaults: {sorted(t['cls'] for t in trucks)})")
    print(f"  {len(plows)} plows")
    print(f"\nOpen: file:///{OUT.as_posix()}")


if __name__ == "__main__":
    main()
