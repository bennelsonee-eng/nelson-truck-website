"""Audit Buyers/SnowDogg SKUs that never resolved to a slug.

After two full sweeps + the variant-SKU fallback, ~285 of the 540
Buyers/SnowDogg products still couldn't be matched to a buyersproducts.com
slug. These are the SKUs that returned "no slug" on every attempt —
their part numbers aren't in Buyers' autocomplete API or search results.

Likely causes (we want to categorize them for owner review):

  - **Variant pattern** — base + finish letter suffix. The autocomplete
    SHOULD route these to a parent but didn't this time. Worth a re-run
    with a less aggressive timeout or a smarter strip-suffix loop.
  - **Short model codes** — `B20`, `B23`, `HP11`, `L3885`. These look
    like internal series codes rather than ordering part numbers.
  - **Other-brand SKUs mis-tagged as Buyers** — short alpha codes
    sometimes belong to ECCO, Federal Signal, Tommy Gate, etc.
  - **Discontinued / superseded** — Buyers no longer carries them.
  - **Genuinely Buyers but renamed** — Buyers refactored their slug
    URL pattern and the autocomplete doesn't index the legacy PN.

Output: a markdown report at refs/buyers_layout_probes/NO_SLUG_AUDIT.md
with totals, grouped samples, and a suggested action per category.

Run from app/ with the backend venv:
    backend/.venv/bin/python -m scripts.audit_buyers_no_slug
"""

from __future__ import annotations

import argparse
import asyncio
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

from sqlalchemy import or_, select  # noqa: E402

from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import Brand, Product, ProductImage, ProductResource  # noqa: E402


# SKU pattern categories — first match wins (more specific first).
# Each tuple is (category_label, regex, suggested_action).
CATEGORIES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "variant_suffix_letter",
        re.compile(r"^[A-Z]+\d+[A-Z]{1,4}$"),
        "Likely base part + finish code (e.g. B2589B = B2589 in 'B' finish). "
        "Worth a targeted re-scrape with a strip-suffix loop.",
    ),
    (
        "digits_then_letter_suffix",
        re.compile(r"^\d+[A-Z]{1,4}$"),
        "Pure-numeric base + letter finish (e.g. 1400601SS = 1400601 stainless). "
        "Same variant-fallback strategy as above.",
    ),
    (
        "short_alpha_code",
        re.compile(r"^[A-Z]{2,4}\d{0,3}$"),
        "Short code like HP11, B20, L3885 — likely internal series ID, not "
        "an orderable PN. Audit: is this real inventory or catalog bloat?",
    ),
    (
        "series_name",
        re.compile(r"^[A-Z]{3,}[IVX]+$"),
        "Series name like SNOWXPII, VXFII — probably a model family, not a "
        "specific orderable SKU. Hide or convert to category if applicable.",
    ),
    (
        "prefixed_with_brand_code",
        re.compile(r"^[A-Z]{3,5}\d+[A-Z]?$"),
        "Brand-prefixed PN that Buyers doesn't recognize. Could be a "
        "discontinued PN or a SnowDogg-internal code Buyers stripped from "
        "their public catalog. Worth a manual spot-check of 3-5 samples.",
    ),
]


def categorize(sku: str) -> tuple[str, str]:
    """Return (category_label, suggested_action) — falls back to 'other'."""
    s = sku.strip().upper()
    for label, pat, action in CATEGORIES:
        if pat.match(s):
            return label, action
    return (
        "other",
        "Doesn't match any known pattern. Manual review required.",
    )


