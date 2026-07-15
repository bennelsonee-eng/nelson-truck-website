"""FLUX Kontext service — talks to ComfyUI on the Linux llama to render
"plow on truck" composites.

Pipeline:
  1. POST the customer's truck image to ComfyUI /upload/image — returns a filename
  2. POST a Kontext workflow JSON to /prompt — uses the uploaded filename via LoadImage
  3. Poll /history/<prompt_id> until completed
  4. Download the resulting image via /view
  5. Return PNG bytes to the caller (router writes them to /static/renders/)

All ComfyUI nodes used here are built-in (no custom node deps):
  LoadImage, VAEEncode, ReferenceLatent, FluxGuidance, KSampler, VAEDecode,
  SaveImage, UNETLoader, DualCLIPLoader, VAELoader, CLIPTextEncode.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import uuid
from dataclasses import dataclass

import httpx
from PIL import Image


log = logging.getLogger(__name__)


COMFY_URL = "http://100.85.94.57:8188"   # llama IP via Tailscale
KONTEXT_MODEL = "flux1-dev-kontext_fp8_scaled.safetensors"
DEFAULT_TIMEOUT_S = 180  # rendering can take 30-90 sec; allow buffer


@dataclass(frozen=True)
class KontextResult:
    ok: bool
    image_bytes: bytes | None
    duration_ms: int
    error: str | None = None


def _build_workflow(
    truck_filename: str,
    prompt: str,
    plow_filename: str | None = None,
    seed: int = 42,
    steps: int = 20,
    guidance: float = 2.5,
) -> dict:
    """ComfyUI workflow for FLUX Kontext.

    Mode 1 (text-only): single truck image + text prompt describing plow.
    Mode 2 (multi-image): truck + clean plow-only reference image.  Two
    ReferenceLatent nodes chained — model uses BOTH inputs as references
    when generating the edited output.

    Use multi-image mode only with whitelisted plow refs (see
    plow_reference_whitelist.py) — feeding a truck-contaminated plow extract
    will scramble the output.
    """
    workflow: dict = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": KONTEXT_MODEL, "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
            "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "flux-vae-bf16.safetensors"}},
        # Load truck image
        "4": {"class_type": "LoadImage", "inputs": {
            "image": truck_filename, "upload": "image"}},
        "5": {"class_type": "VAEEncode", "inputs": {
            "pixels": ["4", 0], "vae": ["3", 0]}},
        # Positive prompt
        "7": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["2", 0], "text": prompt}},
        # FluxGuidance
        "8": {"class_type": "FluxGuidance", "inputs": {
            "conditioning": ["7", 0], "guidance": guidance}},
    }
    # First ReferenceLatent: truck identity
    workflow["6"] = {"class_type": "ReferenceLatent", "inputs": {
        "conditioning": ["8", 0], "latent": ["5", 0]}}

    cond_id = "6"
    if plow_filename:
        # Multi-image mode: also load + reference the clean plow image
        workflow["13"] = {"class_type": "LoadImage", "inputs": {
            "image": plow_filename, "upload": "image"}}
        workflow["14"] = {"class_type": "VAEEncode", "inputs": {
            "pixels": ["13", 0], "vae": ["3", 0]}}
        # Second ReferenceLatent chains on top of the first — both refs feed
        # into the conditioning
        workflow["15"] = {"class_type": "ReferenceLatent", "inputs": {
            "conditioning": ["6", 0], "latent": ["14", 0]}}
        cond_id = "15"

    # Negative
    workflow["9"] = {"class_type": "CLIPTextEncode", "inputs": {
        "clip": ["2", 0], "text": ""}}
    # Sampler — uses truck latent as the start (so output preserves truck framing)
    workflow["10"] = {"class_type": "KSampler", "inputs": {
        "model": ["1", 0],
        "positive": [cond_id, 0],
        "negative": ["9", 0],
        "latent_image": ["5", 0],
        "seed": seed, "steps": steps, "cfg": 1.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
    }}
    workflow["11"] = {"class_type": "VAEDecode", "inputs": {
        "samples": ["10", 0], "vae": ["3", 0]}}
    workflow["12"] = {"class_type": "SaveImage", "inputs": {
        "images": ["11", 0], "filename_prefix": "kontext_render"}}
    return workflow


async def _upload_image_to_comfy(client: httpx.AsyncClient, img: Image.Image) -> str:
    """Upload a PIL image to ComfyUI's /upload/image endpoint.
    Returns the filename ComfyUI assigned (used in LoadImage)."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    fname = f"titan_truck_{uuid.uuid4().hex[:12]}.png"
    files = {"image": (fname, buf, "image/png")}
    data = {"overwrite": "true", "type": "input"}
    r = await client.post(f"{COMFY_URL}/upload/image", files=files, data=data)
    r.raise_for_status()
    payload = r.json()
    return payload.get("name", fname)


