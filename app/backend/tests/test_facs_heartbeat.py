"""Tests for the FACS pickup heartbeat — pure planner + DB integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app.models import (
    Brand,
    Customer,
    CustomerTier,
    FACSPushStatus,
    Order,
    OrderFulfillment,
    OrderStatus,
    PaymentType,
    Product,
)
from app.services import facs_heartbeat as hb_module
from app.services.facs_heartbeat import (
    PickupAction,
    _PushedFulfillmentLike,
    compute_pickup_actions,
    run_heartbeat_once,
)


# =========================================================================
# Pure: compute_pickup_actions()
# =========================================================================


def _F(id, file_name, pushed_minutes_ago=None):
    pushed = (
        datetime.now(timezone.utc) - timedelta(minutes=pushed_minutes_ago)
        if pushed_minutes_ago is not None else None
    )
    return _PushedFulfillmentLike(id=id, file_name=file_name, pushed_at=pushed)


class TestComputePickupActions:
    def test_no_fulfillments_no_actions(self):
        out = compute_pickup_actions(
            pushed_fulfillments=[], dropbox_files=set(),
            now=datetime.now(timezone.utc), lag_alert_minutes=30,
        )
        assert out == []

    def test_file_missing_marks_picked_up(self):
        out = compute_pickup_actions(
            pushed_fulfillments=[_F(1, "X.CSV", 1)],
            dropbox_files=set(),
            now=datetime.now(timezone.utc), lag_alert_minutes=30,
        )
        assert len(out) == 1
        assert out[0].kind == "mark_picked_up"
        assert out[0].fulfillment_id == 1

    def test_file_still_present_within_threshold_no_action(self):
        out = compute_pickup_actions(
            pushed_fulfillments=[_F(1, "X.CSV", 5)],
            dropbox_files={"X.CSV"},
            now=datetime.now(timezone.utc), lag_alert_minutes=30,
        )
        assert out == []

    def test_file_still_present_over_threshold_warns(self):
        out = compute_pickup_actions(
            pushed_fulfillments=[_F(1, "X.CSV", 60)],
            dropbox_files={"X.CSV"},
            now=datetime.now(timezone.utc), lag_alert_minutes=30,
        )
        assert len(out) == 1
        assert out[0].kind == "warn_lag"
        assert out[0].age_minutes is not None and out[0].age_minutes >= 60

    def test_no_pushed_at_skips_lag_check(self):
        out = compute_pickup_actions(
            pushed_fulfillments=[_F(1, "X.CSV", None)],
            dropbox_files={"X.CSV"},
            now=datetime.now(timezone.utc), lag_alert_minutes=30,
        )
        assert out == []

    def test_mixed_actions_in_one_tick(self):
        out = compute_pickup_actions(
            pushed_fulfillments=[
                _F(1, "PICKED.CSV", 5),
                _F(2, "STUCK.CSV", 90),
                _F(3, "FRESH.CSV", 1),
            ],
            dropbox_files={"STUCK.CSV", "FRESH.CSV"},
            now=datetime.now(timezone.utc), lag_alert_minutes=30,
        )
        kinds = sorted((a.kind, a.fulfillment_id) for a in out)
        assert kinds == [("mark_picked_up", 1), ("warn_lag", 2)]


# =========================================================================
# DB integration: run_heartbeat_once()
# =========================================================================


@pytest_asyncio.fixture
async def heartbeat_world(clean_db):
    """Seed a single placed order with a single PUSHED fulfillment for testing."""
    db = clean_db

    brand = Brand(name="HBBrand", slug="hbbrand")
    db.add(brand)
    await db.flush()
    product = Product(sku="HB-1", brand_id=brand.id, prod_code="HB", name="HB Test")
    db.add(product)
    await db.flush()
    customer = Customer(customer_number="HB-CUST", name="HB", tier=CustomerTier.JOBBER)
    db.add(customer)
    await db.flush()

    order = Order(
        web_order_number="TTW9000001", customer_id=customer.id,
        status=OrderStatus.PUSHED_TO_FACS, payment_type=PaymentType.PURCHASE_ORDER,
        item_total_usd=Decimal("100"), grand_total_usd=Decimal("100"),
    )
    db.add(order)
    await db.flush()

    f = OrderFulfillment(
        order_id=order.id,
        warehouse_id=None,
        file_name="ORDERS_TITAN_SPO_TTW9000001_10.CSV",
        routing_type="SPO",
        facs_warehouse_code=10,
        item_subtotal_usd=Decimal("100"),
        push_status=FACSPushStatus.PUSHED,
        pushed_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        push_attempts=1,
        csv_content="dummy",
    )
    db.add(f)
    await db.commit()
    return db, order, f


class TestRunHeartbeatOnce:
    @pytest.mark.asyncio
    async def test_marks_picked_up_when_file_disappears(self, heartbeat_world, monkeypatch):
        db, order, f = heartbeat_world

        # Stub list_dropbox_files to return empty (file disappeared)
        async def fake_list():
            return []
        monkeypatch.setattr(hb_module, "list_dropbox_files", fake_list)

        tick = await run_heartbeat_once(db)
        assert any(a.kind == "mark_picked_up" for a in tick.actions)
        # Re-fetch fulfillment from DB
        await db.refresh(f)
        assert f.push_status == FACSPushStatus.PICKED_UP
        assert f.picked_up_at is not None

    @pytest.mark.asyncio
    async def test_no_change_when_file_still_present_and_fresh(self, heartbeat_world, monkeypatch):
        db, order, f = heartbeat_world

        async def fake_list():
            return [f.file_name]
        monkeypatch.setattr(hb_module, "list_dropbox_files", fake_list)

        tick = await run_heartbeat_once(db)
        assert tick.actions == []
        await db.refresh(f)
        assert f.push_status == FACSPushStatus.PUSHED  # unchanged

    @pytest.mark.asyncio
    async def test_lag_warning_when_old_and_still_present(self, heartbeat_world, monkeypatch):
        db, order, f = heartbeat_world
        # Make the fulfillment look REALLY old
        f.pushed_at = datetime.now(timezone.utc) - timedelta(hours=24)
        await db.commit()

        async def fake_list():
            return [f.file_name]
        monkeypatch.setattr(hb_module, "list_dropbox_files", fake_list)

        tick = await run_heartbeat_once(db)
        assert any(a.kind == "warn_lag" for a in tick.actions)
        await db.refresh(f)
        # Status NOT changed for warn-lag
        assert f.push_status == FACSPushStatus.PUSHED

    @pytest.mark.asyncio
    async def test_only_pushed_fulfillments_considered(self, heartbeat_world, monkeypatch):
        db, order, f = heartbeat_world
        # Flip to FAILED — should be ignored
        f.push_status = FACSPushStatus.FAILED
        await db.commit()

        async def fake_list():
            return []
        monkeypatch.setattr(hb_module, "list_dropbox_files", fake_list)

        tick = await run_heartbeat_once(db)
        assert tick.actions == []
        await db.refresh(f)
        assert f.push_status == FACSPushStatus.FAILED  # unchanged
