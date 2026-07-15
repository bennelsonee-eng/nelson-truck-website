"""Curated whitelist of CONFIRMED-CLEAN plow reference images for FLUX Kontext.

User clarified: only feed Kontext "good floating images" (plow alone, no truck
in the background).  Some of our 61 transparent extracts are still
truck-contaminated where the white-mask extraction left the truck pixels
behind the plow body.

Known contaminated (DO NOT USE as references):
  - MYP-09446-EQP, MYP-09447-EQP            (Meyer Super-V2 8'6" / 9'6")
  - MYP-09494-EQP, MYP-09495-EQP            (Meyer Super-V2 SS 8'6" / 9'6")
  - MYP-84350/84351/84352/84353-EQP         (Meyer Diamond Edge family)

Confirmed clean (visually verified or high transparency-ratio + clean borders):
  - All Western Pro Plus / Defender / MVP3 / Enforcer / HTS
  - All SnowDogg HD/MD/CM/XP/TE/VMD/VXF (some are tight crops but still clean)
  - Meyer Drive Pro / Lot Pro / Road Pro / Super-V Light Duty

Use `is_clean_plow_reference(sku)` to gate which SKUs are safe to feed
Kontext as image references.  Anything not on the whitelist falls back to
text-prompt-only Kontext.
"""

from __future__ import annotations


# SKUs CONFIRMED to have truck still behind plow in the "transparent" extract,
# OR vendor watermarks/stamps overlaid, OR lifestyle scenes instead of
# clean studio shots.  These cannot be used as Kontext references — the
# model would render another truck, copy a watermark, or get scrambled.
KNOWN_CONTAMINATED: set[str] = {
    # Meyer Super-V2 family — gray Ram pickup behind plow
    "MYP-09446-EQP",
    "MYP-09447-EQP",
    "MYP-09494-EQP",
    "MYP-09495-EQP",
    # Meyer Diamond Edge family — dark truck behind plow
    "MYP-84350-EQP",
    "MYP-84351-EQP",
    "MYP-84352-EQP",
    "MYP-84353-EQP",
    # Meyer Super-V LD — Chevy pickup behind plow
    "MYP-09329-EQP",
    # Western Defender family — Tacoma in background, snow scene
    "WEST-DEF68-EQP",
    "WEST-DEF72-EQP",
    # Western Pro Plow S2 — silver truck behind plow
    "WEST-PPS2MS76-EQP",
    "WEST-PPS2MS8-EQP",
    "WEST-PPS2MS86-EQP",
    "WEST-PPS2PLY76-EQP",
    "WEST-PPS2PLY8-EQP",
    "WEST-PPS2PLY86-EQP",
    # SnowDogg lifestyle / truck-attached / watermarked shots
    "SNOW-16020522-EQP",  # HD75II — vendor "We Call You" watermarks
    "SNOW-16020712-EQP",  # VMD75II — lifestyle snow-plowing scene with truck
    "SNOW-16020820-EQP",  # CM100 — F-450 dump truck behind plow + watermarks
}


# SKUs that don't have hero_transparent.png at all (only hero.jpg lifestyle shot).
# These also can't be used as Kontext references for the same reason.
NO_TRANSPARENT_AVAILABLE: set[str] = {
    "MYP-09338-EQP",      # 8' Road Pro 32 — lifestyle shot
    "MYP-09454-EQP",      # 9' Road Pro 32
    "MYP-09455-EQP",      # 10' Road Pro 32
    "MYP-09478-EQP",      # Lot Pro variant
    "MYP-SV386-EQP",      # 8'6" Super-V3
    "MYP-SV386SS-EQP",    # 8'6" Super-V3 SS
    "MYP-SV396-EQP",      # 9'6" Super-V3
    "MYP-SV396SS-EQP",    # 9'6" Super-V3 SS
}


def is_clean_plow_reference(sku: str) -> bool:
    """True if the SKU's hero_transparent.png is safe to use as a Kontext
    reference image (clean plow-only, no truck behind it)."""
    return sku not in KNOWN_CONTAMINATED and sku not in NO_TRANSPARENT_AVAILABLE


def reference_sku_or_fallback(sku: str, fallback: str = "WEST-MVP3MS86-EQP") -> str:
    """Returns the SKU itself if clean, else a known-clean substitute.

    The fallback default is the Western MVP3 MS 8'6" — confirmed-clean V-plow
    used as our locked baseline for all the v5 composite work.
    """
    return sku if is_clean_plow_reference(sku) else fallback
