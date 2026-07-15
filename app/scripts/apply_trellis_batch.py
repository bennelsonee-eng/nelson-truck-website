"""Run the priority plow batch through Microsoft TRELLIS HuggingFace Space.

Per SKU, ~30 sec end-to-end (preprocess + image_to_3d + extract_glb).
Saves .glb mesh + preview.mp4 turntable + 7 angle frames (0/15/30/45/60/75/90 deg)
for each plow.  Then prints a summary table and writes review HTML.

Usage:
    python apply_trellis_batch.py                       # all 9
    python apply_trellis_batch.py --skus WEST-HTS76-EQP # subset
    python apply_trellis_batch.py --resume              # skip SKUs already done
"""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path

# Use certifi's CA bundle to avoid Windows SSL CERTIFICATE_VERIFY_FAILED on HF
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
except ImportError:
    pass

from gradio_client import Client, handle_file


REPO = Path(__file__).resolve().parents[2]
SKUS_DIR = REPO / "app" / "backend" / "static" / "snow-plows" / "skus"
OUTPUT_DIR = REPO / "wan_test_output" / "trellis_batch"

SPACE = "microsoft/TRELLIS"

# 9 plows.  WEST-MVP3MS86-EQP already done in earlier session (preview test dir).
PRIORITY_PLOWS = [
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


def best_source(sku: str) -> Path | None:
    sku_dir = SKUS_DIR / sku
    for fname in ["hero_manufacturer.jpg", "hero.jpg"]:
        p = sku_dir / fname
        if p.exists():
            return p
    return None


def extract_angle_frames(mp4_path: Path, out_dir: Path) -> list[Path]:
    """Pull 7 frames at 0/15/30/45/60/75/90 deg from the 120-frame turntable.
    The auto-generated preview is 360 deg over 120 frames, so 3 deg/frame.
    """
    frames = []
    # frame indices: 0, 5, 10, 15, 20, 25, 30 -> degrees 0, 15, 30, 45, 60, 75, 90
    for i, frame_idx in enumerate([0, 5, 10, 15, 20, 25, 30]):
        out_png = out_dir / f"angle_{i+1:02d}.png"
        cmd = [
            "ffmpeg", "-y", "-i", str(mp4_path),
            "-vf", f"select='eq(n\\,{frame_idx})',scale=512:-1",
            "-vframes", "1",
            str(out_png),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            frames.append(out_png)
        except subprocess.CalledProcessError as e:
            print(f"        ffmpeg failed at frame {frame_idx}: {e.stderr.decode()[:200]}")
    return frames


def build_angle_grid(frames: list[Path], out_path: Path, label: str):
    from PIL import Image, ImageDraw, ImageFont
    angles = [0, 15, 30, 45, 60, 75, 90]
    TILE = 320
    LABEL_H = 32
    COLS = 4
    rows = (len(frames) + COLS - 1) // COLS
    grid = Image.new("RGB", (COLS * TILE, rows * (TILE + LABEL_H) + 36), (30, 30, 30))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("arialbd.ttf", 20)
        font_h = ImageFont.truetype("arialbd.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
        font_h = font
    draw.text((12, 8), label, fill=(255, 224, 74), font=font_h)
    for i, (ang, fn) in enumerate(zip(angles, frames)):
        if not fn.exists():
            continue
        try:
            img = Image.open(fn).convert("RGB")
        except Exception:
            continue
        img.thumbnail((TILE, TILE))
        r, c = divmod(i, COLS)
        x = c * TILE + (TILE - img.width) // 2
        y = r * (TILE + LABEL_H) + (TILE - img.height) // 2 + 36
        grid.paste(img, (x, y))
        label_y = r * (TILE + LABEL_H) + TILE + 36
        draw.rectangle([c*TILE, label_y, (c+1)*TILE, label_y + LABEL_H], fill=(20, 20, 20))
        draw.text((c*TILE + 12, label_y + 6), f"{ang} deg", fill=(255, 224, 74), font=font)
    grid.save(out_path)


def run_one(client: Client, sku: str, src: Path, out_dir: Path) -> dict:
    """Returns dict of timings, status, paths."""
    info: dict = {"sku": sku, "src": str(src), "status": "", "times": {}}
    out_dir.mkdir(parents=True, exist_ok=True)

    # preprocess
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

    # image_to_3d
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
        # result is (video_path, state) typically
        if isinstance(result_3d, (list, tuple)):
            for r in result_3d:
                if isinstance(r, str) and r.endswith((".mp4", ".webm")):
                    out_mp4 = out_dir / "preview.mp4"
                    shutil.copy(r, out_mp4)
                    info["preview_mp4"] = str(out_mp4)
                    break
                elif isinstance(r, dict) and "video" in r:
                    vp = r["video"]
                    if isinstance(vp, dict) and "path" in vp:
                        vp = vp["path"]
                    if vp and Path(vp).exists():
                        out_mp4 = out_dir / "preview.mp4"
                        shutil.copy(vp, out_mp4)
                        info["preview_mp4"] = str(out_mp4)
                        break
    except Exception as e:
        info["status"] = f"image_to_3d_failed: {e}"
        return info

    # extract_glb
    t0 = time.time()
    try:
        glb_result = client.predict(
            mesh_simplify=0.95,
            texture_size=1024,
            api_name="/extract_glb",
        )
        info["times"]["extract_glb"] = round(time.time() - t0, 1)
        if isinstance(glb_result, (list, tuple)):
            for i, r in enumerate(glb_result):
                if isinstance(r, str) and r.endswith(".glb"):
                    out_glb = out_dir / f"{sku}.glb"
                    shutil.copy(r, out_glb)
                    info["glb"] = str(out_glb)
                    break
        elif isinstance(glb_result, str) and glb_result.endswith(".glb"):
            out_glb = out_dir / f"{sku}.glb"
            shutil.copy(glb_result, out_glb)
            info["glb"] = str(out_glb)
    except Exception as e:
        info["status"] = f"extract_glb_failed: {e}"
        return info

    # extract angle frames + grid
    if "preview_mp4" in info:
        frames = extract_angle_frames(Path(info["preview_mp4"]), out_dir)
        if frames:
            grid_path = out_dir / "_angles_grid.png"
            build_angle_grid(frames, grid_path, sku)
            info["angle_grid"] = str(grid_path)

    info["status"] = "ok"
    return info


def main() -> int:
    args = sys.argv[1:]
    skus = list(PRIORITY_PLOWS)
    resume = "--resume" in args
    if "--skus" in args:
        skus = args[args.index("--skus") + 1].split(",")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Connecting to {SPACE}...")
    client = Client(SPACE)
    print("Connected.\n")

    # start session
    try:
        client.predict(api_name="/start_session")
    except Exception as e:
        print(f"  start_session warn: {e}")

    results: list[dict] = []
    overall_t0 = time.time()
    for i, sku in enumerate(skus, 1):
        print(f"=== [{i}/{len(skus)}] {sku} ===")
        sku_out = OUTPUT_DIR / sku
        if resume and (sku_out / f"{sku}.glb").exists():
            print(f"  skip (already have .glb)")
            results.append({"sku": sku, "status": "skipped"})
            continue
        src = best_source(sku)
        if src is None:
            print(f"  ! no source found")
            results.append({"sku": sku, "status": "no_source"})
            continue
        print(f"  source: {src.name} ({src.stat().st_size // 1024} KB)")
        t0 = time.time()
        info = run_one(client, sku, src, sku_out)
        elapsed = round(time.time() - t0, 1)
        info["elapsed"] = elapsed
        if info["status"] == "ok":
            print(f"  done in {elapsed}s  preprocess={info['times'].get('preprocess')}s  "
                  f"i2_3d={info['times'].get('image_to_3d')}s  glb={info['times'].get('extract_glb')}s")
        else:
            print(f"  FAILED: {info['status']}")
        results.append(info)

    total = round(time.time() - overall_t0, 1)
    print(f"\n=== batch done in {total}s ({total/60:.1f} min) ===")

    # write results.json
    (OUTPUT_DIR / "results.json").write_text(json.dumps(results, indent=2))
    print(f"results.json -> {OUTPUT_DIR / 'results.json'}")

    # summary table
    print(f"\n{'SKU':<24} {'status':<10} {'elapsed':>8}")
    print("-" * 46)
    for r in results:
        print(f"{r['sku']:<24} {r['status']:<10} {r.get('elapsed', '-'):>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
