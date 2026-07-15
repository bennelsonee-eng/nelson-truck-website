"""4x upscale plow PNGs on llama, preserving alpha channel.

ESRGAN models are RGB-only — they ignore/drop alpha. Workaround:
  1. Split source RGBA into RGB + alpha mask
  2. Upscale RGB on llama via 4x-UltraSharp
  3. Upscale alpha locally via PIL LANCZOS (alpha is just a mask, lower
     fidelity is acceptable)
  4. Recombine into RGBA at 4x resolution

Output: hero_transparent_x4.png (RGBA, 4x source dimensions)
"""

from __future__ import annotations

import io
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image

COMFY = "http://100.85.94.57:8188"
SKUS_DIR = Path(__file__).resolve().parents[1] / "backend" / "static" / "snow-plows" / "skus"

UPSCALE_MODEL = "4x-UltraSharp.pth"
SCALE = 4

TARGETS = [
    # SnowDoggs — user-erased RGBA preserved, just upscale to 4x
    "SNOW-16020412-EQP",  # MD II
    "SNOW-16020522-EQP",  # HD II
    "SNOW-16020612-EQP",  # EX II
    "SNOW-16020712-EQP",  # VMD75 II
    "SNOW-16020724-EQP",  # VXF II (now reverted to VXXII branding per user pref)
    "SNOW-16020820-EQP",  # CM II
    "SNOW-16020922-EQP",  # XP 810 II
    "SNOW-VXX-EQP",       # VXX 10'6" V-plow (the larger version of VXF)
]


def upload_image(client: httpx.Client, src_path: Path, name: str) -> str:
    with src_path.open("rb") as f:
        files = {"image": (name, f, "image/png")}
        data = {"overwrite": "true"}
        r = client.post(f"{COMFY}/upload/image", files=files, data=data, timeout=60.0)
    r.raise_for_status()
    return r.json()["name"]


def build_workflow(input_filename: str) -> dict:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": input_filename}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALE_MODEL}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {
            "upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {
            "images": ["3", 0], "filename_prefix": "plow_rgb_x4"}},
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


def upscale_one(client: httpx.Client, sku: str) -> bool:
    src = SKUS_DIR / sku / "hero_transparent.png"
    dst = SKUS_DIR / sku / "hero_transparent_x4.png"
    if not src.exists():
        print(f"  ! {sku}: missing hero_transparent.png")
        return False

    src_rgba = Image.open(src).convert("RGBA")
    Sw, Sh = src_rgba.size

    rgb = src_rgba.convert("RGB")
    alpha = src_rgba.split()[-1]

    # Save RGB to temp file for upload
    tmp_dir = SKUS_DIR / sku
    tmp_rgb_path = tmp_dir / f"_tmp_rgb_{uuid.uuid4().hex[:8]}.png"
    try:
        rgb.save(tmp_rgb_path)
        upload_name = f"plow_rgb_{sku}.png"
        uploaded = upload_image(client, tmp_rgb_path, upload_name)

        wf = build_workflow(uploaded)
        result = queue_and_wait(client, wf)

        rgb_x4_bytes = None
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
            rgb_x4_bytes = r.content
            break
        if not rgb_x4_bytes:
            print(f"  ! {sku}: no upscale output")
            return False

        rgb_x4 = Image.open(io.BytesIO(rgb_x4_bytes)).convert("RGB")
        # Some ESRGAN models pad — verify size; otherwise resize alpha to match
        target_size = rgb_x4.size
        alpha_x4 = alpha.resize(target_size, Image.LANCZOS)

        out = Image.new("RGBA", target_size)
        out.paste(rgb_x4, mask=alpha_x4)
        # The above paste keeps RGB but loses our alpha. Reapply via putalpha:
        out = rgb_x4.convert("RGBA")
        out.putalpha(alpha_x4)
        out.save(dst)
        print(f"  {sku}: {Sw}x{Sh} -> {target_size[0]}x{target_size[1]} "
              f"({dst.stat().st_size:,}B)")
        return True
    finally:
        if tmp_rgb_path.exists():
            tmp_rgb_path.unlink()


def main() -> int:
    t_start = time.time()
    n_done = 0
    n_failed = 0
    with httpx.Client() as client:
        for sku in TARGETS:
            try:
                if upscale_one(client, sku):
                    n_done += 1
                else:
                    n_failed += 1
            except Exception as e:
                print(f"  ! {sku}: {e}")
                n_failed += 1

    print(f"\n{n_done}/{len(TARGETS)} done in {time.time()-t_start:.1f}s "
          f"({n_failed} failed)")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
