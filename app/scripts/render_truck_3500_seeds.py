"""Re-render F-350 dually with multiple new seeds.

Issue: 3500_seed8888 had artifacts (user said "wrong").  Trying new seeds with
sharper "dually" emphasis in prompt to force visible dual rear wheels.

Output: /tmp/flux_3500_seeds/3500_seed<seed>.png
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx


COMFY = "http://127.0.0.1:8188"
OUTPUT_DIR = Path("/tmp/flux_3500_seeds")

# Stronger dually-emphasis prompt
PROMPT = (
    "2024 Ford F-350 Super Duty Lariat dually pickup truck, white pearl paint, "
    "chrome trim, prominent dual rear wheels visible, wide rear fenders, "
    "subtle front three-quarter view, camera 15 degrees off centerline, "
    "nearly head-on with slight rotation, both headlights and full grille "
    "prominently visible, hint of passenger side fender, "
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
    "snow plow attached, plow blade, shovel, side view, profile view, rear view, "
    "extreme angle, aggressive rotation, full side view, single rear wheels"
)

SEEDS = [42, 555, 12345, 9999, 7777, 31415]


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
            "images": ["8", 0], "filename_prefix": "flux_3500_seeds"}},
    }


def queue_and_wait(client: httpx.Client, workflow: dict) -> dict:
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
    r = client.post(f"{COMFY}/prompt", json=payload, timeout=30.0)
    r.raise_for_status()
    prompt_id = r.json()["prompt_id"]
    while True:
        time.sleep(3)
        h = client.get(f"{COMFY}/history/{prompt_id}", timeout=15.0).json()
        if prompt_id in h and h[prompt_id].get("status", {}).get("completed"):
            return h[prompt_id]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client() as client:
        for seed in SEEDS:
            print(f"\n[seed {seed}]")
            t0 = time.time()
            wf = build_workflow(PROMPT, seed)
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
                outpath = OUTPUT_DIR / f"3500_seed{seed}.png"
                outpath.write_bytes(r.content)
                print(f"  saved {outpath.name} ({elapsed:.1f}s)")
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
