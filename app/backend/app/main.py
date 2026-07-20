import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import account, admin, admin_catalog, admin_kits, admin_messages, auth, banner, build_ideas, cart, catalog, configurator, content, deals, deweze, error_reports, fitment, health, health_reports, insights, orders, pace_catalog, rebate, rma, seo, showroom, signals, telemetry, weather_alerts, ymm
from app.services import cf_access, content_store, request_telemetry, tester_activity
from app.services.admin_audit import audit_admin_request
from app.services.banner_link_cron import run_daily_loop as run_banner_link_loop
from app.services.facs_heartbeat import run_heartbeat_loop
from app.services.kit_inventory import run_kit_stock_loop
from app.services.weather_alert_cron import run_daily_loop as run_winterwatch_loop

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks. Background services register here as they're built."""
    logger.info("Starting %s (environment=%s)", settings.app_name, settings.environment)

    # Admin-editable content pages (FAQ + trust pages) — create the override
    # table if absent. Self-applying, no manual migration on deploy.
    try:
        await content_store.ensure_table()
        logger.info("content_page table ensured")
    except Exception:
        logger.exception("Failed to ensure content_page table")

    # Request telemetry (Phase 2 site-health) — always-on error + bot + JS-error
    # log for the nightly report. Self-applying DDL, no manual migration.
    try:
        await request_telemetry.ensure_table()
        logger.info("request_log table ensured")
    except Exception:
        logger.exception("Failed to ensure request_log table")

    # Cloudflare-Access tester activity log — create its table when Access is
    # configured (no-op for local dev / Tailscale-only where cf_access_aud is unset).
    if cf_access.is_enabled():
        try:
            await tester_activity.ensure_table()
            logger.info("Cloudflare Access enabled — tester_activity table ensured")
        except Exception:
            logger.exception("Failed to ensure tester_activity table")

    background_tasks: list[asyncio.Task] = []

    # FACS pickup heartbeat — every 5 minutes by default.  Disabled in tests
    # via DISABLE_BACKGROUND_TASKS=1 to keep test sessions deterministic.
    if not os.environ.get("DISABLE_BACKGROUND_TASKS"):
        heartbeat_task = asyncio.create_task(
            run_heartbeat_loop(interval_seconds=300),
            name="facs_heartbeat",
        )
        background_tasks.append(heartbeat_task)
        logger.info("FACS heartbeat task launched")

    # WinterWatch — daily snow forecast alert run, 7am PT.
    if not os.environ.get("DISABLE_BACKGROUND_TASKS"):
        winterwatch_task = asyncio.create_task(
            run_winterwatch_loop(),
            name="winterwatch_daily",
        )
        background_tasks.append(winterwatch_task)
        logger.info("WinterWatch daily alert loop launched")

    # Kit-stock derivation — keep package (kit) stock in lockstep with their
    # component inventory + the search index. Runs every titan_inventory_sync
    # interval so kit stock follows whenever component inventory changes.
    if not os.environ.get("DISABLE_BACKGROUND_TASKS"):
        kit_stock_task = asyncio.create_task(
            run_kit_stock_loop(interval_seconds=settings.titan_inventory_sync_minutes * 60),
            name="kit_stock",
        )
        background_tasks.append(kit_stock_task)
        logger.info("Kit-stock loop launched (every %d min)", settings.titan_inventory_sync_minutes)

    # Banner link health — nightly (~3am PT) sweep that flags broken banner
    # click-through links and auto-hides the offending slide until it's fixed.
    if not os.environ.get("DISABLE_BACKGROUND_TASKS"):
        banner_link_task = asyncio.create_task(
            run_banner_link_loop(),
            name="banner_link_check",
        )
        background_tasks.append(banner_link_task)
        logger.info("Banner link check loop launched (nightly)")

    # Other background services to wire in over Phase 1:
    # - inventory sync poller (15-min from Titan MySQL)
    # - nightly pricing sync (1am PST)
    # - daily reconciliation report

    try:
        yield
    finally:
        logger.info("Shutting down %s — cancelling %d background tasks",
                    settings.app_name, len(background_tasks))
        for t in background_tasks:
            t.cancel()
        for t in background_tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Nelson Truck Equipment — public ecommerce + B2B portal",
    lifespan=lifespan,
)

# CORS — allow Vite dev server + future production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Titan-specific ports (5174/4174) so we don't collide with Nelson ERP on 5173/4173
        "http://localhost:5174",  # Vite dev
        "http://localhost:4174",  # Vite preview
        "https://nelsontruck.com",
        "https://www.nelsontruck.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request telemetry middleware (Phase 2 site-health) — logs HTTP errors (4xx/5xx)
