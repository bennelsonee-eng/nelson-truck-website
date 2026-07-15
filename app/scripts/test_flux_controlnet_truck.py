"""Test FLUX + ControlNet pipeline on llama: render a truck conditioned by
canny edges from an existing truck render.

If this works, we'll batch out 18 trucks (6 classes x 3 angles) using
canny references for each angle.

The test:
  1. Take an existing 30deg-mirrored 2500 truck PNG
  2. Build a canny edge map of it locally
  3. Upload both source + canny to ComfyUI
  4. Run FLUX-Schnell + ControlNet conditioned on the canny
  5. Save result. If it preserves the truck's pose/silhouette, pipeline works.
"""

from __future__ import annotations

import io
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

try:
    import cv2  # type: ignore[import-not-found]
except ImportError:
    cv2 = None  # we'll fall back to PIL FIND_EDGES if cv2 missing

COMFY = "http://100.85.94.57:8188"
REPO = Path(__file__).resolve().parents[1].parent
TRUCK_SRC = REPO / "app" / "backend" / "static" / "trucks" / "renders_3q_mirrored" / "2500.png"
OUT_DIR = REPO / "wan_test_output" / "flux_controlnet_test"

PROMPT_2500 = (
    "2024 Ford F-250 Super Duty Lariat pickup truck, silver paint, chrome trim, "
    "front three-quarter view, full vehicle visible in frame, parked stationary, "
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

# Union ControlNet "control type" enum — 0=canny, 1=tile, 2=depth, 3=blur,
# 4=pose, 5=gray, 6=low quality. We use canny.
UNION_TYPE_CANNY = 0


def make_canny(img_path: Path, low_threshold: int = 50, high_threshold: int = 150) -> Image.Image:
    """Generate canny edges from an image."""
    img = Image.open(img_path).convert("RGB")
    arr = np.array(img)
    if cv2 is not None:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, low_threshold, high_threshold)
        # Make 3-channel for ControlNet
        return Image.fromarray(np.stack([edges, edges, edges], axis=-1))
    # PIL fallback (worse quality but works)
    from PIL import ImageFilter
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    arr = np.array(edges)
    return Image.fromarray(np.stack([arr, arr, arr], axis=-1))


def upload_image(client: httpx.Client, src_path: Path, name: str) -> str:
    with src_path.open("rb") as f:
        files = {"image": (name, f, "image/png")}
        data = {"overwrite": "true"}
        r = client.post(f"{COMFY}/upload/image", files=files, data=data, timeout=60.0)
    r.raise_for_status()
    return r.json()["name"]


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
        # Models
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "flux1-schnell-fp8.safetensors", "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "flux-vae-bf16.safetensors"}},
        # Prompts
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": NEGATIVE}},
        # ControlNet
        "10": {"class_type": "ControlNetLoader", "inputs": {
            "control_net_name": "flux-controlnet-union.safetensors"}},
        "11": {"class_type": "SetUnionControlNetType", "inputs": {
            "control_net": ["10", 0],
            "type": "canny/lineart/anime_lineart/mlsd",
        }},
        "12": {"class_type": "LoadImage", "inputs": {"image": canny_filename}},
        "13": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["4", 0],
            "negative": ["5", 0],
            "control_net": ["11", 0],
            "image": ["12", 0],
            "vae": ["3", 0],
            "strength": strength,
            "start_percent": 0.0,
            "end_percent": 0.95,
        }},
        # Sampling
        "6": {"class_type": "EmptyLatentImage", "inputs": {
            "width": 1024, "height": 576, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["13", 0],
            "negative": ["13", 1],
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
            "images": ["8", 0], "filename_prefix": "flux_cn_test"}},
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
        if prompt_id in h:
            entry = h[prompt_id]
            if entry.get("status", {}).get("completed"):
                return entry
            err = entry.get("status", {}).get("status_str")
            if err == "error":
                print("PROMPT ERROR:")
                print(json.dumps(entry.get("status"), indent=2))
                raise RuntimeError("ComfyUI prompt failed")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Building canny from {TRUCK_SRC.name}...")
    canny = make_canny(TRUCK_SRC)
    canny_path = OUT_DIR / "canny_2500.png"
    canny.save(canny_path)
    print(f"  saved {canny_path}")

    with httpx.Client() as client:
        canny_name = upload_pil(client, canny, "canny_2500_test.png")
        print(f"  uploaded canny as {canny_name}")

        # Test at strength=0.6 (moderate ControlNet influence)
        for strength in [0.4, 0.6, 0.8]:
            for seed in [1337, 4242]:
                print(f"\nrendering strength={strength} seed={seed}...")
                t = time.time()
                wf = build_workflow(canny_name, PROMPT_2500, seed, strength)
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
                    out = OUT_DIR / f"2500_cn_str{int(strength*100)}_seed{seed}.png"
                    out.write_bytes(r.content)
                    elapsed = time.time() - t
                    print(f"  saved {out.name} ({len(r.content):,}B, {elapsed:.1f}s)")
                    break

    print(f"\nDone. Compare results in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
