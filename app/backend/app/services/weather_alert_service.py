"""Snow forecast email alert pipeline.

Public surface:
    - subscribe(email, zip, alert_opt_in, promo_opt_in, ...)
        -> (subscriber, ConfirmationEmail) tuple, caller dispatches the email
    - confirm(token) -> Subscriber  (raises if invalid)
    - unsubscribe(token, reason=None) -> Subscriber
    - run_daily_alerts() -> dict  (called from the morning cron task)

Compose helpers (pure, easy to unit test):
    - compose_confirmation_email(sub, base_url)
    - compose_alert_email(sub, snow_periods, base_url)
    - compose_welcome_email(sub, base_url)
    - compose_unsubscribed_email(sub)

External calls:
    - api.zippopotam.us/us/{zip}     ZIP -> lat/lon (free, no auth, no key)
    - api.weather.gov                  lat/lon -> office+grid -> 7-day forecast
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.weather_alert import WeatherAlertSubscriber
from app.services.email_service import ComposedEmail, send_email
from app.services.weather_service import _classify_snow_risk, _to_period


log = logging.getLogger(__name__)

USER_AGENT = "NelsonTruckEquipment/0.1 (sales@nelsontruck.com)"

# Don't send another alert within this many days after the last one for the
# same subscriber, even if the forecast is still showing snow.  Stops a
# multi-day storm from triggering 5 emails in a row.
DAMPEN_DAYS = 3

# How far ahead to scan for snow events.  NWS gives 7-day max in 12-hour periods.
ALERT_LOOKAHEAD_HOURS = 168  # 7 days

ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


# ---------------------------------------------------------------------------
# ZIP/lat-lon resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolvedLocation:
    latitude: float
    longitude: float
    nws_office: str
    nws_grid_x: int
    nws_grid_y: int
    label: str  # "Spokane Valley, WA"


async def resolve_zip(zip_code: str) -> ResolvedLocation | None:
    """ZIP -> NWS gridpoint via Zippopotam + NWS /points.

    Returns None if either lookup fails — caller can store the row without
    location and resolve later.
    """
    zip5 = zip_code[:5]
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Step 1: Zippopotam.us — ZIP -> lat/lon + place name
        try:
            r = await client.get(f"https://api.zippopotam.us/us/{zip5}")
            r.raise_for_status()
            zd = r.json()
            if not zd.get("places"):
                return None
            place = zd["places"][0]
            lat = float(place["latitude"])
            lon = float(place["longitude"])
            label = f"{place['place name']}, {place['state abbreviation']}"
        except Exception as e:
            log.warning("ZIP %s -> lat/lon failed: %s", zip5, e)
            return None

        # Step 2: NWS /points/{lat,lon} -> gridpoint
        try:
            r2 = await client.get(
                f"https://api.weather.gov/points/{lat},{lon}",
                headers={"User-Agent": USER_AGENT},
            )
            r2.raise_for_status()
            pd = r2.json()
            props = pd.get("properties", {})
            return ResolvedLocation(
                latitude=lat,
                longitude=lon,
                nws_office=props.get("gridId", ""),
                nws_grid_x=int(props.get("gridX", 0)),
                nws_grid_y=int(props.get("gridY", 0)),
                label=label,
            )
        except Exception as e:
            log.warning("NWS gridpoint for %s,%s failed: %s", lat, lon, e)
            return None


async def fetch_subscriber_forecast(sub: WeatherAlertSubscriber) -> list[dict]:
    """Fetch + transform a subscriber's 7-day forecast.  Returns [] on failure."""
    if not sub.has_location:
        return []
    url = f"https://api.weather.gov/gridpoints/{sub.nws_office}/{sub.nws_grid_x},{sub.nws_grid_y}/forecast"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            data = r.json()
        return [_to_period(p) for p in data.get("properties", {}).get("periods", [])]
    except Exception as e:
        log.warning("Forecast fetch for sub %s failed: %s", sub.email, e)
        return []


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------

@dataclass
class SubscribeResult:
    subscriber: WeatherAlertSubscriber
    is_new: bool                 # False if email already existed
    confirmation_email: ComposedEmail | None  # None if already confirmed (re-subscribe)


def _public_base_url() -> str:
    """Where the confirm + unsubscribe links should point."""
    settings = get_settings()
    return getattr(settings, "public_base_url", "http://localhost:5174").rstrip("/")


