"""Render trucks at 5 angles (-30, -15, 0, +15, +30) across 16 makes via
FLUX-Schnell + ControlNet, with multi-seed curation.

Canny references are generated per class:
  - 0deg:   existing renders/<class>.png  (head-on)
  - +30deg: existing renders_3q_mirrored/<class>.png (camera-left facing)
  - -30deg: horizontal mirror of +30deg
  - +15deg: 0deg head-on perspective-rotated by +15° (CSS-style)
  - -15deg: 0deg head-on perspective-rotated by -15°

Per (make, angle): 3 seeds rendered, user curates the cleanest in the
curation HTML.

Output: app/backend/static/trucks/renders_by_angle/<angle>/<make_slug>_seed<N>.png
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
import uuid
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image

# Reuse the perspective rotation helper from the engine
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_composite import perspective_rotate_css  # type: ignore[import-not-found]

COMFY = "http://100.85.94.57:8188"
REPO = Path(__file__).resolve().parents[1].parent
TRUCKS_HEADON = REPO / "app" / "backend" / "static" / "trucks" / "renders"
TRUCKS_3Q = REPO / "app" / "backend" / "static" / "trucks" / "renders_3q_mirrored"
OUT_BASE = REPO / "app" / "backend" / "static" / "trucks" / "renders_by_angle"

# Each entry = (slug, prompt phrase). Slugs are filename-safe.
# Trim-level adjectives ("Platinum", "Lariat") dropped to reduce text hallucination.
MAKES = {
    "mid-size": [
        ("toyota_tacoma",  "2024 Toyota Tacoma TRD pickup truck, silver paint, polished trim"),
        ("chevy_colorado", "2024 Chevrolet Colorado pickup truck, silver paint, chrome trim"),
        ("ford_ranger",    "2024 Ford Ranger pickup truck, silver paint, chrome trim"),
        ("jeep_liberty",   "2024 Jeep Liberty SUV, silver paint, chrome trim"),
        ("jeep_renegade",  "2024 Jeep Renegade SUV, silver paint, chrome trim"),
        ("chevy_tahoe",    "2024 Chevrolet Tahoe SUV, silver paint, chrome trim"),
    ],
    "1500": [
        ("chevy_1500",     "2024 Chevrolet Silverado 1500 pickup truck, white paint, chrome trim"),
        ("ford_f150",      "2024 Ford F-150 pickup truck, white pearl paint, chrome trim"),
        ("toyota_tundra",  "2024 Toyota Tundra pickup truck, white paint, chrome trim"),
        ("ram_1500",       "2024 Ram 1500 pickup truck, white paint, chrome trim"),
        ("nissan_titan",   "2024 Nissan Titan pickup truck, white paint, chrome trim"),
        ("gmc_1500",       "2024 GMC Sierra 1500 pickup truck, white paint, chrome trim"),
    ],
    "2500": [
        ("chevy_3500",     "2024 Chevrolet Silverado 3500 HD pickup truck, white paint, chrome trim"),
        ("ford_f250",      "2024 Ford F-250 Super Duty pickup truck, silver paint, chrome trim"),
        ("ram_2500",       "2024 Ram 2500 Heavy Duty pickup truck, white paint, chrome trim"),
        ("gmc_2500",       "2024 GMC Sierra 2500 HD pickup truck, white paint, chrome trim"),
    ],
}

# Angle name → method to generate canny ref for the class
ANGLES = ["-30deg", "-15deg", "0deg", "+15deg", "+30deg"]

PROMPT_TAIL = (
    ", full vehicle visible in frame, parked stationary, "
    "professional automotive product photography, seamless light grey paper backdrop, "
    "infinity cove studio, soft three-point lighting, "
    "shot on Canon EOS R5 with 85mm lens at f/4, "
    "ultra detailed, photorealistic, 8K, sharp focus, "
    "no people, no plow, no snow, no mud"
)
NEGATIVE = (
    "low quality, blurry, distorted, garbled text, watermark, badge overlay, "
    "people, snow, dirt, mud, motion blur, "
    "cropped, cartoon, illustration, painting"
)

SEEDS = [1337, 4242, 8888]
STRENGTH = 0.55  # slightly looser than 0.65 for shape variation across makes


def make_canny(img_path: Path, low: int = 50, high: int = 150) -> Image.Image:
    img = Image.open(img_path).convert("RGB")
    arr = np.array(img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, low, high)
    return Image.fromarray(np.stack([edges, edges, edges], axis=-1))


def get_class_for_make(make_slug: str) -> str:
    for cls, makes in MAKES.items():
        if any(slug == make_slug for slug, _ in makes):
            return cls
    return "1500"


def build_canny_for_angle(cls: str, angle_name: str) -> Image.Image:
    """Generate a canny reference for the given (class, angle)."""
    headon_src = TRUCKS_HEADON / f"{cls}.png"
    threeq_src = TRUCKS_3Q / f"{cls}.png"

    if angle_name == "0deg":
        return make_canny(headon_src)
    if angle_name == "+30deg":
        return make_canny(threeq_src)
    if angle_name == "-30deg":
        # Mirror the +30 canny
        return make_canny(threeq_src).transpose(Image.FLIP_LEFT_RIGHT)
    if angle_name == "+15deg" or angle_name == "-15deg":
        # Perspective-rotate the head-on truck IMAGE (not canny) by ±15°,
        # then run canny on the rotated image. Better edges than rotating
        # canny itself.
        deg = 15 if angle_name == "+15deg" else -15
        img = Image.open(headon_src).convert("RGB")
        W, H = img.size
        rotated, _, _ = perspective_rotate_css(
            img.convert("RGBA"), deg, anchor_x=W / 2, anchor_y=H / 2, perspective_d=900
        )
        # Convert back to RGB and run canny
        rgb = Image.new("RGB", rotated.size, (200, 200, 200))
        rgb.paste(rotated, mask=rotated.split()[-1])
        return make_canny_pil(rgb)
    raise ValueError(f"unknown angle: {angle_name}")


def make_canny_pil(img: Image.Image, low: int = 50, high: int = 150) -> Image.Image:
    arr = np.array(img.convert("RGB"))
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
            "images": ["8", 0], "filename_prefix": "flux_cn_multi"}},
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

    # Pre-generate and upload all 15 canny refs (3 classes × 5 angles)
    print("Generating + uploading canny refs...")
    canny_uploads: dict[tuple[str, str], str] = {}  # (cls, angle) -> uploaded name
    with httpx.Client() as client:
        for cls in MAKES.keys():
            for angle in ANGLES:
                canny = build_canny_for_angle(cls, angle)
                # save locally for inspection
                debug_dir = OUT_BASE / "_canny_refs"
                debug_dir.mkdir(parents=True, exist_ok=True)
                canny.save(debug_dir / f"{cls}_{angle.replace('+','p').replace('-','m')}.png")
                uploaded = upload_pil(client, canny, f"canny_{cls}_{angle}.png")
                canny_uploads[(cls, angle)] = uploaded
                print(f"  {cls} @ {angle}: {uploaded}")

        # Render each (make, angle, seed)
        n_total = sum(len(makes) for makes in MAKES.values()) * len(ANGLES) * len(SEEDS)
        n_done = 0
        t_start = time.time()

        for cls, makes in MAKES.items():
            for slug, vehicle_phrase in makes:
                for angle in ANGLES:
                    out_dir = OUT_BASE / angle
                    out_dir.mkdir(parents=True, exist_ok=True)
                    canny_name = canny_uploads[(cls, angle)]
                    for seed in SEEDS:
                        n_done += 1
                        out_path = out_dir / f"{slug}_seed{seed}.png"
                        if out_path.exists():
                            print(f"  [{n_done}/{n_total}] {slug}@{angle}/seed{seed}: skip")
                            continue
                        t = time.time()
                        wf = build_workflow(
                            canny_name, vehicle_phrase + PROMPT_TAIL, seed, STRENGTH
                        )
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
                            print(f"  [{n_done}/{n_total}] {slug}@{angle}/seed{seed}.png "
                                  f"({len(r.content):,}B, {time.time()-t:.1f}s)")
                            break

    print(f"\nDone in {time.time()-t_start:.1f}s. Output: {OUT_BASE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
