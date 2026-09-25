"""Trucks & equipment for sale -- the admin side (ADMIN role only).

Organised the way CommercialTruckTrader's dealer backend is, per Ben:
Inventory, Leads, Reports.

Inventory
  GET    /api/admin/units                    every listing, with photo/video/doc
                                             counts, views, leads and health
  POST   /api/admin/units                    new draft (optionally prefilled from
                                             an on-hand ERP part)
  GET    /api/admin/units/{id}               everything, including cost and the
                                             consignor
  PUT    /api/admin/units/{id}               save
  POST   /api/admin/units/{id}/status        publish / pending / sold / archive
  DELETE /api/admin/units/{id}               a draft is deleted, anything else archived
  media: chunked upload, poster frame, order, caption, delete
  GET    /api/admin/units/erp/search         find an on-hand part
  GET    /api/admin/units/erp/unlisted       on-hand units nobody has listed yet
  GET    /api/admin/units/vin/{vin}          NHTSA decode
  POST   /api/admin/units/parse-specs        pull fields out of a pasted spec sheet
Leads
  GET    /api/admin/unit-leads, PATCH /api/admin/unit-leads/{id}
Reports
  GET    /api/admin/units/reports
Build & Price price book
  GET/POST /api/admin/unit-price-guide, PUT/DELETE /api/admin/unit-price-guide/{id}
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models import User
from app.models.unit_listing import (DOC_TYPES, LEAD_STATUSES, OWNERSHIP, PART_ROLES,
                                     PRICE_MODES, RANGE_DELIVERY, UNIT_AVAILABILITY,
                                     UNIT_CATEGORIES, UNIT_CONDITIONS, UNIT_STATUSES,
                                     UNIT_TYPES, ErpOnhand, UnitLead, UnitListing,
                                     UnitListingMedia, UnitListingPart, UnitListingStat,
                                     UnitPriceGuide)
from app.services import unit_listings as svc

log = logging.getLogger(__name__)
router = APIRouter(tags=["admin-units"])

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = BACKEND_DIR / "static"
UNITS_DIR = STATIC_DIR / "units"
# Chunks are assembled in the system temp dir -- outside /static, so a half-
# uploaded file is never served, and outside the repo.
UPLOAD_TMP = Path(tempfile.gettempdir()) / "nelson_unit_uploads"
CHUNK_MAX = 9 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).replace(",", "").replace("$", "").strip())
        return d if d >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _int(v: Any) -> int | None:
    d = _dec(v)
    return int(d) if d is not None else None


def _s(v: Any, n: int) -> str | None:
    if v is None:
        return None
    s = str(v).replace("\x00", "").strip()
    return s[:n] or None


# ---------------------------------------------------------------------------
# Serialisation (admin: everything)
# ---------------------------------------------------------------------------

EDITABLE_STR = {
    "available_note": 120, "make": 60, "model": 80, "trim": 60, "vin": 17, "stock_number": 40,
    "cab_type": 30, "drive": 10, "fuel": 20, "engine": 120, "transmission": 120,
    "suspension": 60, "brakes": 40, "color": 40, "tires": 60, "fuel_capacity": 30,
    "upfit_make": 60, "upfit_model": 120, "headline": 160,
    "consignor_name": 160, "consignor_contact": 200, "consignor_customer_number": 20,
}
EDITABLE_TEXT = {"upfit_description", "spec_sheet", "description", "consignor_notes"}
EDITABLE_INT = {"year", "mileage", "engine_hours", "horsepower", "gvwr_lbs", "front_axle_lbs",
                "rear_axle_lbs", "featured_rank"}
EDITABLE_DEC = {"wheelbase_in", "cab_to_axle_in", "price", "sale_price", "range_low", "range_high"}
EDITABLE_ENUM = {"availability": UNIT_AVAILABILITY, "category": UNIT_CATEGORIES,
                 "condition": UNIT_CONDITIONS, "unit_type": UNIT_TYPES, "ownership": OWNERSHIP,
                 "location": tuple(svc.LOCATION_LABELS), "price_mode": PRICE_MODES,
                 "range_delivery": RANGE_DELIVERY}


def _media_out(m: UnitListingMedia) -> dict[str, Any]:
    return {"id": m.id, "kind": m.kind, "url": m.url, "thumb_url": m.thumb_url,
            "poster_url": m.poster_url, "width": m.width, "height": m.height, "bytes": m.bytes,
            "original_name": m.original_name, "caption": m.caption, "doc_type": m.doc_type,
            "sort_order": m.sort_order}


def _full(l: UnitListing, media: list[UnitListingMedia], pstat: dict[str, Any],
          views_30: int = 0, leads: int = 0) -> dict[str, Any]:
    photos = sum(1 for m in media if m.kind == "photo")
    videos = sum(1 for m in media if m.kind == "video")
    restricted = svc.price_restricted(l, pstat.get("prod_codes", []))
    health = svc.health_score(svc.listing_health(
        l, photos=photos, videos=videos, parts_total=len(pstat.get("parts", [])),
        parts_on_hand=pstat.get("on_hand", 0), restricted=restricted))
    out = {c.name: getattr(l, c.name) for c in UnitListing.__table__.columns}
    for k in ("price", "sale_price", "range_low", "range_high", "wheelbase_in", "cab_to_axle_in"):
        out[k] = svc.money(out[k])
    for k in ("available_date",):
        out[k] = out[k].isoformat() if out[k] else None
    for k in ("created_at", "updated_at", "published_at", "sold_at"):
        out[k] = out[k].isoformat() if out[k] else None
    rng = svc.effective_range(l)
    asking = float(l.sale_price or l.price or 0) or None
    cost = pstat.get("gl_cost") or None
    out.update({
        "title": svc.listing_title(l),
        "subtitle": svc.listing_subtitle(l),
        "media": [_media_out(m) for m in media],
        "counts": {"photos": photos, "videos": videos + len(l.video_urls or []),
                   "documents": sum(1 for m in media if m.kind == "document")},
        "parts": pstat.get("parts", []),
        "price_restricted": restricted,
        "effective_price_mode": svc.effective_price_mode(l, restricted),
        "effective_range": {"low": rng[0], "high": rng[1]} if rng else None,
        "cost": cost,
        "margin_pct": round(100 * (asking - cost) / asking, 1) if asking and cost else None,
        "erp_list_p1": pstat.get("list_p1") or None,
        "days_in_stock": pstat.get("max_days"),
        "health": health,
        "views_30": views_30,
        "leads": leads,
        "default_qualify_specs": svc.default_qualify_specs(l),
        "public_url": f"/trucks-for-sale/{l.slug}",
    })
    return out


async def _get(db: AsyncSession, listing_id: int) -> UnitListing:
    l = await db.get(UnitListing, listing_id)
    if l is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return l


async def _full_one(db: AsyncSession, l: UnitListing) -> dict[str, Any]:
    media = (await svc.media_for(db, [l.id]))[l.id]
    pstat = (await svc.parts_status(db, [l.id]))[l.id]
    since = datetime.now(svc.PACIFIC).date() - timedelta(days=29)
    views = (await db.execute(select(func.coalesce(func.sum(UnitListingStat.views), 0))
                              .where(UnitListingStat.listing_id == l.id, UnitListingStat.day >= since))).scalar_one()
    leads = (await db.execute(select(func.count()).select_from(UnitLead)
                              .where(UnitLead.listing_id == l.id, UnitLead.status != "spam"))).scalar_one()
    return _full(l, media, pstat, int(views), int(leads))


# ---------------------------------------------------------------------------
# Meta, ERP, VIN, spec parsing (declared before /{id} routes)
# ---------------------------------------------------------------------------

@router.get("/api/admin/units/meta")
async def units_meta(_: User = Depends(require_admin)) -> dict[str, Any]:
    return {
        "categories": [{"value": c, "label": svc.CATEGORY_LABELS.get(c, c)} for c in UNIT_CATEGORIES],
        "spec_hints": svc.CATEGORY_SPEC_HINTS,
        "features": svc.FEATURES,
        "locations": [{"value": k, "label": v} for k, v in svc.LOCATION_LABELS.items()],
        "statuses": UNIT_STATUSES, "conditions": UNIT_CONDITIONS, "unit_types": UNIT_TYPES,
        "doc_types": DOC_TYPES, "part_roles": PART_ROLES, "lead_statuses": LEAD_STATUSES,
        "min_photos": svc.MIN_PHOTOS,
        "restricted_note": "Jerr-Dan does not allow an advertised retail price on its wreckers and "
                           "carriers. These units offer the price-range chat or Call for Price instead.",
    }


def _erp_out(r: ErpOnhand, linked: dict[tuple[str, str], list[dict[str, Any]]]) -> dict[str, Any]:
    key = (r.part_number, svc._norm(r.serial))
    return {
        "id": r.id, "part_number": r.part_number, "prod_code": r.prod_code,
        "warehouse": r.warehouse,
        "location": svc.WAREHOUSE_LOCATION.get(r.warehouse or 0),
        "onhand": float(r.onhand or 0), "gl_cost": svc.money(r.gl_cost), "days": r.days,
        "serial": r.serial, "description": r.description, "extra_desc": r.extra_desc,
        "p1": svc.money(r.p1), "p2": svc.money(r.p2), "p3": svc.money(r.p3),
        "kind": svc.classify_erp_part(r.prod_code, r.part_number),
        "linked_to": linked.get(key) or linked.get((r.part_number, "")) or [],
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
    }


async def _linked_map(db: AsyncSession) -> dict[tuple[str, str], list[dict[str, Any]]]:
    rows = (await db.execute(
        select(UnitListingPart.part_number, UnitListingPart.serial, UnitListing.id, UnitListing.status,
               UnitListing.slug, UnitListing.year, UnitListing.make, UnitListing.model)
        .join(UnitListing, UnitListing.id == UnitListingPart.listing_id)
        .where(UnitListing.status.in_(("draft", "active", "pending"))))).all()
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for pn, serial, lid, status, slug, y, mk, md in rows:
        title = " ".join(str(b) for b in (y, mk, md) if b) or f"Listing #{lid}"
        out.setdefault((pn, svc._norm(serial)), []).append({"id": lid, "status": status, "title": title})
    return out


@router.get("/api/admin/units/erp/search")
async def erp_search(q: str = Query(..., min_length=2), db: AsyncSession = Depends(get_db),
                     _: User = Depends(require_admin)) -> dict[str, Any]:
    like = f"%{q.strip()}%"
    rows = (await db.execute(select(ErpOnhand).where(or_(
        ErpOnhand.part_number.ilike(like), ErpOnhand.serial.ilike(like),
        ErpOnhand.description.ilike(like), ErpOnhand.extra_desc.ilike(like)))
        .order_by(ErpOnhand.gl_cost.desc().nullslast()).limit(40))).scalars().all()
    linked = await _linked_map(db)
    return {"items": [_erp_out(r, linked) for r in rows]}


@router.get("/api/admin/units/erp/unlisted")
async def erp_unlisted(min_cost: float = Query(10000, ge=0), db: AsyncSession = Depends(get_db),
                       _: User = Depends(require_admin)) -> dict[str, Any]:
    """On-hand units nobody has listed: the inventory tying up money that the
    website isn't selling yet."""
    rows = (await db.execute(select(ErpOnhand).where(
        ErpOnhand.onhand > 0, ErpOnhand.gl_cost >= min_cost, ErpOnhand.prod_code.isnot(None),
        ErpOnhand.prod_code != "").order_by(ErpOnhand.gl_cost.desc()))).scalars().all()
    rows = [r for r in rows if not svc.PSEUDO_PART.match(r.part_number)]
    linked = await _linked_map(db)
    items = [_erp_out(r, linked) for r in rows]
    unlisted = [i for i in items if not i["linked_to"]]
    synced = max((r.synced_at for r in rows), default=None)
    return {
        "items": items,
        "unlisted_count": len(unlisted),
        "unlisted_cost": round(sum(i["gl_cost"] or 0 for i in unlisted), 2),
        "listed_cost": round(sum(i["gl_cost"] or 0 for i in items if i["linked_to"]), 2),
        "synced_at": synced.isoformat() if synced else None,
    }


