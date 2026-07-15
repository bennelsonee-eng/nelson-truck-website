"""Run Kontext variant-C on the 10 priority plow composites + build comparison grid.

For each composite (F-250 + plow), call Kontext with the photoreal+text-preserve
prompt.  Save each result.  Build a 5x2 grid for visual review.
"""

from __future__ import annotations

import asyncio
import sys
from io import BytesIO
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.services.flux_kontext_service import (  # noqa: E402
    health_check,
    render_plow_on_truck,
)


SOURCE_DIR = REPO / "wan_test_output" / "priority_plows"
RESULT_DIR = REPO / "wan_test_output" / "priority_plows_kontext"
GRID_PATH = REPO / "wan_test_output" / "priority_plows_kontext_grid.png"


# (sku, friendly name)
PLOWS = [
    ("WEST-MVP3MS86-EQP",   "Western MVP3 8'6\" V"),
    ("WEST-MVPPMS86-EQP",   "Western MVP Plus 8'6\" V"),
    ("WEST-MVPPMS96-EQP",   "Western MVP Plus 9'6\" V"),
    ("WEST-ENFMS76-EQP",    "Western Enforcer 7'6\" V MS"),
    ("WEST-ENFSS76-EQP",    "Western Enforcer 7'6\" V SS"),
    ("WEST-HTS76-EQP",      "Western HTS 7'6\" Straight"),
    ("MYP-09275-EQP",       "Meyer Lot Pro LD 7'6\""),
    ("SNOW-16020412-EQP",   "SnowDogg MD68II"),
    ("SNOW-16020724-EQP",   "SnowDogg VXF85II V"),
    ("SNOW-16020922-EQP",   "SnowDogg XP810II Wing"),
]


PROMPT = (
    "make this photorealistic, professional automotive product photography, "
    "matching studio lighting and shadows. "
    "Keep all text on the plow exactly as shown. The brand logo and any model "
    "badge must remain unchanged and clearly readable."
)


async def render_one(sku: str, label: str) -> Image.Image | None:
    src_path = SOURCE_DIR / f"{sku}_on_f250.png"
    if not src_path.exists():
        return None
    seed = Image.open(src_path).convert("RGB")
    print(f"  [{sku}] rendering...")
    result = await render_plow_on_truck(
        truck_image=seed,
        plow_brand="",
        plow_model="",
        plow_blade_type=PROMPT,
        plow_reference_image=None,
        seed=42,
        steps=20,
        guidance=2.5,
        timeout_s=180,
    )
    print(f"  [{sku}] ok={result.ok} duration={result.duration_ms}ms")
    if not result.ok or not result.image_bytes:
        return None
    out_path = RESULT_DIR / f"{sku}_kontext.png"
    out_path.write_bytes(result.image_bytes)
    return Image.open(BytesIO(result.image_bytes)).convert("RGB")


async def main() -> int:
    if not await health_check():
        print("ComfyUI not reachable")
        return 1
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Rendering {len(PLOWS)} plow + F-250 composites via Kontext variant-C")

    results: list[tuple[str, str, Image.Image | None]] = []
    for sku, label in PLOWS:
        img = await render_one(sku, label)
        results.append((sku, label, img))

    # Build a 5-col x 2-row grid
    TILE_W, TILE_H, LABEL_H = 640, 360, 30
    COLS = 5
    rows = (len(results) + COLS - 1) // COLS
    grid = Image.new("RGB", (COLS * TILE_W, rows * (TILE_H + LABEL_H)), (40, 40, 40))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    for i, (sku, label, img) in enumerate(results):
        r, c = divmod(i, COLS)
        x = c * TILE_W
        y = r * (TILE_H + LABEL_H)
        if img is not None:
            fitted = img.resize((TILE_W, TILE_H), Image.LANCZOS)
            grid.paste(fitted, (x, y))
        draw.rectangle([x, y + TILE_H, x + TILE_W, y + TILE_H + LABEL_H], fill=(20, 20, 20))
        draw.text((x + 8, y + TILE_H + 7), label, fill=(255, 255, 100), font=font)

    grid.save(GRID_PATH)
    print(f"\nGrid saved: {GRID_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
