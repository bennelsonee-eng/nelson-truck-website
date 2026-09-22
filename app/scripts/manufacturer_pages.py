"""Parsers for truck-body manufacturer model pages (knapheide.com, cmtruckbeds.com).

Both sites are public WordPress. These read a model page's saved HTML and return
the parts our product page can show:

    intro         marketing paragraph(s)             -> product.description
    features      standard equipment, heading + text -> product_description FEA
    options       optional equipment, name + text    -> product_description OPT
    spec_kv       key/value spec rows (CM)           -> product_attribute
    spec_tables   model matrices                     -> product_spec_table
    literature    PDF title + url                    -> product_resource
    drawings      dimension drawings a table refers to -> product_image

Layout notes, learned the hard way:
  * Knapheide standard features are `vi-feature-title` / `vi-feature-content`
    divs, not <p>. Option text lives in "More Details" pop-ups
    (<h5 class="modal-title"> + <div class="modal-body">), matched by name --
    the pop-ups nest `modal-dialog`/`modal-content` divs, so anything that stops
    at the next "<div class=\"modal" stops immediately.
  * Knapheide's first `pp-photo-img` is the mega-menu, not the model's photo.
  * CM's h2 above the specs is usually a site-wide tagline ("Set the standard.");
    the model's own prose is the paragraph under it. Some CM pages render their
    spec block from an empty PHP widget -- CM publishes no specs there.
  * CM's Configurations table labels its columns A/B/C; those letters are only
    defined by the two drawings beside it, so the drawings travel with it.
"""
from __future__ import annotations

import html as _html
import re


def one_line(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _dedupe_blocks(items: list[dict], key: str, body: str) -> list[dict]:
    """Drop repeats by heading, and by identical body under a different heading
    (CM prints the same frame-rail paragraph as both "Structual" and "structural")."""
    out, seen_k, seen_b = [], set(), set()
    for it in items:
        k = it[key].strip().lower()
        b = (it.get(body) or "")[:120].strip().lower()
        if k in seen_k or (b and b in seen_b):
            continue
        seen_k.add(k)
        if b:
            seen_b.add(b)
        out.append(it)
    return out


# ---------------------------------------------------------------- Knapheide --

def _kn_section(h: str, title: str) -> int:
    m = re.search(r"(?is)<h3[^>]*>\s*%s\s*</h3>" % re.escape(title), h)
    return m.start() if m else -1


def _kn_table(t: str) -> tuple[list[str], list[dict]]:
    thead = re.search(r"(?is)<thead.*?</thead>", t)
    headers = [one_line(c) for c in re.findall(r"(?is)<th[^>]*>(.*?)</th>", thead.group(0))] if thead else []
    tbody = re.search(r"(?is)<tbody.*?</tbody>", t)
    raw = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tbody.group(0) if tbody else t):
        cells = []
        for m in re.finditer(r"(?is)<t[hd]([^>]*)>(.*?)</t[hd]>", tr):
            span = re.search(r'colspan="?(\d+)', m.group(1))
            cells.append((one_line(m.group(2)), int(span.group(1)) if span else 1))
        if any(c[0] for c in cells):
            raw.append(cells)
    if not headers and raw:
        headers, raw = [c[0] for c in raw[0]], raw[1:]
    rows = []
    for cells in raw:
        filled = [c for c in cells if c[0]]
        first = cells[0]
        # A cab-to-axle heading spans the table (or is the only filled cell).
        if first[0] and (first[1] > 1 or (len(filled) == 1 and len(first[0]) > 12 and len(headers) > 2)):
            rows.append({"type": "group", "label": first[0]})
        else:
            rows.append({"type": "row", "cells": [c[0] for c in cells][: len(headers)]})
    return headers, rows


