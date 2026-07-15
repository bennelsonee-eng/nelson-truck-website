"""build_brand_xlsx.py — Generic brand-Excel builder.

For one prod_code (e.g. MAXX, KAR, WEST):
  * Reads {brand}_parts_master.csv from app/data/mysql_dumps/
  * Reads {brand}_tte_inv.csv and {brand}_nte_inv.csv (filtered to wh 10/1/2)
  * Optionally cross-references Nelson ERP `parts` table for richer
    LLM-enriched descriptions
  * Optionally cross-references manufacturer-website scrape data
    (e.g. maxxima_catalog.json)
  * Outputs app/data/reports/{brand}_in_stock_titan_nelson.xlsx

Usage:
    python app/scripts/build_brand_xlsx.py MAXX "Maxxima"
    python app/scripts/build_brand_xlsx.py KAR  "Kargo Master / Holman"
    python app/scripts/build_brand_xlsx.py WEST "Western"
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

DATA = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps"
REPORTS = Path(__file__).resolve().parent.parent / "data" / "reports"
ARIAL = "Arial"
WAREHOUSES = {10: "SPO (Titan)", 1: "Portland (NTE)", 2: "Kent (NTE)"}

# Manufacturer-website URL per prod_code (where known + relevant)
BRAND_WEBSITE = {
    "MAXX": "https://maxxima.com",
    "KAR":  "https://kargo-master.com",
    "BUY":  "https://www.buyersproducts.com",
    "SNOW": "https://www.buyersproducts.com",   # SnowDogg shares parent site
    "MYP":  "https://www.meyerproducts.com",
    "WEST": "https://westernplows.com",
    "BAJA": "https://www.bajadesigns.com",
    "KNP":  "https://www.knapheide.com",
    "MIS":  "",
    "UTL":  "",
    "HRP":  "",
    "BAP":  "",
    "DELCITY": "https://www.delcity.net",
    "ECCO": "https://www.eccoesg.com",
}

BRAND_SEARCH_URL = {
    "MAXX": "https://maxxima.com/category/?q={pn}",
    "KAR":  "https://kargo-master.com/?s={pn}",
    "BUY":  "https://www.buyersproducts.com/search?q={pn}",
    "SNOW": "https://www.buyersproducts.com/search?q={pn}",
    "MYP":  "https://www.meyerproducts.com/search?q={pn}",
    "WEST": "https://westernplows.com/parts/?search={pn}",
    "BAJA": "https://www.bajadesigns.com/search?q={pn}",
    "KNP":  "https://www.knapheide.com/search?searchTerm={pn}",
    "DELCITY": "https://www.delcity.net/store/search?searchTerm={pn}",
    "ECCO": "https://www.eccoesg.com/us/en/products/ProductSearch?q={pn}",
}


def D(v):
    if v in (None, "", "0", "0.00", "0.0"):
        return None
    try:
        d = Decimal(v)
        return d if d.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def load_master(prod_code: str) -> dict[str, dict]:
    path = DATA / f"{prod_code.lower()}_parts_master.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        for r in csv.DictReader(fp):
            ou = (r.get("ourparts_num") or "").strip()
            if not ou or ou == "#":
                continue
            out[ou] = {
                "parts_num": (r.get("parts_num") or "").strip(),
                "description": (r.get("description") or "").strip(),
                "extra_desc": (r.get("extra_desc") or "").strip(),
                "p1": D(r.get("P1")), "p2": D(r.get("P2")), "p3": D(r.get("P3")),
                "p4": D(r.get("P4")), "p5": D(r.get("P5")),
                "weight": D(r.get("weight")),
                "location": (r.get("location") or "").strip(),
                "status": (r.get("status") or "").strip(),
                "supplier": (r.get("supplier") or "").strip(),
            }
    return out


def load_inv_combined(prod_code: str) -> dict[str, dict]:
    inv: dict[tuple[str, int], dict] = {}
    for fname in (f"{prod_code.lower()}_tte_inv.csv", f"{prod_code.lower()}_nte_inv.csv"):
        path = DATA / fname
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as fp:
            for r in csv.DictReader(fp):
                ou = (r.get("ourparts_num") or "").strip()
                if not ou:
                    continue
                try:
                    oh = int(float(r.get("onhand") or 0))
                    av = int(float(r.get("available") or 0))
                    wh = int(r.get("warehouse") or 0)
                except ValueError:
                    continue
                if wh not in WAREHOUSES:
                    continue
                gc = D(r.get("gl_cost"))
                key = (ou, wh)
                rec = inv.setdefault(key, {"on_hand": 0, "available": 0, "gl_cost": None})
                rec["on_hand"] += oh
                rec["available"] += av
                if gc is not None and (rec["gl_cost"] is None or gc > rec["gl_cost"]):
                    rec["gl_cost"] = gc
    by_part: dict[str, dict] = defaultdict(lambda: {
        "warehouses": {}, "total_on_hand": 0, "total_available": 0, "gl_cost": None,
    })
    for (ou, wh), v in inv.items():
        by_part[ou]["warehouses"][wh] = v
        by_part[ou]["total_on_hand"] += v["on_hand"]
        by_part[ou]["total_available"] += v["available"]
        if v["gl_cost"] is not None and (by_part[ou]["gl_cost"] is None or v["gl_cost"] > by_part[ou]["gl_cost"]):
            by_part[ou]["gl_cost"] = v["gl_cost"]
    return dict(by_part)


def load_maxxima_scrape() -> dict[str, str]:
    """SKU.upper() → enriched description (text)."""
    path = DATA / "maxxima_catalog.json"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for p in json.loads(path.read_text(encoding="utf-8")):
        sku = (p.get("sku") or "").upper()
        if sku:
            out[sku] = p.get("description_text", "")
    return out


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: build_brand_xlsx.py PROD_CODE 'Brand Name'")
        sys.exit(1)
    prod = sys.argv[1].upper()
    brand_name = sys.argv[2]

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    master = load_master(prod)
    inv = load_inv_combined(prod)
    print(f"{prod} ({brand_name}): {len(master)} parts in master, {len(inv)} parts in inv")

    # Optional enrichment
    maxxima_descs = load_maxxima_scrape() if prod == "MAXX" else {}

    rows = []
    for ou, i in inv.items():
        if i["total_on_hand"] <= 0:
            continue
        m = master.get(ou, {})
        # Maxxima scrape SKU is the part_num upper-cased
        scrape_desc = ""
        if maxxima_descs and m.get("parts_num"):
            scrape_desc = maxxima_descs.get(m["parts_num"].upper(), "")
        rows.append({
            "ourparts_num": ou,
            "parts_num": m.get("parts_num", ""),
            "description": m.get("description", ""),
            "extra_desc": m.get("extra_desc", ""),
            "scrape_desc": scrape_desc[:400] + ("…" if len(scrape_desc) > 400 else ""),
            "scrape_full_chars": len(scrape_desc),
            "wh_10": i["warehouses"].get(10, {}).get("on_hand"),
            "wh_1":  i["warehouses"].get(1, {}).get("on_hand"),
            "wh_2":  i["warehouses"].get(2, {}).get("on_hand"),
            "total_on_hand": i["total_on_hand"],
            "total_available": i["total_available"],
            "gl_cost": float(i["gl_cost"]) if i["gl_cost"] else None,
            "p1": float(m["p1"]) if m.get("p1") else None,
            "p2": float(m["p2"]) if m.get("p2") else None,
            "p3": float(m["p3"]) if m.get("p3") else None,
            "p4": float(m["p4"]) if m.get("p4") else None,
            "p5": float(m["p5"]) if m.get("p5") else None,
            "weight": float(m["weight"]) if m.get("weight") else None,
            "location": m.get("location", ""),
            "status": m.get("status", ""),
        })
    rows.sort(key=lambda r: -(r["total_on_hand"] or 0))
    units = sum(r["total_on_hand"] for r in rows)
    print(f"  in-stock SKUs (wh 10/1/2): {len(rows)}, total units: {units}")
    if not rows:
        print(f"  no in-stock rows — skipping Excel")
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "In-Stock Items"

    header_font = Font(name=ARIAL, bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", start_color="1F4E78")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    left = Alignment(horizontal="left", vertical="center")
    left_wrap = Alignment(horizontal="left", vertical="center", wrap_text=True)
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    cols = [
        ("ourparts_num", "Our Part #", 18, "left"),
        ("parts_num", "Mfr Part #", 18, "left"),
        ("description", "MySQL Description", 36, "left_wrap"),
        ("extra_desc", "Extra Desc", 18, "left_wrap"),
    ]
    if maxxima_descs:
        cols.append(("scrape_desc", "Maxxima.com Description", 60, "left_wrap"))
    cols += [
        ("wh_10", "SPO (Titan)", 11, "right"),
        ("wh_1",  "Portland", 10, "right"),
        ("wh_2",  "Kent", 10, "right"),
        ("total_on_hand", "Total On Hand", 12, "right"),
        ("total_available", "Available", 11, "right"),
        ("gl_cost", "GL Cost", 11, "currency"),
        ("p1", "P1 List", 11, "currency"),
        ("p2", "P2 Retail", 11, "currency"),
        ("p3", "P3 Jobber", 11, "currency"),
        ("p4", "P4 Dealer", 11, "currency"),
        ("p5", "P5 Cost", 11, "currency"),
        ("weight", "Wt (lb)", 9, "right"),
        ("location", "Loc", 8, "center"),
        ("status", "Status", 8, "center"),
        ("brand_url", f"{brand_name} Search", 22, "url"),
    ]

    for j, (_, h, w, _) in enumerate(cols, start=1):
        c = ws.cell(row=1, column=j, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = header_align
        c.border = border
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.row_dimensions[1].height = 32

    search_pat = BRAND_SEARCH_URL.get(prod, "")
    for i, r in enumerate(rows, start=2):
        for j, (key, _, _, fmt) in enumerate(cols, start=1):
            if key == "brand_url":
                pn = r["parts_num"] or r["ourparts_num"]
                if search_pat:
                    c = ws.cell(row=i, column=j,
                                value=f'=HYPERLINK("{search_pat.format(pn=pn)}", "Search {brand_name}")')
                    c.font = Font(name=ARIAL, color="0563C1", underline="single")
                else:
                    c = ws.cell(row=i, column=j, value="")
                c.alignment = center
            else:
                v = r.get(key)
                c = ws.cell(row=i, column=j, value=v)
                c.font = Font(name=ARIAL)
                if fmt == "currency":
                    c.number_format = "$#,##0.00;($#,##0.00);-"
                    c.alignment = right
                elif fmt == "right":
                    c.alignment = right
                elif fmt == "center":
                    c.alignment = center
                elif fmt == "left_wrap":
                    c.alignment = left_wrap
                else:
                    c.alignment = left
            c.border = border

    total_row = len(rows) + 2
    ws.cell(row=total_row, column=1, value="TOTAL").font = Font(name=ARIAL, bold=True)
    ws.cell(row=total_row, column=1).alignment = right
    ws.cell(row=total_row, column=1).fill = PatternFill("solid", start_color="DDEBF7")
    # Sum the warehouse + total columns
    wh10_col = 5 if not maxxima_descs else 6
    for offset in range(0, 5):
        col_idx = wh10_col + offset
        letter = get_column_letter(col_idx)
        c = ws.cell(row=total_row, column=col_idx,
                    value=f"=SUM({letter}2:{letter}{total_row - 1})")
        c.font = Font(name=ARIAL, bold=True)
        c.alignment = right
        c.fill = PatternFill("solid", start_color="DDEBF7")
        c.border = border

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{total_row - 1}"

    # Summary sheet
    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = f"{brand_name} In-Stock Summary (Titan + Nelson)"
    ws2["A1"].font = Font(name=ARIAL, bold=True, size=14)
    ws2.merge_cells("A1:D1")

    last_row = len(rows) + 1
    labels = [
        ("Brand", brand_name),
        ("Prod code (TigerTech)", prod),
        ("Manufacturer site", BRAND_WEBSITE.get(prod, "(unknown)")),
        ("Data source", "TigerTech MySQL: tte_parts_master + tte_inv_days (wh 10) + nte_inv_days (wh 1, 2)"),
        ("Total parts catalogued (master)", len(master)),
        ("Total in-stock SKUs", len(rows)),
        ("Total units on hand", units),
    ]
    for i, (label, val) in enumerate(labels, start=3):
        ws2.cell(row=i, column=1, value=label).font = Font(name=ARIAL, bold=True)
        ws2.cell(row=i, column=1).alignment = right
        c = ws2.cell(row=i, column=2, value=val)
        c.font = Font(name=ARIAL)
        c.alignment = left
    for col, width in (("A", 30), ("B", 60), ("C", 12), ("D", 12)):
        ws2.column_dimensions[col].width = width

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS / f"{prod.lower()}_in_stock_titan_nelson.xlsx"
    wb.save(out_path)
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
