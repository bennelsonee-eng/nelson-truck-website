"""Truck-class-driven plow recommender — powers the Find My Plow wizard.

User insight that shaped the design: the only vehicle-specific parts on a
plow build are the mount and the light adapter.  Everything else is generic
and selected by truck *class*, not specific YMM.  So the recommender is
class-driven, not VIN-driven.

Common-sense rules from Titan's sales floor:
  - Don't put a huge plow on a small truck (Ranger can't carry a Wide-Out)
  - Don't put a small plow on a big truck (F-550 needs commercial weight)
  - Match plow weight to FAWR (front axle weight rating) headroom
  - Match blade type to route mix:
      driveways/residential        → straight blade, smaller, simpler
      mixed commercial             → straight blade or V-plow
      open commercial lots         → winged blade scoops the most
      municipal/heavy duty         → heaviest V-plow or winged
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from app.services.snow_plow_catalog import CATALOG, PlowModel


TruckClass = Literal["mid-size", "1500", "2500", "3500", "4500", "5500"]
RouteType = Literal["residential", "mixed_commercial", "lots", "municipal"]
BudgetBucket = Literal["under_5k", "5k_8k", "8k_12k", "over_12k", "any"]


# Map our 6 truck-class buckets to the catalog's truck_classes strings.
TRUCK_CLASS_TO_CATALOG: dict[str, list[str]] = {
    "mid-size": ["mid-size"],
    "1500":     ["1500"],
    "2500":     ["2500"],
    "3500":     ["3500"],
    "4500":     ["4500"],
    "5500":     ["5500"],
}


# Recommended plow families per route type.  We give a primary + secondary
# so the recommender can fall through if the primary has no matches.
ROUTE_TO_FAMILY: dict[str, list[str]] = {
    "residential":     ["straight_blade"],
    "mixed_commercial": ["straight_blade", "v_plow"],
    "lots":            ["winged", "v_plow"],
    "municipal":       ["v_plow", "winged"],
}


BUDGET_BUCKETS: dict[str, tuple[int, int]] = {
    "under_5k":  (0,    5_000),
    "5k_8k":     (4_500, 8_500),
    "8k_12k":    (7_500, 12_500),
    "over_12k":  (10_000, 999_999),
    "any":       (0, 999_999),
}


# Friendly display labels — the raw bucket numbers overlap on purpose so the
# matcher catches near-misses, but humans want the clean range they picked.
BUDGET_LABEL: dict[str, str] = {
    "under_5k": "under $5K",
    "5k_8k":    "$5K–$8K",
    "8k_12k":   "$8K–$12K",
    "over_12k": "$12K+",
    "any":      "any price",
}


@dataclass
class PlowMatch:
    plow: PlowModel
    score: float
    reasoning: list[str]
    direct_fit: bool = False        # True iff target truck class is in model.truck_classes
    fit_warning: str | None = None  # plain-English caveat for stretch picks


# Adjacency map — used both to widen the candidate pool AND to render the
# warning text on stretch picks.  Keep in one place so they don't drift.
NEIGHBORS: dict[str, list[str]] = {
    "mid-size": ["1500"],
    "1500":     ["mid-size", "2500"],
    "2500":     ["1500", "3500"],
    "3500":     ["2500", "4500"],
    "4500":     ["3500", "5500"],
    "5500":     ["4500"],
}


def _model_truck_classes_match(model: PlowModel, target: str) -> bool:
    """A plow is suitable for a truck class if either its class list contains
    the target OR the target is one step away (small overrun is OK)."""
    if target in model.truck_classes:
        return True
    return any(n in model.truck_classes for n in NEIGHBORS.get(target, []))


# Friendly truck-class display labels — the catalog uses raw class IDs but
# the UI / warning copy wants plain English.
TRUCK_CLASS_LABEL: dict[str, str] = {
    "mid-size": "mid-size pickups",
    "1500":     "half-tons (F-150 / 1500)",
    "2500":     "3/4-tons (F-250 / 2500)",
    "3500":     "1-tons (F-350 / 3500)",
    "4500":     "Class 4 chassis cabs",
    "5500":     "Class 5 chassis cabs",
}

FAMILY_LABEL: dict[str, str] = {
    "straight_blade": "straight blade",
    "v_plow":         "V-plow",
    "winged":         "winged blade",
}


@dataclass
class RecommendResult:
    """Wraps the matches plus a route-level warning when the chosen route's
    preferred family doesn't fit the truck class — e.g. half-ton + winged."""
    matches: list[PlowMatch]
    truck_class_warning: str | None = None
    suggested_step_up: str | None = None


