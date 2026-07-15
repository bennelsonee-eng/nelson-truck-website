"""Render trucks at a TIGHTER ~15deg rotation via FLUX-Schnell on llama.

v3 changes vs v2:
  * Targets llama at 100.85.94.57:8188 (was localhost)
  * Inverts the prompt strategy: emphasize FRONTAL with hint of rotation,
    instead of "three-quarter view" (which FLUX maps to 30-45deg).
  * 5 seeds per truck class for curation (was 2)
  * Outputs to local Windows path under wan_test_output/

Why the prompt inversion: v2 asked for "subtle three-quarter view, camera
15 degrees off centerline" but the rendered trucks landed near 30deg
because "three-quarter" is the dominant signal in FLUX's training data.
v3 reframes as "predominantly frontal" with a small "hint" of rotation.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

COMFY = "http://100.85.94.57:8188"
OUTPUT_DIR = Path(__file__).resolve().parents[1].parent / "wan_test_output" / "flux_truck_15deg_v3"

# Target ~15deg rotation, both headlights centered, only hint of passenger fender
COMMON_TAIL = (
    ", predominantly frontal view, near head-on with only a slight 15 degree rotation, "
    "front of vehicle dominant in the frame, both headlights equally visible and centered, "
    "full grille fully visible and centered, only a small hint of passenger side fender, "
    "front bumper centered horizontally, minimal side perspective, "
    "stationary parked vehicle, full vehicle visible in frame, "
    "professional automotive product photography, seamless light grey paper backdrop, "
    "infinity cove studio, soft three-point lighting, shot on Canon EOS R5 with 85mm lens at f/4, "
    "ultra detailed, photorealistic, 8K, sharp focus, "
    "no people, no plow, no snow, no mud"
)
NEGATIVE = (
    "low quality, blurry, distorted, text, watermark, logo overlay, badge overlay, "
    "people, snow, dirt, mud, motion blur, lifestyle, road, parking lot, trees, "
    "buildings, multiple vehicles, cropped, cartoon, illustration, painting, "
    "snow plow attached, plow blade, shovel, "
    "three quarter view, three-quarter view, 3/4 view, profile view, side view, rear view, "
    "full passenger side visible, full driver side visible, more than 25 degrees rotation, "
    "aggressive perspective, full vehicle profile, sharply angled, exaggerated perspective"
)

TRUCKS = {
    "mid-size": "2024 Toyota Tacoma TRD pickup truck, silver paint, polished chrome trim",
    "1500":     "2024 Ford F-150 XLT pickup truck, white pearl paint, polished chrome trim",
    "2500":     "2024 Ford F-250 Super Duty Lariat pickup truck, silver paint, chrome trim",
    "3500":     "2024 Ford F-350 Super Duty Platinum pickup truck dual rear wheels, white paint, chrome trim",
    "4500":     "2024 Ford F-450 Super Duty XLT chassis cab commercial truck flatbed, white paint",
    "5500":     "2024 Ford F-550 Super Duty XL chassis cab commercial truck, white paint, large grille",
}
SEEDS = [1337, 8888, 4242, 2026, 17171]


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
            "images": ["8", 0], "filename_prefix": "flux_15deg_v3"}},
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
    n_total = len(TRUCKS) * len(SEEDS)
    n_done = 0
    with httpx.Client() as client:
        for cls, vehicle_phrase in TRUCKS.items():
            for seed in SEEDS:
                n_done += 1
                outpath = OUTPUT_DIR / f"{cls}_seed{seed}.png"
                if outpath.exists():
                    print(f"[{n_done}/{n_total}] {cls} / seed {seed}: exists, skip")
                    continue
                prompt = vehicle_phrase + COMMON_TAIL
                print(f"[{n_done}/{n_total}] {cls} / seed {seed}: rendering...")
                t0 = time.time()
                wf = build_workflow(prompt, seed)
                result = queue_and_wait(client, wf)
                elapsed = time.time() - t0
                got = False
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
                    outpath.write_bytes(r.content)
                    print(f"  saved {outpath.name} ({len(r.content):,} bytes, {elapsed:.1f}s)")
                    got = True
                    break
                if not got:
                    print(f"  WARNING no output found for {cls}/seed{seed}")
    total = time.time() - total_t0
    print(f"\n{n_total} renders saved to {OUTPUT_DIR} in {total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
