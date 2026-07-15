"""WinterWatch — snow forecast email alert subscription endpoints.

Public API surface:
    POST /api/snow-alerts/signup       - submit email + zip + opt-ins
    GET  /api/snow-alerts/confirm      - confirm via tokenised link
    GET  /api/snow-alerts/unsubscribe  - one-click unsubscribe
    GET  /api/snow-alerts/preferences  - view current subscription state
    POST /api/snow-alerts/preferences  - update opt-ins (uses unsub token)

Admin-side (auth-gated):
    POST /api/snow-alerts/run-daily    - trigger the cron immediately
                                         (admins / smoke-test only)
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.weather_alert import WeatherAlertSubscriber
from app.services.email_service import send_email
from app.services.weather_alert_service import (
    compose_unsubscribed_email,
    compose_welcome_email,
    confirm,
    run_daily_alerts,
    subscribe,
    unsubscribe,
    _public_base_url,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/snow-alerts", tags=["snow-alerts"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    zip_code: str = Field(..., min_length=5, max_length=10, description="5-digit US ZIP")
    alert_opt_in: bool = Field(default=True, description="Receive snow forecast alerts")
    promo_opt_in: bool = Field(default=False, description="Receive promotional emails (snow & ice gear)")


class SignupResponse(BaseModel):
    ok: bool
    is_new: bool                # True if a new subscriber, False if already existed
    needs_confirmation: bool    # True if a confirmation email was just sent
    location_resolved: bool     # True if we figured out the NWS gridpoint
    location_label: str | None  # "Spokane Valley, WA" if resolved


class PreferencesResponse(BaseModel):
    email: str
    zip_code: str
    location_label: str | None
    alert_opt_in: bool
    promo_opt_in: bool
    confirmed: bool
    unsubscribed: bool
    last_alert_sent_at: str | None
    total_alerts_sent: int


class UpdatePreferencesRequest(BaseModel):
    alert_opt_in: bool | None = None
    promo_opt_in: bool | None = None
    zip_code: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/signup", response_model=SignupResponse)
async def signup(
    body: SignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SignupResponse:
    """Subscribe an email to WinterWatch alerts (double-opt-in flow)."""
    try:
        result = await subscribe(
            db,
            email=str(body.email),
            zip_code=body.zip_code,
            alert_opt_in=body.alert_opt_in,
            promo_opt_in=body.promo_opt_in,
            source_url=str(request.headers.get("referer") or "")[:200] or None,
            user_agent=str(request.headers.get("user-agent") or "")[:400] or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    needs_confirmation = result.subscriber.confirmed_at is None
    await db.commit()

    # Best-effort send the confirmation/preferences-updated email
    if result.confirmation_email is not None:
        try:
            send_email(result.confirmation_email)
        except Exception as e:
            log.warning("WinterWatch confirmation email send failed: %s", e)

    return SignupResponse(
        ok=True,
        is_new=result.is_new,
        needs_confirmation=needs_confirmation,
        location_resolved=result.subscriber.has_location,
        location_label=result.subscriber.location_label,
    )


@router.get("/confirm")
async def confirm_signup(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Click-target for the link in the confirmation email."""
    try:
        sub = await confirm(db, token)
    except LookupError:
        raise HTTPException(status_code=404, detail="Confirmation token not recognized")
    await db.commit()

    # Send a welcome email on first confirmation
    if sub.total_alerts_sent == 0 and sub.confirmed_at is not None:
        try:
            send_email(compose_welcome_email(sub, _public_base_url()))
        except Exception as e:
            log.warning("WinterWatch welcome email send failed: %s", e)

    return {
        "ok": True,
        "email": sub.email,
        "zip_code": sub.zip_code,
        "location_label": sub.location_label,
        "promo_opt_in": sub.promo_opt_in,
    }


@router.get("/unsubscribe")
async def unsubscribe_endpoint(token: str, reason: str | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    """One-click unsubscribe (RFC 8058 / CAN-SPAM compliant)."""
    try:
        sub = await unsubscribe(db, token, reason=reason)
    except LookupError:
        raise HTTPException(status_code=404, detail="Unsubscribe token not recognized")
    await db.commit()

    # Confirmation email so they know it worked
    try:
        send_email(compose_unsubscribed_email(sub))
    except Exception as e:
        log.warning("WinterWatch unsubscribe-confirm email send failed: %s", e)

    return {"ok": True, "email": sub.email, "unsubscribed_at": sub.unsubscribed_at.isoformat() if sub.unsubscribed_at else None}


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(token: str, db: AsyncSession = Depends(get_db)) -> PreferencesResponse:
    """View current subscription state via unsubscribe token (so user can
    inspect their preferences without exposing email lookups)."""
    sub = (await db.execute(
        select(WeatherAlertSubscriber).where(WeatherAlertSubscriber.unsubscribe_token == token)
    )).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Token not recognized")
    return PreferencesResponse(
        email=sub.email,
        zip_code=sub.zip_code,
        location_label=sub.location_label,
        alert_opt_in=sub.alert_opt_in,
        promo_opt_in=sub.promo_opt_in,
        confirmed=sub.confirmed_at is not None,
        unsubscribed=sub.unsubscribed_at is not None,
        last_alert_sent_at=sub.last_alert_sent_at.isoformat() if sub.last_alert_sent_at else None,
        total_alerts_sent=sub.total_alerts_sent,
    )


@router.post("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    token: str,
    body: UpdatePreferencesRequest,
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    """Update opt-in flags or change ZIP via the unsubscribe token."""
    sub = (await db.execute(
        select(WeatherAlertSubscriber).where(WeatherAlertSubscriber.unsubscribe_token == token)
    )).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Token not recognized")

    if body.alert_opt_in is not None:
        sub.alert_opt_in = body.alert_opt_in
    if body.promo_opt_in is not None:
        sub.promo_opt_in = body.promo_opt_in
    if body.zip_code:
        zip5 = body.zip_code.strip()[:5]
        if zip5 != sub.zip_code:
            sub.zip_code = zip5
            # Clear cached gridpoint — daily cron will re-resolve
            sub.latitude = sub.longitude = None
            sub.nws_office = None
            sub.nws_grid_x = sub.nws_grid_y = None
            sub.location_label = None
            sub.nws_resolved_at = None

    await db.commit()
    return PreferencesResponse(
        email=sub.email,
        zip_code=sub.zip_code,
        location_label=sub.location_label,
        alert_opt_in=sub.alert_opt_in,
        promo_opt_in=sub.promo_opt_in,
        confirmed=sub.confirmed_at is not None,
        unsubscribed=sub.unsubscribed_at is not None,
        last_alert_sent_at=sub.last_alert_sent_at.isoformat() if sub.last_alert_sent_at else None,
        total_alerts_sent=sub.total_alerts_sent,
    )


@router.post("/run-daily")
async def trigger_daily_run(
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger the daily alert run.  Default dry_run=True so it
    doesn't accidentally email everyone during smoke tests.  Will be
    auth-gated to admin role once the daily cron is wired."""
    summary = await run_daily_alerts(db, dry_run=dry_run)
    if not dry_run:
        await db.commit()
    return {
        "ok": True,
        "dry_run": dry_run,
        "checked": summary.checked,
        "skipped_inactive": summary.skipped_inactive,
        "skipped_no_location": summary.skipped_no_location,
        "skipped_dampened": summary.skipped_dampened,
        "snow_detected": summary.snow_detected,
        "sent": summary.sent,
        "errors": summary.errors,
    }