def parse_knapheide(h: str, base: str = "https://www.knapheide.com") -> dict:
    out: dict = {}
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", h)
    out["title"] = one_line(h1.group(1)) if h1 else None
    start = h1.end() if h1 else 0
    sec = {k: _kn_section(h, k) for k in
           ("Body Options", "Add-ons", "Specifications", "Gallery", "Literature", "Resources")}

    first_feature = re.search(r'(?is)<h4 class="vi-feature-title">', h[start:])
    intro_end = start + (first_feature.start() if first_feature else 20000)
    out["intro"] = [p for p in (one_line(x) for x in re.findall(r"(?is)<p[^>]*>(.*?)</p>", h[start:intro_end]))
                    if len(p) > 60]

    feats = [{"heading": one_line(a), "body": one_line(b)} for a, b in re.findall(
        r'(?is)<h4 class="vi-feature-title">(.*?)</h4>\s*<div class="vi-feature-content">(.*?)</div>', h)]
    out["features"] = _dedupe_blocks([f for f in feats if f["heading"] and f["body"]], "heading", "body")

    modals: dict[str, str] = {}
    for name, body in re.findall(r'(?is)<h5 class="modal-title"[^>]*>(.*?)</h5>.*?<div class="modal-body">(.*?)</div>', h):
        n, b = one_line(name), one_line(body)
        if n and b:
            modals.setdefault(n.lower(), b)
    opts = []
    if sec["Body Options"] > 0:
        o = sec["Body Options"]
        end = min(x for x in (sec["Add-ons"], sec["Specifications"], sec["Gallery"], sec["Literature"], len(h)) if x > o)
        for m in re.finditer(r"(?is)<h4[^>]*>(.*?)</h4>", h[o:end]):
            name = one_line(m.group(1))
            if name and name.lower() != "more details":
                opts.append({"name": name, "description": modals.get(name.lower())})
    out["options"] = _dedupe_blocks(opts, "name", "description")

    tables = []
    if sec["Specifications"] > 0:
        s = sec["Specifications"]
        end = min(x for x in (sec["Gallery"], sec["Literature"], sec["Resources"], len(h)) if x > s)
        for m in re.finditer(r"(?is)(?:<h4[^>]*>(.*?)</h4>\s*)?(<table.*?</table>)", h[s:end]):
            headers, rows = _kn_table(m.group(2))
            if headers and rows:
                tables.append({"title": one_line(m.group(1)) if m.group(1) else None,
                               "headers": headers, "rows": rows, "note": None})
    out["spec_tables"] = tables
    out["spec_kv"] = []
    out["spec_note"] = None

    lit, seen = [], set()
    if sec["Literature"] > 0:
        lo = sec["Literature"]
        end = min(x for x in (sec["Resources"], len(h)) if x > lo)
        for a in re.finditer(r"(?is)<a\b([^>]*)>", h[lo:end]):
            href = re.search(r'href="([^"]+\.pdf)"', a.group(1), re.I)
            title = re.search(r'title="([^"]*)"', a.group(1))
            if href and href.group(1) not in seen:
                seen.add(href.group(1))
                lit.append({"title": _html.unescape(title.group(1)).strip() if title else None,
                            "url": href.group(1)})
    out["literature"] = lit
    out["drawings"] = []
    return out


# -------------------------------------------------------------- CM Truck Beds --

def _cm_heads(h: str):
    return [(m.start(), m.end(), m.group(1).lower(), one_line(m.group(2)))
            for m in re.finditer(r"(?is)<(h[1-4])[^>]*>(.*?)</\1>", h)]


def _cm_find(hs, text, level=None):
    for s, e, lv, t in hs:
        if t.lower().startswith(text.lower()) and (level is None or lv == level):
            return s, e
    return None


def _cm_blocks(h, hs, start, end, levels=("h4",)):
    inner = [x for x in hs if start < x[0] < end and x[2] in levels]
    out = []
    for i, (s, e, lv, t) in enumerate(inner):
        nxt = inner[i + 1][0] if i + 1 < len(inner) else end
        out.append((t, one_line(h[e:nxt])))
    return out


