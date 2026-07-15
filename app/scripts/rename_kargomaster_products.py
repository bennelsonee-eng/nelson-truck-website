"""rename_kargomaster_products.py — replace the AI-generated descriptive
SENTENCE names on the 129 Kargo Master products with concise product names.

The brand was imported with names like "The Pro Rack complete leg and crossbar
system for full-size trucks with 24-inch height configuration..." instead of a
real product name. This derives a concise name from the description lead +
detected product line, vehicles, and roof:

    <Line> <Qualifier> <Type> — <Vehicles> (<Roof>)
    e.g. "Pro Rack Leg & Crossbar System — Full-Size Truck"
         "Single Drop-Down Ladder Rack — ProMaster / Sprinter"
         "Perforated Partition — Metris / Transit (Low Roof)"

Short legacy all-caps stubs (e.g. "PRO II BODY LEGS & BARS - PLAT") are
title-cased and de-abbreviated instead.

Idempotent: only rewrites a product whose current name differs from the
generated one. A backup CSV of (id, sku, old_name) is written before applying,
so names can be restored. Categorization is handled separately by
reclassify_kargomaster.py.

Usage
-----
    python app/scripts/rename_kargomaster_products.py            # dry run (prints all 129)
    python app/scripts/rename_kargomaster_products.py --apply    # commit
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("km_rename")

BRAND = "Kargo Master"

VEH = [("transit connect", "Transit Connect"), ("promaster city", "ProMaster City"),
       ("promaster", "ProMaster"), ("sprinter", "Sprinter"), ("metris", "Metris"),
       ("nv200", "NV200"), ("nissan nv", "NV"), ("transit", "Transit"), ("savana", "Savana"),
       ("express", "Express"), ("f-250", "F-250/350"), ("f-350", "F-250/350"),
       ("full-size pickup", "Full-Size Truck"), ("full-size truck", "Full-Size Truck"),
       ("mid-size pickup", "Mid-Size Truck"), ("service body", "Service Body"),
       ("platform body", "Platform Body"), ("pickup truck", "Pickup Truck")]

WORDNUM = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6"}


def vehicles(n: str) -> list[str]:
    out: list[str] = []
    for k, v in VEH:
        if k in n and v not in out:
            out.append(v)
    return out[:3]


def roof(n: str) -> str | None:
    for k, v in [("low roof", "Low Roof"), ("low-roof", "Low Roof"), ("mid roof", "Mid Roof"),
                 ("mid-roof", "Mid Roof"), ("high roof", "High Roof"), ("high-roof", "High Roof"),
                 ("standard roof", "Standard Roof")]:
        if k in n:
            return v
    return None


def line(n: str) -> str:
    for k, v in [("pro iii", "Pro III"), ("pro ii", "Pro II"), ("pro rack", "Pro Rack"),
                 ("econo", "Econo"), ("vantred", "VanTred")]:
        if k in n:
            return v
    return ""


def qual(n: str) -> str:
    for k, v in [("single drop", "Single "), ("double drop", "Double "),
                 ("driver-side", "Driver-Side "), ("driver side", "Driver-Side "),
                 ("perforated", "Perforated "), ("solid steel", "Solid Steel "),
                 ("composite", "Composite ")]:
        if k in n:
            return v
    return ""


# (keyword, display) pairs. ptype() picks the keyword that appears EARLIEST in
# the name lead (the head noun), breaking ties toward the longer keyword — so
# "Additional crossbar for Pro III rack systems" -> Crossbar, while "Pro II
# truck rack system with ... crossbars" -> Truck Rack, and an incidental
# "...for Kargo Master rack systems" deep in a wind-deflector description never
# wins over the real lead.
PTYPES = [("leg & crossbar", "Leg & Crossbar System"), ("leg and crossbar", "Leg & Crossbar System"),
          ("leg and bar", "Leg & Bar Kit"), ("leg & bar", "Leg & Bar Kit"),
          ("side channel", "Side Channel Kit"), ("window guard", "Window Guard"),
          ("drop-down ladder rack", "Drop-Down Ladder Rack"), ("drop-down", "Drop-Down Ladder Rack"),
          ("drop down", "Drop-Down Ladder Rack"), ("ladder extension", "Ladder Extension Hooks"),
          ("crossbar", "Crossbar"), ("cargo rack", "Cargo Rack"), ("truck rack", "Truck Rack"),
          ("rack hoop", "Truck Rack Hoop"), ("rack system", "Rack System"), ("roller bar", "Roller Bar"),
          ("rail mounting", "Rail Mounting Kit"), ("removable bar", "Removable Bar"),
          ("mounting kit", "Mount Kit"), ("mount kit", "Mount Kit"), ("ratchet strap", "Ratchet Strap"),
          ("deflector", "Wind Deflector"), ("leg exten", "Leg Extension"),
          ("partition wing kit", "Partition Wing Kit"), ("wing kit", "Partition Wing Kit"),
          ("partition", "Partition"), ("floor angle", "Floor Angle & Shelf Lip"),
          ("shelf lip", "Shelf Lip"), ("shelf cabinet", "Shelf Cabinet"), ("cabinet locker", "Cabinet Locker"),
          ("shelf unit", "Shelf Unit"), ("shelf", "Shelf Unit"), ("drawer", "Drawer Cabinet"),
          ("cabinet", "Steel Cabinet"), ("storage bin", "Storage Bin"), ("bin holder", "Bin Holder"),
          ("standing bin", "Bin Holder"), ("filing", "Filing System"), ("reel holder", "Wire Reel Holder"),
          ("j-hook", "J-Hook"), ("swivel", "Swivel J-Hook"), ("hook", "J-Hook"),
          ("bottle restraint", "Bottle Restraint"), ("divider", "Shelf Dividers"),
          ("door kit", "Shelf Door Kit"), ("folding shelf", "Folding Shelf"), ("grab handle", "Grab Handles"),
          ("bed rail", "Bed Rail System"), ("window screen", "Window Screen"), ("floor mat", "Floor Mat"),
          ("tri-knob", "Tri-Knob Clamp"), ("emergency light", "Light Mount Bracket"),
          ("three-tier", "3-Tier Storage Rack"), ("mounting bracket", "Mount Bracket")]


def ptype(lead: str) -> str:
    best_idx, best_len, best_val = 999, 0, ""
    for k, v in PTYPES:
        i = lead.find(k)
        if i == -1:
            continue
        if i < best_idx or (i == best_idx and len(k) > best_len):
            best_idx, best_len, best_val = i, len(k), v
    return best_val


def fix_stub(name: str) -> str:
    t = name.title().replace(" - ", " — ")
    t = re.sub(r"^The ", "", t)            # "THE PRO RACK ..." -> "Pro Rack ..."
    t = re.sub(r"\s*\(Use.*$", "", t)      # drop truncated "(USE..." trailers
    t = re.sub(r"\bIii\b", "III", t)
    t = re.sub(r"\bIi\b", "II", t)
    t = re.sub(r"\bHd\b", "HD", t)
    t = re.sub(r"\bPlat\b", "Platform", t)
    t = re.sub(r"\bSpri\b", "Sprinter", t)
    t = re.sub(r"\bExtens?\b", "Extension", t)
    t = re.sub(r"\bKi\b", "Kit", t)        # truncated "...CROSSBAR KI" -> "Kit"
    t = re.sub(r"\s+With\s+", " — ", t)    # "Crossbar Rack With Retractable" -> " — "
    t = re.sub(r'\b60" W X 2\b', '60" Wide', t)
    return t.strip()


def gen(sku: str, name: str) -> str:
    low = name.lower()
    # Short legacy all-caps stub -> just clean it up; the original wording
    # (size, material, "HD Aluminum", "Full Door") is more useful than what the
    # keyword generator would distil it to.
    if len(name) <= 34 and name.upper() == name:
        return fix_stub(name)
    lead = low[:50]
    L, Q, T = line(lead), qual(lead), ptype(lead)
    m = re.search(r"(two|three|four|five|six|\d)-drawer", low)
    if T in ("Drawer Cabinet", "Steel Cabinet") and m:
        cnt = WORDNUM.get(m.group(1), m.group(1))
        T, Q = f"{cnt}-Drawer Steel Cabinet", ""
    # "Pro Rack" + "Rack System" -> "Pro Rack System" (avoid doubled "Rack").
    if T == "Rack System" and L.endswith("Rack"):
        T = "System"
    head = " ".join(x for x in [L, Q.strip(), T] if x).strip()
    if not head:
        head = fix_stub(name) if name.upper() == name else name[:40].strip()
    vs, rf = vehicles(low), roof(low)
    if vs:
        tail = " / ".join(vs) + (f" ({rf})" if rf else "")
        return f"{head} — {tail}"
    if rf:
        return f"{head} ({rf})"
    return head


def is_dirty(name: str) -> bool:
    """True if the name still looks like an original AI-sentence or a legacy
    all-caps stub — i.e. something this script should rewrite. Already-clean
    concise names return False, so re-running --apply is a no-op (idempotent).
    """
    if name.upper() == name and len(name) <= 40:
        return True  # legacy all-caps stub
    if len(name) > 70:
        return True  # descriptive sentence (well above the longest clean name ~61)
    n = name.lower()
    return any(w in n for w in ("designed", "specifically", "provides",
                                "engineered", "features", "ideal for",
                                "delivers", "providing", "combining"))


def resolve_dsn() -> str:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    return dsn


async def main(apply: bool) -> None:
    conn = await asyncpg.connect(resolve_dsn())
    try:
        prods = await conn.fetch(
            "SELECT p.id, p.sku, p.name FROM product p JOIN brand b ON b.id = p.brand_id "
            "WHERE b.name = $1 ORDER BY p.name",
            BRAND,
        )
        changes = []  # (id, sku, old, new)
        for r in prods:
            if not is_dirty(r["name"]):
                continue  # already a clean concise name — leave it (idempotent)
            new = gen(r["sku"], r["name"])
            if new and new != r["name"]:
                changes.append((r["id"], r["sku"], r["name"], new))

        log.info("%s: %d products, %d names to change", BRAND, len(prods), len(changes))
        for _id, sku, old, new in changes:
            log.info("  %-12s %s", sku, new)

        if not apply:
            log.info("DRY RUN — no changes written. Re-run with --apply to commit.")
            return

        backups_dir = Path(__file__).resolve().parents[2] / "backups" / "kargomaster_reclassify"
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backups_dir / f"kargomaster_names_{stamp}.csv"
        with backup_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["product_id", "sku", "old_name", "new_name"])
            for _id, sku, old, new in changes:
                w.writerow([_id, sku, old, new])
        log.info("Backup written: %s", backup_path)

        async with conn.transaction():
            for _id, _sku, _old, new in changes:
                await conn.execute(
                    "UPDATE product SET name = $1, updated_at = NOW() WHERE id = $2", new, _id
                )
        log.info("Applied %d name changes.", len(changes))
        log.info("Reindex Typesense so search reflects the new names.")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rename Kargo Master products to concise names.")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry run).")
    args = ap.parse_args()
    asyncio.run(main(args.apply))
