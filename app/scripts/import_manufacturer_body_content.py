"""Load manufacturer specs, features, options and PDFs onto the truck-body products.

Companion to import_manufacturer_body_images.py. Reads <brand>_parsed.json
(written by harvest_manufacturer_body_pages.py) and the same product -> model
page map, then writes, per product:

    intro paragraph          -> product.description        (only if empty, unless --overwrite)
    spec footnote (CM)       -> product.extended_description (same rule)
    standard equipment       -> product_description code FEA ("Heading\\n\\nbody")
    optional equipment       -> product_description code OPT (shown as "Available
                                Options", never under "Features" -- an option read
                                as a feature is a promise we didn't make)
    key/value specs (CM)     -> product_attribute
    model matrices           -> product_spec_table
    literature PDFs          -> product_resource, downloaded into
                                app/backend/static/product-resources/<source>/
    dimension drawings (CM)  -> product_image (non-primary, downloaded to our server)

PDFs are stored locally, matching the existing Buyers install sheets, so a
manufacturer moving a file can't break our product page. A PDF that fails to
download is skipped rather than linked.

Re-runnable: FEA/OPT rows, this source's spec tables and resources are replaced;
attributes are replaced key by key. Everything touched is backed up to JSON first.

Usage:
    python app/scripts/import_manufacturer_body_content.py --brand knapheide
    python app/scripts/import_manufacturer_body_content.py --brand cm --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
from import_manufacturer_body_images import localize as localize_image  # noqa: E402
APP_DIR = HERE.parent.parent
ENV_FILE = APP_DIR / ".env"
DATA_DIR = APP_DIR.parent / "discovery" / "manufacturer_data"
STATIC_RES = APP_DIR / "backend" / "static" / "product-resources"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

BRANDS = {
    "knapheide": {"source": "knapheide.com", "map": "kn_model_map.json", "parsed": "knapheide_parsed.json"},
    "cm": {"source": "cmtruckbeds.com", "map": "cm_model_map.json", "parsed": "cm_parsed.json"},
    "rugby": {"source": "rugbymfg.com", "map": "rugby_model_map.json", "parsed": "rugby_parsed.json"},
    # Dur-A-Lift's spec charts are images: the image importer puts them in the
    # gallery, so "drawings" is ignored here (see below).
    "duralift": {"source": "dur-a-lift.com", "map": "dal_model_map.json", "parsed": "duralift_parsed.json"},
}

# CM's Configurations table heads its columns A / B / C; the letters are only
# defined by the drawings beside it, which are imported into the gallery.
CM_CONFIGURATIONS_NOTE = (
    "SRW = single rear wheel, DRW = dual rear wheel. A, B and C are the dimensions "
    "marked on the configuration drawings in the photo gallery. \"VV\" means the V "
    "configuration on both the streetside and curbside; optional flip tops are "
    "available on either or both sides."
)


def db_dsn() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().replace("postgresql+asyncpg://", "postgresql://")
    raise SystemExit("DATABASE_URL not found in app/.env")


# The May Dur-A-Lift ingest stored each product page's whole visible text as the
# extended description -- tab labels, "Request A Quote", "Expand", the parent
# company blurb with its URL. Once the product has structured features and
# options, that dump only repeats them in a worse form.
_DUMP_MARKERS = ("Request A Quote", "Specifications", "Photos", "Builds", "Expand", "Videos", "ABOUT DUR-A-LIFT")


def is_page_dump(text: str | None) -> bool:
    if not text or len(text) < 800:
        return False
    return sum(1 for m in _DUMP_MARKERS if m in text) >= 3


def resource_kind(title: str) -> str:
    t = title.lower()
    if "warranty" in t:
        return "other"
    if "install" in t:
        return "installation"
    if "manual" in t or "operator" in t:
        return "manual"
    if "parts" in t:
        return "parts_list"
    if "spec" in t:
        return "spec_sheet"
    if "drawing" in t or "diagram" in t:
        return "diagram"
    return "brochure"


def local_pdf_name(url: str) -> str:
    """wp-content/uploads/2019/12/Steel-Service-Bodies-Ford.pdf -> 2019-12-Steel-Service-Bodies-Ford.pdf.
    The upload month keeps two same-named files from different months apart."""
    m = re.search(r"/uploads/(\d{4})/(\d{2})/([^/?#]+\.pdf)$", url, re.I)
    name = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else url.rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 1024:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                data = r.read()
            if not data.startswith(b"%PDF"):
                return False
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return False


def resource_title(lit: dict, page_title: str) -> str:
    t = (lit.get("title") or "").strip()
    if not t or t.lower() in ("download", "download model overview", "model overview"):
        return f"{page_title} — Model Overview"
    return t


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", choices=sorted(BRANDS), required=True)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace a product description that already has text")
    args = ap.parse_args()
    cfg = BRANDS[args.brand]
    source = cfg["source"]
    model_map = json.loads((DATA_DIR / cfg["map"]).read_text(encoding="utf-8"))
    parsed = json.loads((DATA_DIR / cfg["parsed"]).read_text(encoding="utf-8"))

    conn = await asyncpg.connect(db_dsn())
    try:
        pids = [int(p) for p in model_map]
        prods = {r["id"]: r for r in await conn.fetch(
            "SELECT id, name, description, extended_description FROM product WHERE id = ANY($1::int[])", pids)}

        # ---- plan ----------------------------------------------------------
        plan = []
        for pid_s, page in model_map.items():
            pid = int(pid_s)
            d = parsed.get(page)
            if d is None or pid not in prods:
                print(f"  SKIP {pid}: no parsed page or no product ({page})")
                continue
            p = prods[pid]
            feats = [f"{f['heading']}\n\n{f['body']}" for f in d["features"]]
            opts = [f"{o['name']}\n\n{o['description']}" if o.get("description") else o["name"]
                    for o in d["options"]]
            kv, seen = [], set()
            for k, v in d["spec_kv"]:
                key = k.strip()[:120]
                if key.lower() not in seen:
                    seen.add(key.lower())
                    kv.append((key, v.strip()))
            tables = []
            for t in d["spec_tables"]:
                note = t.get("note")
                if args.brand == "cm" and (t.get("title") or "") == "Configurations" and d["drawings"]:
                    note = CM_CONFIGURATIONS_NOTE
                tables.append({**t, "note": note})
            intro = "\n\n".join(d["intro"]).strip() or None
            ext = f"Note: {d['spec_note']}" if d.get("spec_note") else None
            plan.append({
                "pid": pid, "name": p["name"], "page": page, "title": d["title"],
                "clear_dump": is_page_dump(p["extended_description"]) and bool(feats or opts),
                "description": intro if intro and (args.overwrite or not (p["description"] or "").strip()) else None,
                "extended": ext if ext and (args.overwrite or not (p["extended_description"] or "").strip()) else None,
                "features": feats, "options": opts, "kv": kv, "tables": tables,
                # only CM's drawings define table columns (A/B/C); other brands' images
                # (Dur-A-Lift spec charts) are placed by the image importer
                "literature": d["literature"], "drawings": d["drawings"] if args.brand == "cm" else [],
            })

        pdfs = {lit["url"] for x in plan for lit in x["literature"]}
        print(f"brand            : {args.brand} ({source})")
        print(f"products         : {len(plan)}")
        print(f"descriptions     : {sum(1 for x in plan if x['description'])} to write")
        print(f"page-text dumps  : {sum(1 for x in plan if x['clear_dump'])} to clear (replaced by structured content)")
        print(f"features (FEA)   : {sum(len(x['features']) for x in plan)}")
        print(f"options (OPT)    : {sum(len(x['options']) for x in plan)}")
        print(f"spec attributes  : {sum(len(x['kv']) for x in plan)}")
        print(f"spec tables      : {sum(len(x['tables']) for x in plan)}")
        print(f"PDF links        : {sum(len(x['literature']) for x in plan)} ({len(pdfs)} distinct files)")
        print(f"drawings         : {sum(len(x['drawings']) for x in plan)}")

        if not args.apply:
            print("\nDRY RUN - nothing downloaded or written. Re-run with --apply.")
            return 0

        # ---- PDFs first: only a file we actually hold gets linked ----------
        local = {}
        for i, url in enumerate(sorted(pdfs), 1):
            dest = STATIC_RES / source / local_pdf_name(url)
            ok = download(url, dest)
            if ok:
                local[url] = f"/static/product-resources/{source}/{dest.name}"
            print(f"  pdf {i:>2}/{len(pdfs)} {'ok  ' if ok else 'FAIL'} {url.rsplit('/', 1)[-1]}")
        failed = sorted(pdfs - set(local))

        # ---- backup --------------------------------------------------------
        backup = {
            "product": [dict(r) for r in prods.values()],
            "product_description": [dict(r) for r in await conn.fetch(
                "SELECT * FROM product_description WHERE product_id = ANY($1::int[]) "
                "AND description_code IN ('FEA','OPT')", pids)],
            "product_attribute": [dict(r) for r in await conn.fetch(
                "SELECT * FROM product_attribute WHERE product_id = ANY($1::int[])", pids)],
            "product_spec_table": [dict(r) for r in await conn.fetch(
                "SELECT * FROM product_spec_table WHERE product_id = ANY($1::int[]) AND source = $2", pids, source)],
            "product_resource": [dict(r) for r in await conn.fetch(
                "SELECT * FROM product_resource WHERE product_id = ANY($1::int[]) AND source = $2", pids, source)],
        }
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bfile = DATA_DIR / f"content_backup_{args.brand}_{stamp}.json"
        bfile.write_text(json.dumps(backup, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"\nbacked up existing rows -> {bfile.name}")

        # ---- write ---------------------------------------------------------
        n = {"desc": 0, "ext": 0, "fea": 0, "opt": 0, "attr": 0, "tbl": 0, "res": 0, "img": 0}
        async with conn.transaction():
            for x in plan:
                pid = x["pid"]
                if x["description"]:
                    await conn.execute("UPDATE product SET description=$2, updated_at=now() WHERE id=$1",
                                       pid, x["description"])
                    n["desc"] += 1
                if x["extended"]:
                    await conn.execute("UPDATE product SET extended_description=$2, updated_at=now() WHERE id=$1",
                                       pid, x["extended"])
                    n["ext"] += 1
                elif x["clear_dump"]:
                    await conn.execute("UPDATE product SET extended_description=NULL, updated_at=now() WHERE id=$1", pid)
                    n["dump"] = n.get("dump", 0) + 1

                await conn.execute("DELETE FROM product_description WHERE product_id=$1 "
                                   "AND description_code IN ('FEA','OPT')", pid)
                for code, texts in (("FEA", x["features"]), ("OPT", x["options"])):
                    for seq, text in enumerate(texts, 1):
                        await conn.execute(
                            "INSERT INTO product_description (product_id, description_code, language_code, sequence, text) "
                            "VALUES ($1,$2,'EN',$3,$4)", pid, code, seq, text)
                        n["fea" if code == "FEA" else "opt"] += 1

                if x["kv"]:
                    await conn.execute("DELETE FROM product_attribute WHERE product_id=$1 "
                                       "AND attribute_key = ANY($2::varchar[])", pid, [k for k, _ in x["kv"]])
                    for k, v in x["kv"]:
                        await conn.execute("INSERT INTO product_attribute (product_id, attribute_key, attribute_value) "
                                           "VALUES ($1,$2,$3)", pid, k, v)
                        n["attr"] += 1

                await conn.execute("DELETE FROM product_spec_table WHERE product_id=$1 AND source=$2", pid, source)
                for i, t in enumerate(x["tables"]):
                    await conn.execute(
                        "INSERT INTO product_spec_table (product_id, title, headers, rows, note, sort_order, source) "
                        "VALUES ($1,$2,$3::jsonb,$4::jsonb,$5,$6,$7)",
                        pid, t.get("title"), json.dumps(t["headers"], ensure_ascii=False),
                        json.dumps(t["rows"], ensure_ascii=False), t.get("note"), i, source)
                    n["tbl"] += 1

                await conn.execute("DELETE FROM product_resource WHERE product_id=$1 AND source=$2", pid, source)
                for i, lit in enumerate(x["literature"]):
                    url = local.get(lit["url"])
                    if not url:
                        continue
                    title = resource_title(lit, x["title"] or x["name"])
                    # a parser that knows the section a link sat under (Rugby's
                    # "Product Literature" vs "Manuals") says so; otherwise read the title
                    kind = lit.get("kind") or resource_kind(title)
                    await conn.execute(
                        "INSERT INTO product_resource (product_id, kind, url, title, description, sort_order, source) "
                        "VALUES ($1,$2::resource_kind,$3,$4,$5,$6,$7) ON CONFLICT (product_id, url) DO NOTHING",
                        pid, kind, url, title[:300], f"Source: {lit['url']}", i, source)
                    n["res"] += 1

                if x["drawings"]:
                    start = await conn.fetchval(
                        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM product_image WHERE product_id=$1", pid)
                    alt = f"{x['name']} — configuration drawing (dimensions A, B, C)"
                    for j, u in enumerate(x["drawings"]):
                        # The image import may already have pulled a drawing into the
                        # gallery, captioned as an installed-truck photo. Re-caption it.
                        updated = await conn.execute(
                            "UPDATE product_image SET alt_text=$3, updated_at=now() "
                            "WHERE product_id=$1 AND source_url=$2", pid, u, alt)
                        if updated != "UPDATE 0":
                            n["img"] += 1
                            continue
                        got = localize_image(u)          # our copy or nothing -- never a hotlink
                        if not got:
                            print(f"  drawing FAIL {u}")
                            continue
                        await conn.execute(
                            "INSERT INTO product_image (product_id, url, thumb_url, source_url, alt_text, sort_order, is_primary, legacy_origin) "
                            "VALUES ($1,$2,$3,$4,$5,$6,false,$7)",
                            pid, got[0], got[1], u, alt, start + j, source)
                        n["img"] += 1

        print("written:", ", ".join(f"{k}={v}" for k, v in n.items()))
        if failed:
            print(f"PDFs NOT linked (download failed): {len(failed)}")
            for u in failed:
                print("   ", u)
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
