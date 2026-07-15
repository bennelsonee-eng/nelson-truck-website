"""Drive ONE (Truck -> year -> make -> model -> next) round trip on the
Western Quick Match form via CDP and dump every Intershop Ematch XHR.

Output (overwrites prior):
  app/data/wsm_export/_western_probe/ematch_flow.jsonl
  app/data/wsm_export/_western_probe/ematch_step2.html
"""
from __future__ import annotations

import json
import re
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
PROBE_DIR.mkdir(parents=True, exist_ok=True)

CDP_URL = "http://localhost:9222"
TARGET_HOST = "resources.westernplows.com"


def find_target_page(browser):
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
        ctx, page = find_target_page(browser)
        if page is None:
            print("[ematch] no quick-match tab in CDP; open one first", flush=True)
            return 2
        print(f"[ematch] attached: {page.url}", flush=True)

        def on_response(resp: Response) -> None:
            url = resp.url
            if "Ematch" not in url and "ematch" not in url:
                return
            try:
                body = resp.text()
            except Exception:
                body = "(no body)"
            try:
                req_post = resp.request.post_data
            except Exception:
                req_post = None
            captured.append({
                "url": url,
                "status": resp.status,
                "method": resp.request.method,
                "post_data": req_post,
                "content_type": (resp.headers or {}).get("content-type", ""),
                "response_body": body[:60_000],
            })
            print(f"[ematch] XHR {resp.request.method} {url} -> {resp.status} "
                  f"({len(body)}B)", flush=True)

        page.on("response", on_response)

        # Make sure we're on step1; clicking Start Over guarantees reset.
        if "step1" not in page.url:
            try:
                page.goto("https://resources.westernplows.com/quick-match/plow/step1",
                          wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[ematch] goto step1 failed: {e}", flush=True)

        # 1. Click the Truck radio
        print("[ematch] clicking Truck", flush=True)
        try:
            page.locator("input.vehicle-type-option[value='Truck']").first.check(force=True)
        except Exception as e:
            print(f"[ematch] truck click failed: {e}", flush=True)
        page.wait_for_timeout(3500)

        # 2. Read year options
        years = page.evaluate(
            """() => Array.from(document.querySelectorAll('#vehicleyearoption option'))
                .map(o => ({value: o.value, label: (o.textContent || '').trim()}))
                .filter(o => o.value && o.value !== '')"""
        )
        print(f"[ematch] year options after Truck click: {len(years)}", flush=True)
        if years:
            print(f"[ematch] sample years: {[y['value'] for y in years[:5]]}", flush=True)

        if not years:
            print("[ematch] no years populated — abort", flush=True)
        else:
            # 3. Pick first year
            pick_year = years[0]["value"]
            print(f"[ematch] selecting year={pick_year}", flush=True)
            try:
                page.select_option("#vehicleyearoption", pick_year)
            except Exception as e:
                print(f"[ematch] select year failed: {e}", flush=True)
            page.wait_for_timeout(3500)

            makes = page.evaluate(
                """() => Array.from(document.querySelectorAll('#vehiclemakeoption option'))
                    .map(o => ({value: o.value, label: (o.textContent || '').trim()}))
                    .filter(o => o.value && o.value !== '')"""
            )
            print(f"[ematch] makes after year: {len(makes)}", flush=True)
            if makes:
                print(f"[ematch] sample makes: {[m['value'] for m in makes[:5]]}", flush=True)

                # 4. Pick first make
                pick_make = makes[0]["value"]
                print(f"[ematch] selecting make={pick_make}", flush=True)
                try:
                    page.select_option("#vehiclemakeoption", pick_make)
                except Exception as e:
                    print(f"[ematch] select make failed: {e}", flush=True)
                page.wait_for_timeout(3500)

                models = page.evaluate(
                    """() => Array.from(document.querySelectorAll('#vehiclemodeloption option'))
                        .map(o => ({value: o.value, label: (o.textContent || '').trim()}))
                        .filter(o => o.value && o.value !== '')"""
                )
                print(f"[ematch] models after make: {len(models)}", flush=True)
                if models:
                    print(f"[ematch] sample models: {[m['value'] for m in models[:5]]}", flush=True)

                    # 5. Pick first model
                    pick_model = models[0]["value"]
                    print(f"[ematch] selecting model={pick_model}", flush=True)
                    try:
                        page.select_option("#vehiclemodeloption", pick_model)
                    except Exception as e:
                        print(f"[ematch] select model failed: {e}", flush=True)
                    page.wait_for_timeout(3500)

                    # 6. Click Next
                    print("[ematch] clicking Next", flush=True)
                    try:
                        page.locator("button.ematch-page-next").first.click()
                    except Exception as e:
                        print(f"[ematch] next click failed: {e}", flush=True)
                    page.wait_for_load_state("domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(5000)

                    print(f"[ematch] new URL after Next: {page.url}", flush=True)
                    (PROBE_DIR / "ematch_step2.html").write_text(
                        page.content(), encoding="utf-8"
                    )
                    try:
                        page.screenshot(path=str(PROBE_DIR / "ematch_step2.png"),
                                        full_page=True)
                    except Exception:
                        pass

        # Dump everything
        (PROBE_DIR / "ematch_flow.jsonl").write_text(
            "\n".join(json.dumps(c) for c in captured) + "\n",
            encoding="utf-8",
        )
        print(f"[ematch] captured {len(captured)} XHRs -> {PROBE_DIR / 'ematch_flow.jsonl'}",
              flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
