"""Quick HTML grid showing all v3 (0deg) + v4 (target 20deg) renders side by side."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1].parent
V3 = REPO / "wan_test_output" / "flux_truck_15deg_v3"
V4 = REPO / "wan_test_output" / "flux_truck_20deg_v4"
OUT = REPO / "wan_test_output" / "_v3_v4_compare.html"

CLASSES = ["mid-size", "1500", "2500", "3500", "4500", "5500"]
SEEDS = [1337, 8888, 4242, 2026, 17171]


def main() -> int:
    rows = ""
    for cls in CLASSES:
        v3_imgs = "".join(
            f'<img src="flux_truck_15deg_v3/{cls}_seed{s}.png" alt="v3 {cls} {s}" title="v3 seed{s}">'
            for s in SEEDS
        )
        v4_imgs = "".join(
            f'<img src="flux_truck_20deg_v4/{cls}_seed{s}.png" alt="v4 {cls} {s}" title="v4 seed{s}">'
            for s in SEEDS
        )
        rows += f"""
<section><h2>{cls}</h2>
  <div class="row"><span class="label">v3 (target 0)</span>{v3_imgs}</div>
  <div class="row"><span class="label">v4 (target 20)</span>{v4_imgs}</div>
</section>
"""
    OUT.write_text(
        f"""<!doctype html><html><head><meta charset="utf-8">
<title>v3 vs v4 truck renders</title>
<style>
  body {{ margin:0; font-family:-apple-system,system-ui,sans-serif;
          background:#1f2937; color:#fff; padding:14px; }}
  h2 {{ margin:14px 0 6px 0; font-size:14px; color:#10b981; }}
  .row {{ display:flex; gap:6px; margin-bottom:6px; align-items:center; }}
  .label {{ font-size:11px; color:#9ca3af; min-width:120px;
            font-family:ui-monospace,Consolas,monospace; }}
  .row img {{ flex:1; min-width:0; height:120px; object-fit:cover; border-radius:3px; }}
</style></head><body>
<h1 style="margin:0;font-size:16px;">v3 head-on attempt (0deg) vs v4 angled attempt (20deg target)</h1>
<p style="margin:4px 0 0 0;color:#9ca3af;font-size:12px;">
Looking for any seed that landed in the 15-25 degree sweet spot to match the plow angle.
</p>
{rows}
</body></html>""",
        encoding="utf-8",
    )
    print(f"open: file:///{OUT.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
