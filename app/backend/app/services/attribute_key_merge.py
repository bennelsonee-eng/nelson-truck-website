"""Facet-KEY merge — group attribute keys that describe the same attribute.

One level up from `attribute_canonical` (which merges VALUES within a single
key), this groups whole KEYS so the catalog rail shows one filter instead of
several for the same thing. Motivating case: Transfer Tanks surfaces "Volume",
"Gallon Capacity", "Liquid Storage Capacity", and "WEB: Box Width/Tank
Capacity" as four separate gallon facets.

Two grouping sources, mirroring the value layer's auto + manual split:

  - AUTO (label-variant): keys whose *names* are identical after stripping
    formatting — "Overall Length" / "Overall Length (in.)" /
    "Overall Length(in)". Deterministic, no storage. See `normalize_key_name`.
  - MANUAL (synonym): curator-confirmed groups where names genuinely differ,
    stored in `attribute_key_alias` (member_key -> group_label). Passed in here
    as a {member_key: group_label} dict.

Once keys are grouped, a group's values are re-bucketed by
`group_value_bucket` so differently-formatted values that share a numeric
signature collapse to one checkbox: "100", "100 Gallon", "100 Gallons" -> one.

Everything here is pure string logic (no DB / no I/O) so it unit-tests cleanly
and `catalog.py` can reuse the exact same bucketing on both the facet-render
and the browse-filter sides — they MUST agree or a click returns nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.services.attribute_canonical import _numeric_signature, auto_canonical

# Unit / formatting tokens stripped when normalizing a key NAME so that
# "Overall Length" and "Overall Length (in.)" collapse to one name. These are
# parenthetical qualifiers and bare unit words — never the substance of a key.
_UNIT_TOKENS = {
    "in", "inch", "inche", "lb", "lbs", "lbf", "oz", "ft", "mm", "cm", "m",
    "gal", "gallon", "qt", "quart", "kg", "g", "ton", "pc", "pcs", "piece",
    "deg", "hp", "psi", "amp", "volt", "v", "w", "watt", "wc", "wd",
}


def normalize_key_name(key: str) -> str:
    """Fold a key name to its label-variant signature: lowercase, drop
    parentheticals + punctuation + unit tokens, depluralize.

    'Overall Length (in.)' / 'Overall Length' -> 'overall length'.
    'Install Time' / 'Installation Time' stay DISTINCT (we only fold pure
    formatting here; genuine synonyms are the curator's job, not this).
    """
    s = re.sub(r"\([^)]*\)", " ", key.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = []
    for t in s.split():
        if t in _UNIT_TOKENS:
            continue
        if t.endswith("s") and len(t) > 3:
            t = t[:-1]
        toks.append(t)
    return " ".join(toks).strip()


def group_value_bucket(value: str) -> str:
    """Bucket key for a value INSIDE a merged group.

    Numeric values bucket on their numeric signature so "100", "100 Gallon",
    and "100 Gallons" all land together ('#100'). Non-numeric values fall back
    to `auto_canonical` (same fold the single-key path already uses), so this
    never over-merges text values.
    """
    sig = _numeric_signature(value)
    if sig:
        return "#" + "|".join(sig)
    return auto_canonical(value).lower()


@dataclass
class KeyGroup:
    label: str               # display label for the merged facet group
    members: list[str]       # every source attribute_key in the group
    is_merged: bool          # True when >1 member (drives the new code path)
    source: str              # 'manual', 'auto', or 'single'


def compute_key_groups(
    key_counts: list[tuple[str, int]],
    manual_map: dict[str, str],
) -> list[KeyGroup]:
    """Group surfaced keys into facet groups, preserving input order of the
    first (highest-priority) member of each group.

    Args:
        key_counts: [(attribute_key, n_products), ...] in priority order
            (most-covered first — the order `category_attributes` already
            computed).
        manual_map: {member_key: group_label} from `attribute_key_alias`.

    Union-find over two relations: same `normalize_key_name` (auto) and same
    `group_label` (manual). Manual label wins the display name; otherwise the
    highest-coverage member's own name is the label.
    """
    keys = [k for k, _ in key_counts]
    count_of = dict(key_counts)
    parent: dict[str, str] = {k: k for k in keys}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Auto: union keys sharing a normalized name.
    by_norm: dict[str, list[str]] = {}
    for k in keys:
        by_norm.setdefault(normalize_key_name(k), []).append(k)
    for group in by_norm.values():
        for k in group[1:]:
            union(group[0], k)

    # Manual: union keys sharing a curator group_label (only among surfaced
    # keys — members absent from this category simply don't appear).
    by_label: dict[str, list[str]] = {}
    for k in keys:
        lbl = manual_map.get(k)
        if lbl:
            by_label.setdefault(lbl, []).append(k)
    for group in by_label.values():
        for k in group[1:]:
            union(group[0], k)

    # Collect components, keeping first-seen (priority) order.
    comps: dict[str, list[str]] = {}
    order: list[str] = []
    for k in keys:
        r = find(k)
        if r not in comps:
            comps[r] = []
            order.append(r)
        comps[r].append(k)

    groups: list[KeyGroup] = []
    for r in order:
        members = comps[r]
        manual_labels = {manual_map[k] for k in members if k in manual_map}
        if manual_labels:
            label = sorted(manual_labels)[0]  # stable if curator was consistent
            source = "manual"
        else:
            # Highest-coverage member's name; tie-break shorter then alpha.
            label = sorted(members,
                           key=lambda k: (-count_of.get(k, 0), len(k), k))[0]
            source = "auto" if len(members) > 1 else "single"
        groups.append(KeyGroup(
            label=label, members=members,
            is_merged=len(members) > 1, source=source,
        ))
    return groups


@dataclass
class MergedValue:
    label: str               # display label (canonicalized representative)
    count: int               # summed product count across the bucket
    uom: str | None
    bucket: str              # group_value_bucket key (for matching)


def merge_values(rows: Iterable[tuple[str, str | None, int]]) -> list[MergedValue]:
    """Union raw (value, uom, count) rows from ALL member keys of a group into
    display buckets, summing counts and choosing the best-formatted label.

    Representative preference within a bucket: a value carrying a unit (letters,
    e.g. "100 Gallons") beats a bare number ("100"); then higher count; then
    shorter. The chosen raw is run through `auto_canonical` for display so it
    matches the look of single-key facet values.
    """
    acc: dict[str, dict] = {}
    for raw, uom, count in rows:
        if raw is None or raw == "":
            continue
        b = group_value_bucket(raw)
        slot = acc.get(b)
        if slot is None:
            slot = acc[b] = {"count": 0, "cands": []}
        slot["count"] += count
        slot["cands"].append((raw, uom, count))

    out: list[MergedValue] = []
    for b, slot in acc.items():
        has_letters = lambda s: bool(re.search(r"[a-zA-Z]", s))
        best = sorted(
            slot["cands"],
            key=lambda c: (has_letters(c[0]), c[2], -len(c[0])),
            reverse=True,
        )[0]
        raw, uom, _ = best
        out.append(MergedValue(
            label=auto_canonical(raw), count=slot["count"], uom=uom, bucket=b,
        ))
    out.sort(key=lambda v: v.count, reverse=True)
    return out
