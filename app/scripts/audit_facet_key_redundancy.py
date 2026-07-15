"""Size the redundant-facet-key problem before we build any merge UI.

Two PIES attribute keys are *redundant* when they describe the same physical
measurement under different names/formats — e.g. "Volume" (values "100 Gallon",
"55 Gallon") and "Gallon Capacity" (values "100", "55"). On the catalog browse
rail they render as two separate filter groups even though they're the same
thing.

This script is READ-ONLY. It walks every leaf category, reconstructs the facet
keys that `/category-attributes` would surface there, and flags key-pairs whose
*value spaces overlap* — using the same numeric-signature gate the value-level
clusterer already uses (`_numeric_signature`). The point is to answer one
question: is this a 3-pair problem or a 300-pair problem?

Scoping note: we use LEAF categories with DIRECT product_category membership.
For a leaf, that equals the subtree the real facet resolver walks, so the
sample matches real browse destinations (Transfer Tanks, etc.) without the cost
of a subtree query per node. Redundant pairs that only surface at higher
roll-up nodes are not counted — stated again in the report.

Usage:
    python app/scripts/audit_facet_key_redundancy.py
    python app/scripts/audit_facet_key_redundancy.py --min-overlap 0.5
    python app/scripts/audit_facet_key_redundancy.py --min-products 8
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.services.attribute_canonical import (  # noqa: E402
    _numeric_signature, _levenshtein,
)

import re as _re

# Unit tokens stripped when normalizing a key NAME, so "Overall Length" and
# "Overall Length (in.)" collapse to the same normalized name.
_UNIT_TOKENS = {
    "in", "inch", "inche", "lb", "lbs", "lbf", "oz", "ft", "mm", "cm", "m",
    "gal", "gallon", "qt", "quart", "kg", "g", "ton", "pc", "pcs", "piece",
    "deg", "hp", "psi", "amp", "volt", "v", "w", "watt", "wc", "wd",
}


def _norm_key_name(k: str) -> str:
    """Lowercase, drop parentheticals + punctuation + unit tokens, depluralize.
    'Overall Length (in.)' / 'Overall Length' → 'overall length';
    'Install Time' / 'Installation Time' stay distinct strings but near in
    edit-distance."""
    s = _re.sub(r"\([^)]*\)", " ", k.lower())
    s = _re.sub(r"[^a-z0-9]+", " ", s)
    toks = []
    for t in s.split():
        if t in _UNIT_TOKENS:
            continue
        if t.endswith("s") and len(t) > 3:
            t = t[:-1]
        toks.append(t)
    return " ".join(toks).strip()


def _classify(a: str, b: str, shared_sigs: set[tuple[str, ...]]) -> str:
    """LABEL_VARIANT  — same attribute, name differs only by format → safe auto-merge.
    SYNONYM_CANDIDATE — names differ, values overlap → needs a human.
    LIKELY_FALSE      — overlap is only coincidental small ints / years."""
    na, nb = _norm_key_name(a), _norm_key_name(b)
    if na and nb:
        if na == nb:
            return "LABEL_VARIANT"
        cap = max(1, max(len(na), len(nb)) // 6)
        if _levenshtein(na, nb) <= cap:
            return "LABEL_VARIANT"

    # Names genuinely differ. If every shared signature is a lone integer that
    # is either year-like (1900-2100) or a small count (≤12), the overlap is
    # probably coincidental (quantities, model years), not the same measurement.
    def _weak(sig: tuple[str, ...]) -> bool:
        if len(sig) != 1:
            return False
        try:
            n = int(sig[0])
        except ValueError:
            return False
        return n <= 12 or 1900 <= n <= 2100
    if shared_sigs and all(_weak(s) for s in shared_sigs):
        return "LIKELY_FALSE"
    return "SYNONYM_CANDIDATE"


# Keep in lock-step with catalog._ATTR_DENYLIST — keys that never surface as
# facets shouldn't be considered for redundancy either.
ATTR_DENYLIST = {
    "california proposition 65", "carb compliant", "hazardous material",
    "prop 65 warning", "tariff 301 - xa", "tariff 301", "country of manufacture",
    "harmonized tariff code", "subcategory", "category", "asin", "upc", "ean",
    "gtin", "item number", "mfr part number", "manufacturer part number",
    "oem part number", "part number", "part terminology id", "part type", "sku",
    "title", "brand", "manufacturer", "warranty", "country of origin",
    "description",
}

CHUNK = 200  # leaf category ids per query batch


def _sig_set(values: dict[str, int]) -> tuple[set[tuple[str, ...]], float]:
    """Return (set of numeric signatures over the distinct values, numeric
    fraction). A value with no number contributes nothing to the set; the
    fraction tells us whether the key is a numeric attribute at all."""
    sigs: set[tuple[str, ...]] = set()
    numeric = 0
    for v in values:
        sig = _numeric_signature(v)
        if sig:
            sigs.add(sig)
            numeric += 1
    frac = numeric / max(len(values), 1)
    return sigs, frac


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-overlap", type=float, default=0.40,
                    help="min Jaccard of value-signature sets to flag a pair")
    ap.add_argument("--min-products", type=int, default=5,
                    help="a key must reach this many products in a category to "
                         "count as a facet there")
    ap.add_argument("--min-numeric-frac", type=float, default=0.60,
                    help="fraction of a key's values that must be numeric for "
                         "the signature-overlap test to apply")
    ap.add_argument("--out", default=str(REPO / "app" / "scripts" / "out"
                                         / "facet_key_redundancy.md"))
    args = ap.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # Leaf categories = nodes that are no one's parent.
        leaf_rows = (await db.execute(text("""
            SELECT c.id, c.full_path
            FROM category c
            WHERE NOT EXISTS (SELECT 1 FROM category ch WHERE ch.parent_id = c.id)
        """))).all()
        leaf_path = {cid: fp for cid, fp in leaf_rows}
        leaf_ids = list(leaf_path.keys())

        # (category_id -> key -> {value: n_products}) for facet-eligible rows.
        cat_key_vals: dict[int, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(dict))

        for i in range(0, len(leaf_ids), CHUNK):
            batch = leaf_ids[i:i + CHUNK]
            rows = (await db.execute(text("""
                SELECT pc.category_id,
                       pa.attribute_key,
                       pa.attribute_value,
                       COUNT(DISTINCT pa.product_id) AS n
                FROM product_category pc
                JOIN product p   ON p.id = pc.product_id
                JOIN brand   b   ON b.id = p.brand_id
                JOIN product_attribute pa ON pa.product_id = pc.product_id
                WHERE pc.category_id = ANY(:ids)
                  AND p.is_hidden = false
                  AND p.is_for_sale = true
                  AND b.is_active = true
                  AND pa.attribute_value IS NOT NULL
                  AND pa.attribute_value <> ''
                  AND LOWER(pa.attribute_key) <> ALL(:denylist)
                  AND pa.attribute_key NOT ILIKE '%% - XA'
                  AND pa.attribute_key NOT ILIKE '%% - XB'
                  AND pa.attribute_key NOT ILIKE '%% - XC'
                GROUP BY pc.category_id, pa.attribute_key, pa.attribute_value
            """), {"ids": batch, "denylist": list(ATTR_DENYLIST)})).all()
            for cid, key, val, n in rows:
                cat_key_vals[cid][key][val] = n

    await engine.dispose()

    # Per category, pick facet-eligible keys, then pairwise-compare signatures.
    # pair key = (lower(a), lower(b)) sorted; aggregate impact across categories.
    pair_hits: dict[tuple[str, str], dict] = {}
    cats_scanned = 0

    for cid, keys in cat_key_vals.items():
        eligible = {}
        for key, values in keys.items():
            reach = max(values.values()) if values else 0
            # Mirror the real gate: ≥2 distinct values, present on enough
            # products, not an identifier (≤70% unique handled loosely here).
            if len(values) >= 2 and reach >= args.min_products:
                sigs, frac = _sig_set(values)
                if len(sigs) >= 2 and frac >= args.min_numeric_frac:
                    eligible[key] = (sigs, values, reach)
        if len(eligible) < 2:
            continue
        cats_scanned += 1

        for a, b in combinations(sorted(eligible, key=str.lower), 2):
            sa, va, ra = eligible[a]
            sb, vb, rb = eligible[b]
            inter = sa & sb
            union = sa | sb
            if not union:
                continue
            jacc = len(inter) / len(union)
            contain = len(inter) / min(len(sa), len(sb))
            if jacc < args.min_overlap:
                continue

            pk = tuple(sorted((a, b), key=str.lower))
            rec = pair_hits.setdefault(pk, {
                "keys": pk, "categories": [], "reach": 0,
                "jacc_sum": 0.0, "contain_max": 0.0, "samples": {},
                "shared_sigs": set(),
            })
            rec["categories"].append(leaf_path.get(cid, str(cid)))
            rec["reach"] = max(rec["reach"], ra + rb)
            rec["jacc_sum"] += jacc
            rec["contain_max"] = max(rec["contain_max"], contain)
            rec["shared_sigs"] |= inter
            if not rec["samples"]:
                # Show a couple of overlapping signatures with their raw forms.
                shared = list(inter)[:4]
                ra_by_sig = {_numeric_signature(v): v for v in va}
                rb_by_sig = {_numeric_signature(v): v for v in vb}
                rec["samples"] = {
                    " / ".join(sig): (ra_by_sig.get(sig, "?"), rb_by_sig.get(sig, "?"))
                    for sig in shared
                }

    # Classify every pair.
    for r in pair_hits.values():
        a, b = r["keys"]
        r["klass"] = _classify(a, b, r["shared_sigs"])

    pairs = sorted(pair_hits.values(),
                   key=lambda r: (len(r["categories"]), r["reach"]), reverse=True)
    by_class = {k: [r for r in pairs if r["klass"] == k]
                for k in ("LABEL_VARIANT", "SYNONYM_CANDIDATE", "LIKELY_FALSE")}

    # Connected components over the REAL edges (label-variant + synonym, NOT
    # the coincidental ones). Each component = one candidate merge group, so
    # the towing-weight family collapses from ~30 pairwise rows to 1 cluster.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    real_pairs = by_class["LABEL_VARIANT"] + by_class["SYNONYM_CANDIDATE"]
    for r in real_pairs:
        a, b = r["keys"]
        union(a, b)
    comps: dict[str, list[str]] = defaultdict(list)
    seen_keys = {k for r in real_pairs for k in r["keys"]}
    for k in seen_keys:
        comps[find(k)].append(k)
    clusters = sorted(comps.values(), key=len, reverse=True)

    # ---- Report -----------------------------------------------------------
    lines: list[str] = []
    w = lines.append
    w("# Redundant facet-key audit\n")
    affected = sorted({c for r in real_pairs for c in r["categories"]})
    w(f"- Leaf categories with >=2 facet-eligible numeric keys: **{cats_scanned}**")
    w(f"- Raw pairs above overlap threshold: **{len(pairs)}**")
    w(f"  - LABEL_VARIANT (safe auto-merge, name differs only by format): "
      f"**{len(by_class['LABEL_VARIANT'])}**")
    w(f"  - SYNONYM_CANDIDATE (needs curator confirm): "
      f"**{len(by_class['SYNONYM_CANDIDATE'])}**")
    w(f"  - LIKELY_FALSE (coincidental small ints / years, ignore): "
      f"**{len(by_class['LIKELY_FALSE'])}**")
    w(f"- **Merge clusters (connected components of real pairs): {len(clusters)}**")
    w(f"- Distinct categories affected: **{len(affected)}**")
    w(f"- Thresholds: jaccard >= {args.min_overlap}, "
      f"min-products >= {args.min_products}, numeric-frac >= {args.min_numeric_frac}")
    w("- Scope: leaf categories only (direct membership). Roll-up-node-only "
      "redundancies are not counted.\n")

    w("## Merge clusters (the real sizing)\n")
    for comp in clusters:
        comp_sorted = sorted(comp, key=str.lower)
        # Is the whole cluster label-variants, or does it contain a synonym edge?
        edge_classes = {r["klass"] for r in real_pairs
                        if r["keys"][0] in comp and r["keys"][1] in comp}
        tag = "SYNONYM" if "SYNONYM_CANDIDATE" in edge_classes else "label-variant"
        w(f"- **[{tag}]** " + "  ·  ".join(f"`{k}`" for k in comp_sorted))
    w("")

    def _dump(title: str, rows: list[dict]) -> None:
        w(f"## {title}  ({len(rows)})\n")
        if not rows:
            w("_none_\n")
            return
        for r in rows:
            a, b = r["keys"]
            n_cat = len(r["categories"])
            mean_j = r["jacc_sum"] / n_cat
            w(f"### `{a}`  vs  `{b}`")
            w(f"- categories: **{n_cat}**  ·  peak reach: **{r['reach']}**  "
              f"·  mean jaccard: {mean_j:.2f}  ·  max containment: {r['contain_max']:.2f}")
            if r["samples"]:
                w("- shared values (sig -> forms):")
                for sig, (fa, fb) in r["samples"].items():
                    w(f"    - `{sig}`  ->  \"{fa}\"  /  \"{fb}\"")
            show = r["categories"][:8]
            more = n_cat - len(show)
            w("- in: " + "; ".join(show) + (f"  (+{more} more)" if more > 0 else ""))
            w("")

    _dump("SYNONYM_CANDIDATE - needs curator", by_class["SYNONYM_CANDIDATE"])
    _dump("LABEL_VARIANT - safe auto-merge", by_class["LABEL_VARIANT"])
    _dump("LIKELY_FALSE - probably coincidental", by_class["LIKELY_FALSE"])

    report = "\n".join(lines)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    # Console summary.
    print(f"\nLeaf cats scanned: {cats_scanned} | raw pairs: {len(pairs)}")
    print(f"  LABEL_VARIANT     : {len(by_class['LABEL_VARIANT'])}")
    print(f"  SYNONYM_CANDIDATE : {len(by_class['SYNONYM_CANDIDATE'])}")
    print(f"  LIKELY_FALSE      : {len(by_class['LIKELY_FALSE'])}")
    print(f"  merge clusters    : {len(clusters)}  | categories affected: {len(affected)}")
    print(f"Full report -> {out}\n")
    print("Merge clusters:")
    for comp in clusters:
        comp_sorted = sorted(comp, key=str.lower)
        edge_classes = {r["klass"] for r in real_pairs
                        if r["keys"][0] in comp and r["keys"][1] in comp}
        tag = "SYN " if "SYNONYM_CANDIDATE" in edge_classes else "lbl "
        print(f"  [{tag}] " + "  |  ".join(comp_sorted))


if __name__ == "__main__":
    asyncio.run(main())
