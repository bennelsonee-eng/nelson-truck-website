"""build_gift_card_xlsx.py — Gift card activity analysis for Titan (TTE).

Pulls 2025 + all-history gift-card transactions from tte_rcv390 (TigerTech
MySQL), plus current inventory snapshot from tte_inv_days, then builds a
4-sheet Excel report with the headline finding visible on sheet 1.

Output: app/data/reports/titan_gift_card_analysis_2025.xlsx
"""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps" / "gift_card_data.json"
OUT = Path(__file__).resolve().parent.parent / "data" / "reports" / "titan_gift_card_analysis_2025.xlsx"
ARIAL = "Arial"


def _styled_header(c, fill="1F4E78"):
    c.font = Font(name=ARIAL, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", start_color=fill)
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _bordered(c):
    thin = Side(style="thin", color="CCCCCC")
    c.border = Border(left=thin, right=thin, top=thin, bottom=thin)


def main() -> None:
    data = json.loads(DATA_FILE.read_text())
    wb = Workbook()

    # ------------------------------------------------------------------
    # Sheet 1: Findings (overview)
    # ------------------------------------------------------------------
    ws = wb.active
    ws.title = "Findings"
    ws["A1"] = "Titan Gift Card Activity — 2025 Analysis"
    ws["A1"].font = Font(name=ARIAL, bold=True, size=16)
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.merge_cells("A1:F1")
    ws.row_dimensions[1].height = 28

    ws["A2"] = "Source: TigerTech MySQL — tte_rcv390 (sales line history) + tte_inv_days (current inventory)"
    ws["A2"].font = Font(name=ARIAL, italic=True, color="666666")
    ws.merge_cells("A2:F2")

    ws["A4"] = "HEADLINE"
    ws["A4"].font = Font(name=ARIAL, bold=True, size=12, color="FFFFFF")
    ws["A4"].fill = PatternFill("solid", start_color="C00000")
    ws["A4"].alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A4:F4")

    headlines = [
        "Titan's gift card program is essentially dormant in 2025.",
        "",
        "• 3 transactions all year, only 1 of those a real card sale ($500 to cust #69 on 2025-01-23)",
        "• The other 2 (Oct 7) were a wash pair on the same doc (#1314571) — $50 sold + $50 returned, net $0",
        "• Zero net revenue recognized through 2025 ext_sales (cards are deferred revenue at sale)",
        "• Compare to peak years: 2019 had 9 redemption-side line items (net -$202)",
        "",
        "Current 'on hand' is phantom inventory:",
        "• 5,016 units across 34 SKUs, all at gl_cost=$0",
        "• GIFTCARD150 / GIFTCARD500 / GIFTCARD250 / GIFTCARD50 each carry exactly 999 (seed value)",
        "• Plus a long tail of individual 1-unit lots (cards still outstanding per serial)",
        "",
        "Interpretation:",
        "• The 999-per-SKU seed means TigerTech treats each gift-card denomination as a phantom",
        "   product with a high starting balance; real movement is tracked by serial number per card.",
        "• Active selling looks like it stopped in 2019. The few post-2020 transactions are corrections.",
        "",
        "Recommendations:",
        "1. Treat existing gift card inventory as phantom — do NOT migrate the 5,016 'units' to the website.",
        "2. If we want to re-launch gift cards on the new site, build it native to the new platform",
        "   (Stripe gift cards or a simple credit-balance table) — don't try to bolt onto TigerTech.",
        "3. Audit the open balance of redeemable cards from 2019 — there's an unaccrued liability.",
    ]
    for i, line in enumerate(headlines, start=6):
        c = ws.cell(row=i, column=1, value=line)
        c.font = Font(name=ARIAL, size=11, bold=line.startswith(("HEADLINE", "Current", "Interpretation", "Recommendations")))
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=6)

    for col, w in (("A", 18), ("B", 14), ("C", 14), ("D", 14), ("E", 14), ("F", 14)):
        ws.column_dimensions[col].width = w

    # ------------------------------------------------------------------
    # Sheet 2: 2025 Transactions (the full year)
    # ------------------------------------------------------------------
    ws2 = wb.create_sheet("2025 Transactions")
    cols = [
        ("date", "Date", 14, "left"),
        ("ourparts_num", "SKU", 18, "left"),
        ("cust_id", "Cust ID", 10, "center"),
        ("store", "Store", 8, "center"),
        ("sales_rep", "Rep #", 8, "center"),
        ("quantity", "Qty", 8, "right"),
        ("ext_sales", "Ext Sales", 12, "currency"),
        ("trans_amount", "Trans Amount", 14, "currency"),
        ("trans_type", "Trans Type", 10, "center"),
        ("doc_type", "Doc Type", 10, "center"),
        ("doc_num", "Doc #", 12, "left"),
    ]
    for j, (_, h, w, _) in enumerate(cols, start=1):
        c = ws2.cell(row=1, column=j, value=h)
        _styled_header(c); _bordered(c)
        ws2.column_dimensions[get_column_letter(j)].width = w
    ws2.row_dimensions[1].height = 26

    for i, r in enumerate(data["txns_2025"], start=2):
        for j, (key, _, _, fmt) in enumerate(cols, start=1):
            v = r.get(key)
            if key in ("quantity", "ext_sales", "trans_amount") and v is not None:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    pass
            c = ws2.cell(row=i, column=j, value=v)
            c.font = Font(name=ARIAL)
            if fmt == "currency":
                c.number_format = "$#,##0.00;($#,##0.00);-"
                c.alignment = Alignment(horizontal="right", vertical="center")
            elif fmt == "right":
                c.alignment = Alignment(horizontal="right", vertical="center")
            elif fmt == "center":
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")
            _bordered(c)

    # Totals
    last_data = len(data["txns_2025"]) + 1
    total_row = last_data + 1
    ws2.cell(row=total_row, column=1, value="2025 TOTALS").font = Font(name=ARIAL, bold=True)
    ws2.cell(row=total_row, column=1).alignment = Alignment(horizontal="right", vertical="center")
    for col, letter in ((6, "F"), (7, "G"), (8, "H")):
        c = ws2.cell(row=total_row, column=col,
                     value=f"=SUM({letter}2:{letter}{last_data})")
        c.font = Font(name=ARIAL, bold=True)
        c.number_format = "$#,##0.00;($#,##0.00);-" if col != 6 else "0"
        c.alignment = Alignment(horizontal="right", vertical="center")
        c.fill = PatternFill("solid", start_color="DDEBF7")
        _bordered(c)

    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{last_data}"

    # ------------------------------------------------------------------
    # Sheet 3: Multi-Year Trend
    # ------------------------------------------------------------------
    ws3 = wb.create_sheet("Multi-Year Trend")
    yr_cols = [
        ("yr", "Year", 10, "center"),
        ("txns", "Transactions", 14, "right"),
        ("skus", "Distinct SKUs", 14, "right"),
        ("sold", "Cards Sold (qty)", 16, "right"),
        ("redeemed", "Cards Redeemed (qty)", 18, "right"),
        ("net_revenue", "Net Ext Sales", 14, "currency"),
    ]
    for j, (_, h, w, _) in enumerate(yr_cols, start=1):
        c = ws3.cell(row=1, column=j, value=h)
        _styled_header(c); _bordered(c)
        ws3.column_dimensions[get_column_letter(j)].width = w
    ws3.row_dimensions[1].height = 26

    for i, r in enumerate(data["yearly_summary"], start=2):
        for j, (key, _, _, fmt) in enumerate(yr_cols, start=1):
            v = r.get(key)
            if v is not None and key != "yr":
                try:
                    v = float(v) if "." in str(v) or key in ("net_revenue",) else int(v)
                except (TypeError, ValueError):
                    pass
            c = ws3.cell(row=i, column=j, value=v)
            c.font = Font(name=ARIAL)
            if fmt == "currency":
                c.number_format = "$#,##0.00;($#,##0.00);-"
                c.alignment = Alignment(horizontal="right", vertical="center")
            elif fmt == "right":
                c.alignment = Alignment(horizontal="right", vertical="center")
            else:
                c.alignment = Alignment(horizontal="center", vertical="center")
            _bordered(c)
    ws3.freeze_panes = "A2"

    # ------------------------------------------------------------------
    # Sheet 4: Lifetime All-History Transactions
    # ------------------------------------------------------------------
    ws4 = wb.create_sheet("All History")
    h_cols = [
        ("date", "Date", 14, "left"),
        ("ourparts_num", "SKU", 22, "left"),
        ("cust_id", "Cust ID", 10, "center"),
        ("store", "Store", 8, "center"),
        ("sales_rep", "Rep #", 8, "center"),
        ("quantity", "Qty", 8, "right"),
        ("ext_sales", "Ext Sales", 12, "currency"),
        ("trans_amount", "Trans Amount", 14, "currency"),
        ("trans_type", "Trans", 8, "center"),
        ("doc_type", "Doc", 8, "center"),
        ("doc_num", "Doc #", 12, "left"),
    ]
    for j, (_, h, w, _) in enumerate(h_cols, start=1):
        c = ws4.cell(row=1, column=j, value=h)
        _styled_header(c); _bordered(c)
        ws4.column_dimensions[get_column_letter(j)].width = w
    ws4.row_dimensions[1].height = 26

    for i, r in enumerate(data["txns_all_history"], start=2):
        for j, (key, _, _, fmt) in enumerate(h_cols, start=1):
            v = r.get(key)
            if key in ("quantity", "ext_sales", "trans_amount") and v is not None:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    pass
            c = ws4.cell(row=i, column=j, value=v)
            c.font = Font(name=ARIAL)
            if fmt == "currency":
                c.number_format = "$#,##0.00;($#,##0.00);-"
                c.alignment = Alignment(horizontal="right", vertical="center")
            elif fmt == "right":
                c.alignment = Alignment(horizontal="right", vertical="center")
            elif fmt == "center":
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")
            _bordered(c)
    ws4.freeze_panes = "A2"
    ws4.auto_filter.ref = f"A1:{get_column_letter(len(h_cols))}{len(data['txns_all_history']) + 1}"

    # ------------------------------------------------------------------
    # Sheet 5: Current Inventory (phantom stock)
    # ------------------------------------------------------------------
    ws5 = wb.create_sheet("Current Inventory")
    ws5["A1"] = "Note: TigerTech seeds gift card SKUs at 999 each as phantom inventory."
    ws5["A1"].font = Font(name=ARIAL, italic=True, color="C00000")
    ws5.merge_cells("A1:D1")
    inv_cols = [("ourparts_num", "SKU", 22), ("onhand", "On Hand", 12),
                ("available", "Available", 12), ("warehouse", "Warehouse", 12)]
    for j, (_, h, w) in enumerate(inv_cols, start=1):
        c = ws5.cell(row=2, column=j, value=h)
        _styled_header(c); _bordered(c)
        ws5.column_dimensions[get_column_letter(j)].width = w
    ws5.row_dimensions[2].height = 26
    for i, r in enumerate(data["current_inventory"], start=3):
        for j, (key, _, _) in enumerate(inv_cols, start=1):
            v = r.get(key)
            try:
                v = float(v) if key in ("onhand", "available") else v
            except (TypeError, ValueError):
                pass
            c = ws5.cell(row=i, column=j, value=v)
            c.font = Font(name=ARIAL)
            c.alignment = Alignment(horizontal="center" if j > 1 else "left", vertical="center")
            _bordered(c)
    # SKU-level lifetime totals on the same sheet
    start = len(data["current_inventory"]) + 5
    ws5.cell(row=start, column=1, value="Lifetime SKU Totals (across all years)").font = Font(name=ARIAL, bold=True, size=12)
    ws5.merge_cells(start_row=start, start_column=1, end_row=start, end_column=4)
    sku_cols = [("ourparts_num", "SKU", 22), ("lifetime_txns", "Txns", 10),
                ("net_qty", "Net Qty", 10), ("net_rev", "Net Rev", 14)]
    for j, (_, h, w) in enumerate(sku_cols, start=1):
        c = ws5.cell(row=start + 1, column=j, value=h)
        _styled_header(c); _bordered(c)
    for i, r in enumerate(data["sku_aggregate"], start=start + 2):
        for j, (key, _, _) in enumerate(sku_cols, start=1):
            v = r.get(key)
            try:
                v = float(v) if key in ("net_qty", "net_rev") else (int(v) if key == "lifetime_txns" else v)
            except (TypeError, ValueError):
                pass
            c = ws5.cell(row=i, column=j, value=v)
            c.font = Font(name=ARIAL)
            if key == "net_rev":
                c.number_format = "$#,##0.00;($#,##0.00);-"
            c.alignment = Alignment(horizontal="right" if j > 1 else "left", vertical="center")
            _bordered(c)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
