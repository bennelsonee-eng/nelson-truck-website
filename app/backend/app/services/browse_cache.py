"""Tiny in-process TTL cache for read-only catalog browse + facet responses.

Why this exists
---------------
The catalog browse + category-attributes endpoints recompute the same
filter / count / facet aggregations on every request, even when many shoppers
hit the same popular category back-to-back. There is no Redis on the box (it
also runs the Nelson ERP), so a process-local TTL cache is the pragmatic win:
it collapses repeat loads of the same view to a dict lookup while keeping the
data only seconds stale.

Scope / safety
--------------
Cache ONLY responses that are identical for every viewer:
  * Anonymous catalog browse (user is None) — retail prices come from the
    sentinel price book, same for everyone. Logged-in browse carries
    per-customer tier pricing and MUST NOT be cached here.
  * category-attributes — pure PIES facet aggregation, no pricing at all.

Stock + sentinel-retail can drift within the TTL window; for a browse grid a
few seconds of staleness is acceptable (the PDP / cart remain authoritative).

This is a single-process cache. Under multiple uvicorn workers each worker
keeps its own copy — fine for a TTL this short. It clears on restart.
"""

from __future__ import annotations

import time
from typing import Any, Hashable


# Browse responses include stock + resolved retail, so keep the window short.
BROWSE_CACHE_TTL_SEC = 90
# Attribute facets only change when the PACE/PIES feed is re-ingested, so they
# can live a good deal longer.
ATTRS_CACHE_TTL_SEC = 300
# The full category tree (mega-menu / "Shop by category") is the same for every
# viewer and only changes when categories, their images, or PACE/PIES ingestion
# change — never per-request. Its build is heavy (~2.8s: recursive descendant
# walk + per-category image resolution over the whole catalog), so cache it for
# a good while. A re-ingest or category edit is at most this stale; a deploy
# restart clears it anyway.
TREE_CACHE_TTL_SEC = 900

# Hard cap on entries per cache so a crawler hitting unbounded filter combos
# can't grow the dict without limit. When exceeded we drop the oldest-expiring
# half — crude but bounded and allocation-free in the common (cache-hit) path.
_MAX_ENTRIES = 512


class TTLCache:
    """Minimal time-to-live cache. Not thread-safe in the strict sense, but the
    asyncio event loop is single-threaded so concurrent coroutines never
    interleave mid-statement here."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        # key -> (expires_at_epoch, value)
        self._store: dict[Hashable, tuple[float, Any]] = {}

    def get(self, key: Hashable) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: Hashable, value: Any) -> None:
        if len(self._store) >= _MAX_ENTRIES:
            self._evict()
        self._store[key] = (time.time() + self._ttl, value)

    def _evict(self) -> None:
        # Drop everything already expired first; if still over cap, drop the
        # half that expires soonest.
        now = time.time()
        live = {k: v for k, v in self._store.items() if v[0] > now}
        if len(live) >= _MAX_ENTRIES:
            ordered = sorted(live.items(), key=lambda kv: kv[1][0])
            live = dict(ordered[len(ordered) // 2:])
        self._store = live

    def clear(self) -> None:
        self._store.clear()


# Module-level singletons — import and use directly.
browse_cache = TTLCache(BROWSE_CACHE_TTL_SEC)
attrs_cache = TTLCache(ATTRS_CACHE_TTL_SEC)
tree_cache = TTLCache(TREE_CACHE_TTL_SEC)
