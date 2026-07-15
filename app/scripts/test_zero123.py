"""Test Stable Zero123 novel-view synthesis on the MVP3 plow.

Stable Zero123 takes a single object image and generates views from
different angles (elevation + azimuth).  Purpose-built for this task —
unlike Kontext which preserves structure, Zero123 actively reasons about
3D geometry.

Camera convention:
  elevation: vertical tilt (0 = horizontal, positive = looking down)
  azimuth:   horizontal angle around object
             0   = front (current view)
             +30 = view from object's right side (right side of object
                   appears compressed/receding in output)
             -30 = view from object's left side
             +90 = side view (right profile)

For our plow on truck, we want positive azimuth (~30°) so the right side
of the plow recedes back, matching the truck's 3/4 perspective.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "wan_test_output" / "highres_3d_test" / "step2_transparent.png"
OUT_DIR = REPO / "wan_test_output" / "zero123_test"

COMFY = "http://100.85.94.57:8188"
ZERO123_MODEL = "_zero123/stable_zero123.ckpt"


def build_workflow(input_filename: str, elevation: float, azimuth: float, seed: int = 42) -> dict:
    """Stable Zero123 workflow.

    The Zero123 model is loaded as an SVD-style image-only checkpoint.
    We condition with elevation + azimuth + a reference image, then sample.
    Output is a 256×256 view at the requested angle.
    """
    return {
        "1": {"class_type": "ImageOnlyCheckpointLoader", "inputs": {
            "ckpt_name": ZERO123_MODEL}},
        "2": {"class_type": "LoadImage", "inputs": {
            "image": input_filename, "upload": "image"}},
        "3": {"class_type": "StableZero123_Conditioning", "inputs": {
            "clip_vision": ["1", 1],
            "init_image": ["2", 0],
            "vae": ["1", 2],
            "width": 256,
            "height": 256,
            "batch_size": 1,
            "elevation": elevation,
            "azimuth": azimuth,
        }},
        "4": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["3", 0],
            "negative": ["3", 1],
            "latent_image": ["3", 2],
            "seed": seed,
            "steps": 20,
            "cfg": 4.0,
            "sampler_name": "euler",
            "scheduler": "sgm_uniform",
            "denoise": 1.0,
        }},
        "5": {"class_type": "VAEDecode", "inputs": {
            "samples": ["4", 0], "vae": ["1", 2]}},
        "6": {"class_type": "SaveImage", "inputs": {
            "images": ["5", 0], "filename_prefix": "zero123"}},
    }


async def upload_image(client: httpx.AsyncClient, img: Image.Image, name_hint: str) -> str:
    buf = io.BytesIO()
    img.convert("RGBA").save(buf, format="PNG")
    buf.seek(0)
    fname = f"{name_hint}_{uuid.uuid4().hex[:8]}.png"
    files = {"image": (fname, buf, "image/png")}
    data = {"overwrite": "true", "type": "input"}
    r = await client.post(f"{COMFY}/upload/image", files=files, data=data)
    r.raise_for_status()
    return r.json().get("name", fname)


async def run_zero123(client: httpx.AsyncClient, src_filename: str,
                      elevation: float, azimuth: float) -> Image.Image | None:
    workflow = build_workflow(src_filename, elevation, azimuth)
    r = await client.post(f"{COMFY}/prompt",
                          json={"prompt": workflow, "client_id": str(uuid.uuid4())})
    if r.status_code >= 400:
        print(f"  prompt error: {r.text[:300]}")
        return None
    prompt_id = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 120:
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

    src = Image.open(SOURCE).convert("RGBA")
    # Zero123 expects 256x256 input — center-crop and resize
    # Actually for plow, we should pad to square first, then resize
    W, H = src.size
    side = max(W, H)
    sq = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    sq.paste(src, ((side - W) // 2, (side - H) // 2))
    src_256 = sq.resize((256, 256), Image.LANCZOS)
    print(f"Source: {SOURCE.name} {src.size} -> 256x256 squared")

    angles = [
        # (elevation, azimuth, label)
        (0,    0,   "front_0"),
        (0,   15,   "az_+15"),
        (0,   30,   "az_+30"),
        (0,   45,   "az_+45"),
        (0,   60,   "az_+60"),
        (0,  -30,   "az_-30"),
        (-15, 30,   "elev-15_az+30"),
        (15,  30,   "elev+15_az+30"),
    ]

    results: dict[str, Image.Image] = {}
    async with httpx.AsyncClient(timeout=180) as client:
        src_filename = await upload_image(client, src_256, "mvp3_zero123")
        print(f"Uploaded source as {src_filename}")
        for elev, az, label in angles:
            print(f"\n[{label}] elev={elev}° az={az}°")
            t0 = time.time()
            out = await run_zero123(client, src_filename, elev, az)
            if out is None:
                print(f"  FAILED")
                continue
            results[label] = out
            out.save(OUT_DIR / f"{label}.png")
            print(f"  saved ({time.time() - t0:.1f}s)")

    # Build a labeled grid
    if results:
        TILE = 256
        LABEL_H = 30
        cols = 4
        rows = (len(results) + cols - 1) // cols
        grid = Image.new("RGB", (cols * TILE, rows * (TILE + LABEL_H)), (40, 40, 40))
        draw = ImageDraw.Draw(grid)
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
        for i, (label, img) in enumerate(results.items()):
            r, c = divmod(i, cols)
            x, y = c * TILE, r * (TILE + LABEL_H)
            grid.paste(img.resize((TILE, TILE)), (x, y))
            draw.rectangle([x, y + TILE, x + TILE, y + TILE + LABEL_H], fill=(20, 20, 20))
            draw.text((x + 8, y + TILE + 8), label, fill=(255, 255, 100), font=font)
        grid.save(OUT_DIR / "_zero123_grid.png")
        print(f"\nGrid: {OUT_DIR / '_zero123_grid.png'}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
