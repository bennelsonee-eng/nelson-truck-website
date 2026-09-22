"""Parser tests for the truck-body manufacturer pages (app/scripts/manufacturer_pages.py).

Each fixture is the smallest reproduction of a real page structure that broke
a first attempt at parsing it -- the comments say which.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from manufacturer_pages import parse_cm, parse_knapheide  # noqa: E402


KN_PAGE = """
<h1>Steel Service Body</h1>
<p>Field technicians across many industries can tackle tasks on-site because these bodies carry the tools.</p>
<div class="vi-feature-container"><div class="vi-feature-content-container">
  <h4 class="vi-feature-title">Body Shell</h4><div class="vi-feature-content">Rugged 14-gauge galvanneal steel.</div>
</div></div>
<h3>Body Options</h3>
<h4>500 Series Compartments</h4><button>More Details</button>
<h4>Flip Top Compartments</h4><button>More Details</button>
<div class="modal fade" id="more-details-26048" tabindex="-1" role="dialog">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">500 Series Compartments</h5>
      <button class="close"><span>&times;</span></button></div>
    <div class="modal-body">One full height vertical compartment in the front.</div>
    <div class="modal-footer"><button>Close</button></div>
  </div></div></div>
<div class="modal fade" id="more-details-25526" tabindex="-1" role="dialog">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Flip Top Compartments</h5></div>
    <div class="modal-body">Lids that lift for top access.</div>
  </div></div></div>
<h3>Specifications</h3>
<table><thead><tr><th>Model 500 Series</th><th>Model 600 Series</th><th>Body Length</th></tr></thead>
<tbody>
  <tr><td colspan="3">40" CA, Single Wheel - 1999 or later Ford</td><td></td><td></td></tr>
  <tr><td>580</td><td>680</td><td>80"</td></tr>
  <tr><td></td><td>680LP</td><td>80"</td></tr>
</tbody></table>
<h3>Literature</h3>
<a title="Steel Service Literature-Ford" href="https://www.knapheide.com/wp-content/uploads/2019/04/Steel-Ford.pdf">DOWNLOAD</a>
<a title="Steel Service Literature-Ford" href="https://www.knapheide.com/wp-content/uploads/2019/04/Steel-Ford.pdf">DOWNLOAD</a>
<h3>Resources</h3>
"""


def test_knapheide_option_text_found_through_nested_modal_divs():
    # The pop-up nests modal-dialog / modal-content divs; stopping at the next
    # '<div class="modal' returned an empty body for every one of 346 options.
    opts = {o["name"]: o["description"] for o in parse_knapheide(KN_PAGE)["options"]}
    assert opts == {
        "500 Series Compartments": "One full height vertical compartment in the front.",
        "Flip Top Compartments": "Lids that lift for top access.",
    }


def test_knapheide_features_come_from_feature_divs_not_paragraphs():
    feats = parse_knapheide(KN_PAGE)["features"]
    assert feats == [{"heading": "Body Shell", "body": "Rugged 14-gauge galvanneal steel."}]


def test_knapheide_cab_to_axle_heading_becomes_a_group_row():
    t = parse_knapheide(KN_PAGE)["spec_tables"][0]
    assert t["headers"] == ["Model 500 Series", "Model 600 Series", "Body Length"]
    assert t["rows"][0] == {"type": "group", "label": '40" CA, Single Wheel - 1999 or later Ford'}
    assert t["rows"][1] == {"type": "row", "cells": ["580", "680", '80"']}
    # an empty cell means "not offered in this series" and must stay empty, not shift left
    assert t["rows"][2] == {"type": "row", "cells": ["", "680LP", '80"']}


def test_knapheide_literature_is_deduplicated():
    lit = parse_knapheide(KN_PAGE)["literature"]
    assert lit == [{"title": "Steel Service Literature-Ford",
                    "url": "https://www.knapheide.com/wp-content/uploads/2019/04/Steel-Ford.pdf"}]


CM_PAGE = """
<h1>SK Steel Skirted Body</h1>
<table><tr><td>Program</td><td>Min. Financed</td><td>Monthly Payments</td></tr>
       <tr><td>7.99% for 24 Months *</td><td>$1,500 - $9,999</td><td></td></tr></table>
<h2>Set the standard.</h2>
<p>Looking for the ultimate combination of deck space and integrated toolbox storage? The SK sets the standard.</p>
<h3>Specs &amp; Features</h3>
<table><tr><td>Lengths</td><td>84", 8'6"</td></tr><tr><td>Deck</td><td>11-Gauge Steel Tread Plate</td></tr></table>
<p>* Beds designed for a RAM Mega Cab will only have two tool boxes in the rear.</p>
<a href="/wp-content/uploads/2020/06/SK_Overview.pdf">Download Model Overview</a>
<h3>Standard Equipment Information</h3>
<h4>4&#8243; Structual Steel Channel Frame Rails</h4><p>Because we don't use roll-formed runners, our rails are strong.</p>
<h4>4&#8243; structural steel channel frame rails</h4><p>Because we don't use roll-formed runners, our rails are strong.</p>
<h3>Available Options</h3>
<h4>Cargo Light</h4><p>This option provides truck bed lighting so users can see their tools.</p>
<h3>Brochure</h3>
"""


def test_cm_intro_skips_the_sitewide_tagline():
    assert parse_cm(CM_PAGE)["intro"] == [
        "Looking for the ultimate combination of deck space and integrated toolbox storage? The SK sets the standard."]


def test_cm_specs_skip_the_financing_table_and_keep_the_footnote():
    d = parse_cm(CM_PAGE)
    assert d["spec_kv"] == [("Lengths", "84\", 8'6\""), ("Deck", "11-Gauge Steel Tread Plate")]
    assert d["spec_note"] == "Beds designed for a RAM Mega Cab will only have two tool boxes in the rear."


def test_cm_relative_pdf_link_is_made_absolute():
    # Two CM pages link their overview by path only; urllib can't fetch "/wp-content/...".
    assert parse_cm(CM_PAGE)["literature"] == [
        {"title": "Download Model Overview",
         "url": "https://cmtruckbeds.com/wp-content/uploads/2020/06/SK_Overview.pdf"}]


def test_cm_same_paragraph_under_two_spellings_is_kept_once():
    feats = parse_cm(CM_PAGE)["features"]
    assert len(feats) == 1 and feats[0]["heading"].startswith("4″ Structual")


def test_cm_options_are_separate_from_standard_equipment():
    d = parse_cm(CM_PAGE)
    assert [o["name"] for o in d["options"]] == ["Cargo Light"]
    assert all(f["heading"] != "Cargo Light" for f in d["features"])
