"""Test Kontext at different denoise values to find the sweet spot:
preserve our 3D rotation while still photo-finishing the integration.

denoise=1.0  → full re-render, washes out rotation (current default)
denoise=0.7  → moderate edit, preserves more input structure
denoise=0.5  → light edit, mostly preserves input
denoise=0.3  → very light, minor pixel adjustments
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[2]
SEED_PATH = REPO / "wan_test_output" / "highres_3d_test" / "step4_pil_composite.png"
OUT_DIR = REPO / "wan_test_output" / "denoise_test"

COMFY = "http://100.85.94.57:8188"
KONTEXT_MODEL = "flux1-dev-kontext_fp8_scaled.safetensors"


PROMPT = (
    "make this photorealistic, professional automotive product photography, "
    "matching studio lighting and shadows. Keep all text on the plow exactly "
    "as shown. WESTERN logo and MVP3 badge must remain unchanged and clearly "
    "readable. PRESERVE the exact perspective angle of the plow."
)


def build_workflow(input_filename: str, denoise: float, seed: int = 42) -> dict:
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
            "clip": ["2", 0], "text": PROMPT}},
        "8": {"class_type": "FluxGuidance", "inputs": {
            "conditioning": ["7", 0], "guidance": 2.5}},
        "6": {"class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["8", 0], "latent": ["5", 0]}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": ""}},
        "10": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["6", 0], "negative": ["9", 0],
            "latent_image": ["5", 0], "seed": seed,
            "steps": 20, "cfg": 1.0, "sampler_name": "euler",
            "scheduler": "simple", "denoise": denoise}},  # KEY KNOB
        "11": {"class_type": "VAEDecode", "inputs": {
            "samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {
            "images": ["11", 0], "filename_prefix": "kontext_denoise"}},
    }


async def run_at_denoise(client: httpx.AsyncClient, seed_img: Image.Image,
                          denoise: float) -> Image.Image | None:
    buf = io.BytesIO()
    seed_img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    fname = f"denoise_test_{uuid.uuid4().hex[:8]}.png"
    files = {"image": (fname, buf, "image/png")}
    data = {"overwrite": "true", "type": "input"}
    r = await client.post(f"{COMFY}/upload/image", files=files, data=data)
    r.raise_for_status()
    truck_filename = r.json().get("name", fname)

    workflow = build_workflow(truck_filename, denoise)
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


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seed_img = Image.open(SEED_PATH).convert("RGB")
    print(f"Seed: {SEED_PATH.name} {seed_img.size}")

    denoise_values = [1.0, 0.85, 0.7, 0.55, 0.4]
    results = {}
    async with httpx.AsyncClient(timeout=200) as client:
        for d in denoise_values:
            print(f"\n[denoise {d}]")
            t0 = time.time()
            out = await run_at_denoise(client, seed_img, d)
            if out is None:
                print(f"  FAILED")
                continue
            results[d] = out
            out_path = OUT_DIR / f"denoise_{d:.2f}.png"
            out.save(out_path)
            print(f"  saved {out_path.name} ({time.time() - t0:.1f}s)")

    # Build comparison grid: seed | d=1.0 | d=0.85 | d=0.7 | d=0.55 | d=0.4
    TILE_W, TILE_H, LABEL_H = 480, 270, 30
    cols = 1 + len(denoise_values)
    grid = Image.new("RGB", (cols * TILE_W, TILE_H + LABEL_H + 30), (40, 40, 40))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
        big_font = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
        big_font = font
    draw.text((20, 4),
              "Same hi-res 3D-rotated PIL seed → Kontext at varying denoise levels",
              fill=(255, 255, 100), font=big_font)

    # Tile 0: PIL seed
    fitted = seed_img.resize((TILE_W, TILE_H), Image.LANCZOS)
    grid.paste(fitted, (0, 30))
    draw.rectangle([0, 30 + TILE_H, TILE_W, 30 + TILE_H + LABEL_H], fill=(20, 20, 20))
    draw.text((10, 30 + TILE_H + 8),
              "PIL seed (no Kontext) — full rotation visible",
              fill=(255, 255, 255), font=font)

    # Tiles 1+: Kontext outputs at decreasing denoise
    for i, d in enumerate(denoise_values):
        x = (i + 1) * TILE_W
        if d in results:
            fitted = results[d].resize((TILE_W, TILE_H), Image.LANCZOS)
            grid.paste(fitted, (x, 30))
        draw.rectangle([x, 30 + TILE_H, x + TILE_W, 30 + TILE_H + LABEL_H], fill=(20, 20, 20))
        notes = {
            1.0:  "denoise=1.0 (full re-render, current default)",
            0.85: "denoise=0.85 (mostly re-render)",
            0.7:  "denoise=0.7 (moderate edit)",
            0.55: "denoise=0.55 (light edit)",
            0.4:  "denoise=0.4 (very light, near-passthrough)",
        }
        draw.text((x + 8, 30 + TILE_H + 8), notes.get(d, str(d)),
                  fill=(255, 255, 255), font=font)

    out_path = OUT_DIR / "denoise_comparison_grid.png"
    grid.save(out_path)
    print(f"\nGrid: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