def _score_one(
    model: PlowModel,
    *,
    truck_class: str,
    target_classes: list[str],
    preferred_families: list[str],
    budget: str,
    budget_low: int,
    budget_high: int,
) -> PlowMatch | None:
    """Score a single model against the buyer's selection.  Returns None if
    the model is the wrong family for this route type."""
    score = 0.0
    reasoning: list[str] = []

    # Score on truck class match (+10 exact, +5 neighbor)
    direct_fit = any(c in model.truck_classes for c in target_classes)
    fit_warning: str | None = None
    if direct_fit:
        score += 10
        reasoning.append(f"Sized for {truck_class} trucks")
    else:
        score += 5
        # Find the closest neighbor that the model DOES fit, so the warning
        # can be specific.
        oversize = any(n in model.truck_classes for n in NEIGHBORS.get(truck_class, []))
        if oversize:
            classes_listed = "/".join(model.truck_classes)
            reasoning.append(f"Stretch fit — built for {classes_listed}, not {truck_class}")
            fit_warning = (
                f"This plow is sized for {classes_listed}.  Putting it on a "
                f"{truck_class} will overload the front axle and void the warranty.  "
                f"Consider stepping up to a heavier truck class."
            )

    # Family match
    if model.family == preferred_families[0]:
        score += 10
        reasoning.append(f"{model.family_label} — best blade type for this route")
    elif len(preferred_families) > 1 and model.family == preferred_families[1]:
        score += 5
        reasoning.append(f"{model.family_label} — also works well on this route")
    else:
        return None  # wrong family — skip

    # Budget overlap
    in_budget = budget == "any" or (model.msrp_low <= budget_high and model.msrp_high >= budget_low)
    if in_budget:
        score += 5
        if budget != "any":
            reasoning.append(f"In your {BUDGET_LABEL[budget]} budget range")
    else:
        score -= 5
        if model.msrp_low > budget_high:
            reasoning.append(f"Above budget (${model.msrp_low:,}+)")
        else:
            reasoning.append(f"Below budget (${model.msrp_high:,} max)")

    # Popularity boost
    if model.snow_belt_rank == 1:
        score += 3
        reasoning.append("Top-tier popularity in our market")
    elif model.snow_belt_rank == 2:
        score += 2

    return PlowMatch(
        plow=model,
        score=score,
        reasoning=reasoning,
        direct_fit=direct_fit,
        fit_warning=fit_warning,
    )


def _has_direct_family_fit(truck_class: str, family: str) -> bool:
    """Does any catalog model exist for this (truck_class, family) combo?
    Used to detect 'half-ton + winged' style impossible asks before we hide
    the gap behind silent neighbor fallbacks."""
    return any(
        truck_class in m.truck_classes and m.family == family
        for m in CATALOG
    )


