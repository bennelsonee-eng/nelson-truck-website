"""The PO rule for units for sale, pinned to real ERP entries.

Ben, 2026-09-25, looking at 56 public-agency orders: agency numbers are POs;
a person's name, what the job is, and placeholders are quotes. A customer with
an account has bought a unit only when the order carries a valid PO.
"""
import pytest

from app.services.unit_listings import classify_order, po_is_valid

# Group 1 -- real PO / agency numbers (Ben: "looks correct").
VALID = [
    "T099891", "7A1-367", "7A4-321", "7A4-602", "7A4-850", "7A4-603", "7A4-320",
    "1014553-Colin", "03A20801", "MA5420", "415430/MIKE",
    "A-0000302503/LISA", "A-000302503/MACKENZI", "A-000301677", "A-0000301677/ALEX",
    "A-0000301918/QAZZIAD", "A-0000300479/JENNIFE",
    "NEWPO47/MIKE", "NEW74/NICK", "PO New 74/E15", "04D00064 MARTINEZ",
    "FBS42", "FB-S-42", "1725/JOLE", "243KIM", "33113", "3273",
    # account-customer unit orders
    "20251079A", "20251079D", "20241070L", "20241076E", "20251073B", "PO 45553",
]

# Groups 2-4 -- names, what the job is, placeholders (Ben: "quotes only").
QUOTES = [
    "RON", "RON GREEN", "STEVEN", "JOHN/SHOP", "JOEL", "CONNOR", "CONOR",
    "FERRY UNIT", "ANUAL", "DPM-40/RON", "DUMP REPAIR", "PUBLIC WORKS", "SIGN TRUCK",
    "NEW BUCKET TRUCK", "ENCAMPMENT/JOHN", "TRUCK 8086", "EXCHANGE",
    "QUOTE MIKE", "QUOTE", "TBD", "V", "VISA", "INV#C59260",
    "BUCKET TRUCK/DEMO", "ON FILE QUOTE", "AERIAL", "DEMO", "ADJUSTMENT", "", None,
]


@pytest.mark.parametrize("po", VALID)
def test_real_po_numbers_count(po):
    assert po_is_valid(po), po


@pytest.mark.parametrize("po", QUOTES)
def test_names_jobs_and_placeholders_do_not(po):
    assert not po_is_valid(po), po


def test_account_customer_with_a_real_po_is_a_sale():
    cls, *_ = classify_order("S", "open", "1175", "AAA WA/INLAND @", "N10TH", "20251079D", 0)
    assert cls == "sale"


def test_account_customer_with_a_name_in_the_po_box_is_a_quote():
    cls, *_ = classify_order("S", "open", "71960", "WASHINGTON,UW FACILITIES", "N10TH", "RON", 0)
    assert cls == "quote"


def test_no_account_needs_money_down_even_with_a_po():
    cls, *_ = classify_order("S", "open", "76463", "DOT/WA, CORSON-UTILITIES", "VISA", "T099891", 0)
    assert cls == "quote"
    cls, *_ = classify_order("S", "open", "76463", "DOT/WA, CORSON-UTILITIES", "VISA", "T099891", 5000)
    assert cls == "sale"


def test_nelsons_own_accounts_are_internal():
    cls, *_ = classify_order("S", "open", "43850", "NELSON TRUCK EQUIPMENT CO INC", "N10TH", "AERIAL", 0)
    assert cls == "internal"
