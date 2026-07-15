"""
V3 — Extract highlighted product images from Buyers Products installation PDFs.

Per part:
1. Parse ITEM/PART NO./QTY./DESCRIPTION table from text layer
2. Find callout bubble positions on diagram pages
3. Trace leader lines from callout bubbles to part locations
4. Find part's vector drawings via:
   a) Ground truth polygon if available  (human annotations)
   b) Improved BFS flood-fill from leader endpoint (automated)
5. PRIMARY  : cropped view with contour spotlight dimming
   — Vector-path mask follows exact part shape (lines, bezier curves, rects)
   — Everything outside the mask fades to near-white (opacity 210)
   — Feathered edge via MaxFilter dilation + Gaussian blur
6. SECONDARY: full exploded view with callout number highlighted
   — No part shape highlighting — clean reference diagram
   — Part's item number circled with bright yellow ring

Technique notes (for reuse on future PDFs):
  The contour mask is built from the part's raw PyMuPDF vector paths:
   • Lines → thick (pad*1.5) white strokes on a black mask
   • Bezier curves → sampled at 24 points, drawn as thick polyline
   • Rectangles → filled with pad-pixel expansion
   • Closed paths → polygon-filled
   Then dilated (MaxFilter, odd kernel) and Gaussian-blurred (sigma=pad*0.7)
   to produce a soft feathered edge. Compositing:
     dimmed = blend(base, white, 210/255)
     output = composite(base, dimmed, mask)
   Part area stays at full contrast; surrounding context fades.

Usage:
    python extract_pdf_part_images.py                          # all PDFs
    python extract_pdf_part_images.py --pdf 16061030INST_B.pdf # one PDF
    python extract_pdf_part_images.py --pn 16061031            # one part
    python extract_pdf_part_images.py --dry-run                # table only
"""
from __future__ import annotations
import argparse, json, math, re, sys
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

try:
    import fitz
except ImportError:
    print("ERROR: pip install PyMuPDF"); sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    Image = None

# Defaults — overridden by --pdf-dir / --out-dir CLI args
PDF_DIR = Path("/tmp/buyers_pdfs")
OUT_DIR = Path("/tmp/buyers_pdf_images")
GT_DIR  = Path("/tmp/buyers_pdfs/ground_truth")   # optional annotation JSONs

# ── Geometry helpers ──────────────────────────────────────────────

def _dist(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

def _rect_center(r):
    return ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)

def _rect_area(r):
    return max(0, r.x1 - r.x0) * max(0, r.y1 - r.y0)

def _rects_overlap(r1, r2, margin=2):
    return not (r1.x1 + margin < r2.x0 or r2.x1 + margin < r1.x0 or
                r1.y1 + margin < r2.y0 or r2.y1 + margin < r1.y0)

def _point_in_polygon(px, py, polygon):
    """Ray casting point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def _find_table_top_y(page) -> float:
    """Find y where the parts table begins (separates diagram from table).

    Ignores label hits in the top 40% of the page — Western PDFs put
    'PARTS LIST' as a heading near the top, not at the actual table.
    """
    min_y = page.rect.height * 0.40
    for label in ["Parts List", "ITEM", "PART NO"]:
        hits = page.search_for(label)
        valid = [h.y0 for h in hits if h.y0 >= min_y]
        if valid:
            return min(valid)
    return page.rect.height * 0.65


# ── Contour mask helpers ─────────────────────────────────────────

def _bezier_points(p0, p1, p2, p3, steps=24):
    """Sample a cubic bezier curve into polyline points."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = ((1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] +
             3*(1-t)*t**2*p2[0] + t**3*p3[0])
        y = ((1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] +
             3*(1-t)*t**2*p2[1] + t**3*p3[1])
        pts.append((x, y))
    return pts


