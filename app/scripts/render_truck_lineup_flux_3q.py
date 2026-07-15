"""Render all 6 truck classes at SUBTLE front-3/4 angle via FLUX-Schnell.

Path A v2 — first 3/4 lineup (30° rotation) had angle mismatch with the plow
marketing-shot convention (~10–20° rotation).  This v2 dials the truck back
to ~15° rotation so the truck and plow share the same perspective when
composited.

Same studio scaffolding, only the camera angle changes:
  v1 (too aggressive): "front three-quarter view, camera 30 degrees off centerline"
  v2 (this file):      "subtle three-quarter view, camera 15 degrees off centerline,
                        nearly head-on with slight rotation"

We render 2 seeds per class (1337, 8888) so we can pick the best framing.

Output: /tmp/flux_lineup_3q_output/<class>_seed<seed>.png  (overwrites v1)
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx


COMFY = "http://127.0.0.1:8188"
OUTPUT_DIR = Path("/tmp/flux_lineup_3q_v2_output")

COMMON_TAIL = (
    ", subtle front three-quarter view, camera 15 degrees off centerline, "
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
    "extreme angle, aggressive rotation, full side view"
)

TRUCKS = {
    "mid-size": "2024 Toyota Tacoma TRD pickup truck, silver paint, polished chrome trim",
    "1500":     "2024 Ford F-150 XLT pickup truck, white pearl paint, polished chrome trim",
    "2500":     "2024 Ford F-250 Super Duty Lariat pickup truck, silver paint, chrome trim",
    "3500":     "2024 Ford F-350 Super Duty Platinum pickup truck dual rear wheels, white paint, chrome trim",
    "4500":     "2024 Ford F-450 Super Duty XLT chassis cab commercial truck flatbed, white paint",
    "5500":     "2024 Ford F-550 Super Duty XL chassis cab commercial truck, white paint, large grille",
}
SEEDS = [1337, 8888]


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
            "images": ["8", 0], "filename_prefix": "flux_3q_lineup_v2"}},
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
    total_t0 = time.time()
    with httpx.Client() as client:
        for cls, vehicle_phrase in TRUCKS.items():
            for seed in SEEDS:
                prompt = vehicle_phrase + COMMON_TAIL
                print(f"\n[{cls} / seed {seed}]")
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
                    outpath = OUTPUT_DIR / f"{cls}_seed{seed}.png"
                    outpath.write_bytes(r.content)
                    print(f"  saved {outpath.name} ({len(r.content):,} bytes, {elapsed:.1f}s)")
                    break
    total = time.time() - total_t0
    print(f"\n{len(TRUCKS) * len(SEEDS)} 3/4 renders saved to {OUTPUT_DIR} in {total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
