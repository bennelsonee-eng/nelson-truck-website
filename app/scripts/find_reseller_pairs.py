"""S1 reseller-pair scorer.

For each product, compute a small "match signature" (primary_category_id,
part_terminology_id, fitment_vehicle_hash). Products with the same
signature but different brands become candidate pairs. Score each
candidate on PIES attribute overlap + description text overlap and
insert the top-scoring pairs as pending ProductMatch rows for an admin
to review.

Run from app/ with the backend venv:
    cd /home/titan/titan-truck-website/app
    backend/.venv/bin/python -m scripts.find_reseller_pairs --limit 500

Flags:
    --limit N      max number of candidate pairs to write (default 1000)
    --dry-run      score + report; don't write rows
    --min-score F  drop candidates below this composite score (default 0.5)

The scorer is brand-pair-bucketed: any single brand-pair (e.g. AVS x
WeatherTech) is capped at 200 pairs per run so the admin queue doesn't
fill with one over-aggressive brand mapping.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import (  # noqa: E402
    Brand,
    PacePart,
    PaceFitment,
    Product,
    ProductAttribute,
    ProductCategory,
    ProductMatch,
    ProductMatchStatus,
    ProductMatchSource,
)


log = logging.getLogger("find_reseller_pairs")


def _fitment_hash(vehicle_ids: list[int]) -> str:
    """Short stable hash of a sorted, deduped vehicle-id list. Used to
    bucket products with identical fitment coverage so we only compare
    items that fit literally the same set of trucks.
    """
    if not vehicle_ids:
        return "empty"
    canon = ",".join(str(v) for v in sorted(set(vehicle_ids)))
    return hashlib.sha1(canon.encode()).hexdigest()[:16]


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str | None, *, drop: set[str] | None = None) -> set[str]:
    if not text:
        return set()
    toks = set(_WORD_RE.findall(text.lower()))
    if drop:
        toks -= drop
    # Drop tokens shorter than 3 chars — too noisy
    return {t for t in toks if len(t) >= 3}


def _jaccard(a: set, b: set) -> float:
    if not a or not b: return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


async def score_candidate_pair(*, a: dict, b: dict, brand_a_tokens: set[str], brand_b_tokens: set[str]) -> tuple[float, dict]:
    """Score one candidate (canonical, alias) pair.

    Both inputs carry pre-loaded attribute + description text. Returns
    (composite_score, signals_dict). Composite is the average of the
    individual signals that fired.
    """
    signals: dict = {}

    # 1. PIES attribute Jaccard.
    attr_a = a["attrs"]; attr_b = b["attrs"]
    if attr_a and attr_b:
        # Compare on (key, normalized value) pairs.
        pairs_a = {(k, v.lower().strip()) for k, v in attr_a.items()}
        pairs_b = {(k, v.lower().strip()) for k, v in attr_b.items()}
        attr_j = _jaccard(pairs_a, pairs_b)
        signals["attr_jaccard"] = round(attr_j, 3)

    # 2. Description token Jaccard, after stripping each side's brand name
    # tokens so "WeatherTech FloorLiner" vs "Auto Ventshade FloorLiner"
    # actually overlap.
    desc_a = _tokenize(a["desc"], drop=brand_a_tokens | brand_b_tokens)
    desc_b = _tokenize(b["desc"], drop=brand_a_tokens | brand_b_tokens)
    if desc_a and desc_b:
        desc_j = _jaccard(desc_a, desc_b)
        signals["desc_jaccard"] = round(desc_j, 3)

    # 3. Identical fitment coverage — implicit from the bucket; record
    # the size so big buckets get more confidence than singletons.
    signals["fitment_overlap_n"] = a.get("fitment_n") or 0

    # 4. Same PCDB part type — implicit from the bucket.
    signals["same_part_type"] = a.get("part_type_id") is not None

    # Composite score: weighted mean. Attributes carry the most weight,
    # description tracks behind, fitment bucket-size adds confidence.
    parts: list[float] = []
    weights: list[float] = []
    if "attr_jaccard" in signals:
        parts.append(signals["attr_jaccard"]); weights.append(2.0)
    if "desc_jaccard" in signals:
        parts.append(signals["desc_jaccard"]); weights.append(1.0)
    if signals.get("fitment_overlap_n", 0) > 0:
        # Convert N → 0..1 sigmoid-ish: 1 vehicle = 0.3, 5 = 0.7, 20+ = ~1.0
        n = signals["fitment_overlap_n"]
        fit_strength = min(1.0, 0.3 + (n / 25))
        parts.append(fit_strength); weights.append(0.5)
        signals["fitment_strength"] = round(fit_strength, 3)

    if not parts:
        return 0.0, signals
    composite = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
    return composite, signals


async def run(*, limit: int, min_score: float, dry_run: bool) -> int:
    async with async_session() as db:
        log.info("Loading products + categories + fitments…")

        # All products in active brands. Join brand for name + filtering.
        prod_rows = (await db.execute(
            select(
                Product.id, Product.sku, Product.name, Product.description,
                Product.brand_id, Brand.name.label("brand_name"),
            )
            .join(Brand, Brand.id == Product.brand_id)
            .where(Product.is_for_sale.is_(True), Product.is_hidden.is_(False),
                   Brand.is_active.is_(True))
        )).all()
        products = {r.id: dict(
            id=r.id, sku=r.sku, name=r.name, desc=r.description or r.name or "",
            brand_id=r.brand_id, brand_name=r.brand_name,
        ) for r in prod_rows}
        log.info("  %d active products", len(products))

        # Primary category per product.
        cat_rows = (await db.execute(
            select(ProductCategory.product_id, ProductCategory.category_id)
            .where(ProductCategory.is_primary.is_(True))
        )).all()
        for pid, cid in cat_rows:
            if pid in products:
                products[pid]["primary_cat"] = cid

        # PCDB part type per product (pick the first pace_part's terminology).
        ppart_rows = (await db.execute(
            select(PacePart.product_id, PacePart.id, PacePart.part_terminology_id)
            .where(PacePart.product_id.is_not(None))
        )).all()
        pace_part_by_product: dict[int, list[tuple[int, int | None]]] = defaultdict(list)
        for pid, ppid, ptid in ppart_rows:
            if pid in products:
                pace_part_by_product[pid].append((ppid, ptid))
        for pid, parts in pace_part_by_product.items():
            # Use the first non-null part_terminology_id we see
            for _, ptid in parts:
                if ptid:
                    products[pid]["part_type_id"] = ptid
                    break

        # Fitment vehicle list per product.
        log.info("Loading fitments…")
        if pace_part_by_product:
            pace_part_ids = [ppid for parts in pace_part_by_product.values() for ppid, _ in parts]
            fit_rows = (await db.execute(
                select(PaceFitment.pace_part_id, PaceFitment.base_vehicle_id)
                .where(PaceFitment.pace_part_id.in_(pace_part_ids))
            )).all()
            part_to_product = {ppid: pid for pid, parts in pace_part_by_product.items() for ppid, _ in parts}
            fits_by_product: dict[int, list[int]] = defaultdict(list)
            for ppid, vid in fit_rows:
                pid = part_to_product.get(ppid)
                if pid is not None:
                    fits_by_product[pid].append(vid)
            for pid, vids in fits_by_product.items():
                if pid in products:
                    products[pid]["fitments"] = vids
                    products[pid]["fitment_n"] = len(set(vids))

        # PIES attributes — load as a dict keyed by canonical key.
        log.info("Loading PIES attributes…")
        attr_rows = (await db.execute(
            select(ProductAttribute.product_id, ProductAttribute.key, ProductAttribute.value)
        )).all()
        attrs_by_product: dict[int, dict[str, str]] = defaultdict(dict)
        for pid, k, v in attr_rows:
            if pid in products and k and v:
                attrs_by_product[pid][k] = v
        for pid, ad in attrs_by_product.items():
            products[pid]["attrs"] = ad

        # Bucket by (primary_cat, part_type_id, fitment_hash).
        log.info("Bucketing…")
        buckets: dict[tuple, list[int]] = defaultdict(list)
        for pid, p in products.items():
            if not p.get("primary_cat"):
                continue
            fh = _fitment_hash(p.get("fitments") or [])
            key = (p["primary_cat"], p.get("part_type_id"), fh)
            buckets[key].append(pid)

        log.info("  %d buckets; %d non-trivial (size > 1)",
                 len(buckets), sum(1 for v in buckets.values() if len(v) > 1))

        # Pair generation: within each non-trivial bucket, generate
        # cross-brand pairs only.
        log.info("Scoring candidate pairs…")
        candidates: list[tuple[int, int, float, dict]] = []
        per_brand_pair_cap = 200
        per_brand_pair_count: dict[tuple[int, int], int] = defaultdict(int)
        for key, pids in buckets.items():
            if len(pids) < 2:
                continue
            # Skip the "empty fitments" bucket when there's also no part_type — that's
            # the dumping ground for products with no PIES/ACES coverage.
            if key[1] is None and key[2] == "empty":
                continue
            for i in range(len(pids)):
                for j in range(i + 1, len(pids)):
                    a_id, b_id = pids[i], pids[j]
                    a = products[a_id]; b = products[b_id]
                    if a["brand_id"] == b["brand_id"]:
                        continue
                    # Canonical = lower id (arbitrary but stable)
                    canon, alias = (a_id, b_id) if a_id < b_id else (b_id, a_id)
                    brand_pair = tuple(sorted((a["brand_id"], b["brand_id"])))
                    if per_brand_pair_count[brand_pair] >= per_brand_pair_cap:
                        continue
                    brand_a_tokens = _tokenize(a["brand_name"])
                    brand_b_tokens = _tokenize(b["brand_name"])
                    score, signals = await score_candidate_pair(
                        a=a, b=b,
                        brand_a_tokens=brand_a_tokens,
                        brand_b_tokens=brand_b_tokens,
                    )
                    if score < min_score:
                        continue
                    candidates.append((canon, alias, score, signals))
                    per_brand_pair_count[brand_pair] += 1

        log.info("  %d candidates ≥ %.2f score", len(candidates), min_score)
        candidates.sort(key=lambda c: c[2], reverse=True)
        candidates = candidates[:limit]

        if dry_run:
            for canon, alias, score, signals in candidates[:20]:
                a = products[canon]; b = products[alias]
                log.info("  %.3f  %s/%s  ←→  %s/%s  signals=%s",
                         score, a["brand_name"], a["sku"], b["brand_name"], b["sku"], signals)
            log.info("Dry run — not writing.")
            return 0

        inserted = 0
        for canon, alias, score, signals in candidates:
            stmt = pg_insert(ProductMatch).values(
                canonical_product_id=canon,
                alias_product_id=alias,
                status=ProductMatchStatus.PENDING.value,
                score=float(score),
                source=ProductMatchSource.AUTO.value,
                signals=signals,
            ).on_conflict_do_nothing(index_elements=["canonical_product_id", "alias_product_id"])
            r = await db.execute(stmt)
            if r.rowcount:
                inserted += 1
        await db.commit()
        log.info("Inserted %d new pending pairs (existing duplicates skipped).", inserted)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(limit=args.limit, min_score=args.min_score, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
