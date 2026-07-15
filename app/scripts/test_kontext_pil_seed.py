"""Test Kontext with our v5 PIL composite as the SEED image.

The v5 PIL composite has:
  - Truck rendered at correct angle
  - Plow positioned correctly (V-pivot at grille, cutting edge at ground)
  - Right SCALE per truck class
  - But: flat 2D compositing — looks "pasted on", missing depth/lighting consistency

Strategy: feed this composite as input to Kontext along with a clean plow
reference, and ask the model to "make this photorealistic" — it should
preserve the layout we hand-tuned and just upgrade the realism.

Variants to compare:
  A.  Bare F-250 + text prompt only             (baseline — what we had)
  B.  Bare F-250 + clean plow ref + prompt      (multi-image — current)
  C.  v5 PIL composite as seed + text prompt    (NEW — preserve layout)
  D.  v5 PIL composite as seed + plow ref + prompt  (NEW — best of both)

Builds a 2x2 comparison grid so we can pick the winning approach.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.services.flux_kontext_service import (  # noqa: E402
    health_check,
    render_plow_on_truck,
)


async def render_variant(label: str, truck: Image.Image,
                         plow_ref: Image.Image | None,
                         steps: int = 25, guidance: float = 3.0) -> Image.Image | None:
    print(f"\n[{label}] rendering...")
    result = await render_plow_on_truck(
        truck_image=truck,
        plow_brand="Western",
        plow_model="MVP3 stainless V-plow",
        plow_blade_type="V-plow with two angled wings in scoop position, snow markers extending up, cutting edge at ground level",
        plow_reference_image=plow_ref,
        seed=42,
        steps=steps,
        guidance=guidance,
        timeout_s=240,
    )
    print(f"[{label}] {result.duration_ms}ms ok={result.ok} err={result.error}")
    if result.ok and result.image_bytes:
        from io import BytesIO
        return Image.open(BytesIO(result.image_bytes)).convert("RGB")
    return None


async def main() -> int:
    if not await health_check():
        print("ComfyUI not reachable")
        return 1

    bare_truck = Image.open(REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png").convert("RGB")
    pil_composite = Image.open(REPO / "app" / "backend" / "static" / "trucks" / "composites_3q" / "2500_with_mvp3.png").convert("RGB")
    plow_ref = Image.open(REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png").convert("RGBA")

    print(f"Bare truck:    {bare_truck.size}")
    print(f"PIL composite: {pil_composite.size}")
    print(f"Plow ref:      {plow_ref.size}")

    # Render the 4 variants
    variants = [
        ("A_bare_textonly",      bare_truck,    None),
        ("B_bare_multiimage",    bare_truck,    plow_ref),
        ("C_pil_textonly",       pil_composite, None),
        ("D_pil_multiimage",     pil_composite, plow_ref),
    ]

    results: dict[str, Image.Image | None] = {}
    for label, truck, ref in variants:
        results[label] = await render_variant(label, truck, ref)
        if results[label] is not None:
            results[label].save(REPO / "wan_test_output" / f"FLUX_KONTEXT_v2_{label}.png")

    # Build a 2x2 comparison grid
    if all(r is not None for r in results.values()):
        TILE_W = 800
        TILE_H = int(TILE_W * 9 / 16)
        LABEL_H = 30
        CELL_H = TILE_H + LABEL_H
        grid = Image.new("RGB", (TILE_W * 2 + 4, CELL_H * 2 + 4), (40, 40, 40))
        draw = ImageDraw.Draw(grid)
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except Exception:
            font = ImageFont.load_default()

        descriptions = {
            "A_bare_textonly":   "A) Bare truck + text prompt only (no plow ref)",
            "B_bare_multiimage": "B) Bare truck + plow REFERENCE image",
            "C_pil_textonly":    "C) PIL composite seed + text prompt (no ref)",
            "D_pil_multiimage":  "D) PIL composite seed + plow ref (BEST?)",
        }
        for i, (label, _, _) in enumerate(variants):
            row, col = divmod(i, 2)
            x = col * (TILE_W + 2) + 2
            y = row * (CELL_H + 2) + 2
            img = results[label]
            if img is None:
                continue
            fitted = img.resize((TILE_W, TILE_H), Image.LANCZOS)
            grid.paste(fitted, (x, y))
            draw.rectangle([x, y + TILE_H, x + TILE_W, y + TILE_H + LABEL_H],
                           fill=(20, 20, 20))
            draw.text((x + 10, y + TILE_H + 7), descriptions[label],
                      fill=(255, 255, 0), font=font)

        out_path = REPO / "wan_test_output" / "FLUX_KONTEXT_v2_comparison_grid.png"
        grid.save(out_path)
        print(f"\nSaved comparison grid: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
