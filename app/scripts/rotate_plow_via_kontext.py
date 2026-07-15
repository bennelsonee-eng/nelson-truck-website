"""Use FLUX Kontext to rotate our existing MVP3 plow image to the opposite
camera angle, preserving WESTERN branding readability.

Direct Kontext call (not using the truck-mounting-prompt-wrapped service).
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image


REPO = Path(__file__).resolve().parents[2]

COMFY = "http://100.85.94.57:8188"
KONTEXT_MODEL = "flux1-dev-kontext_fp8_scaled.safetensors"


def build_workflow(input_filename: str, prompt: str, seed: int = 42,
                   steps: int = 20, guidance: float = 2.5) -> dict:
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
            "conditioning": ["7", 0], "guidance": guidance}},
        "6": {"class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["8", 0], "latent": ["5", 0]}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": ""}},
        "10": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0],
            "positive": ["6", 0],
            "negative": ["9", 0],
            "latent_image": ["5", 0],
            "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
        }},
        "11": {"class_type": "VAEDecode", "inputs": {
            "samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {
            "images": ["11", 0], "filename_prefix": "kontext_rotate_plow"}},
    }


async def run_kontext(client, prompt: str, plow_image: Image.Image, label: str) -> bytes | None:
    # Upload
    buf = io.BytesIO()
    plow_image.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    fname = f"plow_rotate_{uuid.uuid4().hex[:10]}.png"
    files = {"image": (fname, buf, "image/png")}
    data = {"overwrite": "true", "type": "input"}
    r = await client.post(f"{COMFY}/upload/image", files=files, data=data)
    r.raise_for_status()
    truck_filename = r.json().get("name", fname)

    workflow = build_workflow(truck_filename, prompt)
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
                return img_r.content
    return None


async def main() -> int:
    plow_path = REPO / "app" / "backend" / "static" / "snow-plows" / "skus" / "WEST-MVP3MS86-EQP" / "hero_transparent.png"
    plow = Image.open(plow_path).convert("RGB")
    print(f"Source plow: {plow.size}")

    prompts = [
        ("p1_camera_other_side", (
            "Show this exact same Western MVP3 V-plow from the opposite camera "
            "side. Camera position moves to the other side of the plow. "
            "WESTERN logo and branding remain clearly readable, not mirrored. "
            "Plow alone, white studio background, no truck."
        )),
        ("p2_mirror_camera", (
            "Mirror the camera angle on this plow. Same plow shown from the "
            "other viewpoint. WESTERN text stays correctly oriented and readable. "
            "Studio shot, white background, no truck."
        )),
        ("p3_op_right_view", (
            "Reposition the camera to the operator-right side of this plow. "
            "We see the plow from the right side now. WESTERN logo readable. "
            "White background, plow only, no truck."
        )),
    ]

    async with httpx.AsyncClient(timeout=200) as client:
        for label, prompt in prompts:
            print(f"\n[{label}]")
            t0 = time.time()
            result_bytes = await run_kontext(client, prompt, plow, label)
            elapsed = (time.time() - t0)
            if result_bytes:
                out_path = REPO / "wan_test_output" / f"PLOW_ROTATED_{label}.png"
                out_path.write_bytes(result_bytes)
                print(f"  saved: {out_path.name} ({elapsed:.1f}s)")
            else:
                print(f"  failed after {elapsed:.1f}s")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
