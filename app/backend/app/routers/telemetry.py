"""Public telemetry ingest — client-side JS errors from the SPA.

The frontend installs window.onerror + unhandledrejection handlers that POST here
when a page throws or a chunk fails to load ("pages that don't load"). Stored in
request_log (kind='js_error') for the nightly health report. Intentionally
unauthenticated (errors happen to anonymous shoppers too) and best-effort.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.services import request_telemetry

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


class JsError(BaseModel):
    message: str = ""
    source: str = ""
    line: int | None = None
    col: int | None = None
    stack: str = ""
    path: str = ""      # SPA route the error happened on
    kind: str = "error"  # 'error' | 'unhandledrejection' | 'chunk_load'


@router.post("/js-error")
async def js_error(payload: JsError, request: Request) -> dict:
    loc = f"{payload.source}:{payload.line}:{payload.col}" if payload.source else ""
    detail = f"[{payload.kind}] {payload.message}\n{loc}\n{payload.stack}".strip()
    await request_telemetry.log(
        kind="js_error",
        method="JS",
        path=payload.path or request.headers.get("referer", ""),
        detail=detail,
        ip=request.headers.get("cf-connecting-ip", "")
        or (request.client.host if request.client else ""),
        user_agent=request.headers.get("user-agent", ""),
        referer=request.headers.get("referer", ""),
    )
    return {"ok": True}
