"""Parse a Year / Make / Model out of a free-text search query.

The storefront search bar lets a shopper type a vehicle plus a product term
in one box, e.g. "2026 ford f-150 tonneau cover".  Without this, the whole
string is matched as free text, so the vehicle words are weak tokens and
products that fit OTHER trucks (a Ram tonneau, a Silverado tonneau) rank right
alongside the F-150 ones — error report #21.

This module recognises a Year/Make/Model phrase inside the query, resolves it
to a VCDB ``base_vehicle_id`` (the same fitment key the YMM picker produces),
and hands back the *residual* keywords ("tonneau cover").  The caller then
filters search results to products that fit that vehicle (or are universal),
giving fitment-correct results while keeping full keyword relevance.

Design notes:
- Make detection is dictionary-driven from VCDB ``vcdb_make`` (cached
  process-wide; makes are effectively static).  A small alias table covers the
  ways customers actually type makes ("chevy", "vw") plus the merged
  Dodge / RAM brand (RAM split from Dodge in VCDB but shoppers still type
  either) — kept in sync with ``MERGED_MAKES`` in routers/ymm.py.
- Model detection is scoped to the matched make's VCDB make_ids, so "F-150"
  only competes against Ford models.  A model matches only when a contiguous
  run of query tokens equals a model name after normalisation
  ("f-150" / "f150" / "f 150" all -> "f150"), so "tonneau"/"cover" can never be
  mistaken for a model.
- A make is REQUIRED (model alone is too ambiguous — "1500" fits several
  makes).  A year is optional: with a year we resolve the nearest produced
  year for that model (right generation); without one we take the newest.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import VcdbBaseVehicle, VcdbMake, VcdbModel

# Plausible model-year window. Upper bound is "next year" so a freshly released
# model year resolves before Jan 1.
_MIN_YEAR = 1950
_MAX_YEAR = datetime.date.today().year + 1

# Common ways shoppers type a make that don't equal the VCDB name. Maps a
# normalised alias -> the set of VCDB make NAMES it stands for. Multi-name sets
# are "merged" makes (Dodge / RAM) — keep in sync with MERGED_MAKES in
# routers/ymm.py.
_MAKE_ALIASES: dict[str, set[str]] = {
    "chevy": {"Chevrolet"},
    "chev": {"Chevrolet"},
    "vw": {"Volkswagen"},
    "mercedes": {"Mercedes-Benz"},
    "benz": {"Mercedes-Benz"},
    "ram": {"Dodge", "Ram"},
    "dodge": {"Dodge", "Ram"},
}

# Module-wide cache of {normalised make name/alias -> sorted list of make_ids}.
# Makes are static for the life of the process; cleared only on restart.
_make_index: dict[str, list[int]] | None = None

# Module-wide model index, built once. Two maps keyed by the concatenation of
# a model name's normalised WORDS:
#   full_map[concat]   -> set of (model_id, make_id) whose FULL name == concat
#   prefix_map[concat] -> set of (model_id, make_id) for which concat is a
#                         leading word-prefix ("f250" -> "F-250 Super Duty")
# Word-prefix (not substring) matching lets "f250" reach "F-250 Super Duty"
# while never letting "tonneau" sneak into a model.
_model_index: tuple[dict[str, set], dict[str, set]] | None = None


def _norm(s: str) -> str:
    """Collapse to lowercase alphanumerics so 'F-150', 'f150', 'f 150' unify."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


async def _load_make_index(db: AsyncSession) -> dict[str, list[int]]:
    global _make_index
    if _make_index is not None:
        return _make_index
    rows = (await db.execute(
        select(VcdbMake.id, VcdbMake.name).where(VcdbMake.name != "UNKNOWN")
    )).all()
    name_to_ids: dict[str, set[int]] = {}
    for mid, name in rows:
        name_to_ids.setdefault(_norm(name), set()).add(mid)
    # Fold in aliases (resolve each alias's member NAMES to ids).
    by_name = {_norm(name): mid for mid, name in rows}
    for alias, member_names in _MAKE_ALIASES.items():
        ids = {by_name[_norm(n)] for n in member_names if _norm(n) in by_name}
        if ids:
            name_to_ids.setdefault(alias, set()).update(ids)
    _make_index = {k: sorted(v) for k, v in name_to_ids.items()}
    return _make_index


async def _load_model_index(db: AsyncSession):
    """Build the word-prefix model index (cached process-wide)."""
    global _model_index
    if _model_index is not None:
        return _model_index
    rows = (await db.execute(
        select(VcdbModel.id, VcdbModel.name, VcdbBaseVehicle.make_id)
        .join(VcdbBaseVehicle, VcdbBaseVehicle.model_id == VcdbModel.id)
        .where(VcdbModel.name != "UNKNOWN")
        .distinct()
    )).all()
    full_map: dict[str, set] = {}
    prefix_map: dict[str, set] = {}
    for mid, name, make_id in rows:
        if make_id is None:
            continue
        words = [_norm(w) for w in name.split() if _norm(w)]
        if not words:
            continue
        full_map.setdefault("".join(words), set()).add((mid, make_id))
        acc = ""
        for w in words:
            acc += w
            prefix_map.setdefault(acc, set()).add((mid, make_id))
    _model_index = (full_map, prefix_map)
    return _model_index


