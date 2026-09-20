"""Shared pytest fixtures.

We run integration tests against a dedicated `nelson_web_test` database
(sibling of the dev `nelson_web` database), on the native Postgres on port 5432.
Schema is applied once per session via ``Base.metadata.create_all`` — fast
enough for the suite size and avoids dragging in alembic.

This was `titan_test` on :5433 until 2026-09-20 — inherited verbatim when this
site was cloned from Titan, and never corrected. :5433 is a docker Postgres that
no longer runs, so EVERY database test in this repo skipped or errored rather
than running, silently, for as long as the clone has existed. Titan itself moved
off that container on 2026-08-06 for the same reason; this is that move, applied
here. Pointing at Titan's catalog was wrong on its own terms too: these are
different sites with different schemas.

Each test gets a fresh AsyncSession; tests are responsible for cleaning up
their own seed data (we don't run inside a transaction-rollback wrapper because
many of the routers commit explicitly).
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Force the test DB URL BEFORE app.config is imported anywhere (Settings caches
# via lru_cache).  This protects accidental dev-DB writes from a stray test.
TEST_DB_URL = os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:nelson2026@localhost:5432/nelson_web_test",
)
# Background tasks (FACS heartbeat, etc.) need a long-lived event loop and a
# real DB they can poll — neither is appropriate during unit tests.
os.environ.setdefault("DISABLE_BACKGROUND_TASKS", "1")

from app.models import Base  # noqa: E402  (must come after env mutation)


_SCHEMA_INITIALIZED = False


async def _ensure_schema():
    """Idempotent: drop + create the test DB schema once per test session.

    Uses a one-shot engine that's disposed immediately so we don't accidentally
    keep connections across event loops.
    """
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED:
        return
    if "nelson_web_test" not in TEST_DB_URL:
        raise RuntimeError(
            f"Refusing to run tests against non-test DB: {TEST_DB_URL!r}"
        )
    engine = create_async_engine(TEST_DB_URL, echo=False, future=True, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    _SCHEMA_INITIALIZED = True


@pytest_asyncio.fixture
async def test_engine():
    """Function-scoped async engine bound to titan_test (NullPool — no
    cross-event-loop connection reuse).

    Schema is created once per session via ``_ensure_schema``; each engine
    here is a fresh, disposable connection factory.
    """
    await _ensure_schema()
    engine = create_async_engine(TEST_DB_URL, echo=False, future=True, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(test_engine) -> AsyncIterator[AsyncSession]:
    """Per-test AsyncSession.  Caller is responsible for cleanup."""
    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session


@pytest_asyncio.fixture
async def clean_db(test_engine) -> AsyncIterator[AsyncSession]:
    """Same as `db`, but TRUNCATEs every table on entry for full isolation."""
    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        # Wipe all tables in dependency-safe order (CASCADE handles FKs)
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
        await session.commit()
        yield session
