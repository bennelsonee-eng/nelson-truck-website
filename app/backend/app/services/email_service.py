"""Transactional email service.

Phase 1 supports three modes selected by `EMAIL_PROVIDER` config:

  * `console`   — log emails to stdout (default for tests / dev w/o creds).
                  Useful when you just want to see what would have gone out.
  * `maildev`   — POST to local maildev SMTP catcher (port 1025) — same
                  Docker container we already run for cart/auth dev.
  * `postmark`  — real Postmark API call (Phase 1.5 once API key lands).

The composer (`compose_order_confirmation`) is a pure function so we can unit
test the body without sending anything.

The send function returns a `SendResult` dataclass — never raises so the
checkout flow can keep going even if email is broken.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable, Protocol

from app.config import get_settings


__all__ = [
    "ComposedEmail",
    "EmailAttachment",
    "SendResult",
    "compose_order_confirmation",
    "compose_rma_request_email",
    "compose_customer_link_request_email",
    "compose_customer_link_decision_email",
    "rma_for_email",
    "send_email",
    "ConsoleSender",
    "MailDevSender",
    "AuthSmtpSender",
]


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailAttachment:
    """One file attachment (Phase 1: RMA photo uploads).

    content_type uses standard MIME (e.g. 'image/jpeg', 'image/png'). content
    is the raw bytes — kept in-memory; not persisted anywhere except as part
    of the outbound email.
    """

    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class ComposedEmail:
    to_email: str
    to_name: str | None
    subject: str
    text_body: str
    html_body: str | None = None
    reply_to: str | None = None
    attachments: tuple[EmailAttachment, ...] = ()


def _build_mime_message(email: ComposedEmail, from_addr: str) -> MIMEMultipart:
    """Build the MIME structure from a ComposedEmail.

    If attachments exist, wraps text/html in a multipart/alternative inside an
    outer multipart/mixed with the attachments. Otherwise emits a plain
    multipart/alternative to match the historical structure.
    """
    if email.attachments:
        outer = MIMEMultipart("mixed")
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(email.text_body, "plain"))
        if email.html_body:
            alt.attach(MIMEText(email.html_body, "html"))
        outer.attach(alt)
        for att in email.attachments:
            maintype, _, subtype = att.content_type.partition("/")
            part = MIMEBase(maintype or "application", subtype or "octet-stream")
            part.set_payload(att.content)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", "attachment", filename=att.filename
            )
            outer.attach(part)
        msg = outer
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(email.text_body, "plain"))
        if email.html_body:
            msg.attach(MIMEText(email.html_body, "html"))

    msg["Subject"] = email.subject
    msg["From"] = from_addr
    msg["To"] = email.to_email
    if email.reply_to:
        msg["Reply-To"] = email.reply_to
    return msg


@dataclass(frozen=True)
class SendResult:
    ok: bool
    provider: str
    message_id: str | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)


# =========================================================================
# Composers — pure functions, easy to unit-test
# =========================================================================


@dataclass(frozen=True)
class _OrderLineForEmail:
    sku: str
    description: str
    quantity: int
    backorder_quantity: int
    unit_price: str
    line_total: str
    routing: str | None


@dataclass(frozen=True)
class _OrderForEmail:
    web_order_number: str
    contact_email: str
    contact_name: str | None
    customer_po_number: str | None
    item_total: str
    shipping_total: str
    tax_total: str
    grand_total: str
    order_date: str
    required_date: str | None
    ship_to: str       # one-line formatted "name · addr · city, ST zip"
    payment_type: str
    lines: list[_OrderLineForEmail]
    fulfillment_routings: list[str]   # e.g. ["SPO", "NELSON"]


def compose_order_confirmation(order: _OrderForEmail) -> ComposedEmail:
    """Pure: build the customer-facing order confirmation email."""
    subject = f"Nelson Truck order {order.web_order_number} confirmed"

    lines_text = "\n".join(
        f"  {l.quantity + l.backorder_quantity:>3} x {l.sku:<20} {l.description[:40]:<40} "
        f"{l.unit_price:>10}  {l.line_total:>10}"
        + (f"  [BACK-ORDER]" if l.backorder_quantity > 0 else "")
        for l in order.lines
    )

    routing_text = ", ".join(order.fulfillment_routings) if order.fulfillment_routings else "—"

    text_body = f"""\