def parse_cm(h: str, base: str = "https://cmtruckbeds.com") -> dict:
    hs = _cm_heads(h)
    out: dict = {}
    h1 = next((x for x in hs if x[2] == "h1"), None)
    out["title"] = h1[3] if h1 else None
    specs_h = _cm_find(hs, "Specs & Features")
    std_h = _cm_find(hs, "Standard Equipment")
    opt_h = _cm_find(hs, "Available Options")
    cfg_h = _cm_find(hs, "Configurations", "h3")
    bro_h = _cm_find(hs, "Brochure", "h3")
    news_h = _cm_find(hs, "CM Truck Beds News")
    end_all = min(x for x in (bro_h and bro_h[0], news_h and news_h[0], len(h)) if x)

    intro = []
    if specs_h:
        h2s = [x for x in hs if x[2] == "h2" and x[0] < specs_h[0]]
        if h2s:
            e0 = h2s[-1][1]
            intro = [p for p in (one_line(x) for x in re.findall(r"(?is)<p[^>]*>(.*?)</p>", h[e0:specs_h[0]]))
                     if len(p) > 40]
            if not intro:
                raw = one_line(h[e0:specs_h[0]])
                if len(raw) > 60:
                    intro = [raw]
    if not intro:
        md = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', h)
        if md and len(md.group(1)) > 40:
            intro = [_html.unescape(md.group(1)).strip()]
    out["intro"] = intro

    kv = []
    for m in re.finditer(r"(?is)<table.*?</table>", h[:cfg_h[0] if cfg_h else end_all]):
        rows = [[one_line(c) for c in re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", tr)]
                for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group(0))]
        rows = [r for r in rows if any(r)]
        if not rows or any("financ" in " ".join(r).lower() or r[0].lower() == "program" for r in rows[:2]):
            continue
        if all(len(r) == 2 for r in rows):
            kv += [(k, v) for k, v in rows if k and v]
    out["spec_kv"] = kv

    note = None
    if specs_h and std_h:
        seg = one_line(h[specs_h[1]:std_h[0]])
        mnote = re.search(r"\*\s([^*]{20,300}?)(?:\s+Download|\s+VIEW|$)", seg)
        note = mnote.group(1).strip() if mnote else None
    out["spec_note"] = note

    feats = []
    if std_h:
        stop = min(x for x in (opt_h and opt_h[0], cfg_h and cfg_h[0], end_all) if x)
        feats = [{"heading": t, "body": b} for t, b in _cm_blocks(h, hs, std_h[1], stop, ("h3", "h4"))
                 if t and len(b) > 20]

    tables, drawings = [], []
    if cfg_h:
        seg_end = min(x for x in (bro_h and bro_h[0], news_h and news_h[0], len(h)) if x > cfg_h[1])
        seg = h[cfg_h[1]:seg_end]
        m = re.search(r"(?is)<table.*?</table>", seg)
        if m:
            rows = [[one_line(c) for c in re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", tr)]
                    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group(0))]
            rows = [r for r in rows if any(r)]
            if len(rows) > 1:
                tables.append({"title": "Configurations", "headers": rows[0],
                               "rows": [{"type": "row", "cells": r} for r in rows[1:]], "note": None})
            # compartment layouts: "V Configuration (76, 81 ...)" followed by "1st Vertical: ..." lines
            lines = [one_line(x) for x in re.findall(r"(?is)<(?:p|h4|h5|li)[^>]*>(.*?)</(?:p|h4|h5|li)>",
                                                     seg[m.end():])]
            group = None
            for ln in (x for x in lines if x):
                if re.match(r"(?i)^[A-Z]{1,3}\s+Configuration\s*\(", ln):
                    group = {"heading": f"Compartment layout — {ln}", "lines": []}
                    feats.append(group)
                elif group is not None and ":" in ln:
                    group["lines"].append(ln)
            for g in feats:
                if "lines" in g:
                    g["body"] = "\n".join(g.pop("lines"))
        drawings = list(dict.fromkeys(re.findall(
            r'(?:data-orig-src|data-src|src)="(https://cmtruckbeds\.com/wp-content/uploads/[^"]+\.(?:png|jpe?g|webp))"',
            seg)))
    out["features"] = _dedupe_blocks([f for f in feats if f.get("body")], "heading", "body")
    out["spec_tables"] = tables
    out["drawings"] = drawings

    opts = []
    if opt_h:
        stop = min(x for x in (cfg_h and cfg_h[0] > opt_h[0] and cfg_h[0], end_all) if x)
        opts = [{"name": t, "description": b} for t, b in _cm_blocks(h, hs, opt_h[1], stop, ("h3", "h4"))
                if t and len(b) > 20]
    out["options"] = _dedupe_blocks(opts, "name", "description")

    lit, seen = [], set()
    for a in re.finditer(r"(?is)<a\b([^>]*)>(.*?)</a>", h[:end_all]):
        href = re.search(r'href="([^"]+\.pdf)(?:[?#][^"]*)?"', a.group(1), re.I)
        if not href:
            continue
        url = href.group(1)
        if url.startswith("/"):
            url = base.rstrip("/") + url          # two CM pages link their PDF by path only
        if url not in seen:
            seen.add(url)
            lit.append({"title": one_line(a.group(2)) or None, "url": url})
    out["literature"] = lit
    return out


