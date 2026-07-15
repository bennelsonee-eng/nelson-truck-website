#!/bin/bash
# Runs on llama directly (since pipeline loads model into GPU RAM there)
set -euo pipefail

cd /tmp
source ~/wan-venv/bin/activate

python <<'PY'
import time
from pathlib import Path
import torch
from diffusers import DiffusionPipeline, EulerAncestralDiscreteScheduler
from PIL import Image

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
print(f"  loaded in {time.time()-t0:.1f}s")

OUT = Path("/tmp/zero123plus_out")
OUT.mkdir(exist_ok=True)

for sku in ["WEST-MVPPMS86-EQP", "WEST-ENFMS76-EQP", "WEST-MVP3MS86-EQP"]:
    src = Path(f"/tmp/{sku}_source.jpg")
    if not src.exists():
        print(f"missing {src}")
        continue
    print(f"\n=== {sku} ===")
    cond = Image.open(src).convert("RGB")
    W, H = cond.size
    side = max(W, H)
    sq = Image.new("RGB", (side, side), (255, 255, 255))
    sq.paste(cond, ((side - W) // 2, (side - H) // 2))
    cond_320 = sq.resize((320, 320), Image.LANCZOS)
    print(f"  input: {cond.size} -> 320x320")
    t0 = time.time()
    result = pipeline(cond_320, num_inference_steps=75).images[0]
    print(f"  rendered in {time.time()-t0:.1f}s, output {result.size}")
    out = OUT / f"{sku}_z123plus.png"
    result.save(out)
    print(f"  saved {out}")
PY
PY
