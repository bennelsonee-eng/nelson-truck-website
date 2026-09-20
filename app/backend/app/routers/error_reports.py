"""
Error Report API — in-app issue recorder for the Nelson Truck website.

Admin-only. The frontend ErrorReporter panel records a screen video (webm +
mic audio), a live voice transcript, click events, pages visited, DOM/route
state, and microphone diagnostics. Reports are saved here and pulled in
Claude Code for resolution.

Ported/adapted from the Nelson ERP error reporter, using this site's auth
(`require_admin`) + cookie session. No ORM model — raw SQL keeps it
self-contained. The table is defined in
`app/scripts/create_error_reports_table.sql`: it used to be created by hand
against the database with nothing in the repo, and this site inherited the
code without it, so every report 500'd on the final INSERT while the panel
reported success.

Endpoints:
  POST   /api/error-reports              — create a report, returns {id}
  POST   /api/error-reports/{id}/video   — upload the screen recording (.webm)
  GET    /api/error-reports              — list (newest first; ?status= filter)
  GET    /api/error-reports/{id}         — full detail
  PATCH  /api/error-reports/{id}         — update status / resolution_notes
  DELETE /api/error-reports/{id}         — delete (also removes the video file)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session, get_db
from app.dependencies import ReporterIdentity, require_admin, require_reporter
from app.models import User
from app.services import transcription
from app.services.email_service import AuthSmtpSender, ComposedEmail, send_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/error-reports", tags=["Error Reports"])

# Videos live OUTSIDE the public /static mount and are served only through the
# admin-gated GET endpoint below — a report can record any page (incl. admin
# views), so the recording must not be reachable by URL guess.
VIDEO_DIR = Path(__file__).resolve().parent.parent.parent / "error_report_media"

VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}


# A recorder session must never be lost because of a character in it.
#
# Ported from the Nelson ERP (commits 0b8da8f3 and 499a9035), which lost reports
# this way twice before the cause was found. The first vanished on 2026-08-28:
# the POST returned 500 with
#     invalid input syntax for type json
#     DETAIL: Unicode low surrogate must follow a high surrogate
# after the capture clicked a sidebar link whose label starts with an emoji.
#
# The JSON columns here are jsonb, which PARSES what it stores (a plain `json`
# column would not), and PostgreSQL rejects an unpaired UTF-16 surrogate
# outright. That gap is why this hid for so long: a test asserting only "this is
# valid JSON" passes on a payload the database will refuse.
#
# The lone half comes from the browser. JavaScript strings are UTF-16, so any
# client-side slice() -- and this panel slices captured click text, the first
# speech segment and the joined transcript -- can cut an emoji between its two
# surrogates and send the leftover on its own. Python then holds a real
# surrogate codepoint, which is not encodable as UTF-8 at all, so it breaks the
# plain text columns too, not just the jsonb ones.
#
# Stripping every surrogate is safe: Python stores an intact emoji as ONE
# codepoint, never as a pair, so anything left in U+D800-U+DFFF is a broken half
# carrying no meaning. Emoji that arrived whole are untouched -- which matters
# here, because this site's own nav labels and category names carry them, so a
# recording that clicks one can trigger this.
#
# U+0000 is the same loss with a different character: PostgreSQL rejects it in
# jsonb ("unsupported Unicode escape sequence") and in every text column
# ("invalid byte sequence"), and it reaches us the same way, out of captured
# DOM text.
#
# Deliberately defensive rather than a fix to the caller: the recorder is how
# people tell us the site is broken, so it must not be the thing that breaks.
# And the loss is silent -- the panel said "your issue has been sent in" for
# every one of these.
_UNSTORABLE = re.compile(r"[\ud800-\udfff\x00]")


def _scrub(value, limit: int | None = None):
    """Strip characters PostgreSQL cannot store, and optionally truncate.

    Recurses into dicts and lists (and dict KEYS) because the break can be
    anywhere in a capture blob; non-strings pass through untouched.

    `limit` is the destination column's varchar width. Every column this router
    writes is unbounded `text` -- verified 2026-09-20 against both production
    databases and the checked-in table definition -- so nothing passes a limit
    today. That is the one way these sites differ from the ERP, where title(200),
    route(500) and browser_info(500) are bounded and an over-long value 500'd the
    POST. The parameter stays so narrowing a column is a one-word change here,
    and `test_every_written_column_is_unbounded` fails if one ever is.
    """
    if isinstance(value, str):
        cleaned = _UNSTORABLE.sub("", value)
        return cleaned[:limit] if limit else cleaned
    if isinstance(value, dict):
        return {_scrub(k): _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _jsonb(value) -> str:
    """Serialise for a jsonb column, with unstorable characters removed first."""
    return json.dumps(_scrub(value))


def _send_report_alert(
    report_id: int, title: str, route: str, severity: str, reported_by: str
) -> None:
    """Email someone that a report was filed.

    Until now a report only existed if somebody thought to open the queue and
    look, which meant a tester could record a problem, be told it was saved,
    and have it sit unread indefinitely. The recorder is the feedback channel
    for people who are not going to chase us a second time.

    Runs as a background task and swallows everything: the report is already
    committed by the time this is called, and a mail outage must never be the
    reason a filed report looks like a failure. `send_email` does not raise on
    its own, but the compose step and the settings lookup can.
    """
    try:
        settings = get_settings()
        to = (settings.error_report_alert_email or "").strip()
        if not to:
            logger.info("report %s: no alert address configured, not emailing", report_id)
            return
        site = settings.app_name
        body = (
            f"{reported_by or 'someone'} filed issue #{report_id} on the {site} site.\n\n"
            f"  Title:    {title}\n"
            f"  Page:     {route or '(not recorded)'}\n"
            f"  Severity: {severity}\n\n"
            "Open the site as an admin and use the Issues badge in the header to\n"
            "watch the recording and read the transcript.\n"
        )
        email = ComposedEmail(
            to_email=to,
            to_name=None,
            # Severity first: a critical report should be sortable in a mailbox
            # without opening it.
            subject=f"[{site}] {severity.upper()} issue #{report_id}: {title[:80]}",
            text_body=body,
        )
        # Alerts get their own mailbox, on purpose.
        #
        # This site runs EMAIL_PROVIDER=maildev before launch, so every email it
        # sends is caught locally and delivered nowhere. That is correct for
        # order confirmations and RMAs on a site that is not live yet -- and
        # useless for an issue alert, which is worth nothing if it is not read.
        # Switching the site-wide provider to make alerts work would also start
        # sending real customer mail from a pre-launch site, so instead an alert
        # can carry its own SMTP credentials and go out on its own.
        #
        # Unset (the default) means fall back to whatever the site uses, which
        # keeps this a no-op in dev.
        if settings.error_report_smtp_host and settings.error_report_smtp_user:
            sender = AuthSmtpSender(
                host=settings.error_report_smtp_host,
                port=settings.error_report_smtp_port,
                user=settings.error_report_smtp_user,
                password=settings.error_report_smtp_password,
                from_addr=settings.error_report_smtp_from or settings.error_report_smtp_user,
            )
            result = sender.send(email)
        else:
            result = send_email(email)
        if result.ok:
            logger.info("report %s: alert emailed to %s", report_id, to)
        else:
            logger.warning("report %s: alert email failed: %s", report_id, result.error)
    except Exception:
        logger.exception("report %s: alert email raised", report_id)


async def _store_transcript(report_id: int, result: dict) -> None:
    """Persist a server-side transcript onto a report. Fills description/title
    only when they're empty or auto-generated, so a human-typed title is never
    clobbered. Always refreshes speech_segments (the browser's were empty) and
    stamps provenance into mic_diagnostics."""
    meta = {"transcription": {
        "engine": "faster-whisper",
        "model": result.get("model"),
        "language": result.get("language"),
        "duration_s": result.get("duration"),
        "chars": len(result.get("text", "") or ""),
        "segments": len(result.get("segments", []) or []),
    }}
    async with async_session() as db:
        await db.execute(
            text("""
                UPDATE error_reports SET
                    speech_segments = CAST(:segs AS JSONB),
                    description = CASE
                        WHEN COALESCE(NULLIF(TRIM(description), ''), '') = ''
                        THEN :text ELSE description END,
                    title = CASE
                        WHEN title IS NULL OR title = '' OR title = 'Untitled report'
                             OR title LIKE 'Issue on %'
                        THEN LEFT(:text, 120) ELSE title END,
                    mic_diagnostics = COALESCE(mic_diagnostics, '{}'::jsonb) || CAST(:meta AS JSONB),
                    updated_at = now()
                WHERE id = :id
            """),
            {
                # Same guard as the create path. This one runs inside a
                # background task whose caller swallows every exception, so an
                # unstorable character here would lose the transcript with
                # nothing but a log line to show for it.
                "segs": _jsonb(result.get("segments", [])),
                "text": _scrub(result.get("text", "")),
                "meta": _jsonb(meta),
                "id": report_id,
            },
        )
        await db.commit()


async def _transcribe_report(report_id: int, path: str) -> None:
    """Background job: transcribe a report's recording and store the result.
    Runs the CPU-bound model in a worker thread so the event loop stays free.
    Swallows all failures — the report already exists with its video."""
    try:
        result = await asyncio.to_thread(transcription.transcribe, path)
        if result and result.get("text"):
            await _store_transcript(report_id, result)
            logger.info("transcribed report %s (%d chars)", report_id, len(result["text"]))
        else:
            logger.info("report %s: no transcript (silent or disabled)", report_id)
    except Exception:
        logger.exception("background transcription failed for report %s", report_id)


class ErrorReportCreate(BaseModel):
    title: str = ""
    description: str = ""           # spoken summary (joined transcript)
    route: str = ""                 # page path where the issue was reported
    severity: str = "normal"        # low | normal | high | critical
    speech_segments: list = []      # [{text, timestamp_ms, confidence}]
    click_events: list = []         # [{tag, text, selector, url, timestamp_ms}]
    pages_visited: list = []        # ["/", "/product/MYP-41660", ...]
    dom_state: dict = {}            # optional DOM snapshot per route
    mic_diagnostics: dict = {}      # {secure_context, speech_supported, errors:[...], ...}
    browser_info: str = ""          # navigator.userAgent


class ErrorReportPatch(BaseModel):
    status: str | None = None
    resolution_notes: str | None = None
    severity: str | None = None
    title: str | None = None


@router.post("")
async def create_error_report(
    body: ErrorReportCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    reporter: ReporterIdentity = Depends(require_reporter),
):
    """Save a new error report from the in-app recorder.

    Filed by an app admin/editor OR a Cloudflare-Access-verified preview tester
    (the latter with reported_by_user_id=NULL, email in reported_by_username).
    """
    title = body.title
    if not title and body.speech_segments:
        title = (body.speech_segments[0].get("text", "") or "")[:120]
    if not title:
        title = f"Issue on {body.route}" if body.route else "Untitled report"

    description = body.description
    if not description and body.speech_segments:
        description = " ".join(s.get("text", "") for s in body.speech_segments)[:4000]

    # Scrub before anything else touches these. The scrubbed values are what we
    # store, what we put in the alert email, and what we hand back to the panel
    # -- a lone surrogate left in the title would also fail the JSON encoding of
    # our own 200 response, turning a committed report into a 500 that the panel
    # would (correctly, now) report as a failure.
    title = _scrub(title)
    description = _scrub(description)
    route = _scrub(body.route)
    username = _scrub(reporter.username)
    severity = (body.severity if body.severity in
                {"low", "normal", "high", "critical"} else "normal")

    insert_sql = text("""
        INSERT INTO error_reports (
            title, description, route, severity, status,
            reported_by_user_id, reported_by_username,
            speech_segments, click_events, pages_visited,
            dom_state, mic_diagnostics, browser_info
        ) VALUES (
            :title, :description, :route, :severity, 'open',
            :user_id, :username,
            CAST(:speech_segments AS JSONB), CAST(:click_events AS JSONB),
            CAST(:pages_visited AS JSONB), CAST(:dom_state AS JSONB),
            CAST(:mic_diagnostics AS JSONB), :browser_info
        ) RETURNING id
    """)

    params = {
        "title": title,
        "description": description,
        "route": route,
        "severity": severity,
        "user_id": reporter.user_id,
        "username": username,
        "speech_segments": _jsonb(body.speech_segments),
        "click_events": _jsonb(body.click_events),
        "pages_visited": _jsonb(body.pages_visited),
        "dom_state": _jsonb(body.dom_state),
        "mic_diagnostics": _jsonb(body.mic_diagnostics),
        "browser_info": _scrub(body.browser_info),
    }

    try:
        result = await db.execute(insert_sql, params)
        await db.commit()
    except Exception as exc:
        # Last-ditch save. The scrub covers the shapes we know break, but the
        # capture blobs come from the browser and we cannot enumerate every
        # future one. What the person SAID is the part of a report that cannot
        # be reconstructed, so retry once keeping the words and dropping the
        # machine-generated blobs rather than losing the lot.
        await db.rollback()
        logger.error(
            "error report insert failed (%s) - retrying without capture blobs; "
            "sizes: speech=%d clicks=%d pages=%d dom=%d",
            exc,
            len(params["speech_segments"]), len(params["click_events"]),
            len(params["pages_visited"]), len(params["dom_state"]),
        )
        degraded = dict(params)
        for key in ("speech_segments", "click_events", "pages_visited"):
            degraded[key] = "[]"
        for key in ("dom_state", "mic_diagnostics"):
            degraded[key] = "{}"
        degraded["description"] = (
            (params["description"] or "")
            + "\n\n[Capture detail was dropped - it could not be stored. "
              "See the server log.]"
        )
        result = await db.execute(insert_sql, degraded)
        await db.commit()

    new_id = result.fetchone()[0]

    # Committed first, alerted after: the report is safe on disk before we go
    # near the mail provider, so a slow or failing send can only cost the
    # notification, never the report itself.
    background.add_task(
        _send_report_alert, new_id, title, route, severity, username,
    )
    return {"id": new_id, "title": title, "status": "open"}


@router.post("/{report_id}/video")
async def upload_video(
    report_id: int,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    reporter: ReporterIdentity = Depends(require_reporter),
):
    """Attach the screen recording (.webm) to an existing report.

    Admins may attach to any report; a tester only to a report they filed.
    """
    row = (await db.execute(
        text("SELECT reported_by_username FROM error_reports WHERE id = :id"),
        {"id": report_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    if not reporter.is_admin and row[0] != reporter.username:
        raise HTTPException(status_code=403, detail="Not your report")

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    dest = VIDEO_DIR / f"{report_id}.webm"
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
            size += len(chunk)

    public_path = f"/api/error-reports/{report_id}/video"
    await db.execute(
        text("UPDATE error_reports SET video_path = :p, updated_at = now() WHERE id = :id"),
        {"p": public_path, "id": report_id},
    )
    await db.commit()

    # Transcribe the recording's audio in the background (the browser's live
    # transcript is unreliable). The report is already saved; the transcript
    # fills in shortly after and is visible on GET /{id}.
    if transcription.is_enabled() and size > 0:
        background.add_task(_transcribe_report, report_id, str(dest))

    return {"id": report_id, "video_path": public_path, "bytes": size}


@router.get("/{report_id}/video")
async def get_video(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Stream a report's screen recording. Admin-gated — recordings can show
    admin/internal pages, so they are not exposed via a public static mount."""
    path = VIDEO_DIR / f"{report_id}.webm"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No video for this report")
    return FileResponse(
        str(path), media_type="video/webm", filename=f"error-report-{report_id}.webm"
    )


@router.post("/{report_id}/transcribe")
async def transcribe_report(
    report_id: int,
    admin: User = Depends(require_admin),
):
    """(Re)transcribe a report's recording server-side and store the result.

    Synchronous — returns the transcript text. Used to backfill reports whose
    browser (Web Speech) transcript came back empty, or to re-run with a better
    model. Runs the CPU-bound model off the event loop."""
    if not transcription.is_enabled():
        raise HTTPException(status_code=503, detail="Transcription is disabled")
    path = VIDEO_DIR / f"{report_id}.webm"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No video for this report")

    result = await asyncio.to_thread(transcription.transcribe, str(path))
    if result is None:
        raise HTTPException(status_code=500, detail="Transcription failed")
    if result.get("text"):
        await _store_transcript(report_id, result)

    return {
        "id": report_id,
        "text": result.get("text", ""),
        "segments": len(result.get("segments", [])),
        "language": result.get("language"),
        "duration": result.get("duration"),
        "model": result.get("model"),
    }


@router.get("")
async def list_error_reports(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """List reports, newest first. Optional ?status= filter."""
    where, params = "WHERE 1=1", {}
    if status:
        where += " AND status = :status"
        params["status"] = status
    rows = (await db.execute(text(f"""
        SELECT id, title, description, route, severity, status,
               reported_by_username, video_path, created_at, resolved_at,
               speech_segments, click_events, pages_visited
        FROM error_reports {where}
        ORDER BY created_at DESC LIMIT 100
    """), params)).fetchall()

    out = []
    for r in rows:
        speech = r[10] if isinstance(r[10], list) else []
        clicks = r[11] if isinstance(r[11], list) else []
        pages = r[12] if isinstance(r[12], list) else []
        out.append({
            "id": r[0], "title": r[1], "description": (r[2] or "")[:240],
            "route": r[3], "severity": r[4], "status": r[5],
            "reported_by": r[6], "video_path": r[7],
            "reported_at": str(r[8]), "resolved_at": str(r[9]) if r[9] else None,
            "speech_segment_count": len(speech),
            "click_event_count": len(clicks),
            "pages_visited": pages,
        })
    return out


@router.get("/stats")
async def error_report_stats(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Counts by status + an `unresolved` total (open + in_progress) for the
    admin header alert badge. Declared before /{report_id} so the literal path
    wins the route match."""
    rows = (await db.execute(text(
        "SELECT status, COUNT(*) FROM error_reports GROUP BY status"
    ))).fetchall()
    by_status = {r[0]: r[1] for r in rows}
    return {
        "open": by_status.get("open", 0),
        "in_progress": by_status.get("in_progress", 0),
        "resolved": by_status.get("resolved", 0),
        "closed": by_status.get("closed", 0),
        "unresolved": by_status.get("open", 0) + by_status.get("in_progress", 0),
    }


@router.get("/{report_id}")
async def get_error_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Full report detail."""
    result = await db.execute(
        text("SELECT * FROM error_reports WHERE id = :id"), {"id": report_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    data = dict(zip(result.keys(), row))
    for k in ("created_at", "updated_at", "resolved_at"):
        if data.get(k) is not None:
            data[k] = str(data[k])
    return data


@router.patch("/{report_id}")
async def update_error_report(
    report_id: int,
    body: ErrorReportPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Update status / resolution. Sets resolved_at when moving to resolved/closed."""
    sets, params = [], {"id": report_id}
    if body.status is not None:
        if body.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Use {VALID_STATUSES}")
        sets.append("status = :status")
        params["status"] = body.status
        if body.status in ("resolved", "closed"):
            sets.append("resolved_at = COALESCE(resolved_at, now())")
        else:
            sets.append("resolved_at = NULL")
    if body.resolution_notes is not None:
        sets.append("resolution_notes = :rn")
        params["rn"] = _scrub(body.resolution_notes)
    if body.severity is not None:
        sets.append("severity = :sev")
        params["sev"] = body.severity
    if body.title is not None:
        sets.append("title = :title")
        params["title"] = _scrub(body.title)
    if not sets:
        raise HTTPException(status_code=400, detail="No fields to update")

    sets.append("updated_at = now()")
    result = await db.execute(
        text(f"UPDATE error_reports SET {', '.join(sets)} WHERE id = :id RETURNING id, status"),
        params,
    )
    await db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"id": row[0], "status": row[1]}


@router.delete("/{report_id}")
async def delete_error_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Delete a report and its video file."""
    await db.execute(text("DELETE FROM error_reports WHERE id = :id"), {"id": report_id})
    await db.commit()
    vid = VIDEO_DIR / f"{report_id}.webm"
    try:
        vid.unlink(missing_ok=True)
    except OSError:
        pass
    return {"status": "deleted"}
