"""Tests for the anonymous-cart merge planner.

These exercise `compute_merge_plan` — the pure function that decides what to do
without touching the DB.  The async DB-wrapping layer is verified by integration
tests at the router level (test_auth_cart_merge_db.py).
"""

from __future__ import annotations

from app.services.cart_service import (
    QTY_CAP,
    MergeAction,
    compute_merge_plan,
    _LineLike,
)


def L(id: int, product_id: int, quantity: int) -> _LineLike:
    return _LineLike(id=id, product_id=product_id, quantity=quantity)


# -------------------------------------------------------------------------
# Case 1 — nothing to merge
# -------------------------------------------------------------------------


class TestNothingToMerge:
    def test_no_anon_cart_no_actions(self):
        plan = compute_merge_plan(
            anon_cart_id=None, customer_cart_id=None,
            anon_lines=[], customer_lines=[],
        )
        assert plan.actions == []
        assert plan.final_quantities == {}

    def test_no_anon_cart_but_customer_cart_unchanged(self):
        plan = compute_merge_plan(
            anon_cart_id=None, customer_cart_id=42,
            anon_lines=[], customer_lines=[L(10, 100, 3)],
        )
        assert plan.actions == []
        assert plan.final_quantities == {100: 3}

    def test_anon_cart_present_but_empty_drops_the_empty_cart(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[], customer_lines=[L(10, 100, 3)],
        )
        # Empty anon cart still gets cleaned up
        assert plan.actions == [MergeAction(kind="delete_anon_cart", anon_cart_id=99)]
        assert plan.final_quantities == {100: 3}

    def test_anon_cart_empty_no_customer_cart_no_op(self):
        # Edge: anon cart exists but is empty AND no customer cart — nothing to do
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=None,
            anon_lines=[], customer_lines=[],
        )
        assert plan.actions == []
        assert plan.final_quantities == {}


# -------------------------------------------------------------------------
# Case 2 — customer has no cart yet → reassign anon to customer
# -------------------------------------------------------------------------


class TestReassignWhenNoCustomerCart:
    def test_simple_reassign(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=None,
            anon_lines=[L(10, 100, 2), L(11, 101, 5)],
            customer_lines=[],
        )
        assert plan.actions == [MergeAction(kind="reassign_anon_cart", anon_cart_id=99)]
        assert plan.final_quantities == {100: 2, 101: 5}

    def test_reassign_caps_quantity_at_999(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=None,
            anon_lines=[L(10, 100, 5000)],  # absurd qty (should never reach here in practice)
            customer_lines=[],
        )
        assert plan.actions == [MergeAction(kind="reassign_anon_cart", anon_cart_id=99)]
        assert plan.final_quantities == {100: QTY_CAP}


# -------------------------------------------------------------------------
# Case 3 — both carts present, line-by-line merge
# -------------------------------------------------------------------------


class TestLineByLineMerge:
    def test_no_overlap_moves_all_anon_lines(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[L(10, 100, 2), L(11, 101, 3)],
            customer_lines=[L(20, 200, 1)],
        )
        assert MergeAction(kind="move", anon_line_id=10, customer_cart_id=42) in plan.actions
        assert MergeAction(kind="move", anon_line_id=11, customer_cart_id=42) in plan.actions
        assert MergeAction(kind="delete_anon_cart", anon_cart_id=99) in plan.actions
        assert plan.final_quantities == {200: 1, 100: 2, 101: 3}

    def test_overlap_sums_quantities_and_deletes_anon_line(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[L(10, 100, 2)],
            customer_lines=[L(20, 100, 5)],  # same product
        )
        # Increment customer line to 7, delete anon line, drop anon cart
        assert MergeAction(kind="increment_existing", customer_line_id=20, new_quantity=7) in plan.actions
        assert MergeAction(kind="delete_anon_line", anon_line_id=10) in plan.actions
        assert MergeAction(kind="delete_anon_cart", anon_cart_id=99) in plan.actions
        assert plan.final_quantities == {100: 7}

    def test_overlap_caps_summed_quantity(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[L(10, 100, 600)],
            customer_lines=[L(20, 100, 600)],
        )
        # 600 + 600 = 1200, capped at 999
        assert MergeAction(kind="increment_existing", customer_line_id=20, new_quantity=QTY_CAP) in plan.actions
        assert plan.final_quantities == {100: QTY_CAP}

    def test_mixed_overlap_and_new_lines(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[L(10, 100, 2), L(11, 200, 4)],   # 100 overlaps, 200 is new
            customer_lines=[L(20, 100, 5), L(21, 300, 1)],  # 100 overlaps
        )
        # Expected: increment customer line 20 to 7, delete anon line 10,
        # move anon line 11 (product 200) into customer cart, drop anon cart.
        kinds = [(a.kind, a.anon_line_id, a.customer_line_id, a.new_quantity, a.anon_cart_id) for a in plan.actions]
        assert ("increment_existing", None, 20, 7, None) in kinds
        assert ("delete_anon_line", 10, None, None, None) in kinds
        assert ("move", 11, None, None, None) in kinds
        assert ("delete_anon_cart", None, None, None, 99) in kinds
        assert plan.final_quantities == {100: 7, 200: 4, 300: 1}

    def test_action_order_matters_for_correctness(self):
        # The delete_anon_cart MUST come last so its dependent line deletes /
        # moves are processed first.  (cascade=delete-orphan would otherwise
        # nuke moved lines.)
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[L(10, 100, 1)],
            customer_lines=[],
        )
        assert plan.actions[-1].kind == "delete_anon_cart"

        plan2 = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[L(10, 100, 1), L(11, 101, 1)],
            customer_lines=[L(20, 100, 1)],
        )
        assert plan2.actions[-1].kind == "delete_anon_cart"


# -------------------------------------------------------------------------
# Edge cases
# -------------------------------------------------------------------------


class TestEdgeCases:
    def test_three_overlapping_products(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[L(10, 100, 1), L(11, 200, 2), L(12, 300, 3)],
            customer_lines=[L(20, 100, 4), L(21, 200, 5), L(22, 300, 6)],
        )
        # Three increments + three deletes + one cart drop
        increments = [a for a in plan.actions if a.kind == "increment_existing"]
        deletes = [a for a in plan.actions if a.kind == "delete_anon_line"]
        assert len(increments) == 3
        assert len(deletes) == 3
        assert plan.final_quantities == {100: 5, 200: 7, 300: 9}

    def test_anon_carts_with_only_new_products_skip_increment_path(self):
        plan = compute_merge_plan(
            anon_cart_id=99, customer_cart_id=42,
            anon_lines=[L(10, 999, 1)],
            customer_lines=[L(20, 100, 1), L(21, 200, 1)],
        )
        # Only a "move" action + cart drop — no increments, no deletes
        assert any(a.kind == "move" for a in plan.actions)
        assert not any(a.kind == "increment_existing" for a in plan.actions)
        assert not any(a.kind == "delete_anon_line" for a in plan.actions)