async def subscribe(
    db: AsyncSession,
    *,
    email: str,
    zip_code: str,
    alert_opt_in: bool = True,
    promo_opt_in: bool = False,
    source_url: str | None = None,
    user_agent: str | None = None,
) -> SubscribeResult:
    """Top-level signup entry.  Idempotent on email — re-subscribing an
    existing email rotates the confirmation token if not yet confirmed,
    or just updates the ZIP / opt-in flags if already active."""
    email = email.strip().lower()
    zip5 = zip_code.strip()[:5]
    if not EMAIL_RE.match(email):
        raise ValueError("Invalid email")
    if not ZIP_RE.match(zip5):
        raise ValueError("Invalid ZIP code (expecting 5 digits)")

    existing = (await db.execute(
        select(WeatherAlertSubscriber).where(WeatherAlertSubscriber.email == email)
    )).scalar_one_or_none()

    is_new = existing is None
    if existing is None:
        sub = WeatherAlertSubscriber(
            email=email,
            zip_code=zip5,
            alert_opt_in=alert_opt_in,
            promo_opt_in=promo_opt_in,
            confirmation_token=secrets.token_urlsafe(32),
            unsubscribe_token=secrets.token_urlsafe(32),
            source_url=source_url,
            user_agent=user_agent,
        )
        db.add(sub)
    else:
        sub = existing
        # If they were unsubscribed, treat this as resubscribe
        if sub.unsubscribed_at is not None:
            sub.unsubscribed_at = None
            sub.unsubscribe_reason = None
        # Update ZIP if changed (re-resolve location)
        zip_changed = sub.zip_code != zip5
        if zip_changed:
            sub.zip_code = zip5
            sub.latitude = sub.longitude = None
            sub.nws_office = None
            sub.nws_grid_x = sub.nws_grid_y = None
            sub.location_label = None
            sub.nws_resolved_at = None
        sub.alert_opt_in = alert_opt_in
        sub.promo_opt_in = promo_opt_in
        # If they hadn't confirmed yet, rotate the token (in case the old
        # email got lost) so the new confirmation link works
        if sub.confirmed_at is None:
            sub.confirmation_token = secrets.token_urlsafe(32)

    # Best-effort location resolution.  If it fails, the daily cron will retry.
    if not sub.has_location:
        loc = await resolve_zip(zip5)
        if loc:
            sub.latitude = loc.latitude
            sub.longitude = loc.longitude
            sub.nws_office = loc.nws_office
            sub.nws_grid_x = loc.nws_grid_x
            sub.nws_grid_y = loc.nws_grid_y
            sub.location_label = loc.label
            sub.nws_resolved_at = datetime.now(timezone.utc)

    await db.flush()

    base_url = _public_base_url()
    if sub.confirmed_at is None:
        email_obj = compose_confirmation_email(sub, base_url)
    else:
        # Already confirmed re-signup — send a "preferences updated" note
        email_obj = compose_preferences_updated_email(sub, base_url)

    return SubscribeResult(subscriber=sub, is_new=is_new, confirmation_email=email_obj)


async def confirm(db: AsyncSession, token: str) -> WeatherAlertSubscriber:
    """Confirm a pending signup by token.  Idempotent: if already confirmed,
    returns the row unchanged."""
    sub = (await db.execute(
        select(WeatherAlertSubscriber).where(WeatherAlertSubscriber.confirmation_token == token)
    )).scalar_one_or_none()
    if sub is None:
        raise LookupError("Invalid confirmation token")
    if sub.confirmed_at is None:
        sub.confirmed_at = datetime.now(timezone.utc)
        await db.flush()
    return sub


async def unsubscribe(db: AsyncSession, token: str, reason: str | None = None) -> WeatherAlertSubscriber:
    """One-click unsubscribe by token.  Idempotent."""
    sub = (await db.execute(
        select(WeatherAlertSubscriber).where(WeatherAlertSubscriber.unsubscribe_token == token)
    )).scalar_one_or_none()
    if sub is None:
        raise LookupError("Invalid unsubscribe token")
    if sub.unsubscribed_at is None:
        sub.unsubscribed_at = datetime.now(timezone.utc)
        sub.unsubscribe_reason = (reason or "")[:200]
        sub.alert_opt_in = False
        sub.promo_opt_in = False
        await db.flush()
    return sub


# ---------------------------------------------------------------------------
# Daily alert cron
# ---------------------------------------------------------------------------

@dataclass
class AlertSummary:
    checked: int        # subscribers walked
    skipped_inactive: int
    skipped_no_location: int
    skipped_dampened: int
    snow_detected: int  # subs whose forecast had snow in next 7d
    sent: int           # subs we actually emailed
    errors: list[str]


def _is_dampened(sub: WeatherAlertSubscriber, now: datetime) -> bool:
    if sub.last_alert_sent_at is None:
        return False
    return (now - sub.last_alert_sent_at) < timedelta(days=DAMPEN_DAYS)


def _find_snow_periods(periods: Iterable[dict]) -> list[dict]:
    """Return periods within the lookahead window that are snow/wintry."""
    return [p for p in periods if p.get("snow_risk") in ("snow", "wintry")]