def _draw_part_mask(part_dwgs, crop, scale, img_size, pad=12):
    """Build a feathered mask from part vector paths.

    White pixels = part area (stays at full contrast).
    Black pixels = background (fades to white in final composite).
    The mask is dilated and Gaussian-blurred for a soft feathered edge.
    """
    mask = Image.new('L', img_size, 0)
    draw = ImageDraw.Draw(mask)

    for d in part_dwgs:
        items = d.get('items', [])
        path_pts = []
        for item in items:
            if item[0] == 'l':
                x1 = (item[1].x - crop.x0) * scale
                y1 = (item[1].y - crop.y0) * scale
                x2 = (item[2].x - crop.x0) * scale
                y2 = (item[2].y - crop.y0) * scale
                path_pts.extend([(x1, y1), (x2, y2)])
                draw.line([(x1, y1), (x2, y2)], fill=255,
                          width=int(pad * 1.5))
            elif item[0] == 'c':
                p0 = ((item[1].x - crop.x0) * scale,
                      (item[1].y - crop.y0) * scale)
                p1 = ((item[2].x - crop.x0) * scale,
                      (item[2].y - crop.y0) * scale)
                p2 = ((item[3].x - crop.x0) * scale,
                      (item[3].y - crop.y0) * scale)
                p3 = ((item[4].x - crop.x0) * scale,
                      (item[4].y - crop.y0) * scale)
                bpts = _bezier_points(p0, p1, p2, p3, steps=24)
                path_pts.extend(bpts)
                for j in range(len(bpts) - 1):
                    draw.line([bpts[j], bpts[j + 1]], fill=255,
                              width=int(pad * 1.5))
            elif item[0] == 're':
                r = item[1]
                x0 = (r.x0 - crop.x0) * scale
                y0 = (r.y0 - crop.y0) * scale
                x1 = (r.x1 - crop.x0) * scale
                y1 = (r.y1 - crop.y0) * scale
                draw.rectangle([x0 - pad, y0 - pad, x1 + pad, y1 + pad],
                               fill=255)
                path_pts.extend([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

        # Fill the interior of closed paths
        if len(path_pts) >= 3 and d.get('closePath', False):
            draw.polygon(path_pts, fill=255)

    # Dilate then blur for soft feathered edge
    fs = int(pad) | 1  # MaxFilter requires odd kernel
    mask = mask.filter(ImageFilter.MaxFilter(fs))
    mask = mask.filter(ImageFilter.GaussianBlur(pad * 0.7))
    return mask


# ── Description-based classification ─────────────────────────────

FASTENER_KW = [
    'screw', 'bolt', 'nut', 'washer', 'locknut', 'rivet', 'pin',
    'cotter', 'fastener', 'cap screw', 'hex hd', 'hex head', 'flange'
]
SMALL_PART_KW = [
    'spacer', 'tab', 'tube', 'bushing', 'clip', 'grommet', 'sleeve'
]
VEHICLE_KW = ['truck frame', 'vehicle', 'existing', 'tow hook']

def _classify(description: str) -> str:
    d = description.lower()
    if any(kw in d for kw in VEHICLE_KW):   return 'vehicle'
    if any(kw in d for kw in FASTENER_KW):  return 'fastener'
    if any(kw in d for kw in SMALL_PART_KW): return 'small'
    return 'structural'

def _size_limits(cls):
    """(min_area, max_area, max_drawings, leash_radius)"""
    if cls == 'fastener':    return (1, 800, 20, 40)
    if cls == 'small':       return (2, 2000, 25, 60)
    if cls == 'structural':  return (5, 50000, 70, 150)
    return (20, 200000, 120, 250)  # vehicle

# ── Data classes ─────────────────────────────────────────────────

@dataclass
class PartEntry:
    item_no: int
    part_number: str
    qty: int
    description: str
    classification: str = ""
    callout_rect: Optional[tuple] = None
    callout_page: Optional[int] = None
    part_position: Optional[tuple] = None
    leader_direction: Optional[tuple] = None

@dataclass
class PdfParts:
    pdf_name: str
    parent_pn: str
    parts: list[PartEntry] = field(default_factory=list)
    diagram_pages: list[int] = field(default_factory=list)
    table_pages: list[int] = field(default_factory=list)


# ── Phase 1: parse parts table ───────────────────────────────────

def parse_parts_table(doc: fitz.Document) -> PdfParts:
    filename = Path(doc.name).stem
    m = re.match(r'(\d{7,10})', filename)
    parent_pn = m.group(1) if m else filename
    result = PdfParts(pdf_name=Path(doc.name).name, parent_pn=parent_pn)

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        text = page.get_text("text")
        if re.search(r'ITEM\s+PART\s*NO', text, re.IGNORECASE) or \
           (re.search(r'\bItem\b', text) and re.search(r'\bQty\b', text)):
            result.table_pages.append(page_idx)
        if len(page.get_drawings()) > 50:
            result.diagram_pages.append(page_idx)

        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # One-line format: "1  16061031  2  PUSHBAR, F650"
            m2 = re.match(r'^(\d{1,3})\s+(\d{5,10}[A-Z]?)\s+(\d{1,3})\s+(.+)$', line)
            if m2:
                result.parts.append(PartEntry(
                    int(m2.group(1)), m2.group(2),
                    int(m2.group(3)), m2.group(4).strip()))
                i += 1; continue
            # Multi-line format: item_no / part_no / qty / description
            if re.match(r'^\d{1,3}$', line):
                item_no = int(line)
                if i + 1 < len(lines):
                    pn_line = lines[i+1].strip()
                    pn_m = re.match(
                        r'^(\d{5,10}[A-Z]?|[A-Z]{2,5}\d{5,10}[A-Z]?|'
                        r'[A-Z0-9]{6,20})$', pn_line)
                    if pn_m:
                        pn = pn_m.group(1); qty = 1; desc = ""
                        if i + 2 < len(lines):
                            ql = lines[i+2].strip()
                            if re.match(r'^\d{1,3}$', ql):
                                qty = int(ql)
                                desc = lines[i+3].strip() if i+3 < len(lines) else ""
                                i += 4
                            else:
                                desc = ql; i += 3
                        else:
                            i += 2
                        result.parts.append(PartEntry(item_no, pn, qty, desc))
                        continue
            i += 1

    seen = set()
    unique = []
    for p in result.parts:
        key = (p.item_no, p.part_number)
        if key not in seen:
            seen.add(key)
            p.classification = _classify(p.description)
            unique.append(p)
    result.parts = sorted(unique, key=lambda p: p.item_no)
    return result


# ── Phase 2: find callout positions ──────────────────────────────

def find_callout_positions(doc, pdf_parts):
    if not pdf_parts.diagram_pages:
        pdf_parts.diagram_pages = list(range(min(doc.page_count, 3)))
    callout_nums = {p.item_no for p in pdf_parts.parts}

    for page_idx in pdf_parts.diagram_pages:
        page = doc[page_idx]
        table_y = _find_table_top_y(page)
        for item_no in callout_nums:
            for inst in page.search_for(str(item_no)):
                if inst.y0 >= table_y:
                    continue
                exp = fitz.Rect(inst.x0-8, inst.y0-3, inst.x1+8, inst.y1+3)
                if page.get_text("text", clip=exp).strip() == str(item_no):
                    for part in pdf_parts.parts:
                        if part.item_no == item_no and part.callout_rect is None:
                            part.callout_rect = (inst.x0, inst.y0, inst.x1, inst.y1)
                            part.callout_page = page_idx
                            break
                    break


# ── Phase 3: trace leader lines ──────────────────────────────────

def _build_seg_index(segments, grid=5):
    """Spatial index: rounded endpoint → list of (seg, other_end)."""
    idx = defaultdict(list)
    for p1, p2 in segments:
        k1 = (round(p1[0] / grid) * grid, round(p1[1] / grid) * grid)
        k2 = (round(p2[0] / grid) * grid, round(p2[1] / grid) * grid)
        idx[k1].append(((p1, p2), p2))
        idx[k2].append(((p1, p2), p1))
    return idx


def _trace_leader(segments, cx, cy, seg_idx, radius=25, grid=5):
    """Trace ALL leader line chains from callout. Returns (endpoint, direction, visited).

    Uses spatial index for O(1) chain following instead of scanning all segments.
    Follows every segment chain emanating from the callout bubble for up to 20
    hops so the full leader — including arrowhead segments — is in visited.
    """
    nearby = []
    for p1, p2 in segments:
        d1 = _dist(p1, (cx, cy))
        d2 = _dist(p2, (cx, cy))
        if d1 < radius:
            nearby.append({"near": p1, "far": p2, "dist": d1, "seg": (p1, p2)})
        elif d2 < radius:
            nearby.append({"near": p2, "far": p1, "dist": d2, "seg": (p1, p2)})
    if not nearby:
        return None, None, set()

    nearby.sort(key=lambda x: x["dist"])

    all_visited = set()
    best_endpoint = nearby[0]["far"]
    best_dist = 0

    # Follow EVERY chain radiating from the callout
    for start in nearby:
        if start["seg"] in all_visited:
            continue
        current_end = start["far"]
        chain = {start["seg"]}

        for _ in range(20):
            k = (round(current_end[0] / grid) * grid,
                 round(current_end[1] / grid) * grid)
            found = False
            # Check grid cell and neighbors
            for dx in (-grid, 0, grid):
                if found: break
                for dy in (-grid, 0, grid):
                    if found: break
                    for seg, other in seg_idx.get((k[0]+dx, k[1]+dy), []):
                        if seg in chain:
                            continue
                        # Check which end is near current_end
                        if _dist(seg[0], current_end) < 5:
                            current_end = seg[1]
                            chain.add(seg); found = True; break
                        elif _dist(seg[1], current_end) < 5:
                            current_end = seg[0]
                            chain.add(seg); found = True; break
            if not found:
                break

        all_visited.update(chain)
        d = _dist(current_end, (cx, cy))
        if d > best_dist:
            best_dist = d
            best_endpoint = current_end

    dx = best_endpoint[0] - cx
    dy = best_endpoint[1] - cy
    length = _dist(best_endpoint, (cx, cy))
    direction = (dx / length, dy / length) if length > 0 else (0, 0)

    return best_endpoint, direction, all_visited


def trace_leader_lines(doc, pdf_parts):
    """Trace leaders for all parts. Returns (all_leader_segs, callout_positions)."""
    all_leader_segs = set()
    _page_cache = {}

    for p in pdf_parts.parts:
        if not p.callout_rect or p.callout_page is None:
            continue
        cx = (p.callout_rect[0] + p.callout_rect[2]) / 2
        cy = (p.callout_rect[1] + p.callout_rect[3]) / 2

        # Cache segments + spatial index per page
        if p.callout_page not in _page_cache:
            page = doc[p.callout_page]
            segments = []
            for d in page.get_drawings():
                for item in d.get("items", []):
                    if item[0] == "l":
                        segments.append(((item[1].x, item[1].y),
                                         (item[2].x, item[2].y)))
            _page_cache[p.callout_page] = (segments, _build_seg_index(segments))

        segments, seg_idx = _page_cache[p.callout_page]
        endpoint, direction, leader_segs = _trace_leader(
            segments, cx, cy, seg_idx)
        if endpoint:
            p.part_position = endpoint
            p.leader_direction = direction
            all_leader_segs.update(leader_segs)

    return all_leader_segs


# ── Phase 4a: drawing helpers ────────────────────────────────────

def _get_drawing_points(drawing):
    """All coordinate points from a drawing, including bezier samples."""
    pts = []
    for item in drawing.get("items", []):
        if item[0] == "l":
            pts.append((item[1].x, item[1].y))
            pts.append((item[2].x, item[2].y))
        elif item[0] == "c":
            p0 = (item[1].x, item[1].y)
            p3 = (item[4].x, item[4].y)
            pts.extend([p0, p3])
            # Sample curve at 25%, 50%, 75%
            p1 = (item[2].x, item[2].y)
            p2 = (item[3].x, item[3].y)
            for t in [0.25, 0.5, 0.75]:
                bx = ((1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] +
                      3*(1-t)*t**2*p2[0] + t**3*p3[0])
                by = ((1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] +
                      3*(1-t)*t**2*p2[1] + t**3*p3[1])
                pts.append((bx, by))
        elif item[0] == "re":
            r = item[1]
            pts.extend([(r.x0, r.y0), (r.x1, r.y0),
                        (r.x0, r.y1), (r.x1, r.y1)])
    return pts

def _drawing_endpoints(d):
    """Just start/end points (for BFS connectivity)."""
    pts = []
    for item in d.get("items", []):
        if item[0] == "l":
            pts += [(round(item[1].x, 1), round(item[1].y, 1)),
                    (round(item[2].x, 1), round(item[2].y, 1))]
        elif item[0] == "c":
            pts += [(round(item[1].x, 1), round(item[1].y, 1)),
                    (round(item[4].x, 1), round(item[4].y, 1))]
    return pts

def _min_pt_dist(d, px, py):
    best = float("inf")
    for pt in _get_drawing_points(d):
        best = min(best, _dist(pt, (px, py)))
    return best

def _build_leader_index(leader_segments, callout_positions, grid=10):
    """Pre-compute spatial indices for fast leader detection.

    Returns (leader_pt_set, callout_pt_set) — each a set of rounded grid keys.
    """
    leader_pts = set()
    for p1, p2 in leader_segments:
        leader_pts.add((round(p1[0] / grid) * grid, round(p1[1] / grid) * grid))
        leader_pts.add((round(p2[0] / grid) * grid, round(p2[1] / grid) * grid))
    callout_pts = set()
    for cp in callout_positions:
        # Cover a radius of ~20px → ±2 grid cells at grid=10
        gx, gy = round(cp[0] / grid) * grid, round(cp[1] / grid) * grid
        for dx in (-grid, 0, grid):
            for dy in (-grid, 0, grid):
                callout_pts.add((gx + dx, gy + dy))
    return leader_pts, callout_pts


def _is_leader_drawing(drawing, leader_segments, callout_positions,
                       leader_idx=None, tolerance=8, grid=10):
    """Check if drawing is a leader line, arrowhead, or callout bubble.

    Uses spatial indices (leader_idx) when provided for O(1) lookups.
    """
    items = drawing.get("items", [])
    if leader_idx:
        leader_pts, callout_pts = leader_idx
    else:
        leader_pts, callout_pts = _build_leader_index(
            leader_segments, callout_positions, grid)

    # 1. Match against traced leader segments via spatial hash
    for item in items:
        if item[0] == "l":
            p1 = (item[1].x, item[1].y)
            p2 = (item[2].x, item[2].y)
            k1 = (round(p1[0] / grid) * grid, round(p1[1] / grid) * grid)
            k2 = (round(p2[0] / grid) * grid, round(p2[1] / grid) * grid)
            # Both endpoints near leader endpoints → likely a leader segment
            if k1 in leader_pts and k2 in leader_pts:
                # Confirm with exact check against original segments
                for lp1, lp2 in leader_segments:
                    if ((_dist(p1, lp1) < tolerance and _dist(p2, lp2) < tolerance) or
                        (_dist(p1, lp2) < tolerance and _dist(p2, lp1) < tolerance)):
                        return True

    # 2. Line-only drawings with endpoint touching a callout = leader/arrowhead
    has_curves = any(item[0] == "c" for item in items)
    if not has_curves:
        for item in items:
            if item[0] == "l":
                p1 = (item[1].x, item[1].y)
                p2 = (item[2].x, item[2].y)
                k1 = (round(p1[0] / grid) * grid, round(p1[1] / grid) * grid)
                k2 = (round(p2[0] / grid) * grid, round(p2[1] / grid) * grid)
                if k1 in callout_pts or k2 in callout_pts:
                    # Confirm with exact distance
                    for cp in callout_positions:
                        if _dist(p1, cp) < 18 or _dist(p2, cp) < 18:
                            return True

    # 3. Short line segments near leader endpoints = arrowheads
    if not has_curves and len(items) <= 4:
        for item in items:
            if item[0] == "l":
                p1 = (item[1].x, item[1].y)
                p2 = (item[2].x, item[2].y)
                if _dist(p1, p2) < 15:
                    k1 = (round(p1[0] / grid) * grid, round(p1[1] / grid) * grid)
                    k2 = (round(p2[0] / grid) * grid, round(p2[1] / grid) * grid)
                    if k1 in leader_pts or k2 in leader_pts:
                        return True

    # 4. Callout bubbles: small circles near callout positions
    r = drawing["rect"]
    w, h = r.x1 - r.x0, r.y1 - r.y0
    cx, cy = _rect_center(r)
    if w < 25 and h < 25 and abs(w - h) < 8:
        k = (round(cx / grid) * grid, round(cy / grid) * grid)
        if k in callout_pts:
            for cp in callout_positions:
                if _dist((cx, cy), cp) < 20:
                    return True
    return False


# ── Phase 4b: ground truth polygon matching ──────────────────────

def _load_ground_truth(gt_path):
    """Load annotation JSON -> {item_no: [{"polygon": [...], "bbox": {...}}, ...]}"""
    with open(gt_path) as f:
        annotations = json.load(f)
    gt = defaultdict(list)
    for ann in annotations:
        poly = [(p["x"], p["y"]) for p in ann["polygon"]]
        gt[ann["item"]].append({"polygon": poly, "bbox": ann["bbox"]})
    return dict(gt)


def _gt_classify(drawing, ground_truth):
    """Assign drawing to GT polygon. Smallest matching polygon wins."""
    cx, cy = _rect_center(drawing["rect"])
    all_pts = _get_drawing_points(drawing)
    r = drawing["rect"]
    d_area = _rect_area(r)
    d_w, d_h = r.x1 - r.x0, r.y1 - r.y0

    matches = []  # (score, gt_area, item_no)

    for item_no, regions in ground_truth.items():
        for region in regions:
            poly = region["polygon"]
            bbox = region["bbox"]
            gt_w = bbox["x1"] - bbox["x0"]
            gt_h = bbox["y1"] - bbox["y0"]
            gt_area = max(1, gt_w * gt_h)

            # Size guard: reject drawings much larger than polygon
            if gt_area < 1000:
                lim = max(gt_w, gt_h) * 4 + 10
                if d_w > lim or d_h > lim: continue
            elif gt_area < 5000:
                lim = max(gt_w, gt_h) * 3 + 20
                if d_w > lim or d_h > lim: continue

            # Bbox overlap test
            if (r.x1 < bbox["x0"] - 5 or r.x0 > bbox["x1"] + 5 or
                r.y1 < bbox["y0"] - 5 or r.y0 > bbox["y1"] + 5):
                continue

            if gt_area < 400:
                # Small polygon: bbox overlap score
                ox = max(0, min(r.x1, bbox["x1"]) - max(r.x0, bbox["x0"]))
                oy = max(0, min(r.y1, bbox["y1"]) - max(r.y0, bbox["y0"]))
                overlap = ox * oy
                if overlap > 0:
                    score = (overlap / max(1, d_area)) * 1.5 + \
                            (overlap / max(1, gt_area)) * 0.5
                    if score > 0.15:
                        matches.append((score, gt_area, item_no))
            else:
                # Standard polygon containment
                center_in = _point_in_polygon(cx, cy, poly)
                pts_in = sum(1 for px, py in all_pts
                             if _point_in_polygon(px, py, poly))
                frac = pts_in / max(1, len(all_pts))
                score = (2.0 if center_in else 0) + frac
                if score > 0.3:
                    matches.append((score, gt_area, item_no))

    if not matches:
        return None

    # Smallest polygon wins (most specific match)
    matches.sort(key=lambda m: (m[1], -m[0]))
    best = matches[0]
    for m in matches[1:]:
        if m[0] > best[0] * 3 and m[0] > 1.0:
            best = m
    return best[2]


# ── Phase 4c: BFS flood-fill (no ground truth) ──────────────────

def find_part_drawings(page, px, py, direction, classification,
                       callout, leader_segments, callout_positions,
                       table_y, connect_tol=3, leader_idx=None):
    """Improved BFS flood-fill from leader endpoint."""
    min_area, max_area, max_drawings, max_leash = _size_limits(classification)

    # Pre-compute spatial index for leader detection (once per call)
    if leader_idx is None:
        leader_idx = _build_leader_index(leader_segments, callout_positions)

    # Index all diagram drawings, excluding leaders/bubbles
    all_drawings = page.get_drawings()
    candidates = {}
    for i, d in enumerate(all_drawings):
        r = d["rect"]
        if r.y1 > table_y + 5:
            continue
        w, h = r.x1 - r.x0, r.y1 - r.y0
        if w < 0.5 and h < 0.5:
            continue
        if _is_leader_drawing(d, leader_segments, callout_positions,
                              leader_idx=leader_idx):
            continue
        area = _rect_area(r)
        if area < min_area or area > max_area:
            continue
        candidates[i] = (d, r)

    # Find seed drawings near endpoint or along projection
    seeds = set()
    leader_len = _dist((px, py), callout) if callout else 999

    def search_near(sx, sy, radius):
        found = set()
        for idx, (d, rect) in candidates.items():
            if _min_pt_dist(d, sx, sy) <= radius:
                found.add(idx); continue
            cx, cy = _rect_center(rect)
            if _dist((cx, cy), (sx, sy)) <= radius:
                found.add(idx)
        return found

    direct_r = 30 if leader_len > 30 else 12
    seeds = search_near(px, py, direct_r)

    # Project along leader direction
    if direction and (direction[0] != 0 or direction[1] != 0) and not seeds:
        dists = [15, 30, 50, 80, 120] if leader_len < 30 else [20, 40, 60, 80]
        for pd in dists:
            sx = px + direction[0] * pd
            sy = py + direction[1] * pd
            seeds = search_near(sx, sy, 25)
            if seeds:
                break

    if not seeds:
        return []

    # Seed centroid for leash
    seed_rects = [candidates[idx][1] for idx in seeds]
    scx = sum(_rect_center(r)[0] for r in seed_rects) / len(seed_rects)
    scy = sum(_rect_center(r)[1] for r in seed_rects) / len(seed_rects)

    # Build point-to-drawing index
    pt2dwg = defaultdict(set)
    dwg_pts = {}
    for idx, (d, rect) in candidates.items():
        pts = _drawing_endpoints(d)
        dwg_pts[idx] = pts
        for pt in pts:
            qpt = (round(pt[0] / connect_tol) * connect_tol,
                   round(pt[1] / connect_tol) * connect_tol)
            pt2dwg[qpt].add(idx)

    # BFS
    visited = set(seeds)
    queue = list(seeds)
    while queue and len(visited) < max_drawings:
        cur = queue.pop(0)
        cur_rect = candidates[cur][1] if cur in candidates else None

        # Endpoint connectivity
        if cur in dwg_pts:
            for pt in dwg_pts[cur]:
                qpt = (round(pt[0] / connect_tol) * connect_tol,
                       round(pt[1] / connect_tol) * connect_tol)
                for ddx in [-connect_tol, 0, connect_tol]:
                    for ddy in [-connect_tol, 0, connect_tol]:
                        for nidx in pt2dwg.get((qpt[0]+ddx, qpt[1]+ddy), set()):
                            if nidx in visited or nidx not in candidates:
                                continue
                            n_cx, n_cy = _rect_center(candidates[nidx][1])
                            if _dist((n_cx, n_cy), (scx, scy)) > max_leash:
                                continue
                            visited.add(nidx)
                            queue.append(nidx)

        # Spatial overlap (structural/vehicle)
        if cur_rect and classification in ('structural', 'vehicle'):
            for idx, (d, rect) in candidates.items():
                if idx in visited:
                    continue
                if _rects_overlap(cur_rect, rect, margin=5):
                    n_cx, n_cy = _rect_center(rect)
                    if _dist((n_cx, n_cy), (scx, scy)) > max_leash:
                        continue
                    visited.add(idx)
                    queue.append(idx)

    result = [candidates[idx][0] for idx in visited]
    # Post-BFS: strip leader lines via callout proximity + geometry
    result = _remove_leader_chains(result, callout_positions)
    result = _remove_escaping_lines(result)
    return result


def _remove_leader_chains(drawings, callout_positions, connect_tol=5):
    """Post-BFS: remove line-only chains that connect back to a callout."""
    if not callout_positions or not drawings:
        return drawings

    is_line_only = []
    for d in drawings:
        items = d.get("items", [])
        is_line_only.append(
            len(items) > 0 and all(item[0] == "l" for item in items))

    to_remove = set()
    for i, d in enumerate(drawings):
        if not is_line_only[i]:
            continue
        for item in d.get("items", []):
            if item[0] == "l":
                p1 = (item[1].x, item[1].y)
                p2 = (item[2].x, item[2].y)
                for cp in callout_positions:
                    if _dist(p1, cp) < 18 or _dist(p2, cp) < 18:
                        to_remove.add(i)

    if not to_remove:
        return drawings

    for _ in range(8):
        newly = set()
        for i, d in enumerate(drawings):
            if i in to_remove or not is_line_only[i]:
                continue
            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                p1 = (item[1].x, item[1].y)
                p2 = (item[2].x, item[2].y)
                for j in to_remove:
                    for jitem in drawings[j].get("items", []):
                        if jitem[0] != "l":
                            continue
                        jp1 = (jitem[1].x, jitem[1].y)
                        jp2 = (jitem[2].x, jitem[2].y)
                        if (_dist(p1, jp1) < connect_tol or
                            _dist(p1, jp2) < connect_tol or
                            _dist(p2, jp1) < connect_tol or
                            _dist(p2, jp2) < connect_tol):
                            newly.add(i)
        if not newly:
            break
        to_remove.update(newly)

    return [d for i, d in enumerate(drawings) if i not in to_remove]


def _remove_escaping_lines(drawings, margin=20):
    """Geometry-based leader removal that works without callout positions.

    Leader lines are straight segments extending FROM the part shape outward
    toward callout bubbles.  The part shape is defined by curve/rect drawings.
    Line-only drawings that extend beyond the curve-based bounding box (+margin)
    are almost certainly leader lines or callout artifacts.

    Also removes small circle-like drawings (callout bubbles picked up by BFS).
    """
    if len(drawings) < 3:
        return drawings

    # Build core region from curve/rect-containing drawings
    core_rects = []
    for d in drawings:
        items = d.get("items", [])
        if any(item[0] in ("c", "re") for item in items):
            core_rects.append(d["rect"])

    if not core_rects:
        # Fallback: all-line part — use median-based core
        centers = [_rect_center(d["rect"]) for d in drawings]
        if len(centers) < 3:
            return drawings
        xs = sorted(c[0] for c in centers)
        ys = sorted(c[1] for c in centers)
        n = len(xs)
        lo, hi = max(0, n // 5), min(n - 1, n * 4 // 5)
        core_x0, core_x1 = xs[lo] - 15, xs[hi] + 15
        core_y0, core_y1 = ys[lo] - 15, ys[hi] + 15
    else:
        core_x0 = min(r.x0 for r in core_rects)
        core_y0 = min(r.y0 for r in core_rects)
        core_x1 = max(r.x1 for r in core_rects)
        core_y1 = max(r.y1 for r in core_rects)

    ex0, ey0 = core_x0 - margin, core_y0 - margin
    ex1, ey1 = core_x1 + margin, core_y1 + margin

    result = []
    for d in drawings:
        items = d.get("items", [])
        is_line_only = len(items) > 0 and all(item[0] == "l" for item in items)

        if is_line_only:
            # Check if any line endpoint escapes the expanded core
            escapes = False
            for item in items:
                if item[0] == "l":
                    for pt in [(item[1].x, item[1].y), (item[2].x, item[2].y)]:
                        if pt[0] < ex0 or pt[0] > ex1 or pt[1] < ey0 or pt[1] > ey1:
                            escapes = True; break
                if escapes:
                    break
            if escapes:
                continue

        # Remove small circles (callout bubbles) far from the core center
        r = d["rect"]
        w, h = r.x1 - r.x0, r.y1 - r.y0
        if w < 20 and h < 20 and abs(w - h) < 6:
            cx, cy = _rect_center(r)
            core_cx = (core_x0 + core_x1) / 2
            core_cy = (core_y0 + core_y1) / 2
            core_diag = _dist((core_x0, core_y0), (core_x1, core_y1)) / 2
            if _dist((cx, cy), (core_cx, core_cy)) > core_diag + 10:
                continue

        result.append(d)

    return result


# ── Phase 5: highlight + render ──────────────────────────────────

def _highlight(page, drawings, color=(1, 0.85, 0), fill_color=(1, 0.9, 0),
               stroke_width=2.5, fill_opacity=0.15):
    """Yellow stroke + semi-transparent fill (V2 legacy — unused in V3 pipeline)."""
    shape = page.new_shape()
    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "l":
                shape.draw_line(item[1], item[2])
            elif item[0] == "c":
                shape.draw_bezier(item[1], item[2], item[3], item[4])
            elif item[0] == "qu":
                shape.draw_quad(item[1])
            elif item[0] == "re":
                shape.draw_rect(item[1])
        shape.finish(
            color=color, fill=fill_color, fill_opacity=fill_opacity,
            width=stroke_width,
            closePath=d.get("closePath", False),
            lineCap=1, lineJoin=1)
    shape.commit(overlay=True)


def _part_region(drawings):
    if not drawings:
        return None
    rects = [d["rect"] for d in drawings]
    return (min(r.x0 for r in rects), min(r.y0 for r in rects),
            max(r.x1 for r in rects), max(r.y1 for r in rects))


def render_main(page, part_dwgs, part_region, out_path,
                dpi=300, margin_pts=100, dim_opacity=210):
    """Cropped image with contour spotlight dimming.

    Renders the page cleanly (no overlay), then builds a feathered mask
    from the part's vector paths. The part stays at full contrast while
    everything else fades to near-white.
    """
    table_y = _find_table_top_y(page)

    if part_region:
        rcx = (part_region[0] + part_region[2]) / 2
        rcy = (part_region[1] + part_region[3]) / 2
        rw = (part_region[2] - part_region[0]) / 2 + 20
        rh = (part_region[3] - part_region[1]) / 2 + 20
        margin = max(margin_pts, rw * 1.3, rh * 1.3)
    else:
        return 0, 0

    crop = fitz.Rect(
        max(0, rcx - margin), max(40, rcy - margin),
        min(page.rect.width, rcx + margin),
        min(table_y - 5, rcy + margin))
    if crop.width < 60 or crop.height < 60:
        crop = fitz.Rect(max(0, rcx - 100), max(0, rcy - 100),
                         min(page.rect.width, rcx + 100),
                         min(page.rect.height, rcy + 100))

    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=crop)

    if Image is None or not part_dwgs:
        pix.save(str(out_path))
        return pix.width, pix.height

    base = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)

    # Build contour mask from vector paths
    mask = _draw_part_mask(part_dwgs, crop, scale, base.size)

    # Composite: part at full contrast, surroundings faded to white
    white_wash = Image.new('RGB', base.size, (255, 255, 255))
    dimmed = Image.blend(base, white_wash, dim_opacity / 255.0)
    out = Image.composite(base, dimmed, mask)

    out.save(str(out_path), "PNG", optimize=True)
    return out.width, out.height


def render_secondary(page, callout_rect, out_path, dpi=200):
    """Full exploded view with the part's callout number highlighted.

    Renders the complete diagram page at lower DPI. A bright yellow
    ring is drawn around the part's item-number callout so the customer
    can quickly locate the part in the assembly.
    """
    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))

    if Image is None:
        pix.save(str(out_path))
        return pix.width, pix.height

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    if callout_rect:
        # Callout center and radius in pixel coordinates
        cx = ((callout_rect[0] + callout_rect[2]) / 2) * scale
        cy = ((callout_rect[1] + callout_rect[3]) / 2) * scale
        cw = (callout_rect[2] - callout_rect[0]) * scale
        ch = (callout_rect[3] - callout_rect[1]) * scale
        r = max(cw, ch) / 2 + 6 * scale   # padding around the number

        # Yellow ring + semi-transparent fill via RGBA overlay
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(255, 230, 0, 50),
            outline=(255, 200, 0, 220),
            width=max(2, int(2.5 * scale)))
        img = Image.alpha_composite(
            img.convert("RGBA"), overlay).convert("RGB")

    img.save(str(out_path), "PNG", optimize=True)
    return img.width, img.height