Hi{(' ' + order.contact_name) if order.contact_name else ''},

Thanks for your order!  Here's a confirmation for your records.

Order:        {order.web_order_number}
Placed:       {order.order_date}
Ship by:      {order.required_date or 'standard ground'}
PO number:    {order.customer_po_number or '(none)'}
Payment:      {order.payment_type.replace('_', ' ')}
Routing:      {routing_text}
Ship to:      {order.ship_to}

Items
-----
{lines_text}

Totals
------
Items:        ${order.item_total}
Shipping:     ${order.shipping_total}
Tax:          ${order.tax_total}
Grand total:  ${order.grand_total}

We've forwarded the routing files to our fulfillment team.  You'll get a
shipment notification once tracking is available.  Reply to this email or call
509-534-5010 if you have questions.

— Nelson Truck Equipment
"""

    return ComposedEmail(
        to_email=order.contact_email,
        to_name=order.contact_name,
        subject=subject,
        text_body=text_body,
    )


def order_for_email(order, lines: Iterable, fulfillments: Iterable, ship_to_str: str) -> _OrderForEmail:
    """Convert an SQLAlchemy Order + its lines/fulfillments into the email-friendly shape."""
    return _OrderForEmail(
        web_order_number=order.web_order_number,
        contact_email=order.contact_email or "",
        contact_name=(order.shipping_name or order.billing_name or None),
        customer_po_number=order.customer_po_number,
        item_total=str(order.item_total_usd.quantize(__import__("decimal").Decimal("0.01"))),
        shipping_total=str(order.shipping_total_usd.quantize(__import__("decimal").Decimal("0.01"))),
        tax_total=str(order.tax_total_usd.quantize(__import__("decimal").Decimal("0.01"))),
        grand_total=str(order.grand_total_usd.quantize(__import__("decimal").Decimal("0.01"))),
        order_date=order.order_date.isoformat() if order.order_date else "",
        required_date=order.required_date.isoformat() if order.required_date else None,
        ship_to=ship_to_str,
        payment_type=order.payment_type.value if hasattr(order.payment_type, "value") else str(order.payment_type),
        lines=[
            _OrderLineForEmail(
                sku=l.sku,
                description=l.description or "",
                quantity=l.quantity,
                backorder_quantity=l.backorder_quantity,
                unit_price=str(l.unit_price_usd.quantize(__import__("decimal").Decimal("0.01"))),
                line_total=str((l.unit_price_usd * (l.quantity + l.backorder_quantity)).quantize(__import__("decimal").Decimal("0.01"))),
                routing=None,
            )
            for l in lines if not (l.is_freight or l.is_discount or l.is_handling)
        ],
        fulfillment_routings=[f.routing_type for f in fulfillments],
    )


# =========================================================================
# RMA email — per SOW A4.31, emails sales@nelsontruck.com with photo attachments
# =========================================================================

RMA_INBOX_EMAIL = "sales@nelsontruck.com"


@dataclass(frozen=True)
class _RmaLineForEmail:
    sku: str
    description: str
    qty_ordered: int
    qty_to_return: int
    reason_label: str
    line_notes: str | None


@dataclass(frozen=True)
class _RmaForEmail:
    rma_id: int
    web_order_number: str
    customer_po_number: str | None
    customer_name: str
    customer_number: str
    location_label: str | None
    requested_by_name: str
    requested_by_email: str
    requested_by_phone: str | None
    order_date: str
    notes: str | None
    lines: list[_RmaLineForEmail]
    photo_summary: list[str]  # one "filename (12.3 KB image/jpeg)" line per photo


_RMA_REASON_LABELS = {
    "defective_doa": "Defective / DOA",
    "wrong_part_shipped": "Wrong part shipped",
    "damaged_shipping": "Damaged in shipping",
    "customer_error": "Customer error / changed mind",
    "other": "Other",
}


def compose_rma_request_email(
    rma: _RmaForEmail,
    attachments: tuple[EmailAttachment, ...] = (),
) -> ComposedEmail:
    """Pure: build the RMA request email destined for sales@nelsontruck.com.

    Reply-To is set to the jobber's email so sales can reply directly.
    """
    subject = (
        f"RMA Request #{rma.rma_id} — order {rma.web_order_number} "
        f"from {rma.customer_name}"
    )

    lines_text = "\n".join(
        f"  {l.qty_to_return:>3} of {l.qty_ordered:<3} x {l.sku:<20} "
        f"{l.description[:40]:<40} — {l.reason_label}"
        + (f"\n      Note: {l.line_notes}" if l.line_notes else "")
        for l in rma.lines
    )

    photo_text = "\n".join(f"  • {p}" for p in rma.photo_summary) if rma.photo_summary else "  (none)"

    notes_text = f"\n\nJobber notes:\n{rma.notes}\n" if rma.notes else ""

    text_body = f"""\