async def run_daily_alerts(db: AsyncSession, *, dry_run: bool = False) -> AlertSummary:
    """Walk every active subscriber, fetch their forecast, send alert if snow
    appears in next 7 days and they're not dampened.

    `dry_run=True` runs the analysis but doesn't send emails or stamp the DB.
    """
    summary = AlertSummary(0, 0, 0, 0, 0, 0, [])
    now = datetime.now(timezone.utc)
    base_url = _public_base_url()

    subs = (await db.execute(select(WeatherAlertSubscriber))).scalars().all()
    for sub in subs:
        summary.checked += 1
        if not sub.is_active or not sub.alert_opt_in:
            summary.skipped_inactive += 1
            continue
        if not sub.has_location:
            summary.skipped_no_location += 1
            # Try to backfill location once, but don't block this run
            loc = await resolve_zip(sub.zip_code)
            if loc:
                sub.latitude = loc.latitude
                sub.longitude = loc.longitude
                sub.nws_office = loc.nws_office
                sub.nws_grid_x = loc.nws_grid_x
                sub.nws_grid_y = loc.nws_grid_y
                sub.location_label = loc.label
                sub.nws_resolved_at = now
            continue
        if _is_dampened(sub, now):
            summary.skipped_dampened += 1
            continue

        periods = await fetch_subscriber_forecast(sub)
        snow_periods = _find_snow_periods(periods)
        if not snow_periods:
            continue
        summary.snow_detected += 1

        email = compose_alert_email(sub, snow_periods, base_url)
        if dry_run:
            summary.sent += 1  # would-have-sent
            continue
        try:
            send_email(email)
            sub.last_alert_sent_at = now
            sub.last_alert_subject = email.subject
            sub.total_alerts_sent += 1
            summary.sent += 1
        except Exception as e:
            summary.errors.append(f"{sub.email}: {e}")
        # Pace ourselves a bit so we don't burst-send
        await asyncio.sleep(0.05)

    if not dry_run:
        await db.flush()
    return summary


# ---------------------------------------------------------------------------
# Email composers (pure functions, easy to unit test)
# ---------------------------------------------------------------------------

def compose_confirmation_email(sub: WeatherAlertSubscriber, base_url: str) -> ComposedEmail:
    confirm_url = f"{base_url}/snow-alerts/confirm?token={sub.confirmation_token}"
    unsub_url = f"{base_url}/snow-alerts/unsubscribe?token={sub.unsubscribe_token}"
    body_text = (
        f"You signed up for snow forecast alerts at WinterWatch (Nelson Truck Equipment).\n\n"
        f"Confirm your subscription to start receiving alerts whenever snow\n"
        f"appears in the 10-day forecast for ZIP {sub.zip_code}:\n\n"
        f"  {confirm_url}\n\n"
        f"If you didn't sign up, just ignore this email or click here to remove your\n"
        f"address from our list:  {unsub_url}\n\n"
        f"-- WinterWatch by Nelson Truck Equipment\n"
    )
    body_html = f"""\
<p>You signed up for snow forecast alerts at WinterWatch (Nelson Truck Equipment).</p>
<p><strong>Confirm your subscription</strong> to start receiving alerts whenever snow
appears in the 10-day forecast for ZIP {sub.zip_code}:</p>
<p><a href="{confirm_url}" style="background:#b91c1c;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px;font-weight:bold">Confirm my email →</a></p>
<p style="color:#666;font-size:12px">If you didn't sign up, just ignore this email or
<a href="{unsub_url}">click here to remove your address from our list</a>.</p>
<p style="color:#666;font-size:12px">— WinterWatch <span style="color:#9ca3af">by Nelson Truck Equipment</span></p>
"""
    return ComposedEmail(
        to_email=sub.email,
        to_name=None,
        subject="Confirm your WinterWatch subscription",
        text_body=body_text,
        html_body=body_html,
    )


