"""Auto-composite engine — places any plow on any truck using anchors + real-world widths.

Reads `plow_truck_anchors.json` (exported from the calibrator) and produces
correct composites for every (truck × plow) combination requested, with
zero per-pair tuning.

Math:
    mount_x = avg(truck.bumper_left.x, truck.bumper_right.x) [in pixels]
    mount_y = avg(truck.bumper_left.y, truck.bumper_right.y)
    truck_pixel_width = |R.x - L.x| [pixels of mount-frame width]
    ppi = truck_pixel_width / truck.width_inches      [pixels per inch]

    plow_display_w_px = plow.width_inches * ppi
    plow_scale = plow_display_w_px / plow_bbox_w_px
    plow_anchor_display = (plow.mount.x * scale, plow.mount.y * scale)
    paste_xy = mount - plow_anchor_display  [aligns plow's mount to truck's mount]

Direction: if truck.facing != plow.facing, mirror the plow horizontally
(and flip the anchor's xr accordingly) before scaling.

Usage:
    # Default: composite MVP3 onto every truck
    python app/scripts/auto_composite.py

    # Custom: list pairs explicitly
    python app/scripts/auto_composite.py --pair 2500 WEST-PPHD10-EQP --pair 1500 WEST-DEF68-EQP

    # All clean Westerns on the F-250
    python app/scripts/auto_composite.py --truck 2500 --all-plows
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


def _find_perspective_coeffs(src_quad, dst_quad):
    """Compute the 8 coefficients PIL needs for Image.PERSPECTIVE."""
    matrix = []
    for s, d in zip(src_quad, dst_quad):
        matrix.append([s[0], s[1], 1, 0, 0, 0, -d[0]*s[0], -d[0]*s[1]])
        matrix.append([0, 0, 0, s[0], s[1], 1, -d[1]*s[0], -d[1]*s[1]])
    A = np.matrix(matrix, dtype=np.float64)
    B = np.array([d for q in dst_quad for d in q]).reshape(8)
    res = np.dot(np.linalg.inv(A.T * A) * A.T, B)
    return np.array(res).reshape(8)


def project_through_rotation(
    px: float, py: float,
    anchor_x: float, anchor_y: float,
    angle_deg: float,
    perspective_d: float = 900,
) -> tuple[float, float]:
    """Project a point (px, py) through a CSS-style perspective(d) rotateY(angle)
    around the vertical line through (anchor_x, anchor_y). Returns the new
    (proj_x, proj_y) in the SAME coord system as the input (no canvas-growth
    offset applied)."""
    import math
    if abs(angle_deg) < 1e-3:
        return px, py
    rad = math.radians(angle_deg)
    cs, sn = math.cos(rad), math.sin(rad)
    x = px - anchor_x
    y = py - anchor_y
    z = -x * sn
    new_x = x * cs
    depth = perspective_d - z
    if depth < 1:
        depth = 1
    proj_x = new_x * perspective_d / depth
    proj_y = y * perspective_d / depth
    return proj_x + anchor_x, proj_y + anchor_y


def perspective_rotate_css(
    img: Image.Image,
    angle_deg: float,
    anchor_x: float,
    anchor_y: float,
    perspective_d: float = 900,
) -> tuple[Image.Image, float, float]:
    """Apply CSS-style `perspective(d) rotateY(angle)` around the given anchor.

    Matches what the calibrator's live preview shows. The rotation axis is
    the vertical line through (anchor_x, anchor_y); the perspective camera
    is at distance `perspective_d` perpendicular to the image plane.

    Returns (transformed_image, new_anchor_x, new_anchor_y). The new image
    canvas grows to fit the transformed pixels; the anchor stays attached
    to its original visual point.
    """
    if abs(angle_deg) < 1e-3:
        return img, anchor_x, anchor_y

    W, H = img.size
    import math
    rad = math.radians(angle_deg)
    cs, sn = math.cos(rad), math.sin(rad)

    def project(px: float, py: float) -> tuple[float, float]:
        # Local coords with anchor at origin
        x = px - anchor_x
        y = py - anchor_y
        # 3D point after rotateY(angle): (x*cs, y, -x*sn)  (CSS convention)
        z = -x * sn
        new_x = x * cs
        # Perspective projection: camera at +Z = perspective_d looking toward -Z
        depth = perspective_d - z  # = perspective_d + x*sn
        if depth < 1:
            depth = 1
        proj_x = new_x * perspective_d / depth
        proj_y = y * perspective_d / depth
        # Translate back to image coords
        return proj_x + anchor_x, proj_y + anchor_y

    # Project all 4 corners of the source image
    src_corners = [(0.0, 0.0), (float(W), 0.0), (float(W), float(H)), (0.0, float(H))]
    dst_corners = [project(x, y) for x, y in src_corners]

    # Output bounding box (with 2-pixel padding)
    xs = [p[0] for p in dst_corners]
    ys = [p[1] for p in dst_corners]
    out_min_x = min(xs) - 2
    out_min_y = min(ys) - 2
    out_max_x = max(xs) + 2
    out_max_y = max(ys) + 2
    out_w = max(2, int(math.ceil(out_max_x - out_min_x)))
    out_h = max(2, int(math.ceil(out_max_y - out_min_y)))

    # Translate dst corners so all coords are inside the output canvas
    dst_adj = [(x - out_min_x, y - out_min_y) for (x, y) in dst_corners]

    coeffs = _find_perspective_coeffs(dst_adj, src_corners)
    transformed = img.transform(
        (out_w, out_h), Image.PERSPECTIVE, coeffs, Image.BICUBIC
    )

    # The anchor's pixel position in the new image: it was at (anchor_x, anchor_y)
    # in the original; project(anchor_x, anchor_y) returns (anchor_x, anchor_y)
    # because (x=0, y=0) projects to (0, 0) → translated back is (anchor_x, anchor_y).
    new_anchor_x = anchor_x - out_min_x
    new_anchor_y = anchor_y - out_min_y
    return transformed, new_anchor_x, new_anchor_y

REPO = Path(__file__).resolve().parents[1].parent
PLOW_DIR = REPO / "app" / "backend" / "static" / "snow-plows"
TRUCK_DIR = REPO / "app" / "backend" / "static" / "trucks" / "renders_3q_mirrored"
ANCHORS_DEFAULT = Path.home() / "Downloads" / "plow_truck_anchors.json"
OUT_DIR = REPO / "app" / "backend" / "static" / "_auto_composites"


REFERENCE_INCHES = 102  # plow_scale_pct=100 means: a 102in plow displays at 100% of truck width


@dataclass
class TruckAnchor:
    cls: str
    img_path: Path
    facing: str = "left"
    # NEW fields (drag + slider model)
    mount_xr: float = 0.30
    mount_yr: float = 0.78
    plow_scale_pct: float = 50.0  # what % of truck width does a 102in plow occupy
    plow_rotation_deg: float = 0.0  # flat 2D rotation around mount anchor
    plow_perspective_deg: float = 0.0  # 3D tilt-into-page (matches truck's camera angle)


def _migrate_legacy(e: dict) -> dict:
    """Convert legacy {points, width_inches, scale_boost_pct, manual_offset_*}
    into {mount_xr, mount_yr, plow_scale_pct, plow_rotation_deg} if needed."""
    if "mount_xr" in e and "plow_scale_pct" in e:
        return e
    pts = e.get("points") or []
    if len(pts) == 2 and e.get("width_inches"):
        midX = (pts[0]["xr"] + pts[1]["xr"]) / 2 + (e.get("manual_offset_xr") or 0)
        midY = (pts[0]["yr"] + pts[1]["yr"]) / 2 + (e.get("manual_offset_yr") or 0)
        e["mount_xr"] = midX
        e["mount_yr"] = midY
        dxr = abs(pts[1]["xr"] - pts[0]["xr"])
        ppi_frac = dxr / float(e["width_inches"])
        boost = (e.get("scale_boost_pct") or 100) / 100.0
        plow_w_frac = REFERENCE_INCHES * ppi_frac * boost
        e["plow_scale_pct"] = round(plow_w_frac * 100)
    return e


@dataclass
class PlowAnchor:
    sku: str
    img_path: Path
    mount_xr: float
    mount_yr: float
    width_inches: float
    facing: str = "left"
    # Per-plow offsets layered on top of truck-side values. Calibrate once
    # per plow against the reference plow (MVP3 8'6"); engine adds them
    # to truck.plow_* fields when compositing.
    rotation_offset_deg: float = 0.0
    perspective_offset_deg: float = 0.0
    scale_offset_pct: float = 0.0


def load_anchors(path: Path) -> tuple[dict[str, TruckAnchor], dict[str, PlowAnchor]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    trucks: dict[str, TruckAnchor] = {}
    for cls, e in (data.get("trucks") or {}).items():
        e = _migrate_legacy(e)
        if "mount_xr" not in e or "plow_scale_pct" not in e:
            print(f"  ! truck {cls}: not enough data to compose, skip")
            continue
        img = TRUCK_DIR / f"{cls}.png"
        if not img.exists():
            print(f"  ! missing truck image {img.name}")
            continue
        trucks[cls] = TruckAnchor(
            cls=cls,
            img_path=img,
            mount_xr=float(e["mount_xr"]),
            mount_yr=float(e["mount_yr"]),
            plow_scale_pct=float(e["plow_scale_pct"]),
            plow_rotation_deg=float(e.get("plow_rotation_deg", 0)),
            plow_perspective_deg=float(e.get("plow_perspective_deg", 0)),
        )
    plows: dict[str, PlowAnchor] = {}
    for sku, e in (data.get("plows") or {}).items():
        pts = e.get("points") or []
        if len(pts) != 1:
            continue
        # Prefer x4 upscale if present
        x4 = PLOW_DIR / "skus" / sku / "hero_transparent_x4.png"
        std = PLOW_DIR / "skus" / sku / "hero_transparent.png"
        img = x4 if x4.exists() else std
        if not img.exists():
            print(f"  ! missing plow image for {sku}")
            continue
        plows[sku] = PlowAnchor(
            sku=sku,
            img_path=img,
            mount_xr=pts[0]["xr"], mount_yr=pts[0]["yr"],
            width_inches=float(e.get("width_inches", 102)),
            rotation_offset_deg=float(e.get("rotation_offset_deg", 0)),
            perspective_offset_deg=float(e.get("perspective_offset_deg", 0)),
            scale_offset_pct=float(e.get("scale_offset_pct", 0)),
        )
    return trucks, plows


def get_alpha_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    """Return the bounding box (x0,y0,x1,y1) of non-zero alpha."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        return (0, 0, img.width, img.height)
    return bbox


