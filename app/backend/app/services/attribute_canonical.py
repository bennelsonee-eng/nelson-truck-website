"""Attribute value canonicalization + clustering for the admin curator.

PIES `product_attribute` values arrive from supplier feeds in inconsistent
spellings.  This module owns two responsibilities:

1.  Deterministic auto-canonicalization.  Given a raw value, produce a
    cleaned display label (Title Case, normalized whitespace, plural-fold).
    This runs without DB I/O so every browse / facets call can fold raw
    rows on the fly without an extra round-trip.

2.  Cluster suggestion.  Given the post-auto raw-value list for an
    attribute_key, propose groups of values that look like the same thing
    (edit-distance, token-set Jaccard) so the curator can confirm a merge
    with one click instead of pairing values manually.

The DB only stores **manual** overrides — see `AttributeValueAlias.source`.
Anything not in the alias table falls back to auto-canonical().
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable


# ----------------------------------------------------------------------------
# Auto-canonicalization
# ----------------------------------------------------------------------------

# Words that should stay lowercase inside Title Case unless they sit at
# the start of the value ("of Steel" but "Steel of Aluminum" → "Steel of
# Aluminum"). Small + common — not exhaustive, but covers the cases that
# normally trip up plain str.title().
_TITLE_LOWERCASE = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "of",
    "on", "or", "the", "to", "vs", "via", "with",
}

# Words that should stay UPPERCASE regardless of position — supplier-specific
# trademark / acronym shorthand we see often in PIES feeds.
_TITLE_UPPERCASE = {
    "tpe", "hdpe", "ldpe", "uhmw", "pvc", "abs", "uv", "led", "ec", "us",
    "usa", "rv", "atv", "utv", "suv", "oem", "pto", "wd1", "wd2", "wd3",
    "wd4", "wd5", "wd6", "wd7", "wd8", "wd9", "msrp", "msr", "jbr", "ret",
    "carb", "epa", "iso", "sae", "din", "cnc", "csa", "fmvss",
}


def _case_letters_only(word: str) -> str:
    """Title-case a single bare (no-punctuation) word, respecting the
    upper/lower allowlists.  Helper for the punctuation-aware path."""
    if not word:
        return word
    low = word.lower()
    if low in _TITLE_UPPERCASE:
        return low.upper()
    if low in _TITLE_LOWERCASE:
        return low
    return low[:1].upper() + low[1:]


def _smart_titlecase_word(word: str) -> str:
    """Title-case a single whitespace-token.  Splits on punctuation so
    "(TPE)" → "(TPE)" (the acronym stays UPPERCASE) and "tie-downs" →
    "Tie-Downs" (each sub-segment capitalized)."""
    if not word:
        return word
    # Split on punctuation runs, keeping them as separators so we can
    # re-stitch the word exactly as it came in.
    parts = re.split(r"([^\w]+)", word)
    out: list[str] = []
    for p in parts:
        if not p or not re.search(r"\w", p):
            # Punctuation/whitespace separator — preserve as-is
            out.append(p)
        else:
            out.append(_case_letters_only(p))
    return "".join(out)


def smart_titlecase(value: str) -> str:
    """Title-case respecting acronym + small-word conventions.

    Differs from `str.title()` in three ways:
      - Recognized acronyms (TPE, HDPE, …) stay UPPERCASE, even when
        wrapped in punctuation: "(TPE)" → "(TPE)".
      - Small connector words (a, of, the, …) stay lowercase, except
        when they're the first token of the value.
      - Hyphenated words capitalize each subtoken: "tie-downs" → "Tie-Down".
    """
    if not value:
        return value
    parts = value.split()
    out: list[str] = []
    for i, p in enumerate(parts):
        word = _smart_titlecase_word(p)
        if i == 0 and word.lower() in _TITLE_LOWERCASE:
            word = word.capitalize()
        out.append(word)
    return " ".join(out)


_PLURAL_EXCEPTIONS = {
    # words that look plural but aren't — leave them alone
    "brass", "glass", "stainless", "pass", "class", "less", "gloss",
    "press", "stress", "process", "access", "address", "express",
}


def _depluralize(token: str) -> str:
    """Cheap singular-fold: 'rings' → 'ring', 'boxes' → 'box', etc.

    Conservative — only handles the common English endings.  Skips:
      - words in `_PLURAL_EXCEPTIONS` (brass, glass, etc. that look plural)
      - acronyms in `_TITLE_UPPERCASE` (ABS, etc.)
      - short tokens (≤ 3 chars)
    """
    low = token.lower()
    if low in _PLURAL_EXCEPTIONS:
        return token
    if low in _TITLE_UPPERCASE:
        return token
    if len(low) <= 3:
        return token
    if low.endswith("ies") and len(low) > 4:
        return token[:-3] + "y"
    if low.endswith("ses") or low.endswith("xes") or low.endswith("zes"):
        return token[:-2]
    if low.endswith("ches") or low.endswith("shes"):
        return token[:-2]
    if low.endswith("s") and not low.endswith("ss"):
        return token[:-1]
    return token


def _depluralize_punctuated(word: str) -> str:
    """Depluralize each alphanumeric subtoken of a word, preserving any
    interleaved punctuation.  "PVC/ABS" → "PVC/ABS" (each is an acronym
    and skips depluralize); "tie-downs" → "tie-down"."""
    parts = re.split(r"([^\w]+)", word)
    out: list[str] = []
    for p in parts:
        if not p or not re.search(r"\w", p):
            out.append(p)
        else:
            out.append(_depluralize(p))
    return "".join(out)


def auto_canonical(raw: str | None) -> str:
    """Deterministic display canonical for a raw PIES attribute value.

    Applies, in order: NBSP → space, Unicode NFKC normalization,
    whitespace collapse + trim, plural-fold per token, smart Title Case.
    """
    if raw is None:
        return ""
    s = raw.replace(" ", " ")
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    # Plural-fold each whitespace-token's alphanumeric subtokens before
    # re-casing.  Punctuation-aware so "PVC/ABS" survives ("ABS" is an
    # acronym, skips depluralize) and "tie-downs" → "tie-down".
    folded = " ".join(_depluralize_punctuated(tok) for tok in s.split(" "))
    return smart_titlecase(folded)


# ----------------------------------------------------------------------------
# Clustering — for the admin curator's "suggested merges" section
# ----------------------------------------------------------------------------


def _tokenize_for_match(value: str) -> set[str]:
    """Lowercase + punctuation-stripped token set used by the Jaccard
    similarity heuristic.  Drops 1-char tokens (mostly noise)."""
    cleaned = re.sub(r"[^\w\s]", " ", value.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return {t for t in cleaned.split(" ") if len(t) > 1}


def _levenshtein(a: str, b: str) -> int:
    """Standard DP edit distance.  Small inputs so iterative + O(len(a)*len(b))
    is fine — values are < 80 chars in practice."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, dele, sub))
        prev = cur
    return prev[-1]


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numeric_signature(value: str) -> tuple[str, ...]:
    """Ordered tuple of the numbers in a value, thousands-separators removed
    and integer-valued decimals normalized ("2,000" → "2000",
    "2000.0" → "2000").

    Numbers are semantically significant in product attributes: "1000 Lbs"
    and "1500 Lbs" sit one edit-distance apart but are *different
    capacities*, not a typo.  Two values can only describe the same physical
    attribute if their numeric signatures match exactly.
    """
    out: list[str] = []
    for m in _NUM_RE.findall(value):
        s = m.replace(",", "")
        try:
            f = float(s)
        except ValueError:
            out.append(s)
            continue
        out.append(str(int(f)) if f == int(f) else repr(f))
    return tuple(out)


