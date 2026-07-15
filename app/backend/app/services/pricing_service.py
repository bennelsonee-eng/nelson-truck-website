"""Pricing service — DB-aware wrapper around the pure pricing_engine.

Resolves a price for a (customer, product, qty) using DB queries to load
contracts + tier_prices, then delegates to pricing_engine.resolve_price().

Anonymous-retail callers can use `resolve_price_anonymous()` which skips the
contract lookup entirely and returns the retail tier-default price.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contract, Customer, CustomerTier, Product, ProductPrice
from app.services.pricing_engine import (
    AgingDiscountConfig,
    ContractRule,
    PriceResolution,
    ResolutionStatus,
    resolve_price,
)


log = logging.getLogger(__name__)


# Sentinel customer that holds the website's retail price book. All
# contracts under this customer drive the public retail price for
# anonymous + retail-tier shoppers. Owner directive 2026-05-17.
# Nelson's website-sales sentinel is customer "9" (86 company='nelson' contract
# rows, all under sentinel contract 9999999 with brand-level markup formulas —
# confirmed 2026-07-14). Titan's equivalent was "106415". Keep in sync with the
# sentinel in scripts/import_initial_data.py.
RETAIL_SENTINEL_CUSTOMER_NUMBER = "9"


__all__ = [
    "TierPricingDisplay",
    "anonymous_retail_display",
    "resolve_for_customer",
    "resolve_retail_for_products",
    "build_retail_display",
    "build_tier_display",
    "build_tier_display_batch",
    "front_counter_quote",
    "RETAIL_SENTINEL_CUSTOMER_NUMBER",
]


def front_counter_quote(
    *,
    cost_basis: Decimal | None,
    map_retail: Decimal | None,
    markup_pct: int | None,
) -> Decimal | None:
    """Compute the walk-in retail price a jobber/dealer should quote.

    Algorithm: ``max(MAP Retail, cost_basis * (1 + markup_pct/100))``.
    Always floored by MAP so the jobber never quotes below the brand-protected
    minimum.  Pure function — no DB, no I/O — so it's trivially testable.

    cost_basis is the *true* underlying cost (pre-MAP-clamp) when available;
    callers should pass ``original_amount or primary_amount`` from the
    ``TierPricingDisplay`` block.

    Returns ``None`` only if there's literally nothing to base a quote on
    (no cost AND no MAP).  If no markup is set, returns MAP Retail (the
    pre-Phase-1 default behavior).
    """
    if not markup_pct:
        # No markup configured — quote is just MAP Retail (or cost if no MAP)
        return map_retail or cost_basis
    if cost_basis is None:
        return map_retail  # cannot compute markup without a cost basis
    factor = Decimal(1) + (Decimal(markup_pct) / Decimal(100))
    marked = (cost_basis * factor).quantize(Decimal("0.01"))
    if map_retail is None:
        return marked
    return marked if marked > map_retail else map_retail


# --- Display helpers ------------------------------------------------------


class TierPricingDisplay:
    """A normalized pricing block for the UI to render.

    Keeps shape stable across tiers; UI renders different layouts based on
    which fields are populated.

    When MAP enforcement clamped the price up (the contract or tier-default
    came in below MAP), the UI gets `map_clamped=True` plus the original
    pre-clamp amount so it can render `~~$160~~ $200 (MAP-floored)` instead
    of two duplicate $200 lines.
    """

    def __init__(
        self,
        *,
        tier: str,
        primary_label: str,
        primary_amount: Decimal | None,
        secondary_label: str | None = None,
        secondary_amount: Decimal | None = None,
        savings_amount: Decimal | None = None,
        contract_id: int | None = None,
        contract_name: str | None = None,
        notes: list[str] | None = None,
        map_clamped: bool = False,
        original_amount: Decimal | None = None,
    ) -> None:
        self.tier = tier
        self.primary_label = primary_label
        self.primary_amount = primary_amount
        self.secondary_label = secondary_label
        self.secondary_amount = secondary_amount
        self.savings_amount = savings_amount
        self.contract_id = contract_id
        self.contract_name = contract_name
        self.notes = notes or []
        self.map_clamped = map_clamped
        self.original_amount = original_amount

    def as_dict(self) -> dict[str, Any]:
        def _f(d: Decimal | None) -> str | None:
            return str(d.quantize(Decimal("0.01"))) if d is not None else None
        return {
            "tier": self.tier,
            "primary_label": self.primary_label,
            "primary_amount": _f(self.primary_amount),
            "secondary_label": self.secondary_label,
            "secondary_amount": _f(self.secondary_amount),
            "savings_amount": _f(self.savings_amount),
            "contract_id": self.contract_id,
            "contract_name": self.contract_name,
            "notes": self.notes,
            "map_clamped": self.map_clamped,
            "original_amount": _f(self.original_amount),
        }


def anonymous_retail_display(price: ProductPrice | None) -> TierPricingDisplay:
    """Single line: "Retail $X".

    Per owner 2026-05-17: MAP is retail-only — meaning the retail price we
    display ALREADY reflects MAP — so the old two-line "Suggested Retail
    $100 / Retail $80 / Save $20" theatrics are off the website. Just show
    one number.

    This is the legacy direct-from-ProductPrice display. New callers should
    prefer `build_retail_display` / `resolve_retail_for_products`, which
    route the retail price through the contract pricing engine using the
    RETAIL_SENTINEL_CUSTOMER_NUMBER customer. This function remains as a
    fallback for when the sentinel customer is unavailable.
    """
    if price is None:
        return TierPricingDisplay(tier="retail", primary_label="Retail", primary_amount=None)
    return TierPricingDisplay(
        tier="retail",
        primary_label="Retail",
        primary_amount=price.retail_price or price.suggested_retail_price,
    )


# --- Sentinel-driven retail resolution --------------------------------------


async def resolve_retail_for_products(
    db: AsyncSession,
    products: list[Product],
) -> dict[int, Decimal | None]:
    """Batch-resolve the public retail price for a list of products.

    Routes each product through the contract pricing engine using the
    "TITAN WEBSITE SALES" sentinel customer (customer_number =
    RETAIL_SENTINEL_CUSTOMER_NUMBER) — owner directive 2026-05-17. The
    contracts under that customer ARE the website's retail price book:
    brand-level markups (e.g. "P5/.85" → cost / 0.85), part-specific
    flat prices, etc.

    Returns a dict keyed by product_id with the resolved Decimal price
    (or None if no price can be derived). Designed for use by the
    catalog browse endpoint where we resolve 24+ products per request;
    a single query for the sentinel's contracts (~170 rows total) gets
    filtered in-Python per product so DB pressure stays constant.
    """
    if not products:
        return {}

    pids = [p.id for p in products]

    sentinel = (await db.execute(
        select(Customer).where(
            Customer.customer_number == RETAIL_SENTINEL_CUSTOMER_NUMBER
        )
    )).scalar_one_or_none()

    # Always load ProductPrice — used either as the engine's tier source or as
    # the fallback path when the sentinel doesn't exist.
    pp_rows = (await db.execute(
        select(ProductPrice).where(ProductPrice.product_id.in_(pids))
    )).scalars().all()
    pp_lookup: dict[int, ProductPrice] = {pp.product_id: pp for pp in pp_rows}

    if sentinel is None:
        log.warning(
            "Retail sentinel customer (customer_number=%s) not found; "
            "falling back to ProductPrice.retail_price",
            RETAIL_SENTINEL_CUSTOMER_NUMBER,
        )
        return {
            p.id: ((pp_lookup.get(p.id).retail_price
                    or pp_lookup.get(p.id).suggested_retail_price)
                   if pp_lookup.get(p.id) else None)
            for p in products
        }

    # One query for ALL of the sentinel's contracts. Filter per product
    # in Python — the sentinel typically carries ~170 contract rows so
    # the bulk load stays small.
    all_contracts = (await db.execute(
        select(Contract).where(Contract.customer_id == sentinel.id)
    )).scalars().all()

    cust_id_str = str(sentinel.id)
    out: dict[int, Decimal | None] = {}
    for p in products:
        pp = pp_lookup.get(p.id)
        tiers = {
            1: pp.suggested_retail_price if pp else None,
            2: pp.retail_price if pp else None,
            3: pp.jobber_price if pp else None,
            4: pp.dealer_price if pp else None,
            5: pp.cost if pp else None,
        } if pp else {}
        # tier_default = retail_price for the sentinel resolution path,
        # regardless of the sentinel record's stored `tier` field. The
        # contract under the sentinel may also reference P-tiers (e.g.
        # P5/.85 = cost / 0.85 retail markup) which the engine resolves
        # against `tiers` directly.
        tier_default = tiers.get(2) or tiers.get(1)

        matching = [
            ContractRule(
                contract_id=c.id,
                contract_name=c.name,
                customer_id=cust_id_str,
                brand=c.brand,
                group_code=c.group_code,
                part_number=c.part_number,
                priority=c.priority,
                min_quantity=c.min_quantity,
                pricing_formula=c.pricing_formula,
                expiration_date=c.expiration_date,
            )
            for c in all_contracts
            # brand filter: contract.brand can either be NULL (applies
            # to all brands) or match the product's prod_code prefix
            # (e.g. "YAK" for Yakima parts).
            if (c.brand is None or c.brand == p.prod_code)
            # part filter: NULL = all parts; otherwise exact SKU match.
            and (c.part_number is None or c.part_number == p.sku)
        ]

        result = resolve_price(
            customer_id=cust_id_str,
            product_part_number=p.sku,
            product_brand_code=p.prod_code,
            product_group_code=None,
            qty=1,
            tier_prices=tiers,
            matching_rules=matching,
            tier_default_price=tier_default,
        )
        out[p.id] = result.price

    return out


async def recompute_resolved_retail(
    db: AsyncSession,
    product_ids: list[int] | None = None,
    *,
    chunk: int = 1000,
) -> int:
    """Resolve the sentinel/contract retail price for products and persist it
    into ``product_price.resolved_retail_price`` (+ ``resolved_retail_at``).

    This is the *sort key* counterpart to ``resolve_retail_for_products`` (which
    resolves the same number live for the visible page). Persisting it lets the
    catalog "Price high→low" sort ORDER BY the price the customer actually sees,
    instead of the raw ``retail_price`` tier the sentinel markup diverges from.

    Pass ``product_ids`` to refresh just the rows a price sync touched; omit it
    to recompute every product that has a ``product_price`` row. Returns the
    number of ``product_price`` rows written. Commits per chunk so a long
    backfill makes incremental progress.
    """
    if product_ids is not None:
        if not product_ids:
            return 0
        # Use the supplied ids directly (deduped) rather than re-selecting them
        # via a single WHERE product_id IN (...). When a price sync touches tens
        # of thousands of rows, that one IN blows past asyncpg's 32767-param
        # limit. The supplied ids were just upserted into product_price by the
        # caller, and the per-chunk UPDATE below is a no-op for any that lack a
        # product_price row, so using them directly is safe.
        all_pids: list[int] = list(dict.fromkeys(product_ids))
    else:
        all_pids = (await db.execute(select(ProductPrice.product_id))).scalars().all()

    updated = 0
    for start in range(0, len(all_pids), chunk):
        batch_ids = all_pids[start:start + chunk]
        products = (await db.execute(
            select(Product).where(Product.id.in_(batch_ids))
        )).scalars().all()
        resolved = await resolve_retail_for_products(db, products)
        now = datetime.now(timezone.utc)
        for pid, price in resolved.items():
            await db.execute(
                sa_update(ProductPrice)
                .where(ProductPrice.product_id == pid)
                .values(resolved_retail_price=price, resolved_retail_at=now)
            )
            updated += 1
        await db.commit()
        log.info("  resolved_retail: %d/%d products", min(start + chunk, len(all_pids)), len(all_pids))
    return updated


async def build_retail_display(
    db: AsyncSession,
    product: Product,
) -> TierPricingDisplay:
    """Single-product version of `resolve_retail_for_products`.

    Used by the PDP and any other path that resolves one product at a
    time. Returns a TierPricingDisplay shaped for retail (single line).
    """
    resolved = await resolve_retail_for_products(db, [product])
    return TierPricingDisplay(
        tier="retail",
        primary_label="Retail",
        primary_amount=resolved.get(product.id),
    )


# --- Customer-aware resolution -----------------------------------------------


def _tiers_for(pp: ProductPrice | None) -> dict[int, Decimal | None]:
    """Map a ProductPrice row onto the engine's 1..5 tier dict."""
    return {
        1: pp.suggested_retail_price if pp else None,
        2: pp.retail_price if pp else None,
        3: pp.jobber_price if pp else None,
        4: pp.dealer_price if pp else None,
        5: pp.cost if pp else None,
    } if pp else {}