def recommend_plows(
    *,
    truck_class: str,
    route_type: str,
    budget: str = "any",
    limit: int = 3,
) -> RecommendResult:
    """Score the catalog and return the top-N plows + truck-class warning.

    The fallback rule (the bug Ben caught on Apr 26): when the preferred
    families don't have any DIRECT fits for the chosen truck class, the
    recommender used to silently fall back to neighbor-class plows of the
    preferred family.  That gives picks the buyer reads as "doesn't fit my
    truck" once they reach the comparison page.

    New behaviour: if no direct-fit picks exist in the preferred family
    AND straight-blade direct fits DO exist, we ALSO return those, so the
    buyer always sees something that genuinely fits — plus a warning that
    explains why we widened the family.
    """
    if truck_class not in TRUCK_CLASS_TO_CATALOG:
        raise ValueError(f"Unknown truck class: {truck_class}")
    if route_type not in ROUTE_TO_FAMILY:
        raise ValueError(f"Unknown route type: {route_type}")
    if budget not in BUDGET_BUCKETS:
        raise ValueError(f"Unknown budget bucket: {budget}")

    target_classes = TRUCK_CLASS_TO_CATALOG[truck_class]
    preferred_families = ROUTE_TO_FAMILY[route_type]
    budget_low, budget_high = BUDGET_BUCKETS[budget]

    # First pass: score everything in the preferred family pool, hard-filter
    # to truck-class neighbors only.
    pool: list[PlowMatch] = []
    for model in CATALOG:
        if not _model_truck_classes_match(model, truck_class):
            continue
        m = _score_one(
            model,
            truck_class=truck_class,
            target_classes=target_classes,
            preferred_families=preferred_families,
            budget=budget,
            budget_low=budget_low,
            budget_high=budget_high,
        )
        if m is not None:
            pool.append(m)

    # Always prioritise direct fits over stretches — even when there are direct
    # picks in the preferred family, budget can push them below stretch picks
    # on raw score.  The buyer wants a plow that ACTUALLY FITS first.
    pool.sort(key=lambda x: (not x.direct_fit, -x.score))

    # Detect the half-ton-needs-winged style gap
    has_direct_in_preferred = any(
        _has_direct_family_fit(truck_class, fam) for fam in preferred_families
    )

    truck_class_warning: str | None = None
    suggested_step_up: str | None = None

    if not has_direct_in_preferred:
        # Build a friendly warning string + a fallback to direct-fit straight blades
        family_text = " or ".join(FAMILY_LABEL[f] for f in preferred_families)
        truck_class_warning = (
            f"No {family_text} plows are spec'd for {TRUCK_CLASS_LABEL[truck_class]} — "
            f"the front axle simply can't carry the weight.  Below: the closest "
            f"oversized picks (warranty-voiding stretch), plus straight-blade "
            f"options that actually fit your truck."
        )
        # Find a step-up suggestion: which truck class WOULD fit the preferred family?
        for upgrade in ["2500", "3500", "4500", "5500"]:
            if any(_has_direct_family_fit(upgrade, fam) for fam in preferred_families):
                suggested_step_up = (
                    f"Step up to a {TRUCK_CLASS_LABEL[upgrade]} and the {family_text} "
                    f"options open up."
                )
                break

        # Add direct-fit straight blade picks (the universal fallback family)
        # so the buyer always sees something that genuinely fits.
        fallback_pool: list[PlowMatch] = []
        for model in CATALOG:
            if model.family != "straight_blade":
                continue
            if truck_class not in model.truck_classes:
                continue
            m = _score_one(
                model,
                truck_class=truck_class,
                target_classes=target_classes,
                preferred_families=["straight_blade"],
                budget=budget,
                budget_low=budget_low,
                budget_high=budget_high,
            )
            if m is not None:
                fallback_pool.append(m)
        fallback_pool.sort(key=lambda x: -x.score)
        # Merge: keep the top stretch picks + top direct-fit fallbacks.  De-dupe
        # by plow.id since some straight blades may already be in pool.
        seen = {m.plow.id for m in pool}
        for fb in fallback_pool:
            if fb.plow.id not in seen:
                pool.append(fb)
                seen.add(fb.plow.id)
        # Re-sort after merge so the new fallback fits land in the right slots
        pool.sort(key=lambda x: (not x.direct_fit, -x.score))

        # Educational guard-rail: when the gap fires, always keep 1 stretch pick
        # in the result.  The user picked (e.g.) "lots" expecting a winged plow;
        # we owe them visibility into the wing-blade option even if it doesn't
        # fit their truck — so they see the upgrade path concretely.
        direct_picks = [m for m in pool if m.direct_fit]
        stretch_picks = [m for m in pool if not m.direct_fit]
        if direct_picks and stretch_picks:
            keep_direct = max(0, limit - 1)
            pool = direct_picks[:keep_direct] + stretch_picks[:1]
            pool.sort(key=lambda x: (not x.direct_fit, -x.score))

    return RecommendResult(
        matches=pool[:limit],
        truck_class_warning=truck_class_warning,
        suggested_step_up=suggested_step_up,
    )


def match_to_dict(m: PlowMatch) -> dict:
    return {
        "plow": asdict(m.plow),
        "score": m.score,
        "reasoning": m.reasoning,
        "direct_fit": m.direct_fit,
        "fit_warning": m.fit_warning,
    }


def result_to_dict(r: RecommendResult) -> dict:
    return {
        "matches": [match_to_dict(m) for m in r.matches],
        "truck_class_warning": r.truck_class_warning,
        "suggested_step_up": r.suggested_step_up,
    }
