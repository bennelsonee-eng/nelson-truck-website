"""FLUX-Schnell test render — single F-150 to compare against Wan 2.2 Turbo.

FLUX-Schnell is 4-step distilled, modern T2I, generally considered the SOTA
open T2I as of Apr 2026.  Goal: see if FLUX produces noticeably prettier
truck imagery than the Wan 2.2 5B Turbo baseline.

Talks to ComfyUI on the llama via SSH-tunneled localhost API.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx


COMFY = "http://127.0.0.1:8188"
OUTPUT_DIR = Path("/tmp/flux_output")

PROMPT = (
    "professional automotive product photography, 2024 Ford F-150 XLT pickup "
    "truck, white pearl paint, polished chrome trim, front three-quarter view, "
    "30-degree angle from front, drivers side and front grille both visible, "
    "full vehicle in frame, seamless grey paper backdrop, infinity cove studio, "
    "soft three-point lighting, shot on Canon EOS R5 with 85mm lens at f/4, "
    "ultra detailed, photorealistic, 8K, sharp focus, no people, parked"
)


def build_workflow(seed: int = 42) -> dict:
    """ComfyUI native FLUX-Schnell workflow.  No CFG (Schnell is distilled),
    4 steps, simple scheduler.  1024x576 = 16:9 to match Wan output for
    apples-to-apples comparison."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "flux1-schnell-fp8.safetensors",
            "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux",
            "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "flux-vae-bf16.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": PROMPT}},
        # Schnell is distilled — empty conditioning works as null negative
        "5": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": ""}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {
            "width": 1024, "height": 576, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["4", 0],
            "negative": ["5", 0],
            "latent_image": ["6", 0],
            "seed": seed,
            "steps": 4,
            "cfg": 1.0,           # Schnell uses cfg=1 (effectively no CFG)
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {
            "samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": "flux_truck_test"}},
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
    with httpx.Client() as client:
        print(f"Rendering FLUX-Schnell: 2024 Ford F-150 (1024x576, 4 steps)...")
        t0 = time.time()
        result = queue_and_wait(client, build_workflow())
        print(f"  done in {time.time() - t0:.1f}s")

        for node_output in result.get("outputs", {}).values():
            for img in node_output.get("images", []):
                url = (
                    f"{COMFY}/view?filename={img['filename']}"
                    f"&subfolder={img.get('subfolder','')}&type=output"
                )
                r = client.get(url, timeout=60.0)
                outpath = OUTPUT_DIR / "1500_flux.png"
                outpath.write_bytes(r.content)
                print(f"  saved {outpath} ({len(r.content):,} bytes)")
                return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
