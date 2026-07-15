"""End-to-end test of FluxKontextService.

Runs from Windows side using the F-250 render we already have + a "Add a
Western MVP3 V-plow" prompt.  Saves result to wan_test_output/ for inspection.

Pre-req:
  - FLUX Kontext model installed at ~/ComfyUI/models/diffusion_models/
    (file: flux1-dev-kontext_fp8_scaled.safetensors)
  - ComfyUI running on llama (port 8188)
  - Tailscale connectivity from Windows -> 100.85.94.57
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add backend to path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from PIL import Image  # noqa: E402

from app.services.flux_kontext_service import (  # noqa: E402
    health_check,
    render_plow_on_truck,
)


async def main() -> int:
    print("[1/4] Checking ComfyUI health on llama (100.85.94.57:8188)...")
    if not await health_check():
        print("  ComfyUI NOT reachable — bail")
        return 1
    print("  OK")

    truck_path = REPO / "wan_test_output" / "lineup_3q" / "2500_seed1337.png"
    if not truck_path.exists():
        print(f"  Truck render missing: {truck_path}")
        return 1

    print(f"[2/4] Loading truck render: {truck_path.name}")
    truck = Image.open(truck_path).convert("RGB")
    print(f"  Loaded {truck.size}")

    # Multi-image mode: feed the clean MVP3 reference as a second image
    plow_ref_path = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
    plow_ref = Image.open(plow_ref_path).convert("RGBA")
    print(f"  Plow reference: {plow_ref_path.name} {plow_ref.size}")

    print("[3/4] Calling FLUX Kontext multi-image (truck + plow ref) — 30-90 sec...")
    result = await render_plow_on_truck(
        truck_image=truck,
        plow_brand="Western",
        plow_model="MVP3 stainless V-plow",
        plow_blade_type="V-plow with two angled wings in scoop position",
        plow_reference_image=plow_ref,
        seed=42,
        steps=20,
        guidance=2.5,
        timeout_s=180,
    )

    print(f"[4/4] Result: ok={result.ok} duration={result.duration_ms}ms")
    if result.ok and result.image_bytes:
        out_path = REPO / "wan_test_output" / "FLUX_KONTEXT_e2e_multimage.png"
        out_path.write_bytes(result.image_bytes)
        print(f"  saved: {out_path}")
        return 0
    else:
        print(f"  ERROR: {result.error}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
