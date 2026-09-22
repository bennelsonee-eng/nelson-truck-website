"""Which Knapheide parts belong under which truck body.

Owner, 2026-09-21: the 255 Knapheide parts that were filed on "Truck Bodies"
should be listed as options underneath the correct truck body. Knapheide
publishes no part-number-to-body data (its store API hides SKUs behind
hashes), so the mapping is read from the part itself: its SKU family
(600-series, PGT/PGN, PVMX, PCON, BH*/R40 racks) and the words Knapheide's
own descriptions use (SB = service body, KUV, PLATFORM, 78"/94" body widths,
CA = cab-to-axle sizes that service bodies are sold by). Each body family is
checked against the options Knapheide lists on that body's page -- e.g.
bulkheads and stake racks are platform options, cab protectors are dump and
landscaper options.

Pure data + functions, no database: `classify(sku, name)` returns
(group, families, rule) or None. Unmatched parts are reported for review,
never guessed.
"""
from __future__ import annotations

import re

# Body families -> the showcase body SKUs in that family. Sized bodies (below)
# are added to their family at run time.
FAMILIES: dict[str, list[str]] = {
    "service":   ["KNP-S15035", "KNP-S15008", "KNP-S204945", "KNP-S15006", "KNP-S15002",
                  "KNP-S204958", "KNP-S15007", "KNP-S91165", "KNP-S91164"],
    "kuv":       ["KNP-S91148", "KNP-S91149", "KNP-S204963"],
    "platform":  ["KNP-S15781", "KNP-S15031", "KNP-S15030", "KNP-S204984", "KNP-S15033",
                  "KNP-S91142", "KNP-S91141"],
    "gooseneck": ["KNP-S91146", "KNP-S91145", "KNP-S91144", "KNP-S91137"],
    "landscape": ["KNP-S91161"],
    "dump":      ["KNP-S91162", "KNP-S204985", "KNP-S91163"],
    "forestry":  ["KNP-S91155"],
    "saw":       ["KNP-S204986"],
    "mechanics": ["KNP-S15013"],
}
ALL_KNAPHEIDE = list(FAMILIES)

# Sized bodies -> (family, the showcase model they are a configuration of).
# Knapheide renamed PGN -> PGT (PGNB = PGTB, PGNC = PGTC, PGND = PGTD).
SIZED_BODIES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^KNP-(?:KNP)?6132D54LP"), "service", "KNP-S204945"),              # low profile
    (re.compile(r"^KNP-(?:KNP)?[567](?:\d{2}|1\d{2})[A-Z0-9]*F"), "service", "KNP-S15008"),  # fliptop
    (re.compile(r"^KNP-(?:KNP)?[567](?:\d{2}|1\d{2})(?:[A-Z]|-|$)"), "service", "KNP-S15035"),
    (re.compile(r"^KNP-(?:KNP)?PVMX"), "platform", "KNP-S15033"),
    (re.compile(r"^KNP-(?:KNP)?PCON-"), "platform", "KNP-S91141"),
    (re.compile(r"^KNP-(?:KNP)?PGTC"), "gooseneck", "KNP-S91145"),
    (re.compile(r"^KNP-(?:KNP)?PGTD"), "gooseneck", "KNP-S91144"),
    (re.compile(r"^KNP-(?:KNP)?PGTB|^KNP-NGB-"), "gooseneck", "KNP-S91146"),
]

GROUP_ORDER = [
    "Sizes & configurations",      # the sized, orderable bodies of this model (each card shows its own stock)
    "Bumpers & hitches",
    "Mounting & installation kits",
    "Racks, bulkheads & sides",
    "Toolboxes & storage",
    "Doors, latches & locks",
    "Glass & windows",
    "Fuel fill & hydraulics",
    "Lighting & wiring",
    "Hardware & touch-up",
]

