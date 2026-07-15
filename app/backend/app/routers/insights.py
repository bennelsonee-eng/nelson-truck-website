"""Internal insights endpoints — competitive landscape, etc.

These are admin-leaning informational endpoints, not customer-facing.
Phase 1.5 will gate behind `require_admin` once the admin role is fully
wired (currently the route is open since there's no PII).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.competitor_audit import (
    average_score,
    competitor_to_dict,
    get_dimensions,
    list_competitors,
)


router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/competitors")
async def competitors(tier: str | None = Query(None, description="Filter by tier: us / local / national / snow_specialist / manufacturer / reference")) -> dict:
    items = list_competitors(tier=tier)
    return {
        "dimensions": get_dimensions(),
        "competitors": [
            {
                **competitor_to_dict(c),
                "average_score": average_score(c),
            }
            for c in items
        ],
    }
