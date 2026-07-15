"""Pick first mount/blade option on step3, advance, and dump every remaining
step until we run out.  Tells us how deep the Ematch flow is."""
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
            print("[step4] no quick-match tab", flush=True)
            return 2
        print(f"[step4] attached: {page.url}", flush=True)

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
                "response_body": body[:80_000],
            })
            print(f"[step4] XHR {resp.request.method} {resp.url.rsplit('/', 1)[-1]} "
                  f"-> {resp.status} ({len(body)}B)", flush=True)

        page.on("response", on_response)

        step_idx = 3
        max_iterations = 6  # safety
        for i in range(max_iterations):
            cur_url = page.url
            print(f"\n[step4] iter {i}  URL={cur_url}", flush=True)

            # Snapshot all radio buttons / selects currently on the page
            state = page.evaluate(
                """() => {
                    const radios = Array.from(document.querySelectorAll('input[type=radio]:not(.vehicle-type-option)'))
                        .filter(r => r.offsetParent !== null || r.checked)
                        .map(r => ({
                            name: r.name, value: r.value, label: r.getAttribute('data-value') || '',
                            checked: r.checked,
                            sku_link: (() => {
                                const link = r.closest('.ematch-product-tile')?.querySelector('a[href*="SelectedMountBladeTyleSKU"], a[value]');
                                return link ? (link.getAttribute('href') || '') + '|' + (link.getAttribute('value') || '') : '';
                            })(),
                        }));
                    const selects = Array.from(document.querySelectorAll('select.form-control'))
                        .map(s => ({
                            id: s.id, name: s.name,
                            disabled: s.disabled,
                            options: Array.from(s.options).map(o => ({value: o.value, label: o.textContent.trim()}))
                        }));
                    const nextBtn = document.querySelector('button.ematch-page-next');
                    return {radios, selects, nextDisabled: nextBtn ? nextBtn.disabled : null,
                            formAction: document.querySelector('form[action*="step"]')?.action || ''};
                }"""
            )
            print(f"[step4]   radios={len(state['radios'])} selects={len(state['selects'])}  "
                  f"nextDisabled={state['nextDisabled']}  formAction={state['formAction']}",
                  flush=True)
            for s in state["selects"]:
                non_empty = [o for o in s["options"] if o["value"]]
                if non_empty:
                    print(f"[step4]   select {s['id']} ({len(non_empty)} opts): "
                          f"{[o['value'] for o in non_empty[:3]]}", flush=True)
            for r in state["radios"][:5]:
                print(f"[step4]   radio {r['name']}={r['value']!r}  label={r['label']!r}  "
                      f"sku_link={r['sku_link']!r}  checked={r['checked']}", flush=True)

            # Save current page
            (PROBE_DIR / f"ematch_iter{i}_step{step_idx}.html").write_text(
                page.content(), encoding="utf-8"
            )
            try:
                page.screenshot(path=str(PROBE_DIR / f"ematch_iter{i}_step{step_idx}.png"),
                                full_page=True)
            except Exception:
                pass

            # Decide what to click next
            # 1. If there's a radio group, pick the first unchecked option
            picked_radio = False
            if state["radios"]:
                # Pick the first non-checked visible radio
                for r in state["radios"]:
                    if not r["checked"]:
                        sel = (f"input[type=radio][name='{r['name']}']"
                               f"[value='{r['value']}']")
                        try:
                            page.locator(sel).first.check(force=True)
                            print(f"[step4]   picked radio {r['name']}={r['value']!r}", flush=True)
                            picked_radio = True
                            page.wait_for_timeout(2500)
                            break
                        except Exception as e:
                            print(f"[step4]   radio click failed: {e}", flush=True)

            # 2. If there are disabled selects with options, fill them in order
            if not picked_radio:
                changed = False
                for s in state["selects"]:
                    if s.get("disabled"):
                        continue
                    non_empty = [o for o in s["options"] if o["value"]]
                    if not non_empty:
                        continue
                    # Check current value
                    cur = page.evaluate(
                        f"() => document.querySelector('#{s['id']}')?.value"
                    )
                    if cur:
                        continue
                    try:
                        page.select_option(f"#{s['id']}", non_empty[0]["value"])
                        print(f"[step4]   picked select #{s['id']}={non_empty[0]['value']!r}",
                              flush=True)
                        changed = True
                        page.wait_for_timeout(2500)
                        break
                    except Exception as e:
                        print(f"[step4]   select failed: {e}", flush=True)
                if changed:
                    continue

            # 3. Click Next
            if state["nextDisabled"] is False:
                try:
                    page.locator("button.ematch-page-next").first.click()
                    print(f"[step4]   clicked Next", flush=True)
                    page.wait_for_load_state("domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(4000)
                    step_idx += 1
                except Exception as e:
                    print(f"[step4]   Next click failed: {e}", flush=True)
                    break
            elif not picked_radio:
                print(f"[step4] Next is disabled and nothing else to pick — stopping", flush=True)
                break

        (PROBE_DIR / "ematch_iter_responses.jsonl").write_text(
            "\n".join(json.dumps(c) for c in captured) + "\n",
            encoding="utf-8",
        )
        print(f"\n[step4] final URL: {page.url}", flush=True)
        print(f"[step4] captured {len(captured)} XHRs", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