def _unit_residue(value: str) -> str:
    """Letters-only residue (lowercased, trailing-'s' folded, space-collapsed)
    for comparing two values that already share the same number(s).  Folds a
    trailing 's' so "Lbs"/"Lb" and "Lbs."/"Lb" agree — the depluralize helper
    skips ≤3-char tokens, so unit words like "lbs"/"tons" need this."""
    letters = re.sub(r"[^a-zA-Z\s]", " ", value).lower()
    toks = [t[:-1] if t.endswith("s") and len(t) > 1 else t for t in letters.split()]
    return " ".join(toks)


def _similar_enough(a: str, b: str) -> bool:
    """Heuristic that decides whether two raw values should suggest a merge.

    First gate: the two values must share the same numeric signature
    (see `_numeric_signature`).  Differing numbers ⇒ different attribute,
    no matter how few characters separate them — this is what stops a
    "Capacity" key from folding 1000/1500/2000/3000 Lbs into one bucket.

    Given matching numbers, triggers if ANY of:
      0. Same number(s) AND same unit residue — only formatting/punctuation
         differs ("2,000 Lb" / "2000 Lbs.")
      1. Edit distance ≤ 2 AND both values are ≥ 4 chars
         (catches "Aluminum" / "Aluminm", "Powder Coat" / "Powder Coated")
      2. Token-set Jaccard ≥ 0.66 with both having ≥ 2 meaningful tokens
         (catches "TPE - Thermoplastic Elastomer" / "Thermoplastic
         Elastomer (TPE)")
      3. Normalized form is identical after dropping parenthetical
         segments + punctuation (catches "Steel (Galvanized)" / "Steel")

    Returns False for short strings where edit distance is too forgiving
    ("Tan" vs "Red" is distance 3 but obviously different — handled by
    the >=4 chars guard).
    """
    if a == b:
        return True

    sig_a = _numeric_signature(a)
    sig_b = _numeric_signature(b)
    if sig_a != sig_b:
        return False
    if sig_a and _unit_residue(a) == _unit_residue(b):
        return True

    al = len(a)
    bl = len(b)
    if al >= 4 and bl >= 4:
        # Relative threshold for longer strings — distance 2 in "Aluminum" (8)
        # is fine; distance 2 in "RV" would over-merge.  Cap absolute at 3.
        cap = min(3, max(1, max(al, bl) // 5))
        if _levenshtein(a.lower(), b.lower()) <= cap:
            return True

    ta = _tokenize_for_match(a)
    tb = _tokenize_for_match(b)
    if len(ta) >= 2 and len(tb) >= 2:
        inter = ta & tb
        union = ta | tb
        if union and (len(inter) / len(union)) >= 0.66:
            return True

    # Drop parenthetical and punctuation; if the residue matches, cluster.
    def _strip(v: str) -> str:
        v = re.sub(r"\([^)]*\)", " ", v)
        v = re.sub(r"[^\w\s]", " ", v).lower()
        return re.sub(r"\s+", " ", v).strip()
    if _strip(a) == _strip(b) and _strip(a):
        return True

    return False


@dataclass
class ValueRow:
    """One raw value + its product count, post-auto-canonical bucketing."""
    raw_values: list[str] = field(default_factory=list)
    canonical: str = ""
    count: int = 0
    uom: str | None = None
    _lead_count: int = 0  # internal — count of the row supplying current uom


@dataclass
class Cluster:
    """A suggested-merge cluster — multiple ValueRows that look like the
    same physical attribute."""
    canonical: str
    members: list[ValueRow]
    total_count: int


def suggest_clusters(rows: list[ValueRow]) -> tuple[list[Cluster], list[ValueRow]]:
    """Group post-auto rows into suggested-merge clusters.

    Returns (clusters, long_tail).  `clusters` is sorted by total_count
    descending (highest-impact merges first); `long_tail` is the rows
    that didn't pair with anything.

    Single-row "clusters" do NOT become clusters — they go straight to
    long_tail so the curator only sees something requiring action.
    """
    if len(rows) < 2:
        return [], list(rows)

    # Union-find over indices
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    # O(n²) pairwise compare — fine for n ≤ a few hundred values per key
    n = len(rows)
    for i in range(n):
        for j in range(i + 1, n):
            if _similar_enough(rows[i].canonical, rows[j].canonical):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    clusters: list[Cluster] = []
    long_tail: list[ValueRow] = []
    for idxs in groups.values():
        members = [rows[i] for i in idxs]
        if len(members) == 1:
            long_tail.append(members[0])
            continue
        # Within-cluster canonical = the highest-count row's canonical.
        # Owner ask: canonical label is always Title Case — that's already
        # true for every member because they came through auto_canonical.
        members.sort(key=lambda m: m.count, reverse=True)
        clusters.append(Cluster(
            canonical=members[0].canonical,
            members=members,
            total_count=sum(m.count for m in members),
        ))

    clusters.sort(key=lambda c: c.total_count, reverse=True)
    long_tail.sort(key=lambda m: m.count, reverse=True)
    return clusters, long_tail


def bucket_by_canonical(
    raw_value_counts: Iterable[tuple[str, str | None, int]],
    manual_aliases: dict[str, str] | None = None,
) -> list[ValueRow]:
    """Fold a stream of (raw_value, uom, count) tuples into ValueRows
    keyed on canonical_value.

    `manual_aliases` is the (raw → canonical) override map from
    `attribute_value_alias`; raws not in it fall back to auto_canonical().

    The bucket's `uom` comes from whichever member contributed the most
    products (most representative UOM for the merged group)."""
    manual_aliases = manual_aliases or {}
    by_canonical: dict[str, ValueRow] = {}
    for raw, uom, count in raw_value_counts:
        if raw is None:
            continue
        if raw in manual_aliases:
            canonical = manual_aliases[raw]
        else:
            canonical = auto_canonical(raw)
        if not canonical:
            continue
        n = int(count)
        row = by_canonical.get(canonical)
        if row is None:
            by_canonical[canonical] = ValueRow(
                raw_values=[raw],
                canonical=canonical,
                count=n,
                uom=uom or None,
                _lead_count=n,
            )
        else:
            row.raw_values.append(raw)
            row.count += n
            if n > row._lead_count and uom:
                row.uom = uom
                row._lead_count = n
    return sorted(by_canonical.values(), key=lambda r: r.count, reverse=True)