RMA Request submitted via Nelson Truck website

RMA reference:  #{rma.rma_id}
Order:          {rma.web_order_number}
PO number:      {rma.customer_po_number or '(none)'}
Order date:     {rma.order_date}

Customer:       {rma.customer_name} (FACS #{rma.customer_number})
Location:       {rma.location_label or '(primary)'}

Requested by:   {rma.requested_by_name}
                {rma.requested_by_email}
                {rma.requested_by_phone or '(no phone on file)'}

Lines to return
---------------
{lines_text}

Photos attached
---------------
{photo_text}
{notes_text}
Reply to this email or call 509-534-5010 to coordinate the return.

— Nelson Truck website
"""

    return ComposedEmail(
        to_email=RMA_INBOX_EMAIL,
        to_name="Nelson Sales",
        subject=subject,
        text_body=text_body,
        reply_to=rma.requested_by_email,
        attachments=attachments,
    )


def rma_for_email(
    rma,
    order,
    customer,
    user,
    location_label: str | None,
) -> _RmaForEmail:
    """Convert SQLAlchemy RmaRequest + related rows into the email-friendly shape."""

    def _fmt_bytes(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n / (1024 * 1024):.2f} MB"

    photo_summary = []
    for p in (rma.photo_metadata or []):
        photo_summary.append(
            f"{p.get('filename', '?')} ({_fmt_bytes(p.get('byte_size', 0))} {p.get('content_type', '?')})"
        )

    # Build line views: pair RmaLine with its OrderLine for description/qty context.
    order_lines_by_id = {ol.id: ol for ol in order.lines}
    lines = []
    for rl in rma.lines:
        ol = order_lines_by_id.get(rl.order_line_id)
        reason_key = rl.reason.value if hasattr(rl.reason, "value") else str(rl.reason)
        lines.append(
            _RmaLineForEmail(
                sku=ol.sku if ol else "(unknown)",
                description=(ol.description if ol and ol.description else "") or "",
                qty_ordered=ol.quantity if ol else 0,
                qty_to_return=rl.qty_to_return,
                reason_label=_RMA_REASON_LABELS.get(reason_key, reason_key),
                line_notes=rl.line_notes,
            )
        )

    return _RmaForEmail(
        rma_id=rma.id,
        web_order_number=order.web_order_number,
        customer_po_number=order.customer_po_number,
        customer_name=customer.name if customer else "(unknown)",
        customer_number=customer.customer_number if customer else "?",
        location_label=location_label,
        requested_by_name=(user.display_name or user.email) if user else "(anonymous)",
        requested_by_email=user.email if user else "",
        requested_by_phone=getattr(user, "phone", None) if user else None,
        order_date=order.order_date.isoformat() if order.order_date else "",
        notes=rma.notes,
        lines=lines,
        photo_summary=photo_summary,
    )


# =========================================================================
# Customer link request — sales@nelsontruck.com confirms before linkage
# =========================================================================


SALES_INBOX_EMAIL = "sales@nelsontruck.com"


def compose_customer_link_request_email(
    *,
    user_email: str,
    user_display_name: str | None,
    user_id: int,
    user_phone: str | None,
    requested_customer_number: str,
    billing_zip: str | None,
    additional_info: str | None,
    link_request_id: int,
) -> ComposedEmail:
    """Pure: build the email asking sales to verify a User → Customer link.

    Until sales confirms and an admin approves, the User has no customer_id
    and therefore no jobber pricing — closing the self-link exploit.
    """
    subject = (
        f"Account-link request #{link_request_id} — "
        f"customer {requested_customer_number}"
    )

    info_text = f"\nAdditional info from requester:\n{additional_info}\n" if additional_info else ""

    text_body = f"""\
A website user has requested to link their account to a Nelson customer record.

Link-request ID:    #{link_request_id}
Requesting user:    {user_display_name or '(no display name)'} <{user_email}>
                    user_id={user_id}{f', phone: {user_phone}' if user_phone else ''}

Requested customer: {requested_customer_number}
Billing ZIP claim:  {billing_zip or '(not provided)'}
{info_text}
Action required: confirm this user is authorized to access the requested
customer record (phone call, in-person check, etc.) and then approve via
the CMS at /admin/customer-link-requests/{link_request_id}. Once approved,
the user's account is linked and they gain jobber/dealer/muni pricing.

If the request looks fraudulent, reject it from the same screen.

— Nelson Truck website
"""

    return ComposedEmail(
        to_email=SALES_INBOX_EMAIL,
        to_name="Nelson Sales",
        subject=subject,
        text_body=text_body,
        reply_to=user_email,
    )


def compose_customer_link_decision_email(
    *,
    user_email: str,
    user_display_name: str | None,
    requested_customer_number: str,
    link_request_id: int,
    approved: bool,
    review_notes: str | None,
) -> ComposedEmail:
    """Notify the requester after sales/admin has decided on their link request."""
    verdict = "approved" if approved else "rejected"
    subject = (
        f"Your Nelson account link request "
        f"(#{link_request_id}) was {verdict}"
    )

    if approved:
        body = f"""\
Hi{(' ' + user_display_name) if user_display_name else ''},

Your request to link your Nelson account to customer #{requested_customer_number}
has been approved. Sign in to nelsontruck.com and you'll see your jobber /
dealer pricing on the catalog and your account page.

If anything looks off, reply to this email — we're happy to help.

— Nelson Truck Equipment
"""
    else:
        body = f"""\
Hi{(' ' + user_display_name) if user_display_name else ''},

We were unable to verify your request to link your Nelson account to customer
#{requested_customer_number}. Common reasons: the customer number doesn't
match what's on file, or the billing zip we have doesn't match the one
submitted.

{('Note from sales: ' + review_notes) if review_notes else 'Reply to this email or call 509-534-5010 if you would like to retry.'}

— Nelson Truck Equipment
"""

    return ComposedEmail(
        to_email=user_email,
        to_name=user_display_name,
        subject=subject,
        text_body=body,
        reply_to=SALES_INBOX_EMAIL,
    )


# =========================================================================
# Senders
# =========================================================================


class _Sender(Protocol):
    def send(self, email: ComposedEmail) -> SendResult: ...


class ConsoleSender:
    """Just log the email — used for tests + dev mode without SMTP."""

    name = "console"

    def send(self, email: ComposedEmail) -> SendResult:
        att = f" [+{len(email.attachments)} attachment(s)]" if email.attachments else ""
        log.info(
            "[email.console] To: %s\nSubject: %s%s\n---\n%s",
            email.to_email, email.subject, att, email.text_body,
        )
        return SendResult(ok=True, provider=self.name)


class MailDevSender:
    """Send via local maildev SMTP catcher (Docker compose service)."""

    name = "maildev"

    def __init__(self, host: str = "localhost", port: int = 1025, from_addr: str = "sales@nelsontruck.com"):
        self.host = host
        self.port = port
        self.from_addr = from_addr

    def send(self, email: ComposedEmail) -> SendResult:
        try:
            msg = _build_mime_message(email, self.from_addr)
            with smtplib.SMTP(self.host, self.port, timeout=5) as smtp:
                smtp.send_message(msg)
            return SendResult(ok=True, provider=self.name)
        except Exception as e:
            log.exception("[email.maildev] send failed")
            return SendResult(ok=False, provider=self.name, error=str(e))


class AuthSmtpSender:
    """Authenticated SMTP sender — works with any provider that supports
    submission ports 587 (STARTTLS) or 465 (SMTPS).  Currently used for
    TigerTech (mail.tigertech.net) which hosts winterwatch@titantruck.com,
    but the same class works for any host/port/user combo.

    Config (settings):
        smtp_host        - mail.tigertech.net
        smtp_port        - 587 (STARTTLS) or 465 (implicit TLS)
        smtp_user        - winterwatch@titantruck.com
        smtp_password    - <secret>
        email_from       - winterwatch@titantruck.com (visible From header)
        smtp_use_tls     - True for 587 STARTTLS, False for 465 implicit TLS
    """

    name = "smtp"

    def __init__(self, host: str, port: int, user: str, password: str,
                 from_addr: str, use_starttls: bool = True):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.use_starttls = use_starttls

    def send(self, email: ComposedEmail) -> SendResult:
        try:
            msg = _build_mime_message(email, self.from_addr)
            if self.use_starttls:
                # Submission port 587 — connect plaintext, then STARTTLS, then auth
                with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(self.user, self.password)
                    smtp.send_message(msg)
            else:
                # Implicit TLS port 465 — wrapped in TLS from the first byte
                with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as smtp:
                    smtp.login(self.user, self.password)
                    smtp.send_message(msg)
            return SendResult(ok=True, provider=self.name)
        except Exception as e:
            log.exception("[email.smtp] send failed via %s:%s", self.host, self.port)
            return SendResult(ok=False, provider=self.name, error=str(e))


def _pick_sender() -> _Sender:
    settings = get_settings()
    provider = (settings.email_provider or "console").lower()
    if provider == "maildev":
        return MailDevSender(from_addr=settings.email_from or "sales@nelsontruck.com")
    if provider == "smtp":
        # Real SMTP with auth — TigerTech, Postmark-SMTP, SendGrid-SMTP, etc.
        if not (settings.smtp_host and settings.smtp_user and settings.smtp_password):
            log.warning("EMAIL_PROVIDER=smtp but smtp_host/user/password not all set — falling back to console")
            return ConsoleSender()
        return AuthSmtpSender(
            host=settings.smtp_host,
            port=settings.smtp_port or 587,
            user=settings.smtp_user,
            password=settings.smtp_password,
            from_addr=settings.email_from or settings.smtp_user,
            use_starttls=(settings.smtp_port or 587) != 465,
        )
    if provider == "postmark":
        # Phase 1.5 — drop in real Postmark API client when key lands
        if not settings.email_api_key:
            log.warning("EMAIL_PROVIDER=postmark but no API key configured — falling back to console")
            return ConsoleSender()
        # Until then: log
        return ConsoleSender()
    return ConsoleSender()


def send_email(email: ComposedEmail) -> SendResult:
    """Send an email via whatever provider is configured.  Never raises."""
    sender = _pick_sender()
    try:
        return sender.send(email)
    except Exception as e:
        log.exception("[email] sender raised unexpectedly")
        return SendResult(ok=False, provider=getattr(sender, "name", "unknown"), error=str(e))
