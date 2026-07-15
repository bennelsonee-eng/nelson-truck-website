"""V6 truck render via img2img, going the OTHER direction.

V5 started from v3 0deg head-on and tried to add rotation -> failed
(geometry didn't shift). V6 starts from v2 ~30deg renders and tries to
pull rotation BACK toward ~20deg, which should be a smaller deviation
that FLUX-Schnell can handle.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

COMFY = "http://100.85.94.57:8188"
OUTPUT_DIR = Path(__file__).resolve().parents[1].parent / "wan_test_output" / "flux_truck_img2img_v6"
INPUT_DIR = Path(__file__).resolve().parents[1].parent / "app" / "backend" / "static" / "trucks" / "renders_3q"

PULL_FRONTAL_PROMPT = (
    "2024 Ford F-250 Super Duty Lariat pickup truck, silver paint, chrome trim, "
    "predominantly frontal view, mostly head-on with only slight rotation, "
    "front of vehicle dominant in the frame, both headlights nearly equally visible, "
    "stationary parked vehicle, full vehicle visible in frame, "
    "professional automotive product photography, seamless light grey paper backdrop, "
    "infinity cove studio, soft three-point lighting, "
    "ultra detailed, photorealistic, 8K, sharp focus, no people, no plow"
)
NEGATIVE = (
    "low quality, blurry, distorted, text, watermark, badge overlay, "
    "people, snow, dirt, mud, motion blur, "
    "side view, profile view, full passenger side visible, full driver side visible, "
    "more than 25 degrees rotation, aggressive perspective, full vehicle profile"
)

DENOISE_VALUES = [0.40, 0.50, 0.60, 0.70, 0.80]
TARGETS = ["2500.png", "1500.png", "3500.png"]


def upload_image(client: httpx.Client, src_path: Path) -> str:
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
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux-vae-bf16.safetensors"}},
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
            "images": ["8", 0], "filename_prefix": "flux_img2img_v6"}},
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
        for src_name in TARGETS:
            src = INPUT_DIR / src_name
            if not src.exists():
                print(f"  ! missing input {src}")
                continue
            try:
                uploaded = upload_image(client, src)
                print(f"  uploaded {src.name} -> {uploaded}")
            except Exception as e:
                print(f"  ! upload failed: {e}")
                continue
            for denoise in DENOISE_VALUES:
                outpath = OUTPUT_DIR / f"{src.stem}_denoise{int(denoise*100)}.png"
                if outpath.exists():
                    print(f"  skip {outpath.name}")
                    continue
                t = time.time()
                wf = build_workflow(uploaded, PULL_FRONTAL_PROMPT, 1337, denoise)
                try:
                    result = queue_and_wait(client, wf)
                except Exception as e:
                    print(f"  ! KSampler failed: {e}")
                    continue
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
                    n += 1
                    break
    print(f"\n{n} renders in {time.time()-t0:.1f}s -> {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