@router.get("/api/admin/units/vin/{vin}")
async def vin_decode(vin: str, _: User = Depends(require_admin)) -> dict[str, Any]:
    return await svc.decode_vin(vin)


class SpecText(BaseModel):
    text: str = Field(..., max_length=60000)


@router.post("/api/admin/units/parse-specs")
async def parse_specs(body: SpecText, _: User = Depends(require_admin)) -> dict[str, Any]:
    return {"fields": svc.parse_spec_sheet(body.text)}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.get("/api/admin/units/reports")
async def units_reports(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db),
                        _: User = Depends(require_admin)) -> dict[str, Any]:
    today = datetime.now(svc.PACIFIC).date()
    since = today - timedelta(days=days - 1)
    listings = (await db.execute(select(UnitListing).where(UnitListing.status != "archived")
                                 .order_by(UnitListing.id))).scalars().all()
    ids = [l.id for l in listings]
    pst = await svc.parts_status(db, ids)
    views = dict((await db.execute(select(UnitListingStat.listing_id, func.sum(UnitListingStat.views))
                                   .where(UnitListingStat.day >= since, UnitListingStat.listing_id.in_(ids or [0]))
                                   .group_by(UnitListingStat.listing_id))).all())
    daily = (await db.execute(select(UnitListingStat.day, func.sum(UnitListingStat.views))
                              .where(UnitListingStat.day >= since).group_by(UnitListingStat.day)
                              .order_by(UnitListingStat.day))).all()
    lead_rows = (await db.execute(select(UnitLead.listing_id, UnitLead.kind, UnitLead.range_shown,
                                         UnitLead.created_at, UnitLead.status)
                                  .where(UnitLead.created_at >= datetime.combine(since, datetime.min.time(), svc.PACIFIC),
                                         UnitLead.status != "spam"))).all()
    per: dict[int | None, dict[str, int]] = {}
    lead_daily: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for lid, kind, shown, created, status in lead_rows:
        p = per.setdefault(lid, {"leads": 0, "ranges": 0, "won": 0})
        p["leads"] += 1
        p["ranges"] += 1 if shown else 0
        p["won"] += 1 if status == "won" else 0
        d = created.astimezone(svc.PACIFIC).date().isoformat()
        lead_daily[d] = lead_daily.get(d, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1

    rows = []
    for l in listings:
        ps = pst.get(l.id, {})
        asking = float(l.sale_price or l.price or 0) or None
        cost = ps.get("gl_cost") or None
        listed_days = (today - l.published_at.astimezone(svc.PACIFIC).date()).days if l.published_at else None
        p = per.get(l.id, {})
        rows.append({
            "id": l.id, "title": svc.listing_title(l), "status": l.status, "category": l.category,
            "availability": l.availability, "ownership": l.ownership, "location": l.location,
            "views": int(views.get(l.id, 0) or 0), "leads": p.get("leads", 0),
            "ranges_given": p.get("ranges", 0), "won": p.get("won", 0),
            "days_listed": listed_days, "days_in_stock": ps.get("max_days"),
            "cost": cost, "asking": asking,
            "margin_pct": round(100 * (asking - cost) / asking, 1) if asking and cost else None,
        })
    live = [r for r in rows if r["status"] in ("active", "pending")]
    unl = await erp_unlisted(min_cost=10000, db=db, _=_)  # type: ignore[arg-type]
    aging = {"0-90": 0.0, "91-180": 0.0, "181-365": 0.0, "365+": 0.0}
    for it in unl["items"]:
        d = it["days"] or 0
        b = "0-90" if d <= 90 else "91-180" if d <= 180 else "181-365" if d <= 365 else "365+"
        aging[b] += it["gl_cost"] or 0
    return {
        "days": days,
        "totals": {
            "live": len(live),
            "drafts": sum(1 for r in rows if r["status"] == "draft"),
            "sold": sum(1 for r in rows if r["status"] == "sold"),
            "views": sum(r["views"] for r in rows),
            "leads": sum(by_kind.values()),
            "ranges_given": sum(p.get("ranges", 0) for p in per.values()),
            "build_quotes": by_kind.get("build_quote", 0),
            "live_cost": round(sum(r["cost"] or 0 for r in live), 2),
            "live_asking": round(sum(r["asking"] or 0 for r in live), 2),
            "consigned_asking": round(sum(r["asking"] or 0 for r in live if r["ownership"] == "consignment"), 2),
            "unlisted_cost": unl["unlisted_cost"],
            "unlisted_count": unl["unlisted_count"],
        },
        "leads_by_kind": by_kind,
        "daily": {"views": {d.isoformat(): int(v) for d, v in daily}, "leads": lead_daily},
        "aging_cost": {k: round(v, 2) for k, v in aging.items()},
        "listings": rows,
    }


# ---------------------------------------------------------------------------
# Inventory list + CRUD
# ---------------------------------------------------------------------------

@router.get("/api/admin/units")
async def list_units(status: str | None = None, q: str | None = None,
                     db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    stmt = select(UnitListing)
    if status in UNIT_STATUSES:
        stmt = stmt.where(UnitListing.status == status)
    elif status != "all":
        stmt = stmt.where(UnitListing.status != "archived")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(UnitListing.make.ilike(like), UnitListing.model.ilike(like),
                              UnitListing.upfit_make.ilike(like), UnitListing.upfit_model.ilike(like),
                              UnitListing.vin.ilike(like), UnitListing.stock_number.ilike(like),
                              UnitListing.headline.ilike(like), UnitListing.consignor_name.ilike(like)))
    rows = (await db.execute(stmt.order_by(UnitListing.updated_at.desc()))).scalars().all()
    ids = [l.id for l in rows]
    media = await svc.media_for(db, ids)
    pst = await svc.parts_status(db, ids)
    since = datetime.now(svc.PACIFIC).date() - timedelta(days=29)
    views = dict((await db.execute(select(UnitListingStat.listing_id, func.sum(UnitListingStat.views))
                                   .where(UnitListingStat.day >= since, UnitListingStat.listing_id.in_(ids or [0]))
                                   .group_by(UnitListingStat.listing_id))).all())
    leads = dict((await db.execute(select(UnitLead.listing_id, func.count())
                                   .where(UnitLead.listing_id.in_(ids or [0]), UnitLead.status != "spam")
                                   .group_by(UnitLead.listing_id))).all())
    new_leads = dict((await db.execute(select(UnitLead.listing_id, func.count())
                                       .where(UnitLead.listing_id.in_(ids or [0]), UnitLead.status == "new")
                                       .group_by(UnitLead.listing_id))).all())
    items = []
    for l in rows:
        f = _full(l, media.get(l.id, []), pst.get(l.id, {}), int(views.get(l.id, 0) or 0), int(leads.get(l.id, 0)))
        f["new_leads"] = int(new_leads.get(l.id, 0))
        # The list needs one photo, not the whole gallery.
        photos = [m for m in f["media"] if m["kind"] == "photo"]
        f["photo"] = (photos[0]["thumb_url"] or photos[0]["url"]) if photos else None
        f.pop("media")
        for k in ("spec_sheet", "description", "upfit_description", "consignor_notes"):
            f.pop(k, None)
        items.append(f)
    counts = dict((await db.execute(select(UnitListing.status, func.count()).group_by(UnitListing.status))).all())
    open_leads = (await db.execute(select(func.count()).select_from(UnitLead).where(UnitLead.status == "new"))).scalar_one()
    return {"items": items, "status_counts": counts, "open_leads": open_leads}


class CreateIn(BaseModel):
    part_number: str | None = None
    serial: str | None = None
    ownership: str = "nelson"
    unit_type: str | None = None
    category: str | None = None
    availability: str | None = None


def _unique_slug(l: UnitListing) -> str:
    return f"{svc.slugify(svc.listing_title(l))}-{l.id}"


@router.post("/api/admin/units")
async def create_unit(body: CreateIn, db: AsyncSession = Depends(get_db),
                      user: User = Depends(require_admin)) -> dict[str, Any]:
    l = UnitListing(slug=f"new-{uuid.uuid4().hex[:10]}", status="draft", created_by=user.email,
                    updated_by=user.email, ownership=body.ownership if body.ownership in OWNERSHIP else "nelson",
                    unit_type=body.unit_type if body.unit_type in UNIT_TYPES else "truck",
                    category=body.category if body.category in UNIT_CATEGORIES else "other",
                    availability=body.availability if body.availability in UNIT_AVAILABILITY else "in_stock",
                    condition="used" if body.ownership == "consignment" else "new",
                    price_mode="range", specs=[], features=[], qualify_specs=[], video_urls=[])
    erp: ErpOnhand | None = None
    if body.part_number:
        stmt = select(ErpOnhand).where(ErpOnhand.part_number == body.part_number.strip())
        if body.serial:
            stmt = stmt.where(ErpOnhand.serial == body.serial.strip())
        erp = (await db.execute(stmt.limit(1))).scalar_one_or_none()
        if erp is not None:
            for k, v in svc.guess_from_erp(erp).items():
                if v is not None and hasattr(l, k):
                    setattr(l, k, v)
            if erp.p1 and erp.p1 > 0:
                l.price = erp.p1
            l.stock_number = erp.part_number[:40]
    db.add(l)
    await db.flush()
    if body.part_number:
        role = "chassis" if (erp and (erp.prod_code or "").upper() == "CHASSIS") else \
               "body" if (erp and (erp.prod_code or "").upper() in ("JERR", "DRL")) else "unit"
        db.add(UnitListingPart(listing_id=l.id, part_number=body.part_number.strip()[:60],
                               serial=(body.serial or (erp.serial if erp else None) or None),
                               role=role, sort_order=0))
    l.slug = _unique_slug(l)
    await db.commit()
    await db.refresh(l)
    return await _full_one(db, l)


@router.get("/api/admin/units/{listing_id}")
async def get_unit(listing_id: int, db: AsyncSession = Depends(get_db),
                   _: User = Depends(require_admin)) -> dict[str, Any]:
    return await _full_one(db, await _get(db, listing_id))


class PartIn(BaseModel):
    part_number: str
    serial: str | None = None
    role: str = "unit"


class SaveIn(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    parts: list[PartIn] | None = None


def _kv_list(v: Any, limit: int = 40) -> list[dict[str, str]]:
    out = []
    for s in (v or [])[:limit]:
        if isinstance(s, dict):
            lab, val = _s(s.get("label"), 60), _s(s.get("value"), 200)
            if lab and val:
                out.append({"label": lab, "value": val})
    return out


@router.put("/api/admin/units/{listing_id}")
async def save_unit(listing_id: int, body: SaveIn, db: AsyncSession = Depends(get_db),
                    user: User = Depends(require_admin)) -> dict[str, Any]:
    l = await _get(db, listing_id)
    f = body.fields
    for k, n in EDITABLE_STR.items():
        if k in f:
            setattr(l, k, _s(f[k], n))
    for k in EDITABLE_TEXT:
        if k in f:
            setattr(l, k, _s(f[k], 60000))
    for k in EDITABLE_INT:
        if k in f:
            setattr(l, k, _int(f[k]))
    for k in EDITABLE_DEC:
        if k in f:
            setattr(l, k, _dec(f[k]))
    for k, allowed in EDITABLE_ENUM.items():
        if k in f:
            v = f[k] or None
            if k == "location":
                setattr(l, k, v if v in allowed else None)
            elif v in allowed:
                setattr(l, k, v)
    if "vin" in f and l.vin:
        l.vin = l.vin.upper().replace(" ", "")
    if "available_date" in f:
        try:
            l.available_date = date.fromisoformat(f["available_date"]) if f["available_date"] else None
        except ValueError:
            raise HTTPException(status_code=422, detail="Available date must be a date.")
    if "cdl_required" in f:
        l.cdl_required = None if f["cdl_required"] in (None, "") else bool(f["cdl_required"])
    if "featured" in f:
        l.featured = bool(f["featured"])
    if "specs" in f:
        l.specs = _kv_list(f["specs"])
    if "qualify_specs" in f:
        l.qualify_specs = _kv_list(f["qualify_specs"], 10)
    if "features" in f:
        l.features = [x for x in dict.fromkeys(_s(x, 60) for x in (f["features"] or [])) if x][:60]
    if "video_urls" in f:
        urls = []
        for u in (f["video_urls"] or [])[:10]:
            u = _s(u, 400)
            if u and re.match(r"^https://(www\.)?(youtube\.com|youtu\.be|vimeo\.com|player\.vimeo\.com)/", u):
                urls.append(u)
        l.video_urls = urls
    if l.range_low and l.range_high and l.range_high < l.range_low:
        raise HTTPException(status_code=422, detail="The top of the price range is below the bottom.")

    if body.parts is not None:
        await db.execute(delete(UnitListingPart).where(UnitListingPart.listing_id == l.id))
        seen = set()
        for i, p in enumerate(body.parts[:12]):
            pn = (p.part_number or "").strip()[:60]
            sn = (p.serial or "").strip()[:40] or None
            if not pn or (pn, sn) in seen:
                continue
            seen.add((pn, sn))
            db.add(UnitListingPart(listing_id=l.id, part_number=pn, serial=sn,
                                   role=p.role if p.role in PART_ROLES else "unit", sort_order=i))
    await db.flush()

    # Jerr-Dan: never an advertised price, whatever was picked.
    pst = (await svc.parts_status(db, [l.id]))[l.id]
    notice = None
    if l.price_mode == "show" and svc.price_restricted(l, pst["prod_codes"]):
        l.price_mode = "range"
        notice = ("Jerr-Dan does not allow an advertised price, so this unit uses the price-range chat. "
                  "Pick Call for Price if you'd rather customers phone in.")
    l.updated_by = user.email
    # The address follows the title while a listing is a draft, then stays put
    # once published so links and search results keep working.
    if l.status == "draft":
        l.slug = _unique_slug(l)
    await db.commit()
    await db.refresh(l)
    out = await _full_one(db, l)
    out["notice"] = notice
    return out


class StatusIn(BaseModel):
    status: str


@router.post("/api/admin/units/{listing_id}/status")
async def set_status(listing_id: int, body: StatusIn, db: AsyncSession = Depends(get_db),
                     user: User = Depends(require_admin)) -> dict[str, Any]:
    if body.status not in UNIT_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status")
    l = await _get(db, listing_id)
    if body.status in ("active", "pending"):
        full = await _full_one(db, l)
        if not full["health"]["can_publish"]:
            missing = [i["label"] for i in full["health"]["items"] if i["blocking"] and not i["ok"]]
            raise HTTPException(status_code=422, detail="Not ready to publish: " + "; ".join(missing))
        if not l.published_at:
            l.published_at = _now()
        if l.status == "draft":
            l.slug = _unique_slug(l)
    if body.status == "sold" and not l.sold_at:
        l.sold_at = _now()
    if body.status in ("active", "pending") and l.sold_at:
        l.sold_at = None
    l.status = body.status
    l.updated_by = user.email
    await db.commit()
    await db.refresh(l)
    return await _full_one(db, l)


@router.delete("/api/admin/units/{listing_id}")
async def delete_unit(listing_id: int, db: AsyncSession = Depends(get_db),
                      user: User = Depends(require_admin)) -> dict[str, Any]:
    l = await _get(db, listing_id)
    if l.status == "draft" and not l.published_at:
        folder = UNITS_DIR / str(l.id)
        await db.delete(l)
        await db.commit()
        shutil.rmtree(folder, ignore_errors=True)
        return {"deleted": listing_id}
    l.status = "archived"
    l.updated_by = user.email
    await db.commit()
    return {"archived": listing_id}


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

_SAFE_ID = re.compile(r"^[a-f0-9]{16,40}$")


@router.post("/api/admin/units/{listing_id}/media/chunk")
async def upload_chunk(
    listing_id: int,
    upload_id: str = Form(...),
    index: int = Form(...),
    total: int = Form(...),
    filename: str = Form(...),
    chunk: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict[str, Any]:
    """Uploads arrive in <=8 MB pieces: nginx and Cloudflare both cap a single
    request, and a phone video is often several hundred megabytes. Pieces are
    appended in order; the last one turns the file into a media row."""
    l = await _get(db, listing_id)
    if not _SAFE_ID.match(upload_id) or index < 0 or total < 1 or index >= total or total > 200:
        raise HTTPException(status_code=422, detail="Bad upload")
    kind = svc.media_kind_for(filename)
    if kind is None:
        raise HTTPException(status_code=415, detail="Photos (JPG, PNG, WebP, HEIC), videos (MP4, MOV, WebM) or PDFs only.")
    UPLOAD_TMP.mkdir(parents=True, exist_ok=True)
    part = UPLOAD_TMP / f"{listing_id}_{upload_id}.part"
    data = await chunk.read()
    if len(data) > CHUNK_MAX:
        raise HTTPException(status_code=413, detail="Chunk too large")
    if index == 0 and part.exists():
        part.unlink()
    if index > 0 and not part.exists():
        raise HTTPException(status_code=409, detail="Upload lost its earlier pieces; please retry the file.")
    with part.open("ab") as fh:
        fh.write(data)
    size = part.stat().st_size
    limit = {"photo": svc.PHOTO_MAX_BYTES, "video": svc.VIDEO_MAX_BYTES, "document": svc.DOC_MAX_BYTES}[kind]
    if size > limit:
        part.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail=f"That file is over the {limit // (1024 * 1024)} MB limit.")
    if index < total - 1:
        return {"done": False, "received": size}

    out_dir = UNITS_DIR / str(l.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    base = f"/static/units/{l.id}"
    next_order = (await db.execute(select(func.coalesce(func.max(UnitListingMedia.sort_order), -1))
                                   .where(UnitListingMedia.listing_id == l.id))).scalar_one() + 1
    try:
        if kind == "photo":
            src = part.with_suffix(ext)
            part.replace(src)
            try:
                info = svc.process_photo(src, out_dir)
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Could not read that photo ({type(e).__name__}).")
            finally:
                src.unlink(missing_ok=True)
            m = UnitListingMedia(listing_id=l.id, kind="photo", url=f"{base}/{info['stem']}.jpg",
                                 thumb_url=f"{base}/{info['stem']}_t.jpg", width=info["width"],
                                 height=info["height"], bytes=size, original_name=filename[:200],
                                 sort_order=next_order)
            warn = None
            if max(info["source_width"], info["source_height"]) < 1200:
                warn = (f"{filename} is only {info['source_width']}x{info['source_height']} — it will look soft "
                        f"on a large screen. A full-size original from the camera is better.")
        else:
            stem = uuid.uuid4().hex
            dest = out_dir / f"{stem}{'.mp4' if ext == '.m4v' else ext}"
            part.replace(dest)
            m = UnitListingMedia(listing_id=l.id, kind=kind, url=f"{base}/{dest.name}", bytes=size,
                                 original_name=filename[:200], sort_order=next_order,
                                 doc_type="spec_sheet" if kind == "document" else None,
                                 caption=Path(filename).stem[:200] if kind == "document" else None)
            warn = None
    finally:
        part.unlink(missing_ok=True)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return {"done": True, "media": _media_out(m), "warning": warn}


@router.post("/api/admin/units/{listing_id}/media/{media_id}/poster")
async def upload_poster(listing_id: int, media_id: int, image: UploadFile = File(...),
                        db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    m = await db.get(UnitListingMedia, media_id)
    if m is None or m.listing_id != listing_id or m.kind != "video":
        raise HTTPException(status_code=404, detail="Video not found")
    data = await image.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Poster too large")
    out_dir = UNITS_DIR / str(listing_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = svc.process_poster(data, out_dir)
    m.poster_url = f"/static/units/{listing_id}/{name}"
    await db.commit()
    return _media_out(m)


class OrderIn(BaseModel):
    ids: list[int]


@router.patch("/api/admin/units/{listing_id}/media/order")
async def reorder_media(listing_id: int, body: OrderIn, db: AsyncSession = Depends(get_db),
                        _: User = Depends(require_admin)) -> dict[str, Any]:
    rows = (await db.execute(select(UnitListingMedia).where(UnitListingMedia.listing_id == listing_id))).scalars().all()
    pos = {mid: i for i, mid in enumerate(body.ids)}
    for m in rows:
        if m.id in pos:
            m.sort_order = pos[m.id]
    await db.commit()
    return {"ok": True}


class MediaPatch(BaseModel):
    caption: str | None = None
    doc_type: str | None = None


@router.patch("/api/admin/units/{listing_id}/media/{media_id}")
async def patch_media(listing_id: int, media_id: int, body: MediaPatch, db: AsyncSession = Depends(get_db),
                      _: User = Depends(require_admin)) -> dict[str, Any]:
    m = await db.get(UnitListingMedia, media_id)
    if m is None or m.listing_id != listing_id:
        raise HTTPException(status_code=404, detail="Not found")
    if body.caption is not None:
        m.caption = _s(body.caption, 200)
    if body.doc_type in DOC_TYPES:
        m.doc_type = body.doc_type
    await db.commit()
    return _media_out(m)


@router.delete("/api/admin/units/{listing_id}/media/{media_id}")
async def delete_media(listing_id: int, media_id: int, db: AsyncSession = Depends(get_db),
                       _: User = Depends(require_admin)) -> dict[str, Any]:
    m = await db.get(UnitListingMedia, media_id)
    if m is None or m.listing_id != listing_id:
        raise HTTPException(status_code=404, detail="Not found")
    files = [m.url, m.thumb_url, m.poster_url]
    await db.delete(m)
    await db.commit()
    for u in files:
        if u and u.startswith(f"/static/units/{listing_id}/"):
            (STATIC_DIR / u[len("/static/"):]).unlink(missing_ok=True)
    return {"deleted": media_id}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

def _lead_out(x: UnitLead) -> dict[str, Any]:
    d = {c.name: getattr(x, c.name) for c in UnitLead.__table__.columns}
    for k in ("range_low", "range_high", "offer_amount"):
        d[k] = svc.money(d[k])
    for k in ("created_at", "updated_at", "contacted_at"):
        d[k] = d[k].isoformat() if d[k] else None
    d.pop("source_ip", None)
    return d


@router.get("/api/admin/unit-leads")
async def list_leads(status: str | None = None, listing_id: int | None = None, kind: str | None = None,
                     db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    stmt = select(UnitLead)
    if status in LEAD_STATUSES:
        stmt = stmt.where(UnitLead.status == status)
    elif status == "open":
        stmt = stmt.where(UnitLead.status.in_(("new", "contacted", "quoted")))
    if listing_id:
        stmt = stmt.where(UnitLead.listing_id == listing_id)
    if kind:
        stmt = stmt.where(UnitLead.kind == kind)
    rows = (await db.execute(stmt.order_by(UnitLead.created_at.desc()).limit(500))).scalars().all()
    slugs = dict((await db.execute(select(UnitListing.id, UnitListing.slug)
                                   .where(UnitListing.id.in_({r.listing_id for r in rows if r.listing_id} or {0})))).all())
    counts = dict((await db.execute(select(UnitLead.status, func.count()).group_by(UnitLead.status))).all())
    items = []
    for r in rows:
        d = _lead_out(r)
        d["listing_slug"] = slugs.get(r.listing_id)
        items.append(d)
    return {"items": items, "status_counts": counts}


class LeadPatch(BaseModel):
    status: str | None = None
    notes: str | None = None


@router.patch("/api/admin/unit-leads/{lead_id}")
async def patch_lead(lead_id: int, body: LeadPatch, db: AsyncSession = Depends(get_db),
                     user: User = Depends(require_admin)) -> dict[str, Any]:
    x = await db.get(UnitLead, lead_id)
    if x is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if body.status in LEAD_STATUSES:
        if body.status != "new" and x.status == "new" and not x.contacted_at:
            x.contacted_at = _now()
        x.status = body.status
        x.handled_by = user.email
    if body.notes is not None:
        x.notes = _s(body.notes, 5000)
    await db.commit()
    return _lead_out(x)


# ---------------------------------------------------------------------------
# Build & Price price book
# ---------------------------------------------------------------------------

def _guide_out(r: UnitPriceGuide) -> dict[str, Any]:
    d = {c.name: getattr(r, c.name) for c in UnitPriceGuide.__table__.columns}
    d["price_low"], d["price_high"] = svc.money(r.price_low), svc.money(r.price_high)
    d.pop("created_at"), d.pop("updated_at")
    return d


class GuideIn(BaseModel):
    category: str
    group_name: str
    group_order: int = 0
    multi: bool = False
    required: bool = True
    label: str
    detail: str | None = None
    price_low: float = 0
    price_high: float = 0
    sort_order: int = 0
    active: bool = True
    basis: str | None = None


def _apply_guide(r: UnitPriceGuide, b: GuideIn) -> None:
    if b.category not in UNIT_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown category")
    if b.price_high < b.price_low:
        raise HTTPException(status_code=422, detail="High is below low.")
    r.category, r.group_name, r.group_order = b.category, b.group_name.strip()[:60], b.group_order
    r.multi, r.required, r.label = b.multi, b.required, b.label.strip()[:160]
    r.detail = _s(b.detail, 300)
    r.price_low, r.price_high = Decimal(str(b.price_low)), Decimal(str(b.price_high))
    r.sort_order, r.active, r.basis = b.sort_order, b.active, _s(b.basis, 300)


@router.get("/api/admin/unit-price-guide")
async def list_guide(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    rows = (await db.execute(select(UnitPriceGuide).order_by(
        UnitPriceGuide.category, UnitPriceGuide.group_order, UnitPriceGuide.sort_order, UnitPriceGuide.id))).scalars().all()
    return {"items": [_guide_out(r) for r in rows]}


@router.post("/api/admin/unit-price-guide")
async def create_guide(b: GuideIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    r = UnitPriceGuide()
    _apply_guide(r, b)
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return _guide_out(r)


@router.put("/api/admin/unit-price-guide/{row_id}")
async def update_guide(row_id: int, b: GuideIn, db: AsyncSession = Depends(get_db),
                       _: User = Depends(require_admin)) -> dict[str, Any]:
    r = await db.get(UnitPriceGuide, row_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Not found")
    _apply_guide(r, b)
    await db.commit()
    return _guide_out(r)


@router.delete("/api/admin/unit-price-guide/{row_id}")
async def delete_guide(row_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)) -> dict[str, Any]:
    r = await db.get(UnitPriceGuide, row_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(r)
    await db.commit()
    return {"deleted": row_id}
