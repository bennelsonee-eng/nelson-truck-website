"""Suggest facet-KEY merge clusters for the admin curator.

Async port of the offline audit (`app/scripts/audit_facet_key_redundancy.py`),
trimmed to what the curator needs: SYNONYM clusters only — groups of keys whose
*names differ* but whose value spaces overlap by numeric signature. Pure
label-variant keys ("Overall Length" / "Overall Length (in.)") are folded
automatically by `attribute_key_merge.normalize_key_name`, so they're excluded
here; the curator never has to act on them.

Keys already in a manual merge group are excluded so confirmed work doesn't
keep resurfacing.

Read-only. Walks leaf categories with direct product_category membership (for a
leaf that equals the subtree the facet resolver walks), reconstructs the
facet-eligible numeric keys per category, flags overlapping pairs, and unions
them into clusters via connected components.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.attribute_canonical import _numeric_signature, _levenshtein
from app.services.attribute_key_merge import normalize_key_name

_CHUNK = 200


def _sig_set(values: dict[str, int]) -> tuple[set[tuple[str, ...]], float]:
    sigs: set[tuple[str, ...]] = set()
    numeric = 0
    for v in values:
        sig = _numeric_signature(v)
        if sig:
            sigs.add(sig)
            numeric += 1
    return sigs, numeric / max(len(values), 1)


def _is_label_variant(a: str, b: str) -> bool:
    na, nb = normalize_key_name(a), normalize_key_name(b)
    if not (na and nb):
        return False
    if na == nb:
        return True
    cap = max(1, max(len(na), len(nb)) // 6)
    return _levenshtein(na, nb) <= cap


def _all_weak(sigs: set[tuple[str, ...]]) -> bool:
    """Every shared signature is a lone small int / year -> coincidental."""
    if not sigs:
        return True
    for sig in sigs:
        if len(sig) != 1:
            return False
        try:
            n = int(sig[0])
        except ValueError:
            return False
        if not (n <= 12 or 1900 <= n <= 2100):
            return False
    return True


async def suggest_key_merges(
    db: AsyncSession,
    *,
    denylist: set[str],
    already_merged: set[str],
    min_overlap: float = 0.40,
    min_products: int = 5,
    min_numeric_frac: float = 0.60,
    max_clusters: int = 60,
) -> list[dict[str, Any]]:
    leaf_rows = (await db.execute(text("""
        SELECT c.id, c.full_path
        FROM category c
        WHERE NOT EXISTS (SELECT 1 FROM category ch WHERE ch.parent_id = c.id)
    """))).all()
    leaf_path = {cid: fp for cid, fp in leaf_rows}
    leaf_ids = list(leaf_path.keys())

    cat_key_vals: dict[int, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(dict))
    for i in range(0, len(leaf_ids), _CHUNK):
        batch = leaf_ids[i:i + _CHUNK]
        rows = (await db.execute(text("""
            SELECT pc.category_id, pa.attribute_key, pa.attribute_value,
                   COUNT(DISTINCT pa.product_id) AS n
            FROM product_category pc
            JOIN product p ON p.id = pc.product_id
            JOIN brand   b ON b.id = p.brand_id
            JOIN product_attribute pa ON pa.product_id = pc.product_id
            WHERE pc.category_id = ANY(:ids)
              AND p.is_hidden = false AND p.is_for_sale = true AND b.is_active = true
              AND pa.attribute_value IS NOT NULL AND pa.attribute_value <> ''
              AND LOWER(pa.attribute_key) <> ALL(:denylist)
              AND pa.attribute_key NOT ILIKE '%% - XA'
              AND pa.attribute_key NOT ILIKE '%% - XB'
              AND pa.attribute_key NOT ILIKE '%% - XC'
            GROUP BY pc.category_id, pa.attribute_key, pa.attribute_value
        """), {"ids": batch, "denylist": list(denylist)})).all()
        for cid, key, val, n in rows:
            if key in already_merged:
                continue
            cat_key_vals[cid][key][val] = n

    # Pairwise SYNONYM detection per category, aggregated.
    pair_hits: dict[tuple[str, str], dict] = {}
    for cid, keys in cat_key_vals.items():
        eligible = {}
        for key, values in keys.items():
            reach = max(values.values()) if values else 0
            if len(values) >= 2 and reach >= min_products:
                sigs, frac = _sig_set(values)
                if len(sigs) >= 2 and frac >= min_numeric_frac:
                    eligible[key] = (sigs, values, reach)
        if len(eligible) < 2:
            continue
        for a, b in combinations(sorted(eligible, key=str.lower), 2):
            sa, va, ra = eligible[a]
            sb, vb, rb = eligible[b]
            inter = sa & sb
            union = sa | sb
            if not union:
                continue
            if len(inter) / len(union) < min_overlap:
                continue
            if _is_label_variant(a, b):     # auto-folded; not the curator's job
                continue
            if _all_weak(inter):            # coincidental years / counts
                continue
            pk = tuple(sorted((a, b), key=str.lower))
            rec = pair_hits.setdefault(pk, {
                "members": set(pk), "categories": set(),
                "reach": {}, "shared": set(),
            })
            rec["categories"].add(leaf_path.get(cid, str(cid)))
            rec["reach"][a] = max(rec["reach"].get(a, 0), ra)
            rec["reach"][b] = max(rec["reach"].get(b, 0), rb)
            for sig in list(inter)[:6]:
                # store one readable raw form per shared signature
                raw = next((v for v in va if _numeric_signature(v) == sig), None)
                if raw:
                    rec["shared"].add(raw)

    if not pair_hits:
        return []

    # Connected components over flagged pairs = clusters.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    reach: dict[str, int] = {}
    cats: dict[str, set] = defaultdict(set)
    shared: dict[str, set] = defaultdict(set)
    for (a, b), rec in pair_hits.items():
        union(a, b)
        for k, v in rec["reach"].items():
            reach[k] = max(reach.get(k, 0), v)

    comps: dict[str, set] = defaultdict(set)
    for (a, b), rec in pair_hits.items():
        root = find(a)
        comps[root] |= rec["members"]
        cats[root] |= rec["categories"]
        shared[root] |= rec["shared"]

    clusters: list[dict[str, Any]] = []
    for root, members in comps.items():
        mem = sorted(members, key=lambda k: (-reach.get(k, 0), k))
        clusters.append({
            "label_guess": mem[0],   # highest-reach member as default label
            "members": [{"key": k, "products": reach.get(k, 0)} for k in mem],
            "categories": sorted(cats[root])[:10],
            "category_count": len(cats[root]),
            "shared_values": sorted(shared[root])[:10],
            "total_reach": sum(reach.get(k, 0) for k in mem),
        })
    clusters.sort(key=lambda c: (c["category_count"], c["total_reach"]), reverse=True)
    return clusters[:max_clusters]