def _contract_rules_for(
    contracts: list[Contract],
    product: Product,
    customer_id_str: str,
) -> list[ContractRule]:
    """Filter a customer's contracts down to the ones that scope this product
    and convert them to engine ContractRules.

    Matches the SQL filter resolve_for_customer used to run per product:
      brand:  NULL (all brands) OR == product.prod_code
      part:   NULL (all parts)  OR == product.sku
    Doing it in Python lets the caller load the customer's contracts ONCE and
    reuse them across a whole page of products (no per-product query).
    """
    rules: list[ContractRule] = []
    for r in contracts:
        if not (r.brand is None or r.brand == product.prod_code):
            continue
        if not (r.part_number is None or r.part_number == product.sku):
            continue
        rules.append(ContractRule(
            contract_id=r.id,
            contract_name=r.name,
            customer_id=customer_id_str,
            brand=r.brand,
            group_code=r.group_code,
            part_number=r.part_number,
            priority=r.priority,
            min_quantity=r.min_quantity,
            pricing_formula=r.pricing_formula,
            expiration_date=r.expiration_date,
        ))
    return rules


def _resolve_loaded(
    customer: Customer,
    product: Product,
    pp: ProductPrice | None,
    contracts: list[Contract],
    *,
    qty: int = 1,
    aging_config: AgingDiscountConfig = AgingDiscountConfig(),
) -> PriceResolution:
    """Pure (no-DB) resolution from pre-loaded contracts + ProductPrice.

    Shared core for both resolve_for_customer (one product) and
    build_tier_display_batch (a whole page) so the tier-default cascade and
    retail-fallback note logic can't drift between the two call sites.
    """
    cust_id_str = str(customer.id)
    rules = _contract_rules_for(contracts, product, cust_id_str)
    tiers = _tiers_for(pp)

    # Tier default price by customer tier
    if customer.tier == CustomerTier.RETAIL:
        tier_default = tiers.get(2)
    elif customer.tier == CustomerTier.JOBBER:
        tier_default = tiers.get(3)
    elif customer.tier == CustomerTier.DEALER:
        tier_default = tiers.get(3)  # dealers also get jobber price as default tier (per user)
    elif customer.tier == CustomerTier.MUNICIPALITY:
        tier_default = tiers.get(3)  # placeholder; muni really requires contract
    else:
        tier_default = tiers.get(2)

    # Cascade fallback per Ben (2026-05-17): "if a customer doesn't have a
    # contract listing then their price defaults to a retail customer." If
    # the customer's tier-specific price isn't populated on the product,
    # drop through to retail (tier 2), then suggested-retail/MAP (tier 1).
    # This stops "Call for price" surfacing whenever any tier has a price.
    retail_fallback = False
    if tier_default is None:
        tier_default = tiers.get(2)
        if tier_default is not None:
            retail_fallback = True
    if tier_default is None:
        tier_default = tiers.get(1)
        if tier_default is not None:
            retail_fallback = True

    # MAP intentionally NOT passed: per owner 2026-05-17, MAP only applies to
    # retail customers and must not override contract pricing. Jobber / Dealer /
    # Muni / contract customers see their negotiated price even if it sits
    # below the brand-protected minimum. MAP floor still drives the walk-in
    # retail quote inside front_counter_quote() — that path is unchanged.
    result = resolve_price(
        customer_id=cust_id_str,
        product_part_number=product.sku,
        product_brand_code=product.prod_code,
        product_group_code=None,
        qty=qty,
        tier_prices=tiers,
        matching_rules=rules,
        tier_default_price=tier_default,
        aging_config=aging_config,
    )

    # When we fell back to retail because no contract matched AND no
    # tier-specific price existed, replace the engine's generic "used tier
    # default" note with a clearer one so the UI can surface the reason.
    if retail_fallback and result.status == ResolutionStatus.OK_TIER_DEFAULT:
        result.notes = [n for n in result.notes if "tier default" not in n]
        result.notes.append("no contract on file; showing retail price")

    return result


