"""Request telemetry — always-on per-site error + bot logging (Phase 2 of the
site-health report).

Unlike tester_activity (which only logs Cloudflare-Access-authenticated testers),
this logs regardless of identity, focused on what the nightly health report needs:
HTTP errors (4xx/5xx), bot crawl volume + bot errors, and client-side JS errors.

Written to each site's own DB (titan_web / nelson_web) so attribution is per-site
automatically. Table is created via idempotent startup DDL — same no-Alembic
pattern as tester_activity / error_reports.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.database import async_session, engine

logger = logging.getLogger(__name__)

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS request_log (
        id          BIGSERIAL PRIMARY KEY,
        ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
        kind        TEXT        NOT NULL DEFAULT '',   -- 'error' | 'bot' | 'js_error'
        method      TEXT        NOT NULL DEFAULT '',
        path        TEXT        NOT NULL DEFAULT '',
        status      INTEGER,
        duration_ms INTEGER,
        bot         TEXT,                              -- classified bot name (NULL = human)
        ip          TEXT        NOT NULL DEFAULT '',
        user_agent  TEXT        NOT NULL DEFAULT '',
        referer     TEXT        NOT NULL DEFAULT '',
        detail      TEXT        NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_request_log_ts ON request_log (ts DESC)",
    "CREATE INDEX IF NOT EXISTS ix_request_log_status ON request_log (status)",
    "CREATE INDEX IF NOT EXISTS ix_request_log_kind_ts ON request_log (kind, ts DESC)",
]

# UA substring (lowercased) -> friendly bot name. Order matters (first hit wins).
_BOT_MAP = [
    ("googlebot", "Googlebot"), ("google-inspectiontool", "Googlebot"),
    ("bingbot", "Bingbot"), ("adidxbot", "Bingbot"),
    ("gptbot", "GPTBot"), ("oai-searchbot", "OAI-SearchBot"), ("chatgpt-user", "ChatGPT-User"),
    ("claudebot", "ClaudeBot"), ("claude-web", "Claude-Web"), ("anthropic-ai", "Anthropic-AI"),
    ("perplexitybot", "PerplexityBot"), ("perplexity", "PerplexityBot"),
    ("applebot", "Applebot"), ("amazonbot", "Amazonbot"), ("yandexbot", "YandexBot"),
    ("duckduckbot", "DuckDuckBot"), ("bytespider", "Bytespider"),
    ("facebookexternalhit", "Facebook"), ("meta-externalagent", "Meta"),
    ("twitterbot", "Twitterbot"), ("linkedinbot", "LinkedInBot"), ("slackbot", "Slackbot"),
    ("ahrefsbot", "AhrefsBot"), ("semrushbot", "SemrushBot"), ("mj12bot", "MJ12bot"),
    ("dotbot", "DotBot"), ("petalbot", "PetalBot"),
]


def classify_bot(ua: str) -> str | None:
    """Return a friendly bot name if the UA is a known crawler, else a generic
    'Other bot' for anything self-identifying as a bot/spider/crawler, else None."""
    if not ua:
        return None
    u = ua.lower()
    for needle, name in _BOT_MAP:
        if needle in u:
            return name
    if any(k in u for k in ("bot", "spider", "crawler", "crawl")):
        return "Other bot"
    return None


async def ensure_table() -> None:
    async with engine.begin() as conn:
        for stmt in _DDL:
            await conn.execute(text(stmt))


async def log(*, kind: str, method: str = "", path: str = "", status: int | None = None,
              duration_ms: int | None = None, bot: str | None = None, ip: str = "",
              user_agent: str = "", referer: str = "", detail: str = "") -> None:
    """Best-effort insert. Never raises into the caller."""
    try:
        async with async_session() as session:
            await session.execute(
                text("""
                    INSERT INTO request_log
                        (kind, method, path, status, duration_ms, bot, ip, user_agent, referer, detail)
                    VALUES
                        (:kind, :method, :path, :status, :duration_ms, :bot, :ip, :ua, :referer, :detail)
                """),
                {"kind": kind, "method": method[:10], "path": (path or "")[:1000],
                 "status": status, "duration_ms": duration_ms, "bot": bot,
                 "ip": (ip or "")[:64], "ua": (user_agent or "")[:400],
                 "referer": (referer or "")[:1000], "detail": (detail or "")[:4000]},
            )
            await session.commit()
    except Exception:
        logger.exception("request_telemetry.log failed (path=%s)", path)