# ── Main pipeline ────────────────────────────────────────────────

def process_pdf(pdf_path: Path, target_pn: str | None = None,
                dry_run: bool = False):
    doc = fitz.open(str(pdf_path))
    pdf_parts = parse_parts_table(doc)

    print(f"\n{'='*60}")
    print(f"PDF: {pdf_parts.pdf_name}  ({pdf_parts.parent_pn})")
    print(f"Diagram pages: {[p+1 for p in pdf_parts.diagram_pages]}")
    print(f"Parts found: {len(pdf_parts.parts)}")

    if not pdf_parts.parts:
        print("  (no parts table)"); doc.close(); return []

    find_callout_positions(doc, pdf_parts)
    all_leader_segs = trace_leader_lines(doc, pdf_parts)

    callout_positions = []
    for p in pdf_parts.parts:
        if p.callout_rect:
            callout_positions.append((
                (p.callout_rect[0] + p.callout_rect[2]) / 2,
                (p.callout_rect[1] + p.callout_rect[3]) / 2))

    # Check for ground truth
    gt_file = GT_DIR / f"{pdf_parts.parent_pn}.json"
    if not gt_file.exists():
        # Fallback: single-file ground truth (only for its original PDF)
        gt_file = PDF_DIR / "ground_truth.json"
        if gt_file.exists() and pdf_parts.parent_pn == "16061030":
            pass  # correct PDF for this GT
        else:
            gt_file = None

    ground_truth = None
    if gt_file and gt_file.exists():
        try:
            ground_truth = _load_ground_truth(str(gt_file))
            print(f"Ground truth: {len(ground_truth)} items from {gt_file.name}")
        except Exception as e:
            print(f"Ground truth load failed: {e}")

    print(f"\n  {'#':>3}  {'Part Number':<20}  {'Type':<10}  {'C':>1} {'L':>1}  Description")
    print(f"  {'─'*3}  {'─'*20}  {'─'*10}  {'─'*1} {'─'*1}  {'─'*30}")
    for p in pdf_parts.parts:
        c = "Y" if p.callout_rect else "-"
        l = "Y" if p.part_position else "-"
        print(f"  {p.item_no:>3}  {p.part_number:<20}  "
              f"{p.classification:<10}  {c} {l}  {p.description[:30]}")

    if dry_run:
        doc.close(); return pdf_parts.parts

    out_dir = OUT_DIR / pdf_parts.parent_pn
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Ground truth path: assign all drawings by polygon containment ──
    if ground_truth:
        results = _process_with_gt(doc, pdf_parts, ground_truth,
                                   out_dir, target_pn,
                                   all_leader_segs, callout_positions)
        doc.close()
        return results

    # ── Automated path: BFS per part ──
    # Pre-compute leader spatial index once for all parts in this PDF
    leader_idx = _build_leader_index(all_leader_segs, callout_positions)

    results = []
    for p in pdf_parts.parts:
        if target_pn and p.part_number != target_pn:
            continue
        if not p.callout_rect:
            continue
        if not p.part_position:
            cx = (p.callout_rect[0] + p.callout_rect[2]) / 2
            cy = (p.callout_rect[1] + p.callout_rect[3]) / 2
            p.part_position = (cx, cy)

        page_idx = p.callout_page if p.callout_page is not None else (
            pdf_parts.diagram_pages[0] if pdf_parts.diagram_pages else 0)
        table_y = _find_table_top_y(doc[page_idx])

        # Fresh doc (clean page, no overlays)
        pdoc = fitz.open(str(pdf_path))
        ppage = pdoc[page_idx]

        callout = callout_positions[0] if callout_positions else None
        part_dwgs = find_part_drawings(
            ppage, p.part_position[0], p.part_position[1],
            p.leader_direction, p.classification,
            callout, all_leader_segs, callout_positions, table_y,
            leader_idx=leader_idx)

        region = _part_region(part_dwgs)

        main_path = out_dir / f"{p.part_number}.png"
        sec_path = out_dir / f"{p.part_number}_full.png"

        if region:
            render_main(ppage, part_dwgs, region, main_path)
        else:
            # Fallback: render around leader endpoint
            fallback_r = (p.part_position[0] - 30, p.part_position[1] - 30,
                         p.part_position[0] + 30, p.part_position[1] + 30)
            render_main(ppage, part_dwgs, fallback_r, main_path)

        render_secondary(ppage, p.callout_rect, sec_path)

        pdoc.close()

        n = len(part_dwgs)
        rw = int(region[2] - region[0]) if region else 0
        rh = int(region[3] - region[1]) if region else 0
        print(f"  {p.part_number:<20}  {n:>3} curves  "
              f"{rw}x{rh}  -> {main_path.name}")

        results.append({
            "part_number": p.part_number,
            "description": p.description,
            "item_no": p.item_no,
            "main_image": str(main_path),
            "secondary_image": str(sec_path),
            "source_pdf": pdf_parts.pdf_name,
            "outline_curves": n,
        })

    doc.close()
    return results