async def resolve_for_customer(
    db: AsyncSession,
    *,
    customer: Customer,
    product: Product,
    qty: int = 1,
    aging_config: AgingDiscountConfig = AgingDiscountConfig(),
) -> PriceResolution:
    """Run the full pricing engine for a (customer, product) pair."""
    contracts = (await db.execute(
        select(Contract).where(Contract.customer_id == customer.id)
    )).scalars().all()
    pp = (await db.execute(
        select(ProductPrice).where(ProductPrice.product_id == product.id)
    )).scalar_one_or_none()
    return _resolve_loaded(
        customer, product, pp, contracts, qty=qty, aging_config=aging_config,
    )


async def build_tier_display(
    db: AsyncSession,
    *,
    customer: Customer,
    product: Product,
) -> TierPricingDisplay:
    """Build the per-tier pricing UI block.

    Calls the pricing engine, then formats per Q29-Q32 rules:
      retail: two-line (Suggested Retail + Retail)
      jobber: two-column (MAP Retail | Your Cost) + can apply Front Counter markup
      dealer: same as jobber (+ Phase 1 financing calc on PDP, Phase 2 toggle)
      muni:   single line (computed contract price)
    """
    res = await resolve_for_customer(db, customer=customer, product=product)
    pp = (await db.execute(
        select(ProductPrice).where(ProductPrice.product_id == product.id)
    )).scalar_one_or_none()
    if customer.tier == CustomerTier.RETAIL:
        # Retail-tier logged-in customers see the same contract-resolved
        # retail price as anonymous shoppers (driven by the sentinel
        # customer's contracts), not their own customer record's contracts.
        return await build_retail_display(db, product)
    return _format_tier_display(customer, res, pp)


