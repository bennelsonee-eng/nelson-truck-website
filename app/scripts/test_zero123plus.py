"""Test Zero123++ on the plows that broke Zero123 (MVP Plus + Enforcer).

Zero123++ v1.2 is "more robust to a wider range of input field of views,
croppings" — exactly our problem.  Generates 6 views at fixed azimuths
(30°, 90°, 150°, 210°, 270°, 330°) in one shot.  The 30° view matches
what we want for the truck composite.

Runs on the llama via diffusers (no ComfyUI custom node needed).
Apache 2.0 license — commercial-friendly.
"""

from __future__ import annotations

import sys
import time
from io import BytesIO
from pathlib import Path

import requests
import torch
from diffusers import DiffusionPipeline, EulerAncestralDiscreteScheduler
from PIL import Image


REPO = Path(__file__).resolve().parents[2]
SKUS = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUT_DIR = REPO / "wan_test_output" / "zero123plus_test"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading Zero123++ v1.2 pipeline...")
    t0 = time.time()
    pipeline = DiffusionPipeline.from_pretrained(
        "sudo-ai/zero123plus-v1.2",
        custom_pipeline="sudo-ai/zero123plus-pipeline",
        torch_dtype=torch.float16,
    )
    pipeline.scheduler = EulerAncestralDiscreteScheduler.from_config(
        pipeline.scheduler.config, timestep_spacing="trailing"
    )
    pipeline.to("cuda")
    print(f"  loaded in {time.time() - t0:.1f}s")

    # Test plows: the ones that broke Zero123
    test_skus = [
        "WEST-MVPPMS86-EQP",
        "WEST-ENFMS76-EQP",
        # Also test one that worked with Zero123 for comparison
        "WEST-MVP3MS86-EQP",
    ]

    for sku in test_skus:
        src = SKUS / sku / "hero_manufacturer.jpg"
        if not src.exists():
            print(f"  ! missing {src}")
            continue
        print(f"\n=== {sku} ===")
        print(f"  loading {src.name}")
        cond = Image.open(src).convert("RGB")

        # Pad to square + resize to 320 (Zero123++ native input)
        W, H = cond.size
        side = max(W, H)
        sq = Image.new("RGB", (side, side), (255, 255, 255))
        sq.paste(cond, ((side - W) // 2, (side - H) // 2))
        cond_320 = sq.resize((320, 320), Image.LANCZOS)
        print(f"  input: {cond.size} -> 320x320 squared")

        t0 = time.time()
        result = pipeline(cond_320, num_inference_steps=75).images[0]
        elapsed = time.time() - t0
        print(f"  rendered in {elapsed:.1f}s")
        print(f"  output: {result.size}")
        out_path = OUT_DIR / f"{sku}_z123plus.png"
        result.save(out_path)
        print(f"  saved {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
