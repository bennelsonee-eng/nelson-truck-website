"""Apply Stable Zero123 rotation to all priority plows at +60° azimuth.

Pipeline per SKU:
  1. Load best available source (hero_manufacturer.jpg if exists, else hero.jpg)
  2. Pad to square + resize to 256x256 (Zero123 native input)
  3. Upload to ComfyUI on llama
  4. Run Zero123 with elevation=0, azimuth=60
  5. Download 256x256 output (black bg)
  6. rembg to extract clean transparent
  7. Save as canonical hero_transparent.png
     (back up old transparent as hero_transparent_v4_3dmath.png)
"""

from __future__ import annotations

import asyncio
import io
import shutil
import sys
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image
from rembg import remove, new_session


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
WORK_DIR = REPO / "wan_test_output" / "zero123_batch"

COMFY = "http://100.85.94.57:8188"
ZERO123_MODEL = "_zero123/stable_zero123.ckpt"

AZIMUTH = int(__import__("os").environ.get("AZIMUTH", "60"))
ELEVATION = int(__import__("os").environ.get("ELEVATION", "0"))


ALL_PRIORITY = [
    "WEST-MVP3MS86-EQP",
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
# CLI: --skus a,b,c to limit
PRIORITY_PLOWS = ALL_PRIORITY
if "--skus" in sys.argv:
    PRIORITY_PLOWS = sys.argv[sys.argv.index("--skus") + 1].split(",")


def best_source(sku: str) -> Path | None:
    sku_dir = SKUS_DIR / sku
    for fname in ["hero_manufacturer.jpg", "hero.jpg"]:
        p = sku_dir / fname
        if p.exists():
            return p
    return None


def pad_to_square_256(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    W, H = img.size
    side = max(W, H)
    sq = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    sq.paste(img, ((side - W) // 2, (side - H) // 2))
    return sq.resize((256, 256), Image.LANCZOS)


def build_workflow(input_filename: str, elevation: float, azimuth: float, seed: int = 42) -> dict:
    return {
        "1": {"class_type": "ImageOnlyCheckpointLoader", "inputs": {
            "ckpt_name": ZERO123_MODEL}},
        "2": {"class_type": "LoadImage", "inputs": {
            "image": input_filename, "upload": "image"}},
        "3": {"class_type": "StableZero123_Conditioning", "inputs": {
            "clip_vision": ["1", 1], "init_image": ["2", 0], "vae": ["1", 2],
            "width": 256, "height": 256, "batch_size": 1,
            "elevation": elevation, "azimuth": azimuth,
        }},
        "4": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["3", 0], "negative": ["3", 1],
            "latent_image": ["3", 2],
            "seed": seed, "steps": 20, "cfg": 4.0,
            "sampler_name": "euler", "scheduler": "sgm_uniform", "denoise": 1.0,
        }},
        "5": {"class_type": "VAEDecode", "inputs": {
            "samples": ["4", 0], "vae": ["1", 2]}},
        "6": {"class_type": "SaveImage", "inputs": {
            "images": ["5", 0], "filename_prefix": "zero123_batch"}},
    }


async def upload(client, img, hint):
    buf = io.BytesIO()
    img.convert("RGBA").save(buf, format="PNG")
    buf.seek(0)
    fname = f"{hint}_{uuid.uuid4().hex[:8]}.png"
    files = {"image": (fname, buf, "image/png")}
    data = {"overwrite": "true", "type": "input"}
    r = await client.post(f"{COMFY}/upload/image", files=files, data=data)
    r.raise_for_status()
    return r.json().get("name", fname)


async def run_zero123(client, src_filename, elevation, azimuth) -> Image.Image | None:
    workflow = build_workflow(src_filename, elevation, azimuth)
    r = await client.post(f"{COMFY}/prompt",
                          json={"prompt": workflow, "client_id": str(uuid.uuid4())})
    if r.status_code >= 400:
        return None
    prompt_id = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 120:
        await asyncio.sleep(1)
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
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    rembg_sess = new_session("isnet-general-use")
    print(f"Zero123 azimuth={AZIMUTH}° elevation={ELEVATION}°\n")

    async with httpx.AsyncClient(timeout=180) as client:
        for sku in PRIORITY_PLOWS:
            print(f"=== {sku} ===")
            src_path = best_source(sku)
            if src_path is None:
                print(f"  ! no source")
                continue
            print(f"  [1/6] source: {src_path.name}")

            src = Image.open(src_path).convert("RGBA")
            print(f"        original size: {src.size}")
            sq256 = pad_to_square_256(src)
            (WORK_DIR / f"{sku}_input256.png").write_bytes(b"")  # placeholder
            sq256.save(WORK_DIR / f"{sku}_input256.png")
            print(f"  [2/6] padded to 256x256")

            print(f"  [3/6] uploading to ComfyUI...")
            upload_name = await upload(client, sq256, f"z123_{sku.replace('-','_').lower()}")

            print(f"  [4/6] running Zero123 (az={AZIMUTH})...")
            t0 = time.time()
            rotated = await run_zero123(client, upload_name, ELEVATION, AZIMUTH)
            if rotated is None:
                print(f"  ! Zero123 failed")
                continue
            elapsed = time.time() - t0
            rotated.save(WORK_DIR / f"{sku}_z123_raw.png")
            print(f"        rendered ({elapsed:.1f}s)")

            print(f"  [5/6] rembg...")
            transparent = remove(rotated, session=rembg_sess)
            transparent.save(WORK_DIR / f"{sku}_z123_transparent.png")

            print(f"  [6/6] save as canonical")
            sku_dir = SKUS_DIR / sku
            canonical = sku_dir / "hero_transparent.png"
            backup = sku_dir / "hero_transparent_v4_3dmath.png"
            if canonical.exists() and not backup.exists():
                shutil.copy(canonical, backup)
                print(f"        backed up old to {backup.name}")
            transparent.save(canonical)
            print(f"        installed new {canonical.name}\n")

    print(f"\nDone. Working dir: {WORK_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
