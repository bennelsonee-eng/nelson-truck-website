"""Seed the Build & Price price book (unit_price_guide) from Nelson's own sales.

Ben, 2026-09-25: a customer who specs the truck they want should get a range
"based on past history ... probably a big open range, like $130,000 - $150,000
depending on options and current market pricing".

The numbers below come from Nelson ERP invoices 2023-2026 (invoice_lines joined
to invoices, voids excluded, whole-unit invoices over $50K). Each builder total
is the chassis choice plus the body choice plus any options; the public range is
that sum widened 3% and rounded outward to $5,000 (services/unit_listings.
builder_range). The component splits were chosen so the sums land on what the
same configurations actually sold for -- each row's `basis` says which invoices.

Option adders the ERP can't separate out (4x4, remotes, toolboxes) are marked
"estimate" in their basis. Everything is editable in Admin > Trucks for Sale >
Price guide; this script only fills an EMPTY category and never overwrites.

Run from app/ with the backend venv:
    PYTHONPATH=backend backend/.venv/bin/python -m scripts.seed_unit_price_guide [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal

from sqlalchemy import func, select

from app.database import async_session
from app.models.unit_listing import UnitPriceGuide

# (category, group, group_order, multi, required, label, detail, low, high, basis)
G = list[tuple[str, str, int, bool, bool, str, str | None, int, int, str]]

WRECKER: G = [
    ("wrecker", "Wrecker", 10, False, True, "Jerr-Dan MPL40 self-loading wrecker",
     "Light- to medium-duty cars, pickups and SUVs; up to 4,000 lb retracted lift", 82000, 92000,
     "15 MPL40 builds on class 4-5 chassis 2023-25 sold $143,890-$180,391 whole (median $160,111); chassis median $67,932"),
    ("wrecker", "Wrecker", 10, False, True, "Jerr-Dan MPL60 twin-line wrecker",
     "Heavier wheel-lift and dual winches for fleet and highway work", 105000, 118000,
     "4 MPL60 builds on Freightliner M2 2024-25 sold $195,472-$216,311; chassis median $95,113"),
    ("wrecker", "Chassis", 20, False, True, "Class 4-5 regular cab",
     "Ram 4500 / 5500, Ford F-450 / F-550", 64000, 72000,
     "chassis lines on 15 MPL40 builds 2023-25, median $67,932"),
    ("wrecker", "Chassis", 20, False, True, "Class 4-5 crew or double cab",
     "Room for a crew of four or five", 70000, 80000,
     "6 crew-cab wrecker builds 2023-24, chassis median $69,015 (thin -- review)"),
    ("wrecker", "Chassis", 20, False, True, "Class 6-7 conventional",
     "Freightliner M2, International MV", 90000, 100000,
     "M2 chassis on 4 MPL60 builds 2024-25, median $95,113"),
    ("wrecker", "Drive", 30, False, True, "4x2", None, 0, 0, "baseline"),
    ("wrecker", "Drive", 30, False, True, "4x4", "Front-wheel drive for snow, gravel and off-road recoveries", 4000, 8000,
     "estimate -- the ERP doesn't split the 4x4 premium out"),
    ("wrecker", "Options", 40, True, False, "Wireless remote", None, 2500, 4500, "estimate"),
    ("wrecker", "Options", 40, True, False, "Extra toolboxes", None, 2000, 5000, "estimate"),
    ("wrecker", "Options", 40, True, False, "LED light bar & strobe upgrade", None, 2000, 4500, "estimate"),
    ("wrecker", "Options", 40, True, False, "Dual-line tow sling & recovery kit", None, 3000, 6000,
     "estimate (dual-line sling installs appear on the $244,829 double-cab builds)"),
]

CARRIER: G = [
    ("carrier", "Deck", 10, False, True, "19-20 ft aluminum dual-angle",
     "Light, corrosion-free; the everyday car carrier", 57000, 63000,
     "22 builds on class 4-5 chassis 2023-25, median $131,185 whole (max $137,815); chassis median $69,287"),
    ("carrier", "Deck", 10, False, True, "21-22 ft steel, 6-ton",
     "Longer deck for full-size pickups and vans", 58000, 66000,
     "12 builds on class 6-7 chassis 2023-25 sold $134,200-$171,103 (median $150,105); body-only sales $52,377-$67,027"),
    ("carrier", "Deck", 10, False, True, "22 ft aluminum",
     "Long deck without the steel weight", 54000, 62000,
     "6 builds on class 6-7 chassis 2023-25 sold $139,865-$162,073 (median $144,200)"),
    ("carrier", "Chassis", 20, False, True, "Class 5 cab-over",
     "Isuzu NRR -- tight turning, great visibility", 65000, 76000,
     "NRR chassis lines on 2024-25 carrier builds, $65,287-$76,072"),
    ("carrier", "Chassis", 20, False, True, "Class 5 conventional",
     "Ram 5500, Ford F-550", 68000, 76000,
     "Ram 5500 chassis lines on 2024-25 carrier builds, $71,136-$76,072"),
    ("carrier", "Chassis", 20, False, True, "Class 6-7 conventional",
     "International MV, Freightliner M2, Isuzu FTR", 85000, 98000,
     "chassis lines on 12 class 6-7 carrier builds 2023-25, median $87,660"),
    ("carrier", "Options", 30, True, False, "Wheel lift (underlift)", "Tow a second vehicle", 6000, 10000,
     "estimate -- 'AAA spec no W/L' units show it is optional"),
    ("carrier", "Options", 30, True, False, "Wireless remote", None, 2500, 4500, "estimate"),
    ("carrier", "Options", 30, True, False, "Extra toolboxes", None, 2000, 5000, "estimate"),
    ("carrier", "Options", 30, True, False, "LED light bar & strobe upgrade", None, 2000, 4500, "estimate"),
]

AERIAL: G = [
    ("aerial", "Aerial device", 10, False, True, "Dur-A-Lift up to 42 ft working height",
     "Utility, sign and tree trimming", 95000, 125000,
     "8 aerial builds 2023-26 sold $139,995-$276,322 (median $171,749) -- thin and varied, review"),
    ("aerial", "Aerial device", 10, False, True, "Dur-A-Lift 45-60 ft (arborist)",
     "Two-man platform, forestry package", 140000, 175000,
     "the in-stock DLT2-60 arborist truck lists at $284,966 (ERP P1) -- review"),
    ("aerial", "Chassis", 20, False, True, "Class 5 conventional", "Ford F-550, Ram 5500", 65000, 75000,
     "chassis lines on class 4-5 aerial builds, median $67,108"),
    ("aerial", "Chassis", 20, False, True, "Class 6-7 conventional", "International MV, Freightliner M2", 85000, 100000,
     "estimate from class 6-7 chassis pricing on carrier builds"),
    ("aerial", "Options", 30, True, False, "Chip box / dump body", None, 12000, 20000, "estimate"),
    ("aerial", "Options", 30, True, False, "Service body with compartments", None, 10000, 18000, "estimate"),
]

TRAILER: G = [
    ("trailer", "Trailer", 10, False, True, "Landoll 455B traveling-axle, 53 ft",
     "The workhorse equipment trailer", 128000, 145000,
     "12 sold 2023-26, $123,494-$152,532 (median $134,728)"),
    ("trailer", "Trailer", 10, False, True, "Landoll 440B traveling-axle, 40-41 ft",
     None, 105000, 122000, "3 sold 2023-26, $105,358-$121,858"),
    ("trailer", "Trailer", 10, False, True, "Landoll 950E / 950 detachable",
     None, 110000, 145000, "7 sold 2023-26, $107,372-$148,734 (median $116,794)"),
    ("trailer", "Trailer", 10, False, True, "Landoll 343A", "Tilt deck", 78000, 90000,
     "3 sold 2023-26, $78,845-$88,496"),
    ("trailer", "Options", 20, True, False, "Winch", None, 4000, 8000, "estimate"),
    ("trailer", "Options", 20, True, False, "Aluminum wheels", None, 2500, 5000, "estimate"),
]

ALL = WRECKER + CARRIER + AERIAL + TRAILER


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    async with async_session() as db:
        have = dict((await db.execute(select(UnitPriceGuide.category, func.count())
                                      .group_by(UnitPriceGuide.category))).all())
        added = 0
        for i, (cat, grp, gord, multi, req, label, detail, lo, hi, basis) in enumerate(ALL):
            if have.get(cat):
                continue
            added += 1
            if args.dry_run:
                continue
            db.add(UnitPriceGuide(category=cat, group_name=grp, group_order=gord, multi=multi,
                                  required=req, label=label, detail=detail,
                                  price_low=Decimal(lo), price_high=Decimal(hi),
                                  sort_order=i, active=True, basis=basis))
        if not args.dry_run:
            await db.commit()
        skipped = [c for c in ("wrecker", "carrier", "aerial", "trailer") if have.get(c)]
        print(f"price guide: {'would add' if args.dry_run else 'added'} {added} rows"
              + (f"; left alone (already has rows): {', '.join(skipped)}" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
