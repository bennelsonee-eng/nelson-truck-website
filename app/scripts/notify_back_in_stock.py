"""Sweep back-in-stock alerts: email subscribers when their SKU returns to stock.

L7 nightly notifier. For every BackInStockAlert with notified_at IS NULL,
sum product_inventory.on_hand for the SKU; if positive, send the email and
mark the row notified.

Run from app/ (one level above backend/) with the backend venv:
    cd /home/titan/titan-truck-website/app
    backend/.venv/bin/python -m scripts.notify_back_in_stock           # send + mark
    backend/.venv/bin/python -m scripts.notify_back_in_stock --dry-run # just report

Cron: invoke nightly. Frequency tradeoff: more frequent = customer hears
sooner but more risk of "we got 1 unit and 8 subscribers all rushed". Once
a day is fine for v1; can tighten later.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import BackInStockAlert, Brand, Product, ProductInventory  # noqa: E402
from app.services.email_service import ComposedEmail, send_email  # noqa: E402


log = logging.getLogger("notify_back_in_stock")


def compose_back_in_stock_email(*, sku: str, name: str, brand_name: str, total_on_hand: int, base_url: str) -> ComposedEmail:
    """Pure: build the back-in-stock notification email."""
    subject = f"Back in stock: {sku}"
    pdp_url = f"{base_url.rstrip('/')}/product/{sku}"
    text_body = (
        f"Good news — {brand_name} {sku} is back in stock at Titan Truck Equipment.\n\n"
        f"{name}\n"
        f"On hand: {total_on_hand}\n\n"
        f"Order it here: {pdp_url}\n\n"
        f"Heads up: stock can move fast. If you don't get to it today and it sells out\n"
        f"again, you'll need to re-subscribe to be notified the next time it returns.\n\n"
        f"— Titan Truck Equipment\n"
        f"Spokane HQ · 509-534-5010\n"
    )
    html_body = (
        f"<p>Good news — <strong>{brand_name} {sku}</strong> is back in stock at Titan Truck Equipment.</p>"
        f"<p><strong>{name}</strong><br>On hand: {total_on_hand}</p>"
        f'<p><a href="{pdp_url}" style="display:inline-block;background:#b91c1c;color:#fff;padding:8px 16px;text-decoration:none;border-radius:4px;font-weight:bold;">Order it now →</a></p>'
        f"<p style=\"font-size:12px;color:#666\">Stock moves fast. If you don't get to it today and it sells out again, "
        f"you'll need to re-subscribe to be notified the next time it returns.</p>"
        f"<p style=\"font-size:12px;color:#666\">— Titan Truck Equipment · Spokane HQ · 509-534-5010</p>"
    )
    return ComposedEmail(
        to_email="placeholder@example.com",  # caller overrides
        to_name=None,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


async def run(*, dry_run: bool) -> int:
    settings = get_settings()
    base_url = getattr(settings, "public_base_url", None) or "https://titan-prod.tail0c2fbc.ts.net"

    sent = 0
    skipped_no_stock = 0
    skipped_product_missing = 0
    failed = 0

    async with async_session() as db:
        # All pending subscriptions.
        pending = (await db.execute(
            select(BackInStockAlert)
            .where(BackInStockAlert.notified_at.is_(None))
            .order_by(BackInStockAlert.sku, BackInStockAlert.id)
        )).scalars().all()

        if not pending:
            log.info("No pending back-in-stock alerts.")
            return 0

        # Resolve product + stock totals per unique SKU (one query each).
        # The set is small in practice — pending demand is bursty around a
        # few SKUs, not spread across the catalog.
        unique_skus = {a.sku for a in pending}
        stock_rows = (await db.execute(
            select(
                Product.id, Product.sku, Product.name, Brand.name.label("brand_name"),
                func.coalesce(func.sum(ProductInventory.on_hand), 0).label("total_on_hand"),
            )
            .join(Brand, Brand.id == Product.brand_id)
            .outerjoin(ProductInventory, ProductInventory.product_id == Product.id)
            .where(Product.sku.in_(unique_skus))
            .group_by(Product.id, Brand.name)
        )).all()
        stock_lookup = {r.sku: r for r in stock_rows}

        log.info("Pending alerts: %d across %d unique SKUs", len(pending), len(unique_skus))

        for alert in pending:
            row = stock_lookup.get(alert.sku)
            if row is None:
                skipped_product_missing += 1
                continue
            total = int(row.total_on_hand or 0)
            if total <= 0:
                skipped_no_stock += 1
                continue
            email = compose_back_in_stock_email(
                sku=row.sku, name=row.name, brand_name=row.brand_name,
                total_on_hand=total, base_url=base_url,
            )
            email = ComposedEmail(
                to_email=alert.email, to_name=None, subject=email.subject,
                text_body=email.text_body, html_body=email.html_body,
            )
            if dry_run:
                log.info("[dry-run] would send → %s for %s (%d on hand)", alert.email, alert.sku, total)
                sent += 1
                continue
            result = send_email(email)
            if not result.ok:
                log.warning("send failed for alert %d (%s → %s): %s", alert.id, alert.sku, alert.email, result.error)
                failed += 1
                continue
            await db.execute(
                update(BackInStockAlert)
                .where(BackInStockAlert.id == alert.id)
                .values(notified_at=datetime.now(tz=timezone.utc))
            )
            sent += 1

        if not dry_run:
            await db.commit()

    log.info(
        "back-in-stock sweep done: sent=%d, no-stock=%d, missing-product=%d, failed=%d",
        sent, skipped_no_stock, skipped_product_missing, failed,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Don't send or mark; just log what would happen")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
