"""IMS315 writer tests.

Verifies output matches the format reverse-engineered from production PHP
and 60 real-sample CSVs (per addendum 002 + 003).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.ims315 import (
    GeneratedCSV,
    OrderHeader,
    OrderLine,
    RoutingType,
    build_csv,
    filename_for,
)


# -------------------------------------------------------------------------
# Filename generation
# -------------------------------------------------------------------------


class TestFilenameFor:
    def test_spo_filename(self):
        assert filename_for(RoutingType.SPO, "3026053", 10) == "ORDERS_TITAN_SPO_3026053_10.CSV"

    def test_boise_filename(self):
        assert filename_for(RoutingType.BOISE, "3026166", 19) == "ORDERS_TITAN_BOISE_3026166_19.CSV"

    def test_nelson_filename(self):
        assert filename_for(RoutingType.NELSON, "3026322", 10) == "ORDERS_TITAN_NELSON_3026322_10.CSV"

    def test_bo_filename(self):
        assert filename_for(RoutingType.BO, "3026166", 10) == "ORDERS_TITAN_BO_3026166_10.CSV"


# -------------------------------------------------------------------------
# CSV content
# -------------------------------------------------------------------------


def _basic_header(order_num: str = "3026053", payment_type: str = "PO") -> OrderHeader:
    return OrderHeader(
        order_number=order_num,
        customer_id="106415",  # anonymous retail sentinel
        customer_name="HOLYLOH STUDIO",
        addr1="3775 STATE HWY 3 WEST",
        addr2="APT J4",
        city="TORRANCE",
        state="CA",
        zip="98312",
        email="justinjeong328@gmail.com",
        contact_name="WOOKHYUN JEONG",
        phone="714-929-0610",
        fax="0",
        customer_po_number="",
        payment_type=payment_type,
        order_date=date(2026, 1, 5),
        required_date=date(2026, 1, 7),
    )


class TestSimpleSpoOrder:
    def test_basic_format(self):
        header = _basic_header()
        lines = [
            OrderLine(part_number="DOM9600051030", quantity=1, unit_price=Decimal("149.99")),
        ]
        out = build_csv(
            header=header,
            lines=lines,
            routing=RoutingType.SPO,
            warehouse_code=10,
        )
        assert isinstance(out, GeneratedCSV)
        assert out.filename == "ORDERS_TITAN_SPO_3026053_10.CSV"
        assert out.content.endswith("\r\n")

        rows = out.content.strip().split("\r\n")
        # Header row + 1 product line = 2 rows
        assert len(rows) == 2

    def test_header_row_fields(self):
        header = _basic_header()
        lines = [OrderLine(part_number="DOM1", quantity=1, unit_price=Decimal("99.99"))]
        out = build_csv(header=header, lines=lines, routing=RoutingType.SPO, warehouse_code=10)
        h = out.content.split("\r\n")[0]
        fields = h.split(",")

        # Verify field-by-field
        assert fields[0] == "3026053"             # order #
        assert fields[1] == "1"                   # record type 1
        assert fields[2] == "106415"              # customer id
        assert fields[3] == "HOLYLOH STUDIO"      # customer name (uppercase, no commas)
        assert fields[4] == "3775 STATE HWY 3 WEST"
        assert fields[5] == "APT J4"
        assert fields[6] == "TORRANCE"
        assert fields[7] == "CA"
        assert fields[8] == "98312"
        assert fields[9] == "justinjeong328@gmail.com"  # email preserves case
        assert fields[10] == "WOOKHYUN JEONG"
        assert fields[11] == " 714-929-0610"      # leading space (PHP quirk)
        assert fields[12] == " 0"                  # fax with leading space
        # Ship-* fields default to billing-* when not set
        assert fields[13] == "3775 STATE HWY 3 WEST"
        assert fields[14] == "APT J4"
        assert fields[15] == "TORRANCE"
        assert fields[16] == "CA"
        assert fields[17] == "98312"
        assert fields[18] == ""                   # no PO number
        assert fields[19] == "01/05 PPD"          # ship via — order date + PPD
        assert fields[20] == "WEB ORDER"
        assert fields[21] == "PO"
        # Money fields all zero for this order
        assert fields[22] == "0"
        assert fields[23] == "0"
        assert fields[24] == "0"
        assert fields[25] == "0"
        assert fields[26] == "0"
        assert fields[27] == "01/05/2026"         # order date with slashes
        assert fields[28] == "01/07/2026"         # required date
        assert fields[29] == "3026053"            # reference = order #
        assert fields[30] == ""                   # sales rep empty

    def test_detail_row_format(self):
        header = _basic_header()
        lines = [OrderLine(part_number="CURT13323", quantity=1, backorder_quantity=1,
                           unit_price=Decimal("122.56"))]
        out = build_csv(header=header, lines=lines, routing=RoutingType.SPO, warehouse_code=10)
        d = out.content.split("\r\n")[1]
        fields = d.split(",")

        assert fields[0] == "3026053"   # order #
        assert fields[1] == "2"         # record type 2
        assert fields[2] == "CURT13323"
        assert fields[3] == ""          # description blank
        assert fields[4] == "1"         # qty
        assert fields[5] == "1"         # backorder qty
        assert fields[6] == "$122.56"   # unit price with $


class TestSpecialLines:
    def test_freight_line(self):
        header = _basic_header()
        lines = [OrderLine(part_number="DOM1", quantity=1, unit_price=Decimal("100"))]
        out = build_csv(
            header=header,
            lines=lines,
            routing=RoutingType.SPO,
            warehouse_code=10,
            freight_amount=Decimal("29.31"),
        )
        rows = out.content.strip().split("\r\n")
        assert len(rows) == 3  # header + product + freight
        freight = rows[2].split(",")
        assert freight[2] == "FREIGHT"
        assert freight[3] == ""
        assert freight[4] == "1"
        assert freight[6] == "$29.31"

    def test_discount_line_negative(self):
        header = _basic_header()
        lines = [OrderLine(part_number="DOM1", quantity=1, unit_price=Decimal("100"))]
        out = build_csv(
            header=header,
            lines=lines,
            routing=RoutingType.SPO,
            warehouse_code=10,
            discount_amount=Decimal("-14.99"),
        )
        rows = out.content.strip().split("\r\n")
        assert len(rows) == 3
        discount = rows[2].split(",")
        assert discount[2] == "DISCOUNT"
        assert discount[6] == "$-14.99"

    def test_all_three_synthetic_lines(self):
        header = _basic_header()
        lines = [OrderLine(part_number="DOM1", quantity=1, unit_price=Decimal("100"))]
        out = build_csv(
            header=header,
            lines=lines,
            routing=RoutingType.SPO,
            warehouse_code=10,
            freight_amount=Decimal("10.00"),
            discount_amount=Decimal("-5.00"),
            handling_amount=Decimal("2.50"),
        )
        rows = out.content.strip().split("\r\n")
        assert len(rows) == 5  # header + product + freight + discount + handling


class TestRoutingShipVia:
    def test_spo_ship_via_is_dated_ppd(self):
        header = _basic_header()
        lines = [OrderLine(part_number="X")]
        out = build_csv(header=header, lines=lines, routing=RoutingType.SPO, warehouse_code=10)
        ship_via = out.content.split("\r\n")[0].split(",")[19]
        assert ship_via == "01/05 PPD"

    def test_boise_ship_via_is_dated_ppd(self):
        header = _basic_header(order_num="3026166")
        lines = [OrderLine(part_number="X")]
        out = build_csv(header=header, lines=lines, routing=RoutingType.BOISE, warehouse_code=19)
        ship_via = out.content.split("\r\n")[0].split(",")[19]
        assert ship_via == "01/05 PPD"

    def test_nelson_ship_via_is_pal(self):
        header = _basic_header(order_num="3026322")
        lines = [OrderLine(part_number="X")]
        out = build_csv(header=header, lines=lines, routing=RoutingType.NELSON, warehouse_code=10)
        ship_via = out.content.split("\r\n")[0].split(",")[19]
        assert ship_via == "PAL"

    def test_bo_ship_via_is_back_ordered(self):
        header = _basic_header(order_num="3026166")
        lines = [OrderLine(part_number="X", backorder_quantity=1)]
        out = build_csv(header=header, lines=lines, routing=RoutingType.BO, warehouse_code=10)
        ship_via = out.content.split("\r\n")[0].split(",")[19]
        assert ship_via == "BACK ORDERED"


class TestSpokaneTaxBehavior:
    """Per addendum 003: only Spokane file passes tax info; others = 0."""

    def test_spokane_with_tax(self):
        header = OrderHeader(
            order_number="9999", customer_id="780023",
            customer_name="TEST CUSTOMER", addr1="1 MAIN ST", addr2="",
            city="SPOKANE", state="WA", zip="99201",
            email="test@example.com", contact_name="JANE DOE",
            phone="509-555-1212", fax="0",
            tax_amount=Decimal("12.50"), tax_rate_x1000=87,  # 8.7%
            order_date=date(2026, 4, 25),
        )
        lines = [OrderLine(part_number="X", quantity=1, unit_price=Decimal("143.50"))]
        out = build_csv(header=header, lines=lines, routing=RoutingType.SPO, warehouse_code=10)
        fields = out.content.split("\r\n")[0].split(",")
        assert fields[24] == "$12.50"   # tax_amount with $
        assert fields[25] == "87"       # tax_rate_x1000

    def test_non_spokane_zero_tax(self):
        # Even if tax_amount provided to a Boise file, caller passes 0 (per PHP)
        header = OrderHeader(
            order_number="9999", customer_id="780023",
            customer_name="TEST CUSTOMER", addr1="1 MAIN ST", addr2="",
            city="BOISE", state="ID", zip="83705",
            email="test@example.com", contact_name="JANE DOE",
            phone="208-555-1212", fax="0",
            tax_amount=Decimal("0"), tax_rate_x1000=0,
            order_date=date(2026, 4, 25),
        )
        lines = [OrderLine(part_number="X", quantity=1, unit_price=Decimal("143.50"))]
        out = build_csv(header=header, lines=lines, routing=RoutingType.BOISE, warehouse_code=19)
        fields = out.content.split("\r\n")[0].split(",")
        assert fields[24] == "0"  # tax field is "0" not "$0.00" when zero


class TestRealSample:
    """Spot-check against the structure of a known production order.

    Production sample (from addendum 002):
      3026053,1,106415,HOLYLOH STUDIO,3775 STATE HWY 3 WEST,APT J4,TORRANCE,CA,98312,...,01/05 PPD,WEB ORDER,PO,...
      3026053,2,DOM9600051030,,1,0,$149.99
      3026053,2,FREIGHT,,1,0,$29.31
      3026053,2,DISCOUNT,,1,0,$-14.99
    """

    def test_full_round_trip(self):
        header = _basic_header()
        lines = [OrderLine(part_number="DOM9600051030", quantity=1, unit_price=Decimal("149.99"))]
        out = build_csv(
            header=header,
            lines=lines,
            routing=RoutingType.SPO,
            warehouse_code=10,
            freight_amount=Decimal("29.31"),
            discount_amount=Decimal("-14.99"),
        )
        # Sanity checks
        assert "ORDERS_TITAN_SPO_3026053_10.CSV" == out.filename
        assert "3026053,1,106415,HOLYLOH STUDIO" in out.content
        assert "3026053,2,DOM9600051030,,1,0,$149.99" in out.content
        assert "3026053,2,FREIGHT,,1,0,$29.31" in out.content
        assert "3026053,2,DISCOUNT,,1,0,$-14.99" in out.content
