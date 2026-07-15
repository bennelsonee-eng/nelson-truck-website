"""V5 truck render via img2img — start from a head-on render and rotate slightly.

FLUX-Schnell can't reliably hit ~20deg rotation via text prompts alone (v3
got 0deg, v4 got 30deg, neither lands at 20). img2img with moderate denoise
gives finer control: start from a 0deg head-on render, encode to latent,
partial-denoise with a "slight 3/4" prompt, decode. The starting image's
geometry biases FLUX so it can't snap all the way to 30deg.

Sweeps multiple denoise values for the 2500 truck first to find a sweet
spot. If a value works, it can be re-applied across the rest of the lineup.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

COMFY = "http://100.85.94.57:8188"
OUTPUT_DIR = Path(__file__).resolve().parents[1].parent / "wan_test_output" / "flux_truck_img2img_v5"

# Source: v3 head-on render (0deg) — we'll rotate toward ~20deg
INPUT_DIR = Path(__file__).resolve().parents[1].parent / "wan_test_output" / "flux_truck_15deg_v3"

# Prompt asking for slight rotation (assumes the input's geometry will bias)
ROTATE_PROMPT = (
    "2024 Ford F-250 Super Duty Lariat pickup truck, silver paint, chrome trim, "
    "shallow front-quarter view, slight rotation showing the front passenger fender, "
    "front passenger wheel just barely visible at the corner, "
    "stationary parked vehicle, full vehicle visible in frame, "
    "professional automotive product photography, seamless light grey paper backdrop, "
    "infinity cove studio, soft three-point lighting, "
    "ultra detailed, photorealistic, 8K, sharp focus, no people, no plow"
)
NEGATIVE = (
    "low quality, blurry, distorted, text, watermark, badge overlay, "
    "people, snow, dirt, mud, motion blur, "
    "perfectly head-on, dead front view, perfectly symmetric, "
    "side view, profile view, rear view, full side visible, "
    "more than 30 degrees rotation, exaggerated perspective"
)

# Sweep multiple denoise levels: lower = closer to input (less rotation),
# higher = more freedom (potentially more rotation)
DENOISE_VALUES = [0.40, 0.50, 0.55, 0.60, 0.65, 0.70]

# Try just the 2500 first across all denoise values, plus quick checks on
# the others at the most promising denoise level (0.55) to see if it generalizes.
TARGETS = [
    ("2500", "2500_seed1337.png"),
    ("2500", "2500_seed4242.png"),
    ("2500", "2500_seed17171.png"),
]


def upload_image(client: httpx.Client, src_path: Path) -> str:
    """Upload local image to ComfyUI's input dir, return the filename."""
    with src_path.open("rb") as f:
        files = {"image": (src_path.name, f, "image/png")}
        data = {"overwrite": "true"}
        r = client.post(f"{COMFY}/upload/image", files=files, data=data, timeout=30.0)
    r.raise_for_status()
    return r.json()["name"]


def build_workflow(input_filename: str, prompt: str, seed: int, denoise: float) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "flux1-schnell-fp8.safetensors", "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "flux-vae-bf16.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": NEGATIVE}},
        "10": {"class_type": "LoadImage", "inputs": {"image": input_filename}},
        "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["3", 0]}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["11", 0],
            "seed": seed, "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": denoise}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": "flux_img2img_v5"}},
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
    t0 = time.time()
    n = 0
    with httpx.Client() as client:
        for cls, src_name in TARGETS:
            src = INPUT_DIR / src_name
            if not src.exists():
                print(f"  ! missing input {src}")
                continue
            try:
                uploaded_name = upload_image(client, src)
                print(f"  uploaded {src.name} -> {uploaded_name}")
            except Exception as e:
                print(f"  ! upload failed for {src.name}: {e}")
                continue
            for denoise in DENOISE_VALUES:
                outpath = OUTPUT_DIR / f"{src.stem}_denoise{int(denoise*100)}.png"
                if outpath.exists():
                    print(f"  skip {outpath.name} (exists)")
                    continue
                seed = int(src.stem.split("seed")[1]) if "seed" in src.stem else 1337
                t = time.time()
                wf = build_workflow(uploaded_name, ROTATE_PROMPT, seed, denoise)
                try:
                    result = queue_and_wait(client, wf)
                except Exception as e:
                    print(f"  ! KSampler failed denoise={denoise}: {e}")
                    continue
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
                    print(f"  saved {outpath.name} (denoise={denoise}, {time.time()-t:.1f}s)")
                    got = True
                    n += 1
                    break
                if not got:
                    print(f"  ! no output denoise={denoise}")
    print(f"\n{n} renders in {time.time()-t0:.1f}s -> {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