def compose_alert_email(sub: WeatherAlertSubscriber, snow_periods: list[dict], base_url: str) -> ComposedEmail:
    unsub_url = f"{base_url}/snow-alerts/unsubscribe?token={sub.unsubscribe_token}"
    snow_url = f"{base_url}/snow-plows"
    n = len(snow_periods)
    first = snow_periods[0]
    location = sub.location_label or sub.zip_code
    lines = []
    for p in snow_periods[:5]:
        lines.append(
            f"  • {p['name']}: {p['short_forecast']} "
            f"({p['temperature']}°{p['temperature_unit']}"
            + (f", {p['pop']}% precip" if p.get('pop') else "")
            + ")"
        )
    body_text = (
        f"❄ Snow is in the forecast for {location}.\n\n"
        f"NWS shows {n} period{'s' if n != 1 else ''} of snow or wintry mix in the\n"
        f"next 7 days, starting {first['name']}:\n\n"
        + "\n".join(lines)
        + f"\n\nGet your plow ready: {snow_url}\n\n"
        f"---\n"
        f"You're getting this because you signed up for snow alerts at\n"
        f"Nelson Truck Equipment for ZIP {sub.zip_code}.\n"
        f"Unsubscribe: {unsub_url}\n"
    )
    rows = "".join(
        f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e5e7eb'><strong>{p['name']}</strong></td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #e5e7eb'>{p['short_forecast']}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:right'>{p['temperature']}°{p['temperature_unit']}</td></tr>"
        for p in snow_periods[:7]
    )
    body_html = f"""\
<div style="font-family:system-ui,sans-serif;max-width:560px">
  <h2 style="color:#1e3a8a;margin-bottom:6px">❄ Snow in the forecast for {location}</h2>
  <p>NWS shows <strong>{n} period{'s' if n != 1 else ''}</strong> of snow or wintry mix in the next 7 days,
  starting <strong>{first['name']}</strong>.</p>
  <table style="border-collapse:collapse;width:100%;margin:16px 0">{rows}</table>
  <p><a href="{snow_url}" style="background:#b91c1c;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px;font-weight:bold">Shop snow plows + parts →</a></p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
  <p style="color:#666;font-size:12px">
    You're getting this because you signed up for snow alerts at WinterWatch (Nelson Truck Equipment) for ZIP {sub.zip_code}.
    <a href="{unsub_url}">Unsubscribe</a>.
  </p>
</div>
"""
    return ComposedEmail(
        to_email=sub.email,
        to_name=None,
        subject=f"❄ WinterWatch — snow in the forecast for {location}",
        text_body=body_text,
        html_body=body_html,
    )


def compose_welcome_email(sub: WeatherAlertSubscriber, base_url: str) -> ComposedEmail:
    unsub_url = f"{base_url}/snow-alerts/unsubscribe?token={sub.unsubscribe_token}"
    body_text = (
        f"You're confirmed for snow forecast alerts at ZIP {sub.zip_code}.\n\n"
        f"We check the 10-day NWS forecast every morning and email you when snow\n"
        f"appears in the window.\n\n"
        + (
            f"You also opted in to occasional promotional emails about snow & ice removal\n"
            f"gear — pre-season pricing, new arrivals, parts deals.\n\n"
            if sub.promo_opt_in else ""
        )
        + f"To stop receiving these emails any time: {unsub_url}\n"
    )
    body_html = f"""\
<div style="font-family:system-ui,sans-serif;max-width:560px">
  <h2 style="color:#1e3a8a">✓ You're confirmed for ZIP {sub.zip_code}</h2>
  <p>We check the 10-day NWS forecast every morning and email you when snow appears in the window.</p>
  {'<p>You also opted in to occasional promotional emails about snow &amp; ice removal gear — pre-season pricing, new arrivals, parts deals.</p>' if sub.promo_opt_in else ''}
  <p style="color:#666;font-size:12px">To stop receiving these emails any time: <a href="{unsub_url}">unsubscribe</a>.</p>
</div>
"""
    return ComposedEmail(
        to_email=sub.email,
        to_name=None,
        subject="You're confirmed for WinterWatch alerts",
        text_body=body_text,
        html_body=body_html,
    )


def compose_unsubscribed_email(sub: WeatherAlertSubscriber) -> ComposedEmail:
    body_text = (
        f"You've been removed from snow alerts at WinterWatch (Nelson Truck Equipment).\n"
        f"You won't receive any further emails from us.\n\n"
        f"If this was a mistake, you can re-subscribe at https://nelsontruck.com/snow-plows\n"
    )
    return ComposedEmail(
        to_email=sub.email,
        to_name=None,
        subject="You're unsubscribed from snow alerts",
        text_body=body_text,
        html_body=f"<p>{body_text.replace(chr(10), '<br>')}</p>",
    )


def compose_preferences_updated_email(sub: WeatherAlertSubscriber, base_url: str) -> ComposedEmail:
    unsub_url = f"{base_url}/snow-alerts/unsubscribe?token={sub.unsubscribe_token}"
    body_text = (
        f"Your snow alert preferences are updated for ZIP {sub.zip_code}.\n"
        + (f"  • Snow alerts: ON\n" if sub.alert_opt_in else "  • Snow alerts: OFF\n")
        + (f"  • Promotional emails: ON\n" if sub.promo_opt_in else "  • Promotional emails: OFF\n")
        + f"\nUnsubscribe: {unsub_url}\n"
    )
    return ComposedEmail(
        to_email=sub.email,
        to_name=None,
        subject="Snow alert preferences updated",
        text_body=body_text,
        html_body=f"<p>{body_text.replace(chr(10), '<br>')}</p>",
    )
