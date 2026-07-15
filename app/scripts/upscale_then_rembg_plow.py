"""Upscale plow hero.jpg first, THEN run rembg.

The previous pipeline (rembg first, then upscale RGBA) ate semi-transparent
detail like reflective lens surfaces on the plow lights, because
upscaling alpha via LANCZOS over-smooths partially-transparent pixels.

This script does it the other way:
  1. Upscale the original RGB hero.jpg on llama via 4x-UltraSharp -> 4x RGB
  2. Run rembg locally on the 4x RGB -> 4x RGBA with crisp natural alpha
  3. Save as hero_transparent_x4.png

Result: lights and other reflective details preserved at full resolution.
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
from rembg import new_session, remove

COMFY = "http://100.85.94.57:8188"
SKUS_DIR = Path(__file__).resolve().parents[1] / "backend" / "static" / "snow-plows" / "skus"
UPSCALE_MODEL = "4x-UltraSharp.pth"
REMBG_MODEL = "isnet-general-use"  # better detail preservation than u2net default

TARGETS = [
    # All clean Westerns — replaces low-res hero_transparent.png with crisp x4
    "WEST-DEF68-EQP", "WEST-DEF72-EQP",
    "WEST-ENFMS76-EQP", "WEST-ENFSS76-EQP",
    "WEST-HTS76-EQP",
    "WEST-MIDMS76-EQP", "WEST-MIDPLY76-EQP",
    "WEST-MVP3MS106-EQP", "WEST-MVP3MS86-EQP", "WEST-MVP3MS96-EQP",
    "WEST-MVP3PLY86-EQP", "WEST-MVP3PLY96-EQP",
    "WEST-MVP3SS106-EQP", "WEST-MVP3SS86-EQP", "WEST-MVP3SS96-EQP",
    "WEST-MVPPMS86-EQP", "WEST-MVPPMS96-EQP",
    "WEST-MVPPPLY86-EQP", "WEST-MVPPPLY96-EQP",
    "WEST-PDGY-EQP",
    "WEST-PPHD10-EQP",
    "WEST-PPMS8-EQP", "WEST-PPMS86-EQP", "WEST-PPMS9-EQP",
    "WEST-PPS2MS76-EQP", "WEST-PPS2MS8-EQP", "WEST-PPS2MS86-EQP",
    "WEST-PPS2PLY76-EQP", "WEST-PPS2PLY8-EQP",
    "WEST-WIDE810-EQP", "WEST-WIDEXL-EQP",
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
            "images": ["3", 0], "filename_prefix": "plow_4x_rgb"}},
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


def process_one(client: httpx.Client, sku: str, rembg_session) -> bool:
    src = SKUS_DIR / sku / "hero.jpg"
    dst = SKUS_DIR / sku / "hero_transparent_x4.png"
    if not src.exists():
        print(f"  ! {sku}: missing hero.jpg")
        return False

    src_w, src_h = Image.open(src).size

    try:
        t0 = time.time()
        # Step 1: upload + 4x upscale on llama
        uploaded = upload_image(client, src, f"plow_input_{sku}.jpg")
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
        upscale_t = time.time() - t0
        print(f"  {sku}: upscaled in {upscale_t:.1f}s ({len(rgb_x4_bytes):,}B)")

        # Step 2: rembg on the 4x RGB
        t1 = time.time()
        rgba_bytes = remove(rgb_x4_bytes, session=rembg_session)
        rembg_t = time.time() - t1
        print(f"  {sku}: rembg in {rembg_t:.1f}s")

        # Save final RGBA
        dst.write_bytes(rgba_bytes)
        with Image.open(dst) as im:
            print(f"  {sku}: saved {dst.name} {im.size} ({dst.stat().st_size:,}B)")
            assert im.mode == "RGBA", f"expected RGBA got {im.mode}"
        return True
    except Exception as e:
        print(f"  ! {sku}: failed - {e}")
        return False


def main() -> int:
    print(f"Loading rembg session ({REMBG_MODEL})...")
    rembg_session = new_session(REMBG_MODEL)

    n_done = 0
    n_failed = 0
    t_total = time.time()
    with httpx.Client() as client:
        for sku in TARGETS:
            if process_one(client, sku, rembg_session):
                n_done += 1
            else:
                n_failed += 1
    print(f"\n{n_done}/{len(TARGETS)} done in {time.time()-t_total:.1f}s "
          f"({n_failed} failed)")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
