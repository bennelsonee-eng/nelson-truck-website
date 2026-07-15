"""V2 part extraction: polygon-containment approach.

Strategy for the test PDF (with ground truth):
  1. Load ground truth polygon annotations from user's freeform drawings
  2. For each PDF vector drawing, check which ground truth polygon contains
     its center (or majority of its points)
  3. Assign drawing to that part
  4. Highlight + render

Strategy for OTHER PDFs (no ground truth):
  1. Parse parts table, find callout positions, trace leaders
  2. Use leader endpoint as seed, expand via connected endpoints
  3. Use classification-based size/distance limits
  4. Key improvement: respect the PATTERNS learned from ground truth:
     - Multi-region parts are common (mirror sides, bracket + body)
     - Leader often points to ONE region; other regions share the same
       visual pattern (same stroke width, similar shapes)
     - Small fasteners are very precise, tiny bboxes
"""
import sys, math, re, json
from pathlib import Path
from collections import defaultdict

try:
    import fitz
except ImportError:
    print("pip install PyMuPDF"); sys.exit(1)

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("pip install Pillow"); sys.exit(1)

PDF_PATH = Path("/tmp/buyers_pdfs/16061030INST_B.pdf")
OUT_DIR = Path("/tmp/buyers_pdf_images/v2_test")
GROUND_TRUTH = Path("/tmp/buyers_pdfs/ground_truth.json")

# ── Geometry helpers ──────────────────────────────────────────────

def dist(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

def point_in_polygon(px, py, polygon):
    """Ray casting algorithm for point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def rect_center(r):
    return ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)

def rect_area(r):
    return max(0, r.x1 - r.x0) * max(0, r.y1 - r.y0)


# ── Drawing point extraction ─────────────────────────────────────

def get_drawing_all_points(drawing):
    """Extract ALL coordinate points from a drawing's path items.
    For bezier curves, sample intermediate points too."""
    points = []
    for item in drawing.get("items", []):
        if item[0] == "l":
            points.append((item[1].x, item[1].y))
            points.append((item[2].x, item[2].y))
        elif item[0] == "c":
            # Bezier: start, ctrl1, ctrl2, end — sample points along curve
            p0 = (item[1].x, item[1].y)
            p1 = (item[2].x, item[2].y)
            p2 = (item[3].x, item[3].y)
            p3 = (item[4].x, item[4].y)
            points.append(p0)
            points.append(p3)
            # Sample 3 intermediate points
            for t in [0.25, 0.5, 0.75]:
                bx = (1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t**2*p2[0] + t**3*p3[0]
                by = (1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] + 3*(1-t)*t**2*p2[1] + t**3*p3[1]
                points.append((bx, by))
        elif item[0] == "re":
            r = item[1]
            points.append((r.x0, r.y0))
            points.append((r.x1, r.y0))
            points.append((r.x0, r.y1))
            points.append((r.x1, r.y1))
    return points


def drawing_center(drawing):
    """Get the center of a drawing's bounding rect."""
    r = drawing["rect"]
    return ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)


# ── Ground truth polygon matching ────────────────────────────────

def load_ground_truth(gt_path):
    """Load ground truth annotations and structure by item number.
    Returns dict: item_no -> list of polygon point lists.
    """
    with open(gt_path) as f:
        annotations = json.load(f)

    gt = defaultdict(list)
    for ann in annotations:
        item = ann["item"]
        poly = [(p["x"], p["y"]) for p in ann["polygon"]]
        gt[item].append({
            "polygon": poly,
            "bbox": ann["bbox"],
        })
    return dict(gt)