def _format_tier_display(
    customer: Customer,
    res: PriceResolution,
    pp: ProductPrice | None,
) -> TierPricingDisplay:
    """Format a resolved price into the per-tier UI block (non-retail tiers).

    RETAIL is handled by the callers (they delegate to the sentinel-driven
    build_retail_display); this covers MUNICIPALITY + JOBBER/DEALER. Pure —
    no DB — so it's shared by the single-product and batch paths.
    """
    map_retail = pp.suggested_retail_price if pp else None
    map_clamped = res.status == ResolutionStatus.MAP_CLAMPED
    original_amount = res.map_clamped_from if map_clamped else None

    if customer.tier == CustomerTier.MUNICIPALITY:
        return TierPricingDisplay(
            tier="municipality",
            primary_label="Contract Price",
            primary_amount=res.price,
            contract_id=res.contract_used.contract_id if res.contract_used else None,
            contract_name=res.contract_used.contract_name if res.contract_used else None,
            notes=res.notes,
            map_clamped=map_clamped,
            original_amount=original_amount,
        )
    # JOBBER + DEALER share the layout (per Q31)
    return TierPricingDisplay(
        tier=customer.tier.value,
        primary_label="Your Cost",
        primary_amount=res.price,
        secondary_label="MAP Retail",
        secondary_amount=map_retail,
        contract_id=res.contract_used.contract_id if res.contract_used else None,
        contract_name=res.contract_used.contract_name if res.contract_used else None,
        notes=res.notes,
        map_clamped=map_clamped,
        original_amount=original_amount,
    )


