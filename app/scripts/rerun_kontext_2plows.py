"""Rerun Kontext variant-C on the rotated MYP-09275 + WEST-HTS76 composites."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from PIL import Image  # noqa: E402

from app.services.flux_kontext_service import (  # noqa: E402
    health_check, render_plow_on_truck,
)


async def run_one(sku: str) -> None:
    src_path = REPO / "wan_test_output" / "priority_plows" / f"{sku}_on_f250.png"
    seed = Image.open(src_path).convert("RGB")
    print(f"[{sku}] rendering...")
    result = await render_plow_on_truck(
        truck_image=seed,
        plow_brand="", plow_model="",
        plow_blade_type=(
            "make this photorealistic, professional automotive product "
            "photography, matching studio lighting and shadows. "
            "Keep all text on the plow exactly as shown. The brand logo and any "
            "model badge must remain unchanged and clearly readable."
        ),
        plow_reference_image=None, seed=42, steps=20, guidance=2.5, timeout_s=180,
    )
    print(f"[{sku}] ok={result.ok} duration={result.duration_ms}ms")
    if result.ok and result.image_bytes:
        out_path = REPO / "wan_test_output" / "priority_plows_kontext" / f"{sku}_kontext.png"
        out_path.write_bytes(result.image_bytes)


async def main() -> int:
    if not await health_check():
        return 1
    for sku in ("MYP-09275-EQP", "WEST-HTS76-EQP"):
        await run_one(sku)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