def classify_drawing_to_gt(drawing, ground_truth):
    """Determine which ground truth item a drawing belongs to.

    Strategy:
    1. Size guard: reject drawings much larger than the GT polygon
    2. Check all GT polygons and collect all matches with scores
    3. For overlapping polygons, prefer the SMALLEST (most specific) match
    4. For very small polygons, use bbox overlap instead of polygon containment

    Returns item_no or None.
    """
    cx, cy = drawing_center(drawing)
    all_pts = get_drawing_all_points(drawing)
    r = drawing["rect"]
    d_area = rect_area(r)
    d_w = r.x1 - r.x0
    d_h = r.y1 - r.y0

    # Collect ALL viable matches: (score, gt_area, item_no)
    matches = []

    for item_no, regions in ground_truth.items():
        for region in regions:
            poly = region["polygon"]
            bbox = region["bbox"]
            gt_w = bbox["x1"] - bbox["x0"]
            gt_h = bbox["y1"] - bbox["y0"]
            gt_area = max(1, gt_w * gt_h)

            # ── Size guard: drawing shouldn't be much larger than polygon ──
            if gt_area < 1000:
                max_dim = max(gt_w, gt_h) * 4 + 10
                if d_w > max_dim or d_h > max_dim:
                    continue
            elif gt_area < 5000:
                max_dim = max(gt_w, gt_h) * 3 + 20
                if d_w > max_dim or d_h > max_dim:
                    continue

            # ── Quick bbox rejection ──
            d_in_gt = not (r.x1 < bbox["x0"] - 5 or r.x0 > bbox["x1"] + 5 or
                          r.y1 < bbox["y0"] - 5 or r.y0 > bbox["y1"] + 5)
            if not d_in_gt:
                continue

            # ── Compute match score ──
            score = 0

            if gt_area < 400:
                # For small polygons: use bbox overlap approach
                ox0 = max(r.x0, bbox["x0"])
                oy0 = max(r.y0, bbox["y0"])
                ox1 = min(r.x1, bbox["x1"])
                oy1 = min(r.y1, bbox["y1"])
                if ox1 > ox0 and oy1 > oy0:
                    overlap = (ox1 - ox0) * (oy1 - oy0)
                    d_frac = overlap / max(1, d_area)
                    g_frac = overlap / max(1, gt_area)
                    score = d_frac * 1.5 + g_frac * 0.5
            else:
                # Standard polygon containment test
                center_inside = point_in_polygon(cx, cy, poly)
                pts_inside = sum(1 for px, py in all_pts
                                if point_in_polygon(px, py, poly))
                frac = pts_inside / max(1, len(all_pts))
                score = (2.0 if center_inside else 0) + frac

            if score > 0.15:
                matches.append((score, gt_area, item_no))

    if not matches:
        return None

    # ── Resolve conflicts: prefer smallest (most specific) polygon ──
    # When a drawing matches both a small and large polygon,
    # pick the smallest polygon that has a reasonable score.
    # This ensures tiny fastener polygons win over the larger
    # screw polygon that contains them.

    # Sort by gt_area ascending (smallest first), then score descending
    matches.sort(key=lambda m: (m[1], -m[0]))

    # The smallest polygon that has a decent score wins
    best = matches[0]

    # But if a much larger polygon has a dramatically higher score,
    # prefer it (e.g., score 3.0 vs 0.2)
    for m in matches[1:]:
        if m[0] > best[0] * 3 and m[0] > 1.0:
            best = m

    return best[2]


# ── Highlighting and rendering ────────────────────────────────────

def highlight_drawings(page, drawings, color=(1, 0.9, 0), stroke_width=2.5):
    """Re-draw paths in yellow using Shape API."""
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
            color=color,
            width=stroke_width,
            closePath=d.get("closePath", False),
            lineCap=1, lineJoin=1,
        )
    shape.commit(overlay=True)


def highlight_with_fill(page, drawings, color=(1, 0.85, 0),
                        fill_color=None, stroke_width=2.0):
    """Highlight with both stroke and semi-transparent fill."""
    if fill_color is None:
        fill_color = (color[0], color[1], color[2])

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
            color=color,
            fill=fill_color,
            fill_opacity=0.15,
            width=stroke_width,
            closePath=d.get("closePath", False),
            lineCap=1, lineJoin=1,
        )
    shape.commit(overlay=True)


