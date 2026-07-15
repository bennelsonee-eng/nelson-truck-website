"""Check if Quick Match form is live (no captcha) on the active CDP tab."""
from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def main() -> int:
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://localhost:9222")
        target = None
        for ctx in b.contexts:
            for pg in ctx.pages:
                if "quick-match/plow" in (pg.url or ""):
                    target = pg
                    break
            if target:
                break
        if target is None:
            print("no QM tab found")
            return 1
        # Give it a moment to settle past any Incapsula challenge if present
        try:
            target.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        target.wait_for_timeout(3000)
        html = target.content()
        title = target.title()
        has_incap = "Incapsula_Resource" in html or "main-iframe" in html
        has_truck_radio = target.evaluate(
            "() => !!document.querySelector(\"input.vehicle-type-option\")"
        )
        print(f"url:           {target.url}")
        print(f"title:         {title!r}")
        print(f"html_len:      {len(html)}")
        print(f"has_incap:     {has_incap}")
        print(f"truck_radio:   {has_truck_radio}")
        print()
        if has_incap or not has_truck_radio:
            print("STATUS: form NOT live — captcha may need solving")
            return 2
        print("STATUS: form is live, walker can resume")
    return 0


if __name__ == "__main__":
    sys.exit(main())
