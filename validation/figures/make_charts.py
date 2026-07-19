#!/usr/bin/env python3
"""Regenerate the inline SVG charts in validation/index.html from the papers' sources.

Run:  python3 validation/figures/make_charts.py          # rewrite validation/index.html
      python3 validation/figures/make_charts.py --check  # exit 1 if the page is stale

Why hand-emitted SVG rather than matplotlib: the charts must stay *inline* in the
HTML (the site ships no third-party JS and no external assets) and must inherit the
site's CSS custom properties so they retheme for light/dark. A matplotlib export
bakes in literal colours and would need post-processing to strip them; emitting the
markup directly keeps every fill and stroke on a `vc-*` class defined in style.css.

Every plotted number is either read from a committed data file under papers/*/figures/
or transcribed, with a per-value source pointer, in chart_data.json next to this file.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PAGE = ROOT / "validation" / "index.html"


# ---------------------------------------------------------------- helpers

def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def n(x: float) -> str:
    """Format a coordinate the way the committed markup does: 1dp, no trailing .0 loss."""
    return f"{x:.1f}"


# ---------------------------------------------------------------- data loading

def load_obr_anchored():
    """Quarterly % deviation of the anchored emulator from the Nov-2025 EFO.

    Source: papers/obr-macro/figures/fig_anchored_data.csv (model vs EFO levels).
    """
    path = ROOT / "papers" / "obr-macro" / "figures" / "fig_anchored_data.csv"
    quarters, gdp, cons = [], [], []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            quarters.append(row[""])
            gdp.append((float(row["GDPM_model"]) / float(row["GDPM_efo"]) - 1) * 100)
            cons.append((float(row["CONS_model"]) / float(row["CONS_efo"]) - 1) * 100)
    return quarters, gdp, cons


def load_svar():
    """Global-shock FEVD shares at the 1-year horizon, ours vs the paper."""
    d = json.loads((ROOT / "papers" / "boe-svar" / "figures" / "comparison_numbers.json").read_text())
    return d["production_artifact"], d["paper"]


def load_transcribed():
    return json.loads((HERE / "chart_data.json").read_text())


# ---------------------------------------------------------------- chart builders

def svg_open(view_w, view_h, chart_id, title, desc):
    tid, did = f"{chart_id}-t", f"{chart_id}-d"
    return [
        f'<svg class="vchart" data-chart="{chart_id}" viewBox="0 0 {view_w} {view_h}" '
        f'role="img" aria-labelledby="{tid} {did}">',
        f'<title id="{tid}">{esc(title)}</title>',
        f'<desc id="{did}">{esc(desc)}</desc>',
    ]


def chart_obr_anchored():
    quarters, gdp, cons = load_obr_anchored()
    W, H = 760, 326
    x0, x1 = 58.0, 724.0
    zero_y = 175.0
    per_unit = 55.5 / 0.3          # px per percentage point
    step = (x1 - x0) / (len(quarters) - 1)

    xs = [x0 + i * step for i in range(len(quarters))]
    ymap = lambda v: zero_y - v * per_unit

    mape_g = sum(abs(v) for v in gdp) / len(gdp)
    mape_c = sum(abs(v) for v in cons) / len(cons)

    desc = (
        f"Line chart. Quarterly percentage deviation of the anchored emulator from the "
        f"published November 2025 EFO, {quarters[0]} to {quarters[-1]}. Real GDP ranges from "
        f"{min(gdp):+.2f}% to {max(gdp):+.2f}% (mean absolute deviation {mape_g:.2f}%); "
        f"consumption from {min(cons):+.2f}% to {max(cons):+.2f}% (mean absolute deviation "
        f"{mape_c:.2f}%). Both series stay well inside the plus or minus 1% band at which "
        f"continuous integration hard-fails the build, which is off the top and bottom of "
        f"this frame."
    )
    out = svg_open(W, H, "obr-anchored",
                   "obr-macro: anchored baseline vs November 2025 EFO, quarterly deviation",
                   desc)

    # legend
    out.append('<line class="vc-s1" x1="58" y1="26" x2="84" y2="26"/><circle class="vc-s1-dot" cx="71" cy="26" r="3"/>')
    out.append(f'<text class="vc-lab" x="92" y="30">real GDP (peak {max(gdp):+.2f}%)</text>')
    out.append('<line class="vc-s2" x1="288" y1="26" x2="314" y2="26"/><circle class="vc-s2-dot" cx="301" cy="26" r="3"/>')
    out.append(f'<text class="vc-lab vc-lab2" x="322" y="30">consumption (peak {max(cons):+.2f}%)</text>')

    # y grid
    for tick in (-0.6, -0.3, 0.0, 0.3, 0.6):
        y = ymap(tick)
        cls = "vc-axis" if tick == 0 else "vc-grid"
        label = "0" if tick == 0 else f"{tick:+.1f}%".replace("+0.", "+0.").replace("-0.", "-0.")
        out.append(f'<line class="{cls}" x1="{x0:.0f}" y1="{n(y)}" x2="{x1:.0f}" y2="{n(y)}"/>')
        out.append(f'<text class="vc-tick" x="48" y="{n(y + 4)}" text-anchor="end">{label}</text>')

    # x ticks: first, and each subsequent Q1, plus the last point
    tick_idx = [i for i, q in enumerate(quarters) if q.endswith("Q1")]
    if len(quarters) - 1 not in tick_idx:
        tick_idx.append(len(quarters) - 1)
    for i in tick_idx:
        out.append(f'<text class="vc-tick" x="{n(xs[i])}" y="306" text-anchor="middle">{quarters[i]}</text>')

    for cls, series in (("vc-s1", gdp), ("vc-s2", cons)):
        pts = " L".join(f"{n(xs[i])} {n(ymap(v))}" for i, v in enumerate(series))
        out.append(f'<path class="{cls}" d="M{pts}"/>')
        for i, v in enumerate(series):
            out.append(f'<circle class="{cls}-dot" cx="{n(xs[i])}" cy="{n(ymap(v))}" r="3"/>')

    out.append("</svg>")
    return "\n".join(out)


def grouped_bars(chart_id, title, desc, groups, y_max, y_step, fmt, unit_suffix=""):
    """Two side-by-side bars per group, shared layout for the OBR and SVAR charts."""
    W, H = 760, 304
    base_y, top_y = 258.0, 26.0
    scale = (base_y - top_y) / y_max
    bar_w = 79.2
    centres = (229.0, 559.0)

    out = svg_open(W, H, chart_id, title, desc)

    t = 0.0
    while t <= y_max + 1e-9:
        y = base_y - t * scale
        cls = "vc-axis" if t == 0 else "vc-grid"
        out.append(f'<line class="{cls}" x1="64" y1="{n(y)}" x2="724" y2="{n(y)}"/>')
        out.append(f'<text class="vc-tick" x="54" y="{n(y + 4)}" text-anchor="end">{t:g}{unit_suffix}</text>')
        t += y_step

    for centre, group in zip(centres, groups):
        for k, bar in enumerate(group["bars"]):
            x = centre - 87.1 + k * 91.1
            h = bar["value"] * scale
            y = base_y - h
            out.append(f'<rect class="vc-b{bar["series"]}" x="{n(x)}" y="{n(y)}" width="{bar_w}" height="{n(h)}"/>')
            cx = x + 39.6
            out.append(f'<text class="vc-val" x="{n(cx)}" y="{n(y - 8)}" text-anchor="middle">{fmt(bar["value"])}</text>')
            out.append(f'<text class="vc-tick" x="{n(cx)}" y="276" text-anchor="middle">{esc(bar["name"])}</text>')
        out.append(f'<text class="vc-lab" x="{n(centre - 0.0)}" y="296" text-anchor="middle">{esc(group["label"])}</text>')

    out.append("</svg>")
    return "\n".join(out)


def chart_obr_reform():
    data = load_transcribed()["obr_reform"]
    groups = data["groups"]
    parts = []
    for g in groups:
        ours, off = g["bars"][0]["value"], g["bars"][1]["value"]
        parts.append(f'For the {g["label"]} group, ours is {ours:.2f} against HMRC’s '
                     f'{off:.2f}, a deviation of {(ours / off - 1) * 100:+.1f}%.')
    desc = ("Grouped bar chart in billions of pounds per year. PolicyEngine's static costing of a "
            "1 percentage point rise in the UK basic rate of income tax, against HMRC's Direct "
            "effects of illustrative tax changes ready reckoner, June 2025 vintage. "
            + " ".join(parts) +
            " The 2028–29 emulator figure is interpolated between the scored endpoints "
            "£6.46bn in 2026 and £7.38bn in 2030.")
    return grouped_bars(
        "obr-reform",
        "obr-macro: 1p on the basic rate, ours vs HMRC ready reckoner (£bn/yr)",
        desc, groups, y_max=10, y_step=2, fmt=lambda v: f"{v:.2f}")


def chart_svar_fevd():
    ours, paper = load_svar()
    groups = [
        {"label": "UK GDP, 1-yr horizon",
         "bars": [{"name": "ours", "value": ours["gdp"], "series": 1},
                  {"name": "paper", "value": paper["gdp"], "series": 2}]},
        {"label": "UK CPI, 1-yr horizon",
         "bars": [{"name": "ours", "value": ours["cpi"], "series": 1},
                  {"name": "paper", "value": paper["cpi"], "series": 2}]},
    ]
    desc = (f"Grouped bar chart. Share of UK forecast-error variance attributed to identified "
            f"global shocks (world demand, energy and supply) at the one-year horizon. For GDP, "
            f"our 10,000-draw production run gives {ours['gdp']:.1f}% against the paper's "
            f"{paper['gdp']:.1f}%; for CPI, {ours['cpi']:.1f}% against {paper['cpi']:.1f}%. "
            f"Both deviations are a percentage point or less. The paper's values are approximate.")
    return grouped_bars(
        "svar-fevd",
        "boe-svar: global-shock FEVD shares, ours vs Brignone & Piffer (2025)",
        desc, groups, y_max=60, y_step=20, fmt=lambda v: f"{v:.1f}", unit_suffix="%")


def chart_frbus_residuals():
    data = load_transcribed()["frbus_residuals"]
    rows = data["rows"]
    W, H = 760, 300
    x0, x1 = 380.0, 692.7      # 1e-18 .. 1e-8
    lo_exp, hi_exp = -18, -8
    per_decade = (x1 - x0) / (hi_exp - lo_exp)

    desc = ("Horizontal bar chart on a base-10 logarithmic axis of maximum absolute residuals; "
            "shorter is closer. " +
            "; ".join(f"{r['label']}: {r['value']:.1e}" for r in rows) +
            ". The framing comparison is the last row: the Federal Reserve's own two pyfrbus "
            "releases disagree with each other by as much as this implementation disagrees with "
            "either, so our agreement sits at the scale of the reference implementation's own "
            "numerical noise rather than at a chosen tolerance.")

    out = svg_open(W, H, "frbus-residuals",
                   "frb-us: residuals against the Fed’s pyfrbus, log scale", desc)

    for k in range(6):
        e = lo_exp + 2 * k
        x = x0 + (e - lo_exp) * per_decade
        out.append(f'<line class="vc-grid" x1="{n(x)}" y1="26" x2="{n(x)}" y2="264.0"/>')
        out.append(f'<text class="vc-tick" x="{n(x)}" y="284.0" text-anchor="middle">1e{e}</text>')

    for i, r in enumerate(rows):
        y = 34.0 + 48 * i
        ty = y + 21
        w = (math.log10(r["value"]) - lo_exp) * per_decade
        out.append(f'<text class="vc-lab vc-rowlab" x="366" y="{n(ty)}" text-anchor="end">{esc(r["label"])}</text>')
        out.append(f'<rect class="vc-b{r["series"]}" x="380" y="{n(y)}" width="{n(w)}" height="34"/>')
        out.append(f'<text class="vc-val" x="{n(380 + w + 8)}" y="{n(ty)}">{r["value"]:.1e}</text>')

    out.append("</svg>")
    return "\n".join(out)


BUILDERS = [
    ("obr-anchored", chart_obr_anchored),
    ("obr-reform", chart_obr_reform),
    ("svar-fevd", chart_svar_fevd),
    ("frbus-residuals", chart_frbus_residuals),
]

SVG_RE = re.compile(r'<svg class="vchart".*?</svg>', re.DOTALL)


def render_page(html: str) -> str:
    charts = [build() for _, build in BUILDERS]
    found = SVG_RE.findall(html)
    if len(found) != len(charts):
        sys.exit(f"expected {len(charts)} .vchart SVGs in {PAGE}, found {len(found)}")
    it = iter(charts)
    return SVG_RE.sub(lambda _m: next(it).replace("\\", "\\\\"), html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the page is out of date")
    args = ap.parse_args()

    html = PAGE.read_text()
    new = render_page(html)
    if args.check:
        if new != html:
            print(f"{PAGE} is out of date; run: python3 validation/figures/make_charts.py")
            return 1
        print("validation/index.html charts are up to date.")
        return 0
    if new == html:
        print("no change.")
    else:
        PAGE.write_text(new)
        print(f"wrote {len(BUILDERS)} charts into {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
