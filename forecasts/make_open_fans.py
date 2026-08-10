#!/usr/bin/env python3
"""Render the open-round unemployment fan on the forecasts page.

Run:  python3 forecasts/make_open_fans.py          # rewrite forecasts/index.html
      python3 forecasts/make_open_fans.py --check  # exit 1 if the page is stale

Same contract as forecasts/score.py and validation/figures/make_charts.py: the
page is committed, the figure between the ``open-fan-unemployment`` markers is
generated from the committed round artifact, and --check fails if they drift
apart. GDP and CPI fans for the open boe-svar round are rendered by
forecasts/score.py (the model-vs-official block); this script covers the
svar-unemployment satellite's round, which has no official path to overlay.
The archived round artifact keeps its original filename.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
ROUNDS = HERE / "rounds"
PAGE = HERE / "index.html"

MARKER = "open-fan-unemployment"
CHART_ID = "open-unemployment-fan"


def _latest_round() -> Path:
    candidates = sorted(
        p
        for p in ROUNDS.glob("*/okun-unemployment.json")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.parent.name)
    )
    if not candidates:
        raise SystemExit("no rounds/<date>/okun-unemployment.json artifact found")
    return candidates[-1]


def render() -> str:
    """Fan chart of the archived unemployment medians with 68/90% bands."""
    src = _latest_round()
    rnd = json.loads(src.read_text())
    rows = [
        {"period": period, **block["unemployment"]}
        for period, block in sorted(rnd["forecast"].items())
        if "unemployment" in block
    ]
    if len(rows) < 2:
        return "      <!-- fewer than two forecast periods -->"

    # SVG geometry mirrors the validation-page vchart conventions.
    width, height = 760, 300
    left, right, top, bottom = 56, 16, 34, 40
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [v for r in rows for v in (r["lo90"], r["hi90"])]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    lo -= span * 0.15
    hi += span * 0.15
    span = hi - lo

    def x(i: int) -> float:
        return left + plot_w * i / (len(rows) - 1)

    def y(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / span)

    def band(lo_key: str, hi_key: str) -> str:
        pts = " ".join(f"{x(i):.1f},{y(r[hi_key]):.1f}" for i, r in enumerate(rows))
        return pts + " " + " ".join(
            f"{x(i):.1f},{y(r[lo_key]):.1f}"
            for i, r in reversed(list(enumerate(rows)))
        )

    median = " ".join(f"{x(i):.1f},{y(r['median']):.1f}" for i, r in enumerate(rows))

    gridlines, ticks = [], []
    step = 0.1 if span > 0.45 else 0.05
    v = round(lo / step) * step
    while v <= hi:
        if v >= lo:
            gridlines.append(
                f'          <line class="vc-grid" x1="{left}" y1="{y(v):.1f}" '
                f'x2="{width - right}" y2="{y(v):.1f}"/>'
            )
            ticks.append(
                f'          <text class="vc-tick" x="{left - 8}" y="{y(v) + 4:.1f}" '
                f'text-anchor="end">{v:.2f}</text>'
            )
        v += step
    xticks = [
        f'          <text class="vc-tick" x="{x(i):.1f}" y="{height - 14}" '
        f'text-anchor="middle">{r["period"]}</text>'
        for i, r in enumerate(rows)
    ]

    desc = (
        f"Fan chart of the UK unemployment rate, percent, from the "
        f"svar-unemployment satellite round of {src.parent.name}: the archived median "
        f"with its 68 and 90 percent bands, {rows[0]['period']} to "
        f"{rows[-1]['period']}. The median runs from {rows[0]['median']:.2f}% "
        f"to {rows[-1]['median']:.2f}%."
    )

    return "\n".join(
        [
            '      <p class="chart-intro">Unemployment, from the '
            f"{src.parent.name} svar-unemployment satellite round — no "
            "official quarterly path to overlay, so the fan stands "
            "alone.</p>",
            '      <figure class="vchart-figure">',
            f'        <svg class="vchart" data-chart="{CHART_ID}" '
            f'viewBox="0 0 {width} {height}" role="img" '
            f'aria-labelledby="{CHART_ID}-t {CHART_ID}-d">',
            f'          <title id="{CHART_ID}-t">svar-unemployment satellite UK '
            "unemployment rate forecast, median with 68% and 90% bands</title>",
            f'          <desc id="{CHART_ID}-d">{desc}</desc>',
            *gridlines,
            *ticks,
            f'          <polygon class="vc-band90" points="{band("lo90", "hi90")}"/>',
            f'          <polygon class="vc-band68" points="{band("lo68", "hi68")}"/>',
            f'          <polyline class="vc-s1" points="{median}"/>',
            *xticks,
            "        </svg>",
            '        <div class="olg-legend">'
            '<span class="li"><span class="ln ln-s1"></span>'
            "svar-unemployment median (68% and 90% bands)</span></div>",
            "      </figure>",
        ]
    )


def render_page(html: str) -> str:
    pattern = re.compile(
        rf"(<!-- {MARKER}:begin -->\n).*?(<!-- {MARKER}:end -->)", re.DOTALL
    )
    if not pattern.search(html):
        raise SystemExit(f"{PAGE}: marker {MARKER} not found")
    body = render()
    return pattern.sub(lambda m: m.group(1) + body + "\n" + m.group(2), html, count=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--check", action="store_true", help="exit 1 if the page is stale"
    )
    args = ap.parse_args()

    page_now = PAGE.read_text()
    page_fresh = render_page(page_now)

    if args.check:
        if page_now != page_fresh:
            print(
                "FAIL forecasts/index.html open-fan-unemployment block is stale "
                "— run forecasts/make_open_fans.py",
                file=sys.stderr,
            )
            return 1
        print("OK — open-round unemployment fan current")
        return 0

    if page_now != page_fresh:
        PAGE.write_text(page_fresh)
        print(f"updated {PAGE.relative_to(ROOT)}")
    else:
        print("no change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
