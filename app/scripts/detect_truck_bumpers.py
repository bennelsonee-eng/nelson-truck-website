"""Detect front-bumper bounding boxes in truck renders using Claude Vision.

Built for the snow-plow configurator (Snow E-2): each Wan 2.2-rendered truck
needs accurate (bumperCx, bumperCy, bumperWidth) coords so the plow overlay
lands on the actual bumper.  Eyeballing those coords is brittle; this script
asks Claude to look at every render and emit precise pixel coords.

The output drops into TRUCK_PROFILES in App.tsx.  Re-run this whenever new
truck renders land — the coords will adapt to whatever angle / framing the
new render has.

Requires ANTHROPIC_API_KEY in the environment.

Usage:
    python -m app.scripts.detect_truck_bumpers
    python -m app.scripts.detect_truck_bumpers --truck mid-size
    python -m app.scripts.detect_truck_bumpers --emit-typescript
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

import anthropic


RENDERS_DIR = Path(__file__).resolve().parent.parent / "backend" / "static" / "trucks" / "renders"

MODEL = "claude-sonnet-4-5"

# Prompt asks for tight, structured JSON we can parse without ceremony.
PROMPT = """Look at this image of a pickup truck or chassis cab.

The image is exactly 1024x576 pixels.  Coordinates use pixel units with the
origin at the TOP-LEFT (x grows right, y grows DOWN).

Identify the truck's FRONT BUMPER — the horizontal bumper bar across the
front of the vehicle, where a snow plow would attach.  Even if foreshortened
by the camera angle, give your best estimate of:

  - bumperCx: x-coordinate (pixels) of the visible CENTER of the front bumper
  - bumperCy: y-coordinate (pixels) of the visible CENTER of the front bumper
  - bumperWidth: visible width of the bumper in pixels (foreshortened
    by the camera angle — this is the apparent width on screen, not the
    real-world bumper width)
  - facingDirection: "left" if the truck's front grille points toward the
    left side of the image, "right" if it points right

Respond with ONLY a JSON object on a single line, no markdown, no commentary:
{"bumperCx": 800, "bumperCy": 400, "bumperWidth": 240, "facingDirection": "right", "confidence": 0.92, "notes": "F-150 at 3/4 view, front grille right-of-center"}
"""


def encode_image(path: Path) -> tuple[str, str]:
    """Return (media_type, base64-encoded image)."""
    suffix = path.suffix.lower().lstrip(".")
    mt_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}
    media_type = mt_map.get(suffix, "image/png")
    return media_type, base64.standard_b64encode(path.read_bytes()).decode("ascii")


def detect_one(client: anthropic.Anthropic, render_path: Path) -> dict:
    media_type, b64 = encode_image(render_path)
    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text",  "text": PROMPT},
            ],
        }],
    )
    text = response.content[0].text.strip()
    # Find the JSON object — model sometimes wraps it
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON object found in response: {text!r}")
    data = json.loads(m.group(0))
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--truck", help="Single truck class id (mid-size / 1500 / 2500 / 3500 / 4500 / 5500)")
    p.add_argument("--emit-typescript", action="store_true",
                   help="Print a ready-to-paste TRUCK_PROFILES block")
    args = p.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set in environment.", file=sys.stderr)
        print("On Windows, set it with:", file=sys.stderr)
        print("  setx ANTHROPIC_API_KEY \"sk-ant-...\"", file=sys.stderr)
        print("  (then restart your shell)", file=sys.stderr)
        return 2

    client = anthropic.Anthropic()

    if args.truck:
        targets = [RENDERS_DIR / f"{args.truck}.png"]
    else:
        targets = sorted(RENDERS_DIR.glob("*.png"))

    results: dict[str, dict] = {}
    for path in targets:
        if not path.exists():
            print(f"  SKIP (missing): {path}")
            continue
        truck_id = path.stem
        print(f"\n[{truck_id}] {path.name}")
        try:
            data = detect_one(client, path)
            results[truck_id] = data
            print(f"  cx={data.get('bumperCx')}, cy={data.get('bumperCy')}, "
                  f"w={data.get('bumperWidth')}, facing={data.get('facingDirection')}, "
                  f"conf={data.get('confidence')}")
            if data.get("notes"):
                print(f"  notes: {data['notes']}")
        except Exception as e:
            print(f"  FAILED: {e}")

    print()
    print("=== JSON ===")
    print(json.dumps(results, indent=2))

    if args.emit_typescript:
        print()
        print("=== TypeScript (paste into TRUCK_PROFILES) ===")
        for truck_id, data in results.items():
            cx = data.get("bumperCx")
            cy = data.get("bumperCy")
            w = data.get("bumperWidth")
            print(f'  // {truck_id}: facing={data.get("facingDirection")} conf={data.get("confidence")}')
            print(f'  // {data.get("notes", "")}')
            print(f'  bumperCx: {cx}, bumperCy: {cy}, bumperWidth: {w},')
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
