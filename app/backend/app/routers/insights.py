"""Internal insights endpoints — competitive landscape, etc.

These are internal endpoints, not customer-facing. The competitor scorecard
is Titan-era internal analysis, so it is admin-only (2026-09-22, launch audit).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import require_admin

from app.services.competitor_audit import (
    average_score,
    competitor_to_dict,
    get_dimensions,
    list_competitors,
)


router = APIRouter(prefix="/api/insights", tags=["insights"], dependencies=[Depends(require_admin)])


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
