"""Re-rotate the 4 failed plows with stronger no-truck constraints.

Failures from previous run:
  - MYP-09275-EQP    (Lot Pro)   — Kontext added Chevy
  - WEST-HTS76-EQP   (HTS)       — added truck
  - SNOW-16020412-EQP (MD68II)   — added Silverado
  - SNOW-16020724-EQP (VXF85II)  — morphed shape entirely

Strategy:
  1. Restore from _v2_headon backup (revert canonical to head-on)
  2. Try multiple seeds with stronger no-truck prompt
  3. Pick best result per SKU
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import uuid
from pathlib import Path

import httpx
import numpy as np
from PIL import Image
from rembg import remove, new_session


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
WORK_DIR = REPO / "wan_test_output" / "redo_rotation"

COMFY = "http://100.85.94.57:8188"
KONTEXT_MODEL = "flux1-dev-kontext_fp8_scaled.safetensors"


FAILED_SKUS = [
    "MYP-09275-EQP",
    "WEST-HTS76-EQP",
    "SNOW-16020412-EQP",
    "SNOW-16020724-EQP",
]


# Stronger prompt with explicit no-truck language at the START
ROTATION_PROMPT = (
    "ABSOLUTELY NO TRUCK in the image. Show ONLY the snow plow alone. "
    "The plow is isolated on a pure white empty studio background with "
    "nothing else visible. No vehicle, no truck cab, no pickup, no GMC, "
    "no Chevy, no Ford, no headlights of any other vehicle. Just the plow. "
    "Reposition the camera to the operator-right side at slight 3/4 angle "
    "(about 25 degrees). Operator-left blade prominent in foreground. "
    "Keep all branding readable."
)


def build_workflow(input_filename: str, prompt: str, seed: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": KONTEXT_MODEL, "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "flux-vae-bf16.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {
            "image": input_filename, "upload": "image"}},
        "5": {"class_type": "VAEEncode", "inputs": {
            "pixels": ["4", 0], "vae": ["3", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": prompt}},
        "8": {"class_type": "FluxGuidance", "inputs": {
            "conditioning": ["7", 0], "guidance": 3.5}},  # higher guidance to follow prompt more strictly
        "6": {"class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["8", 0], "latent": ["5", 0]}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": ""}},
        "10": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["6", 0], "negative": ["9", 0],
            "latent_image": ["5", 0], "seed": seed,
            "steps": 25, "cfg": 1.0, "sampler_name": "euler",
            "scheduler": "simple", "denoise": 1.0}},
        "11": {"class_type": "VAEDecode", "inputs": {
            "samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {
            "images": ["11", 0], "filename_prefix": "kontext_redo"}},
    }


async def run_kontext(client: httpx.AsyncClient,
                      plow_image: Image.Image, sku: str, seed: int) -> Image.Image | None:
    buf = io.BytesIO()
    plow_image.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    fname = f"plow_redo_{sku.replace('-', '_').lower()}_{uuid.uuid4().hex[:6]}.png"
    files = {"image": (fname, buf, "image/png")}
    data = {"overwrite": "true", "type": "input"}
    r = await client.post(f"{COMFY}/upload/image", files=files, data=data)
    r.raise_for_status()
    truck_filename = r.json().get("name", fname)

    workflow = build_workflow(truck_filename, ROTATION_PROMPT, seed)
    r = await client.post(f"{COMFY}/prompt",
                          json={"prompt": workflow, "client_id": str(uuid.uuid4())})
    r.raise_for_status()
    prompt_id = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 180:
        await asyncio.sleep(2)
        h = await client.get(f"{COMFY}/history/{prompt_id}")
        history = h.json()
        if prompt_id in history and history[prompt_id].get("status", {}).get("completed"):
            for node_output in history[prompt_id].get("outputs", {}).values():
                imgs = node_output.get("images", [])
                if not imgs:
                    continue
                first = imgs[0]
                view_url = (
                    f"{COMFY}/view?filename={first['filename']}"
                    f"&subfolder={first.get('subfolder','')}&type=output"
                )
                img_r = await client.get(view_url)
                return Image.open(io.BytesIO(img_r.content)).convert("RGB")
    return None


def clean_alpha_halo(img: Image.Image, threshold: int = 200) -> Image.Image:
    arr = np.asarray(img.convert("RGBA")).copy()
    alpha = arr[:, :, 3]
    arr[:, :, 3] = np.where(alpha >= threshold, 255, 0)
    return Image.fromarray(arr, mode="RGBA")


async def main() -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    rembg_sess = new_session("isnet-general-use")

    # First: restore bad ones to head-on
    print("[restore phase]")
    for sku in FAILED_SKUS:
        sku_dir = SKUS_DIR / sku
        backup = sku_dir / "hero_transparent_v2_headon.png"
        canonical = sku_dir / "hero_transparent.png"
        if backup.exists():
            import shutil
            shutil.copy(backup, canonical)
            print(f"  {sku}: restored from backup")

    # Then: try multiple seeds per SKU, save all variants for visual pick later
    seeds = [42, 1337, 8888]
    async with httpx.AsyncClient(timeout=200) as client:
        for sku in FAILED_SKUS:
            print(f"\n=== {sku} ===")
            hero_jpg = SKUS_DIR / sku / "hero.jpg"
            if not hero_jpg.exists():
                continue
            src = Image.open(hero_jpg).convert("RGB")
            print(f"  source: {src.size}")
            for seed in seeds:
                t0 = time.time()
                rotated = await run_kontext(client, src, sku, seed)
                elapsed = time.time() - t0
                if rotated is None:
                    print(f"  seed {seed}: FAILED")
                    continue
                # Save raw rotation
                raw_path = WORK_DIR / f"{sku}_seed{seed}_raw.png"
                rotated.save(raw_path)
                # rembg + clean
                trans = remove(rotated, session=rembg_sess)
                cleaned = clean_alpha_halo(trans, threshold=200)
                clean_path = WORK_DIR / f"{sku}_seed{seed}_clean.png"
                cleaned.save(clean_path)
                print(f"  seed {seed}: saved ({elapsed:.1f}s)")

    print(f"\nDone. Outputs in {WORK_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
