"""4x upscale plow transparent PNGs via ComfyUI's 4x-UltraSharp on llama.

Source plow heroes are 300x168 — at the lineup display size (768x430)
we're scaling 2.56x past native, which causes visible distortion. Pre-
upscaling to 1200x672 gives us comfortable headroom.

Targets the WEST-MVP3MS86 plow first (only one used in the current lineup
preview); add more SKUs to TARGETS as needed.

Output: hero_transparent_x4.png next to each hero_transparent.png.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

COMFY = "http://100.85.94.57:8188"
SKUS_DIR = Path(__file__).resolve().parents[1] / "backend" / "static" / "snow-plows" / "skus"

UPSCALE_MODEL = "4x-UltraSharp.pth"

TARGETS = [
    "WEST-MVP3MS86-EQP",  # the only plow in the current lineup preview
]


def upload_image(client: httpx.Client, src_path: Path) -> str:
    with src_path.open("rb") as f:
        files = {"image": (src_path.name, f, "image/png")}
        data = {"overwrite": "true"}
        r = client.post(f"{COMFY}/upload/image", files=files, data=data, timeout=60.0)
    r.raise_for_status()
    return r.json()["name"]


def build_workflow(input_filename: str) -> dict:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": input_filename}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALE_MODEL}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {
            "upscale_model": ["2", 0],
            "image": ["1", 0],
        }},
        "4": {"class_type": "SaveImage", "inputs": {
            "images": ["3", 0],
            "filename_prefix": "plow_x4",
        }},
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
    t_start = time.time()
    n_done = 0
    n_failed = 0
    with httpx.Client() as client:
        for sku in TARGETS:
            src = SKUS_DIR / sku / "hero_transparent.png"
            dst = SKUS_DIR / sku / "hero_transparent_x4.png"
            if not src.exists():
                print(f"  ! {sku}: missing hero_transparent.png")
                n_failed += 1
                continue
            try:
                t = time.time()
                uploaded = upload_image(client, src)
                wf = build_workflow(uploaded)
                result = queue_and_wait(client, wf)
                got = False
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
                    dst.write_bytes(r.content)
                    print(f"  {sku}: {time.time()-t:.1f}s ({dst.stat().st_size:,}B)")
                    got = True
                    n_done += 1
                    break
                if not got:
                    print(f"  ! {sku}: no output")
                    n_failed += 1
            except Exception as e:
                print(f"  ! {sku}: {e}")
                n_failed += 1

    print(f"\n{n_done}/{len(TARGETS)} done in {time.time()-t_start:.1f}s "
          f"({n_failed} failed)")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
