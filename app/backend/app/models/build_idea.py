"""Build Ideas — an admin-only backlog of future website features.

A place to park "we should build this someday" ideas so they aren't lost in the
issue-report queue (which is for bugs/requests to action soon). Admins can add
ideas directly or promote an error report into an idea (the report's text is
copied and `source_report_id` keeps the link). Viewable only on the admin side
at /admin/build-ideas.

Status / priority are stored as plain strings (validated at the API layer) to
keep migrations simple — same pattern as showroom_receipt.status. Allowed
values live in the router as STATUSES / PRIORITIES.
"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BuildIdea(Base):
    """One future-build idea in the admin backlog."""

    __tablename__ = "build_idea"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Free-form bucket, e.g. "Catalog", "Merchandising", "Checkout". Optional.
    category: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    # idea | queued | in_progress | done | declined
    status: Mapped[str] = mapped_column(String(20), default="idea", nullable=False, index=True)
    # low | normal | high
    priority: Mapped[str] = mapped_column(String(10), default="normal", nullable=False, index=True)
    # manual | issue_report — where the idea came from.
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    # error_reports.id when promoted from a reported issue (else NULL).
    source_report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Admin email that created the idea (audit breadcrumb).
    created_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
