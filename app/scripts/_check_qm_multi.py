"""Check Quick Match form status on multiple CDP ports."""
import sys
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ports = [int(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else [9222, 9223, 9224]

for port in ports:
    print(f"--- Port {port} ---")
    try:
        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(f"http://localhost:{port}")
            target = None
            for ctx in b.contexts:
                for pg in ctx.pages:
                    url = pg.url or ""
                    if "quick-match" in url or "westernplows" in url:
                        target = pg
                        break
                if target:
                    break
            if not target:
                print(f"  No QM tab found")
                continue
            target.wait_for_timeout(3000)
            html = target.content()
            title = target.title()
            has_incap = "Incapsula_Resource" in html or "main-iframe" in html
            has_truck = 'vehicle-type-option' in html
            print(f"  url: {target.url}")
            print(f"  title: {title!r}")
            print(f"  incapsula: {has_incap}")
            print(f"  truck_radio: {has_truck}")
            if has_incap or not has_truck:
                print(f"  STATUS: CAPTCHA NEEDED")
            else:
                print(f"  STATUS: LIVE - ready to scrape!")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()
