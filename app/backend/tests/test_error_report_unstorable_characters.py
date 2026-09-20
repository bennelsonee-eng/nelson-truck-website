"""A recorder session must never be lost because of a character in it.

The Nelson ERP lost two reports this way before anyone found the cause. The
first vanished on 2026-08-28: no row, and therefore no alert email -- the alert
fires on create, so a failed insert is completely silent from the reporter's
side. You record a problem, the panel says it was sent in, and nothing exists.

The log had it::

    POST /api/error-reports -> 500
    invalid input syntax for type json
    DETAIL: Unicode low surrogate must follow a high surrogate

The capture had clicked a sidebar link whose label starts with an emoji. The
JSON columns are **jsonb**, which parses what it stores, and PostgreSQL rejects
an unpaired UTF-16 surrogate. The broken half comes from the browser: JavaScript
strings are UTF-16, so a client-side slice() can cut an emoji between its two
surrogates and send the leftover alone.

Both of these sites run the same recorder code against the same column types,
and both sites' nav labels and category names carry emoji -- so a recording that
clicks one could hit it here too. This module is the port of the ERP's guard,
and it is byte-identical in the Nelson and Titan repos on purpose: a `diff` of
the two is the check that the fix did not drift.

Two things are pinned here: what `_scrub` does, and -- because the whole bug
lived in the gap between "looks like valid JSON" and "PostgreSQL accepts it" --
what a real database does with each shape. A test that only asserted the former
would have passed on the payload that lost the report.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.dependencies import ReporterIdentity
from app.routers import error_reports as mod
from app.routers.error_reports import ErrorReportCreate, _jsonb, _scrub, create_error_report

CHART = "\U0001F4CA"           # an intact emoji: ONE codepoint in Python
HIGH = "\ud83d"                # its leading surrogate, alone
LOW = "\udcca"                 # its trailing surrogate, alone
NUL = "\x00"                   # U+0000

TEST_USER = "unstorable-characters-test@example.invalid"

# The router has no ORM model -- it writes raw SQL against a table that is
# created out of band -- so conftest's Base.metadata.create_all does not build
# it. Running the repo's own checked-in DDL is both how we get a table to test
# against and a check that the file still matches what the router expects.
TABLE_SQL = Path(__file__).resolve().parents[2] / "scripts" / "create_error_reports_table.sql"

# Every column create_error_report() writes, and the type it must have for the
# router's scrubbing choices to be the right ones.
WRITTEN_COLUMNS = {
    "title": "text",
    "description": "text",
    "route": "text",
    "severity": "text",
    "status": "text",
    "reported_by_username": "text",
    "browser_info": "text",
    "speech_segments": "jsonb",
    "click_events": "jsonb",
    "pages_visited": "jsonb",
    "dom_state": "jsonb",
    "mic_diagnostics": "jsonb",
}


# ---------------------------------------------------------------- scrubbing --
#
# No database needed for these: they pin the helper's behaviour.

def test_intact_emoji_is_left_alone():
    """The fix must not damage the very characters that triggered it.

    Python holds a real emoji as one codepoint, never as a surrogate pair, so
    stripping the D800-DFFF range cannot touch one that arrived whole.
    """
    assert _scrub(f"{CHART}Dashboard") == f"{CHART}Dashboard"
    assert json.loads(_jsonb([{"text": f"{CHART}Snow Plows"}]))[0]["text"] == f"{CHART}Snow Plows"


@pytest.mark.parametrize("broken", [HIGH, LOW, HIGH + "x", f"a{LOW}b"])
def test_lone_surrogates_are_removed(broken):
    assert not any("\ud800" <= c <= "\udfff" for c in _scrub(broken))


def test_scrub_reaches_nested_values_and_keys():
    """Click events arrive as a list of dicts; the break can be anywhere."""
    payload = [{"text": f"{LOW}Dashboard", "selector": "", "nested": {"a": HIGH}},
               {f"k{HIGH}": [f"{LOW}x", 1, None]}]
    out = _scrub(payload)
    flat = json.dumps(out)
    assert "\\ud8" not in flat.lower() and "\\udc" not in flat.lower()
    assert out[0]["text"] == "Dashboard"
    assert out[1]["k"] == ["x", 1, None]


def test_non_strings_pass_through_untouched():
    assert _scrub({"n": 1, "f": 1.5, "b": True, "z": None}) == \
        {"n": 1, "f": 1.5, "b": True, "z": None}


def test_scrubbed_output_is_utf8_encodable():
    """A lone surrogate cannot be encoded as UTF-8 at all.

    This is why the plain text columns had to be scrubbed too, not only the
    jsonb ones -- and why the failure is a client-side DataError there rather
    than a server-side syntax error.
    """
    with pytest.raises(UnicodeEncodeError):
        f"{LOW}Dashboard".encode("utf-8")
    _scrub(f"{LOW}Dashboard").encode("utf-8")          # must not raise


def test_nul_is_stripped_from_strings_and_nested_values():
    """U+0000 reaches us out of captured DOM text exactly like a half emoji."""
    assert _scrub(f"Dash{NUL}board") == "Dashboard"
    out = _scrub([{"text": f"a{NUL}b", "nested": {f"k{NUL}": f"{NUL}v"}}])
    assert out[0]["text"] == "ab"
    assert out[0]["nested"]["k"] == "v"


@pytest.mark.parametrize("limit", [20, 100, 200, 500])
def test_scrub_truncates_to_the_column_width(limit):
    """Unused on these sites today -- see test_every_written_column_is_unbounded
    -- but pinned so the parameter still works the day a column is narrowed."""
    assert len(_scrub("X" * (limit + 60), limit)) == limit


def test_truncation_happens_after_the_characters_are_removed():
    """Otherwise the cut could leave a value that is still over the limit."""
    assert _scrub(NUL * 10 + "Y" * 10, 10) == "Y" * 10


def test_no_limit_means_no_truncation():
    """Every column this router writes is unbounded; nothing may be shortened."""
    assert len(_scrub("X" * 5000)) == 5000


# ------------------------------------------------------------- the database --

@pytest_asyncio.fixture
async def reports_db():
    """An AsyncSession against the test database, with `error_reports` in place.

    Skips rather than fails when no database is reachable, so the scrubbing
    tests above still run on a box without Postgres -- but the point of this
    module is that they are not enough on their own.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    try:
        import asyncpg
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
        # Multiple statements, so this goes through asyncpg's simple-query path
        # rather than SQLAlchemy's prepared statements. The DDL is idempotent.
        await conn.execute(io.open(TABLE_SQL, encoding="utf-8").read())
        await conn.close()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no reachable database for the round-trip tests: {exc}")

    engine = create_async_engine(url, poolclass=NullPool, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
        await session.rollback()
        await session.execute(
            text("DELETE FROM error_reports WHERE reported_by_username = :u"),
            {"u": TEST_USER},
        )
        await session.commit()
    await engine.dispose()


def _as_json(value):
    """jsonb comes back decoded through the driver's JSON codec on some
    paths and as raw text on others; both are the same stored value."""
    return json.loads(value) if isinstance(value, (str, bytes)) else value


async def _cast(session, value, pgtype):
    """Round-trip one value through a cast, rolling back whatever happens.

    A failed statement poisons the session's transaction, so every one of these
    has to be followed by a rollback before the next.
    """
    try:
        return (await session.execute(
            text(f"SELECT CAST(:v AS {pgtype})"), {"v": value})).scalar()
    finally:
        await session.rollback()


@pytest.mark.asyncio
async def test_postgres_rejects_the_raw_payload_and_accepts_the_scrubbed_one(reports_db):
    """The 2026-08-28 regression itself, against a real database."""
    broken = [{"text": f"{LOW}Dashboard", "selector": "", "url": "/"}]

    with pytest.raises(Exception) as exc:
        await _cast(reports_db, json.dumps(broken), "JSONB")
    assert "invalid input syntax for type json" in str(exc.value).lower()

    stored = await _cast(reports_db, _jsonb(broken), "JSONB")
    assert _as_json(stored)[0]["text"] == "Dashboard"


@pytest.mark.asyncio
async def test_json_would_have_hidden_this_but_jsonb_does_not(reports_db):
    """Documents why the column type is the whole story.

    `json` stores the text as given and never parses it, so the very payload
    that breaks jsonb sails through json -- and so does json.dumps/json.loads in
    Python. If these columns are ever migrated, the guard here is what keeps the
    recorder alive.
    """
    raw = json.dumps([{"text": f"{LOW}Dashboard"}])
    assert json.loads(raw)[0]["text"] == f"{LOW}Dashboard"     # Python: fine
    await _cast(reports_db, raw, "JSON")                       # lenient: accepted
    with pytest.raises(Exception):
        await _cast(reports_db, raw, "JSONB")                  # strict: rejected


@pytest.mark.asyncio
async def test_intact_emoji_survives_a_round_trip_through_jsonb(reports_db):
    stored = await _cast(reports_db, _jsonb([{"text": f"{CHART}Dashboard"}]), "JSONB")
    assert _as_json(stored)[0]["text"] == f"{CHART}Dashboard"


@pytest.mark.asyncio
async def test_postgres_rejects_nul_in_jsonb_and_accepts_it_scrubbed(reports_db):
    """PostgreSQL refuses U+0000 in jsonb: 'unsupported Unicode escape sequence'."""
    broken = [{"text": f"Dash{NUL}board"}]

    with pytest.raises(Exception) as exc:
        await _cast(reports_db, json.dumps(broken), "JSONB")
    assert "unsupported unicode escape sequence" in str(exc.value).lower()

    stored = await _cast(reports_db, _jsonb(broken), "JSONB")
    assert _as_json(stored)[0]["text"] == "Dashboard"


@pytest.mark.asyncio
async def test_postgres_rejects_nul_in_a_text_column_too(reports_db):
    """Not a jsonb quirk -- it breaks title/description/route the same way."""
    with pytest.raises(Exception) as exc:
        await _cast(reports_db, f"Dash{NUL}board", "TEXT")
    assert "0x00" in str(exc.value) or "invalid byte sequence" in str(exc.value).lower()
    assert await _cast(reports_db, _scrub(f"Dash{NUL}board"), "TEXT") == "Dashboard"


@pytest.mark.asyncio
async def test_postgres_rejects_a_lone_surrogate_in_a_text_column_too(reports_db):
    """This one never reaches the server: asyncpg cannot encode it as UTF-8.

    A different error from the jsonb case, the same lost report -- which is why
    the text columns are scrubbed rather than trusted.
    """
    with pytest.raises(Exception) as exc:
        await _cast(reports_db, f"{LOW}Dashboard", "TEXT")
    assert "utf-8" in str(exc.value).lower() and "encode" in str(exc.value).lower()
    assert await _cast(reports_db, _scrub(f"{LOW}Dashboard"), "TEXT") == "Dashboard"


@pytest.mark.asyncio
async def test_every_written_column_is_unbounded(reports_db):
    """Why `_scrub` is called without a limit anywhere in this router.

    The ERP's title(200)/route(500)/browser_info(500) are bounded varchars, and
    an over-long value 500'd its POST and took the whole session with it. Here
    they are unbounded `text`, so truncating would only throw away data the
    database was willing to keep. If anyone ever narrows one, this fails and the
    fix is to pass that width to _scrub().
    """
    rows = (await reports_db.execute(text("""
        SELECT column_name, data_type, character_maximum_length
        FROM information_schema.columns
        WHERE table_name = 'error_reports'
    """))).fetchall()
    found = {r[0]: (r[1], r[2]) for r in rows}

    for column, expected_type in WRITTEN_COLUMNS.items():
        assert column in found, f"{column} is missing from error_reports"
        data_type, width = found[column]
        assert data_type == expected_type, f"{column} is {data_type}, expected {expected_type}"
        assert width is None, (
            f"{column} is now bounded at {width} -- pass that width to _scrub() "
            "in create_error_report, or an over-long value will 500 the POST "
            "and lose the report"
        )


# ------------------------------------------------------- the endpoint itself --

def _payload(**over):
    """The shape the panel actually posts, with the 2026-08-28 break in it."""
    body = dict(
        title="",
        description="",
        route="/plows",
        severity="high",
        # A half emoji in captured click text, an intact one beside it, and a
        # NUL in the DOM snapshot: every shape we know of, in one report.
        speech_segments=[{"text": f"the {LOW}filter is broken", "timestamp_ms": 10, "confidence": 0.9}],
        click_events=[{"tag": "A", "text": f"{LOW}Dashboard", "selector": "nav a",
                       "url": "/", "timestamp_ms": 5},
                      {"tag": "A", "text": f"{CHART}Snow Plows", "selector": "nav a",
                       "url": "/plows", "timestamp_ms": 9}],
        pages_visited=["/", "/plows"],
        dom_state={"title": f"Titan{NUL} Truck", "viewport": {"w": 1280, "h": 900}},
        mic_diagnostics={"secure_context": True, "errors": [f"no-speech{HIGH}"]},
        browser_info=f"Mozilla/5.0 {LOW}",
    )
    body.update(over)
    return ErrorReportCreate(**body)


async def _row(session, report_id):
    return (await session.execute(
        text("SELECT * FROM error_reports WHERE id = :id"), {"id": report_id}
    )).mappings().fetchone()


@pytest.mark.asyncio
async def test_the_report_that_used_to_vanish_now_saves(reports_db):
    """End to end through the handler: POST the payload that lost a report."""
    out = await create_error_report(
        body=_payload(),
        background=BackgroundTasks(),
        db=reports_db,
        reporter=ReporterIdentity(user_id=None, username=TEST_USER, is_admin=False),
    )
    assert isinstance(out["id"], int)

    row = await _row(reports_db, out["id"])
    clicks = _as_json(row["click_events"])
    assert clicks[0]["text"] == "Dashboard"              # broken half gone
    assert clicks[1]["text"] == f"{CHART}Snow Plows"     # whole emoji kept
    assert _as_json(row["dom_state"])["title"] == "Titan Truck"   # the NUL is gone
    assert "the filter is broken" in row["description"]  # what they said, intact
    assert row["route"] == "/plows"
    assert row["browser_info"] == "Mozilla/5.0 "
    # The 200 body is JSON-encoded on the way out; a surrogate left in the title
    # would fail that encoding and 500 a report that was already committed.
    json.dumps(out).encode("utf-8")


@pytest.mark.asyncio
async def test_a_blob_we_cannot_store_still_saves_what_the_person_said(reports_db, monkeypatch):
    """The last-ditch retry, for the shape we have not thought of yet.

    The scrub covers what we know breaks, but the capture blobs come from the
    browser and we cannot enumerate every future one. Simulated here by taking
    the scrub off the jsonb path: the first insert fails, and the words -- the
    only part of a report that cannot be reconstructed -- still land.
    """
    monkeypatch.setattr(mod, "_jsonb", json.dumps)

    out = await create_error_report(
        body=_payload(description="the price sheet PDF is the wrong year"),
        background=BackgroundTasks(),
        db=reports_db,
        reporter=ReporterIdentity(user_id=None, username=TEST_USER, is_admin=False),
    )

    row = await _row(reports_db, out["id"])
    assert "the price sheet PDF is the wrong year" in row["description"]
    assert "Capture detail was dropped" in row["description"]
    assert _as_json(row["click_events"]) == []
