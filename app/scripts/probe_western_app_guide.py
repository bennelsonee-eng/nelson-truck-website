"""Probe westernplows.com Quick Match (snow-plow application guide).

One-off diagnostic — opens https://resources.westernplows.com/quick-match/plow/step1
with Playwright, records every network response, dumps the rendered DOM, and
lists visible <select> options.  Output lives in
``app/data/wsm_export/_western_probe/`` so the next pass can decide whether
to scrape via JSON API or by walking the UI.

Run from the repo root:
    python -m app.scripts.probe_western_app_guide
"""
from __future__ import annotations

import argparse
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
OUT_DIR = REPO_ROOT / "app" / "data" / "wsm_export" / "_western_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_URL = "https://resources.westernplows.com/quick-match/plow/step1"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--wait", type=float, default=25.0, help="seconds to settle after load")
    args = ap.parse_args()

    responses_log: list[dict] = []
    json_bodies: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
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
                print("[probe] stealth applied", flush=True)
            except Exception as e:
                print(f"[probe] stealth setup failed: {e}", flush=True)
        page = ctx.new_page()

        def on_response(resp: Response) -> None:
            url = resp.url
            entry = {
                "url": url,
                "status": resp.status,
                "method": resp.request.method,
                "content_type": (resp.headers or {}).get("content-type", ""),
            }
            responses_log.append(entry)
            ct = entry["content_type"].lower()
            if "json" in ct or url.lower().endswith(".json"):
                try:
                    body = resp.text()
                    if len(body) <= 200_000:
                        json_bodies.append({"url": url, "status": resp.status, "body": body})
                except Exception as e:
                    json_bodies.append({"url": url, "status": resp.status, "error": repr(e)})

        page.on("response", on_response)

        print(f"[probe] GET {START_URL}", flush=True)
        try:
            page.goto(START_URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"[probe] goto failed: {e}", flush=True)

        # Let JS settle and any data-bootstrap XHRs fire
        page.wait_for_timeout(int(args.wait * 1000))

        title = page.title()
        final_url = page.url
        html = page.content()
        print(f"[probe] title={title!r}  final_url={final_url}", flush=True)
        print(f"[probe] html_len={len(html)}", flush=True)

        # Dump select dropdowns visible on the page
        selects = page.evaluate(
            """() => Array.from(document.querySelectorAll('select')).map(s => ({
                name: s.name || s.id || '',
                options: Array.from(s.options).map(o => ({
                    value: o.value, label: (o.textContent || '').trim()
                }))
            }))"""
        )

        # Some quick-match wizards use button/anchor grids instead of <select>.
        # Capture all visible buttons + links that look like step choices.
        choices = page.evaluate(
            """() => {
                const out = [];
                for (const el of document.querySelectorAll('a, button, [role="button"]')) {
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
                return out.slice(0, 200);
            }"""
        )

        # Save artifacts
        (OUT_DIR / "step1.html").write_text(html, encoding="utf-8")
        try:
            page.screenshot(path=str(OUT_DIR / "step1.png"), full_page=True)
        except Exception as e:
            print(f"[probe] screenshot failed: {e}", flush=True)

        (OUT_DIR / "responses.jsonl").write_text(
            "\n".join(json.dumps(r) for r in responses_log) + "\n",
            encoding="utf-8",
        )
        (OUT_DIR / "json_bodies.jsonl").write_text(
            "\n".join(json.dumps(b) for b in json_bodies) + "\n",
            encoding="utf-8",
        )
        (OUT_DIR / "selects.json").write_text(
            json.dumps(selects, indent=2), encoding="utf-8"
        )
        (OUT_DIR / "choices.json").write_text(
            json.dumps(choices, indent=2), encoding="utf-8"
        )

        print(f"[probe] saved -> {OUT_DIR}", flush=True)
        print(f"[probe] responses={len(responses_log)}  json_bodies={len(json_bodies)}  "
              f"selects={len(selects)}  choices~={len(choices)}", flush=True)

        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
