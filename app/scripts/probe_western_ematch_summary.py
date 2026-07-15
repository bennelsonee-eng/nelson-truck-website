"""Reset to step1, drive Truck/2026/CHEVY-GMC/CANYON all the way through to
the /summary page, picking one specific path (Defender 6'8"/Joystick/LED).

Captures every Ematch XHR + the final summary HTML so we can see where the
full BOM (mount kit + harness + blade + control + lights) lives.

Output: app/data/wsm_export/_western_probe/ematch_summary_*.html / jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import Response, sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROBE_DIR = REPO_ROOT / "app" / "data" / "wsm_export" / "_western_probe"

CDP_URL = "http://localhost:9222"


def find_quick_match_tab(browser):
    for ctx in browser.contexts:
        for pg in ctx.pages:
            try:
                if "quick-match/plow" in (pg.url or ""):
                    return ctx, pg
            except Exception:
                continue
    return None, None


def main() -> int:
    captured: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx, page = find_quick_match_tab(browser)
        if page is None:
            print("[summary] no quick-match tab", flush=True)
            return 2

        def on_response(resp: Response) -> None:
            url = resp.url
            if "Ematch" not in url and "ematch" not in url and "/quick-match/" not in url:
                return
            try:
                body = resp.text()
            except Exception:
                body = "(no body)"
            captured.append({
                "url": url,
                "status": resp.status,
                "method": resp.request.method,
                "post_data": getattr(resp.request, "post_data", None),
                "response_body": body[:80_000],
            })
            print(f"[summary] XHR {resp.request.method} {url.rsplit('/', 1)[-1][:60]} "
                  f"-> {resp.status} ({len(body)}B)", flush=True)

        page.on("response", on_response)

        # 0. Start fresh
        print("[summary] navigating to step1 fresh", flush=True)
        page.goto("https://resources.westernplows.com/quick-match/plow/step1",
                  wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)

        # 1. Click Truck
        print("[summary] picking Truck", flush=True)
        page.locator("input.vehicle-type-option[value='Truck']").first.check(force=True)
        page.wait_for_timeout(3000)

        # 2. Year 2026
        print("[summary] picking 2026", flush=True)
        page.select_option("#vehicleyearoption", "2026")
        page.wait_for_timeout(3000)

        # 3. Make
        print("[summary] picking CHEVY/GMC", flush=True)
        page.select_option("#vehiclemakeoption", "CHEVY/GMC")
        page.wait_for_timeout(3000)

        # 4. Model (first one that's a Canyon variant)
        print("[summary] picking CANYON (ALL TRIMS, see notes)", flush=True)
        page.select_option("#vehiclemodeloption", "CANYON (ALL TRIMS, see notes)")
        page.wait_for_timeout(3000)

        # Click Next to go to step2
        print("[summary] Next -> step2", flush=True)
        page.locator("button.ematch-page-next").first.click()
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3500)

        # 5. Step2 selects — pick first non-empty in order
        step2_selects = [
            "#vehicledrivetrainoption", "#vehiclebodystyleoption",
            "#vehicledualrearwheelsoption", "#vehicleboxoption",
            "#vehicleengineoption", "#vehicleminfgawroption",
            "#vehicleminrgawroption", "#vehiclemingvwroption",
            "#vehicleheadlampstyleoption",
        ]
        for sel in step2_selects:
            try:
                opts = page.evaluate(
                    f"""() => {{
                        const s = document.querySelector('{sel}');
                        if (!s) return [];
                        return Array.from(s.options)
                            .map(o => ({{value: o.value, label: o.textContent.trim()}}))
                            .filter(o => o.value);
                    }}"""
                )
                if not opts:
                    continue
                print(f"[summary] step2 {sel} -> {opts[0]['value']!r}", flush=True)
                page.select_option(sel, opts[0]["value"])
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[summary] step2 {sel}: {e}", flush=True)

        # Click Next to step3
        print("[summary] Next -> step3", flush=True)
        page.locator("button.ematch-page-next").first.click()
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3500)

        # 6. Step3: pick 6'8" Defender (radio value=55)
        print("[summary] picking 6'8\" Defender radio", flush=True)
        page.locator("input[type=radio][name='mountbladegridview'][value='55']").first.check(force=True)
        page.wait_for_timeout(3000)

        # Click Next to step4
        print("[summary] Next -> step4", flush=True)
        page.locator("button.ematch-page-next").first.click()
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3500)

        (PROBE_DIR / "summary_step4.html").write_text(page.content(), encoding="utf-8")

        # 7. Step4: pick Joystick + LED
        print("[summary] picking Joystick + LED", flush=True)
        try:
            page.locator("input[type=radio][name='VehicleControlType'][value='Joystick Control']").first.check(force=True)
            page.wait_for_timeout(2500)
        except Exception as e:
            print(f"[summary] joystick: {e}", flush=True)
        try:
            page.locator("input[type=radio][name='VehiclePlowHeadLampType'][value='LED']").first.check(force=True)
            page.wait_for_timeout(2500)
        except Exception as e:
            print(f"[summary] LED: {e}", flush=True)

        # Click Next -> summary
        print("[summary] Next -> summary", flush=True)
        try:
            page.locator("button.ematch-page-next").first.click()
            page.wait_for_load_state("domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"[summary] next-to-summary failed: {e}", flush=True)

        print(f"[summary] final URL: {page.url}", flush=True)
        (PROBE_DIR / "summary_final.html").write_text(page.content(), encoding="utf-8")
        try:
            page.screenshot(path=str(PROBE_DIR / "summary_final.png"), full_page=True)
        except Exception:
            pass

        (PROBE_DIR / "summary_responses.jsonl").write_text(
            "\n".join(json.dumps(c) for c in captured) + "\n",
            encoding="utf-8",
        )
        print(f"[summary] captured {len(captured)} XHRs", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
