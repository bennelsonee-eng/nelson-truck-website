"""Continue the Ematch flow from current state through to step3 (results).

Picks the first valid option for every disabled select in order until Next
becomes enabled, then clicks Next and captures step3 HTML.

Output:
  app/data/wsm_export/_western_probe/ematch_step3.html
  app/data/wsm_export/_western_probe/ematch_step3_responses.jsonl
"""
from __future__ import annotations

import json
import sys
import time
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


# Ordered list of select id's on step2.  We pick first valid value for each.
STEP2_SELECTS = [
    "#vehicledrivetrainoption",
    "#vehiclebodystyleoption",
    "#vehicledualrearwheelsoption",
    "#vehicleboxoption",
    "#vehicleengineoption",
    "#vehicleminfgawroption",
    "#vehicleminrgawroption",
    "#vehiclemingvwroption",
    "#vehicleheadlampstyleoption",
]


def main() -> int:
    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx, page = find_quick_match_tab(browser)
        if page is None:
            print("[ematch3] no quick-match tab found", flush=True)
            return 2
        print(f"[ematch3] attached: {page.url}", flush=True)

        def on_response(resp: Response) -> None:
            if "Ematch" not in resp.url and "ematch" not in resp.url:
                return
            try:
                body = resp.text()
            except Exception:
                body = "(no body)"
            captured.append({
                "url": resp.url,
                "status": resp.status,
                "method": resp.request.method,
                "post_data": getattr(resp.request, "post_data", None),
                "response_body": body[:60_000],
            })
            print(f"[ematch3] XHR {resp.request.method} {resp.url.rsplit('/', 1)[-1]} "
                  f"-> {resp.status} ({len(body)}B)", flush=True)

        page.on("response", on_response)

        # For each step2 select, pick first non-empty option
        for sel_id in STEP2_SELECTS:
            try:
                if page.locator(sel_id).count() == 0:
                    print(f"[ematch3] select {sel_id} not present, skipping", flush=True)
                    continue
                # Read available options
                opts = page.evaluate(
                    f"""() => {{
                        const sel = document.querySelector('{sel_id}');
                        if (!sel) return [];
                        return Array.from(sel.options).map(o => ({{value: o.value, label: o.textContent.trim()}}))
                            .filter(o => o.value && o.value !== '');
                    }}"""
                )
                if not opts:
                    print(f"[ematch3] {sel_id} has no options yet — waiting 3s", flush=True)
                    page.wait_for_timeout(3000)
                    opts = page.evaluate(
                        f"""() => {{
                            const sel = document.querySelector('{sel_id}');
                            if (!sel) return [];
                            return Array.from(sel.options).map(o => ({{value: o.value, label: o.textContent.trim()}}))
                                .filter(o => o.value && o.value !== '');
                        }}"""
                    )
                if not opts:
                    print(f"[ematch3] {sel_id} STILL empty — stopping refinement loop", flush=True)
                    break
                pick = opts[0]["value"]
                print(f"[ematch3] {sel_id} -> {pick!r} (of {len(opts)} options)", flush=True)
                page.select_option(sel_id, pick)
                page.wait_for_timeout(2500)
            except Exception as e:
                print(f"[ematch3] error on {sel_id}: {e}", flush=True)
                break

        # Check Next button state
        try:
            is_disabled = page.locator("button.ematch-page-next").first.is_disabled()
            print(f"[ematch3] Next disabled? {is_disabled}", flush=True)
        except Exception:
            is_disabled = True

        if not is_disabled:
            print("[ematch3] clicking Next", flush=True)
            try:
                page.locator("button.ematch-page-next").first.click()
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
                page.wait_for_timeout(5000)
            except Exception as e:
                print(f"[ematch3] next click failed: {e}", flush=True)

        print(f"[ematch3] URL now: {page.url}", flush=True)
        (PROBE_DIR / "ematch_step3.html").write_text(page.content(), encoding="utf-8")
        try:
            page.screenshot(path=str(PROBE_DIR / "ematch_step3.png"), full_page=True)
        except Exception:
            pass
        (PROBE_DIR / "ematch_step3_responses.jsonl").write_text(
            "\n".join(json.dumps(c) for c in captured) + "\n",
            encoding="utf-8",
        )
        print(f"[ematch3] captured {len(captured)} XHRs", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
