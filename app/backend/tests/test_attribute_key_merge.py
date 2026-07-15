"""Tests for the facet-key merge engine (attribute_key_merge).

Pure string logic — no DB. Covers the two grouping sources (auto label-variant,
manual synonym), value re-bucketing across differently-formatted keys, and the
label-selection rules. The facet-render and browse-filter paths both depend on
these, so a regression here means clicks that return nothing.
"""
from __future__ import annotations

from app.services.attribute_key_merge import (
    KeyGroup,
    compute_key_groups,
    group_value_bucket,
    merge_values,
    normalize_key_name,
)


# --- normalize_key_name -------------------------------------------------

def test_normalize_folds_unit_suffix_variants():
    assert normalize_key_name("Overall Length") == normalize_key_name("Overall Length (in.)")
    assert normalize_key_name("Overall Length") == normalize_key_name("Overall Length(in)")


def test_normalize_folds_plural_case_spacing():
    assert normalize_key_name("Parts Pack") == normalize_key_name("Parts Pack(s)")
    assert normalize_key_name("TOTAL LENGTH") == normalize_key_name("Total Length")
    assert normalize_key_name("Weight Carrying Capacity(WC)") == \
        normalize_key_name("Weight Carrying Capacity (WC)")


def test_normalize_keeps_genuine_synonyms_distinct():
    # These mean the same thing but are NOT pure formatting — curator's job.
    assert normalize_key_name("Volume") != normalize_key_name("Gallon Capacity")
    assert normalize_key_name("Install Time") != normalize_key_name("Installation Time")
    # And genuinely different attributes stay apart.
    assert normalize_key_name("Diameter") != normalize_key_name("Height")


# --- group_value_bucket -------------------------------------------------

def test_value_bucket_collapses_numeric_formats():
    assert group_value_bucket("100") == group_value_bucket("100 Gallon")
    assert group_value_bucket("100") == group_value_bucket("100 Gallons")
    assert group_value_bucket("2,000") == group_value_bucket("2000 lbs")


def test_value_bucket_separates_different_numbers():
    assert group_value_bucket("100 Gallon") != group_value_bucket("75 Gallon")


def test_value_bucket_textual_uses_canonical():
    assert group_value_bucket("aluminum") == group_value_bucket("Aluminum")


# --- compute_key_groups: auto label-variant -----------------------------

def test_auto_groups_label_variants():
    groups = compute_key_groups(
        [("Overall Length", 50), ("Overall Length (in.)", 10), ("Material", 30)],
        manual_map={},
    )
    by_label = {g.label: g for g in groups}
    # The two length keys fold; Material stands alone.
    assert "Material" in by_label
    length = next(g for g in groups if "Length" in g.label)
    assert set(length.members) == {"Overall Length", "Overall Length (in.)"}
    assert length.is_merged
    # Winner label = highest-coverage member.
    assert length.label == "Overall Length"
    assert by_label["Material"].is_merged is False
    assert by_label["Material"].source == "single"


# --- compute_key_groups: manual synonym ---------------------------------

def test_manual_groups_synonyms_under_curator_label():
    manual = {
        "Volume": "Gallon Capacity",
        "Gallon Capacity": "Gallon Capacity",
        "Liquid Storage Capacity": "Gallon Capacity",
    }
    groups = compute_key_groups(
        [("Volume", 25), ("Gallon Capacity", 17),
         ("Liquid Storage Capacity", 9), ("Material", 40)],
        manual_map=manual,
    )
    tank = next(g for g in groups if g.label == "Gallon Capacity")
    assert set(tank.members) == {"Volume", "Gallon Capacity", "Liquid Storage Capacity"}
    assert tank.is_merged and tank.source == "manual"
    # Even though Volume has the highest count, the curator's label wins.
    assert tank.label == "Gallon Capacity"


def test_auto_and_manual_merge_into_one_component():
    # Volume(+auto variant) plus a manual synonym all collapse together.
    manual = {"Volume": "Tank Gallons", "Gallon Capacity": "Tank Gallons"}
    groups = compute_key_groups(
        [("Volume", 25), ("Volume (gal)", 5), ("Gallon Capacity", 17)],
        manual_map=manual,
    )
    assert len(groups) == 1
    g = groups[0]
    assert g.label == "Tank Gallons"
    assert set(g.members) == {"Volume", "Volume (gal)", "Gallon Capacity"}


def test_group_order_follows_input_priority():
    groups = compute_key_groups(
        [("Material", 100), ("Overall Length", 50), ("Overall Length (in.)", 10)],
        manual_map={},
    )
    assert groups[0].label == "Material"  # highest-priority first


# --- merge_values -------------------------------------------------------

def test_merge_values_unions_across_keys_and_prefers_unit_label():
    # "100" from one key, "100 Gallons" from another -> one bucket, count summed,
    # the unit-bearing form wins the label.
    rows = [
        ("100", None, 17),
        ("100 Gallons", "GAL", 25),
        ("75", None, 10),
    ]
    vals = merge_values(rows)
    by_bucket = {v.bucket: v for v in vals}
    hundred = by_bucket[group_value_bucket("100")]
    assert hundred.count == 42
    # auto_canonical depluralizes -> "100 Gallon"
    assert "Gallon" in hundred.label
    assert hundred.uom == "GAL"
    # sorted by count desc
    assert vals[0].count >= vals[-1].count


def test_merge_values_skips_blanks():
    vals = merge_values([("", None, 5), ("100", None, 3)])
    assert len(vals) == 1
    assert vals[0].count == 3
