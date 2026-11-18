#!/usr/bin/env python3
"""Regenerate the inline SVG fan chart in the homepage hero from committed data.

Run:  python3 assets/make_hero.py          # rewrite index.html
      python3 assets/make_hero.py --check  # exit 1 if the page is stale

Same approach, and the same reasons, as validation/figures/make_charts.py: the
markup must stay *inline* (the site ships no third-party assets and enforces
default-src 'self'), and every fill and stroke must sit on a class defined in
style.css so the figure retint itself for light and dark.

The hero motif is the current boe-svar UK real-GDP growth fan: the 68% and 90%
credible bands and posterior median from the latest complete quarterly data
edge.  The frozen 2024Q2 backtest remains on the validation page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import chartkit  # noqa: E402  (stdlib-only, repo root)
PAGE = ROOT / "index.html"
SRC = ROOT / "papers" / "boe-svar" / "figures" / "current_forecast.json"

MARK_OPEN = "<!-- hero-fan:begin -->"
MARK_CLOSE = "<!-- hero-fan:end -->"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def n(x: float) -> str:
    return f"{x:.1f}"


def data_edge() -> str:
    """Last quarter of data the forecast conditions on, from the archived round."""
    return json.loads(SRC.read_text())["data_edge"]


CALIBRATION = ROOT / "forecasts" / "band_calibration.json"


def _qi(period: str) -> int:
    return int(period[:4]) * 4 + int(period[5]) - 1


def load_fan():
    """Quarterly year-on-year UK real GDP growth: median, 68% and 90% bands.

    The bands are re-calibrated exactly as the /forecasts fans are
    (forecasts/score.py build_vs_official): each half-width is scaled around the
    archived median by the per-horizon factor in forecasts/band_calibration.json,
    with h beyond the evaluated 8 holding the h8 factor. The archived round is
    never modified; only the drawn bands change.
    """
    payload = json.loads(SRC.read_text())
    table = payload["forecast"]
    quarters = list(table)
    k = json.loads(CALIBRATION.read_text())["k"]["gdp"]
    edge = _qi(payload["data_edge"])
    med, lo68, hi68, lo90, hi90 = [], [], [], [], []
    for q in quarters:
        row = table[q]["gdp"]
        m, l68, h68, l90, h90 = (
            row[kk] for kk in ("median", "lo68", "hi68", "lo90", "hi90")
        )
        h = min(max(_qi(q) - edge, 1), 8)
        k68, k90 = k["68"][f"h{h}"], k["90"][f"h{h}"]
        l68, h68 = m + (l68 - m) * k68, m + (h68 - m) * k68
        l90, h90 = m + (l90 - m) * k90, m + (h90 - m) * k90
        med.append(m)
        lo68.append(l68)
        hi68.append(h68)
        lo90.append(l90)
        hi90.append(h90)
    return quarters, med, lo68, hi68, lo90, hi90


def build() -> str:
    quarters, med, lo68, hi68, lo90, hi90 = load_fan()

    W, H = 640, 400
    # The value ticks sit in a gutter right of the plot, clear of the bands and
    # the median (at 1440 the "+1%" label used to sit on the median path).
    x0, x1 = 30.0, 580.0
    top, bot = 40.0, 344.0  # plot area for the value range below
    # the value range follows the (re-calibrated) 90% band, with a little headroom
    import math
    v_lo = math.floor(min(lo90) - 0.2)
    v_hi = math.ceil(max(hi90) + 0.2)
    step = (x1 - x0) / (len(quarters) - 1)
    xs = [x0 + i * step for i in range(len(quarters))]

    def ymap(v):
        return bot - (v - v_lo) / (v_hi - v_lo) * (bot - top)

    def band(lo, hi):
        up = " L".join(f"{n(xs[i])} {n(ymap(v))}" for i, v in enumerate(hi))
        dn = " L".join(
            f"{n(xs[i])} {n(ymap(v))}" for i, v in reversed(list(enumerate(lo)))
        )
        return f"M{up} L{dn} Z"

    widths = [hi - lo for lo, hi in zip(lo90, hi90)]
    w = widths.index(max(widths))
    neg = [i for i, lo in enumerate(lo90) if lo < 0]
    if not neg:
        edge = "its lower edge stays positive throughout the forecast"
    elif neg[0] == 0:
        edge = "its lower edge is below zero throughout the forecast"
    else:
        edge = (
            f"its lower edge is positive for the first "
            f"{'quarter' if neg[0] == 1 else str(neg[0]) + ' quarters'} and dips "
            f"below zero from {quarters[neg[0]]} onward"
        )
    desc = (
        f"Fan chart. Posterior forecast of UK year-on-year real GDP growth from the "
        f"boe-svar model, {quarters[0]} to {quarters[-1]}, conditioned through {data_edge()}. The "
        f"median path runs from {med[0]:+.2f}% to {med[-1]:+.2f}%. The re-calibrated 90% band "
        f"is widest at {quarters[w]}, spanning {lo90[w]:+.2f}% to {hi90[w]:+.2f}%; {edge}."
    )

    out = [
        f'<svg class="hero-fan" data-chart="hero-fan" viewBox="{x0 - 6:g} {top - 6:g} '
        f'{x1 - x0 + 12:g} {bot - top + 12:g}" '
        f'role="img" aria-labelledby="hero-fan-t hero-fan-d">',
        '<title id="hero-fan-t">boe-svar: UK real GDP growth forecast, median with re-calibrated 68% and 90% bands</title>',
        f'<desc id="hero-fan-d">{esc(desc)}</desc>',
    ]

    for tick in range(math.ceil(v_lo), math.floor(v_hi) + 1):
        y = ymap(tick)
        cls = "hf-zero" if tick == 0 else "hf-grid"
        out.append(
            f'<line class="{cls}" x1="{n(x0)}" y1="{n(y)}" x2="{n(x1)}" y2="{n(y)}"/>'
        )
        label = f"{tick:+d}%".replace("-", "\u2212") if tick else "0%"
        out.append(
            f'<text class="vc-tick hf-tick vc-gutter" x="{n(x1 + 8)}" y="{n(y)}">{label}</text>'
        )

    out.append(f'<path class="hf-b90" d="{band(lo90, hi90)}"/>')
    out.append(f'<path class="hf-b68" d="{band(lo68, hi68)}"/>')
    line = " L".join(f"{n(xs[i])} {n(ymap(v))}" for i, v in enumerate(med))
    out.append(f'<path class="hf-med" d="M{line}"/>')
    out.append(
        f'<circle class="hf-dot" cx="{n(xs[-1])}" cy="{n(ymap(med[-1]))}" r="4"/>'
    )

    # Year labels along the x-axis: the first quarter's year at the left edge,
    # then each subsequent year at its Q1 boundary.
    for i, q in enumerate(quarters):
        year, qtr = q.split("Q")
        if i == 0 or qtr == "1":
            anchor = "start" if i == 0 else "middle"
            out.append(
                f'<text class="vc-tick hf-q vc-x" x="{n(xs[i])}" y="{n(bot)}" '
                f'text-anchor="{anchor}">{esc(year)}</text>'
            )
    # The labels are lifted into HTML by chartkit, so they stay 12 px at every
    # width; the <figcaption> next to this figure carries the rest.
    out.append("</svg>")
    fig = chartkit.figure("\n".join(out), wrap_class="vc-hero",
                          unit="UK real GDP, % change on a year earlier")
    # Interactive version, the same rows and range; the SVG above stays as the
    # no-JS, print and screen-reader version. The home page loads none of the
    # page stylesheets that carry the swap rules, so they travel with the block.
    rows = [{"period": q, "median": m, "lo68": a, "hi68": b, "lo90": c, "hi90": d}
            for q, m, a, b, c, d in zip(quarters, med, lo68, hi68, lo90, hi90)]
    spec = chartkit.fan_plot(rows, median_name="BoE SVAR median", band_note="(re-calibrated)",
                             y_range=(v_lo, v_hi), zero=True, height=300)
    spec["data"].append(chartkit.plot_last(quarters[-1], med[-1], "var(--series-ours)", digits=2,
                                           position="top left"))
    legend = ('<div class="hf-key"><ul class="hf-legend" aria-label="Chart key">'
              '<li><span class="hf-sw hf-sw-med" aria-hidden="true"></span>Median</li>'
              '<li><span class="hf-sw hf-sw-68" aria-hidden="true"></span>68% band</li>'
              '<li><span class="hf-sw hf-sw-90" aria-hidden="true"></span>90% band</li></ul>'
              '<p class="hf-key-note">Bands re-calibrated for measured under-coverage, as on '
              '<a href="/forecasts#open">Forecasts</a>.</p></div>')
    return "\n".join([MARK_OPEN, chartkit.attach_plot(fig, spec), legend, HERO_PLOT_CSS,
                       chartkit.plot_scripts(), MARK_CLOSE])


HERO_PLOT_CSS = (
    "<style>"
    ".hf-key{margin:8px 0 0;font-size:12px;color:var(--text-muted)}"
    ".hf-legend{display:flex;flex-wrap:wrap;gap:4px 16px;margin:0;padding:0;list-style:none}"
    ".hf-legend li{display:inline-flex;align-items:center;gap:6px;margin:0;padding:0;border:0;background:none}"
    ".hf-sw{display:inline-block;flex:none;width:14px;height:10px;border-radius:2px}"
    ".hf-sw-med{height:0;border-top:2.25px solid var(--series-ours);border-radius:0;width:18px}"
    ".hf-sw-68{background:var(--band-68)}.hf-sw-90{background:var(--band-90)}"
    ".hf-key-note{margin:4px 0 0;line-height:1.4}"
    ".vc-hero .pe-plot{width:100%;height:0;overflow:hidden}"
    ".vc-hero.has-plot .pe-plot{height:auto;overflow:visible}"
    ".vc-hero.has-plot>.vc-plot{position:absolute!important;width:1px!important;height:1px!important;"
    "min-height:0!important;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap}"
    "@media (prefers-color-scheme:dark){.vc-hero{--band-68:color-mix(in srgb,var(--primary) 45%,transparent);"
    "--band-90:color-mix(in srgb,var(--primary) 22%,transparent);--chart-zero:color-mix(in srgb,#fff 35%,transparent)}}"
    "@media print{.vc-hero.has-plot .pe-plot{display:none}.vc-hero.has-plot>.vc-plot{position:relative!important;"
    "width:auto!important;height:auto!important;overflow:visible;clip:auto;clip-path:none}}"
    "</style>"
)


BLOCK_RE = re.compile(re.escape(MARK_OPEN) + r".*?" + re.escape(MARK_CLOSE), re.DOTALL)


def render_page(html: str) -> str:
    if not BLOCK_RE.search(html):
        sys.exit(f"no {MARK_OPEN} … {MARK_CLOSE} block in {PAGE}")
    return BLOCK_RE.sub(lambda _m: build(), html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check", action="store_true", help="exit 1 if the page is out of date"
    )
    args = ap.parse_args()

    html = PAGE.read_text()
    new = render_page(html)
    if args.check:
        if new != html:
            print(f"{PAGE} is out of date; run: python3 assets/make_hero.py")
            return 1
        print("index.html hero fan is up to date.")
        return 0
    if new == html:
        print("no change.")
    else:
        PAGE.write_text(new)
        print(f"wrote the hero fan into {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