# (rule id, regex on the part NAME, families, group). First match wins, so the
# specific families (PGT, PVM, KUV, platform) come before the generic words.
R = re.IGNORECASE
# Families per option come from Knapheide's own model pages (which bodies list
# tool boxes, cab guards, ICC bumpers, receiver hitches, stake racks, ...),
# measured 2026-09-21 from knapheide_parsed.json.
SERVICE_LIKE = ["service", "kuv"]
TOOLBOX_BODIES = ["platform", "dump", "landscape", "gooseneck", "forestry"]
HITCH_BODIES = ["service", "kuv", "platform", "dump", "landscape", "gooseneck"]
LATCH_BODIES = ["service", "kuv", "mechanics", "gooseneck"]

# Family markers: matched against SKU + name, carry no group of their own.
MARKERS: list[tuple[str, re.Pattern, list[str]]] = [
    ("pgt-pgn",       re.compile(r"\bPG[NT][A-Z]?\b|PGT[A-Z]|\bPGN|GOOSE?NECK", R), ["gooseneck"]),
    ("pvm",           re.compile(r"\bPVM", R), ["platform"]),
    ("kuv",           re.compile(r"\bKUV\b", R), ["kuv"]),
    ("platform-word", re.compile(r"\bPLATFORM\b", R), ["platform"]),
]

