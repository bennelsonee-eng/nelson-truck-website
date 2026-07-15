"""Attach to a user-launched Chrome over CDP and capture the Quick Match form.

Why CDP attach instead of Playwright-spawned browser?  Claude Code's shell
tool on this machine can't spawn a headed Chromium ("BrowserType.launch:
spawn UNKNOWN" on Windows — desktop-session issue).  Connecting to a
Chrome that the user launched themselves bypasses that entirely.

User flow:
  1. Run scripts\open_western_debug_chrome.bat  (launches Chrome with
     --remote-debugging-port=9222 and a dedicated user-data-dir)
  2. In that Chrome window, navigate to
       https://resources.westernplows.com/quick-match/plow/step1
     and solve the hCaptcha.
  3. Leave the window open and run this script:
       python -m app.scripts.warm_western_session_cdp
  4. We attach, listen to network responses, capture the rendered DOM,
     enumerate dropdown options, and save storage_state.

Output: same as warm_western_session.py — artifacts under
app/data/wsm_export/_western_probe/.
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
PROBE_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_STATE = PROBE_DIR / "storage_state.json"

CDP_URL = "http://localhost:9222"
TARGET_HOST = "resources.westernplows.com"


def find_target_page(browser):
    """Return the page that's already on resources.westernplows.com, or None."""
    for ctx in browser.contexts:
        for pg in ctx.pages:
            try:
                if TARGET_HOST in (pg.url or ""):
                    return ctx, pg
            except Exception:
                continue
    return None, None


def main() -> int:
    with sync_playwright() as p:
        print(f"[warm-cdp] connecting to {CDP_URL}", flush=True)
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx, page = find_target_page(browser)
        if page is None:
            print(f"[warm-cdp] no tab found on {TARGET_HOST}.  "
                  f"Open https://resources.westernplows.com/quick-match/plow/step1 "
                  f"in the debug Chrome window and rerun.", flush=True)
            # Fallback: just list what tabs we did see
            for c in browser.contexts:
                for pg in c.pages:
                    print(f"[warm-cdp]   tab: {pg.url}", flush=True)
            return 2

        print(f"[warm-cdp] attached to tab: {page.url}", flush=True)

        # Wire up network capture *after* attach.  We won't see history,
        # but any further navigation / XHR will be logged.
        responses_log: list[dict] = []
        json_bodies: list[dict] = []

        def on_response(resp: Response) -> None:
            entry = {
                "url": resp.url,
                "status": resp.status,
                "method": resp.request.method,
                "content_type": (resp.headers or {}).get("content-type", ""),
            }
            responses_log.append(entry)
            host = resp.url.split("/", 3)[2] if "://" in resp.url else ""
            ct = entry["content_type"].lower()
            if ("westernplows.com" in host or "douglas-dynamics" in host) and "json" in ct:
                try:
                    body = resp.text()
                    if len(body) <= 500_000:
                        json_bodies.append({"url": resp.url, "status": resp.status, "body": body})
                except Exception as e:
                    json_bodies.append({"url": resp.url, "status": resp.status, "error": repr(e)})

        page.on("response", on_response)

        # Reload to capture the bootstrap XHRs.  We're past the captcha so
        # the session cookie carries us straight to the real form.
        print("[warm-cdp] reloading to capture bootstrap network traffic", flush=True)
        try:
            page.reload(wait_until="networkidle", timeout=60_000)
        except Exception as e:
            print(f"[warm-cdp] reload note: {e}", flush=True)
        # belt + suspenders settle
        page.wait_for_timeout(3000)

        html = page.content()
        title = page.title()
        url = page.url
        print(f"[warm-cdp] title={title!r} url={url} html_len={len(html)}", flush=True)

        if "Incapsula_Resource" in html or "main-iframe" in html:
            print("[warm-cdp] WARNING: page still shows Incapsula iframe.  "
                  "Solve the hCaptcha in the browser tab and rerun.", flush=True)

        # Enumerate selects and clickable choices
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
                    for (const el of document.querySelectorAll('a, button, [role="button"], .step-option, .option, .choice, li')) {
                        const txt = (el.textContent || '').trim();
                        if (txt && txt.length < 80) {
                            out.push({
                                tag: el.tagName,
                                text: txt,
                                href: el.getAttribute('href') || '',
                                classes: (el.className && typeof el.className === 'string') ? el.className : '',
                                dataAttrs: Object.fromEntries(
                                    Array.from(el.attributes || [])
                                        .filter(a => a.name.startsWith('data-'))
                                        .map(a => [a.name, a.value])
                                ),
                            });
                        }
                    }
                    return out.slice(0, 500);
                }"""
            )
        except Exception:
            choices = []

        (PROBE_DIR / "step1_cleared.html").write_text(html, encoding="utf-8")
        try:
            page.screenshot(path=str(PROBE_DIR / "step1_cleared.png"), full_page=True)
        except Exception as e:
            print(f"[warm-cdp] screenshot failed: {e}", flush=True)
        (PROBE_DIR / "responses_cleared.jsonl").write_text(
            "\n".join(json.dumps(r) for r in responses_log) + "\n",
            encoding="utf-8",
        )
        (PROBE_DIR / "json_bodies_cleared.jsonl").write_text(
            "\n".join(json.dumps(b) for b in json_bodies) + "\n",
            encoding="utf-8",
        )
        (PROBE_DIR / "selects_cleared.json").write_text(
            json.dumps(selects, indent=2), encoding="utf-8"
        )
        (PROBE_DIR / "choices_cleared.json").write_text(
            json.dumps(choices, indent=2), encoding="utf-8"
        )

        # Save storage state from the attached context so an unattended
        # walker (if we ever solve the spawn issue) can re-use the session.
        try:
            ctx.storage_state(path=str(STORAGE_STATE))
            print(f"[warm-cdp] storage_state saved -> {STORAGE_STATE}", flush=True)
        except Exception as e:
            print(f"[warm-cdp] storage_state save failed: {e}", flush=True)

        print(f"[warm-cdp] artifacts -> {PROBE_DIR}", flush=True)
        print(f"[warm-cdp] responses={len(responses_log)}  json_bodies={len(json_bodies)}  "
              f"selects={len(selects)}  choices~={len(choices)}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