def _process_with_gt(doc, pdf_parts, ground_truth, out_dir, target_pn,
                     leader_segments=None, callout_positions=None):
    """Process PDF using ground truth polygon annotations.

    GT is applied only to the FIRST diagram page (the one the user annotated).
    Leader lines and callout bubbles are filtered out before GT assignment
    so they never get highlighted.
    """
    leader_segments = leader_segments or set()
    callout_positions = callout_positions or []
    results = []
    rendered_pns = set()

    # Only use GT on the first diagram page
    if not pdf_parts.diagram_pages:
        return results

    page_idx = pdf_parts.diagram_pages[0]
    page = doc[page_idx]
    table_y = _find_table_top_y(page)

    # Get all diagram drawings on this page
    all_drawings = page.get_drawings()
    diagram_drawings = [d for d in all_drawings
                       if d["rect"].y1 <= table_y + 5
                       and (d["rect"].x1 - d["rect"].x0 >= 0.5
                            or d["rect"].y1 - d["rect"].y0 >= 0.5)]

    # Filter out leader lines and callout bubbles BEFORE GT assignment
    leader_idx = _build_leader_index(leader_segments, callout_positions)
    filtered = [d for d in diagram_drawings
                if not _is_leader_drawing(d, leader_segments, callout_positions,
                                          leader_idx=leader_idx)]
    n_leaders = len(diagram_drawings) - len(filtered)
    if n_leaders:
        print(f"  Excluded {n_leaders} leader/callout drawings")

    # Assign drawings to items via GT polygons
    part_drawings = defaultdict(list)
    for d in filtered:
        item = _gt_classify(d, ground_truth)
        if item is not None:
            part_drawings[item].append(d)

    total = sum(len(v) for v in part_drawings.values())
    print(f"\n  GT page {page_idx+1}: {total}/{len(filtered)} drawings assigned"
          f" ({len(diagram_drawings)} total, {n_leaders} leaders excluded)")

    # Render each part that has drawings on this page
    for p in pdf_parts.parts:
        if target_pn and p.part_number != target_pn:
            continue
        if p.part_number in ('–', '-', ''):
            continue  # vehicle reference parts

        item_no = p.item_no
        dwgs = part_drawings.get(item_no, [])
        if not dwgs:
            continue

        # Post-filter: remove leader lines that slipped through GT
        dwgs = _remove_leader_chains(dwgs, callout_positions)
        dwgs = _remove_escaping_lines(dwgs)
        if not dwgs:
            continue

        # Fresh doc (clean page, no overlays)
        pdoc = fitz.open(str(doc.name))
        ppage = pdoc[page_idx]

        # Use GT bboxes for crop regions
        gt_regions = ground_truth.get(item_no, [])
        regions = [(r["bbox"]["x0"], r["bbox"]["y0"],
                   r["bbox"]["x1"], r["bbox"]["y1"]) for r in gt_regions]
        if not regions:
            regions = [_part_region(dwgs)]

        merged = (min(r[0] for r in regions), min(r[1] for r in regions),
                 max(r[2] for r in regions), max(r[3] for r in regions))

        main_path = out_dir / f"{p.part_number}.png"
        sec_path = out_dir / f"{p.part_number}_full.png"

        render_main(ppage, dwgs, merged, main_path)
        render_secondary(ppage, p.callout_rect, sec_path)
        pdoc.close()

        rendered_pns.add(p.part_number)
        rw = int(merged[2] - merged[0])
        rh = int(merged[3] - merged[1])
        print(f"  {p.part_number:<20}  {len(dwgs):>3} curves  "
              f"{rw}x{rh}  -> {main_path.name}")

        results.append({
            "part_number": p.part_number,
            "description": p.description,
            "item_no": item_no,
            "main_image": str(main_path),
            "secondary_image": str(sec_path),
            "source_pdf": pdf_parts.pdf_name,
            "outline_curves": len(dwgs),
        })

    not_rendered = [p for p in pdf_parts.parts
                   if p.part_number not in rendered_pns
                   and p.part_number not in ('–', '-', '')
                   and (not target_pn or p.part_number == target_pn)]
    if not_rendered:
        print(f"  {len(not_rendered)} parts not in GT (skipped)")

    return results


