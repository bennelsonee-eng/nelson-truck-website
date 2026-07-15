"""Configurator API — "see this plow on my truck" via FLUX Kontext.

Endpoints:
  POST /api/configurator/render-on-truck
      Accept truck image (uploaded or preset class) + plow SKU + YMM data,
      log the request, call FLUX Kontext on the llama, return rendered URL.

  GET  /api/configurator/render/{request_id}
      Poll endpoint — returns status + URL once rendering is complete.

  GET  /api/configurator/recent-requests  (admin only)
      List recent render requests for the sales team to follow up on.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from PIL import Image
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.dependencies import get_current_user
from app.models import (
    Product,
    TruckRenderRequest,
    TruckRenderStatus,
    User,
)
from app.services.flux_kontext_service import (
    KontextResult,
    health_check,
    render_plow_on_truck,
)
from app.services.plow_reference_whitelist import is_clean_plow_reference


log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/configurator", tags=["configurator"])

# Where rendered images go on disk — served as /static/renders/...
STATIC_RENDERS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "renders"
STATIC_RENDERS_DIR.mkdir(parents=True, exist_ok=True)

# Where uploaded customer truck images go
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "trucks"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Preset truck renders we already have on disk (from FLUX-Schnell lineup)
PRESET_TRUCKS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "trucks" / "renders_3q"

# v5 PIL composites (truck + plow already roughly positioned).  When a customer
# picks a preset truck class + a plow we have a composite for, we feed the
# composite as the Kontext SEED image rather than the bare truck.  This dramatically
# improves output quality — Kontext upgrades the realism of the existing layout
# instead of trying to invent the mounted-plow scene from scratch.
COMPOSITES_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "trucks" / "composites_3q"

# Plow SKU library — used to fetch the clean reference image for multi-image Kontext
SKUS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "snow-plows" / "skus"


@router.get("/health")
async def configurator_health() -> dict[str, Any]:
    """Confirm the llama is reachable for FLUX Kontext renders."""
    is_reachable = await health_check()
    return {
        "comfy_reachable": is_reachable,
        "renders_dir": str(STATIC_RENDERS_DIR),
        "preset_trucks_available": [p.stem for p in PRESET_TRUCKS_DIR.glob("*.png")],
    }


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    return (
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
    )


@router.post("/render-on-truck")
async def render_on_truck(
    request: Request,
    plow_sku: str = Form(...),
    truck_class: str | None = Form(None),
    truck_image: UploadFile | None = File(None),
    year: int | None = Form(None),
    make: str | None = Form(None),
    model: str | None = Form(None),
    color: str | None = Form(None),
    customer_notes: str | None = Form(None),
    session_token: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Kick off a "plow on my truck" render request.

    The customer either:
      (a) Uploads a photo of their truck (truck_image), OR
      (b) Picks one of our preset truck classes (truck_class)

    YMM (year, make, model, color) is captured for sales-team follow-up
    even when the customer is anonymous.

    Returns immediately with a request_id; the actual render runs in the
    background.  Poll /api/configurator/render/{request_id} for the result.
    """
    # Resolve the source truck image
    seed_has_plow = False  # if True, skip plow ref downstream (seed already has one)
    if truck_image is not None:
        # Customer-uploaded photo — bare truck, will use multi-image with plow ref
        contents = await truck_image.read()
        try:
            pil_img = Image.open(BytesIO(contents)).convert("RGB")
        except Exception:
            raise HTTPException(status_code=400, detail="Could not parse uploaded image")

        # Save the upload so we keep a record of what they sent
        upload_id = uuid.uuid4().hex
        upload_path = UPLOADS_DIR / f"{upload_id}.png"
        pil_img.save(upload_path)
        truck_image_url = f"/static/uploads/trucks/{upload_id}.png"
        truck_class_resolved: str | None = None
    elif truck_class:
        # Prefer the v5 PIL COMPOSITE if it exists for this truck class.
        # The composite has the plow already positioned correctly — Kontext
        # just upgrades the realism rather than inventing the layout.
        composite_path = COMPOSITES_DIR / f"{truck_class}_with_mvp3.png"
        preset_path = PRESET_TRUCKS_DIR / f"{truck_class}.png"
        if composite_path.exists():
            pil_img = Image.open(composite_path).convert("RGB")
            truck_image_url = f"/static/trucks/composites_3q/{truck_class}_with_mvp3.png"
            seed_has_plow = True  # skip plow reference downstream — would confuse the model
            log.info("[render-on-truck] using v5 PIL composite as seed for %s", truck_class)
        elif preset_path.exists():
            pil_img = Image.open(preset_path).convert("RGB")
            truck_image_url = f"/static/trucks/renders_3q/{truck_class}.png"
            seed_has_plow = False
            log.info("[render-on-truck] using bare 3/4 render as seed for %s", truck_class)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown truck_class '{truck_class}'. "
                       f"Valid: {[p.stem for p in PRESET_TRUCKS_DIR.glob('*.png')]}",
            )
        truck_class_resolved = truck_class
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either truck_image (upload) or truck_class (preset)",
        )

    # Look up plow brand + model — try meta.json from the static SKU folder
    # (the snow-plow catalog source of truth), falling back to product table.
    plow_meta_path = SKUS_DIR / plow_sku / "meta.json"
    plow_brand: str = "Western"
    plow_model: str = plow_sku
    if plow_meta_path.exists():
        try:
            import json as _json
            meta = _json.loads(plow_meta_path.read_text(encoding="utf-8"))
            plow_brand = meta.get("brand") or plow_brand
            plow_model = meta.get("title") or meta.get("product_series_title") or plow_model
        except Exception:
            log.exception("[render-on-truck] failed to read plow meta for %s", plow_sku)
    else:
        # Fall back to product table look-up (won't match for catalog SKUs)
        prod = (await db.execute(
            select(Product).where(Product.sku == plow_sku).limit(1)
        )).scalars().first()
        if prod is None:
            raise HTTPException(status_code=404, detail=f"Plow SKU '{plow_sku}' not found")
        plow_brand = prod.brand.name if prod.brand else "Western"
        plow_model = prod.name or plow_sku

    # Insert a pending request row — we have a row to update with results later
    user_agent, ip_address = _client_meta(request)
    req = TruckRenderRequest(
        customer_id=None,  # extend later when we wire customer auth
        user_id=user.id if user else None,
        session_token=session_token,
        year=year,
        make=make,
        model=model,
        color=color,
        truck_image_url=truck_image_url,
        truck_class=truck_class_resolved,
        plow_sku=plow_sku,
        status=TruckRenderStatus.PENDING,
        user_agent=user_agent,
        ip_address=ip_address,
        customer_notes=customer_notes,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    # Kick off the render in the background
    asyncio.create_task(_run_render_task(
        request_id=req.id,
        truck_image=pil_img,
        plow_sku=plow_sku,
        plow_brand=plow_brand,
        plow_model=plow_model,
        seed_has_plow=seed_has_plow,
    ))

    return {
        "request_id": req.id,
        "status": req.status.value,
        "poll_url": f"/api/configurator/render/{req.id}",
        "message": "Render queued — typically 30-60 seconds. Poll for status.",
    }


@router.get("/render/{request_id}")
async def get_render(request_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Poll endpoint — returns status + URL once render completes."""
    req = (await db.execute(
        select(TruckRenderRequest).where(TruckRenderRequest.id == request_id)
    )).scalars().first()
    if req is None:
        raise HTTPException(status_code=404, detail="Render request not found")
    return {
        "request_id": req.id,
        "status": req.status.value,
        "rendered_image_url": req.rendered_image_url,
        "render_duration_ms": req.render_duration_ms,
        "error_message": req.error_message,
        "ymm": {
            "year": req.year,
            "make": req.make,
            "model": req.model,
            "color": req.color,
        },
        "plow_sku": req.plow_sku,
    }


@router.get("/recent-requests")
async def recent_requests(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List recent render requests — for sales team follow-up."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    rows = (await db.execute(
        select(TruckRenderRequest)
        .order_by(desc(TruckRenderRequest.created_at))
        .limit(limit)
    )).scalars().all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "ymm": {"year": r.year, "make": r.make, "model": r.model, "color": r.color},
            "plow_sku": r.plow_sku,
            "status": r.status.value,
            "rendered_image_url": r.rendered_image_url,
            "customer_notes": r.customer_notes,
        }
        for r in rows
    ]


async def _run_render_task(
    *,
    request_id: int,
    truck_image: Image.Image,
    plow_sku: str,
    plow_brand: str,
    plow_model: str,
    seed_has_plow: bool = False,
) -> None:
    """Background task: call FLUX Kontext + save result + update DB row.

    seed_has_plow: True when truck_image is the v5 PIL composite (already has a
    plow positioned).  In that case we DON'T pass a plow reference image —
    Kontext just upgrades the realism of the existing layout.  Variant C from
    test_kontext_pil_seed.py — the winning approach.
    """
    log.info("[render-task] starting request=%d sku=%s", request_id, plow_sku)
    # Mark rendering
    async with async_session() as db:
        req = await db.get(TruckRenderRequest, request_id)
        if req is None:
            log.error("[render-task] request %d gone before we could render", request_id)
            return
        req.status = TruckRenderStatus.RENDERING
        await db.commit()

    # Pick blade type from SKU/name (heuristic)
    name_lower = (plow_model or "").lower()
    if "v-plow" in name_lower or "super-v" in name_lower or "mvp" in name_lower:
        blade_type = "V-plow with two angled wings in scoop position"
    elif "expandable" in name_lower or "wing" in name_lower:
        blade_type = "expandable wing plow"
    else:
        blade_type = "straight blade plow"

    # Plow reference image: ONLY used if the seed image doesn't already have
    # a plow.  When seed_has_plow=True (PIL composite seed), passing a plow
    # reference confuses Kontext — variant D in test_kontext_pil_seed.py
    # underperformed variant C.
    plow_reference: Image.Image | None = None
    if not seed_has_plow:
        plow_ref_path = SKUS_DIR / plow_sku / "hero_transparent.png"
        if plow_ref_path.exists() and is_clean_plow_reference(plow_sku):
            try:
                plow_reference = Image.open(plow_ref_path).convert("RGBA")
                log.info("[render-task] using plow ref image for sku=%s", plow_sku)
            except Exception:
                log.exception("[render-task] failed to load plow reference for sku=%s", plow_sku)
                plow_reference = None
    else:
        log.info("[render-task] seed already has plow; skipping plow ref (variant C path)")

    # Tune the prompt based on which mode we're in.  When seeding with a PIL
    # composite, Kontext just needs to "make this realistic".  When building
    # from a bare truck, Kontext needs to "add a plow".
    #
    # IMPORTANT: include an explicit text-preservation instruction.  Kontext
    # otherwise sometimes garbles "WESTERN" -> "WoSTAID" / "WE FERN" / etc.
    # Variants A and B in test_kontext_text_preservation.py both worked, but
    # B's explicit text-preservation prompt is more robust across re-rolls.
    if seed_has_plow:
        kontext_prompt_extra = (
            "make this photorealistic, professional automotive product "
            "photography, matching studio lighting and shadows. "
            "Keep all text on the plow exactly as shown. The WESTERN logo "
            "and any model badge must remain unchanged and clearly readable."
        )
    else:
        kontext_prompt_extra = blade_type

    result: KontextResult = await render_plow_on_truck(
        truck_image=truck_image,
        plow_brand=plow_brand,
        plow_model=plow_model,
        plow_blade_type=kontext_prompt_extra,
        plow_reference_image=plow_reference,
    )

    # Update DB with result
    async with async_session() as db:
        req = await db.get(TruckRenderRequest, request_id)
        if req is None:
            return
        req.render_duration_ms = result.duration_ms
        if result.ok and result.image_bytes:
            out_path = STATIC_RENDERS_DIR / f"render_{request_id}.png"
            out_path.write_bytes(result.image_bytes)
            req.rendered_image_url = f"/static/renders/render_{request_id}.png"
            req.status = TruckRenderStatus.COMPLETE
        else:
            req.status = TruckRenderStatus.FAILED
            req.error_message = result.error
        await db.commit()
        log.info("[render-task] done request=%d status=%s duration=%dms",
                 request_id, req.status.value, result.duration_ms)
