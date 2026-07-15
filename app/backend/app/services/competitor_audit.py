"""Competitive landscape data — Titan vs local + national competitors.

Phase 1 hand-curated audit data drives the /insights/competitive scoreboard.
Phase 1.5 will replace the static scores with automated Lighthouse / crawl
metrics, plus an admin editor for the qualitative notes.

Score model:
  Each dimension is rated 1-10 (10 = best-in-class).  Stored alongside a
  one-line note + the date the audit was performed.  When we re-audit, the
  date stamp updates and the previous score is archived (Phase 1.5 work —
  for now we just overwrite).

Tier classification:
  - "us"            our site under development (titantruck.com new)
  - "local"         Pacific NW direct competitors
  - "national"      US-wide truck/plow ecommerce
  - "snow_specialist"  pure-play snow plow retailers
  - "manufacturer"  brand-direct sites (compete via product info, not sale)
  - "reference"     PACE/AAM mockup we benchmarked against
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


CompetitorTier = Literal["us", "local", "national", "snow_specialist", "manufacturer", "reference"]


# Dimensions we score on.  Order = display order in the UI matrix.
SCORE_DIMENSIONS: list[tuple[str, str, str]] = [
    # (key, label, what we mean by it)
    ("seo",            "SEO foundations",       "Schema.org markup, sitemap, meta tags, canonical URLs, page titles"),
    ("page_speed",     "Page speed",            "Lighthouse mobile + desktop performance scores"),
    ("mobile",         "Mobile UX",             "Touch-friendly nav, responsive layout, mobile cart"),
    ("catalog",        "Catalog breadth",       "Product count, brand coverage, image coverage"),
    ("search",         "Search quality",        "Autocomplete, fuzzy match, facets, relevance"),
    ("pdp",            "PDP richness",          "Multi-image gallery, specs, fitment, reviews, videos"),
    ("ymm",            "Vehicle fitment (YMM)", "Year/Make/Model selector + fitment-aware filtering"),
    ("b2b",            "B2B features",          "Tier pricing, account, quote builder, Front Counter mode"),
    ("snow",           "Snow plow specialization","Brand-specific landing, comparison, buying guide, install"),
    ("trust",          "Trust signals",         "Phone, hours, locations, reviews, BBB, service info"),
    ("checkout",       "Checkout flow",         "Steps to purchase, transparency, freight, tax estimation"),
    ("content",        "Education / content",   "Buying guides, install videos, blog, FAQ"),
    ("design",         "Visual polish",         "Hero treatment, brand consistency, image quality, typography"),
    ("compare",        "Compare / configure",   "Side-by-side tools, product selectors, configurators"),
]


@dataclass
class Score:
    value: int          # 1-10
    note: str = ""      # one-line justification


@dataclass
class Competitor:
    id: str             # url-safe slug
    name: str           # display name
    url: str            # primary URL
    tier: CompetitorTier
    region: str = ""    # e.g. "Pacific NW", "Nationwide", "Manufacturer"
    summary: str = ""   # one paragraph positioning
    last_audited: str = "2026-04-26"
    scores: dict[str, Score] = field(default_factory=dict)


def _S(v: int, note: str = "") -> Score:
    return Score(value=v, note=note)


# ===========================================================================
# CATALOG
# ===========================================================================
#
# Scoring scale (for context):
#   10  best-in-class — sets the bar
#   8-9 strong, professional execution
#   6-7 functional, room to improve
#   4-5 dated or thin
#   1-3 broken, missing, or actively bad
#
# The "us" entry reflects what we've actually built into the new
# titantruck.com (this rebuild) — not the legacy WSM site at the production
# URL.  It updates as we ship.

COMPETITORS: list[Competitor] = [
    # ===================================================================
    # US (the new Titan website — auto-updates as we build)
    # ===================================================================
    Competitor(
        id="titan-new", name="Titan Truck Equipment (new build)",
        url="https://titantruck.com (this rebuild)", tier="us",
        region="Pacific NW", last_audited="2026-04-26",
        summary="Site under construction.  IMPORTANT: these scores are SELF-ASSESSED based on what's been built — not validated by user testing, sales attribution, ranking data, or third-party Lighthouse runs yet.  Treat them as aspirational floors, not earned numbers.  Phase 1.5 will replace these with measured data.",
        scores={
            "seo":        _S(6, "Basic meta tags + structured layout; no Schema.org product markup yet"),
            "page_speed": _S(8, "Vite + React, Tailwind, Typesense — sub-100ms search, fast PDPs"),
            "mobile":     _S(7, "Tailwind responsive defaults; mega menu needs mobile pass"),
            "catalog":    _S(9, "221K products, 131 brands, 48K images imported from WSM"),
            "search":     _S(9, "Typesense autocomplete with parts/categories/brands 3-col + facets + sub-100ms"),
            "pdp":        _S(8, "Multi-image gallery, tier pricing, warehouse stock table, specs/fitment tabs, lost-sale + price-match modals"),
            "ymm":        _S(5, "YMM selector ships + persists; fitment data import lands Phase 1.5"),
            "b2b":        _S(9, "Tier-aware pricing, contract resolution, Front Counter Mode, account linking, reorder"),
            "snow":       _S(8, "Dedicated /snow-plows landing + 17-model comparison builder + buying guide tabs"),
            "trust":      _S(8, "3 phone numbers + locations + family-since-1971 + price-match"),
            "checkout":   _S(7, "Multi-warehouse split, IMS315 push, freight + WA tax wired; Authorize.Net pending creds"),
            "content":    _S(6, "Snow buying guide + FAQ in place; full blog/video lib coming"),
            "design":     _S(8, "Dark hero + 3-column landing + mega menu modeled on PACE"),
            "compare":    _S(9, "Snow plow comparison builder is best-in-class for the space"),
        },
    ),

    # ===================================================================
    # LOCAL — Pacific NW direct competitors
    # ===================================================================
    Competitor(
        id="titan-legacy", name="Titan Truck Equipment (current production)",
        url="https://www.titantruck.com", tier="local",
        region="Pacific NW", last_audited="2026-04-26",
        summary="Current production site — Web Shop Manager template, ~50K products, dated UX.  This is what we're replacing.",
        scores={
            "seo":        _S(6, "Decent meta tags; old-school WSM markup"),
            "page_speed": _S(5, "WSM-hosted, slower JS; render-blocking scripts"),
            "mobile":     _S(5, "Responsive but cramped; mega menus break on touch"),
            "catalog":    _S(8, "Full Titan WSM catalog — solid breadth"),
            "search":     _S(5, "Basic keyword search, no autocomplete dropdown"),
            "pdp":        _S(6, "Single image, basic specs, no fitment, no reviews"),
            "ymm":        _S(3, "WSM YMM exists but rarely populated for fitment"),
            "b2b":        _S(4, "Login + dealer locator; no tier pricing visible"),
            "snow":       _S(5, "Has Snow & Ice Control category page with 7 sub-cats and 3 brand tiles — basic"),
            "trust":      _S(7, "Phone numbers + 3 locations + dealer locator"),
            "checkout":   _S(5, "Standard WSM cart, no transparency on freight/tax until end"),
            "content":    _S(3, "No buying guides, no blog content"),
            "design":     _S(4, "Dated WSM theme, generic banner imagery"),
            "compare":    _S(2, "No comparison tool"),
        },
    ),
    Competitor(
        id="nelson-legacy", name="Nelson Truck Equipment",
        url="https://www.nelsontruck.com", tier="local",
        region="Pacific NW", last_audited="2026-04-26",
        summary="Local competitor, similar product mix.  Hosts our image archive (we cross-link until we self-host).",
        scores={
            "seo":        _S(5, "Old WSM site, basic meta only"),
            "page_speed": _S(4, "WSM template + lots of legacy assets"),
            "mobile":     _S(4, "Functional but cramped"),
            "catalog":    _S(7, "Comparable WSM catalog"),
            "search":     _S(4, "Keyword box; no autocomplete"),
            "pdp":        _S(5, "Image + basic info; minimal specs"),
            "ymm":        _S(3, "Limited fitment integration"),
            "b2b":        _S(3, "No tier pricing surfaced; basic login"),
            "snow":       _S(4, "Basic snow category"),
            "trust":      _S(6, "Locations + phone visible"),
            "checkout":   _S(4, "Standard WSM"),
            "content":    _S(3, "No content marketing visible"),
            "design":     _S(3, "Dated"),
            "compare":    _S(1, "No comparison"),
        },
    ),

    # ===================================================================
    # NATIONAL — US-wide truck equipment ecommerce
    # ===================================================================
    Competitor(
        id="elitetruck", name="Elite Truck",
        url="https://elitetruck.com", tier="national",
        region="Nationwide (Shopify)", last_audited="2026-04-26",
        summary="Polished Shopify storefront.  14-tile featured grid, brand-deal section, business-account CTA, blog.  Strong B2B narrative.",
        scores={
            "seo":        _S(8, "Shopify defaults + good schema markup"),
            "page_speed": _S(7, "Shopify CDN; fast PDPs but heavy collections"),
            "mobile":     _S(8, "Shopify responsive themes are excellent"),
            "catalog":    _S(7, "Curated truck/van categories; smaller than ours"),
            "search":     _S(7, "Shopify search + filters; no live autocomplete"),
            "pdp":        _S(8, "Good imagery, descriptions, related products"),
            "ymm":        _S(5, "Some fitment in PDPs; no global YMM"),
            "b2b":        _S(8, "'Create a Business Account' CTA + dedicated narrative"),
            "snow":       _S(4, "General mention only; not a focus"),
            "trust":      _S(8, "Phone, 'Elite Promise' guarantee, blog content"),
            "checkout":   _S(8, "Shopify checkout — smooth"),
            "content":    _S(7, "Active blog with real articles"),
            "design":     _S(9, "Clean, professional, high-quality photography"),
            "compare":    _S(3, "No compare tool"),
        },
    ),
    Competitor(
        id="snowplowsplus", name="SnowplowsPlus",
        url="https://snowplowsplus.com", tier="snow_specialist",
        region="Nationwide", last_audited="2026-04-26",
        summary="Pure-play snow plow + parts ecommerce.  'Largest variety of Western, Boss, SnowDogg parts'.  Older WordPress design.",
        scores={
            "seo":        _S(6, "Decent product pages; thin meta"),
            "page_speed": _S(5, "WordPress + WooCommerce defaults"),
            "mobile":     _S(5, "Workable but dated"),
            "catalog":    _S(6, "Strong on parts; smaller on whole plows"),
            "search":     _S(6, "WooCommerce search"),
            "pdp":        _S(6, "Standard WooCommerce PDP"),
            "ymm":        _S(4, "No real YMM"),
            "b2b":        _S(4, "Basic account, no tier pricing"),
            "snow":       _S(8, "Pure snow focus, deep parts catalog"),
            "trust":      _S(6, "Phone + live chat"),
            "checkout":   _S(6, "WooCommerce defaults"),
            "content":    _S(5, "Some basic guides"),
            "design":     _S(4, "Dated"),
            "compare":    _S(2, "No tool"),
        },
    ),
    Competitor(
        id="storksplows", name="Storks Plows",
        url="https://storksplows.com", tier="snow_specialist",
        region="Nationwide", last_audited="2026-04-26",
        summary="Whole snow plow retailer specializing in Western MVP3 / Pro-Plus + Boss + SnowDogg + Meyer.  Strong product photography.",
        scores={
            "seo":        _S(7, "Good product detail pages"),
            "page_speed": _S(6, "Reasonable"),
            "mobile":     _S(6, "OK but not native"),
            "catalog":    _S(7, "Whole-plow focused — smaller than parts shops"),
            "search":     _S(5, "Basic"),
            "pdp":        _S(8, "Excellent product photography + spec sheets"),
            "ymm":        _S(3, "No YMM"),
            "b2b":        _S(3, "Basic"),
            "snow":       _S(9, "Pure whole-plow focus + brand expertise"),
            "trust":      _S(7, "Active dealer + phone"),
            "checkout":   _S(6, "Standard"),
            "content":    _S(6, "Some buying advice"),
            "design":     _S(7, "Cleaner than SPP"),
            "compare":    _S(2, "No tool"),
        },
    ),
    Competitor(
        id="legacyplow", name="Legacy Plow & Trailer",
        url="https://legacyplowandtrailer.com", tier="snow_specialist",
        region="Nationwide (Midwest)", last_audited="2026-04-26",
        summary="Carries Western, Meyer, SnowEx, Boss, SnowDogg + trailers.  Multi-brand snow + trailer combo store.",
        scores={
            "seo":        _S(6, ""),
            "page_speed": _S(6, ""),
            "mobile":     _S(6, ""),
            "catalog":    _S(7, "Solid whole-plow + trailer combo"),
            "search":     _S(5, ""),
            "pdp":        _S(7, "Good photos"),
            "ymm":        _S(3, ""),
            "b2b":        _S(4, ""),
            "snow":       _S(8, "Strong snow inventory"),
            "trust":      _S(7, "Phone + showroom"),
            "checkout":   _S(6, ""),
            "content":    _S(5, ""),
            "design":     _S(6, ""),
            "compare":    _S(2, ""),
        },
    ),

    Competitor(
        id="snowplowsdirect", name="Snow Plows Direct",
        url="https://snowplowsdirect.com", tier="snow_specialist",
        region="Nationwide (Illinois HQ)", last_audited="2026-04-26",
        summary="Pure-play snow plow ecommerce.  Strong customer-service positioning: $1 price-match guarantee, free shipping, 12-month price protection, US-based product experts.  'Shop by Vehicle' YMM at top of nav.  Personal + Professional + ATV/UTV segmentation.",
        scores={
            "seo":        _S(6, "Standard schema; product pages indexable"),
            "page_speed": _S(6, "OK but legacy framework"),
            "mobile":     _S(6, "Responsive but cramped"),
            "catalog":    _S(6, "Snow + spreaders + ATV, no parts depth"),
            "search":     _S(5, "Basic search box"),
            "pdp":        _S(6, "Standard product pages"),
            "ymm":        _S(7, "'Shop by Vehicle' actually works for fitment"),
            "b2b":        _S(4, "Dual residential/commercial; no tier pricing"),
            "snow":       _S(8, "Pure snow focus"),
            "trust":      _S(9, "Best-in-class price guarantee + 12mo protection + live chat"),
            "checkout":   _S(7, "Free ship + financing CTA"),
            "content":    _S(5, "Light 'Knowledge Center'"),
            "design":     _S(6, "Functional but dated"),
            "compare":    _S(3, "No compare tool"),
        },
    ),
    Competitor(
        id="newhydraulics", name="NEW Hydraulics",
        url="https://newhydraulics.com", tier="snow_specialist",
        region="Nationwide (custom hydraulics)", last_audited="2026-04-26",
        summary="Hybrid hydraulic-services + snow equipment shop.  Custom hose assemblies, tube bending, fabrication PLUS Western/Fisher/SnowEx snow gear.  Strong service-shop positioning ('The Art of Uptime™' tagline) targeting fleet operators across ag/construction/landscape/municipal.",
        scores={
            "seo":        _S(6, ""),
            "page_speed": _S(7, ""),
            "mobile":     _S(7, ""),
            "catalog":    _S(5, "Limited online catalog vs full service shop"),
            "search":     _S(5, ""),
            "pdp":        _S(5, "Service-focused, less product detail"),
            "ymm":        _S(3, "No YMM"),
            "b2b":        _S(7, "Industry-focused, service contracts, 24/7 emergency"),
            "snow":       _S(6, "Western + Fisher + SnowEx but parts-light"),
            "trust":      _S(8, "24/7 emergency support, multi-industry"),
            "checkout":   _S(5, "Quote-driven, less ecommerce"),
            "content":    _S(6, "Industries-served pages"),
            "design":     _S(7, "Clean, professional"),
            "compare":    _S(3, "No compare"),
        },
    ),
    Competitor(
        id="trailersuperstore", name="All Pro Trailer Superstore",
        url="https://trailersuperstore.com", tier="national",
        region="Pennsylvania (nationwide delivery)", last_audited="2026-04-26",
        summary="Family-owned since 1988, Mechanicsburg PA.  1000+ trailers + snow plows + salt spreaders.  SnowDogg primary plow brand.  Standout: on-the-spot financing + accredited PA dealer with title/tag department.",
        scores={
            "seo":        _S(7, "Strong category structure"),
            "page_speed": _S(6, ""),
            "mobile":     _S(6, ""),
            "catalog":    _S(7, "1000+ items spread across trailers + plows + spreaders"),
            "search":     _S(6, "Filter by trailer type"),
            "pdp":        _S(7, "Good photos, financing per item"),
            "ymm":        _S(4, "Trailer fitment less critical"),
            "b2b":        _S(6, "Some commercial focus"),
            "snow":       _S(7, "SnowDogg lineup"),
            "trust":      _S(9, "Since 1988 + family-owned + accredited dealer + on-the-spot finance"),
            "checkout":   _S(8, "On-the-spot financing is the differentiator"),
            "content":    _S(6, ""),
            "design":     _S(6, ""),
            "compare":    _S(3, ""),
        },
    ),
    Competitor(
        id="qte", name="Quality Truck & Equipment (QTE)",
        url="https://www.4qte.com", tier="snow_specialist",
        region="Illinois (nationwide / worldwide ship)", last_audited="2026-04-26",
        summary="Founded 1967.  Self-described 'one of the largest snowplow distributors in the country'.  Carries Western + Fisher + SnowEx + plow parts for every make.  Strong national reach with worldwide shipping.  Direct competitor for whole-plow + parts.",
        scores={
            "seo":        _S(7, "Deep product page coverage"),
            "page_speed": _S(5, "Older PHP-style site"),
            "mobile":     _S(5, "Functional, dated"),
            "catalog":    _S(8, "Deep parts coverage across all major brands"),
            "search":     _S(6, "Standard"),
            "pdp":        _S(7, "Good spec pages"),
            "ymm":        _S(5, ""),
            "b2b":        _S(7, "Competitive finance programs"),
            "snow":       _S(9, "Among the largest US distributors"),
            "trust":      _S(9, "Founded 1967, established reputation"),
            "checkout":   _S(6, ""),
            "content":    _S(7, "Brand-by-brand educational pages"),
            "design":     _S(5, "Older design language"),
            "compare":    _S(4, "Basic spec sheets per model"),
        },
    ),
    Competitor(
        id="zequip", name="Zequip Equipment Superstore",
        url="https://www.zequip.com", tier="national",
        region="Nationwide", last_audited="2026-04-26",
        summary="(User typed 'zeuip.com' — actual site is zequip.com.)  Multi-vertical truck-equipment marketplace: towing, hydraulics, snow/ice control, liftgates, PTO, dump beds, salt spreaders.  Brand mix: Fisher, Western, Towmate, B/A Products, Buyers, Muncie Power.  Closest peer to Titan's product breadth.",
        scores={
            "seo":        _S(7, "Solid category structure"),
            "page_speed": _S(6, ""),
            "mobile":     _S(6, ""),
            "catalog":    _S(8, "Multi-vertical breadth (tow/plow/hydraulic/PTO/liftgate)"),
            "search":     _S(6, ""),
            "pdp":        _S(6, ""),
            "ymm":        _S(4, "Limited fitment"),
            "b2b":        _S(7, "Strong B2B / commercial focus"),
            "snow":       _S(7, "Parts-focused, full brand coverage"),
            "trust":      _S(7, "Customer service emphasized"),
            "checkout":   _S(6, ""),
            "content":    _S(5, ""),
            "design":     _S(6, ""),
            "compare":    _S(3, ""),
        },
    ),

    # ===================================================================
    # MANUFACTURER (brand-direct, compete on info not sale)
    # ===================================================================
    Competitor(
        id="bossplow", name="BOSS Snowplow",
        url="https://bossplow.com", tier="manufacturer",
        region="Manufacturer (USA)", last_audited="2026-04-26",
        summary="Manufacturer site.  Best-in-class product taxonomy, Product Selector wizard, Where-To-Buy + Financing widgets.",
        scores={
            "seo":        _S(9, "Strong product/category structure"),
            "page_speed": _S(7, "Image-heavy hero carousels"),
            "mobile":     _S(8, "Good responsive design"),
            "catalog":    _S(7, "Their lineup only"),
            "search":     _S(6, "Internal search"),
            "pdp":        _S(9, "Beautiful product pages with specs + videos"),
            "ymm":        _S(5, "No global YMM (manufacturer model)"),
            "b2b":        _S(5, "Owner Group portal"),
            "snow":       _S(10, "It's their entire business"),
            "trust":      _S(9, "Manufacturer authority + dealer network"),
            "checkout":   _S(0, "No checkout — funnel to dealer"),
            "content":    _S(9, "Tech videos, training, manuals portal"),
            "design":     _S(9, "Premium brand visuals"),
            "compare":    _S(7, "Product Selector wizard + Sidewalk Builder"),
        },
    ),
    Competitor(
        id="westernplows", name="Western Plows",
        url="https://westernplows.com", tier="manufacturer",
        region="Manufacturer (USA)", last_audited="2026-04-26",
        summary="Our #1 snow brand's manufacturer site.  Quick Match Wizard for fitment + 'Compare Products' link in footer.",
        scores={
            "seo":        _S(9, ""),
            "page_speed": _S(7, ""),
            "mobile":     _S(8, ""),
            "catalog":    _S(7, ""),
            "search":     _S(7, "Quick Match Wizard"),
            "pdp":        _S(8, ""),
            "ymm":        _S(7, "Quick Match is real fitment"),
            "b2b":        _S(4, ""),
            "snow":       _S(10, "Their entire business"),
            "trust":      _S(9, ""),
            "checkout":   _S(0, "Dealer-direct"),
            "content":    _S(8, ""),
            "design":     _S(9, ""),
            "compare":    _S(6, "Has compare link in footer"),
        },
    ),
    Competitor(
        id="meyerproducts", name="Meyer Products",
        url="https://meyerproducts.com", tier="manufacturer",
        region="Manufacturer (USA)", last_audited="2026-04-26",
        summary="Meyer's manufacturer site.  Strong on residential plow segment (Home Plow).",
        scores={
            "seo":        _S(8, ""),
            "page_speed": _S(7, ""),
            "mobile":     _S(7, ""),
            "catalog":    _S(7, "Their lineup"),
            "search":     _S(6, ""),
            "pdp":        _S(8, ""),
            "ymm":        _S(5, ""),
            "b2b":        _S(4, ""),
            "snow":       _S(9, "Their entire business"),
            "trust":      _S(8, ""),
            "checkout":   _S(0, "Dealer-direct"),
            "content":    _S(7, ""),
            "design":     _S(7, ""),
            "compare":    _S(4, ""),
        },
    ),

    # ===================================================================
    # REFERENCE (the design we benchmarked against)
    # ===================================================================
    Competitor(
        id="pace-titan", name="PACE Demo (Titan template)",
        url="https://titan.pacesystems.com/home", tier="reference",
        region="Reference / mockup", last_audited="2026-04-26",
        summary="The PACE/AAM mockup our home page mirrors.  Strong nav (YMM, Engine Family, Brands, Categories), 3-col home, Quick Order, autocomplete, admin panel.",
        scores={
            "seo":        _S(7, ""),
            "page_speed": _S(6, ""),
            "mobile":     _S(6, ""),
            "catalog":    _S(8, "AAM Pro catalog access"),
            "search":     _S(9, "3-col autocomplete dropdown — best in class"),
            "pdp":        _S(8, "Locations breakdown, Lost Sale + Price Match buttons"),
            "ymm":        _S(8, "Year/Make/Model + Engine Family selectors"),
            "b2b":        _S(10, "Account dashboard, View-As-Account, Order History, Backorders, Pre-Rebates"),
            "snow":       _S(5, "Generic equipment focus"),
            "trust":      _S(7, ""),
            "checkout":   _S(9, "Submit Purchase Order with Shipment Type, prepaid freight callout"),
            "content":    _S(6, "Program Blog area"),
            "design":     _S(7, "Dense info-rich layout"),
            "compare":    _S(4, "No real compare tool"),
        },
    ),
]


def list_competitors(tier: str | None = None) -> list[Competitor]:
    if tier:
        return [c for c in COMPETITORS if c.tier == tier]
    return list(COMPETITORS)


def get_competitor(slug: str) -> Competitor | None:
    return next((c for c in COMPETITORS if c.id == slug), None)


def competitor_to_dict(c: Competitor) -> dict:
    d = asdict(c)
    return d


def get_dimensions() -> list[dict]:
    return [{"key": k, "label": l, "description": desc} for k, l, desc in SCORE_DIMENSIONS]


def average_score(c: Competitor) -> float:
    if not c.scores: return 0
    vals = [s.value for s in c.scores.values() if s.value > 0]
    return round(sum(vals) / len(vals), 1) if vals else 0
