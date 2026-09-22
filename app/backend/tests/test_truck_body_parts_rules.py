"""Which Knapheide parts list under which truck body (app/scripts/truck_body_parts_rules.py).

Each case is a real part from the 255 that were filed on "Truck Bodies" on prod
(2026-09-21), and most are ones a first draft of the rules got wrong.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from truck_body_parts_rules import classify, sized_body  # noqa: E402


def test_rules_file_holds_regex_word_boundaries_not_backspaces():
    # A heredoc once turned every \b into a 0x08 byte; the rules still imported
    # and quietly stopped matching KEY, BOLT, LUG and ICC.
    assert bytes([8]) not in (SCRIPTS / "truck_body_parts_rules.py").read_bytes()


@pytest.mark.parametrize("sku,name,group,families", [
    # wiring adapters mention a cab-to-axle size but are wiring, for every body
    ("KNP-20009670", "ADAPTER, 17OLD FORD 40/56CA", "Lighting & wiring", None),
    # an install kit that mentions a hitch is still an install kit
    ("KNP-20226010", "KIT, INSTALL 20 GM WITH HITCH", "Mounting & installation kits", ["service"]),
    # a receiver hitch whose description mentions a mounting system is still a hitch,
    # and "PGT" makes it a gooseneck part
    ("KNP-34537687", "Heavy-duty 21,000 lb capacity receiver hitch designed specifically for Knapheide "
                     "9' and 11' PGT service bodies. Provides secure towing capability for commercial work "
                     "trucks with integrated mounting system.", "Bumpers & hitches", ["gooseneck"]),
    ("KNP-35135312", 'CLASS V HITCH SB 2"', "Bumpers & hitches", ["service"]),
    ("KNP-KNP33931798", "CLASS V 21,000LB HITCH/ICC", "Bumpers & hitches", ["platform", "dump"]),
    # doors in general are service-body parts; this one says gooseneck
    ("KNP-80413719P", "DOOR, GOOSENECK", "Doors, latches & locks", ["gooseneck"]),
    ("KNP-KNP12211173", "KUV REAR DOOR WINDOW", "Glass & windows", ["kuv"]),
    # family read from the SKU when the name doesn't say
    ("KNP-PGTZSIDES-894", 'SIDES, 4" High Z Shaped', "Racks, bulkheads & sides", ["gooseneck"]),
    ("KNP-BHR4894C", 'BULKHEAD, REINFORCED 48"X94', "Racks, bulkheads & sides", ["platform"]),
    # Knapheide offers cab guards on service, dump and landscaper bodies -- not platforms
    ("KNP-26266379", 'CAB GUARD MODULAR 49" UNIV', "Racks, bulkheads & sides", ["service", "dump", "landscape"]),
    ("KNP-12247359", "KEY, ONE PLUS #", "Doors, latches & locks", ["service", "kuv", "mechanics", "gooseneck"]),
    ("KNP-KNP12010040", "BOLT WHIZ", "Hardware & touch-up", None),
    ("KNP-85412607LED", "LED LIGHT KIT PVM SERIES", "Lighting & wiring", ["platform"]),
])
def test_part_lands_under_the_right_bodies(sku, name, group, families):
    got = classify(sku, name)
    assert got is not None, f"{sku} unmatched"
    assert got[0] == group
    if families is not None:
        assert got[1] == families


def test_a_bare_name_is_left_for_review_not_guessed():
    assert classify("KNP-33670260", "BUMPER") is None


@pytest.mark.parametrize("sku,family,model", [
    ("KNP-6108D54-2", "service", "KNP-S15035"),        # standard steel service body
    ("KNP-696F-2", "service", "KNP-S15008"),           # fliptop
    ("KNP-6132D54LP", "service", "KNP-S204945"),       # low profile
    ("KNP-KNPPVMX-125", "platform", "KNP-S15033"),     # Value-Master X
    ("KNP-KNPPCON-9-W", "platform", "KNP-S91141"),     # contractor
    ("KNP-KNPPGTB-96", "gooseneck", "KNP-S91146"),     # PGTB = the renamed PGNB
    ("KNP-PGTC-1110", "gooseneck", "KNP-S91145"),
])
def test_sized_bodies_map_to_their_model(sku, family, model):
    assert sized_body(sku) == (family, model)


def test_part_numbers_are_not_mistaken_for_service_bodies():
    # 8-digit Knapheide part numbers starting 5/6/7 are parts, not 500/600/700-series bodies
    assert sized_body("KNP-77001972") is None
    assert sized_body("KNP-KNP77008282") is None
