"""Render trucks via FLUX.1 [dev] using the user's universal prompt template
and directional-language angle phrasing.

Class list (27 makes across 6 classes):
  Mid-size  : Tacoma, Colorado, Ranger, Liberty, Renegade, Tahoe
  1/2-ton   : Chevy 1500, F-150, Tundra, Ram 1500, Titan, GMC 1500
  3/4-ton   : Chevy 2500, F-250 SD, Ram 2500, GMC 2500
  1-ton     : Chevy 3500, F-350 SD DRW, Ram 3500, GMC 3500
  4500      : F-450, Chevy 4500, Isuzu NPR
  5500      : F-550, F-650, Chevy 6500, Isuzu NRR

Pure prompt (no ControlNet) — relying on FLUX-dev's better prompt adherence
for "angled X degrees to the left/right" phrasing.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import uuid
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_composite import perspective_rotate_css  # type: ignore[import-not-found]

COMFY = "http://100.85.94.57:8188"
REPO = Path(__file__).resolve().parents[1].parent
TRUCKS_HEADON = REPO / "app" / "backend" / "static" / "trucks" / "renders"
TRUCKS_3Q = REPO / "app" / "backend" / "static" / "trucks" / "renders_3q_mirrored"
# Per-make user-provided reference photos (e.g. ram_1500_0deg.png).
# build_canny_for_angle() checks here first; falls back to class-level on miss.
USER_REFS = REPO / "refs"
OUT_BASE = REPO / "app" / "backend" / "static" / "trucks" / "renders_flux_dev"
CANNY_DEBUG_DIR = REPO / "app" / "backend" / "static" / "trucks" / "renders_by_angle" / "_canny_refs"

# (slug, brand, model, color, class_label, vehicle_kind)
# vehicle_kind: "pickup truck" | "SUV" | "cab-over commercial truck"
# Drives prompt phrasing — "The {vehicle_kind} is painted..."
MAKES = {
    "mid-size": [
        ("toyota_tacoma",  "Toyota",     "Tacoma TRD",                          "silver",     "mid-size pickup",  "pickup truck"),
        ("chevy_colorado", "Chevrolet",  "Colorado",                            "silver",     "mid-size pickup",  "pickup truck"),
        ("ford_ranger",    "Ford",       "Ranger",                              "silver",     "mid-size pickup",  "pickup truck"),
        ("jeep_liberty",   "Jeep",       "Liberty",                             "silver",     "mid-size SUV with a boxy upright stance",  "SUV"),
        ("jeep_renegade",  "Jeep",       "Renegade Trailhawk",                  "silver",     "compact crossover SUV with seven-slot Jeep grille",  "SUV"),
        ("chevy_tahoe",    "Chevrolet",  "Tahoe",                               "silver",     "full-size SUV",    "SUV"),
    ],
    "1500": [
        ("chevy_1500",     "Chevrolet",  "Silverado 1500",                      "white",      "1/2-ton pickup",   "pickup truck"),
        ("ford_f150",      "Ford",       "F-150",                               "white pearl","1/2-ton pickup",   "pickup truck"),
        # Tundra is the larger, beefier full-size sibling of the Tacoma
        ("toyota_tundra",  "Toyota",     "Tundra full-size",                    "white",      "large 1/2-ton pickup, beefier and more imposing than the Tacoma",  "pickup truck"),
        # Use Dodge Ram branding (classic crosshair grille) to disambiguate
        ("ram_1500",       "Dodge",      "Ram 1500",                            "white",      "1/2-ton pickup with classic Dodge crosshair grille",  "pickup truck"),
        ("nissan_titan",   "Nissan",     "Titan",                               "white",      "1/2-ton pickup",   "pickup truck"),
        ("gmc_1500",       "GMC",        "Sierra 1500",                         "white",      "1/2-ton pickup",   "pickup truck"),
    ],
    "2500": [
        ("chevy_2500",     "Chevrolet",  "Silverado 2500 HD",                   "white",      "3/4-ton pickup",   "pickup truck"),
        ("ford_f250",      "Ford",       "F-250 Super Duty",                    "silver",     "3/4-ton pickup",   "pickup truck"),
        ("ram_2500",       "Ram",        "2500 Heavy Duty",                     "white",      "3/4-ton pickup",   "pickup truck"),
        ("gmc_2500",       "GMC",        "Sierra 2500 HD",                      "white",      "3/4-ton pickup",   "pickup truck"),
    ],
    "3500": [
        ("chevy_3500",     "Chevrolet",  "Silverado 3500 HD DRW",               "white",      "1-ton pickup with dual rear wheels",  "pickup truck"),
        ("ford_f350",      "Ford",       "F-350 Super Duty DRW",                "white",      "1-ton pickup with dual rear wheels",  "pickup truck"),
        ("ram_3500",       "Ram",        "3500 Heavy Duty DRW",                 "white",      "1-ton pickup with dual rear wheels",  "pickup truck"),
        ("gmc_3500",       "GMC",        "Sierra 3500 HD DRW",                  "white",      "1-ton pickup with dual rear wheels",  "pickup truck"),
    ],
    "4500": [
        ("ford_f450",      "Ford",       "F-450 Super Duty Chassis Cab",        "white",      "medium-duty truck with service body",  "pickup truck"),
        ("chevy_4500",     "Chevrolet",  "Silverado 4500 HD Chassis Cab",       "white",      "medium-duty truck with service body",  "pickup truck"),
        # Isuzu NPR is a CAB-OVER-ENGINE commercial vehicle — short snub nose, cab sits above engine
        ("isuzu_npr",      "Isuzu",      "NPR",                                  "white",      "cab-over-engine medium-duty commercial truck, flat snub-nose front, cab sits directly above the engine, no extended hood",  "cab-over commercial truck"),
    ],
    "5500": [
        ("ford_f550",      "Ford",       "F-550 Super Duty Chassis Cab",        "white",      "medium-duty truck with service body",  "pickup truck"),
        ("ford_f650",      "Ford",       "F-650 Commercial",                    "white",      "medium-duty commercial truck",  "pickup truck"),
        ("chevy_6500",     "Chevrolet",  "Silverado 6500 HD Chassis Cab",       "white",      "heavy-medium-duty commercial truck",  "pickup truck"),
        ("isuzu_nrr",      "Isuzu",      "NRR",                                  "white",      "cab-over-engine heavy-medium-duty commercial truck, flat snub-nose front, cab sits directly above the engine, no extended hood",  "cab-over commercial truck"),
    ],
}

ANGLES = {
    "-30deg": "angled 30 degrees to the left",
    "0deg":   "straight-on centered front view",
    "+30deg": "angled 30 degrees to the right",
}


def make_canny(img: Image.Image, low: int = 50, high: int = 150) -> Image.Image:
    arr = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, low, high)
    return Image.fromarray(np.stack([edges, edges, edges], axis=-1))


def build_canny_for_angle(cls: str, angle_name: str, make_slug: str | None = None) -> Image.Image:
    """Build canny edge map for (class, angle). If a per-make ref exists at
    USER_REFS/<slug>_<angle>.png, use it; otherwise fall back to class-level."""
    if make_slug:
        override = USER_REFS / f"{make_slug}_{angle_name}.png"
        if override.exists():
            return make_canny(Image.open(override))

    headon_src = TRUCKS_HEADON / f"{cls}.png"
    threeq_src = TRUCKS_3Q / f"{cls}.png"

    if angle_name == "0deg":
        return make_canny(Image.open(headon_src))
    if angle_name == "+30deg":
        return make_canny(Image.open(threeq_src))
    if angle_name == "-30deg":
        return make_canny(Image.open(threeq_src)).transpose(Image.FLIP_LEFT_RIGHT)
    if angle_name in ("+15deg", "-15deg"):
        deg = 15 if angle_name == "+15deg" else -15
        img = Image.open(headon_src).convert("RGB")
        W, H = img.size
        rotated, _, _ = perspective_rotate_css(
            img.convert("RGBA"), deg, anchor_x=W / 2, anchor_y=H / 2, perspective_d=900
        )
        rgb = Image.new("RGB", rotated.size, (200, 200, 200))
        rgb.paste(rotated, mask=rotated.split()[-1])
        return make_canny(rgb)
    raise ValueError(f"unknown angle: {angle_name}")


def upload_pil(client: httpx.Client, img: Image.Image, name: str) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    files = {"image": (name, buf, "image/png")}
    data = {"overwrite": "true"}
    r = client.post(f"{COMFY}/upload/image", files=files, data=data, timeout=60.0)
    r.raise_for_status()
    return r.json()["name"]


def make_prompt(brand: str, model: str, color: str, class_label: str, angle_phrase: str,
                vehicle_kind: str = "pickup truck") -> str:
    return (
        f"A high-resolution photorealistic professional studio shot of a 2024 {brand} {model}, "
        f"a {class_label}. Front-facing view, {angle_phrase}. "
        f"The {vehicle_kind} is painted in {color}, featuring a clean front grille and headlights. "
        f"Studio lighting with soft shadows, 8k resolution, cinematic composition, "
        f"neutral grey seamless background. No people, no plow, no snow."
    )


NEGATIVE = (
    "low quality, blurry, distorted, garbled text, watermark, badge overlay, "
    "people, snow, dirt, mud, motion blur, multiple vehicles, "
    "cropped, cartoon, illustration, painting"
)


def build_workflow(
    prompt: str, seed: int, canny_filename: str,
    steps: int = 16, controlnet_strength: float = 0.55,
    model_filename: str = "flux1-dev-fp8.safetensors",
) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": model_filename, "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux-vae-bf16.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": NEGATIVE}},
        "11": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["4", 0], "guidance": 3.5}},
        # ControlNet: canny conditioning for reliable angle
        "20": {"class_type": "ControlNetLoader", "inputs": {
            "control_net_name": "flux-controlnet-union.safetensors"}},
        "21": {"class_type": "SetUnionControlNetType", "inputs": {
            "control_net": ["20", 0],
            "type": "canny/lineart/anime_lineart/mlsd"}},
        "22": {"class_type": "LoadImage", "inputs": {"image": canny_filename}},
        "23": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["11", 0], "negative": ["5", 0],
            "control_net": ["21", 0], "image": ["22", 0], "vae": ["3", 0],
            "strength": controlnet_strength,
            "start_percent": 0.0, "end_percent": 0.85}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {
            "width": 1024, "height": 576, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["23", 0],
            "negative": ["23", 1],
            "latent_image": ["6", 0],
            "seed": seed,
            "steps": steps,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": "flux_dev_cn"}},
    }


def queue_and_wait(client: httpx.Client, workflow: dict) -> dict:
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
    r = client.post(f"{COMFY}/prompt", json=payload, timeout=30.0)
    if r.status_code >= 400:
        print(json.dumps(r.json(), indent=2))
        r.raise_for_status()
    prompt_id = r.json()["prompt_id"]
    while True:
        time.sleep(3)
        h = client.get(f"{COMFY}/history/{prompt_id}", timeout=15.0).json()
        if prompt_id in h:
            entry = h[prompt_id]
            if entry.get("status", {}).get("completed"):
                return entry
            err = entry.get("status", {}).get("status_str")
            if err == "error":
                print("PROMPT ERROR:")
                print(json.dumps(entry.get("status"), indent=2))
                raise RuntimeError("ComfyUI prompt failed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=16, help="FLUX-dev steps (16 fast, 20 quality)")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1337, 4242, 8888],
                    help="seed values to render")
    ap.add_argument("--only-class", help="render only this class (e.g., 'mid-size')")
    ap.add_argument("--only-make", help="render only this make slug (single)")
    ap.add_argument("--makes", help="comma-separated list of make slugs")
    ap.add_argument("--only-angle", help="render only this angle (e.g., '0deg')")
    args = ap.parse_args()

    OUT_BASE.mkdir(parents=True, exist_ok=True)
    CANNY_DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    # Filter classes for canny upload based on CLI flags so we don't upload
    # 30 refs when running a 1-truck smoke test.
    classes_in_run = [
        cls for cls in MAKES.keys()
        if not args.only_class or cls == args.only_class
    ]
    angles_in_run = [
        a for a in ANGLES.keys()
        if not args.only_angle or a == args.only_angle
    ]

    n_total = sum(
        len([m for m in makes if not args.only_make or m[0] == args.only_make])
        for cls, makes in MAKES.items() if cls in classes_in_run
    ) * len(angles_in_run) * len(args.seeds)
    n_done = 0
    t_start = time.time()

    with httpx.Client() as client:
        # Pre-pass: build + upload canny refs.
        # Per-make ref (refs/<slug>_<angle>.png) → upload one canny per (slug, angle).
        # No per-make ref → reuse a single class-level canny across all makes in that class.
        target_slugs = set(s.strip() for s in args.makes.split(",")) if args.makes else None

        def in_scope(cls: str, slug: str, angle_name: str) -> bool:
            if cls not in classes_in_run:
                return False
            if angle_name not in angles_in_run:
                return False
            if args.only_make and slug != args.only_make:
                return False
            if target_slugs is not None and slug not in target_slugs:
                return False
            return True

        canny_uploads: dict[tuple[str, str], str] = {}  # key: (make_slug or class_key, angle)
        class_key = lambda c: f"__class__:{c}"          # noqa: E731
        n_uploaded = 0
        for cls, makes in MAKES.items():
            for slug, *_ in makes:
                for angle_name in angles_in_run:
                    if not in_scope(cls, slug, angle_name):
                        continue
                    override = USER_REFS / f"{slug}_{angle_name}.png"
                    if override.exists():
                        key = (slug, angle_name)
                        label = f"{slug}@{angle_name} [per-make]"
                    else:
                        key = (class_key(cls), angle_name)
                        label = f"{cls}@{angle_name} [class fallback]"
                    if key in canny_uploads:
                        continue
                    canny = build_canny_for_angle(cls, angle_name, make_slug=slug)
                    local_name = f"{key[0]}_{angle_name.replace('+', 'p').replace('-', 'm')}.png"
                    canny.save(CANNY_DEBUG_DIR / local_name)
                    uploaded = upload_pil(client, canny, f"canny_{key[0]}_{angle_name}.png")
                    canny_uploads[key] = uploaded
                    n_uploaded += 1
                    print(f"  [{n_uploaded}] {label} -> {uploaded}")

        for cls, makes in MAKES.items():
            if args.only_class and cls != args.only_class:
                continue
            for slug, brand, model, color, class_label, vehicle_kind in makes:
                if args.only_make and slug != args.only_make:
                    continue
                if target_slugs is not None and slug not in target_slugs:
                    continue
                for angle_name, angle_phrase in ANGLES.items():
                    if args.only_angle and angle_name != args.only_angle:
                        continue
                    out_dir = OUT_BASE / angle_name
                    out_dir.mkdir(parents=True, exist_ok=True)
                    canny_filename = canny_uploads.get((slug, angle_name)) \
                        or canny_uploads[(class_key(cls), angle_name)]
                    for seed in args.seeds:
                        n_done += 1
                        out_path = out_dir / f"{slug}_seed{seed}.png"
                        if out_path.exists():
                            print(f"  [{n_done}/{n_total}] {slug}@{angle_name}/{seed}: skip (exists)")
                            continue
                        prompt = make_prompt(brand, model, color, class_label, angle_phrase, vehicle_kind)
                        t = time.time()
                        try:
                            wf = build_workflow(prompt, seed, canny_filename, steps=args.steps)
                            result = queue_and_wait(client, wf)
                        except Exception as e:
                            print(f"  [{n_done}/{n_total}] {slug}@{angle_name}/{seed}: FAILED — {e}")
                            continue
                        for node_output in result.get("outputs", {}).values():
                            imgs = node_output.get("images", [])
                            if not imgs:
                                continue
                            first = imgs[0]
                            url = (
                                f"{COMFY}/view?filename={first['filename']}"
                                f"&subfolder={first.get('subfolder','')}&type=output"
                            )
                            r = client.get(url, timeout=180.0)
                            out_path.write_bytes(r.content)
                            elapsed = time.time() - t
                            print(f"  [{n_done}/{n_total}] {slug}@{angle_name}/{seed}: "
                                  f"{elapsed:.1f}s ({len(r.content):,}B)")
                            break

    print(f"\nDone in {(time.time()-t_start)/60:.1f}min — output: {OUT_BASE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