async def parse_vehicle_from_query(
    db: AsyncSession, q: str | None
) -> dict[str, Any] | None:
    """Detect a Year/Make/Model in ``q`` and resolve it to a base_vehicle_id.

    Returns ``None`` when no make+model can be confidently identified.  On a
    hit returns::

        {
            "base_vehicle_id": int,
            "year": int,          # the resolved (produced) year
            "label": str,         # "2026 Ford F-150"
            "residual_q": str,    # query minus the vehicle words ("tonneau cover")
        }
    """
    if not q or not q.strip():
        return None
    raw_tokens = q.split()
    # Per-token normalised form, parallel to raw_tokens; None for empties.
    norm_tokens = [_norm(t) for t in raw_tokens]
    # consumed[i] marks tokens claimed by year/make/model so we can build the
    # residual query from what's left.
    consumed = [False] * len(raw_tokens)

    make_idx = await _load_make_index(db)

    # --- Year: first standalone 4-digit token in range. ----------------------
    year: int | None = None
    for i, tok in enumerate(raw_tokens):
        if re.fullmatch(r"\d{4}", tok):
            yv = int(tok)
            if _MIN_YEAR <= yv <= _MAX_YEAR:
                year = yv
                consumed[i] = True
                break

    # --- Make: longest 2- then 1-token window matching a known make. ---------
    make_ids: list[int] | None = None
    make_span: tuple[int, int] | None = None  # [start, end) of consumed make tokens
    n = len(raw_tokens)
    for width in (2, 1):
        for i in range(n - width + 1):
            if any(consumed[i:i + width]):
                continue
            key = "".join(norm_tokens[i:i + width])
            if key and key in make_idx:
                make_ids = make_idx[key]
                make_span = (i, i + width)
                break
        if make_ids is not None:
            break
    if make_span is not None:
        for j in range(*make_span):
            consumed[j] = True

    # A make in the text is the strong signal. With NO make we only attempt a
    # model-only resolution when a YEAR is present (so ordinary search words
    # like "cover" can't be mistaken for a model), and the model must point at
    # a single make.
    if make_ids is None and year is None:
        return None

    full_map, prefix_map = await _load_model_index(db)

    # --- Model: longest unconsumed token run matching model word(s). ----------
    # For each run, collect EXACT full-name matches and word-PREFIX matches
    # ("f250" -> "F-250 Super Duty"). Resolution below uses the union (so a
    # dead exact like the legacy "F-250" doesn't shadow the live Super Duty),
    # with exact names preferred as a tie-break.
    best_run: tuple[int, int] | None = None
    best_exact: set = set()
    best_prefix: set = set()
    for start in range(n):
        if consumed[start]:
            continue
        acc = ""
        for end in range(start, n):
            if consumed[end]:
                break
            acc += norm_tokens[end]
            ex = full_map.get(acc, set())
            pf = prefix_map.get(acc, set())
            if not ex and not pf:
                continue
            run_len = end - start + 1
            if best_run is None or run_len > (best_run[1] - best_run[0]):
                best_run, best_exact, best_prefix = (start, end + 1), ex, pf
    if best_run is None:
        return None

    # Candidate (model_id, make_id) pairs for the matched run.
    cands = set(best_exact) | set(best_prefix)
    if make_ids is not None:
        mk_set = set(make_ids)
        cands = {(mid, mk) for (mid, mk) in cands if mk in mk_set}
        exact_models = {mid for (mid, mk) in best_exact if mk in mk_set}
    else:
        exact_models = {mid for (mid, mk) in best_exact}
    if not cands:
        return None
    cand_make_ids = {mk for (_, mk) in cands}
    cand_model_ids = {mid for (mid, _) in cands}
    # Ambiguity guard: a model-only / no-exact prefix that fans out to several
    # distinct models (e.g. "silverado" -> 1500/2500/3500) can't be pinned to
    # one truck — bail and let plain text search handle it.
    if not exact_models and len(cand_model_ids) > 1:
        return None
    # A model with no make context must resolve to exactly one make.
    if make_ids is None and len(cand_make_ids) != 1:
        return None
    for j in range(*best_run):
        consumed[j] = True

    # --- Resolve to a concrete base_vehicle_id. ------------------------------
    bv_rows = (await db.execute(
        select(VcdbBaseVehicle.id, VcdbBaseVehicle.year, VcdbBaseVehicle.model_id,
               VcdbMake.name, VcdbModel.name)
        .join(VcdbMake, VcdbMake.id == VcdbBaseVehicle.make_id)
        .join(VcdbModel, VcdbModel.id == VcdbBaseVehicle.model_id)
        .where(VcdbBaseVehicle.make_id.in_(cand_make_ids),
               VcdbBaseVehicle.model_id.in_(cand_model_ids))
    )).all()
    if not bv_rows:
        return None

    # Pick: when a year is given it DOMINATES — nearest produced year wins so a
    # legacy "F-250" (exact name, but ended ~1999) can't beat "F-250 Super Duty"
    # for a 2023 query; exact-name only breaks a year tie (F-150 over F-150
    # Lightning at the same year). With no year, prefer exact name then newest.
    def _key(r):
        is_exact = r[2] in exact_models
        if year is not None:
            return (-abs(r[1] - year), is_exact, r[1])
        return (is_exact, r[1])
    chosen = max(bv_rows, key=_key)

    residual = " ".join(t for t, c in zip(raw_tokens, consumed) if not c).strip()
    return {
        "base_vehicle_id": chosen[0],
        "year": chosen[1],
        "label": f"{chosen[1]} {chosen[3]} {chosen[4]}",
        "residual_q": residual,
    }