def composite(truck: TruckAnchor, plow: PlowAnchor) -> Image.Image:
    """Place a plow on a truck, matching the calibrator's CSS preview.

    Pipeline order matches CSS rendering so the engine output equals what the
    user calibrated against:
      1. Mirror plow horizontally if facings disagree.
      2. Resize plow to its display size (so perspective(900px) acts at the
         scale the user saw in the preview).
      3. CSS-style perspective(900px) rotateY around the mount anchor.
      4. Flat 2D rotation around the (possibly translated) anchor.
      5. Composite at the truck's mount point.
    """
    truck_img = Image.open(truck.img_path).convert("RGBA")
    plow_img = Image.open(plow.img_path).convert("RGBA")
    Tw, Th = truck_img.size

    mount_x = truck.mount_xr * Tw
    mount_y = truck.mount_yr * Th

    # 1. Mirror if needed
    plow_mount_xr = plow.mount_xr
    plow_mount_yr = plow.mount_yr
    if truck.facing != plow.facing:
        plow_img = plow_img.transpose(Image.FLIP_LEFT_RIGHT)
        plow_mount_xr = 1.0 - plow_mount_xr

    # Effective values: truck values + per-plow offsets (so each plow can
    # account for its own natural-angle differences vs the reference plow).
    effective_scale_pct = truck.plow_scale_pct + plow.scale_offset_pct
    effective_rotation_deg = truck.plow_rotation_deg + plow.rotation_offset_deg
    effective_perspective_deg = truck.plow_perspective_deg + plow.perspective_offset_deg

    # 2. Resize to display size first so perspective(900px) operates at the
    # same scale the calibrator's preview used.
    plow_display_w_px = (
        Tw * (effective_scale_pct / 100.0) * (plow.width_inches / REFERENCE_INCHES)
    )
    # The CSS preview uses overlay.naturalWidth as its base — i.e., the FULL
    # source image width (no alpha-bbox trim) — when computing displayedW from
    # plow_scale_pct. Match that here.
    Pw, Ph = plow_img.size
    scale = plow_display_w_px / Pw
    new_w = max(2, int(round(Pw * scale)))
    new_h = max(2, int(round(Ph * scale)))
    plow_resized = plow_img.resize((new_w, new_h), Image.LANCZOS)
    anchor_x = plow_mount_xr * new_w
    anchor_y = plow_mount_yr * new_h

    # 3. CSS-style perspective(900px) rotateY around the anchor.
    if abs(effective_perspective_deg) > 1e-3:
        plow_resized, anchor_x, anchor_y = perspective_rotate_css(
            plow_resized, effective_perspective_deg, anchor_x, anchor_y, perspective_d=900
        )

    # 4. Flat 2D rotation around the anchor (CSS applies this AFTER perspective).
    if abs(effective_rotation_deg) > 1e-3:
        before_w, before_h = plow_resized.size
        plow_resized = plow_resized.rotate(
            effective_rotation_deg,
            resample=Image.BICUBIC,
            center=(anchor_x, anchor_y),
            expand=True,
        )
        # PIL pads symmetrically around `center` when expand=True
        delta_w = (plow_resized.width - before_w) / 2
        delta_h = (plow_resized.height - before_h) / 2
        anchor_x += delta_w
        anchor_y += delta_h

    # 5. Composite at the truck's mount point.
    paste_x = int(round(mount_x - anchor_x))
    paste_y = int(round(mount_y - anchor_y))

    out = truck_img.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchors", default=str(ANCHORS_DEFAULT),
                    help="Path to plow_truck_anchors.json (default: Downloads)")
    ap.add_argument("--pair", action="append", nargs=2, metavar=("TRUCK", "PLOW"),
                    help="Specific (truck_cls, plow_sku) pair; can repeat")
    ap.add_argument("--truck", help="Render this truck against --all-plows")
    ap.add_argument("--all-plows", action="store_true", help="Render against every calibrated plow")
    ap.add_argument("--default-plow", default="WEST-MVP3MS86-EQP",
                    help="Plow used when iterating --all-trucks (default: MVP3)")
    ap.add_argument("--all-trucks", action="store_true",
                    help="Render --default-plow on every calibrated truck")
    args = ap.parse_args()

    anchors_path = Path(args.anchors)
    if not anchors_path.exists():
        print(f"Anchors file not found: {anchors_path}")
        return 1

    trucks, plows = load_anchors(anchors_path)
    print(f"Loaded {len(trucks)} calibrated trucks, {len(plows)} calibrated plows.")
    if not trucks or not plows:
        print("Nothing to composite — calibrate at least one truck and one plow first.")
        return 1

    pairs: list[tuple[str, str]] = []
    if args.pair:
        pairs.extend((t, p) for t, p in args.pair)
    if args.all_plows:
        truck_cls = args.truck or next(iter(trucks))
        for sku in plows:
            pairs.append((truck_cls, sku))
    if args.all_trucks or not pairs:
        plow_sku = args.default_plow
        if plow_sku not in plows:
            # Fall back to first calibrated plow
            plow_sku = next(iter(plows))
        for cls in trucks:
            pairs.append((cls, plow_sku))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for truck_cls, plow_sku in pairs:
        if truck_cls not in trucks:
            print(f"  ! truck {truck_cls} not calibrated, skip")
            continue
        if plow_sku not in plows:
            print(f"  ! plow {plow_sku} not calibrated, skip")
            continue
        out = composite(trucks[truck_cls], plows[plow_sku])
        slug = f"{truck_cls}__{plow_sku}.png"
        out_path = OUT_DIR / slug
        out.save(out_path)
        n += 1
        print(f"  saved {slug}")

    # Build a comparison HTML
    cards = "\n".join(
        f'<div class="card"><h3>{p.replace(".png","").replace("__"," + ")}</h3>'
        f'<img src="{p}"></div>'
        for p in sorted(x.name for x in OUT_DIR.glob("*.png"))
    )
    (OUT_DIR / "_lineup.html").write_text(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>Auto-composite results</title>
<style>
  body {{ margin:0; font-family:-apple-system,system-ui,sans-serif;
          background:#0f172a; color:#e2e8f0; padding:14px; }}
  h1 {{ margin:0 0 4px 0; font-size:16px; }}
  p {{ margin:0 0 14px 0; color:#94a3b8; font-size:12px; }}
  .grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }}
  .card {{ background:#1e293b; padding:8px; border-radius:6px; }}
  .card h3 {{ margin:0 0 6px 0; color:#10b981;
             font-family:ui-monospace,Consolas,monospace; font-size:13px; }}
  .card img {{ width:100%; border-radius:4px; display:block; }}
</style></head><body>
<h1>Auto-composite results — anchor-driven engine</h1>
<p>Each pair below was placed automatically using calibrated anchors and real-world widths. No per-pair tuning.</p>
<div class="grid">{cards}</div>
</body></html>""",
        encoding="utf-8",
    )
    print(f"\n{n} composites saved to {OUT_DIR}")
    print(f"open: file:///{(OUT_DIR / '_lineup.html').as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