async def build_tier_display_batch(
    db: AsyncSession,
    *,
    customer: Customer,
    products: list[Product],
) -> dict[int, TierPricingDisplay]:
    """Batched build_tier_display for a whole page of products.

    Eliminates the catalog-browse N+1: instead of per-product contract +
    ProductPrice queries (build_tier_display × 24 rows ≈ 70 queries), this
    loads the customer's contracts ONCE and all page ProductPrice rows ONCE,
    then resolves each product in Python via the shared _resolve_loaded /
    _format_tier_display core. Returns a dict keyed by product_id.
    """
    if not products:
        return {}
    pids = [p.id for p in products]

    # RETAIL-tier logged-in shoppers see the sentinel-driven retail price,
    # same as anonymous — resolve_retail_for_products is already batched.
    if customer.tier == CustomerTier.RETAIL:
        resolved = await resolve_retail_for_products(db, products)
        return {
            p.id: TierPricingDisplay(
                tier="retail", primary_label="Retail",
                primary_amount=resolved.get(p.id),
            )
            for p in products
        }

    contracts = (await db.execute(
        select(Contract).where(Contract.customer_id == customer.id)
    )).scalars().all()
    pp_rows = (await db.execute(
        select(ProductPrice).where(ProductPrice.product_id.in_(pids))
    )).scalars().all()
    pp_lookup: dict[int, ProductPrice] = {pp.product_id: pp for pp in pp_rows}

    out: dict[int, TierPricingDisplay] = {}
    for p in products:
        res = _resolve_loaded(customer, p, pp_lookup.get(p.id), contracts)
        out[p.id] = _format_tier_display(customer, res, pp_lookup.get(p.id))
    return out
