"""Proof-of-concept: highlight the actual vector outline of a part in a Buyers PDF.

Approach:
1. Find the leader-line endpoint (where the part is)
2. Collect all vector path segments whose bounding rect contains/is near that point
3. Re-draw those paths in red with thicker stroke using PyMuPDF's Shape API
4. Render the modified page
"""
import sys, math, re
from pathlib import Path

try:
    import fitz
except ImportError:
    print("pip install PyMuPDF"); sys.exit(1)

PDF_PATH = Path("/tmp/buyers_pdfs/16061030INST_B.pdf")
OUT_DIR = Path("/tmp/buyers_pdf_images/outline_test")


def dist(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def find_leader_endpoint(page, cx, cy, search_radius=25):
    drawings = page.get_drawings()
    segments = []
    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "l":
                segments.append(((item[1].x, item[1].y), (item[2].x, item[2].y)))

    nearby = []
    for p1, p2 in segments:
        d1 = dist(p1, (cx, cy))
        d2 = dist(p2, (cx, cy))
        if d1 < search_radius:
            nearby.append({"far": p2, "near_dist": d1, "seg": (p1, p2)})
        elif d2 < search_radius:
            nearby.append({"far": p1, "near_dist": d2, "seg": (p1, p2)})

    if not nearby:
        return None
    nearby.sort(key=lambda x: x["near_dist"])
    current_end = nearby[0]["far"]
    visited = {nearby[0]["seg"]}
    for _ in range(5):
        found = False
        for p1, p2 in segments:
            if (p1, p2) in visited: continue
            if dist(p1, current_end) < 5:
                current_end = p2; visited.add((p1, p2)); found = True; break
            elif dist(p2, current_end) < 5:
                current_end = p1; visited.add((p1, p2)); found = True; break
        if not found: break
    return current_end


def _min_point_dist(drawing, px, py):
    """Minimum distance from any path point in a drawing to (px, py)."""
    min_d = float("inf")
    for item in drawing.get("items", []):
        if item[0] == "l":  # line: 2 endpoints
            for pt in [item[1], item[2]]:
                min_d = min(min_d, dist((pt.x, pt.y), (px, py)))
        elif item[0] == "c":  # bezier: 4 control points
            for pt in [item[1], item[2], item[3], item[4]]:
                min_d = min(min_d, dist((pt.x, pt.y), (px, py)))
        elif item[0] == "re":  # rect
            r = item[1]
            for corner in [(r.x0, r.y0), (r.x1, r.y0), (r.x0, r.y1), (r.x1, r.y1)]:
                min_d = min(min_d, dist(corner, (px, py)))
    return min_d


def _is_leader_line(drawing, callout_positions, threshold=20):
    """Check if a drawing is a leader line (a line segment connecting to a callout)."""
    items = drawing.get("items", [])
    if len(items) != 1:
        return False
    item = items[0]
    if item[0] != "l":
        return False
    # Check if either endpoint is near a callout position
    for pt in [item[1], item[2]]:
        for cx, cy in callout_positions:
            if dist((pt.x, pt.y), (cx, cy)) < threshold:
                return True
    return False


def _get_drawing_endpoints(drawing):
    """Extract all start/end points from a drawing's path segments."""
    points = []
    for item in drawing.get("items", []):
        if item[0] == "l":
            points.append((round(item[1].x, 1), round(item[1].y, 1)))
            points.append((round(item[2].x, 1), round(item[2].y, 1)))
        elif item[0] == "c":
            points.append((round(item[1].x, 1), round(item[1].y, 1)))
            points.append((round(item[4].x, 1), round(item[4].y, 1)))
        elif item[0] == "re":
            r = item[1]
            points.append((round(r.x0, 1), round(r.y0, 1)))
            points.append((round(r.x1, 1), round(r.y1, 1)))
    return points


def get_part_drawings(page, px, py, callout_positions,
                      seed_radius=35, connect_tolerance=3,
                      min_area=15, max_area=20000):
    """Find vector drawings that form the part outline via connected-component flood fill.

    1. Seed: find drawings with a path point near the leader endpoint
    2. Expand: BFS to find drawings that share endpoints with the seed set
    3. This traces the entire connected outline of the part
    """
    drawings = page.get_drawings()

    # Pre-filter: remove leader lines and extreme sizes
    candidates = []
    for i, d in enumerate(drawings):
        r = d["rect"]
        w = r.x1 - r.x0
        h = r.y1 - r.y0
        area = w * h
        if area < min_area or area > max_area:
            continue
        if w < 1.5 and h < 1.5:
            continue
        if _is_leader_line(d, callout_positions):
            continue
        candidates.append((i, d))

    # Build endpoint index: point -> list of candidate indices
    from collections import defaultdict
    point_to_drawings = defaultdict(set)
    drawing_endpoints = {}

    for idx, (i, d) in enumerate(candidates):
        pts = _get_drawing_endpoints(d)
        drawing_endpoints[idx] = pts
        for pt in pts:
            # Quantize to connect_tolerance grid for fuzzy matching
            qpt = (round(pt[0] / connect_tolerance) * connect_tolerance,
                   round(pt[1] / connect_tolerance) * connect_tolerance)
            point_to_drawings[qpt].add(idx)

    # Seed: find candidate drawings with a point near the leader endpoint
    seed_indices = set()
    for idx, (i, d) in enumerate(candidates):
        min_d = _min_point_dist(d, px, py)
        if min_d <= seed_radius:
            seed_indices.add(idx)

    if not seed_indices:
        return []

    # Compute seed region centroid and max-leash radius
    seed_pts = []
    for idx in seed_indices:
        seed_pts.extend(drawing_endpoints.get(idx, []))
    if seed_pts:
        seed_cx = sum(p[0] for p in seed_pts) / len(seed_pts)
        seed_cy = sum(p[1] for p in seed_pts) / len(seed_pts)
    else:
        seed_cx, seed_cy = px, py
    max_leash = 100  # don't expand beyond 100pts from seed center

    # BFS flood fill: expand from seed via shared endpoints
    visited = set(seed_indices)
    queue = list(seed_indices)
    max_expansion = 40  # safety cap

    while queue and len(visited) < max_expansion:
        current = queue.pop(0)
        pts = drawing_endpoints.get(current, [])
        for pt in pts:
            qpt = (round(pt[0] / connect_tolerance) * connect_tolerance,
                   round(pt[1] / connect_tolerance) * connect_tolerance)
            for dx in [-connect_tolerance, 0, connect_tolerance]:
                for dy in [-connect_tolerance, 0, connect_tolerance]:
                    neighbor_pt = (qpt[0] + dx, qpt[1] + dy)
                    for neighbor_idx in point_to_drawings.get(neighbor_pt, set()):
                        if neighbor_idx in visited:
                            continue
                        # Spatial leash: check the neighbor's center isn't too far
                        n_pts = drawing_endpoints.get(neighbor_idx, [])
                        if n_pts:
                            n_cx = sum(p[0] for p in n_pts) / len(n_pts)
                            n_cy = sum(p[1] for p in n_pts) / len(n_pts)
                            if dist((n_cx, n_cy), (seed_cx, seed_cy)) > max_leash:
                                continue
                        visited.add(neighbor_idx)
                        queue.append(neighbor_idx)

    return [candidates[idx][1] for idx in visited]


def highlight_part(page, part_drawings, color=(1, 0, 0), stroke_width=2.5, opacity=0.7):
    """Re-draw the part's vector paths in highlight color using Shape API."""
    shape = page.new_shape()

    for d in part_drawings:
        for item in d.get("items", []):
            if item[0] == "l":  # line segment
                shape.draw_line(item[1], item[2])
            elif item[0] == "c":  # cubic bezier curve
                shape.draw_bezier(item[1], item[2], item[3], item[4])
            elif item[0] == "qu":  # quad (4-point)
                shape.draw_quad(item[1])
            elif item[0] == "re":  # rectangle
                shape.draw_rect(item[1])

        # Finish each path separately to respect original path structure
        shape.finish(
            color=color,
            width=stroke_width,
            closePath=d.get("closePath", False),
            lineCap=1,   # round cap
            lineJoin=1,  # round join
        )

    shape.commit(overlay=True)


def render_cropped(page, px, py, part_region, out_path, dpi=300, margin_pts=120):
    """Render a crop centered on the part."""
    table_hits = page.search_for("Parts List")
    table_y = table_hits[0].y0 if table_hits else page.rect.height * 0.65

    if part_region:
        rcx = (part_region[0] + part_region[2]) / 2
        rcy = (part_region[1] + part_region[3]) / 2
        rw = (part_region[2] - part_region[0]) / 2 + 40
        rh = (part_region[3] - part_region[1]) / 2 + 40
        margin = max(margin_pts, rw, rh)
    else:
        rcx, rcy = px, py
        margin = margin_pts

    crop = fitz.Rect(
        max(0, rcx - margin),
        max(45, rcy - margin),
        min(page.rect.width, rcx + margin),
        min(table_y - 5, rcy + margin),
    )
    if crop.width < 80 or crop.height < 80:
        crop = fitz.Rect(max(0, rcx - margin), max(0, rcy - margin),
                         min(page.rect.width, rcx + margin),
                         min(page.rect.height, rcy + margin))

    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=crop)
    pix.save(str(out_path))
    print(f"  Saved: {out_path}  ({pix.width}x{pix.height})")


