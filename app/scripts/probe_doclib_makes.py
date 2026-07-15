"""Probe the Western doc-library to find the real make-filter values."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

OUT_DIR = Path(r"C:\Users\Ben\titan truck website\app\data\wsm_export\_western_probe")
OUT_DIR.mkdir(parents=True, exist_ok=True)
URL = "https://westernplows.com/document-library/search-results/?nhfzznev2izjx8qf6ubr=mpn8gmudl5hcb1yrclgk&LitLanguage=EN"


def main() -> int:
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = b.contexts[0]
        pg = ctx.new_page()
        pg.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        pg.wait_for_timeout(7000)

        # Click any button with "Vehicle Make" text to open the dropdown
        try:
            pg.locator("button:has-text('Vehicle Make')").first.click()
            pg.wait_for_timeout(1500)
        except Exception as e:
            print(f"click failed: {e}")

        pg.screenshot(path=str(OUT_DIR / "doclib_make_opened.png"), full_page=True)
        html = pg.content()
        (OUT_DIR / "doclib_full.html").write_text(html, encoding="utf-8")

        # Now inspect the open dropdown for make values.
        info = pg.evaluate(
            """() => {
                const result = {open_dropdowns: [], all_link_makes: [], all_data_attrs: []};
                // Bootstrap-select renders dropdowns as ul.dropdown-menu with li>a items
                for (const ul of document.querySelectorAll('ul.dropdown-menu')) {
                    if (ul.offsetParent !== null) {
                        const items = Array.from(ul.querySelectorAll('li')).map(li => ({
                            text: (li.textContent || '').trim(),
                            value: li.getAttribute('data-original-index') || '',
                            data: Object.fromEntries(Array.from(li.attributes||[])
                                .filter(a => a.name.startsWith('data-'))
                                .map(a => [a.name, a.value]))
                        }));
                        result.open_dropdowns.push({class: ul.className, items: items.slice(0, 60)});
                    }
                }
                // Many filter UIs store options in hidden <option> tags inside the original <select>
                for (const s of document.querySelectorAll('select[name*="VehicleMake" i], select[id*="VehicleMake" i], select[name*="LitVehicleMake" i]')) {
                    const items = Array.from(s.options)
                        .map(o => ({value: o.value, text: (o.textContent || '').trim()}))
                        .filter(o => o.value);
                    result.open_dropdowns.push({selectName: s.name || s.id, items});
                }
                // As fallback list every data-value attribute that looks like a make
                for (const el of document.querySelectorAll('[data-value],[data-make],[data-tokens]')) {
                    const v = el.getAttribute('data-value') || el.getAttribute('data-make') || el.getAttribute('data-tokens');
                    if (v && v.length < 40 && /^[A-Za-z]/.test(v)) result.all_data_attrs.push(v);
                }
                return result;
            }"""
        )
        print(json.dumps(info, indent=2))
        pg.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