# ------------------------------------------------------------------- Rugby --

_OPTIONISH = re.compile(r"\boption(al|s)?\b|\bavailable\b|\bupgrade\b", re.I)


def parse_rugby(h: str, base: str = "https://www.rugbymfg.com") -> dict:
    """rugbymfg.com product ("portfolio") pages: OVERVIEW paragraph, a FEATURES
    accordion of <h4> sub-sections each followed by a <ul>, and LITERATURE &
    MANUALS with "Product Literature" and "Manuals" link lists (relative hrefs).
    Rugby lists features and options in one "Features & Options" list, so a
    line that says optional/available/upgrade is filed as an option."""
    out: dict = {}
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", h)
    out["title"] = one_line(h1.group(1)) if h1 else None
    og = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', h)
    out["og_image"] = og.group(1) if og else None

    ov = re.search(r"(?is)>\s*OVERVIEW\s*<", h)
    feat = re.search(r"(?is)>\s*FEATURES\s*<", h)
    lit = re.search(r"(?is)>\s*LITERATURE\s*(?:&amp;|&)\s*MANUALS\s*<", h)
    rel = re.search(r"(?is)<h3[^>]*>\s*Related Products\s*</h3>", h)
    end = rel.start() if rel else len(h)

    intro = []
    if ov:
        stop = feat.start() if feat and feat.start() > ov.end() else ov.end() + 20000
        intro = [p for p in (one_line(x) for x in re.findall(r"(?is)<p[^>]*>(.*?)</p>", h[ov.end():stop])) if len(p) > 40]
    out["intro"] = intro

    kv, feats, opts = [], [], []
    if feat:
        seg = h[feat.end(): lit.start() if lit and lit.start() > feat.end() else end]
        # Two layouts: "<h4>Specifications</h4><ul><li>..." and (Eliminator pages)
        # "<p><strong>Specifications</strong></p><p>line<br/>line</p>".
        sections: list[tuple[str, list[str]]] = []
        token = re.compile(
            r"(?is)<h4[^>]*>(?P<h4>.*?)</h4>"
            r"|<p[^>]*>\s*<strong>(?P<ph>[^<]{2,40})</strong>\s*</p>"
            r"|<ul[^>]*>(?P<ul>.*?)</ul>"
            r"|<p[^>]*>(?P<p>.*?)</p>")
        for m in token.finditer(seg):
            if m.group("h4") is not None or m.group("ph") is not None:
                sections.append((one_line(m.group("h4") or m.group("ph")), []))
            elif sections and m.group("ul") is not None:
                sections[-1][1].extend(one_line(li) for li in re.findall(r"(?is)<li[^>]*>(.*?)</li>", m.group("ul")))
            elif sections and m.group("p") is not None:
                sections[-1][1].extend(one_line(x) for x in re.split(r"(?i)<br\s*/?>", m.group("p")))
        for head, items in sections:
            items = [i for i in items if i]
            if not items:
                continue
            hl = head.lower()
            if hl == "materials":
                kv.append(("Materials", "; ".join(items)))
            elif "option" in hl and "feature" not in hl:
                opts += [{"name": i, "description": None} for i in items]
            else:
                for i in items:
                    k, sep, v = i.partition(":")
                    if sep and 0 < len(k) <= 40 and v.strip():
                        kv.append((k.strip(), v.strip()))
                    elif _OPTIONISH.search(i):
                        opts.append({"name": i, "description": None})
                    else:
                        feats.append({"heading": "", "body": i})
    out["spec_kv"] = kv
    out["features"] = feats
    out["options"] = opts
    out["spec_tables"] = []
    out["spec_note"] = None
    out["drawings"] = []

    literature, seen = [], set()
    if lit:
        seg = h[lit.end():end]
        # "Product Literature" / "Manuals" sub-headings tell a brochure from a manual
        marks = [(m.start(), one_line(m.group(1)).lower()) for m in re.finditer(r"(?is)<h4[^>]*>(.*?)</h4>", seg)]
        for a in re.finditer(r'(?is)<a\b[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', seg):
            url = a.group(1)
            if url.startswith("/"):
                url = base.rstrip("/") + url
            if url in seen:
                continue
            seen.add(url)
            section = next((t for pos, t in reversed(marks) if pos < a.start()), "")
            kind = "manual" if "manual" in section else "brochure"
            title = one_line(a.group(2)) or None
            # the Manuals list titles some links with just the model ("Titan")
            if title and kind == "manual" and "manual" not in title.lower():
                title = f"{title} Manual"
            literature.append({"title": title, "url": url, "kind": kind})
    out["literature"] = literature
    return out