async def render_plow_on_truck(
    *,
    truck_image: Image.Image,
    plow_brand: str,
    plow_model: str,
    plow_blade_type: str = "V-plow",
    plow_reference_image: Image.Image | None = None,
    seed: int = 42,
    steps: int = 20,
    guidance: float = 2.5,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> KontextResult:
    """Render the customer's truck with a plow attached via FLUX Kontext.

    Two modes:
      - Text-only: plow_reference_image=None.  Kontext renders the plow from
        text description.  Generic-looking but works for any SKU.
      - Multi-image: plow_reference_image is a CLEAN plow-only PNG (no truck
        in the background).  Kontext uses it as a visual reference, giving
        SKU-accurate plow appearance.  Use only with whitelisted SKUs.

    Returns the rendered image bytes (PNG) on success, or an error.
    Never raises — always returns KontextResult.
    """
    t0 = time.time()
    if plow_reference_image is not None:
        prompt = (
            f"Take the snow plow shown in the second image and mount it to "
            f"the front bumper of the truck in the first image. The plow "
            f"should sit at proper height with the cutting edge near ground "
            f"level. Keep the truck completely unchanged. Photorealistic, "
            f"matching the truck's lighting and perspective."
        )
    else:
        prompt = (
            f"Add a {plow_brand} {plow_model} {plow_blade_type} mounted to "
            f"the front bumper of this truck. The plow should sit at proper "
            f"height, with the cutting edge near ground level. Keep the truck "
            f"unchanged. Photorealistic, matching the truck's lighting and "
            f"perspective."
        )

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            # 1. Upload truck image
            truck_filename = await _upload_image_to_comfy(client, truck_image)
            # 1b. Optionally upload plow reference too
            plow_filename: str | None = None
            if plow_reference_image is not None:
                plow_filename = await _upload_image_to_comfy(client, plow_reference_image)

            # 2. Build + queue workflow (single or multi-image)
            workflow = _build_workflow(truck_filename, prompt,
                                       plow_filename=plow_filename,
                                       seed=seed, steps=steps, guidance=guidance)
            r = await client.post(
                f"{COMFY_URL}/prompt",
                json={"prompt": workflow, "client_id": str(uuid.uuid4())},
            )
            if r.status_code >= 400:
                return KontextResult(ok=False, image_bytes=None,
                                     duration_ms=int((time.time() - t0) * 1000),
                                     error=f"prompt rejected: {r.text[:400]}")
            prompt_id = r.json()["prompt_id"]

            # 3. Poll history
            while time.time() - t0 < timeout_s:
                await asyncio.sleep(2)
                h = await client.get(f"{COMFY_URL}/history/{prompt_id}")
                history = h.json()
                if prompt_id in history and history[prompt_id].get("status", {}).get("completed"):
                    for node_output in history[prompt_id].get("outputs", {}).values():
                        imgs = node_output.get("images", [])
                        if not imgs:
                            continue
                        first = imgs[0]
                        view_url = (
                            f"{COMFY_URL}/view?filename={first['filename']}"
                            f"&subfolder={first.get('subfolder','')}&type=output"
                        )
                        img_r = await client.get(view_url)
                        return KontextResult(
                            ok=True,
                            image_bytes=img_r.content,
                            duration_ms=int((time.time() - t0) * 1000),
                        )
                    return KontextResult(ok=False, image_bytes=None,
                                         duration_ms=int((time.time() - t0) * 1000),
                                         error="completed but no image in history")

            return KontextResult(ok=False, image_bytes=None,
                                 duration_ms=int((time.time() - t0) * 1000),
                                 error=f"timeout after {timeout_s}s")
        except Exception as e:
            log.exception("[flux_kontext] render failed")
            return KontextResult(ok=False, image_bytes=None,
                                 duration_ms=int((time.time() - t0) * 1000),
                                 error=str(e))


async def health_check() -> bool:
    """Quick check: is ComfyUI on the llama reachable?"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{COMFY_URL}/system_stats")
            return r.status_code == 200
    except Exception:
        return False
