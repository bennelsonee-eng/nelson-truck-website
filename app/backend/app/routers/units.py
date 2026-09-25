"""Trucks & equipment for sale -- the public side.

  GET  /api/units                     the grid: filters by category, availability,
                                      make and location
  GET  /api/units/showcase            the homepage band (featured first)
  GET  /api/units/{slug}              one unit's page
  POST /api/units/{slug}/view         a page view, for the admin's Reports
  POST /api/units/{slug}/inquiry      quote / call-back / question / offer
  POST /api/units/{slug}/price-range  the qualifier: specs confirmed + contact
                                      details -> a price range, also emailed
  GET  /api/units/builder             Build & Price: the steps for a category
  POST /api/units/builder/quote       a configured truck -> a ballpark range

Nothing internal leaves this module: no ERP cost, no consignor, no ERP part
numbers, and no price range except to a customer who has confirmed the unit's
specs and said who they are. A Jerr-Dan unit never carries its price here --
see services/unit_listings.price_restricted.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.unit_listing import (UNIT_CATEGORIES, UnitLead, UnitListing,
                                     UnitListingStat, UnitPriceGuide)
from app.services import unit_listings as svc
from app.services.email_service import AuthSmtpSender, ComposedEmail, send_email

log = logging.getLogger(__name__)
router = APIRouter(tags=["units"])

PUBLIC_STATUSES = ("active", "pending")
# Sold units stay up, marked SOLD, "for people to see what we sold" (Ben, 2026-09-25).
VISIBLE_STATUSES = ("active", "pending", "sold")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BOT_RE = re.compile(r"bot|crawl|spider|slurp|prerender|headless|lighthouse|preview|facebookexternalhit", re.I)


def _clean(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.replace("\x00", "").encode("utf-8", "replace").decode("utf-8").strip()
    return value[:limit] or None


def _ip(request: Request) -> str | None:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None)


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------

def _price_block(l: UnitListing, restricted: bool) -> dict[str, Any]:
    mode = svc.effective_price_mode(l, restricted)
    out: dict[str, Any] = {"mode": mode, "restricted": restricted,
                           "range_available": mode == "range" and svc.effective_range(l) is not None}
    if mode == "show":
        out["price"] = svc.money(l.price)
        if l.sale_price and l.price and l.sale_price < l.price:
            out["sale_price"] = svc.money(l.sale_price)
    return out


def _chassis_specs(l: UnitListing) -> list[dict[str, str]]:
    rows: list[tuple[str, Any]] = [
        ("Year", l.year), ("Make", l.make), ("Model", l.model), ("Trim", l.trim),
        ("Condition", (l.condition or "").title()),
        ("Mileage", f"{l.mileage:,} mi" if l.mileage else None),
        ("Engine hours", f"{l.engine_hours:,}" if l.engine_hours else None),
        ("Cab", l.cab_type), ("Drive", l.drive), ("Fuel", l.fuel), ("Engine", l.engine),
        ("Horsepower", f"{l.horsepower} hp" if l.horsepower else None),
        ("Transmission", l.transmission),
        ("GVWR", f"{l.gvwr_lbs:,} lbs" if l.gvwr_lbs else None),
        ("Wheelbase", f"{l.wheelbase_in:g} in" if l.wheelbase_in else None),
        ("Cab to axle", f"{l.cab_to_axle_in:g} in" if l.cab_to_axle_in else None),
        ("Front axle", f"{l.front_axle_lbs:,} lbs" if l.front_axle_lbs else None),
        ("Rear axle", f"{l.rear_axle_lbs:,} lbs" if l.rear_axle_lbs else None),
        ("Suspension", l.suspension), ("Brakes", l.brakes), ("Tires", l.tires),
        ("Fuel capacity", l.fuel_capacity), ("Color", l.color),
        ("CDL required", None if l.cdl_required is None else ("Yes" if l.cdl_required else "No")),
        ("VIN", l.vin), ("Stock #", l.stock_number),
    ]
    if l.unit_type == "equipment":
        keep = {"Year", "Make", "Model", "Condition", "Engine hours", "Stock #"}
        rows = [r for r in rows if r[0] in keep]
    return [{"label": k, "value": str(v)} for k, v in rows if v not in (None, "", "None")]


def _card(l: UnitListing, media: list, restricted: bool, erp: str = "ok") -> dict[str, Any]:
    photos = [m for m in media if m.kind == "photo"]
    videos = [m for m in media if m.kind == "video"]
    first = photos[0] if photos else None
    return {
        "slug": l.slug,
        "title": svc.listing_title(l),
        "subtitle": svc.listing_subtitle(l),
        "headline": l.headline,
        "category": l.category,
        "category_label": svc.CATEGORY_LABELS.get(l.category, l.category),
        "unit_type": l.unit_type,
        "condition": l.condition,
        # Sold in the ERP (a real sale, or the unit has left the lot) reads as
        # sold here even before anyone marks it in the admin.
        "status": "sold" if erp == "sold" else l.status,
        "sold": erp == "sold" or l.status == "sold",
        "tags": [] if (erp == "sold" or l.status == "sold") else (l.tags or []),
        "availability": l.availability,
        "available_date": l.available_date.isoformat() if l.available_date else None,
        "available_note": l.available_note,
        "location": l.location,
        "location_label": svc.LOCATION_LABELS.get(l.location or "", None),
        "year": l.year, "make": l.make, "model": l.model,
        "mileage": l.mileage, "drive": l.drive, "fuel": l.fuel, "gvwr_lbs": l.gvwr_lbs,
        "photo": first.url if first else None,
        "thumb": (first.thumb_url or first.url) if first else None,
        "photo_count": len(photos),
        "video_count": len(videos) + len(l.video_urls or []),
        "price": _price_block(l, restricted),
        "featured": l.featured,
    }


async def _load_public(db: AsyncSession, listings: list[UnitListing]) -> tuple[dict, dict, dict]:
    ids = [l.id for l in listings]
    media = await svc.media_for(db, ids)
    parts = await svc.parts_status(db, ids)
    live = await svc.erp_mirror_live(db)
    orders = await svc.orders_for(db, parts)
    state = {l.id: svc.erp_state(l, parts.get(l.id, {}), live, orders.get(l.id, {}).get("sold", False))
             for l in listings}
    return media, parts, state


def _restricted(l: UnitListing, parts: dict) -> bool:
    return svc.price_restricted(l, parts.get(l.id, {}).get("prod_codes", []))


# ---------------------------------------------------------------------------
# Grid, showcase, detail
# ---------------------------------------------------------------------------

@router.get("/api/units")
async def list_units(
    category: str | None = None,
    availability: str | None = None,
    make: str | None = None,
    location: str | None = None,
    sort: str = "featured",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    q = select(UnitListing).where(UnitListing.status.in_(VISIBLE_STATUSES))
    cats = [c for c in (category or "").split(",") if c in UNIT_CATEGORIES]
    if cats:
        q = q.where(UnitListing.category.in_(cats))
    if availability in ("in_stock", "future_build"):
        q = q.where(UnitListing.availability == availability)
    if make:
        q = q.where(or_(func.lower(UnitListing.make) == make.lower(),
                        func.lower(UnitListing.upfit_make) == make.lower()))
    if location in svc.LOCATION_LABELS:
        q = q.where(UnitListing.location == location)
    order = {
        "newest": [UnitListing.published_at.desc().nullslast()],
        "year": [UnitListing.year.desc().nullslast()],
    }.get(sort, [UnitListing.featured.desc(), UnitListing.featured_rank.asc(),
                 UnitListing.published_at.desc().nullslast()])
    rows = (await db.execute(q.order_by(*order, UnitListing.id.desc()))).scalars().all()
    media, parts, state = await _load_public(db, rows)
    cards = [_card(l, media.get(l.id, []), _restricted(l, parts), state[l.id]) for l in rows]
    items = [c for c in cards if not c["sold"]]
    sold = sorted([c for c in cards if c["sold"]], key=lambda c: c.get("published_at") or "", reverse=True)[:24]

    # Facets over everything public, so a filter never hides its own options.
    all_rows = (await db.execute(
        select(UnitListing.category, UnitListing.make, UnitListing.upfit_make,
               UnitListing.location, UnitListing.availability)
        .where(UnitListing.status.in_(VISIBLE_STATUSES)))).all()
    facet_cat: dict[str, int] = {}
    facet_make: dict[str, int] = {}
    facet_loc: dict[str, int] = {}
    facet_av: dict[str, int] = {}
    for c, mk, up, loc, av in all_rows:
        facet_cat[c] = facet_cat.get(c, 0) + 1
        for m in {x for x in (mk, up) if x}:
            facet_make[m] = facet_make.get(m, 0) + 1
        if loc:
            facet_loc[loc] = facet_loc.get(loc, 0) + 1
        facet_av[av] = facet_av.get(av, 0) + 1
    return {
        "items": items,
        "total": len(items),
        "sold": sold,
        "facets": {
            "category": [{"value": k, "label": svc.CATEGORY_LABELS.get(k, k), "count": v}
                         for k, v in sorted(facet_cat.items(), key=lambda kv: -kv[1])],
            "make": [{"value": k, "count": v} for k, v in sorted(facet_make.items())],
            "location": [{"value": k, "label": svc.LOCATION_LABELS[k], "count": v}
                         for k, v in facet_loc.items() if k in svc.LOCATION_LABELS],
            "availability": facet_av,
        },
    }


@router.get("/api/units/showcase")
async def units_showcase(
    category: str | None = None,
    limit: int = Query(12, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    q = select(UnitListing).where(UnitListing.status.in_(PUBLIC_STATUSES))
    cats = [c for c in (category or "").split(",") if c in UNIT_CATEGORIES]
    if cats:
        q = q.where(UnitListing.category.in_(cats))
    q = q.order_by(UnitListing.featured.desc(), UnitListing.featured_rank.asc(),
                   UnitListing.status.asc(), UnitListing.published_at.desc().nullslast(),
                   UnitListing.id.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    media, parts, state = await _load_public(db, rows)
    rows = [l for l in rows if state[l.id] != "sold"]
    all_live = (await db.execute(select(UnitListing).where(UnitListing.status.in_(VISIBLE_STATUSES)))).scalars().all()
    _, _, all_state = await _load_public(db, all_live)
    total = sum(1 for l in all_live if l.status != "sold" and all_state[l.id] != "sold")
    return {"items": [_card(l, media.get(l.id, []), _restricted(l, parts), state[l.id]) for l in rows],
            "total": total, "sold_count": len(all_live) - total}


@router.get("/api/units/builder")
async def builder_config(category: str | None = None, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The Build & Price steps. Prices stay server-side: the page gets labels,
    never the per-choice numbers, so the range is only ever the widened total."""
    rows = (await db.execute(select(UnitPriceGuide).where(UnitPriceGuide.active.is_(True))
                             .order_by(UnitPriceGuide.category, UnitPriceGuide.group_order,
                                       UnitPriceGuide.sort_order, UnitPriceGuide.id))).scalars().all()
    cats: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = cats.setdefault(r.category, {"category": r.category,
                                          "label": svc.CATEGORY_LABELS.get(r.category, r.category),
                                          "steps": {}})
        step = c["steps"].setdefault(r.group_name, {"name": r.group_name, "order": r.group_order,
                                                    "multi": r.multi, "required": r.required,
                                                    "choices": []})
        step["choices"].append({"id": r.id, "label": r.label, "detail": r.detail})
    out = []
    for c in cats.values():
        c["steps"] = sorted(c["steps"].values(), key=lambda s: s["order"])
        c["spec_hints"] = svc.CATEGORY_SPEC_HINTS.get(c["category"], [])
        out.append(c)
    if category:
        out = [c for c in out if c["category"] == category]
    return {"categories": out}


