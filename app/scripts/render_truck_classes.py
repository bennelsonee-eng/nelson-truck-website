"""Render all 6 truck classes for the snow plow configurator (Snow E-2).

Uses Wan 2.2 5B Turbo in T2V mode — first frame of a 17-frame T2V output is
essentially T2I, much higher quality than the I2V camera-orbit attempt.

Same prompt scaffolding for every class so backdrop / lighting / angle are
visually consistent.  Same seed too — that anchors the lighting + composition
even when the truck identity changes.

Output:
    /tmp/wan_t2v_output/{class_id}.png   (on llama)
    -> scp'd back to:
    app/backend/static/trucks/renders/{class_id}.png

Run on llama:
    source ~/wan-venv/bin/activate && python /tmp/test_wan_t2v_classes.py
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx


COMFY = "http://127.0.0.1:8188"
OUTPUT_DIR = Path("/tmp/wan_t2v_output")

# Locked prompt scaffolding so all 6 trucks share backdrop / lighting / angle.
# - "front three-quarter view": consistent camera angle for the plow overlay
# - "white pearl paint": consistent body color
# - "seamless grey paper backdrop, infinity cove": consistent BG (good for
#   white-mask transparency extraction afterward)
SCAFFOLD = (
    "{vehicle}, {year} model year, white pearl paint, polished chrome trim, "
    "front three-quarter view, 30-degree angle from front, drivers side and "
    "front grille both visible, full vehicle in frame, no cropping, "
    "professional automotive product photography, studio lighting, "
    "seamless grey paper backdrop, infinity cove, centered composition, "
    "sharp focus, no people, no plow, no dirt, parked, stationary"
)

NEGATIVE = (
    "low quality, blurry, distorted, text, watermark, logo, badge, "
    "people, snow on ground, dirt, mud, motion blur, lifestyle, road, "
    "trees, buildings, street, parking lot, multiple vehicles, cropped"
)

TRUCK_CLASSES = [
    ("mid-size", "Toyota Tacoma TRD Sport pickup truck", 2024),
    ("1500",     "Ford F-150 XLT pickup truck",          2024),
    ("2500",     "Ford F-250 Super Duty pickup truck",   2024),
    ("3500",     "Ford F-350 Super Duty dual rear wheel pickup truck", 2024),
    ("4500",     "Ford F-450 chassis cab commercial truck with bare frame behind cab", 2024),
    ("5500",     "Ford F-550 chassis cab commercial truck with bare frame behind cab", 2024),
]

# Same seed for all 6 anchors lighting/composition; truck identity comes from
# the prompt itself.
SEED = 42


def build_t2v_workflow(positive_prompt: str, seed: int) -> dict:
    return {
        "3": {"class_type": "WanVideoVAELoader", "inputs": {
            "model_name": "Wan2_2_VAE_bf16.safetensors", "precision": "bf16"}},
        "4": {"class_type": "WanVideoModelLoader", "inputs": {
            "model": "Wan2_2-TI2V-5B-Turbo_bf16.safetensors",
            "base_precision": "bf16", "quantization": "disabled",
            "load_device": "main_device", "attention_mode": "sdpa"}},
        "5": {"class_type": "LoadWanVideoT5TextEncoder", "inputs": {
            "model_name": "umt5-xxl-enc-fp8_e4m3fn.safetensors",
            "precision": "bf16", "load_device": "offload_device", "quantization": "disabled"}},
        "6": {"class_type": "WanVideoTextEncode", "inputs": {
            "t5": ["5", 0], "model_to_offload": ["4", 0],
            "positive_prompt": positive_prompt, "negative_prompt": NEGATIVE,
            "force_offload": True}},
        "8": {"class_type": "WanVideoEmptyEmbeds", "inputs": {
            "width": 1024, "height": 576, "num_frames": 17}},
        "9": {"class_type": "WanVideoSampler", "inputs": {
            "model": ["4", 0], "image_embeds": ["8", 0], "text_embeds": ["6", 0],
            "steps": 4, "cfg": 1.0, "shift": 5.0, "seed": seed,
            "force_offload": True, "scheduler": "flowmatch_distill",
            "riflex_freq_index": 0, "denoise_strength": 1.0,
            "batched_cfg": "", "rope_function": "comfy",
            "start_step": 0, "end_step": -1, "add_noise_to_samples": ""}},
        "10": {"class_type": "WanVideoDecode", "inputs": {
            "vae": ["3", 0], "samples": ["9", 0],
            "enable_vae_tiling": True, "tile_x": 272, "tile_y": 272,
            "tile_stride_x": 144, "tile_stride_y": 128, "normalization": "default"}},
        "11": {"class_type": "SaveImage", "inputs": {
            "images": ["10", 0], "filename_prefix": "truck_class"}},
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
        for class_id, vehicle, year in TRUCK_CLASSES:
            prompt = SCAFFOLD.format(vehicle=vehicle, year=year)
            print(f"\n[{class_id}] {vehicle}")
            t0 = time.time()
            wf = build_t2v_workflow(prompt, SEED)
            result = queue_and_wait(client, wf)
            print(f"  rendered in {time.time() - t0:.1f}s")

            # Take only frame 1 (first frame of the 17-frame T2V output)
            saved = False
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
                outpath = OUTPUT_DIR / f"{class_id}.png"
                outpath.write_bytes(r.content)
                print(f"  saved {outpath}  ({len(r.content):,} bytes)")
                saved = True
                break
            if not saved:
                print(f"  WARN: no output for {class_id}")

    print(f"\nAll 6 truck classes rendered to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
