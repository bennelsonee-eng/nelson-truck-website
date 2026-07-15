"""Render a Western MVP3 V-plow at multiple orientations via FLUX-Schnell.

Goal: a clean plow reference image with the camera positioned correctly to
composite onto our existing 3/4 truck render (passenger-side close to camera,
nose pointing upper-left).

For that truck angle, the plow should be shot from the operator's-RIGHT
viewpoint — meaning we see the operator-LEFT blade more prominently in the
foreground (camera-near), with WESTERN branding correctly oriented on it.

We render 3 angles × 4 seeds = 12 candidates so we can pick the best one
that pairs with our truck.

Output: /tmp/flux_plow_orientations/<angle>_seed<seed>.png
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx


COMFY = "http://127.0.0.1:8188"
OUTPUT_DIR = Path("/tmp/flux_plow_orientations")

# Common scaffolding — clean studio shot of the plow on white
COMMON_TAIL = (
    ", professional automotive product photography, isolated on pure white "
    "studio backdrop, infinity cove, soft three-point lighting, clean, "
    "sharp focus, no truck visible, no truck behind plow, no truck in "
    "background, plow alone, studio shot, ultra detailed, photorealistic, "
    "8K, no people, no snow"
)
NEGATIVE = (
    "low quality, blurry, distorted, text artifacts, garbled letters, "
    "truck attached, truck behind, truck visible, vehicle, person, snow, "
    "dirt, mud, motion blur, lifestyle, road, parking lot, trees, "
    "buildings, multiple plows, cropped, cartoon, illustration, painting"
)

ANGLES = {
    # Head-on — symmetric, works for any truck angle
    "headon": (
        "Western MVP3 stainless steel V-plow, contractor grade snow plow, "
        "head-on front view, both blade wings angled forward in scoop "
        "position, V-pivot column visible center, snow markers extending "
        "up vertically on each blade tip, clean stainless finish reflecting "
        "studio light, WESTERN logo branding centered on right blade panel, "
        "MVP3 badge below logo, black cutting edge along bottom"
    ),
    # 3/4 from operator's RIGHT — pairs with passenger-side-close truck
    "op_right": (
        "Western MVP3 stainless steel V-plow, contractor grade snow plow, "
        "front three-quarter view from operator-right side, camera 25 "
        "degrees off centerline to the right, both blade wings angled "
        "forward in scoop position, V-pivot column visible center, snow "
        "markers extending up, the operator's left blade prominent in "
        "foreground with WESTERN logo branding readable on its outer face, "
        "operator's right blade extending back and partially in profile, "
        "clean stainless finish, black cutting edge along bottom"
    ),
    # 3/4 from operator's LEFT — pairs with driver-side-close truck (alt)
    "op_left": (
        "Western MVP3 stainless steel V-plow, contractor grade snow plow, "
        "front three-quarter view from operator-left side, camera 25 "
        "degrees off centerline to the left, both blade wings angled "
        "forward in scoop position, V-pivot column visible center, snow "
        "markers extending up, the operator's right blade prominent in "
        "foreground with WESTERN logo branding readable on its outer face, "
        "clean stainless finish, black cutting edge along bottom"
    ),
}

SEEDS = [42, 1337, 8888, 31415]


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
            "width": 1280, "height": 720, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["4", 0],
            "negative": ["5", 0],
            "latent_image": ["6", 0],
            "seed": seed, "steps": 4, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
        }},
        "8": {"class_type": "VAEDecode", "inputs": {
            "samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": "flux_plow_orientation"}},
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
        for angle_name, vehicle_phrase in ANGLES.items():
            for seed in SEEDS:
                print(f"\n[{angle_name} / seed {seed}]")
                t0 = time.time()
                wf = build_workflow(vehicle_phrase + COMMON_TAIL, seed)
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
                    outpath = OUTPUT_DIR / f"{angle_name}_seed{seed}.png"
                    outpath.write_bytes(r.content)
                    print(f"  saved {outpath.name} ({elapsed:.1f}s)")
                    break
    return 0


if __name__ == "__main__":
    sys.exit(main())
