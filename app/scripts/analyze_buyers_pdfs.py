"""Analyze Buyers Products PDF structure for part-image extraction feasibility."""
import sys, json, re
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF not installed. pip install PyMuPDF")
    sys.exit(1)

PDF_DIR = Path("/tmp/buyers_pdfs")

def analyze_pdf(pdf_path: Path) -> dict:
    doc = fitz.open(str(pdf_path))
    result = {
        "file": pdf_path.name,
        "size_kb": round(pdf_path.stat().st_size / 1024, 1),
        "pages": doc.page_count,
        "page_details": [],
    }

    all_text = ""
    for i, page in enumerate(doc):
        rect = page.rect
        text = page.get_text("text")
        all_text += text + "\n"

        # Count images on this page
        img_list = page.get_images(full=True)

        # Count drawings (vector paths)
        drawings = page.get_drawings()

        # Look for part numbers in text (patterns like 1234567, 16XXXYYY, etc.)
        pn_candidates = re.findall(r'\b\d{5,10}\b', text)
        # Also look for alphanumeric part numbers
        alpha_pn = re.findall(r'\b[A-Z0-9]{2,4}[-]?\d{4,8}[A-Z]?\b', text)

        page_info = {
            "page": i + 1,
            "width_pts": round(rect.width, 1),
            "height_pts": round(rect.height, 1),
            "width_in": round(rect.width / 72, 2),
            "height_in": round(rect.height / 72, 2),
            "text_chars": len(text),
            "text_lines": len(text.strip().split('\n')) if text.strip() else 0,
            "raster_images": len(img_list),
            "vector_drawings": len(drawings),
            "numeric_pn_candidates": len(pn_candidates),
            "alpha_pn_candidates": len(alpha_pn),
            "text_preview": text[:500].replace('\n', '  |  ') if text.strip() else "(no text)",
        }

        # Image details
        if img_list:
            page_info["image_details"] = []
            for img in img_list[:5]:  # first 5
                xref = img[0]
                try:
                    base_image = doc.extract_image(xref)
                    page_info["image_details"].append({
                        "xref": xref,
                        "width": base_image.get("width", "?"),
                        "height": base_image.get("height", "?"),
                        "colorspace": base_image.get("cs-name", "?"),
                        "bpc": base_image.get("bpc", "?"),
                        "size_kb": round(len(base_image.get("image", b"")) / 1024, 1),
                        "ext": base_image.get("ext", "?"),
                    })
                except Exception as e:
                    page_info["image_details"].append({"xref": xref, "error": str(e)})

        # Sample part number candidates
        if pn_candidates:
            page_info["sample_numeric_pns"] = pn_candidates[:15]
        if alpha_pn:
            page_info["sample_alpha_pns"] = alpha_pn[:15]

        # Check for callout patterns (number with leader line = "1", "2" etc near drawings)
        callout_nums = re.findall(r'(?:^|\s)(\d{1,3})(?:\s|$)', text)
        if callout_nums:
            page_info["possible_callout_numbers"] = sorted(set(callout_nums), key=int)[:20]

        result["page_details"].append(page_info)

    # Summary
    result["total_text_chars"] = len(all_text)
    result["total_raster_images"] = sum(p["raster_images"] for p in result["page_details"])
    result["total_vector_drawings"] = sum(p["vector_drawings"] for p in result["page_details"])
    result["has_text_layer"] = len(all_text.strip()) > 50
    result["unique_numeric_pns"] = len(set(re.findall(r'\b\d{5,10}\b', all_text)))

    # Try to identify "parts list" or "exploded view" pages
    exploded_pages = []
    parts_list_pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text").lower()
        if any(kw in text for kw in ["exploded", "parts breakdown", "parts list",
                                      "bill of material", "bom", "item no",
                                      "part no", "ref no", "component"]):
            if "exploded" in text or "breakdown" in text:
                exploded_pages.append(i + 1)
            else:
                parts_list_pages.append(i + 1)

    result["exploded_view_pages"] = exploded_pages
    result["parts_list_pages"] = parts_list_pages

    doc.close()
    return result


def main():
    if not PDF_DIR.exists():
        print(f"ERROR: {PDF_DIR} does not exist")
        sys.exit(1)

    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {PDF_DIR}")
        sys.exit(1)

    print(f"Found {len(pdfs)} PDFs in {PDF_DIR}")
    print("=" * 70)

    for pdf_path in pdfs:
        try:
            result = analyze_pdf(pdf_path)
        except Exception as e:
            print(f"\nERROR analyzing {pdf_path.name}: {e}")
            continue

        print(f"\n{'=' * 70}")
        print(f"FILE: {result['file']}  ({result['size_kb']} KB, {result['pages']} pages)")
        print(f"Text layer: {'YES' if result['has_text_layer'] else 'NO'}")
        print(f"Total raster images: {result['total_raster_images']}")
        print(f"Total vector drawings: {result['total_vector_drawings']}")
        print(f"Unique numeric part numbers found: {result['unique_numeric_pns']}")
        if result['exploded_view_pages']:
            print(f"Exploded view pages: {result['exploded_view_pages']}")
        if result['parts_list_pages']:
            print(f"Parts list pages: {result['parts_list_pages']}")

        for pg in result["page_details"]:
            print(f"\n  --- Page {pg['page']} ---")
            print(f"  Size: {pg['width_in']}\" x {pg['height_in']}\"")
            print(f"  Text: {pg['text_chars']} chars, {pg['text_lines']} lines")
            print(f"  Raster images: {pg['raster_images']}, Vector drawings: {pg['vector_drawings']}")
            print(f"  Numeric PNs: {pg['numeric_pn_candidates']}, Alpha PNs: {pg['alpha_pn_candidates']}")

            if pg.get("sample_numeric_pns"):
                print(f"  Sample numeric PNs: {pg['sample_numeric_pns']}")
            if pg.get("sample_alpha_pns"):
                print(f"  Sample alpha PNs: {pg['sample_alpha_pns']}")
            if pg.get("possible_callout_numbers"):
                print(f"  Callout numbers: {pg['possible_callout_numbers']}")

            if pg.get("image_details"):
                for img in pg["image_details"]:
                    if "error" in img:
                        print(f"    IMG xref={img['xref']}: ERROR {img['error']}")
                    else:
                        print(f"    IMG xref={img['xref']}: {img['width']}x{img['height']} "
                              f"{img['ext']} {img['colorspace']} {img['size_kb']}KB")

            # Truncate text preview
            preview = pg.get("text_preview", "")
            if preview and preview != "(no text)":
                print(f"  Text preview: {preview[:300]}...")

    # Also dump full JSON for programmatic use
    json_path = PDF_DIR / "analysis.json"
    all_results = []
    for pdf_path in pdfs:
        try:
            all_results.append(analyze_pdf(pdf_path))
        except:
            pass
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n\nFull JSON analysis saved to {json_path}")


if __name__ == "__main__":
    main()
