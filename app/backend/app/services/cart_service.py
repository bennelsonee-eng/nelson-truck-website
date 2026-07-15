"""Cart utilities — anonymous-cart merge on login + helpers.

Anonymous shoppers get a cart keyed by `session_token` (HttpOnly cookie). The
moment they log in (signup, login, link-customer), we merge that anonymous cart
into their customer cart so they don't lose what they were building.

Merge rules:
  * If both products overlap, quantities sum (capped at 999 to match
    AddLineRequest validation).
  * If the customer didn't have a cart yet, the anonymous cart is reassigned
    to the customer (cheap UPSERT — no row deletes needed).
  * If the customer already has a cart, anonymous lines are moved or merged
    into it line-by-line, then the empty anonymous cart is deleted.

The pure merge planner is split out so unit tests can exercise the logic
without a DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Cart, CartLine


__all__ = [
    "MergeAction",
    "MergePlan",
    "compute_merge_plan",
    "merge_anonymous_into_customer_cart",
    "QTY_CAP",
]


QTY_CAP = 999  # Mirror AddLineRequest validation upper bound.


@dataclass
class MergeAction:
    """One discrete action against the database."""

    kind: str           # "move" | "increment_existing" | "delete_anon_line" | "delete_anon_cart" | "reassign_anon_cart"
    anon_line_id: int | None = None
    customer_line_id: int | None = None
    new_quantity: int | None = None
    anon_cart_id: int | None = None
    customer_cart_id: int | None = None


@dataclass
class MergePlan:
    actions: list[MergeAction] = field(default_factory=list)
    # Final post-merge customer-cart product → quantity map.  Useful for assertions.
    final_quantities: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _LineLike:
    """Minimal cart-line shape for the pure planner (id, product_id, quantity)."""

    id: int
    product_id: int
    quantity: int


def compute_merge_plan(
    *,
    anon_cart_id: int | None,
    customer_cart_id: int | None,
    anon_lines: list[_LineLike],
    customer_lines: list[_LineLike],
) -> MergePlan:
    """Pure: figure out the merge actions without touching the DB.

    Three shapes:
      1. No anonymous cart → no-op.
      2. Anonymous cart but no customer cart → reassign anon → customer.
      3. Both carts present → walk anon lines, move-or-sum into customer cart,
         then delete the (now empty) anonymous cart.
    """
    plan = MergePlan()

    # Case 1 — nothing to merge
    if anon_cart_id is None or not anon_lines:
        plan.final_quantities = {l.product_id: l.quantity for l in customer_lines}
        # If the anon cart exists but is empty, just clear it out
        if anon_cart_id is not None and customer_cart_id is not None:
            plan.actions.append(MergeAction(kind="delete_anon_cart", anon_cart_id=anon_cart_id))
        return plan

    # Case 2 — customer has no cart yet, just reassign
    if customer_cart_id is None:
        plan.actions.append(MergeAction(kind="reassign_anon_cart", anon_cart_id=anon_cart_id))
        plan.final_quantities = {l.product_id: min(QTY_CAP, l.quantity) for l in anon_lines}
        return plan

    # Case 3 — both carts present, do the line-by-line merge
    customer_by_pid: dict[int, _LineLike] = {l.product_id: l for l in customer_lines}
    final = {pid: line.quantity for pid, line in customer_by_pid.items()}

    for anon in anon_lines:
        existing = customer_by_pid.get(anon.product_id)
        if existing is None:
            # Move this anon line into the customer cart
            plan.actions.append(MergeAction(
                kind="move",
                anon_line_id=anon.id,
                customer_cart_id=customer_cart_id,
            ))
            final[anon.product_id] = min(QTY_CAP, anon.quantity)
        else:
            # Increment the customer line and delete the anon line
            new_qty = min(QTY_CAP, existing.quantity + anon.quantity)
            plan.actions.append(MergeAction(
                kind="increment_existing",
                customer_line_id=existing.id,
                new_quantity=new_qty,
            ))
            plan.actions.append(MergeAction(
                kind="delete_anon_line",
                anon_line_id=anon.id,
            ))
            final[anon.product_id] = new_qty

    plan.actions.append(MergeAction(kind="delete_anon_cart", anon_cart_id=anon_cart_id))
    plan.final_quantities = final
    return plan


async def merge_anonymous_into_customer_cart(
    db: AsyncSession,
    *,
    session_token: str | None,
    customer_id: int,
) -> Cart | None:
    """Apply `compute_merge_plan` against the DB.

    Returns the resulting customer cart (may still be None if neither cart
    existed).  No-op if `session_token` is empty/missing.
    """
    if not session_token:
        # No anon cookie → nothing to merge
        return (await db.execute(
            select(Cart).where(Cart.customer_id == customer_id)
        )).scalar_one_or_none()

    anon_cart = (await db.execute(
        select(Cart).where(Cart.session_token == session_token)
    )).scalar_one_or_none()
    customer_cart = (await db.execute(
        select(Cart).where(Cart.customer_id == customer_id)
    )).scalar_one_or_none()

    anon_lines: list[_LineLike] = []
    if anon_cart is not None:
        rows = (await db.execute(
            select(CartLine).where(CartLine.cart_id == anon_cart.id)
        )).scalars().all()
        anon_lines = [_LineLike(id=l.id, product_id=l.product_id, quantity=l.quantity) for l in rows]

    customer_lines: list[_LineLike] = []
    if customer_cart is not None:
        rows = (await db.execute(
            select(CartLine).where(CartLine.cart_id == customer_cart.id)
        )).scalars().all()
        customer_lines = [_LineLike(id=l.id, product_id=l.product_id, quantity=l.quantity) for l in rows]

    plan = compute_merge_plan(
        anon_cart_id=anon_cart.id if anon_cart else None,
        customer_cart_id=customer_cart.id if customer_cart else None,
        anon_lines=anon_lines,
        customer_lines=customer_lines,
    )

    # Index existing rows for fast lookup during action application
    line_by_id: dict[int, CartLine] = {}
    if anon_cart is not None:
        for l in (await db.execute(
            select(CartLine).where(CartLine.cart_id == anon_cart.id)
        )).scalars().all():
            line_by_id[l.id] = l
    if customer_cart is not None:
        for l in (await db.execute(
            select(CartLine).where(CartLine.cart_id == customer_cart.id)
        )).scalars().all():
            line_by_id[l.id] = l

    for action in plan.actions:
        if action.kind == "reassign_anon_cart":
            assert anon_cart is not None
            anon_cart.session_token = None
            anon_cart.customer_id = customer_id
            customer_cart = anon_cart
        elif action.kind == "move":
            assert action.anon_line_id is not None
            line = line_by_id.get(action.anon_line_id)
            if line is not None and customer_cart is not None:
                line.cart_id = customer_cart.id
        elif action.kind == "increment_existing":
            assert action.customer_line_id is not None
            line = line_by_id.get(action.customer_line_id)
            if line is not None:
                line.quantity = action.new_quantity or line.quantity
        elif action.kind == "delete_anon_line":
            assert action.anon_line_id is not None
            line = line_by_id.get(action.anon_line_id)
            if line is not None:
                await db.delete(line)
        elif action.kind == "delete_anon_cart":
            if anon_cart is not None and anon_cart is not customer_cart:
                await db.delete(anon_cart)

    await db.flush()
    return customer_cart