# and bot crawls to request_log for the nightly report. Static assets are skipped;
# the insert runs in a fire-and-forget task so it never adds latency. Best-effort.
@app.middleware("http")
async def request_telemetry_middleware(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    try:
        path = request.url.path
        if not (path.startswith("/static") or path.startswith("/assets")
                or path == "/api/telemetry/js-error"):
            ua = request.headers.get("user-agent", "")
            bot = request_telemetry.classify_bot(ua)
            status = response.status_code
            if status >= 400 or bot is not None:
                asyncio.create_task(request_telemetry.log(
                    kind=("error" if status >= 400 else "bot"),
                    method=request.method, path=path, status=status,
                    duration_ms=int((time.monotonic() - start) * 1000), bot=bot,
                    ip=request.headers.get("cf-connecting-ip", "")
                    or (request.client.host if request.client else ""),
                    user_agent=ua, referer=request.headers.get("referer", "")))
    except Exception:
        logger.exception("request telemetry middleware error")
    return response


# Cloudflare Access middleware — validates the per-request `Cf-Access-Jwt-Assertion`
# header (no-op unless cf_access_aud is set), stashes the verified tester identity
# on request.state for downstream dependencies, and logs API activity per identity.
# Tailscale/LAN requests carry no assertion header → identity is None → behaves
# exactly as before (admin cookie auth still governs admin endpoints).
@app.middleware("http")
async def cloudflare_access_middleware(request: Request, call_next):
    identity = await cf_access.verify_request(request) if cf_access.is_enabled() else None
    request.state.cf_identity = identity
    request.state.cf_email = identity.email if identity else None

    response = await call_next(request)

    if identity is not None:
        path = request.url.path
        # Log /api activity only; the pageview beacon writes its own row, and the
        # health check is too noisy to be useful.
        if (
            path.startswith("/api")
            and path != "/api/signals/pageview"
            and not path.startswith("/api/health")
        ):
            await tester_activity.log(
                email=identity.email,
                event="api",
                path=path,
                method=request.method,
                status=response.status_code,
                ip=request.headers.get("cf-connecting-ip", "")
                or (request.client.host if request.client else ""),
                user_agent=request.headers.get("user-agent", ""),
            )
    return response


# Admin audit middleware — records one audit_log row per privileged (ADMIN/
# EDITOR) state-mutating request. Cheap for ordinary traffic (bails before any
# DB hit unless the JWT role claim is admin/editor). Best-effort: never breaks
# the request it is auditing.
@app.middleware("http")
async def admin_audit_middleware(request: Request, call_next):
    response = await call_next(request)
    try:
        await audit_admin_request(request, response)
    except Exception:
        logger.exception("admin audit middleware error")
    return response


# Routers
app.include_router(health.router)
app.include_router(seo.router)
app.include_router(fitment.router)
app.include_router(content.router)
app.include_router(catalog.router)
app.include_router(auth.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(rma.router)
app.include_router(admin.router)
app.include_router(admin_kits.router)
app.include_router(admin_catalog.router)
app.include_router(admin_messages.router)
app.include_router(health_reports.router)
app.include_router(telemetry.router)
app.include_router(ymm.router)
app.include_router(signals.router)
app.include_router(insights.router)
app.include_router(weather_alerts.router)
app.include_router(configurator.router)
app.include_router(pace_catalog.router)
app.include_router(deweze.router)
app.include_router(account.router)
app.include_router(error_reports.router)
app.include_router(build_ideas.router)
app.include_router(banner.router)
app.include_router(deals.router)
app.include_router(rebate.router)
app.include_router(showroom.router)

# Static assets — snow-plow/truck imagery + category tiles + brand images.
# Lives at app/backend/static/ (one level up from app/). Served by uvicorn (no
# CDN in front), so we attach a long-lived Cache-Control: without it the browser
# revalidates every image on every page view (extra round-trips over Tailscale).
# These files are content-stable; when one changes the deploy bumps its mtime and
# StaticFiles' etag/last-modified still force a refetch.
class CachedStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.setdefault("Cache-Control", "public, max-age=604800")  # 7 days
        return resp


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    # follow_symlink=True: Nelson's static subdirs (product-images, brand_images,
    # …) are symlinks into Titan's shared image library, which resolve OUTSIDE
    # STATIC_DIR. Without this, StaticFiles' path-traversal guard 404s every
    # image. (Titan has the real dirs in place, so it doesn't need this.)
    app.mount("/static", CachedStaticFiles(directory=str(STATIC_DIR), follow_symlink=True), name="static")

# As Phase 1 modules come online they register here:
# app.include_router(account.router)
# app.include_router(admin.router)
