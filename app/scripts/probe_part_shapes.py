"""Probe vector drawing structure near leader-line endpoints to see if we can
identify the full part shape for highlighting.

For each callout's leader endpoint, find nearby vector paths and analyze
whether they form closed shapes we could highlight as "the part".
"""
import sys, math, re
from pathlib import Path
from collections import defaultdict

try:
    import fitz
except ImportError:
    print("pip install PyMuPDF")
    sys.exit(1)

PDF_PATH = Path("/tmp/buyers_pdfs/16061030INST_B.pdf")


def dist(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def rect_contains(rect, px, py, margin=5):
    """Check if point is inside a rect (with margin)."""
    return (rect[0] - margin <= px <= rect[2] + margin and
            rect[1] - margin <= py <= rect[3] + margin)


def find_leader_endpoint(page, cx, cy, search_radius=25):
    drawings = page.get_drawings()
    segments = []
    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "l":
                p1 = (item[1].x, item[1].y)
                p2 = (item[2].x, item[2].y)
                segments.append((p1, p2))

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


def analyze_drawings_near_point(page, px, py, label=""):
    """Find vector drawings whose bounding rect contains or is near the point."""
    drawings = page.get_drawings()

    # Categorize drawings by whether they contain the point
    containing = []   # drawings whose rect contains the point
    nearby = []       # drawings whose rect is within 30pts

    for i, d in enumerate(drawings):
        r = d["rect"]
        rect = (r.x0, r.y0, r.x1, r.y1)
        w = r.x1 - r.x0
        h = r.y1 - r.y0
        area = w * h

        # Skip tiny drawings (dots, ticks) and huge ones (page background)
        if area < 20 or w > 500 or h > 500:
            continue

        # Count path segments
        n_items = len(d.get("items", []))
        is_closed = d.get("closePath", False)
        fill = d.get("fill")
        color = d.get("color")
        stroke_w = d.get("width", 0)

        info = {
            "idx": i,
            "rect": rect,
            "w": round(w, 1),
            "h": round(h, 1),
            "area": round(area, 1),
            "segments": n_items,
            "closed": is_closed,
            "fill": fill,
            "color": color,
            "stroke_w": round(stroke_w, 2) if stroke_w else 0,
            "dist_to_pt": round(dist(
                ((r.x0+r.x1)/2, (r.y0+r.y1)/2), (px, py)
            ), 1),
        }

        if rect_contains(rect, px, py, margin=5):
            containing.append(info)
        elif rect_contains(rect, px, py, margin=30):
            nearby.append(info)

    # Sort containing by area (smallest first = most specific shape)
    containing.sort(key=lambda x: x["area"])
    nearby.sort(key=lambda x: x["dist_to_pt"])

    print(f"\n{'='*60}")
    print(f"Point: ({px:.0f}, {py:.0f})  {label}")
    print(f"Drawings containing this point: {len(containing)}")
    print(f"Drawings nearby (within 30pts): {len(nearby)}")

    if containing:
        print(f"\n  CONTAINING (sorted by area, smallest first):")
        for c in containing[:8]:
            closed = "CLOSED" if c["closed"] else "open"
            filled = f"fill={c['fill']}" if c['fill'] else "no-fill"
            print(f"    [{c['idx']:>4}] {c['w']:>6.0f}x{c['h']:<6.0f} "
                  f"area={c['area']:>8.0f}  segs={c['segments']:>3}  "
                  f"{closed:>6}  {filled}  stroke={c['stroke_w']}")

    if nearby:
        print(f"\n  NEARBY (within 30pts, sorted by distance):")
        for n in nearby[:5]:
            closed = "CLOSED" if n["closed"] else "open"
            print(f"    [{n['idx']:>4}] {n['w']:>6.0f}x{n['h']:<6.0f} "
                  f"dist={n['dist_to_pt']:>5.0f}  segs={n['segments']:>3}  {closed}")

    return containing, nearby


def main():
    doc = fitz.open(str(PDF_PATH))
    page = doc[1]  # page 2

    # Find table boundary
    hits = page.search_for("Parts List")
    table_y = hits[0].y0 if hits else 600

    # Analyze a few key parts
    test_parts = [
        (1, "PUSHBAR"),
        (2, "MID BRACE"),
        (3, "REAR BRACE DS"),
        (4, "REAR BRACE PS"),
        (5, "SIDEPLATE"),
    ]

    for item_no, desc in test_parts:
        # Find callout position
        text_instances = page.search_for(str(item_no))
        for inst in text_instances:
            if inst.y0 >= table_y:
                continue
            expanded = fitz.Rect(inst.x0 - 8, inst.y0 - 3, inst.x1 + 8, inst.y1 + 3)
            surrounding = page.get_text("text", clip=expanded).strip()
            if surrounding == str(item_no):
                cx = (inst.x0 + inst.x1) / 2
                cy = (inst.y0 + inst.y1) / 2
                endpoint = find_leader_endpoint(page, cx, cy)
                if endpoint:
                    analyze_drawings_near_point(
                        page, endpoint[0], endpoint[1],
                        f"Item {item_no}: {desc}"
                    )
                break

    # Also: dump a summary of all drawing sizes on the page
    drawings = page.get_drawings()
    size_buckets = defaultdict(int)
    closed_count = 0
    for d in drawings:
        r = d["rect"]
        area = (r.x1 - r.x0) * (r.y1 - r.y0)
        if area < 10: size_buckets["tiny (<10)"] += 1
        elif area < 100: size_buckets["small (10-100)"] += 1
        elif area < 1000: size_buckets["medium (100-1K)"] += 1
        elif area < 10000: size_buckets["large (1K-10K)"] += 1
        else: size_buckets["huge (10K+)"] += 1
        if d.get("closePath"): closed_count += 1

    print(f"\n{'='*60}")
    print(f"PAGE DRAWING SUMMARY: {len(drawings)} total, {closed_count} closed")
    for bucket, count in sorted(size_buckets.items()):
        print(f"  {bucket}: {count}")

    doc.close()


if __name__ == "__main__":
    main()
