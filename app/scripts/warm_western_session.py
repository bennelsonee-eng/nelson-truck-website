"""Warm a Playwright session against resources.westernplows.com.

The Quick Match tool sits behind Incapsula + hCaptcha.  We need a human to
solve the captcha once; after that the cookies + Incapsula session token
let an unattended walker hit every YMM combo.

This script:
  1. Opens a HEADED Chromium with stealth applied.
  2. Navigates to the Quick Match step1.
  3. Polls the DOM every 2s for signs the challenge is cleared (real form
     visible, no Incapsula iframe, page title set).
  4. Once cleared, captures the rendered HTML + a network log + a screenshot
     so the next pass can see exactly how the form is structured / what
     XHR endpoint to call.
  5. Saves storage_state.json so the walker can re-use the session.

Run from the repo root:
    python -m app.scripts.warm_western_session

User action: solve the hCaptcha in the window when prompted, then leave the
window open.  The script saves and closes itself automatically.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import Response, sync_playwright

try:
    from playwright_stealth import Stealth  # type: ignore
except Exception:  # noqa: BLE001
    Stealth = None  # type: ignore

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROBE_DIR = REPO_ROOT / "app" / "data" / "wsm_export" / "_western_probe"
PROBE_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_STATE = PROBE_DIR / "storage_state.json"

START_URL = "https://resources.westernplows.com/quick-match/plow/step1"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Heuristic: the Incapsula challenge body is ~900 bytes.  Once cleared the
# real Quick Match page is many KB.  We also look for absence of the
# Incapsula iframe and presence of clickable choices.
CLEARED_MIN_LEN = 4000
MAX_WAIT_SEC = 600  # 10 minutes for the human to solve


def is_cleared(page) -> tuple[bool, dict]:
    try:
        html = page.content()
    except Exception:
        return False, {"err": "no_content"}
    length = len(html)
    has_incap_iframe = "Incapsula_Resource" in html or "main-iframe" in html
    title = page.title() or ""
    # Try a few markers: any <select>, any data-step-* attribute, any
    # button/link with year-like text.
    try:
        marker_count = page.evaluate(
            """() => {
                const selects = document.querySelectorAll('select').length;
                const dataSteps = document.querySelectorAll('[data-step], [class*="step"], [class*="Step"]').length;
                const yearButtons = Array.from(document.querySelectorAll('a,button'))
                    .filter(e => /^(19|20)\\d{2}$/.test((e.textContent || '').trim())).length;
                return {selects, dataSteps, yearButtons};
            }"""
        )
    except Exception:
        marker_count = {"selects": 0, "dataSteps": 0, "yearButtons": 0}

    snapshot = {
        "length": length,
        "has_incap_iframe": has_incap_iframe,
        "title": title,
        **marker_count,
    }
    cleared = (
        not has_incap_iframe
        and length >= CLEARED_MIN_LEN
        and (marker_count["selects"] > 0
             or marker_count["dataSteps"] > 0
             or marker_count["yearButtons"] > 0)
    )
    return cleared, snapshot


def main() -> int:
    responses_log: list[dict] = []
    json_bodies: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        if Stealth is not None:
            try:
                Stealth().apply_stealth_sync(ctx)
                print("[warm] stealth applied", flush=True)
            except Exception as e:
                print(f"[warm] stealth setup failed: {e}", flush=True)
        page = ctx.new_page()

        def on_response(resp: Response) -> None:
            entry = {
                "url": resp.url,
                "status": resp.status,
                "method": resp.request.method,
                "content_type": (resp.headers or {}).get("content-type", ""),
            }
            responses_log.append(entry)
            ct = entry["content_type"].lower()
            host = resp.url.split("/", 3)[2] if "://" in resp.url else ""
            # Only capture JSON bodies from Western itself — skip hCaptcha / sitelock noise
            if ("westernplows.com" in host or "douglas-dynamics" in host) and "json" in ct:
                try:
                    body = resp.text()
                    if len(body) <= 500_000:
                        json_bodies.append({"url": resp.url, "status": resp.status, "body": body})
                except Exception as e:
                    json_bodies.append({"url": resp.url, "status": resp.status, "error": repr(e)})

        page.on("response", on_response)

        print(f"[warm] opening {START_URL}", flush=True)
        try:
            page.goto(START_URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"[warm] goto failed: {e}", flush=True)

        print("[warm] ============================================================", flush=True)
        print("[warm]  Solve the hCaptcha in the browser window.", flush=True)
        print("[warm]  When the Quick Match form appears, leave the window open;", flush=True)
        print("[warm]  this script will detect it and exit on its own.", flush=True)
        print("[warm] ============================================================", flush=True)

        start = time.time()
        last_print = 0.0
        while True:
            elapsed = time.time() - start
            if elapsed > MAX_WAIT_SEC:
                print(f"[warm] timeout after {MAX_WAIT_SEC}s", flush=True)
                break

            cleared, snap = is_cleared(page)
            if elapsed - last_print > 10:
                print(f"[warm] t={int(elapsed)}s  cleared={cleared}  {snap}", flush=True)
                last_print = elapsed
            if cleared:
                print(f"[warm] CLEARED at t={int(elapsed)}s  {snap}", flush=True)
                # Give any post-clear XHRs a moment to finish.
                page.wait_for_timeout(3000)
                break
            page.wait_for_timeout(2000)

        # Capture artifacts
        try:
            html = page.content()
        except Exception:
            html = ""
        (PROBE_DIR / "step1_cleared.html").write_text(html, encoding="utf-8")
        try:
            page.screenshot(path=str(PROBE_DIR / "step1_cleared.png"), full_page=True)
        except Exception as e:
            print(f"[warm] screenshot failed: {e}", flush=True)
        (PROBE_DIR / "responses_cleared.jsonl").write_text(
            "\n".join(json.dumps(r) for r in responses_log) + "\n",
            encoding="utf-8",
        )
        (PROBE_DIR / "json_bodies_cleared.jsonl").write_text(
            "\n".join(json.dumps(b) for b in json_bodies) + "\n",
            encoding="utf-8",
        )

        # Also dump visible <select>s and clickable step choices for the next pass.
        try:
            selects = page.evaluate(
                """() => Array.from(document.querySelectorAll('select')).map(s => ({
                    name: s.name || s.id || '',
                    options: Array.from(s.options).map(o => ({
                        value: o.value, label: (o.textContent || '').trim()
                    }))
                }))"""
            )
        except Exception:
            selects = []
        try:
            choices = page.evaluate(
                """() => {
                    const out = [];
                    for (const el of document.querySelectorAll('a, button, [role="button"], .step-option, .option')) {
                        const txt = (el.textContent || '').trim();
                        if (txt && txt.length < 60) {
                            out.push({
                                tag: el.tagName,
                                text: txt,
                                href: el.getAttribute('href') || '',
                                classes: el.className || '',
                            });
                        }
                    }
                    return out.slice(0, 300);
                }"""
            )
        except Exception:
            choices = []
        (PROBE_DIR / "selects_cleared.json").write_text(
            json.dumps(selects, indent=2), encoding="utf-8"
        )
        (PROBE_DIR / "choices_cleared.json").write_text(
            json.dumps(choices, indent=2), encoding="utf-8"
        )

        # Save storage state for the unattended walker
        try:
            ctx.storage_state(path=str(STORAGE_STATE))
            print(f"[warm] storage_state saved -> {STORAGE_STATE}", flush=True)
        except Exception as e:
            print(f"[warm] storage_state save failed: {e}", flush=True)

        print(f"[warm] artifacts -> {PROBE_DIR}", flush=True)
        print(f"[warm] responses={len(responses_log)}  json_bodies={len(json_bodies)}  "
              f"selects={len(selects)}  choices~={len(choices)}", flush=True)
        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
