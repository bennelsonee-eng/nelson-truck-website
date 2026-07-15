"""TRELLIS batch runner — designed to run ON LLAMA (Linux side).

Reads JPGs from /tmp/trellis_batch_in/<SKU>/hero_manufacturer.jpg
Writes results to /tmp/trellis_batch_out/<SKU>/{<SKU>.glb, preview.mp4, preprocessed.png, results.json}

Run on llama via:
    ~/wan-venv/bin/python /tmp/trellis_batch_llama.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from gradio_client import Client, handle_file


SPACE = "microsoft/TRELLIS"
IN_DIR = Path("/tmp/trellis_batch_in")
OUT_DIR = Path("/tmp/trellis_batch_out")


def discover_skus() -> list[Path]:
    """Each subdir of IN_DIR with a hero_manufacturer.jpg is one SKU."""
    found = []
    for sub in sorted(IN_DIR.iterdir()):
        if sub.is_dir():
            jpg = sub / "hero_manufacturer.jpg"
            if jpg.exists():
                found.append(jpg)
    return found


def run_one(client: Client, sku: str, src: Path, out_dir: Path) -> dict:
    info: dict = {"sku": sku, "src": str(src), "status": "", "times": {}}
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        preproc = client.predict(image=handle_file(str(src)), api_name="/preprocess_image")
        info["times"]["preprocess"] = round(time.time() - t0, 1)
        if isinstance(preproc, dict) and "path" in preproc:
            shutil.copy(preproc["path"], out_dir / "preprocessed.png")
        elif isinstance(preproc, str):
            shutil.copy(preproc, out_dir / "preprocessed.png")
    except Exception as e:
        info["status"] = f"preprocess_failed: {e}"
        return info

    t0 = time.time()
    try:
        result_3d = client.predict(
            image=handle_file(str(src)),
            multiimages=[],
            seed=0,
            ss_guidance_strength=7.5,
            ss_sampling_steps=12,
            slat_guidance_strength=3.0,
            slat_sampling_steps=12,
            multiimage_algo="stochastic",
            api_name="/image_to_3d",
        )
        info["times"]["image_to_3d"] = round(time.time() - t0, 1)
        if isinstance(result_3d, (list, tuple)):
            for r in result_3d:
                if isinstance(r, str) and r.endswith((".mp4", ".webm")):
                    shutil.copy(r, out_dir / "preview.mp4")
                    info["preview_mp4"] = "preview.mp4"
                    break
                if isinstance(r, dict) and "video" in r:
                    vp = r["video"]
                    if isinstance(vp, dict) and "path" in vp:
                        vp = vp["path"]
                    if vp and Path(vp).exists():
                        shutil.copy(vp, out_dir / "preview.mp4")
                        info["preview_mp4"] = "preview.mp4"
                        break
    except Exception as e:
        info["status"] = f"image_to_3d_failed: {e}"
        return info

    t0 = time.time()
    try:
        glb_result = client.predict(
            mesh_simplify=0.95,
            texture_size=1024,
            api_name="/extract_glb",
        )
        info["times"]["extract_glb"] = round(time.time() - t0, 1)
        glb_path = None
        if isinstance(glb_result, (list, tuple)):
            for r in glb_result:
                if isinstance(r, str) and r.endswith(".glb"):
                    glb_path = r
                    break
        elif isinstance(glb_result, str) and glb_result.endswith(".glb"):
            glb_path = glb_result
        if glb_path:
            shutil.copy(glb_path, out_dir / f"{sku}.glb")
            info["glb"] = f"{sku}.glb"
    except Exception as e:
        info["status"] = f"extract_glb_failed: {e}"
        return info

    # Extract 7 angle frames from preview.mp4 at 0/15/30/45/60/75/90 deg
    if "preview_mp4" in info:
        for i, frame_idx in enumerate([0, 5, 10, 15, 20, 25, 30]):
            out_png = out_dir / f"angle_{i+1:02d}.png"
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(out_dir / "preview.mp4"),
                     "-vf", f"select='eq(n\\,{frame_idx})',scale=512:-1",
                     "-vframes", "1", str(out_png)],
                    check=True, capture_output=True,
                )
            except subprocess.CalledProcessError:
                pass

    info["status"] = "ok"
    return info


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sources = discover_skus()
    print(f"Found {len(sources)} sources to process.")

    print(f"Connecting to {SPACE}...")
    client = Client(SPACE)
    print("Connected.")

    try:
        client.predict(api_name="/start_session")
    except Exception as e:
        print(f"start_session warn: {e}")

    results = []
    overall_t0 = time.time()
    for i, src in enumerate(sources, 1):
        sku = src.parent.name
        print(f"\n=== [{i}/{len(sources)}] {sku} ===")
        sku_out = OUT_DIR / sku
        t0 = time.time()
        info = run_one(client, sku, src, sku_out)
        info["elapsed"] = round(time.time() - t0, 1)
        if info["status"] == "ok":
            print(f"  ok in {info['elapsed']}s  preprocess={info['times'].get('preprocess')}s  "
                  f"i2_3d={info['times'].get('image_to_3d')}s  glb={info['times'].get('extract_glb')}s")
        else:
            print(f"  FAILED: {info['status']}")
        results.append(info)

    total = round(time.time() - overall_t0, 1)
    print(f"\n=== batch done in {total}s ({total/60:.1f} min) ===")

    (OUT_DIR / "results.json").write_text(json.dumps(results, indent=2))
    print(f"results.json written")

    print(f"\n{'SKU':<24} {'status':<14} {'elapsed':>8}")
    print("-" * 50)
    for r in results:
        print(f"{r['sku']:<24} {r['status']:<14} {r.get('elapsed', '-'):>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
