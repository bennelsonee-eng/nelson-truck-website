"""Render 6 truck classes at 2 angle buckets via FLUX-Schnell + ControlNet.

Canny reference sources:
  - 0°  (head-on):       app/backend/static/trucks/renders/<class>.png
  - 30° (three-quarter): app/backend/static/trucks/renders_3q_mirrored/<class>.png

For each (class, angle): render 3 seeds and let user curate the cleanest.

Output: app/backend/static/trucks/renders_by_angle/<angle>/<class>_seed<N>.png
"""

from __future__ import annotations

import io
import json
import sys
import time
import uuid
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image

COMFY = "http://100.85.94.57:8188"
REPO = Path(__file__).resolve().parents[1].parent
TRUCKS_HEADON = REPO / "app" / "backend" / "static" / "trucks" / "renders"
TRUCKS_3Q = REPO / "app" / "backend" / "static" / "trucks" / "renders_3q_mirrored"
OUT_BASE = REPO / "app" / "backend" / "static" / "trucks" / "renders_by_angle"

# (class, angle, source_dir, prompt_vehicle)
TRUCKS = {
    "mid-size": "2024 Toyota Tacoma TRD pickup truck, silver paint, polished chrome trim",
    "1500":     "2024 Ford F-150 XLT pickup truck, white pearl paint, polished chrome trim",
    "2500":     "2024 Ford F-250 Super Duty Lariat pickup truck, silver paint, chrome trim",
    "3500":     "2024 Ford F-350 Super Duty Platinum pickup truck dual rear wheels, white paint, chrome trim",
    "4500":     "2024 Ford F-450 Super Duty XLT chassis cab commercial truck flatbed, white paint",
    "5500":     "2024 Ford F-550 Super Duty XL chassis cab commercial truck, white paint, large grille",
}

ANGLES = {
    "0deg":  TRUCKS_HEADON,
    "30deg": TRUCKS_3Q,
}

PROMPT_TAIL = (
    ", full vehicle visible in frame, parked stationary, "
    "professional automotive product photography, seamless light grey paper backdrop, "
    "infinity cove studio, soft three-point lighting, "
    "shot on Canon EOS R5 with 85mm lens at f/4, "
    "ultra detailed, photorealistic, 8K, sharp focus, "
    "no people, no plow, no snow, no mud"
)
NEGATIVE = (
    "low quality, blurry, distorted, text, watermark, badge overlay, "
    "people, snow, dirt, mud, motion blur, "
    "cropped, cartoon, illustration, painting"
)

SEEDS = [1337, 4242, 8888]
STRENGTH = 0.65


def make_canny(img_path: Path, low: int = 50, high: int = 150) -> Image.Image:
    img = Image.open(img_path).convert("RGB")
    arr = np.array(img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, low, high)
    return Image.fromarray(np.stack([edges, edges, edges], axis=-1))


def upload_pil(client: httpx.Client, img: Image.Image, name: str) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    files = {"image": (name, buf, "image/png")}
    data = {"overwrite": "true"}
    r = client.post(f"{COMFY}/upload/image", files=files, data=data, timeout=60.0)
    r.raise_for_status()
    return r.json()["name"]


def build_workflow(canny_filename: str, prompt: str, seed: int, strength: float) -> dict:
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
        "10": {"class_type": "ControlNetLoader", "inputs": {
            "control_net_name": "flux-controlnet-union.safetensors"}},
        "11": {"class_type": "SetUnionControlNetType", "inputs": {
            "control_net": ["10", 0],
            "type": "canny/lineart/anime_lineart/mlsd"}},
        "12": {"class_type": "LoadImage", "inputs": {"image": canny_filename}},
        "13": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["4", 0], "negative": ["5", 0],
            "control_net": ["11", 0], "image": ["12", 0], "vae": ["3", 0],
            "strength": strength, "start_percent": 0.0, "end_percent": 0.95}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {
            "width": 1024, "height": 576, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["13", 0], "negative": ["13", 1],
            "latent_image": ["6", 0],
            "seed": seed, "steps": 4, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": "flux_cn_lineup"}},
    }


def queue_and_wait(client: httpx.Client, workflow: dict) -> dict:
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
    r = client.post(f"{COMFY}/prompt", json=payload, timeout=30.0)
    if r.status_code >= 400:
        print(json.dumps(r.json(), indent=2))
        r.raise_for_status()
    prompt_id = r.json()["prompt_id"]
    while True:
        time.sleep(2)
        h = client.get(f"{COMFY}/history/{prompt_id}", timeout=15.0).json()
        if prompt_id in h and h[prompt_id].get("status", {}).get("completed"):
            return h[prompt_id]


def main() -> int:
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    n_total = len(TRUCKS) * len(ANGLES) * len(SEEDS)
    n_done = 0
    t_start = time.time()

    with httpx.Client() as client:
        for cls, vehicle in TRUCKS.items():
            for angle_name, src_dir in ANGLES.items():
                src_png = src_dir / f"{cls}.png"
                if not src_png.exists():
                    print(f"  ! missing {src_png}, skip")
                    n_done += len(SEEDS)
                    continue
                # Build canny once per (class, angle)
                canny = make_canny(src_png)
                canny_name = f"canny_{cls}_{angle_name}.png"
                uploaded = upload_pil(client, canny, canny_name)

                out_dir = OUT_BASE / angle_name
                out_dir.mkdir(parents=True, exist_ok=True)
                for seed in SEEDS:
                    n_done += 1
                    out_path = out_dir / f"{cls}_seed{seed}.png"
                    if out_path.exists():
                        print(f"  [{n_done}/{n_total}] {angle_name}/{cls}/seed{seed}: exists, skip")
                        continue
                    t = time.time()
                    wf = build_workflow(uploaded, vehicle + PROMPT_TAIL, seed, STRENGTH)
                    result = queue_and_wait(client, wf)
                    for node_output in result.get("outputs", {}).values():
                        imgs = node_output.get("images", [])
                        if not imgs:
                            continue
                        first = imgs[0]
                        url = (
                            f"{COMFY}/view?filename={first['filename']}"
                            f"&subfolder={first.get('subfolder','')}&type=output"
                        )
                        r = client.get(url, timeout=120.0)
                        out_path.write_bytes(r.content)
                        print(f"  [{n_done}/{n_total}] saved {angle_name}/{cls}/seed{seed}.png "
                              f"({len(r.content):,}B, {time.time()-t:.1f}s)")
                        break

    print(f"\n{n_total} renders done in {time.time()-t_start:.1f}s -> {OUT_BASE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