# (rule id, regex on the part NAME, default families, group). First match wins.
RULES: list[tuple[str, re.Pattern, list[str], str]] = [
    # lighting & wiring first: wiring adapters carry chassis/CA text that would
    # otherwise read as a mounting kit. Every Knapheide body uses these.
    ("lighting",       re.compile(r"LIGHT|\bLED\b|\bSTT\b|STOP/TAIL|MARKER|STROBE|HARNESS|WIRING|ADAPTER|7WAY|7 PLUG", R), ALL_KNAPHEIDE, "Lighting & wiring"),
    ("glass",          re.compile(r"GLASS|WINDOW", R), ["kuv"], "Glass & windows"),
    # racks, bulkheads, sides
    ("bulkhead",       re.compile(r"BULKHEAD|HEADBOARD", R), ["platform"], "Racks, bulkheads & sides"),
    ("stake",          re.compile(r"STAKE", R), ["platform", "gooseneck"], "Racks, bulkheads & sides"),
    ("sides",          re.compile(r"\bSIDES\b|SIDE BOARDS", R), ["platform", "gooseneck"], "Racks, bulkheads & sides"),
    ("r40-rack",       re.compile(r"RACK 40\"|40-inch height|40\" (LEFT|RIGHT)|cargo rack system|\bR40", R), ["platform"], "Racks, bulkheads & sides"),
    ("refuse-sides",   re.compile(r"REFUSE", R), ["platform"], "Racks, bulkheads & sides"),
    ("overcab-rack",   re.compile(r"OVERCAB MAT RACK", R), ["platform"], "Racks, bulkheads & sides"),
    ("cab-guard",      re.compile(r"CAB GUARD", R), ["service", "dump", "landscape"], "Racks, bulkheads & sides"),
    ("service-racks",  re.compile(r"UTILITY RACK|LADDER RACK|RACK, 96\" BODY|96-inch service", R), SERVICE_LIKE, "Racks, bulkheads & sides"),
    ("body-pack",      re.compile(r"body pack", R), ["dump", "platform", "landscape"], "Toolboxes & storage"),
    # Hitches that name their body type come first ("HITCH SB" = service body,
    # "HITCH/ICC" = platform/dump). Then a part that calls itself a receiver
    # hitch is one, even when its description goes on to mention an
    # "integrated mounting system" (KNP-34537687).
    ("icc",            re.compile(r"\bICC\b", R), ["platform", "dump"], "Bumpers & hitches"),
    ("sb-hitch",       re.compile(r"HITCH SB|\bSB 2\"", R), ["service"], "Bumpers & hitches"),
    ("receiver-hitch-named", re.compile(r"RECEIVER HITCH|RECEIVER HIT\b|CLASS V\b|CLASS 5\b", R), HITCH_BODIES, "Bumpers & hitches"),
    # mounting & installation (before the generic hitch rule: "KIT, INSTALL 20 GM WITH HITCH" is an install kit)
    ("toolbox-mount",  re.compile(r"TOOLBOX MOUNTING|SHOVEL BOX", R), TOOLBOX_BODIES, "Mounting & installation kits"),
    ("mudflap",        re.compile(r"MUDFLAP", R), ["platform", "dump", "landscape"], "Mounting & installation kits"),
    ("tailgate-mount", re.compile(r"TAILGATE", R), ["platform", "dump", "landscape"], "Mounting & installation kits"),
    ("vise",           re.compile(r"VISE", R), ["service", "mechanics"], "Mounting & installation kits"),
    # service bodies are sold by cab-to-axle (56/60/84 CA); these kits mount them to the chassis
    ("sb-install",     re.compile(r"\d\d ?CA\b|/\d\dCA|UNDERSTRUCTURE|INSTALL|\bINST\b|INTALL|MOUNT(ING)? KI|MT KIT|QK MT|mounting (kit|system|bracket)", R), ["service"], "Mounting & installation kits"),
    # bumpers & hitches
    ("liftgate-bumper",re.compile(r"LIFTGATE", R), ["service"], "Bumpers & hitches"),
    ("sb-bumper",      re.compile(r"BUMPER SB|BUMPER.*\b(78|89|94)\b|\b(78|83|94)\"? ?WIDE|\b(78|94)-inch|KNAPLIN|GALVA.?GRIP|BUMPER, STEP", R), SERVICE_LIKE, "Bumpers & hitches"),
    ("receiver-hitch", re.compile(r"RECEIVER|CLASS V|CLASS 5|HITCH", R), HITCH_BODIES, "Bumpers & hitches"),
    # storage & interior
    ("underbody-box",  re.compile(r"UNDERBODY|^TOOLBOX$", R), TOOLBOX_BODIES, "Toolboxes & storage"),
    ("interior",       re.compile(r"CABINET|SHELF|DIVIDER|DRAWER|GRAB HANDLE", R), LATCH_BODIES, "Toolboxes & storage"),
    # doors, latches, locks
    ("latches",        re.compile(r"LATCH|NXG|T-HANDLE|\bKEY\b|POWER LOCK|DOOR|SEAL|SPRING", R), LATCH_BODIES, "Doors, latches & locks"),
    # fuel fill & hydraulics
    ("fuel-fill",      re.compile(r"FUEL FILL", R), ["service", "kuv", "mechanics"], "Fuel fill & hydraulics"),
    ("pump",           re.compile(r"PUMP|RESEVOIR|RESERVOIR", R), ["dump"], "Fuel fill & hydraulics"),
    # hardware & touch-up
    ("hardware",       re.compile(r"\bNUT\b|NUT\.|\bBOLT\b|SCREW|RIVNUT|\bLUG\b|BUMPER, RUBBER|PAINT|EMBLEM", R), ALL_KNAPHEIDE, "Hardware & touch-up"),
]

def sized_body(sku: str) -> tuple[str, str] | None:
    """(family, showcase SKU) when the SKU is a sized, orderable body."""
    for rx, fam, model in SIZED_BODIES:
        if rx.search(sku):
            return fam, model
    return None


def classify(sku: str, name: str) -> tuple[str, list[str], str] | None:
    """(group, families, rule id) for a part, or None when no rule is sure.

    A family marker (PGT, PVM, KUV, PLATFORM in the SKU or name) overrides the
    rule's default families: a "DOOR, GOOSENECK" is a gooseneck part even
    though doors in general belong to service bodies."""
    text = f"{sku} {name}"
    marker = next(((rid, fams) for rid, rx, fams in MARKERS if rx.search(text)), None)
    for rid, rx, fams, group in RULES:
        if rx.search(name or ""):
            # Hardware (whiz nuts, touch-up paint) fits every Knapheide body whatever the SKU says.
            if marker and group != "Hardware & touch-up":
                return group, marker[1], f"{marker[0]}+{rid}"
            return group, fams, rid
    if marker:        # family known, kind of part not named: file it with that family's install hardware
        return "Mounting & installation kits", marker[1], marker[0] + "+install-default"
    return None
