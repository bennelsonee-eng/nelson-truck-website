"""Analyze leader line vector paths from callout bubbles to parts in Buyers PDFs.

Goal: given a callout number's position, find the leader line(s) nearby
and trace them to determine WHERE the actual part is in the diagram.
"""
import sys, re, math
from pathlib import Path

try:
    import fitz
except ImportError:
    print("pip install PyMuPDF")
    sys.exit(1)

PDF_PATH = Path("/tmp/buyers_pdfs/16061030INST_B.pdf")


def dist(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def find_leader_endpoint(page, callout_cx, callout_cy, search_radius=25):
    """Find leader line starting near a callout and return the far endpoint."""
    drawings = page.get_drawings()

    # Collect all line segments
    segments = []
    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "l":  # line segment
                p1 = (item[1].x, item[1].y)
                p2 = (item[2].x, item[2].y)
                segments.append((p1, p2))

    # Find segments with one endpoint near the callout
    callout_pos = (callout_cx, callout_cy)
    nearby = []
    for p1, p2 in segments:
        d1 = dist(p1, callout_pos)
        d2 = dist(p2, callout_pos)
        if d1 < search_radius:
            nearby.append({"near": p1, "far": p2, "near_dist": d1, "seg": (p1, p2)})
        elif d2 < search_radius:
            nearby.append({"near": p2, "far": p1, "near_dist": d2, "seg": (p1, p2)})

    if not nearby:
        return None, nearby

    # Sort by distance from callout — closest first
    nearby.sort(key=lambda x: x["near_dist"])

    # The leader line might be multi-segment. Try to follow connected segments.
    # Start from the nearest segment's far endpoint and keep going.
    best = nearby[0]
    current_end = best["far"]
    visited_segs = {best["seg"]}
    max_hops = 5

    for _ in range(max_hops):
        # Find another segment with an endpoint near current_end
        found_next = False
        for p1, p2 in segments:
            seg = (p1, p2)
            if seg in visited_segs:
                continue
            d1 = dist(p1, current_end)
            d2 = dist(p2, current_end)
            if d1 < 5:  # connected at p1
                current_end = p2
                visited_segs.add(seg)
                found_next = True
                break
            elif d2 < 5:  # connected at p2
                current_end = p1
                visited_segs.add(seg)
                found_next = True
                break
        if not found_next:
            break

    return current_end, nearby


def main():
    doc = fitz.open(str(PDF_PATH))
    page = doc[1]  # page 2 (0-indexed) — the diagram + parts list page

    # Find "Parts List" Y to know diagram boundary
    hits = page.search_for("Parts List")
    table_y = hits[0].y0 if hits else page.rect.height * 0.65
    print(f"Table starts at Y={table_y:.1f}")

    # Known callout positions from the extraction script (search for standalone numbers)
    callout_nums = list(range(1, 20))
    results = []

    for item_no in callout_nums:
        text_instances = page.search_for(str(item_no))
        # Filter to diagram area and standalone
        for inst in text_instances:
            if inst.y0 >= table_y:
                continue
            expanded = fitz.Rect(inst.x0 - 8, inst.y0 - 3, inst.x1 + 8, inst.y1 + 3)
            surrounding = page.get_text("text", clip=expanded).strip()
            if surrounding == str(item_no):
                cx = (inst.x0 + inst.x1) / 2
                cy = (inst.y0 + inst.y1) / 2

                endpoint, nearby = find_leader_endpoint(page, cx, cy, search_radius=25)

                if endpoint:
                    dx = endpoint[0] - cx
                    dy = endpoint[1] - cy
                    leader_len = dist(endpoint, (cx, cy))
                    print(f"  Callout {item_no:>2}: bubble=({cx:.0f},{cy:.0f})  "
                          f"part=({endpoint[0]:.0f},{endpoint[1]:.0f})  "
                          f"leader={leader_len:.0f}pts  "
                          f"nearby_segs={len(nearby)}")
                    results.append({
                        "item": item_no,
                        "callout": (cx, cy),
                        "part": endpoint,
                        "leader_len": leader_len,
                    })
                else:
                    print(f"  Callout {item_no:>2}: bubble=({cx:.0f},{cy:.0f})  "
                          f"NO LEADER LINE FOUND (nearby_segs={len(nearby)})")
                break  # only first match per callout

    doc.close()

    print(f"\nFound leader endpoints for {len([r for r in results if r['part']])} / {len(results)} callouts")


if __name__ == "__main__":
    main()