def render_full_page(page, px, py, part_region, out_path, dpi=200):
    """Render the full page with the part highlighted."""
    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))

    # Add spotlight dimming via PIL
    try:
        from PIL import Image, ImageDraw
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        if part_region:
            # Dim everything except the part region
            dim = Image.new("RGBA", img.size, (255, 255, 255, 80))
            dim_draw = ImageDraw.Draw(dim)
            pad = 15 * scale
            rx0 = part_region[0] * scale
            ry0 = part_region[1] * scale
            rx1 = part_region[2] * scale
            ry1 = part_region[3] * scale
            dim_draw.rounded_rectangle(
                [rx0 - pad, ry0 - pad, rx1 + pad, ry1 + pad],
                radius=int(8 * scale), fill=(0, 0, 0, 0))
            img = Image.alpha_composite(img.convert("RGBA"), dim).convert("RGB")

        img.save(str(out_path), "PNG", optimize=True)
        print(f"  Saved: {out_path}  ({img.width}x{img.height})")
    except ImportError:
        pix.save(str(out_path))


def _find_all_callout_positions(page, table_y):
    """Find all callout bubble positions on the diagram."""
    positions = []
    for item_no in range(1, 30):
        for inst in page.search_for(str(item_no)):
            if inst.y0 >= table_y:
                continue
            expanded = fitz.Rect(inst.x0 - 8, inst.y0 - 3, inst.x1 + 8, inst.y1 + 3)
            surrounding = page.get_text("text", clip=expanded).strip()
            if surrounding == str(item_no):
                positions.append(((inst.x0 + inst.x1) / 2, (inst.y0 + inst.y1) / 2))
                break
    return positions


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    test_items = [
        (1, "PUSHBAR"),
        (2, "MID BRACE"),
        (3, "REAR BRACE DS"),
        (5, "SIDEPLATE"),
    ]

    # Process each part independently (re-open doc each time so highlights
    # don't accumulate across parts)
    for item_no, desc in test_items:
        doc = fitz.open(str(PDF_PATH))
        page = doc[1]

        table_hits = page.search_for("Parts List")
        table_y = table_hits[0].y0 if table_hits else 600

        # Get all callout positions for leader-line filtering
        all_callouts = _find_all_callout_positions(page, table_y)

        # Find this callout
        found = False
        for inst in page.search_for(str(item_no)):
            if inst.y0 >= table_y:
                continue
            expanded = fitz.Rect(inst.x0 - 8, inst.y0 - 3, inst.x1 + 8, inst.y1 + 3)
            surrounding = page.get_text("text", clip=expanded).strip()
            if surrounding == str(item_no):
                cx = (inst.x0 + inst.x1) / 2
                cy = (inst.y0 + inst.y1) / 2
                endpoint = find_leader_endpoint(page, cx, cy)
                if not endpoint:
                    print(f"  Item {item_no}: no leader endpoint")
                    break

                px, py = endpoint
                print(f"\nItem {item_no} ({desc}): part at ({px:.0f}, {py:.0f})")

                # Find part drawings with improved filtering
                part_dwgs = get_part_drawings(page, px, py, all_callouts)
                print(f"  Found {len(part_dwgs)} drawings for this part")
                total_segs = sum(len(d.get("items", [])) for d in part_dwgs)
                print(f"  Total path segments: {total_segs}")

                # Highlight the outline
                highlight_part(page, part_dwgs, color=(1, 0, 0), stroke_width=2.5)

                # Part region from matched drawings
                if part_dwgs:
                    all_rects = [d["rect"] for d in part_dwgs]
                    part_region = (
                        min(r.x0 for r in all_rects),
                        min(r.y0 for r in all_rects),
                        max(r.x1 for r in all_rects),
                        max(r.y1 for r in all_rects),
                    )
                else:
                    part_region = None

                # Render crop (just this part highlighted)
                render_cropped(page, px, py, part_region,
                               OUT_DIR / f"item{item_no}_crop.png")

                # Render full page (just this part highlighted)
                render_full_page(page, px, py, part_region,
                                 OUT_DIR / f"item{item_no}_full.png")
                found = True
                break

        doc.close()

    print(f"\nDone! Check {OUT_DIR}")


if __name__ == "__main__":
    main()
