"""
Parse Meyer 2023-2024 Application & Product Guide PDF (pages 3-10)
into structured JSON at refs/meyer/meyer_app_guide.json.

Strategy: single top-to-bottom pass through word bounding-boxes on each page.
Detect make headers, column headers (to learn plow-column x-positions), and
data rows (year-starting lines) in document order.

Usage:  python app/scripts/parse_meyer_app_guide.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import fitz  # pymupdf

PDF_PATH = Path("refs/meyer/Meyer-Application-Guide-2023-2024.pdf")
OUT_PATH = Path("refs/meyer/meyer_app_guide.json")

# Plow column names per mount system
EZ_MOUNT_PLUS_PLOWS = [
    "DP 6'8\"", "DP 7'6\"", "LPLD", "LP", "SB", "DE", "SV 7'6\"", "SV", "RP-32",
]
DRIVE_PRO_PLOWS = ["DP 6'8\"", "DP 7'6\""]
EZ_MOUNT_CLASSIC_PLOWS = [
    "DP 6'8\"", "DP 7'6\"", "LPLD", "LP", "DE", "SV 7'6\"", "SV", "RP-32",
]

YEAR_RE = re.compile(r"^(19\d{2}|20[0-4]\d)$")  # 1900-2049 only
MOUNT_RE = re.compile(r"^(1[6-8]\d{3}(?:DP)?)([!*]?)$")
HEADLIGHT_CODE_RE = re.compile(r"^0[78]\d{3}$")

MAKE_KEYWORDS = {
    "CHEVROLET/GMC", "DODGE/RAM", "DODGE", "FORD", "HINO", "INTERNATIONAL",
    "MITSUBISHI", "NISSAN", "TOYOTA", "HUMMER", "JEEP",
}


def group_lines(words, threshold=5):
    """Group words into horizontal lines by y-proximity."""
    if not words:
        return []
    ws = sorted(words, key=lambda w: (w[1], w[0]))
    lines = []
    cur = [ws[0]]
    for w in ws[1:]:
        if abs(w[1] - cur[0][1]) <= threshold:
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda x: x[0]))
            cur = [w]
    lines.append(sorted(cur, key=lambda x: x[0]))
    return lines


def detect_plow_centres(all_header_words):
    """
    Given ALL words from the header region (may span 2-3 lines), detect
    plow-column x-centres.  DP/SV labels and their 6'8"/7'6" qualifiers
    may be on the same line (Drive Pro) or stacked (EZ Mount Plus).
    """
    centres = {}

    # Gather qualifiers (6'8", 7'6") from all header words
    quals = [w for w in all_header_words if w[4].strip() in ("6'8\"", "7'6\"")]

    # Find DP tokens in ALL header words
    dp_tokens = sorted(
        [w for w in all_header_words if w[4].strip() == "DP"],
        key=lambda w: w[0],
    )
    for dt in dp_tokens:
        dt_cx = (dt[0] + dt[2]) / 2
        dt_y = dt[1]
        # Look for qualifier: either directly below (|dy| < 15, |dx| < 15)
        # or immediately to the right on the same line (dy ~ 0, qualifier x > dt x)
        best_q = None
        best_score = 999
        for q in quals:
            q_cx = (q[0] + q[2]) / 2
            dx = abs(q_cx - dt_cx)
            dy = abs(q[1] - dt_y)
            # Below: dx < 15, dy < 15
            # Right-of: dy < 5, q starts after dt ends, gap < 20
            if dy < 15 and dx < 15:
                score = dx + dy
            elif dy < 5 and q[0] > dt[2] - 2 and q[0] - dt[2] < 20:
                score = q[0] - dt[2]  # prefer closer
            else:
                continue
            if score < best_score:
                best_score = score
                best_q = q
        if best_q:
            sz = best_q[4].strip()
            # Use midpoint of the combined DP + qualifier span as the column centre
            combined_cx = (dt[0] + best_q[2]) / 2
            if "6" in sz and "8" in sz:
                centres["DP 6'8\""] = combined_cx
            elif "7" in sz and "6" in sz:
                centres["DP 7'6\""] = combined_cx
            quals = [q for q in quals if q is not best_q]

    # Find SV tokens
    sv_tokens = sorted(
        [w for w in all_header_words if w[4].strip() == "SV"],
        key=lambda w: w[0],
    )
    for st in sv_tokens:
        st_cx = (st[0] + st[2]) / 2
        st_y = st[1]
        best_q = None
        best_score = 999
        for q in quals:
            q_cx = (q[0] + q[2]) / 2
            dx = abs(q_cx - st_cx)
            dy = abs(q[1] - st_y)
            if dy < 15 and dx < 15:
                score = dx + dy
            elif dy < 5 and q[0] > st[2] - 2 and q[0] - st[2] < 20:
                score = q[0] - st[2]
            else:
                continue
            if score < best_score:
                best_score = score
                best_q = q
        if best_q:
            combined_cx = (st[0] + best_q[2]) / 2
            centres["SV 7'6\""] = combined_cx
            quals = [q for q in quals if q is not best_q]
        else:
            centres["SV"] = st_cx

    # Single-token columns
    for tok in ("LPLD", "LP", "SB", "DE", "RP-32"):
        for w in all_header_words:
            if w[4].strip() == tok:
                centres[tok] = (w[0] + w[2]) / 2
                break

    return centres


def detect_make(line_text):
    """Return normalised make name or None."""
    t = line_text.strip()
    t = re.sub(r"^\d+\s*", "", t)
    t = re.sub(r"\s*\(CONT\.?\)\s*$", "", t, flags=re.IGNORECASE)
    t = t.strip()
    if t in MAKE_KEYWORDS:
        return t
    if "HEAVY DUTY" in t.upper() and "BUMPER" in t.upper():
        return "HEAVY DUTY UNIVERSAL"
    return None


def is_column_header_line(line_words):
    """Check if a line is a column header (contains Year + Vehicle or DP tokens)."""
    tokens = {w[4].strip() for w in line_words}
    if "Year" in tokens and ("Vehicle" in tokens or "Description" in tokens):
        return True
    # Also catch the sub-header line with DP / Headlight
    if "DP" in tokens and ("Headlight" in tokens or "SV" in tokens):
        return True
    return False


def is_category_line(text):
    """Detect sub-category headers like '1/2 Ton (1500)'."""
    t = text.strip()
    if re.match(r"^(Compact Trucks|1/2 Ton|3/4 Ton|Medium Duty)", t, re.IGNORECASE):
        return True
    return False


def is_noise(text):
    """Filter out noise lines."""
    t = text.strip()
    if not t or t == "v":
        return True
    if re.match(r"^\d+$", t):
        return True
    if t.startswith("* ") or t.startswith("! "):
        return True
    if "Installation requires" in t or "SV3" in t:
        return True
    if t in ("Discontinued", "! Discontinued"):
        return True
    if "MOUNT SELECTION" in t.upper():
        return True
    return False


def parse_page(page, mount_system, plow_cols_for_system):
    """
    Parse a single page, returning extracted rows and updated state
    (current_make, current plow_centres).
    """
    words = page.get_text("words")
    words.sort(key=lambda w: (w[1], w[0]))
    lines = group_lines(words)

    rows = []
    current_make = None
    plow_centres = {}
    pending = None  # accumulator for the current data row
    orphan_buffer = []  # words from lines between rows that may belong to next row

    for li, line_words in enumerate(lines):
        line_text = " ".join(w[4] for w in line_words)
        y = line_words[0][1]

        # 1) Make header?
        mk = detect_make(line_text)
        if mk:
            if pending:
                r = finalise_row(pending, plow_centres, plow_cols_for_system, mount_system)
                if r:
                    rows.append(r)
                pending = None
            orphan_buffer = []
            current_make = mk
            continue

        # 2) Column header line? -> update plow centres
        if is_column_header_line(line_words):
            if pending:
                r = finalise_row(pending, plow_centres, plow_cols_for_system, mount_system)
                if r:
                    rows.append(r)
                pending = None
            # Gather words from this line and 2 lines above/below for
            # qualifier detection (DP/SV headers may be split across lines)
            nearby = []
            for li2 in range(max(0, li - 2), min(len(lines), li + 3)):
                nearby.extend(lines[li2])
            new_centres = detect_plow_centres(nearby)
            if new_centres:
                plow_centres = new_centres
            continue

        # 3) Category or noise?
        if is_category_line(line_text) or is_noise(line_text):
            continue

        # 4) Data row start? (line has a 4-digit year token or "ALL" in x < 170)
        year_words = [w for w in line_words
                      if (YEAR_RE.match(w[4].strip()) or w[4].strip() == "ALL")
                      and w[0] < 170]
        starts_new_row = bool(year_words) and current_make is not None

        if starts_new_row:
            # Flush pending
            if pending:
                # Before flushing, check if orphan_buffer words should go to
                # this new row instead (they appeared between the old row and
                # this new year line).
                if orphan_buffer:
                    # If the orphan words are closer to THIS year line than the
                    # pending row's year line, steal them.
                    new_y = y
                    pending_y = pending.get("year_y", 0)
                    orphan_y = orphan_buffer[0][1]
                    if abs(orphan_y - new_y) < abs(orphan_y - pending_y):
                        # Orphans belong to new row -- remove from pending
                        pending["words"] = [
                            w for w in pending["words"]
                            if w not in orphan_buffer
                        ]

                r = finalise_row(pending, plow_centres, plow_cols_for_system, mount_system)
                if r:
                    rows.append(r)
            pending = {
                "make": current_make,
                "words": list(line_words),
                "year_y": y,
            }
            # Prepend orphan buffer to new row if it exists
            if orphan_buffer:
                pending["words"] = orphan_buffer + pending["words"]
            orphan_buffer = []
        elif pending:
            # Check if this continuation line is close enough to the pending row.
            # Use the latest y among pending words (not the year_y) to judge
            # proximity, so multi-line rows extend naturally.
            last_pending_y = max(w[1] for w in pending["words"])
            gap = y - last_pending_y
            if gap > 12:
                # Too far from the current row -- buffer as potential start of next row
                orphan_buffer = list(line_words)
            else:
                pending["words"].extend(line_words)
                orphan_buffer = []
        else:
            # No pending row yet -- buffer these words
            orphan_buffer = list(line_words)

    # Flush final pending
    if pending:
        r = finalise_row(pending, plow_centres, plow_cols_for_system, mount_system)
        if r:
            rows.append(r)

    return rows, current_make, plow_centres


def finalise_row(pending, plow_centres, plow_cols, mount_system):
    """Convert pending word accumulator into a row dict."""
    make = pending["make"]
    all_words = pending["words"]

    # Sort words by position
    all_words_sorted = sorted(all_words, key=lambda w: (w[1], w[0]))
    full_text = " ".join(w[4] for w in all_words_sorted)

    # --- Years ---
    # Check for "ALL" (universal fitment, no year range)
    has_all = any(w[4].strip() == "ALL" and w[0] < 170 for w in all_words_sorted)
    thru_match = re.search(r"THRU\s+(\d{4})", full_text, re.IGNORECASE)

    if has_all:
        year_start = None
        year_end = None
    elif thru_match:
        year_start = None
        year_end = int(thru_match.group(1))
    else:
        # Find year tokens in the year column (x < 170)
        year_tokens = [int(w[4]) for w in all_words_sorted
                       if YEAR_RE.match(w[4].strip()) and w[0] < 170]
        if len(year_tokens) >= 2:
            year_start = year_tokens[0]
            year_end = year_tokens[1]
        elif len(year_tokens) == 1:
            year_start = year_tokens[0]
            year_end = year_tokens[0]
        else:
            return None

    # --- Classify each word by role ---
    min_plow_x = min(plow_centres.values()) - 25 if plow_centres else 9999

    mount_sku = None
    discontinued = False
    vehicle_parts = []
    headlight_parts = []
    x_mark_positions = []

    for w in all_words_sorted:
        token = w[4].strip()
        wx = w[0]
        wcx = (w[0] + w[2]) / 2

        # Skip year-column tokens
        if YEAR_RE.match(token) and wx < 170:
            continue
        if token.lower() == "to" and wx < 170:
            continue
        if token.upper() in ("THRU", "ALL") and wx < 170:
            continue

        # X marks -- always treat as plow compatibility marks, never vehicle text
        if token in ("X", "X*"):
            x_mark_positions.append(wcx)
            continue

        # Mount SKU
        mm = MOUNT_RE.match(token)
        if mm and mount_sku is None:
            mount_sku = mm.group(1)
            if mm.group(2) in ("!", "*"):
                discontinued = True
            continue

        # Standalone ! or * after mount
        if token in ("!", "*") and mount_sku:
            discontinued = True
            continue

        # Headlight code: bare 5-digit (07xxx, 08xxx) or with suffix like 07777(STD)
        if HEADLIGHT_CODE_RE.match(token):
            headlight_parts.append(token)
            continue
        # Compound: 07xxx(STD), 07xxx(LED), 07747(HID), possibly with trailing comma
        hl_compound = re.match(r"^(0[78]\d{3})\((\w+)\)[,]?$", token)
        if hl_compound:
            headlight_parts.append(f"{hl_compound.group(1)} ({hl_compound.group(2)})")
            continue

        # SOS / Pgs references (headlight adapter alternatives)
        # Only classify these as headlight if they're past the mount-column x position
        # (to avoid catching "ONLY" in vehicle text like "SUPER CAB ONLY")
        if token.lower() in ("use", "sos", "system", "only") and wx > 230:
            headlight_parts.append(token)
            continue
        if token in ("Pgs.", "118-119"):
            headlight_parts.append(token)
            continue

        # Headlight qualifiers in parens (with optional trailing comma)
        if re.match(r"^\((STD|LED|HID|Halogen|std|led)\),?$", token):
            headlight_parts.append(token.rstrip(","))
            continue
        if token == "or" and wcx > 250:
            headlight_parts.append(token)
            continue

        # Skip column header words that leaked into data rows
        if token in ("Headlight", "Adapter", "Light", "adapter"):
            continue

        # Remaining text to the left of plow columns = vehicle description
        if wcx < min_plow_x:
            vehicle_parts.append(token)

    if not mount_sku:
        return None

    # --- Build strings ---
    vehicle = " ".join(vehicle_parts).strip()
    vehicle = re.sub(r"\s+", " ", vehicle)

    hl_raw = " ".join(headlight_parts)
    hl_raw = re.sub(r"(?i)use\s+sos\s+system\s+only", "Use SOS system only", hl_raw)
    hl_raw = re.sub(r"Pgs?\.\s*118[\s-]*119", "Pgs. 118-119", hl_raw)
    headlight = hl_raw.strip()

    # --- Map X marks to plow columns ---
    compatible = []
    for xpos in x_mark_positions:
        best_col = None
        best_dist = 35
        for col_name, col_cx in plow_centres.items():
            d = abs(xpos - col_cx)
            if d < best_dist:
                best_dist = d
                best_col = col_name
        if best_col and best_col not in compatible:
            compatible.append(best_col)

    col_order = {c: i for i, c in enumerate(plow_cols)}
    compatible.sort(key=lambda p: col_order.get(p, 99))

    row = {
        "make": make,
        "year_start": year_start,
        "year_end": year_end,
        "model": vehicle,
        "mount_sku": mount_sku,
        "headlight_adapter": headlight,
        "mount_system": mount_system,
        "compatible_plows": compatible,
    }
    if discontinued:
        row["discontinued"] = True

    return row


def main():
    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        sys.exit(1)

    doc = fitz.open(str(PDF_PATH))
    print(f"Opened PDF: {doc.page_count} pages")

    all_rows = []

    sections = [
        ([2, 3, 4, 5], "EZ Mount Plus", EZ_MOUNT_PLUS_PLOWS),
        ([6, 7], "Drive Pro", DRIVE_PRO_PLOWS),
        ([8, 9], "EZ Mount Classic", EZ_MOUNT_CLASSIC_PLOWS),
    ]

    for page_indices, mount_system, plow_cols in sections:
        carry_make = None
        carry_centres = {}
        for pi in page_indices:
            page = doc[pi]
            rows, last_make, last_centres = parse_page(page, mount_system, plow_cols)
            # If the page didn't find its own make, inherit from previous page
            # (for continuation pages)
            if not rows and carry_make:
                pass  # nothing to adjust
            elif rows and rows[0]["make"] and not last_make:
                pass
            all_rows.extend(rows)
            if last_make:
                carry_make = last_make
            if last_centres:
                carry_centres = last_centres
            print(f"  Page {pi+1} ({mount_system}): {len(rows)} rows")

    doc.close()

    output = {
        "source": "Meyer 2023-2024 Application & Product Guide",
        "rows": all_rows,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(all_rows)} rows to {OUT_PATH}")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    makes = defaultdict(lambda: {"skus": set(), "year_min": 9999, "year_max": 0,
                                  "discontinued": 0, "total": 0})
    for r in all_rows:
        mk = r["make"]
        makes[mk]["skus"].add(r["mount_sku"])
        if r.get("year_start"):
            makes[mk]["year_min"] = min(makes[mk]["year_min"], r["year_start"])
        if r.get("year_end"):
            makes[mk]["year_max"] = max(makes[mk]["year_max"], r["year_end"])
        if r.get("discontinued"):
            makes[mk]["discontinued"] += 1
        makes[mk]["total"] += 1

    all_skus = set()
    all_disc = 0
    for mk in sorted(makes.keys()):
        info = makes[mk]
        all_skus |= info["skus"]
        all_disc += info["discontinued"]
        yr = f"{info['year_min']}-{info['year_max']}" if info["year_min"] < 9999 else "N/A"
        print(f"  {mk:40s}  {info['total']:3d} rows  {len(info['skus']):3d} unique mounts  "
              f"years {yr:12s}  {info['discontinued']} discontinued")

    print(f"\n  TOTAL: {len(all_rows)} rows, {len(all_skus)} unique mount SKUs, "
          f"{all_disc} discontinued entries")

    print("\nBy mount system:")
    for ms in ["EZ Mount Plus", "Drive Pro", "EZ Mount Classic"]:
        ms_rows = [r for r in all_rows if r["mount_system"] == ms]
        ms_skus = {r["mount_sku"] for r in ms_rows}
        print(f"  {ms:20s}  {len(ms_rows):3d} rows  {len(ms_skus):3d} unique mounts")


if __name__ == "__main__":
    main()
