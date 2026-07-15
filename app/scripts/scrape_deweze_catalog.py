"""scrape_deweze_catalog.py — Extract Deweze clutch pump kit catalog.

deweze.com/hydraulics/find-kit/ embeds the full kit lookup as inline
JavaScript objects (no API call — the page rehydrates from a static
array).  Each kit record includes:

  id, number, make, engine_or_model, engine_size, engine_fuel,
  engine_oem_belt, engine_start_year, engine_end_year,
  engine_options, pump_type, pump_port, clutch_configuration,
  belt, notes, obsolete, manual (PDF URL)

We pull the page, parse out each `{...}` block that contains a
"manual" PDF URL, and write a clean JSON catalog plus a deduped list
of schematic PDF URLs.

Output:
  app/data/mysql_dumps/deweze_kits.json     ~300 kit records
  app/data/mysql_dumps/deweze_pdfs.txt      unique S3 PDF URLs (one per line)
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from html import unescape
from pathlib import Path


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FIND_KIT_URL = "https://www.deweze.com/hydraulics/find-kit/"
ENGINE_PTO_URL = "https://www.deweze.com/hydraulics/engine-driven-pto/"

DATA = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps"
OUT_JSON = DATA / "deweze_kits.json"
OUT_PDFS = DATA / "deweze_pdfs.txt"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# Pull just the keys we care about from each kit object via permissive regex.
# The JS objects are JSON-ish but with trailing commas — can't json.loads
# directly, so we extract per-field with regex.
FIELD_PATTERNS = {
    "id": r'"id":\s*(\d+)',
    "number": r'"number":\s*"([^"]+)"',
    "make": r'"make":\s*"([^"]*)"',
    "engine_or_model": r'"engine_or_model":\s*"([^"]*)"',
    "engine_size": r'"engine_size":\s*"([^"]*)"',
    "engine_fuel": r'"engine_fuel":\s*"([^"]*)"',
    "engine_start_year": r'"engine_start_year":\s*(\d+|null)',
    "engine_end_year": r'"engine_end_year":\s*(\d+|null)',
    "pump_type_name": r'"pump_type":\s*\{\s*"name":\s*"([^"]*)"',
    "pump_type_short": r'"pump_type":[^}]*?"short_name":\s*"([^"]*)"',
    "pump_port": r'"pump_port":\s*"([^"]*)"',
    "clutch_configuration": r'"clutch_configuration":\s*"([^"]*)"',
    "belt": r'"belt":\s*"([^"]*)"',
    "manual": r'"manual":\s*"(https?://[^"]+\.pdf)"',
    "obsolete": r'"obsolete":\s*(true|false)',
}


def extract_kits(html: str) -> list[dict]:
    """Walk the inline JS array and extract each kit record.

    Each record is `{ ... }` with a "manual" PDF URL.  We split the
    page on "{" and look at the chunk after each opening brace for
    the field patterns.  This is intentionally permissive — false
    positives just don't have a "manual" field and get filtered out.
    """
    kits: list[dict] = []
    # Find every kit object by anchoring on `"manual": "...pdf"` then
    # looking backward ~3000 chars for the matching opening `{`.
    for m in re.finditer(r'"manual":\s*"(https?://[^"]+\.pdf)"', html):
        end = m.end()
        # Walk back to the nearest `{` that begins the record
        start = end
        depth = 0
        for i in range(end - 1, max(0, end - 5000), -1):
            ch = html[i]
            if ch == "}":
                depth += 1
            elif ch == "{":
                if depth == 0:
                    start = i
                    break
                depth -= 1
        chunk = html[start:end + 200]
        record: dict = {}
        for field, pat in FIELD_PATTERNS.items():
            mm = re.search(pat, chunk, re.S)
            if not mm:
                continue
            v = mm.group(1)
            if v == "null":
                record[field] = None
            elif v in ("true", "false"):
                record[field] = (v == "true")
            elif field in ("id", "engine_start_year", "engine_end_year") and v.isdigit():
                record[field] = int(v)
            else:
                # Decode JS escapes
                record[field] = unescape(v.replace("\\u0022", '"').replace("\\/", "/"))
        if "manual" in record and "number" in record:
            kits.append(record)
    return kits


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    print("Fetching find-kit page…")
    html = fetch(FIND_KIT_URL)
    print(f"  {len(html)} bytes")

    kits = extract_kits(html)
    print(f"\nExtracted {len(kits)} kit records")

    # Dedupe by kit number (some are duplicated under multiple sub-options)
    by_num: dict[str, dict] = {}
    for k in kits:
        num = k["number"]
        if num not in by_num:
            by_num[num] = k
        else:
            # Merge — accumulate distinct makes/engines if needed
            existing = by_num[num]
            for kk in ("make", "engine_or_model"):
                if k.get(kk) and existing.get(kk) and k[kk] != existing[kk]:
                    existing[kk] = f"{existing[kk]}, {k[kk]}"
    deduped = list(by_num.values())
    deduped.sort(key=lambda k: k["number"])
    print(f"After dedupe: {len(deduped)} unique kit numbers")

    # Also pull the general hydraulics PDFs from the engine-driven-pto page
    print("\nFetching engine-driven-pto page for general resource PDFs…")
    eh = fetch(ENGINE_PTO_URL)
    general_pdfs = sorted(set(re.findall(
        r'https://harperindustries\.s3\.amazonaws\.com/[^\s"\'<>]+\.pdf', eh,
    )))
    print(f"  {len(general_pdfs)} general PDFs found")

    # Print sample
    print("\nSample kits:")
    for k in deduped[:6]:
        ye = f"{k.get('engine_start_year', '')}-{k.get('engine_end_year', '')}"
        print(f"  #{k['number']:<8} {k.get('make', ''):<15} {k.get('engine_or_model', ''):<25} {ye:<10} pump={k.get('pump_type_short', '')}  PDF=…/{k['manual'].rsplit('/', 1)[1]}")

    DATA.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "kits": deduped,
        "general_pdfs": general_pdfs,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}")

    all_pdfs = sorted(set(general_pdfs) | {k["manual"] for k in deduped})
    OUT_PDFS.write_text("\n".join(all_pdfs) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PDFS} ({len(all_pdfs)} unique PDFs)")


if __name__ == "__main__":
    main()
