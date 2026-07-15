"""
Convert OPERATIONS_NOTES.md (or any markdown) to a polished .docx.

Usage:
    python scripts/md_to_docx.py SOURCE.md OUTPUT.docx [--title "Title"] [--subtitle "Subtitle"]

Designed for our project ops/handoff documents:
- Title page with title + subtitle + date
- Auto TOC from H1/H2 headings
- Heading styles preserved
- Tables rendered with borders
- Code blocks as monospace + light gray background
- Bullets and numbered lists handled
- Inline code styled
- Hyperlinks active
- Page numbers in footer

Requires: python-docx, markdown
"""

from __future__ import annotations
import argparse
import datetime
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


# --------------------------------------------------------------------------- #
# Style helpers
# --------------------------------------------------------------------------- #


def add_table_borders(table) -> None:
    tbl = table._tbl
    tblPr = tbl.tblPr
    tblBorders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "4")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), "BFBFBF")
        tblBorders.append(b)
    tblPr.append(tblBorders)


def set_cell_background(cell, color_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex)
    tc_pr.append(shd)


def add_page_number_field(paragraph) -> None:
    run = paragraph.add_run()
    fldChar1 = OxmlElement("w:fldChar")
    fldChar1.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = "PAGE \\* MERGEFORMAT"
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "end")
    run._r.append(fldChar1)
    run._r.append(instrText)
    run._r.append(fldChar2)


def add_toc_field(paragraph) -> None:
    """Insert a Word TOC field. Word will populate it on open (Update Field)."""
    run = paragraph.add_run()
    fldChar1 = OxmlElement("w:fldChar")
    fldChar1.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = r'TOC \o "1-3" \h \z \u'
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:r")
    placeholder_t = OxmlElement("w:t")
    placeholder_t.text = "Right-click and select 'Update Field' to populate the table of contents."
    placeholder.append(placeholder_t)
    fldChar3 = OxmlElement("w:fldChar")
    fldChar3.set(qn("w:fldCharType"), "end")
    run._r.append(fldChar1)
    run._r.append(instrText)
    run._r.append(fldChar2)
    run._r.append(placeholder)
    run._r.append(fldChar3)


def add_hyperlink(paragraph, url: str, text: str) -> None:
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    style = OxmlElement("w:rStyle")
    style.set(qn("w:val"), "Hyperlink")
    rPr.append(style)
    new_run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def ensure_styles(doc: Document) -> None:
    """Ensure the styles we rely on exist."""
    styles = doc.styles
    # Hyperlink style
    if "Hyperlink" not in [s.name for s in styles]:
        s = styles.add_style("Hyperlink", WD_STYLE_TYPE.CHARACTER)
        s.font.color.rgb = RGBColor(0x00, 0x66, 0xCC)
        s.font.underline = True
    # InlineCode character style
    if "InlineCode" not in [s.name for s in styles]:
        s = styles.add_style("InlineCode", WD_STYLE_TYPE.CHARACTER)
        s.font.name = "Consolas"
        s.font.size = Pt(10)


# --------------------------------------------------------------------------- #
# Markdown → DOCX
# --------------------------------------------------------------------------- #


INLINE_CODE_RE = re.compile(r"`([^`]+)`")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BOLD_RE = re.compile(r"\*\*([^\*]+)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^\*]+)\*(?!\*)")


def render_inline(paragraph, text: str) -> None:
    """Best-effort inline-formatting render: bold, italic, code, links."""
    # Tokenize into segments
    tokens: list[tuple[str, str, str | None]] = []  # (kind, text, url)
    pos = 0
    text_remaining = text
    while text_remaining:
        # Find earliest match across the patterns
        candidates = []
        for kind, regex in (
            ("link", LINK_RE),
            ("code", INLINE_CODE_RE),
            ("bold", BOLD_RE),
            ("italic", ITALIC_RE),
        ):
            m = regex.search(text_remaining)
            if m:
                candidates.append((m.start(), kind, m))
        if not candidates:
            tokens.append(("plain", text_remaining, None))
            break
        candidates.sort()
        first_start, kind, m = candidates[0]
        if first_start > 0:
            tokens.append(("plain", text_remaining[:first_start], None))
        if kind == "link":
            tokens.append(("link", m.group(1), m.group(2)))
        elif kind == "code":
            tokens.append(("code", m.group(1), None))
        elif kind == "bold":
            tokens.append(("bold", m.group(1), None))
        elif kind == "italic":
            tokens.append(("italic", m.group(1), None))
        text_remaining = text_remaining[m.end():]

    for kind, t, url in tokens:
        if kind == "plain":
            paragraph.add_run(t)
        elif kind == "bold":
            r = paragraph.add_run(t)
            r.bold = True
        elif kind == "italic":
            r = paragraph.add_run(t)
            r.italic = True
        elif kind == "code":
            r = paragraph.add_run(t)
            r.style = "InlineCode"
        elif kind == "link":
            add_hyperlink(paragraph, url, t)