def render_cropped(page, part_regions, out_path, dpi=300, margin_pts=80):
    """Render a crop centered on the part region(s).
    part_regions is a list of (x0,y0,x1,y1) tuples — one per polygon region.
    """
    table_hits = page.search_for("Parts List")
    table_y = table_hits[0].y0 if table_hits else page.rect.height * 0.65

    # Compute bounding box across ALL regions
    all_x0 = min(r[0] for r in part_regions)
    all_y0 = min(r[1] for r in part_regions)
    all_x1 = max(r[2] for r in part_regions)
    all_y1 = max(r[3] for r in part_regions)

    rcx = (all_x0 + all_x1) / 2
    rcy = (all_y0 + all_y1) / 2
    rw = (all_x1 - all_x0) / 2 + 20
    rh = (all_y1 - all_y0) / 2 + 20
    margin = max(margin_pts, rw * 1.3, rh * 1.3)

    crop = fitz.Rect(
        max(0, rcx - margin),
        max(40, rcy - margin),
        min(page.rect.width, rcx + margin),
        min(table_y - 5, rcy + margin),
    )
    if crop.width < 60 or crop.height < 60:
        crop = fitz.Rect(max(0, rcx - 100), max(0, rcy - 100),
                         min(page.rect.width, rcx + 100),
                         min(page.rect.height, rcy + 100))

    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=crop)
    pix.save(str(out_path))
    return pix.width, pix.height


def render_full_page(page, part_regions, out_path, dpi=200):
    """Render full page with spotlight dimming around the part region(s)."""
    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    if part_regions:
        # Create dimming overlay with cutouts for each region
        dim = Image.new("RGBA", img.size, (255, 255, 255, 90))
        dim_draw = ImageDraw.Draw(dim)
        pad = 18 * scale

        for region in part_regions:
            rx0 = region[0] * scale
            ry0 = region[1] * scale
            rx1 = region[2] * scale
            ry1 = region[3] * scale
            dim_draw.rounded_rectangle(
                [rx0 - pad, ry0 - pad, rx1 + pad, ry1 + pad],
                radius=int(10 * scale), fill=(0, 0, 0, 0))

        img = Image.alpha_composite(img.convert("RGBA"), dim).convert("RGB")

    img.save(str(out_path), "PNG", optimize=True)
    return img.width, img.height


# ── Parts table parsing ──────────────────────────────────────────

def parse_parts_table(page, table_y):
    """Parse the parts list table into structured data."""
    table_text = page.get_text("text", clip=fitz.Rect(
        0, table_y - 5, page.rect.width, page.rect.height))

    parts = []
    lines = table_text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r'^(\d{1,2})$', line)
        if m:
            item_no = int(m.group(1))
            if i + 3 < len(lines):
                part_no = lines[i+1].strip()
                qty_str = lines[i+2].strip()
                desc = lines[i+3].strip()
                if re.match(r'^\d+$', qty_str) and part_no not in (
                        'PART NO.', 'QTY.', 'DESCRIPTION'):
                    parts.append({
                        'item_no': item_no,
                        'part_number': part_no,
                        'qty': int(qty_str),
                        'description': desc,
                    })
                    i += 4
                    continue
        i += 1
    return parts


