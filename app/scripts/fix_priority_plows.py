"""Fix priority plow source images: rotate to op-right via Kontext, then
re-extract transparent with cleaner alpha (no white halo).

Pipeline per SKU:
  1. Load original hero.jpg (with white background — the source)
  2. Send to Kontext with rotation prompt → rotated plow on white bg
  3. rembg the rotated output with isnet-general-use model
  4. Alpha-threshold cleanup: alpha < 200 → 0, alpha >= 200 → 255
     (kills anti-aliased edge pixels that show as white halo)
  5. Save as the new canonical hero_transparent.png
  6. Backup the previous version as hero_transparent_v2_headon.png
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
WORK_DIR = REPO / "wan_test_output" / "plow_v2_pipeline"

COMFY = "http://100.85.94.57:8188"
KONTEXT_MODEL = "flux1-dev-kontext_fp8_scaled.safetensors"


# Priority plows to fix.  MVP3 already done in earlier session.
# Allow override via CLI for testing on a subset.
ALL_PRIORITY = [
    "WEST-MVPPMS86-EQP",
    "WEST-MVPPMS96-EQP",
    "WEST-ENFMS76-EQP",
    "WEST-ENFSS76-EQP",
    "WEST-HTS76-EQP",
    "MYP-09275-EQP",
    "SNOW-16020412-EQP",
    "SNOW-16020724-EQP",
    "SNOW-16020922-EQP",
]
# CLI override: --skus WEST-MVPPMS86-EQP,WEST-ENFMS76-EQP
PRIORITY_PLOWS = ALL_PRIORITY
if "--skus" in sys.argv:
    idx = sys.argv.index("--skus")
    PRIORITY_PLOWS = sys.argv[idx + 1].split(",")


ROTATION_PROMPT = (
    "Reposition the camera to the operator-right side of this plow at a "
    "slight three-quarter angle (about 25 degrees off centerline). The "
    "operator's left blade should be prominent in the foreground. Keep all "
    "branding, logos, and badges clearly readable and unchanged. Plow alone "
    "on pure white studio background, no truck, no snow, no people, no shadows."
)


def build_kontext_workflow(input_filename: str, prompt: str, seed: int = 42) -> dict:
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
            "conditioning": ["7", 0], "guidance": 2.5}},
        "6": {"class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["8", 0], "latent": ["5", 0]}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": ""}},
        "10": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["6", 0],
            "negative": ["9", 0],
            "latent_image": ["5", 0],
            "seed": seed, "steps": 20, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
        }},
        "11": {"class_type": "VAEDecode", "inputs": {
            "samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {
            "images": ["11", 0], "filename_prefix": "kontext_plow_v2"}},
    }


async def rotate_via_kontext(client: httpx.AsyncClient,
                             plow_image: Image.Image, sku: str) -> Image.Image | None:
    # Upload
    buf = io.BytesIO()
    plow_image.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    fname = f"plow_v2_{sku.replace('-', '_').lower()}_{uuid.uuid4().hex[:8]}.png"
    files = {"image": (fname, buf, "image/png")}
    data = {"overwrite": "true", "type": "input"}
    r = await client.post(f"{COMFY}/upload/image", files=files, data=data)
    r.raise_for_status()
    truck_filename = r.json().get("name", fname)

    # Queue + poll
    workflow = build_kontext_workflow(truck_filename, ROTATION_PROMPT)
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
                from io import BytesIO
                return Image.open(BytesIO(img_r.content)).convert("RGB")
    return None


def clean_alpha_halo(img: Image.Image, threshold: int = 200) -> Image.Image:
    """Sharpen alpha edges to kill anti-aliased white halo.

    alpha < threshold → 0 (transparent)
    alpha >= threshold → 255 (opaque)

    Trades soft edges for clean transparency.  At display sizes typical
    in the configurator (300-800px wide) the hard edges aren't noticeable.
    """
    arr = np.asarray(img.convert("RGBA")).copy()
    alpha = arr[:, :, 3]
    arr[:, :, 3] = np.where(alpha >= threshold, 255, 0)
    return Image.fromarray(arr, mode="RGBA")


async def process_one(client: httpx.AsyncClient, rembg_session, sku: str) -> bool:
    print(f"\n=== {sku} ===")
    sku_dir = SKUS_DIR / sku
    hero_jpg = sku_dir / "hero.jpg"
    if not hero_jpg.exists():
        print(f"  ! no hero.jpg")
        return False
    current_transparent = sku_dir / "hero_transparent.png"

    print(f"  [1/5] loading source: {hero_jpg.name}")
    src = Image.open(hero_jpg).convert("RGB")
    print(f"        source size: {src.size}")

    print(f"  [2/5] Kontext rotation to op-right viewpoint...")
    t0 = time.time()
    rotated = await rotate_via_kontext(client, src, sku)
    if rotated is None:
        print(f"  ! rotation failed")
        return False
    print(f"        rotated {rotated.size} in {time.time() - t0:.1f}s")
    rotated_path = WORK_DIR / f"{sku}_kontext_rotated.png"
    rotated.save(rotated_path)

    print(f"  [3/5] rembg + transparency...")
    transparent = remove(rotated, session=rembg_session)
    transparent_path = WORK_DIR / f"{sku}_rembg.png"
    transparent.save(transparent_path)

    print(f"  [4/5] alpha-halo cleanup (threshold 200)...")
    cleaned = clean_alpha_halo(transparent, threshold=200)
    cleaned_path = WORK_DIR / f"{sku}_cleaned.png"
    cleaned.save(cleaned_path)

    print(f"  [5/5] backup current + install new canonical...")
    if current_transparent.exists():
        backup_path = sku_dir / f"hero_transparent_v2_headon.png"
        # Don't overwrite if already backed up
        if not backup_path.exists():
            current_transparent.replace(backup_path)
            print(f"        backed up old to {backup_path.name}")
    cleaned.save(current_transparent)
    print(f"        installed new {current_transparent.name}")
    return True


async def main() -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    rembg_sess = new_session("isnet-general-use")
    async with httpx.AsyncClient(timeout=200) as client:
        ok_count = 0
        for sku in PRIORITY_PLOWS:
            try:
                if await process_one(client, rembg_sess, sku):
                    ok_count += 1
            except Exception as e:
                print(f"  ! {sku} failed: {e}")
        print(f"\nDone — {ok_count}/{len(PRIORITY_PLOWS)} processed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
