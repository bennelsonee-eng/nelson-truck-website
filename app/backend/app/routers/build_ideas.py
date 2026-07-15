"""Build Ideas — admin-only future-build backlog API.

A parking lot for "build this someday" website features, kept separate from the
error-report queue (which is for things to action soon). Admin-only on every
route. Ideas can be added directly or promoted from an error report.

    GET    /api/admin/build-ideas?status=&category=&q=
    POST   /api/admin/build-ideas
    PATCH  /api/admin/build-ideas/{idea_id}
    DELETE /api/admin/build-ideas/{idea_id}
    POST   /api/admin/build-ideas/from-report/{report_id}   (+ ?resolve=true)
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models import BuildIdea, User

router = APIRouter(prefix="/api/admin/build-ideas", tags=["build-ideas"])

# Allowed values (stored as plain strings on build_idea). Kept here, not in the
# DB, so adding a state is a code change not a migration.
STATUSES = ("idea", "queued", "in_progress", "done", "declined")
PRIORITIES = ("low", "normal", "high")

StatusT = Literal["idea", "queued", "in_progress", "done", "declined"]
PriorityT = Literal["low", "normal", "high"]


class IdeaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    detail: str = ""
    category: str = ""
    status: StatusT = "idea"
    priority: PriorityT = "normal"


class IdeaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=300)
    detail: str | None = None
    category: str | None = None
    status: StatusT | None = None
    priority: PriorityT | None = None


def _serialize(i: BuildIdea) -> dict[str, Any]:
    return {
        "id": i.id,
        "title": i.title,
        "detail": i.detail,
        "category": i.category,
        "status": i.status,
        "priority": i.priority,
        "source": i.source,
        "source_report_id": i.source_report_id,
        "created_by": i.created_by,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }


@router.get("")
async def list_ideas(
    status_f: str | None = Query(None, alias="status"),
    category: str | None = Query(None),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    stmt = select(BuildIdea)
    if status_f:
        stmt = stmt.where(BuildIdea.status == status_f)
    if category:
        stmt = stmt.where(BuildIdea.category == category)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(BuildIdea.title.ilike(like), BuildIdea.detail.ilike(like)))
    # Open work first (idea/queued/in_progress) then done/declined; newest first.
    rows = (await db.execute(stmt)).scalars().all()
    _rank = {"in_progress": 0, "queued": 1, "idea": 2, "done": 3, "declined": 4}
    _prio = {"high": 0, "normal": 1, "low": 2}
    rows = sorted(
        rows,
        key=lambda i: (_rank.get(i.status, 9), _prio.get(i.priority, 9), -(i.id or 0)),
    )
    # Category list for the filter dropdown.
    cats = sorted({i.category for i in rows if i.category})
    return {"ideas": [_serialize(i) for i in rows], "categories": cats, "total": len(rows)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_idea(
    body: IdeaCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    idea = BuildIdea(
        title=body.title.strip(),
        detail=body.detail or "",
        category=(body.category or "").strip(),
        status=body.status,
        priority=body.priority,
        source="manual",
        created_by=admin.email or "",
    )
    db.add(idea)
    await db.commit()
    await db.refresh(idea)
    return _serialize(idea)


@router.patch("/{idea_id}")
async def update_idea(
    idea_id: int,
    body: IdeaPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    idea = (await db.execute(select(BuildIdea).where(BuildIdea.id == idea_id))).scalar_one_or_none()
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        idea.title = data["title"].strip()
    if "detail" in data and data["detail"] is not None:
        idea.detail = data["detail"]
    if "category" in data and data["category"] is not None:
        idea.category = data["category"].strip()
    if "status" in data and data["status"] is not None:
        idea.status = data["status"]
    if "priority" in data and data["priority"] is not None:
        idea.priority = data["priority"]
    await db.commit()
    await db.refresh(idea)
    return _serialize(idea)


@router.delete("/{idea_id}")
async def delete_idea(
    idea_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    idea = (await db.execute(select(BuildIdea).where(BuildIdea.id == idea_id))).scalar_one_or_none()
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    await db.delete(idea)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/from-report/{report_id}", status_code=status.HTTP_201_CREATED)
async def idea_from_report(
    report_id: int,
    resolve: bool = Query(True, description="Also mark the source report resolved"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Promote an error report into a build idea (copies its text, links back).

    error_reports is a raw table (no ORM model), so it's read via SQL.
    """
    row = (await db.execute(
        text("SELECT id, title, description FROM error_reports WHERE id = :id"),
        {"id": report_id},
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Report #{report_id} not found")
    # Don't duplicate if this report was already promoted.
    existing = (await db.execute(
        select(BuildIdea).where(BuildIdea.source_report_id == report_id)
    )).scalar_one_or_none()
    if existing is not None:
        return _serialize(existing)
    title = (row.title or f"Report #{report_id}").strip()[:300]
    idea = BuildIdea(
        title=title,
        detail=row.description or "",
        category="",
        status="idea",
        priority="normal",
        source="issue_report",
        source_report_id=report_id,
        created_by=admin.email or "",
    )
    db.add(idea)
    if resolve:
        await db.execute(
            text("UPDATE error_reports SET status = 'resolved', resolved_at = now(), "
                 "updated_at = now(), resolution_notes = COALESCE(NULLIF(resolution_notes, ''), "
                 ":note) WHERE id = :id"),
            {"id": report_id, "note": "Moved to Build Ideas (admin backlog)."},
        )
    await db.commit()
    await db.refresh(idea)
    return _serialize(idea)