# ── CLI ──────────────────────────────────────────────────────────

def main():
    global PDF_DIR, OUT_DIR, GT_DIR

    parser = argparse.ArgumentParser(
        description="Extract highlighted part images from installation PDFs")
    parser.add_argument("--pdf", help="Process one PDF filename")
    parser.add_argument("--pn", help="Extract one part number only")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse tables only, no images")
    parser.add_argument("--pdf-dir",
                        help="PDF source directory (default: /tmp/buyers_pdfs)")
    parser.add_argument("--out-dir",
                        help="Output directory (default: /tmp/buyers_pdf_images)")
    args = parser.parse_args()

    if args.pdf_dir:
        PDF_DIR = Path(args.pdf_dir)
        GT_DIR = PDF_DIR / "ground_truth"
    if args.out_dir:
        OUT_DIR = Path(args.out_dir)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GT_DIR.mkdir(parents=True, exist_ok=True)

    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            pdf_path = PDF_DIR / args.pdf
        if not pdf_path.exists():
            print(f"ERROR: {args.pdf} not found"); sys.exit(1)
        results = process_pdf(pdf_path, target_pn=args.pn, dry_run=args.dry_run)
    else:
        pdfs = sorted(PDF_DIR.glob("*.pdf"))
        if not pdfs:
            print(f"No PDFs in {PDF_DIR}"); sys.exit(1)
        results = []
        for pdf_path in pdfs:
            results.extend(process_pdf(pdf_path, target_pn=args.pn,
                                       dry_run=args.dry_run))

    if results and not args.dry_run:
        manifest = OUT_DIR / "manifest.json"
        with open(manifest, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n{'='*60}")
        print(f"Manifest: {manifest}")
        print(f"Total part images: {len(results)}")


if __name__ == "__main__":
    main()
