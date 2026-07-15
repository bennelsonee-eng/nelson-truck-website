"""Detect each plow's photographed angle and pre-fill perspective offsets.

Approach: a plow shot at 0deg (head-on) has a symmetric alpha distribution
along X — the median X of opaque pixels equals the geometric center of
the alpha bbox. As the plow rotates, the side closer to the camera grows
and the median X shifts toward it. The amount of shift, normalized to
half the plow width, is approximately sin(angle).

For V-plows this is robust because both wings are symmetric in 3D. For
straight blades it's noisier but still indicative.

Per-plow perspective offset is then computed relative to MVP3 8'6" (the
reference plow against which trucks were calibrated):
    offset = (mvp3_angle - this_plow_angle)

Outputs:
  - app/backend/static/snow-plows/_angle_detection.html  (review page)
  - C:/Users/Ben/Downloads/plow_truck_anchors_with_offsets.json
    (the latest anchors JSON with rotation/perspective_offset_deg pre-filled)
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PLOW_DIR = ROOT / "backend" / "static" / "snow-plows"
MANIFEST = PLOW_DIR / "skus" / "_manifest.json"
REVIEW = PLOW_DIR / "_angle_detection.html"
DOWNLOADS = Path.home() / "Downloads"

REFERENCE_SKU = "WEST-MVP3MS86-EQP"  # truck calibration baseline
DENY = {"SNOW-16020312-EQP"}  # not sold

# Manual angle overrides — used when alpha-mass asymmetry mis-estimates
# (typically caused by mount frame/light tower mass on the top of the image
# that doesn't represent the blade's actual rotation). User-provided values.
MANUAL_OVERRIDES = {
    "SNOW-16020724-EQP":  -9.5,  # VXF II — was -23.8 detected, my text overlay biased it
    "SNOW-16020412-EQP":  -4.0,  # MD II — was +11.2 detected
    "SNOW-16020820-EQP": -27.0,  # CM II — was -12.5 detected
}


def detect_angle(img_path: Path) -> dict:
    """Return {angle_deg, asymmetry, bbox, n_opaque} for the plow image."""
    img = Image.open(img_path).convert("RGBA")
    alpha = np.array(img.split()[-1])
    # Threshold: count anything noticeably opaque
    opaque = alpha > 32
    ys, xs = np.where(opaque)
    if len(xs) == 0:
        return {"angle_deg": 0.0, "asymmetry": 0.0, "bbox": (0, 0, 0, 0), "n_opaque": 0}

    left = int(xs.min())
    right = int(xs.max())
    top = int(ys.min())
    bottom = int(ys.max())
    width = right - left + 1

    median_x = float(np.median(xs))
    center_x = (left + right) / 2.0

    # Asymmetry in [-1, +1]: positive = visible mass shifted RIGHT (left side
    # of plow is closer to camera, since rotated such that its left wing comes
    # forward in the photo); negative = mass shifted LEFT (right side closer).
    asym = (median_x - center_x) / max(1.0, width / 2.0)
    asym_clamped = max(-0.95, min(0.95, asym))

    # asymmetry ≈ sin(angle) for typical V-plow projections; invert to angle.
    # An empirical scaling factor that maps asymmetry to a more realistic angle.
    # Pure sin assumption underestimates because median != geometric center
    # of-mass. Bumping by ~1.5x gives more accurate angle estimates.
    angle_rad = math.asin(asym_clamped) * 1.5
    angle_rad = max(-math.pi / 4, min(math.pi / 4, angle_rad))
    angle_deg = math.degrees(angle_rad)

    return {
        "angle_deg": angle_deg,
        "asymmetry": asym,
        "bbox": (left, top, right, bottom),
        "n_opaque": int(len(xs)),
    }


def load_plows() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = []
    for s in data.get("skus", []):
        sku = s.get("stockid_sanitized", "")
        if sku in DENY:
            continue
        if not (sku.startswith("WEST-") or sku.startswith("SNOW-")):
            continue
        x4 = PLOW_DIR / "skus" / sku / "hero_transparent_x4.png"
        std = PLOW_DIR / "skus" / sku / "hero_transparent.png"
        if x4.exists():
            img_path = x4
            rel = f"skus/{sku}/hero_transparent_x4.png"
        elif std.exists():
            img_path = std
            rel = f"skus/{sku}/hero_transparent.png"
        else:
            continue
        out.append({
            "sku": sku,
            "title": s.get("title", ""),
            "img_path": img_path,
            "img_rel": rel,
        })
    out.sort(key=lambda p: (
        0 if p["sku"].startswith("SNOW-") else 1,
        p["sku"],
    ))
    return out


def find_latest_anchors_json() -> Path | None:
    candidates = sorted(
        DOWNLOADS.glob("plow_truck_anchors*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def write_review(rows: list[dict], reference_angle: float) -> None:
    rows_json = json.dumps(rows)
    REVIEW.write_text(f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Plow Angle Detection</title>
<style>
  body {{ margin:0; font-family:-apple-system,system-ui,sans-serif;
          background:#0f172a; color:#e2e8f0; padding:14px; }}
  h1 {{ margin:0 0 4px 0; font-size:18px; }}
  p  {{ margin:0 0 14px 0; color:#94a3b8; font-size:13px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(420px,1fr));
           gap:14px; }}
  .card {{ background:#1e293b; padding:8px; border-radius:6px; }}
  .card h3 {{ margin:0 0 4px 0; font-size:13px;
             font-family:ui-monospace,Consolas,monospace; color:#10b981; }}
  .card.reference h3::before {{ content:"★ "; color:#fde047; }}
  .vals {{ display:flex; gap:10px; font-size:11px; flex-wrap:wrap;
          color:#94a3b8; margin:4px 0; }}
  .vals b {{ color:#e2e8f0; }}
  .vals .pos {{ color:#10b981; }}
  .vals .neg {{ color:#ef4444; }}
  .imgwrap {{ background:repeating-conic-gradient(#334155 0 25%,#475569 0 50%) 50%/14px 14px;
              border-radius:4px; padding:6px;
              display:flex; align-items:center; justify-content:center;
              aspect-ratio:16/10; }}
  .imgwrap img {{ max-width:100%; max-height:100%; object-fit:contain; }}
</style></head>
<body>
<h1>Plow Angle Detection</h1>
<p>Reference plow: <code>{REFERENCE_SKU}</code> at detected angle <b>{reference_angle:.1f}°</b>.
Per-plow perspective offset = (reference angle − this plow's angle), so any plow renders
"as if" it were the reference plow when truck calibration is applied.</p>
<div class="grid" id="grid"></div>
<script>
const ROWS = {rows_json};
const g = document.getElementById("grid");
ROWS.forEach(r => {{
  const div = document.createElement("div");
  div.className = "card" + (r.reference ? " reference" : "");
  const offsetSign = r.suggested_offset > 0 ? "+" : "";
  const offsetCls = r.suggested_offset > 0 ? "pos" : (r.suggested_offset < 0 ? "neg" : "");
  div.innerHTML = `
    <h3>${{r.sku}}</h3>
    <div class="imgwrap"><img src="${{r.img_rel}}"></div>
    <div class="vals">
      <span>angle: <b>${{r.angle_deg.toFixed(1)}}°</b></span>
      <span>asym: <b>${{r.asymmetry.toFixed(3)}}</b></span>
      <span>offset: <b class="${{offsetCls}}">${{offsetSign}}${{r.suggested_offset.toFixed(1)}}°</b></span>
    </div>
  `;
  g.appendChild(div);
}});
</script></body></html>""", encoding="utf-8")