# ── Main pipeline ─────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(PDF_PATH))
    page = doc[1]  # diagram page (page 2)

    # Find table boundary
    hits = page.search_for("Parts List")
    table_y = hits[0].y0 if hits else page.rect.height * 0.75

    # Parse parts table
    parts = parse_parts_table(page, table_y)
    print(f"Parts found: {len(parts)}")
    for p in parts:
        print(f"  Item {p['item_no']:2d}: {p['part_number']:20s} {p['description']}")

    # Load ground truth
    if not GROUND_TRUTH.exists():
        print(f"\nERROR: Ground truth file not found: {GROUND_TRUTH}")
        print("Copy ground_truth.json to /tmp/buyers_pdfs/")
        sys.exit(1)

    gt = load_ground_truth(str(GROUND_TRUTH))
    print(f"\nGround truth loaded: {len(gt)} items, "
          f"{sum(len(v) for v in gt.values())} total polygons")
    for item_no in sorted(gt.keys()):
        regions = gt[item_no]
        print(f"  Item {item_no:2d}: {len(regions)} polygon(s)")

    # Get ALL diagram drawings (above table)
    all_drawings = page.get_drawings()
    diagram_drawings = []
    for d in all_drawings:
        r = d["rect"]
        if r.y1 > table_y + 5:
            continue
        w = r.x1 - r.x0
        h = r.y1 - r.y0
        if w < 0.5 and h < 0.5:
            continue
        diagram_drawings.append(d)

    print(f"\nDiagram drawings: {len(diagram_drawings)}")

    # ── Assign drawings to parts via ground truth polygons ──
    part_drawings = defaultdict(list)  # item_no -> [drawing, ...]
    unassigned = []

    for d in diagram_drawings:
        item = classify_drawing_to_gt(d, gt)
        if item is not None:
            part_drawings[item].append(d)
        else:
            unassigned.append(d)

    total_assigned = sum(len(v) for v in part_drawings.values())
    print(f"\nAssignment: {total_assigned}/{len(diagram_drawings)} drawings assigned "
          f"({total_assigned/len(diagram_drawings)*100:.0f}%), "
          f"{len(unassigned)} unassigned")

    for item_no in sorted(part_drawings.keys()):
        dwgs = part_drawings[item_no]
        rects = [d["rect"] for d in dwgs]
        if rects:
            region = (
                min(r.x0 for r in rects),
                min(r.y0 for r in rects),
                max(r.x1 for r in rects),
                max(r.y1 for r in rects),
            )
            rw = region[2] - region[0]
            rh = region[3] - region[1]
        else:
            rw = rh = 0

        # Find the part info
        pinfo = next((p for p in parts if p['item_no'] == item_no), None)
        desc = pinfo['description'][:35] if pinfo else '?'
        print(f"  Item {item_no:2d}: {len(dwgs):3d} drawings  "
              f"region={rw:.0f}x{rh:.0f}  {desc}")

    # Print unassigned drawing info for debugging
    if unassigned:
        print(f"\n  Unassigned drawings breakdown:")
        small = sum(1 for d in unassigned if rect_area(d["rect"]) < 20)
        medium = sum(1 for d in unassigned if 20 <= rect_area(d["rect"]) < 200)
        large = sum(1 for d in unassigned if rect_area(d["rect"]) >= 200)
        print(f"    Small (<20 area): {small}")
        print(f"    Medium (20-200):  {medium}")
        print(f"    Large (>200):     {large}")

    # ── Render each part ──
    print(f"\n--- Rendering ---")
    for p in parts:
        item_no = p['item_no']
        if item_no not in part_drawings or not part_drawings[item_no]:
            print(f"  {p['part_number']:20s} SKIP (no drawings)")
            continue

        # Fresh doc for each part
        rdoc = fitz.open(str(PDF_PATH))
        rpage = rdoc[1]

        dwgs = part_drawings[item_no]

        # Highlight with yellow stroke + light fill
        highlight_with_fill(rpage, dwgs,
                           color=(1, 0.85, 0),
                           fill_color=(1, 0.9, 0),
                           stroke_width=2.5)

        # Compute regions for each GT polygon this item has
        gt_regions = gt.get(item_no, [])
        regions_for_crop = []
        for gr in gt_regions:
            bbox = gr["bbox"]
            regions_for_crop.append(
                (bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]))

        # Fallback: compute from actual drawing rects
        if not regions_for_crop:
            rects = [d["rect"] for d in dwgs]
            regions_for_crop = [(
                min(r.x0 for r in rects),
                min(r.y0 for r in rects),
                max(r.x1 for r in rects),
                max(r.y1 for r in rects),
            )]

        pn = p['part_number']

        # Main image: cropped
        w, h = render_cropped(rpage, regions_for_crop,
                              OUT_DIR / f"{pn}.png")
        print(f"  {pn:20s} main={w}x{h}  ({len(dwgs)} drawings)")

        # Full page with spotlight
        w, h = render_full_page(rpage, regions_for_crop,
                                OUT_DIR / f"{pn}_full.png")

        rdoc.close()

    # ── Also render a debug overlay showing ALL assignments ──
    print(f"\n--- Debug overlay ---")
    rdoc = fitz.open(str(PDF_PATH))
    rpage = rdoc[1]

    COLORS = [
        (0.91, 0.27, 0.37),   # red
        (0, 0.71, 0.85),      # cyan
        (0.02, 0.84, 0.63),   # green
        (1, 0.82, 0.4),       # yellow
        (0.66, 0.33, 0.97),   # purple
        (0.98, 0.45, 0.09),   # orange
        (0.08, 0.72, 0.65),   # teal
        (0.93, 0.29, 0.6),    # pink
        (0.52, 0.8, 0.09),    # lime
        (0.39, 0.4, 0.95),    # indigo
        (0.96, 0.25, 0.37),   # rose
        (0.05, 0.65, 0.91),   # sky
        (0.06, 0.73, 0.51),   # emerald
        (0.92, 0.7, 0.03),    # amber
        (0.55, 0.36, 0.98),   # violet
        (0.94, 0.27, 0.27),   # red-500
        (0.23, 0.51, 0.96),   # blue
        (0.13, 0.77, 0.37),   # green-500
        (0.96, 0.62, 0.04),   # orange-500
        (0.66, 0.55, 0.98),   # purple-300
    ]

    for item_no in sorted(part_drawings.keys()):
        dwgs = part_drawings[item_no]
        color = COLORS[(item_no - 1) % len(COLORS)]
        highlight_with_fill(rpage, dwgs,
                           color=color,
                           fill_color=color,
                           stroke_width=2.0)

    scale = 200 / 72
    pix = rpage.get_pixmap(matrix=fitz.Matrix(scale, scale))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    # Add item number labels at the centroid of each part's drawings
    from PIL import ImageFont
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(img)
    for item_no in sorted(part_drawings.keys()):
        dwgs = part_drawings[item_no]
        if not dwgs:
            continue
        rects = [d["rect"] for d in dwgs]
        cx = sum((r.x0 + r.x1) / 2 for r in rects) / len(rects) * scale
        cy = sum((r.y0 + r.y1) / 2 for r in rects) / len(rects) * scale
        label = f"#{item_no}"
        color_rgb = tuple(int(c * 255) for c in COLORS[(item_no - 1) % len(COLORS)])
        # Background pill
        try:
            bbox_text = draw.textbbox((cx, cy), label, font=font)
        except:
            bbox_text = (cx, cy, cx + 30, cy + 14)
        pad = 4
        draw.rounded_rectangle(
            [bbox_text[0]-pad, bbox_text[1]-pad, bbox_text[2]+pad, bbox_text[3]+pad],
            radius=4, fill=color_rgb)
        draw.text((cx, cy), label, fill=(255, 255, 255), font=font,
                  anchor="mm" if hasattr(draw, 'textbbox') else None)

    img.save(str(OUT_DIR / "debug_all_items.png"), "PNG", optimize=True)
    print(f"  Debug overlay: {img.width}x{img.height}")

    rdoc.close()
    print(f"\nDone! Check {OUT_DIR}")


if __name__ == "__main__":
    main()
