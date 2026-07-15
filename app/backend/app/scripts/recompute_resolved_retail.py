"""Backfill / refresh product_price.resolved_retail_price.

Run once after deploying the resolved-retail column, and any time the sentinel
("TITAN WEBSITE SALES") contracts change outside the normal price-sync path
(the nightly NTE price sync already refreshes the SKUs it touches):

    cd app/backend && .venv/bin/python -m app.scripts.recompute_resolved_retail

Recomputes every product that has a product_price row.
"""
import asyncio
import logging

from app.database import async_session
from app.services.pricing_service import recompute_resolved_retail

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("recompute_resolved_retail")


async def main() -> None:
    async with async_session() as db:
        n = await recompute_resolved_retail(db)
    log.info("resolved_retail recompute complete: %d product_price rows updated", n)


if __name__ == "__main__":
    asyncio.run(main())
