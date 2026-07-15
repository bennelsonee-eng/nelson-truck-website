"""Test Kontext variant C with the NEW MVP3 v2 composite (correct orientation,
WESTERN text readable).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from PIL import Image  # noqa: E402

from app.services.flux_kontext_service import (  # noqa: E402
    health_check,
    render_plow_on_truck,
)


async def main() -> int:
    if not await health_check():
        print("ComfyUI not reachable")
        return 1

    seed_path = REPO / "wan_test_output" / "f250_with_mvp3_v2.png"
    seed = Image.open(seed_path).convert("RGB")
    print(f"Seed (PIL composite v2): {seed.size}")

    print("\nCalling Kontext variant C (composite seed, no plow ref)...")
    result = await render_plow_on_truck(
        truck_image=seed,
        plow_brand="Western",
        plow_model="MVP3 stainless V-plow",
        plow_blade_type="make this photorealistic, professional automotive product photography, matching studio lighting and shadows",
        plow_reference_image=None,  # variant C: seed already has plow
        seed=42,
        steps=25,
        guidance=2.5,
        timeout_s=180,
    )
    print(f"  ok={result.ok} duration={result.duration_ms}ms")
    if result.ok and result.image_bytes:
        out_path = REPO / "wan_test_output" / "FLUX_KONTEXT_v3_new_composite.png"
        out_path.write_bytes(result.image_bytes)
        print(f"  saved: {out_path}")
    else:
        print(f"  error: {result.error}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
