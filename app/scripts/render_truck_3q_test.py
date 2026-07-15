"""Render a single F-250 at front-3/4 angle to match 3/4 plow marketing shots.

Test for Path A (re-render trucks at 3/4 to align with the 70 plow shots we
already have at 3/4 marketing angle).

Camera convention:
  - Front three-quarter view, camera ~30° off centerline (operator's right)
  - Same eye-level pitch as our head-on renders
  - Same studio backdrop / lighting as render_truck_lineup_flux.py

Why F-250: middle of the lineup, photographs well at 3/4, paired with
the Western MVP3 MS V-plow (8'6" stainless) for the composite test.

Run on llama:
    source ~/wan-venv/bin/activate && python /tmp/render_3q_test.py
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx


COMFY = "http://127.0.0.1:8188"
OUTPUT_DIR = Path("/tmp/flux_3q_test")

# Front-3/4 view tail.  Differences from head-on:
#   - "front three-quarter view" replaces "head-on front view"
#   - "passenger side visible" hints at which 3/4 side
#   - "both headlights and grille visible" forces front face still showing
COMMON_TAIL = (
    ", front three-quarter view, camera 30 degrees off centerline, "
    "passenger side and front grille visible, both headlights visible, "
    "full vehicle visible in frame, parked stationary, "
    "professional automotive product photography, seamless light grey paper backdrop, "
    "infinity cove studio, soft three-point lighting, shot on Canon EOS R5 with 85mm "
    "lens at f/4, ultra detailed, photorealistic, 8K, sharp focus, no people, "
    "no plow, no snow, no mud"
)
NEGATIVE = (
    "low quality, blurry, distorted, text, watermark, logo overlay, badge overlay, "
    "people, snow, dirt, mud, motion blur, lifestyle, road, parking lot, trees, "
    "buildings, multiple vehicles, cropped, cartoon, illustration, painting, "
    "snow plow attached, plow blade, shovel, side view, profile view, rear view"
)

# F-250 (2500 class) — middle of the lineup, paired with Western MVP3 V-plow test
TEST_TRUCK = {
    "id": "2500_3q",
    "vehicle_phrase": (
        "2024 Ford F-250 Super Duty Lariat pickup truck, silver paint, chrome trim"
    ),
    "seed": 42,
}


def build_workflow(prompt: str, seed: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "flux1-schnell-fp8.safetensors",
            "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "flux-vae-bf16.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": NEGATIVE}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {
            "width": 1024, "height": 576, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["4", 0],
            "negative": ["5", 0],
            "latent_image": ["6", 0],
            "seed": seed,
            "steps": 4,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {
            "samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": "flux_3q_test"}},
    }


def queue_and_wait(client: httpx.Client, workflow: dict) -> dict:
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
    r = client.post(f"{COMFY}/prompt", json=payload, timeout=30.0)
    if r.status_code >= 400:
        print(json.dumps(r.json(), indent=2))
        r.raise_for_status()
    prompt_id = r.json()["prompt_id"]
    while True:
        time.sleep(3)
        h = client.get(f"{COMFY}/history/{prompt_id}", timeout=15.0).json()
        if prompt_id in h and h[prompt_id].get("status", {}).get("completed"):
            return h[prompt_id]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Render 4 seed variants so we can pick the cleanest 3/4 framing
    seeds = [42, 1337, 8888, 31415]
    with httpx.Client() as client:
        for i, seed in enumerate(seeds):
            prompt = TEST_TRUCK["vehicle_phrase"] + COMMON_TAIL
            print(f"\n[variant {i+1}/{len(seeds)}, seed={seed}]")
            t0 = time.time()
            wf = build_workflow(prompt, seed)
            result = queue_and_wait(client, wf)
            elapsed = time.time() - t0
            for node_output in result.get("outputs", {}).values():
                imgs = node_output.get("images", [])
                if not imgs:
                    continue
                first = imgs[0]
                url = (
                    f"{COMFY}/view?filename={first['filename']}"
                    f"&subfolder={first.get('subfolder','')}&type=output"
                )
                r = client.get(url, timeout=60.0)
                outpath = OUTPUT_DIR / f"f250_3q_seed{seed}.png"
                outpath.write_bytes(r.content)
                print(f"  saved {outpath.name} ({len(r.content):,} bytes, {elapsed:.1f}s)")
                break
    print(f"\n4 F-250 3/4 variants saved to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
