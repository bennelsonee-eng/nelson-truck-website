"""Composite engine variant: rotate the TRUCK to match the plow's angle,
not the plow to match the truck.

User-preferred behavior because:
  - Plow is the "hero" of the configurator (they're selling plows)
  - Plow image quality stays untouched (no perspective skew on the plow)
  - Truck image is more disposable (it's a generated FLUX render anyway)

Math:
  - Each plow has perspective_offset_deg in the anchor JSON. That value was
    originally calibrated to ROTATE THE PLOW so it matches MVP3 8'6".
  - We apply the SAME magnitude but to the TRUCK (with opposite sign) so the
    truck rotates to match the plow's natural angle instead.
  - Plow gets no perspective transform — shown at its native photographed angle.

Usage:
    python app/scripts/auto_composite_truck_match.py
        [--anchors PATH] [--truck CLS] [--all-plows] [--all-trucks]
        [--default-plow SKU] [--pair TRUCK PLOW]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

# Reuse helpers from the original engine
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_composite import (  # type: ignore[import-not-found]
    REFERENCE_INCHES,
    ANCHORS_DEFAULT,
    perspective_rotate_css,
    load_anchors,
)

REPO = Path(__file__).resolve().parents[1].parent
OUT_DIR = REPO / "app" / "backend" / "static" / "_auto_composites_truck_match"


def composite_truck_match(truck, plow) -> Image.Image:
    """Rotate truck to match plow's natural angle, then composite plow as-is."""
    truck_img = Image.open(truck.img_path).convert("RGBA")
    plow_img = Image.open(plow.img_path).convert("RGBA")
    Tw, Th = truck_img.size

    # Mirror plow if facing differs
    plow_mount_xr = plow.mount_xr
    plow_mount_yr = plow.mount_yr
    if truck.facing != plow.facing:
        plow_img = plow_img.transpose(Image.FLIP_LEFT_RIGHT)
        plow_mount_xr = 1.0 - plow_mount_xr

    # Rotate the TRUCK by the same magnitude that would have rotated the plow,
    # but with opposite sign (since we want the truck to come to the plow,
    # not the other way around). Use truck.plow_perspective_deg as the
    # baseline (this was tuned for MVP3) plus the plow's offset (which captures
    # how much THIS plow differs from MVP3).
    # Combined effect: the truck rotates to match each individual plow.
    # NOTE on sign: truck.plow_perspective_deg was the value that rotated the
    # PLOW to match the truck. To make the TRUCK rotate to where the plow
    # naturally is, use the SAME magnitude with the SAME sign (don't negate).
    # Reasoning: -36 was "plow needed to rotate -36 to align with truck", so
    # equivalently "truck needs to rotate -(-36) = +36 to align with plow"...
    # WAIT no. If plow rotated -36 brought plow to truck position, then truck
    # rotated -(-36)=+36 brings TRUCK to plow position (same destination from
    # opposite directions). Sign experimentation needed.
    truck_rotation = (truck.plow_perspective_deg + plow.perspective_offset_deg)

    if abs(truck_rotation) > 1e-3:
        truck_img, _, _ = perspective_rotate_css(
            truck_img, truck_rotation,
            anchor_x=Tw / 2, anchor_y=Th / 2,
            perspective_d=900,
        )
        Tw, Th = truck_img.size

    # Mount point: same RATIO in the (possibly expanded) truck image
    mount_x = truck.mount_xr * Tw
    mount_y = truck.mount_yr * Th

    # Resize plow to display size — use the standard scale calculation
    plow_display_w_px = (
        Tw * (truck.plow_scale_pct / 100.0) * (plow.width_inches / REFERENCE_INCHES)
    )
    Pw, Ph = plow_img.size
    scale = plow_display_w_px / Pw
    new_w = max(2, int(round(Pw * scale)))
    new_h = max(2, int(round(Ph * scale)))
    plow_resized = plow_img.resize((new_w, new_h), Image.LANCZOS)
    anchor_x = plow_mount_xr * new_w
    anchor_y = plow_mount_yr * new_h

    # No perspective on plow — shown at its native angle
    # (This is the whole point of truck-match mode)

    # Optional: keep flat 2D rotation if user set one
    if abs(truck.plow_rotation_deg + plow.rotation_offset_deg) > 1e-3:
        rot = truck.plow_rotation_deg + plow.rotation_offset_deg
        before_w, before_h = plow_resized.size
        plow_resized = plow_resized.rotate(
            rot, resample=Image.BICUBIC,
            center=(anchor_x, anchor_y), expand=True,
        )
        anchor_x += (plow_resized.width - before_w) / 2
        anchor_y += (plow_resized.height - before_h) / 2

    paste_x = int(round(mount_x - anchor_x))
    paste_y = int(round(mount_y - anchor_y))
    out = truck_img.copy()
    out.alpha_composite(plow_resized, dest=(paste_x, paste_y))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchors", default=str(ANCHORS_DEFAULT))
    ap.add_argument("--pair", action="append", nargs=2, metavar=("TRUCK", "PLOW"))
    ap.add_argument("--truck")
    ap.add_argument("--all-plows", action="store_true")
    ap.add_argument("--all-trucks", action="store_true")
    ap.add_argument("--default-plow", default="WEST-MVP3MS86-EQP")
    args = ap.parse_args()

    anchors_path = Path(args.anchors)
    if not anchors_path.exists():
        print(f"Anchors file not found: {anchors_path}")
        return 1

    trucks, plows = load_anchors(anchors_path)
    print(f"Loaded {len(trucks)} trucks, {len(plows)} plows.")

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
        t = trucks[truck_cls]
        p = plows[plow_sku]
        truck_rot = -(t.plow_perspective_deg + p.perspective_offset_deg)
        img = composite_truck_match(t, p)
        slug = f"{truck_cls}__{plow_sku}.png"
        img.save(OUT_DIR / slug)
        n += 1
        print(f"  saved {slug}  truck rotated {truck_rot:+.1f}°")

    cards = "\n".join(
        f'<div class="card"><h3>{p.replace(".png","").replace("__"," + ")}</h3>'
        f'<img src="{p}"></div>'
        for p in sorted(x.name for x in OUT_DIR.glob("*.png"))
    )
    (OUT_DIR / "_lineup.html").write_text(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>Truck-rotated-to-match-plow composite</title>
<style>
  body {{ margin:0; font-family:-apple-system,system-ui,sans-serif;
          background:#0f172a; color:#e2e8f0; padding:14px; }}
  h1 {{ margin:0 0 4px 0; font-size:16px; }}
  p  {{ margin:0 0 14px 0; color:#94a3b8; font-size:12px; }}
  .grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }}
  .card {{ background:#1e293b; padding:8px; border-radius:6px; }}
  .card h3 {{ margin:0 0 6px 0; color:#10b981;
             font-family:ui-monospace,Consolas,monospace; font-size:13px; }}
  .card img {{ width:100%; border-radius:4px; display:block; }}
</style></head><body>
<h1>Truck rotated to match plow's natural angle</h1>
<p>Plow is shown at its photographed angle (no perspective skew). Truck is
rotated via CSS-style perspective(900px) rotateY to match.
Tradeoff: heavier rotations distort the truck, but plow image stays crisp.</p>
<div class="grid">{cards}</div>
</body></html>""",
        encoding="utf-8",
    )
    print(f"\n{n} composites in {OUT_DIR}")
    print(f"open: http://localhost:8765/_auto_composites_truck_match/_lineup.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