def main() -> int:
    plows = load_plows()
    print(f"Detecting angle on {len(plows)} plows…")

    results = []
    reference_angle = None
    for p in plows:
        det = detect_angle(p["img_path"])
        p.update(det)
        # Apply manual override if set
        if p["sku"] in MANUAL_OVERRIDES:
            override = MANUAL_OVERRIDES[p["sku"]]
            print(f"  {p['sku']:24s} angle={det['angle_deg']:+6.2f}° -> OVERRIDE {override:+6.1f}°")
            p["angle_deg"] = override
            p["overridden"] = True
        else:
            print(f"  {p['sku']:24s} angle={det['angle_deg']:+6.2f}°  asym={det['asymmetry']:+.3f}")
            p["overridden"] = False
        results.append(p)
        if p["sku"] == REFERENCE_SKU:
            reference_angle = p["angle_deg"]

    if reference_angle is None:
        print(f"! reference plow {REFERENCE_SKU} not found — using 0 as reference")
        reference_angle = 0.0

    rows = []
    for p in results:
        suggested_offset = reference_angle - p["angle_deg"]
        rows.append({
            "sku": p["sku"],
            "title": p["title"],
            "img_rel": p["img_rel"],
            "angle_deg": p["angle_deg"],
            "asymmetry": p["asymmetry"],
            "suggested_offset": suggested_offset,
            "reference": p["sku"] == REFERENCE_SKU,
            "overridden": p.get("overridden", False),
        })

    write_review(rows, reference_angle)
    print(f"\nReview: http://localhost:8765/snow-plows/_angle_detection.html")

    # Inject offsets into the latest anchors JSON
    src_json = find_latest_anchors_json()
    if not src_json:
        print("\n(no anchors JSON in Downloads to inject into)")
        return 0
    print(f"\nInjecting offsets into {src_json.name}...")
    data = json.loads(src_json.read_text(encoding="utf-8"))
    for row in rows:
        sku = row["sku"]
        if sku not in data.get("plows", {}):
            data.setdefault("plows", {})[sku] = {
                "points": [],
                "width_inches": 102,
            }
        data["plows"][sku]["perspective_offset_deg"] = round(row["suggested_offset"], 1)
        # Don't touch rotation_offset/scale_offset — leave at user's existing value or 0
        if "rotation_offset_deg" not in data["plows"][sku]:
            data["plows"][sku]["rotation_offset_deg"] = 0
        if "scale_offset_pct" not in data["plows"][sku]:
            data["plows"][sku]["scale_offset_pct"] = 0
    out_json = DOWNLOADS / "plow_truck_anchors_with_offsets.json"
    out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {out_json}")
    print("Import this JSON in the calibrator to apply the auto-detected offsets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
