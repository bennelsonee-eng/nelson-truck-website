"""Walk Western Quick Match for Truck × {anchor years} × all makes × all models
× every mount/blade × LED + Halogen.  Saves raw summary HTML + per-combo
metadata for later parsing.

Pre-req: chrome.exe running with --remote-debugging-port=9222 and the user
has solved the hCaptcha once on resources.westernplows.com/quick-match/plow/step1
(see warm_western_session_cdp.py).

Run from repo root:
    python -m app.scripts.scrape_western_app_guide
    python -m app.scripts.scrape_western_app_guide --years 2026
    python -m app.scripts.scrape_western_app_guide --resume

Output:
  app/data/wsm_export/_western_summaries/<year>_<make>_<model>__<mount>__<headlamp>.html
  app/data/wsm_export/western_app_guide_raw.jsonl  (one JSON per combo, appended)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import Response, sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_ROOT = REPO_ROOT / "app" / "data" / "wsm_export"
SUMMARIES_DIR = OUT_ROOT / "_western_summaries"
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
RAW_JSONL = OUT_ROOT / "western_app_guide_raw.jsonl"
LOG_PATH = OUT_ROOT / "western_walker.log"

CDP_PORT = 9222  # default; overridden by --cdp-port
CDP_URL = f"http://localhost:{CDP_PORT}"

# Refinement selects on step2 in order
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


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def safe_slug(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-").strip(".")
    return s[:maxlen]


def find_quick_match_tab(browser):
    for ctx in browser.contexts:
        for pg in ctx.pages:
            try:
                if "quick-match/plow" in (pg.url or ""):
                    return ctx, pg
            except Exception:
                continue
    return None, None


def ensure_quick_match_tab(browser):
    ctx, pg = find_quick_match_tab(browser)
    if pg is not None:
        return ctx, pg
    # No tab on quick-match — open one in the first context
    if not browser.contexts:
        return None, None
    ctx = browser.contexts[0]
    pg = ctx.new_page()
    pg.goto("https://resources.westernplows.com/quick-match/plow/step1",
            wait_until="domcontentloaded", timeout=60_000)
    pg.wait_for_timeout(2500)
    return ctx, pg


def is_captcha_walled(page) -> bool:
    try:
        title = page.title() or ""
        if "Incapsula" in title:
            return True
        html = page.content()
        return ("Incapsula_Resource" in html or
                "main-iframe" in html or
                "hcaptcha" in html.lower() and len(html) < 5000)
    except Exception:
        return False


def start_over(page) -> bool:
    """Click Start Over and return to step1 with empty form."""
    try:
        page.goto("https://resources.westernplows.com/quick-match/plow/step1",
                  wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)
        # If Start Over button is present, click it for good measure
        try:
            so = page.locator("a[data-dialog-href*='ViewEmatch-StartOver'], "
                              "button[data-dialog-action*='ViewEmatch-StartOver']").first
            if so.count() > 0:
                so.click()
                page.wait_for_timeout(1500)
                # Confirmation dialog might appear — click OK if present
                try:
                    page.locator("button:has-text('Ok'), button:has-text('OK'), "
                                 "button:has-text('Yes')").first.click(timeout=3000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
        except Exception:
            pass
        # Re-navigate to step1 to be sure
        page.goto("https://resources.westernplows.com/quick-match/plow/step1",
                  wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2000)
        return not is_captcha_walled(page)
    except Exception as e:
        log(f"  start_over failed: {e}")
        return False


def pick_vehicle_type(page, value: str) -> bool:
    try:
        page.locator(f"input.vehicle-type-option[value='{value}']").first.check(force=True)
        page.wait_for_timeout(2800)
        return True
    except Exception as e:
        log(f"  pick_vehicle_type({value}) failed: {e}")
        return False


def select_options(page, select_id: str) -> list[dict]:
    """Return list of non-empty options on a select. Empty list if select missing or no options."""
    try:
        return page.evaluate(
            f"""() => {{
                const s = document.querySelector('{select_id}');
                if (!s) return [];
                return Array.from(s.options)
                    .map(o => ({{value: o.value, label: (o.textContent || '').trim()}}))
                    .filter(o => o.value);
            }}"""
        )
    except Exception:
        return []


def select_pick(page, select_id: str, value: str, wait_ms: int = 2500) -> bool:
    try:
        page.select_option(select_id, value)
        page.wait_for_timeout(wait_ms)
        return True
    except Exception as e:
        log(f"  select_pick({select_id}={value!r}) failed: {e}")
        return False


def click_next_button(page, timeout_ms: int = 30_000) -> bool:
    """Click the active Next control — may be <button>, <a class=ematch-page-next>,
    or <a class=ematch-page-next id=plow-opt-next data-href=...>."""
    # Look for an enabled button first
    try:
        b = page.locator("button.ematch-page-next:not([disabled])").first
        if b.count() > 0 and b.is_visible():
            b.click()
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3000)
            return True
    except Exception:
        pass
    # Anchor with data-href
    try:
        a = page.locator("a.ematch-page-next").first
        if a.count() > 0 and a.is_visible():
            href = a.get_attribute("data-href") or a.get_attribute("href")
            if href:
                page.goto(href, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(3000)
                return True
            a.click()
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3000)
            return True
    except Exception:
        pass
    return False


def fill_step2_defaults(page) -> dict:
    """Pick first non-empty option for each step2 refinement select.  Return a dict
    of {select_id: chosen_value} so we can record what was selected."""
    chosen: dict[str, str] = {}
    for sel_id in STEP2_SELECTS:
        # Wait briefly for the select to populate (may be loading from AJAX)
        opts: list[dict] = []
        for _ in range(3):
            opts = select_options(page, sel_id)
            if opts:
                break
            page.wait_for_timeout(1500)
        if not opts:
            continue
        # If a value is already selected, leave it
        cur = page.evaluate(f"() => document.querySelector('{sel_id}')?.value")
        if cur:
            chosen[sel_id] = cur
            continue
        if not select_pick(page, sel_id, opts[0]["value"]):
            continue
        chosen[sel_id] = opts[0]["value"]
    return chosen


def get_step3_mount_blade_options(page) -> list[dict]:
    """Return mount/blade radio options visible on step3."""
    try:
        return page.evaluate(
            """() => Array.from(document.querySelectorAll(
                "input[type=radio][name='mountbladegridview']"
            )).map(r => ({
                value: r.value,
                data_value: r.getAttribute('data-value') || '',
                sku: (() => {
                    const link = r.closest('.ematch-product-tile')?.querySelector('a[value]');
                    return link?.getAttribute('value') || '';
                })(),
            }))"""
        )
    except Exception:
        return []


def get_step4_headlamp_options(page) -> list[str]:
    """Return headlamp values present on step4."""
    try:
        return page.evaluate(
            """() => Array.from(document.querySelectorAll(
                "input[type=radio][name='VehiclePlowHeadLampType']"
            )).map(r => r.value)"""
        )
    except Exception:
        return []


def pick_radio_by_value(page, name: str, value: str, wait_ms: int = 2500) -> bool:
    try:
        page.locator(f"input[type=radio][name='{name}'][value='{value}']").first.check(force=True)
        page.wait_for_timeout(wait_ms)
        return True
    except Exception as e:
        log(f"  radio {name}={value!r} failed: {e}")
        return False


def goto_summary(page) -> bool:
    try:
        page.goto("https://resources.westernplows.com/quick-match/plow/summary",
                  wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4000)
        return "/summary" in page.url
    except Exception as e:
        log(f"  goto_summary failed: {e}")
        return False


def load_done_set() -> set[str]:
    """Read existing RAW_JSONL and return set of combo keys already saved (for resume)."""
    done: set[str] = set()
    if RAW_JSONL.exists():
        for line in RAW_JSONL.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                done.add(d["key"])
            except Exception:
                continue
    return done


def append_combo(combo: dict) -> None:
    with RAW_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(combo) + "\n")


def walk_one_ymm(page, year: int, make: str, model: str, done: set[str],
                 max_mount_blade: int = 99, max_headlamp: int = 99) -> int:
    """Drive form for one YMM, walking every mount/blade × headlamp combo.
    Returns count of successful summary captures."""
    captured = 0

    # 0. Reset
    if not start_over(page):
        log(f"  ! start_over failed for {year}/{make}/{model}")
        return 0

    # 1. Truck → Year → Make → Model
    if not pick_vehicle_type(page, "Truck"):
        return 0
    if not select_pick(page, "#vehicleyearoption", str(year), wait_ms=2800):
        return 0
    if not select_pick(page, "#vehiclemakeoption", make, wait_ms=2800):
        # Make may not be available for this year — that's fine, skip
        log(f"  -- make {make!r} not available for {year}")
        return 0
    if not select_pick(page, "#vehiclemodeloption", model, wait_ms=2800):
        log(f"  -- model {model!r} not available")
        return 0
    if not click_next_button(page):
        log(f"  ! couldn't advance past step1 for {year}/{make}/{model}")
        return 0

    # 2. Step2 defaults
    step2_chosen = fill_step2_defaults(page)
    if not click_next_button(page):
        log(f"  ! couldn't advance past step2 for {year}/{make}/{model}")
        return 0

    # 3. Step3: enumerate mount/blade options
    mb_opts = get_step3_mount_blade_options(page)
    if not mb_opts:
        log(f"  -- no mount/blade for {year}/{make}/{model} (no application)")
        return 0
    log(f"     step3 mount/blade options: {len(mb_opts)}")

    for mb_idx, mb in enumerate(mb_opts[:max_mount_blade]):
        # Pick the mount/blade radio
        if not pick_radio_by_value(page, "mountbladegridview", mb["value"]):
            continue
        if not click_next_button(page):
            log(f"  ! couldn't advance past step3 for mb={mb}")
            continue

        # 4. Step4: enumerate headlamp options
        # First make sure a control type is selected (defaults to first)
        try:
            page.locator(
                "input[type=radio][name='VehicleControlType']"
            ).first.check(force=True)
            page.wait_for_timeout(2500)
        except Exception:
            pass

        hl_opts = get_step4_headlamp_options(page)
        # Fallback if structure differs — just attempt 'LED' and 'Halogen'
        if not hl_opts:
            hl_opts = ["LED", "Halogen"]
        log(f"     step4 headlamp options for mb#{mb_idx}: {hl_opts}")

        for hl_idx, hl in enumerate(hl_opts[:max_headlamp]):
            key = f"{year}|{make}|{model}|mb={mb['sku'] or mb['value']}|hl={hl}"
            if key in done:
                continue

            if not pick_radio_by_value(page, "VehiclePlowHeadLampType", hl):
                continue

            # 5. /summary
            if not goto_summary(page):
                log(f"  ! summary nav failed for {key}")
                continue

            html = page.content()
            if "/summary" not in page.url or len(html) < 5000:
                log(f"  ! summary too short ({len(html)}B) for {key}")
                continue

            fname = (
                f"{year}__{safe_slug(make)}__{safe_slug(model)}__"
                f"mb-{safe_slug(mb['sku'] or mb['value'])}__hl-{safe_slug(hl)}.html"
            )
            (SUMMARIES_DIR / fname).write_text(html, encoding="utf-8")
            combo = {
                "key": key,
                "year": year,
                "make": make,
                "model": model,
                "step2_refinements": step2_chosen,
                "mount_blade": mb,
                "headlamp_type": hl,
                "summary_html_path": str(
                    (SUMMARIES_DIR / fname).relative_to(REPO_ROOT)
                ).replace("\\", "/"),
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            append_combo(combo)
            done.add(key)
            captured += 1
            log(f"     OK [{captured}] {key}")

            # Go back to step3/step4 boundary for next headlamp/mb variant.
            # Easiest: navigate to step4 (state preserves selections).
            try:
                page.goto("https://resources.westernplows.com/quick-match/plow/step4",
                          wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2500)
            except Exception:
                pass

        # After done with this mount/blade's headlamps, go back to step3 to pick next mb
        if mb_idx + 1 < len(mb_opts):
            try:
                page.goto("https://resources.westernplows.com/quick-match/plow/step3",
                          wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2500)
            except Exception:
                pass

    return captured


def enumerate_makes_models(page, year: int) -> list[tuple[str, str]]:
    """For a given year, enumerate every (make, model) pair by walking the
    Quick Match selects.  Pure enumeration — no advance past step1."""
    pairs: list[tuple[str, str]] = []

    if not start_over(page):
        return []
    if not pick_vehicle_type(page, "Truck"):
        return []
    if not select_pick(page, "#vehicleyearoption", str(year), wait_ms=2800):
        return []

    makes = select_options(page, "#vehiclemakeoption")
    log(f"  year {year}: {len(makes)} makes")
    for make in makes:
        if not select_pick(page, "#vehiclemakeoption", make["value"], wait_ms=2500):
            continue
        models = select_options(page, "#vehiclemodeloption")
        for model in models:
            pairs.append((make["value"], model["value"]))
    return pairs


def main() -> int:
    global CDP_PORT, CDP_URL, LOG_PATH

    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2026,2018,2010",
                    help="Comma-separated anchor years")
    ap.add_argument("--makes", default="",
                    help="If set, restrict to these makes (comma-separated)")
    ap.add_argument("--limit", type=int, default=0,
                    help="If >0, stop after this many YMMs (debug)")
    ap.add_argument("--resume", action="store_true",
                    help="Skip combos already in western_app_guide_raw.jsonl")
    ap.add_argument("--max-mount-blade", type=int, default=99,
                    help="Cap mount/blade options walked per YMM")
    ap.add_argument("--max-headlamp", type=int, default=99,
                    help="Cap headlamp options walked per mount/blade")
    ap.add_argument("--cdp-port", type=int, default=9222,
                    help="Chrome remote-debugging port (default 9222)")
    args = ap.parse_args()

    # Configure CDP for this instance
    CDP_PORT = args.cdp_port
    CDP_URL = f"http://localhost:{CDP_PORT}"
    if CDP_PORT != 9222:
        LOG_PATH = OUT_ROOT / f"western_walker_{CDP_PORT}.log"

    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    make_filter = {m.strip().upper() for m in args.makes.split(",") if m.strip()}

    done = load_done_set() if args.resume else set()
    log(f"=== walker start years={years} cdp_port={CDP_PORT} resume_skipping={len(done)} ===")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx, page = ensure_quick_match_tab(browser)
        if page is None:
            log("FATAL: no CDP context")
            return 2

        if is_captcha_walled(page):
            log("FATAL: hCaptcha challenge is active.  Solve it in Chrome first.")
            return 3

        ymm_count = 0
        for year in years:
            try:
                pairs = enumerate_makes_models(page, year)
            except Exception as e:
                log(f"! enum failed for {year}: {e}\n{traceback.format_exc()}")
                continue
            log(f"  year {year}: {len(pairs)} (make,model) pairs")

            for make, model in pairs:
                if make_filter and make.upper() not in make_filter:
                    continue
                ymm_count += 1
                if args.limit and ymm_count > args.limit:
                    log(f"  hit --limit={args.limit}; stopping")
                    return 0

                log(f"YMM {ymm_count}: {year}/{make}/{model}")
                try:
                    captured = walk_one_ymm(
                        page, year, make, model, done,
                        max_mount_blade=args.max_mount_blade,
                        max_headlamp=args.max_headlamp,
                    )
                    log(f"  -> captured {captured} combos for {year}/{make}/{model}")
                except Exception as e:
                    log(f"! walk_one_ymm crashed: {e}\n{traceback.format_exc()}")
                    # Try to reset and continue
                    try:
                        start_over(page)
                    except Exception:
                        pass

                if is_captcha_walled(page):
                    log("!! captcha challenge resurfaced — pausing.  "
                        "Solve in Chrome and re-run with --resume.")
                    return 4

    log(f"=== walker complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