# --------------------------------------------------------------- Dur-A-Lift --

_DAL_SKIP = re.compile(r"about dur-a-lift", re.I)
_DAL_OPTIONS = re.compile(r"option", re.I)
_DAL_SPECS = re.compile(r"spec|dimension|weight|performance|tracks|steering", re.I)


def parse_duralift(h: str, base: str = "https://dur-a-lift.com") -> dict:
    """dur-a-lift.com product pages: a header with ◼ bullets and a per-model
    "Max working height / side reach" list; an Overview tab of <details>
    sections (Product Overview, Specifications -- often an IMAGE of the spec
    chart --, Standard Features, Options, Basket Styles ...); a Photos tab whose
    links point at full-size originals; a Videos tab (YouTube) and a Builds tab
    (units built for named customers -- not used)."""
    out: dict = {}
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", h)
    out["title"] = one_line(h1.group(1)) if h1 else None
    md = re.search(r'<meta\s+(?:name|property)="(?:og:)?description"\s+content="([^"]*)"', h)
    intro = [_html.unescape(md.group(1)).strip()] if md and len(md.group(1)) > 40 else []

    # header: "<p><strong>Max working height / side reach:</strong><br/> DPM2-52: 59′ / 31′6″<br/> ..."
    tables = []
    head_end = h.find('role="tablist"') if 'role="tablist"' in h else (h1.end() + 6000 if h1 else 0)
    header = h[h1.end():head_end] if h1 else ""
    for m in re.finditer(r"(?is)<p[^>]*>\s*<strong>([^<]{4,80}?):?\s*</strong>(.*?)</p>", header):
        label = one_line(m.group(1)).rstrip(":")
        rows = []
        for line in re.split(r"(?i)<br\s*/?>", m.group(2)):
            k, sep, v = one_line(line).partition(":")
            if sep and k and v.strip():
                rows.append({"type": "row", "cells": [k.strip(), v.strip()]})
        if len(rows) >= 1:
            tables.append({"title": label, "headers": ["Model", label], "rows": rows, "note": None})
    if not intro:
        paras = [one_line(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", header)]
        intro = [p for p in paras if len(p) > 60 and "◼" not in p][:1]
    out["intro"] = intro

    feats, opts, kv, charts = [], [], [], []
    models = re.search(r"(?is)Models:\s*([^<]{3,200})<", h)
    if models:
        kv.append(("Models", one_line(models.group(1))))
    for m in re.finditer(r"(?is)<details[^>]*>\s*<summary[^>]*>(.*?)</summary>(.*?)</details>", h):
        title = one_line(m.group(1))
        body = m.group(2)
        if not title or _DAL_SKIP.search(title):
            continue
        items = [one_line(li) for li in re.findall(r"(?is)<li[^>]*>(.*?)</li>", body)]
        items = [i for i in items if i]
        paras = [one_line(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", body)]
        paras = [p for p in paras if len(p) > 20 and not p.lower().startswith("read more")]
        imgs = re.findall(r'src="(https?://dur-a-lift\.com/wp-content/uploads/[^"]+\.(?:png|jpe?g|webp))"', body, re.I)
        pretty = title if not title.isupper() else title.capitalize()
        if _DAL_OPTIONS.search(title):
            opts += [{"name": i, "description": None} for i in items]
            opts += [{"name": p, "description": None} for p in paras]
        elif _DAL_SPECS.search(title):
            for i in items + paras:
                k, sep, v = i.partition(":")
                if sep and 0 < len(k) <= 50 and v.strip():
                    kv.append((k.strip(), v.strip()))
                else:
                    feats.append({"heading": pretty, "body": i})
            charts += [re.sub(r"-\d{2,4}x\d{2,4}(?=\.\w+$)", "", u) for u in imgs]
        elif title.lower() in ("product overview", "standard features"):
            for i in items:
                (opts.append({"name": i, "description": None}) if re.search(r"\boption", i, re.I)
                 else feats.append({"heading": "", "body": i}))
            feats += [{"heading": "", "body": p} for p in paras]
        else:
            text = "\n".join(items + paras)
            if text:
                feats.append({"heading": pretty, "body": text})
    out["features"] = _dedupe_blocks([f for f in feats if f.get("body")], "body", "body")
    out["options"] = _dedupe_blocks(opts, "name", "name")
    out["spec_kv"] = kv
    out["spec_tables"] = tables
    out["spec_note"] = None
    out["drawings"] = list(dict.fromkeys(charts))           # spec charts: shown in the gallery

    # Photos tab: each thumbnail links to its full-size original
    photos = []
    pi, vi = h.find('id="tab-photos"'), h.find('id="tab-videos"')
    if pi > 0:
        seg = h[pi: vi if vi > pi else pi + 60000]
        for u in re.findall(r'href="(https?://dur-a-lift\.com/wp-content/uploads/[^"]+\.(?:png|jpe?g|webp))"', seg, re.I):
            if "screenshot" not in u.lower() and u not in photos:
                photos.append(u)
    out["photos"] = photos
    out["videos"] = sorted(set(re.findall(r"(?:youtube(?:-nocookie)?\.com/embed/|youtu\.be/|watch\?v=)([A-Za-z0-9_-]{11})",
                                          h[vi: h.find('id="tab-builds"')] if vi > 0 else "")))

    literature, seen = [], set()
    for a in re.finditer(r'(?is)<a\b[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', h):
        url = a.group(1) if a.group(1).startswith("http") else base.rstrip("/") + a.group(1)
        if url not in seen:
            seen.add(url)
            t = one_line(a.group(2))
            # the link text is usually just "Product Literature"; say which product
            if not t or len(t) <= 3 or t.lower() in ("product literature", "literature", "download", "brochure"):
                t = f"{out['title']} Literature"
            literature.append({"title": t, "url": url})
    out["literature"] = literature
    return out


PARSERS = {"knapheide": parse_knapheide, "cm": parse_cm, "rugby": parse_rugby, "duralift": parse_duralift}