async def run(out_path: Path) -> int:
    async with async_session() as db:
        # Find Buyers/SnowDogg products that have NO ProductResource from
        # buyersproducts.com (= never got a successful Phase-2 PDP fetch).
        # We further filter to products with no ProductImage either — those
        # are the ones that probably failed at Phase 1 (no slug), as opposed
        # to slugs that returned 0 matching images via filename filter.
        stmt = (
            select(Product, Brand.name)
            .join(Brand, Brand.id == Product.brand_id)
            .where(
                or_(Brand.name.ilike("%buyers%"), Brand.name.ilike("%snowdogg%")),
                Product.is_for_sale.is_(True),
                Product.is_hidden.is_(False),
                ~(
                    select(ProductImage.id)
                    .where(ProductImage.product_id == Product.id)
                    .exists()
                ),
                ~(
                    select(ProductResource.id)
                    .where(
                        ProductResource.product_id == Product.id,
                        ProductResource.source == "buyersproducts.com",
                    )
                    .exists()
                ),
            )
            .order_by(Product.sku)
        )
        rows = (await db.execute(stmt)).all()

    # Group by category
    by_cat: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    actions: dict[str, str] = {}
    for product, brand_name in rows:
        # Use the PN portion (after brand prefix) for pattern matching, since
        # our DB stores SKUs like SNOW-16063120 but the relevant pattern lives
        # on the bare 16063120.
        bare = re.sub(r"^(?:[A-Z]{2,5}-)", "", product.sku)
        cat, action = categorize(bare)
        by_cat[cat].append((product.sku, brand_name, product.name or ""))
        actions[cat] = action

    total = sum(len(v) for v in by_cat.values())

    # Build the markdown report
    lines: list[str] = []
    lines.append("# Buyers/SnowDogg no-slug audit")
    lines.append("")
    lines.append(
        f"**Total products with no Buyers image AND no Buyers ProductResource: "
        f"{total}**"
    )
    lines.append("")
    lines.append(
        "These are Buyers/SnowDogg-branded products in our catalog that two "
        "full scrape sweeps (the original + the variant-SKU fallback round) "
        "failed to resolve to a buyersproducts.com slug. They're grouped by "
        "SKU pattern below; each group has a suggested next action."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Sort categories by count desc
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"## `{cat}` ({len(items)} SKUs)")
        lines.append("")
        lines.append(f"**Suggested action**: {actions.get(cat, '')}")
        lines.append("")
        lines.append("Sample (first 20):")
        lines.append("")
        lines.append("| SKU | Brand | Name |")
        lines.append("|---|---|---|")
        for sku, brand_name, name in items[:20]:
            short_name = name[:60].replace("|", "\\|")
            lines.append(f"| `{sku}` | {brand_name} | {short_name} |")
        if len(items) > 20:
            lines.append("")
            lines.append(f"_…and {len(items) - 20} more._")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Recommended next steps")
    lines.append("")
    lines.append(
        "1. **`variant_suffix_letter` + `digits_then_letter_suffix`**: write a "
        "targeted re-scrape that, on \"no slug\" from the autocomplete + HTML "
        "fallback, strips trailing letters from the PN and retries (e.g. "
        "`B2589BZ` → `B2589B` → `B2589`). Should resolve most of these to a "
        "parent product."
    )
    lines.append(
        "2. **`short_alpha_code` + `series_name`**: manual triage. These are "
        "the highest-suspicion catalog-bloat candidates. Decision per SKU:"
    )
    lines.append("   - Real inventory we sell → re-tag to actual vendor brand")
    lines.append("   - Discontinued / never-stocked → set `is_hidden=true`")
    lines.append("   - Series/family code → convert to a category page")
    lines.append(
        "3. **`prefixed_with_brand_code`**: 3-5 sample SKUs into Buyers' "
        "search UI manually — confirm whether they're truly gone from the "
        "public catalog or just renamed."
    )
    lines.append(
        "4. **`other`**: skim the list; usually a long tail of "
        "one-off edge cases not worth a script."
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}  ({total} products, {len(by_cat)} categories)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="refs/buyers_layout_probes/NO_SLUG_AUDIT.md",
        help="Output path for the markdown report (default: in refs/)",
    )
    args = parser.parse_args()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(run(out_path))


if __name__ == "__main__":
    sys.exit(main())
