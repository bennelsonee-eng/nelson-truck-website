"""Try to dial in FLUX Kontext settings that preserve text accurately.

Variants:
  A) Default: 20 steps, guidance 2.5, generic "make photorealistic" prompt
  B) Explicit text instruction
  C) Lower guidance (1.8) — gives model less freedom to alter input
  D) Higher steps (30) + explicit text instruction
  E) Multi-image with the same v2 plow as reference (gives Kontext two text anchors)
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
        return 1
    seed_path = REPO / "app" / "backend" / "static" / "trucks" / "composites_3q" / "2500_with_mvp3.png"
    seed = Image.open(seed_path).convert("RGB")
    plow_ref_path = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
    plow_ref = Image.open(plow_ref_path).convert("RGBA")
    print(f"Seed: {seed.size}")
    print(f"Plow ref: {plow_ref.size}")

    variants = [
        ("A_default",         "make this photorealistic, professional automotive product photography, matching studio lighting and shadows", None, 20, 2.5),
        ("B_text_explicit",   "make this photorealistic. Keep all text on the plow exactly as shown. The WESTERN logo and MVP3 badge must remain unchanged and clearly readable. Professional automotive photography, matching studio lighting.", None, 20, 2.5),
        ("C_low_guidance",    "make this photorealistic. Keep all text exactly readable. WESTERN logo and MVP3 badge unchanged.", None, 20, 1.8),
        ("D_high_steps",      "make this photorealistic. Keep all text on the plow exactly as shown. The WESTERN logo and MVP3 badge must remain unchanged and clearly readable.", None, 30, 2.5),
        ("E_multiimage",      "make this photorealistic. Keep all WESTERN and MVP3 text exactly as in the reference plow image, unchanged and readable.", plow_ref, 25, 2.5),
    ]

    for label, prompt, ref, steps, guidance in variants:
        print(f"\n[{label}] steps={steps} guidance={guidance} multi={'yes' if ref else 'no'}")
        result = await render_plow_on_truck(
            truck_image=seed,
            plow_brand="Western",
            plow_model="MVP3 stainless V-plow",
            plow_blade_type=prompt,
            plow_reference_image=ref,
            seed=42,
            steps=steps,
            guidance=guidance,
            timeout_s=200,
        )
        print(f"  ok={result.ok} duration={result.duration_ms}ms")
        if result.ok and result.image_bytes:
            out_path = REPO / "wan_test_output" / f"FLUX_KONTEXT_text_{label}.png"
            out_path.write_bytes(result.image_bytes)
            print(f"  saved {out_path.name}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