@router.get("/api/units/{slug}")
async def unit_detail(slug: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    l = (await db.execute(select(UnitListing).where(UnitListing.slug == slug))).scalar_one_or_none()
    if l is None or l.status not in VISIBLE_STATUSES:
        raise HTTPException(status_code=404, detail="That unit is no longer listed.")
    media, parts, state = await _load_public(db, [l])
    restricted = _restricted(l, parts)
    ms = media.get(l.id, [])
    card = _card(l, ms, restricted, state[l.id])
    qs = l.qualify_specs or svc.default_qualify_specs(l)
    card.update({
        "description": l.description,
        "upfit_make": l.upfit_make, "upfit_model": l.upfit_model,
        "upfit_description": l.upfit_description,
        "specs": [s for s in (l.specs or []) if s.get("label") and s.get("value")],
        "chassis_specs": _chassis_specs(l),
        "features": l.features or [],
        "spec_sheet": l.spec_sheet,
        "photos": [{"url": m.url, "thumb": m.thumb_url or m.url, "width": m.width,
                    "height": m.height, "caption": m.caption} for m in ms if m.kind == "photo"],
        "videos": [{"url": m.url, "poster": m.poster_url, "caption": m.caption}
                   for m in ms if m.kind == "video"],
        "video_links": l.video_urls or [],
        "documents": [{"url": m.url, "name": m.caption or m.original_name or "Document",
                       "doc_type": m.doc_type} for m in ms if m.kind == "document"],
        "qualify_specs": [{"label": s.get("label"), "value": s.get("value")} for s in qs
                          if s.get("label") and s.get("value")],
        "vin": l.vin, "stock_number": l.stock_number,
        "published_at": l.published_at.isoformat() if l.published_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
    })
    return card


@router.post("/api/units/{slug}/view")
async def unit_view(slug: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """Count a page view. Crawlers and the prerenderer run the page's script
    too, so they are dropped by user agent."""
    ua = request.headers.get("user-agent") or ""
    if not ua or _BOT_RE.search(ua):
        return {"ok": True}
    lid = (await db.execute(select(UnitListing.id).where(UnitListing.slug == slug,
                                                         UnitListing.status.in_(PUBLIC_STATUSES)))).scalar_one_or_none()
    if lid is None:
        return {"ok": False}
    today = datetime.now(svc.PACIFIC).date()
    stmt = pg_insert(UnitListingStat).values(listing_id=lid, day=today, views=1)
    stmt = stmt.on_conflict_do_update(constraint="uq_unit_listing_stat_day",
                                      set_={"views": UnitListingStat.views + 1,
                                            "updated_at": func.now()})
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

class ContactIn(BaseModel):
    name: str = Field(..., max_length=120)
    company: str | None = Field(None, max_length=160)
    email: str | None = Field(None, max_length=254)
    phone: str | None = Field(None, max_length=40)
    zip: str | None = Field(None, max_length=12)
    page_url: str | None = Field(None, max_length=500)
    website: str | None = None  # honeypot


class InquiryIn(ContactIn):
    kind: str = "quote"                         # quote | call | question | offer
    message: str | None = Field(None, max_length=5000)
    offer_amount: float | None = Field(None, ge=0, le=10_000_000)
    # Equipment the customer wants quoted on top of the unit (Ben, 2026-09-25).
    additional_items: list[str] = Field(default_factory=list)


class PriceRangeIn(ContactIn):
    # One answer per qualify spec, in order: True = "yes, that's what I'm pricing".
    confirmed: list[bool] = Field(default_factory=list)
    answers: dict[str, Any] = Field(default_factory=dict)
    message: str | None = Field(None, max_length=2000)


class BuilderQuoteIn(ContactIn):
    category: str
    choice_ids: list[int] = Field(default_factory=list)
    specs: dict[str, Any] = Field(default_factory=dict)
    answers: dict[str, Any] = Field(default_factory=dict)
    message: str | None = Field(None, max_length=3000)


async def _guard(db: AsyncSession, body: ContactIn, request: Request, need_email: bool) -> dict[str, Any]:
    name = _clean(body.name, 120)
    email = _clean(body.email, 254)
    phone = _clean(body.phone, 40)
    if not name:
        raise HTTPException(status_code=422, detail="Please tell us your name.")
    if need_email and not email:
        raise HTTPException(status_code=422, detail="We email the price to you, so we need an email address.")
    if not email and not phone:
        raise HTTPException(status_code=422, detail="Please give us an email address or a phone number so we can reply.")
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="That email address doesn't look right.")
    ip = _ip(request)
    if ip:
        recent = (await db.execute(
            select(func.count()).select_from(UnitLead)
            .where(UnitLead.source_ip == ip, UnitLead.created_at > func.now() - func.make_interval(0, 0, 0, 0, 1))
        )).scalar_one()
        if recent >= 8:
            raise HTTPException(status_code=429, detail="Too many requests from this network. Please call us instead.")
    return {"name": name, "email": email, "phone": phone,
            "company": _clean(body.company, 160), "zip": _clean(body.zip, 12),
            "page_url": _clean(body.page_url, 500), "source_ip": (ip or "")[:64] or None,
            "user_agent": _clean(request.headers.get("user-agent"), 300)}


def _lead_dict(lead: UnitLead) -> dict[str, Any]:
    return {c.name: getattr(lead, c.name) for c in UnitLead.__table__.columns}


_KIND_LABEL = {"price_range": "Price range request", "build_quote": "Build & Price request",
               "quote": "Quote request", "call": "Call-back request",
               "question": "Question", "offer": "Offer"}


def _alert(lead: dict[str, Any]) -> None:
    """Email the alert address. Background task; the lead is already stored,
    so a mail failure loses nothing."""
    try:
        settings = get_settings()
        to = (settings.inquiry_alert_email or "").strip()
        if not to:
            return
        label = _KIND_LABEL.get(lead["kind"], "Lead")
        lines = [f"{label} #{lead['id']} from the {settings.app_name} website.", ""]
        if lead.get("listing_title"):
            lines.append(f"  Unit:     {lead['listing_title']}")
        for k, lab in (("name", "Name"), ("company", "Company"), ("email", "Email"),
                       ("phone", "Phone"), ("zip", "ZIP")):
            if lead.get(k):
                lines.append(f"  {lab + ':':<9} {lead[k]}")
        if lead.get("offer_amount"):
            lines.append(f"  Offer:    ${float(lead['offer_amount']):,.0f}")
        if lead.get("range_low") is not None and lead.get("range_high") is not None:
            shown = "shown and emailed" if lead.get("range_shown") else "emailed"
            lines.append(f"  Range:    ${float(lead['range_low']):,.0f} - ${float(lead['range_high']):,.0f} ({shown})")
        extra = (lead.get("answers") or {}).get("additional_items")
        if extra:
            lines.append("  ALSO QUOTE: " + ", ".join(str(x) for x in extra))
        if lead.get("specs_confirmed") is False:
            lines.append("  NOTE:     the customer wants a different spec than the listed unit - price their build.")
        ans = lead.get("answers") or {}
        if ans:
            lines += ["", "Their answers:"]
            for k, v in ans.items():
                if isinstance(v, (list, tuple)):
                    v = ", ".join(str(x) for x in v)
                lines.append(f"  {k}: {v}")
        if lead.get("page_url"):
            lines += ["", f"Page: {lead['page_url']}"]
        lines += ["", "Message:", lead.get("message") or "(none)", "",
                  "All unit leads are under Admin > Trucks for Sale > Leads."]
        email = ComposedEmail(
            to_email=to, to_name=None,
            subject=f"[{settings.app_name}] {label} · {lead.get('listing_title') or lead.get('company') or lead['name']}"[:150],
            text_body="\n".join(lines),
            reply_to=lead["email"] if lead.get("email") and _EMAIL_RE.match(lead["email"]) else None,
        )
        if settings.error_report_smtp_host and settings.error_report_smtp_user:
            sender = AuthSmtpSender(host=settings.error_report_smtp_host, port=settings.error_report_smtp_port,
                                    user=settings.error_report_smtp_user, password=settings.error_report_smtp_password,
                                    from_addr=settings.error_report_smtp_from or settings.error_report_smtp_user)
            result = sender.send(email)
        else:
            result = send_email(email)
        if not result.ok:
            log.warning("unit lead %s: alert failed: %s", lead["id"], result.error)
    except Exception:
        log.exception("unit lead %s: alert raised", lead.get("id"))


def _email_customer_range(lead: dict[str, Any], follow_up: str, unit_url: str | None) -> None:
    """Send the customer their price range. Goes through the site's own mail
    provider, which delivers nothing until launch-day SMTP is switched on."""
    try:
        settings = get_settings()
        low, high = float(lead["range_low"]), float(lead["range_high"])
        first = (lead["name"] or "").split(" ")[0]
        what = lead.get("listing_title") or "the truck you configured"
        lines = [
            f"Hi {first},", "",
            f"Thanks for your interest in {what}.", "",
            f"    Price range: ${low:,.0f} - ${high:,.0f}", "",
        ]
        if lead["kind"] == "build_quote":
            lines += ["This is a ballpark for the configuration you built, based on what similar",
                      "trucks have sold for and today's chassis and equipment pricing. Your exact",
                      "price depends on the chassis we can source, options and delivery timing.", ""]
        else:
            lines += ["That range is for this unit as listed. Final price depends on options,",
                      "trade-in and delivery, which your salesperson will go over with you.", ""]
        lines += [follow_up, ""]
        if unit_url:
            lines += [f"The unit: {unit_url}", ""]
        lines += ["Nelson Truck Equipment",
                  "Portland 503-548-9300 · Kent 253-395-3825 · sales@nelsontruck.com"]
        res = send_email(ComposedEmail(to_email=lead["email"], to_name=lead["name"],
                                       subject=f"Your price range: {what}"[:150],
                                       text_body="\n".join(lines), reply_to=None))
        if not res.ok:
            log.warning("unit lead %s: customer range email failed: %s", lead["id"], res.error)
    except Exception:
        log.exception("unit lead %s: customer range email raised", lead.get("id"))


async def _public_listing(db: AsyncSession, slug: str, allow_sold: bool = False) -> UnitListing:
    l = (await db.execute(select(UnitListing).where(UnitListing.slug == slug))).scalar_one_or_none()
    if l is None or l.status not in VISIBLE_STATUSES:
        raise HTTPException(status_code=404, detail="That unit is no longer listed.")
    _, _, state = await _load_public(db, [l])
    if not allow_sold and (l.status == "sold" or state[l.id] == "sold"):
        raise HTTPException(status_code=409, detail="That unit has sold — ask us about one like it.")
    return l


def _canonical(slug: str) -> str:
    base = getattr(get_settings(), "canonical_base_url", None) or "https://nelsontruck.com"
    return f"{base.rstrip('/')}/trucks-for-sale/{slug}"


@router.post("/api/units/{slug}/inquiry")
async def unit_inquiry(slug: str, body: InquiryIn, request: Request, background: BackgroundTasks,
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if body.website:
        return {"ok": True}
    l = await _public_listing(db, slug, allow_sold=True)
    c = await _guard(db, body, request, need_email=False)
    kind = body.kind if body.kind in ("quote", "call", "question", "offer") else "quote"
    extra = [x for x in (_clean(i, 80) for i in body.additional_items[:20]) if x]
    lead = UnitLead(listing_id=l.id, kind=kind, status="new", listing_title=svc.listing_title(l),
                    message=_clean(body.message, 5000),
                    answers={"additional_items": extra} if extra else {},
                    offer_amount=Decimal(str(body.offer_amount)) if kind == "offer" and body.offer_amount else None,
                    **c)
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    background.add_task(_alert, _lead_dict(lead))
    return {"ok": True, "follow_up": svc.follow_up_message((c["name"] or "").split(" ")[0])}


@router.post("/api/units/{slug}/price-range")
async def unit_price_range(slug: str, body: PriceRangeIn, request: Request, background: BackgroundTasks,
                           db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The qualifier. A range is given only when the customer has confirmed
    every spec of the listed unit -- a different spec is a different price, so
    that becomes a lead for a salesperson to price, not a number on screen."""
    if body.website:
        return {"ok": True, "range": None}
    l = await _public_listing(db, slug)
    parts = await svc.parts_status(db, [l.id])
    restricted = svc.price_restricted(l, parts.get(l.id, {}).get("prod_codes", []))
    if svc.effective_price_mode(l, restricted) != "range":
        raise HTTPException(status_code=409, detail="Please call us for pricing on this unit.")
    rng = svc.effective_range(l, parts.get(l.id, {}).get("gl_cost") or None)
    c = await _guard(db, body, request, need_email=True)
    qs = [s for s in (l.qualify_specs or svc.default_qualify_specs(l)) if s.get("label") and s.get("value")]
    all_confirmed = bool(qs) and len(body.confirmed) == len(qs) and all(body.confirmed)
    answers = dict(body.answers or {})
    answers["specs"] = {s["label"]: ("confirmed" if i < len(body.confirmed) and body.confirmed[i] else "different")
                        for i, s in enumerate(qs)}
    give = all_confirmed and rng is not None
    show = give and l.range_delivery != "email_only"
    first = (c["name"] or "").split(" ")[0]
    follow = svc.follow_up_message(first)
    lead = UnitLead(listing_id=l.id, kind="price_range", status="new", listing_title=svc.listing_title(l),
                    answers=answers, specs_confirmed=all_confirmed, message=_clean(body.message, 2000),
                    range_low=Decimal(rng[0]) if give else None, range_high=Decimal(rng[1]) if give else None,
                    range_shown=show, range_emailed=give and bool(c["email"]), **c)
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    d = _lead_dict(lead)
    background.add_task(_alert, d)
    if give and c["email"]:
        background.add_task(_email_customer_range, d, follow["text"], _canonical(l.slug))
    return {
        "ok": True,
        "range": {"low": rng[0], "high": rng[1]} if show else None,
        "emailed": give and bool(c["email"]),
        "specs_confirmed": all_confirmed,
        "follow_up": follow,
    }


@router.post("/api/units/builder/quote")
async def builder_quote(body: BuilderQuoteIn, request: Request, background: BackgroundTasks,
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if body.website:
        return {"ok": True, "range": None}
    if body.category not in UNIT_CATEGORIES:
        raise HTTPException(status_code=422, detail="Pick what kind of truck you're building.")
    rows = (await db.execute(select(UnitPriceGuide).where(
        UnitPriceGuide.category == body.category, UnitPriceGuide.active.is_(True)))).scalars().all()
    by_id = {r.id: r for r in rows}
    chosen = [by_id[i] for i in dict.fromkeys(body.choice_ids) if i in by_id]
    # Every required pick-one step needs an answer.
    groups: dict[str, list[UnitPriceGuide]] = {}
    for r in rows:
        groups.setdefault(r.group_name, []).append(r)
    missing = [g for g, rs in groups.items()
               if rs[0].required and not rs[0].multi and not any(c.group_name == g for c in chosen)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Please choose: {', '.join(missing)}.")
    c = await _guard(db, body, request, need_email=True)
    low = sum(float(r.price_low) for r in chosen)
    high = sum(float(r.price_high) for r in chosen)
    rng = svc.builder_range(low, high) if high > 0 else None
    first = (c["name"] or "").split(" ")[0]
    follow = svc.follow_up_message(first)
    config = {r.group_name + (f" #{r.id}" if r.multi else ""): r.label for r in chosen}
    answers = {"category": svc.CATEGORY_LABELS.get(body.category, body.category), **config,
               **{f"spec: {k}": v for k, v in (body.specs or {}).items() if v not in (None, "", [])},
               **(body.answers or {})}
    title = f"Build & Price: {svc.CATEGORY_SINGULAR.get(body.category, body.category)} — " + \
            " / ".join(r.label for r in chosen if not r.multi)[:150]
    lead = UnitLead(listing_id=None, kind="build_quote", status="new", listing_title=title[:200],
                    answers=answers, message=_clean(body.message, 3000),
                    range_low=Decimal(rng[0]) if rng else None, range_high=Decimal(rng[1]) if rng else None,
                    range_shown=rng is not None, range_emailed=rng is not None and bool(c["email"]), **c)
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    d = _lead_dict(lead)
    background.add_task(_alert, d)
    if rng and c["email"]:
        background.add_task(_email_customer_range, d, follow["text"], None)
    return {"ok": True, "range": {"low": rng[0], "high": rng[1]} if rng else None,
            "emailed": bool(rng and c["email"]), "follow_up": follow}
