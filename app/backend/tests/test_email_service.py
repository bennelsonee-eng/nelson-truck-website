"""Tests for email_service — composer + sender abstraction."""

from __future__ import annotations

from unittest.mock import patch

from app.services.email_service import (
    ComposedEmail,
    ConsoleSender,
    SendResult,
    _OrderForEmail,
    _OrderLineForEmail,
    compose_order_confirmation,
    send_email,
)


def _line(sku="ABC123", qty=2, bo=0, price="10.00", total="20.00") -> _OrderLineForEmail:
    return _OrderLineForEmail(
        sku=sku, description=f"description for {sku}",
        quantity=qty, backorder_quantity=bo,
        unit_price=price, line_total=total, routing=None,
    )


def _order(**overrides) -> _OrderForEmail:
    defaults = dict(
        web_order_number="TTW0000123",
        contact_email="recipient@example.com",
        contact_name="Test Recipient",
        customer_po_number="PO-42",
        item_total="100.00",
        shipping_total="18.00",
        tax_total="10.50",
        grand_total="128.50",
        order_date="2026-04-25",
        required_date="2026-04-27",
        ship_to="Test Recipient · 123 Main · Spokane, WA 99201",
        payment_type="purchase_order",
        lines=[_line()],
        fulfillment_routings=["SPO"],
    )
    defaults.update(overrides)
    return _OrderForEmail(**defaults)


# =========================================================================
# Composer (pure)
# =========================================================================


class TestComposeOrderConfirmation:
    def test_subject_includes_order_number(self):
        e = compose_order_confirmation(_order())
        assert "TTW0000123" in e.subject
        assert "confirmed" in e.subject.lower()

    def test_to_email_passed_through(self):
        e = compose_order_confirmation(_order(contact_email="alt@example.com"))
        assert e.to_email == "alt@example.com"

    def test_text_body_includes_grand_total(self):
        e = compose_order_confirmation(_order(grand_total="999.99"))
        assert "$999.99" in e.text_body

    def test_text_body_includes_each_line(self):
        e = compose_order_confirmation(_order(lines=[
            _line(sku="A1", qty=1), _line(sku="B2", qty=5),
        ]))
        assert "A1" in e.text_body
        assert "B2" in e.text_body

    def test_back_order_line_marked(self):
        e = compose_order_confirmation(_order(lines=[
            _line(sku="OOS-PART", qty=0, bo=3),
        ]))
        assert "BACK-ORDER" in e.text_body

    def test_no_po_number_renders_none(self):
        e = compose_order_confirmation(_order(customer_po_number=None))
        assert "(none)" in e.text_body

    def test_routings_listed(self):
        e = compose_order_confirmation(_order(fulfillment_routings=["SPO", "BOISE", "BO"]))
        assert "SPO" in e.text_body
        assert "BOISE" in e.text_body
        assert "BO" in e.text_body

    def test_empty_routings_shows_dash(self):
        e = compose_order_confirmation(_order(fulfillment_routings=[]))
        assert "Routing" in e.text_body
        # no crash; just renders the dash

    def test_anonymous_recipient_skipped_gracefully(self):
        e = compose_order_confirmation(_order(contact_name=None))
        assert "Hi," in e.text_body  # comma alone, no name


# =========================================================================
# Sender abstraction
# =========================================================================


class TestSenderDispatch:
    def test_console_sender_returns_ok(self):
        result = ConsoleSender().send(ComposedEmail(
            to_email="t@example.com", to_name=None, subject="x", text_body="y",
        ))
        assert result.ok is True
        assert result.provider == "console"

    def test_send_email_swallows_sender_exceptions(self, monkeypatch):
        class BoomSender:
            name = "boom"
            def send(self, email): raise RuntimeError("kaboom")
        monkeypatch.setattr("app.services.email_service._pick_sender", lambda: BoomSender())
        result = send_email(ComposedEmail(
            to_email="t@example.com", to_name=None, subject="x", text_body="y",
        ))
        assert result.ok is False
        assert result.error is not None
        assert "kaboom" in result.error

    def test_console_default_when_no_provider_configured(self, monkeypatch):
        # Force settings.email_provider="" → falls through to console
        from app.services import email_service
        from app.config import Settings

        class FakeSettings:
            email_provider = ""
            email_api_key = ""
            email_from = "x@x.com"

        monkeypatch.setattr(email_service, "get_settings", lambda: FakeSettings())
        sender = email_service._pick_sender()
        assert sender.name == "console"