def add_code_block(doc: Document, code: str, lang: str | None = None) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Cm(0.5)
    pf.space_before = Pt(6)
    pf.space_after = Pt(6)
    # Light-gray shading on the paragraph
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F4F4F4")
    pPr.append(shd)
    for i, line in enumerate(code.split("\n")):
        if i > 0:
            r = p.add_run()
            r.add_break()
        r = p.add_run(line)
        r.font.name = "Consolas"
        r.font.size = Pt(9)


def parse_markdown_table(lines: list[str]) -> list[list[str]] | None:
    """Parse a GitHub-style markdown table starting at lines[0]. Returns rows or None."""
    if len(lines) < 2:
        return None
    if not re.match(r"^\s*\|", lines[0]):
        return None
    sep = lines[1].strip()
    if not re.match(r"^\|?\s*[:\-]+\s*(\|\s*[:\-]+\s*)+\|?\s*$", sep):
        return None
    rows = []
    for ln in [lines[0]] + lines[2:]:
        if not re.match(r"^\s*\|", ln):
            break
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def add_table(doc: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=cols)
    add_table_borders(table)
    for ri, row in enumerate(rows):
        cells = table.rows[ri].cells
        for ci in range(cols):
            text = row[ci] if ci < len(row) else ""
            cell = cells[ci]
            cell.text = ""
            p = cell.paragraphs[0]
            render_inline(p, text)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            if ri == 0:
                set_cell_background(cell, "E7EEF7")
                for run in p.runs:
                    run.bold = True


def convert(md_path: Path, docx_path: Path, title: str, subtitle: str) -> None:
    doc = Document()
    # Page setup: US Letter, 1" margins
    section = doc.sections[0]
    section.page_height = Cm(27.94)
    section.page_width = Cm(21.59)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)

    ensure_styles(doc)

    # Footer with page numbers
    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number_field(fp)

    # ---- Title page ----
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(title)
    r.bold = True
    r.font.size = Pt(28)
    p.paragraph_format.space_before = Cm(7)
    p.paragraph_format.space_after = Pt(20)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(subtitle)
    r.italic = True
    r.font.size = Pt(14)
    p.paragraph_format.space_after = Pt(12)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"Generated {datetime.date.today().isoformat()}")
    r.font.size = Pt(11)
    r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---- Table of Contents ----
    p = doc.add_paragraph()
    r = p.add_run("Contents")
    r.bold = True
    r.font.size = Pt(18)
    p.paragraph_format.space_after = Pt(12)
    add_toc_field(doc.add_paragraph())

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---- Body ----
    md_text = md_path.read_text(encoding="utf-8")
    lines = md_text.split("\n")

    i = 0
    in_code = False
    code_lang: str | None = None
    code_buf: list[str] = []

    while i < len(lines):
        line = lines[i]

        # Fenced code blocks
        if line.startswith("```"):
            if not in_code:
                in_code = True
                code_lang = line[3:].strip() or None
                code_buf = []
            else:
                add_code_block(doc, "\n".join(code_buf), code_lang)
                in_code = False
                code_buf = []
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # Headings (ATX)
        if line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
            i += 1
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
            i += 1
            continue
        if line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
            i += 1
            continue
        if line.startswith("#### "):
            doc.add_heading(line[5:].strip(), level=4)
            i += 1
            continue

        # Tables
        if re.match(r"^\s*\|", line):
            tbl_lines: list[str] = []
            j = i
            while j < len(lines) and re.match(r"^\s*\|", lines[j]):
                tbl_lines.append(lines[j])
                j += 1
            rows = parse_markdown_table(tbl_lines)
            if rows is not None:
                add_table(doc, rows)
                i = j
                continue

        # Horizontal rule
        if re.match(r"^\s*---+\s*$", line):
            p = doc.add_paragraph()
            pPr = p._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            top = OxmlElement("w:top")
            top.set(qn("w:val"), "single")
            top.set(qn("w:sz"), "6")
            top.set(qn("w:space"), "1")
            top.set(qn("w:color"), "BFBFBF")
            pBdr.append(top)
            pPr.append(pBdr)
            i += 1
            continue

        # Bulleted list
        m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        if m:
            indent = len(m.group(1)) // 2
            level = min(indent, 8)
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.left_indent = Cm(0.5 + level * 0.4)
            render_inline(p, m.group(2))
            i += 1
            continue

        # Numbered list
        m = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
        if m:
            indent = len(m.group(1)) // 2
            level = min(indent, 8)
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.left_indent = Cm(0.5 + level * 0.4)
            render_inline(p, m.group(2))
            i += 1
            continue

        # Blockquote
        if line.startswith("> "):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            r = p.add_run(line[2:])
            r.italic = True
            r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            i += 1
            continue

        # Blank line
        if not line.strip():
            i += 1
            continue

        # Plain paragraph (consume continuation lines)
        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "```", "|", "-", "*")) and not re.match(r"^\d+\.\s", lines[i]):
            para_lines.append(lines[i])
            i += 1
        text = " ".join(l.strip() for l in para_lines)
        p = doc.add_paragraph()
        render_inline(p, text)

    doc.save(docx_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--title", default="Operations Notes")
    ap.add_argument("--subtitle", default="Working Draft")
    args = ap.parse_args()

    if not args.source.exists():
        print(f"Source not found: {args.source}", file=sys.stderr)
        return 1
    convert(args.source, args.output, args.title, args.subtitle)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
