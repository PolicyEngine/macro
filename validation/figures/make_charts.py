#!/usr/bin/env python3
"""Regenerate the inline SVG evidence charts on the model validation pages.

Each chart lives inline on the validation subtab of the model it belongs to
(obr/validation, svar/validation, frb-us/validation, us-hank/validation) as an
``<svg class="vchart" data-chart="...">`` block; this script rewrites each block
in place on its owning page, keyed by the ``data-chart`` attribute.

Run:  python3 validation/figures/make_charts.py          # rewrite the pages
      python3 validation/figures/make_charts.py --check  # exit 1 if any page is stale

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
sys.path.insert(0, str(ROOT))
import chartkit  # noqa: E402  (stdlib-only, repo root)


# ---------------------------------------------------------------- helpers

def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def n(x: float) -> str:
    """Format a coordinate the way the committed markup does: 1dp, no trailing .0 loss."""
    return f"{x:.1f}"


# ---------------------------------------------------------------- data loading

def load_obr_anchored():
    """Quarterly % deviation of the anchored emulator from the March-2026 EFO.

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


def load_levels(name, cols):
    """Quarterly levels from a papers/obr-macro/figures CSV, keyed by column."""
    path = ROOT / "papers" / "obr-macro" / "figures" / name
    quarters, out = [], {c: [] for c in cols}
    with path.open() as fh:
        for row in csv.DictReader(fh):
            quarters.append(row[""])
            for c in cols:
                out[c].append(float(row[c]))
    return quarters, out


def load_outturn():
    """Quarterly %q/q GDP growth: emulator vs EFO vintage vs ONS outturn."""
    path = ROOT / "papers" / "obr-macro" / "figures" / "fig_outturn_data.csv"
    rows = []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            rows.append((row["period"], float(row["model_qoq_pct"]),
                         float(row["efo_qoq_pct"]), float(row["ons_outturn_qoq_pct"])))
    return rows


def load_svar_fan():
    """Median/68% forecast paths from the frozen 2024Q2 edge, plus ONS outturns.

    Medians and bands: papers/boe-svar/figures/figure_numbers.json (forecast_table,
    entries [median, lo68, hi68, lo90, hi90]). Outturns: the committed arrays in
    papers/boe-svar/figures/make_figures.py.
    """
    d = json.loads((ROOT / "papers" / "boe-svar" / "figures" / "figure_numbers.json").read_text())
    ft = d["forecast_table"]
    quarters = list(ft)
    src = (ROOT / "papers" / "boe-svar" / "figures" / "make_figures.py").read_text()
    outturns = {}
    for var in ("gdp", "cpi"):
        m = re.search(rf"outturn_{var}\s*=\s*\[([^\]]+)\]", src)
        outturns[var] = [float(v) for v in m.group(1).split(",")]
    series = {var: {"median": [ft[q][var][0] for q in quarters],
                    "lo68": [ft[q][var][1] for q in quarters],
                    "hi68": [ft[q][var][2] for q in quarters]}
              for var in ("gdp", "cpi")}
    return quarters, series, outturns


def load_transcribed():
    return json.loads((HERE / "chart_data.json").read_text())


def load_define_emissions():
    """S1 baseline total emissions at the manual's benchmark years.

    Source: validation/figures/data/define_emissions_divergence.csv — the
    cached pinned run of upstream commit 846081a against the manual's
    published Table 4, MtCO2e/yr, as recorded in the define-uk-model
    repository's VALIDATION.md (target 1b).
    """
    path = HERE / "data" / "define_emissions_divergence.csv"
    rows = []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            rows.append((row["year"], float(row["pinned_run_mtco2e"]),
                         float(row["manual_table4_mtco2e"])))
    return rows


def load_rolling_eval():
    """Expanding-window forecast skill against a random walk with drift.

    Source: papers/boe-svar/figures/rolling_evaluation.json, which stores, per
    horizon, ``relative_rmse_vs_drift_by_variable`` (model RMSE / benchmark
    RMSE; below 1 means the model wins) and ``dm_pvalue_vs_drift_by_variable``
    (Diebold-Mariano p-value for that difference).

    The drift benchmark is used rather than the plain random walk because it is
    the harder of the two: a drifting series makes a no-change forecast look
    worse than it is, and the model's advantage shrinks against drift.
    """
    d = json.loads(
        (ROOT / "papers" / "boe-svar" / "figures" / "rolling_evaluation.json").read_text()
    )
    horizons = sorted(d["horizons"], key=lambda h: h["horizon"])
    ratio = {h["horizon"]: h["relative_rmse_vs_drift_by_variable"] for h in horizons}
    pval = {h["horizon"]: h["dm_pvalue_vs_drift_by_variable"] for h in horizons}
    return [h["horizon"] for h in horizons], ratio, pval, d


# Descriptions are read aloud by screen readers, where digits for small counts
# scan worse than words.
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
         6: "six", 7: "seven", 8: "eight"}


def word(k):
    return WORDS.get(k, str(k))


# ---------------------------------------------------------------- chart builders

def svg_open(view_w, view_h, chart_id, title, desc, origin=(0, 0)):
    """Open a chart. ``origin`` crops the viewBox's top-left (min-x, min-y)."""
    tid, did = f"{chart_id}-t", f"{chart_id}-d"
    ox, oy = origin
    return [
        f'<svg class="vchart" data-chart="{chart_id}" viewBox="{ox:g} {oy:g} {view_w} {view_h}" '
        f'role="img" aria-labelledby="{tid} {did}">',
        f'<title id="{tid}">{esc(title)}</title>',
        f'<desc id="{did}">{esc(desc)}</desc>',
    ]


def chart_obr_anchored():
    quarters, gdp, cons = load_obr_anchored()
    W, H = 760, 326
    x0, x1 = 58.0, 724.0
    # Frame runs -0.3pp to +1.2pp: the March 2026 vintage with the recovered
    # ONS series drifts above the EFO to about +1.2% on consumption by 2027Q4.
    zero_y = 244.0
    per_unit = 46.0 / 0.3          # px per percentage point
    step = (x1 - x0) / (len(quarters) - 1)

    xs = [x0 + i * step for i in range(len(quarters))]
    def ymap(v):
        return zero_y - v * per_unit

    mape_g = sum(abs(v) for v in gdp) / len(gdp)
    mape_c = sum(abs(v) for v in cons) / len(cons)
    over = [q for q, v in zip(quarters, cons) if abs(v) >= 1.0]
    over_note = (f", and consumption is more than 1% from the EFO in {' and '.join(over)}"
                 if over else "")

    desc = (
        f"Line chart. Quarterly percentage deviation of the anchored emulator from the "
        f"published March 2026 EFO, {quarters[0]} to {quarters[-1]}. Real GDP ranges from "
        f"{min(gdp):+.2f}% to {max(gdp):+.2f}% (mean absolute deviation {mape_g:.2f}%); "
        f"consumption from {min(cons):+.2f}% to {max(cons):+.2f}% (mean absolute deviation "
        f"{mape_c:.2f}%). Continuous integration hard-fails the build if either mean absolute "
        f"deviation reaches 1%; it does not test single quarters{over_note}."
    )
    y_top, y_bot = ymap(1.2), ymap(-0.3)
    out = svg_open(x1 - x0 + 12, y_bot - y_top + 12, "obr-anchored",
                   "OBR emulator: anchored baseline vs March 2026 EFO, quarterly deviation",
                   desc, origin=(x0 - 6, y_top - 6))

    # y grid: labels inside the plot, above their gridline; zero is vc-zero.
    for tick in (-0.3, 0.0, 0.3, 0.6, 0.9, 1.2):
        y = ymap(tick)
        cls = "vc-zero" if tick == 0 else "vc-grid"
        label = "0" if tick == 0 else f"{tick:+.1f}%".replace("-", "\u2212")
        out.append(f'<line class="{cls}" x1="{x0:.0f}" y1="{n(y)}" x2="{x1:.0f}" y2="{n(y)}"/>')
        out.append(chartkit.ytick(x0, y, label))

    # x ticks: first, and each subsequent Q1, plus the last point
    tick_idx = [i for i, q in enumerate(quarters) if q.endswith("Q1")]
    if 0 not in tick_idx:
        tick_idx.insert(0, 0)
    if len(quarters) - 1 not in tick_idx:
        tick_idx.append(len(quarters) - 1)
    for j, i in enumerate(tick_idx):
        out.append(chartkit.xtick(xs[i], y_bot + 6, quarters[i], j, len(tick_idx) - 1,
                                  minor=_crowds_last(tick_idx, j)))

    # Both lines are this emulator (the EFO is the zero line), so neither is
    # drawn in the dashed "official" style: GDP is the headline series,
    # consumption the labelled neutral, and each is named at its last point.
    for cls, dot, series in (("vc-s1", "vc-s1-dot", gdp), ("vc-s3", "vc-s3-dot", cons)):
        pts = " L".join(f"{n(xs[i])} {n(ymap(v))}" for i, v in enumerate(series))
        out.append(f'<path class="{cls}" d="M{pts}"/>')
        for i, v in enumerate(series):
            out.append(f'<circle class="{dot}" cx="{n(xs[i])}" cy="{n(ymap(v))}" r="3"/>')
    # "peak" is the largest deviation in either direction, not the largest
    # positive one: max() would quietly report the least-negative value on a
    # series that never rose above the EFO.
    # Both labels sit above their own line's end: each line rises into the
    # right edge, so the space above the end point is clear of it.
    for series, name, ink in ((gdp, "real GDP", "s1"), (cons, "consumption", "s3")):
        out.append(chartkit.endlabel(
            xs[-1] - 8, ymap(series[-1]),
            f"{name}, peak {fmt_signed(max(series, key=abs))}%", ink))

    out.append("</svg>")
    return chartkit.figure("\n".join(out), unit="% deviation from the March 2026 EFO")


def _crowds_last(tick_idx: list[int], j: int) -> bool:
    """True for an x tick too close to the last one to share a phone-width axis.

    The quarterly charts label each Q1 plus the final quarter; when the final
    quarter is Q4 its label lands three quarters after the last Q1 and the two
    touch below 520 px. Marking the earlier one minor keeps first and last.
    """
    last = len(tick_idx) - 1
    if j in (0, last) or last < 2:
        return False
    spacing = (tick_idx[last] - tick_idx[0]) / last
    return j == last - 1 and tick_idx[last] - tick_idx[j] < spacing


def fmt_signed(v: float, places: int = 2) -> str:
    """+0.70 / \u22120.30: a signed number with a true minus sign."""
    return f"{v:+.{places}f}".replace("-", "\u2212")


def grouped_bars(chart_id, title, desc, groups, y_max, y_step, fmt, unit_suffix="", unit=None):
    """Two side-by-side bars per group, shared layout for the OBR and SVAR charts.

    The bars' names go in the HTML legend (series 1 = ours, 2 = the published
    counterpart); each group's label wraps under its own pair.
    """
    W = 760
    base_y, top_y = 258.0, 26.0
    scale = (base_y - top_y) / y_max
    bar_w = 79.2
    centres = (229.0, 559.0)
    x0, x1 = 64.0, 724.0

    out = svg_open(x1 - x0, base_y - top_y + 12, chart_id, title, desc, origin=(x0, top_y - 6))

    t = 0.0
    while t <= y_max + 1e-9:
        y = base_y - t * scale
        cls = "vc-zero" if t == 0 else "vc-grid"
        out.append(f'<line class="{cls}" x1="{x0:g}" y1="{n(y)}" x2="{x1:g}" y2="{n(y)}"/>')
        if t:
            out.append(chartkit.ytick(x0, y, f"{t:g}{unit_suffix}"))
        t += y_step

    for centre, group in zip(centres, groups):
        for k, bar in enumerate(group["bars"]):
            x = centre - 87.1 + k * 91.1
            h = bar["value"] * scale
            y = base_y - h
            # An interpolated value is not a scored one: outline it (vc-interp).
            cls = "vc-interp" if bar.get("interpolated") else f'vc-b{bar["series"]}'
            out.append(f'<rect class="{cls}" x="{n(x)}" y="{n(y)}" width="{bar_w}" height="{n(h)}"/>')
            cx = x + 39.6
            out.append(f'<text class="vc-val" x="{n(cx)}" y="{n(y - 6)}" text-anchor="middle">{fmt(bar["value"])}</text>')
        out.append(f'<text class="vc-lab vc-x" x="{n(centre)}" y="{n(base_y + 6)}" '
                   f'text-anchor="middle" data-w="320">{esc(group["label"])}</text>')

    out.append("</svg>")
    legend = [(f'sw-b{bar["series"]}', esc(bar["name"])) for bar in groups[0]["bars"]]
    if any(bar.get("interpolated") for g in groups for bar in g["bars"]):
        legend.append(("sw-interp", "interpolated between scored years"))
    return chartkit.figure("\n".join(out), legend=legend, wrap_class="vc-two-rows", unit=unit)


def _reform_costing(chart_id: str, title: str):
    """The PolicyEngine static costing of a 1pp basic-rate rise, vs HMRC.

    Rendered twice from one committed source (chart_data.json ``obr_reform``):
    on obr/validation as the macro bridge's input, and on the microsimulation's
    own page as the independent check on the costing it produced. Same numbers,
    two framings — so the numbers can only ever be changed in one place.
    """
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
            " The 2028–29 microsimulation figure is interpolated between the scored endpoints "
            "£6.46bn in 2026 and £7.38bn in 2030.")
    return grouped_bars(
        chart_id, title, desc, groups, y_max=10, y_step=2, fmt=lambda v: f"{v:.2f}",
        unit="Static revenue, £bn a year")


def chart_obr_reform():
    return _reform_costing(
        "obr-reform",
        "OBR emulator: 1p on the basic rate, ours vs HMRC ready reckoner (£bn/yr)")


def chart_pe_costing():
    return _reform_costing(
        "pe-costing",
        "PolicyEngine microsimulation: 1p on the UK basic rate, our static costing vs the HMRC "
        "ready reckoner (£bn/yr)")


def chart_svar_fevd():
    ours, paper = load_svar()
    d = json.loads((ROOT / "papers" / "boe-svar" / "figures" / "comparison_numbers.json").read_text())
    fast = d["fast_config"]
    fan = json.loads(
        (ROOT / "papers" / "boe-svar" / "figures" / "figure_numbers.json").read_text()
    )
    groups = [
        {"label": "UK GDP, 1-yr horizon",
         "bars": [{"name": "ours", "value": ours["gdp"], "series": 1},
                  {"name": "paper", "value": paper["gdp"], "series": 2}]},
        {"label": "UK CPI, 1-yr horizon",
         "bars": [{"name": "ours", "value": ours["cpi"], "series": 1},
                  {"name": "paper", "value": paper["cpi"], "series": 2}]},
    ]
    # The draw count of the production run is not recorded in the artifact, so
    # it is not asserted here. The 68% bands are the 600-draw check
    # configuration's, and are labelled as such rather than attached to the
    # production bars as if they had been measured on them.
    desc = (f"Grouped bar chart. Share of UK forecast-error variance attributed to identified "
            f"global shocks (world demand, energy and supply) four quarters ahead, as a share of "
            f"total variance — the statistic the paper's Figure 4 plots. For GDP, our production "
            f"artifact gives {ours['gdp']:.1f}% against the paper's {paper['gdp']:.1f}%, "
            f"{abs(ours['gdp'] - paper['gdp']):.1f} points short; for CPI, {ours['cpi']:.1f}% "
            f"against {paper['cpi']:.1f}%, {abs(ours['cpi'] - paper['cpi']):.1f} points short. "
            f"Neither gap is resolvable: on the {fast['n_draws']}-draw check configuration the "
            f"68 per cent posterior band on the same share runs {fast['gdp_68_band_pct'][0]:.0f} "
            f"to {fast['gdp_68_band_pct'][1]:.0f} per cent for GDP and "
            f"{fast['cpi_68_band_pct'][0]:.0f} to {fast['cpi_68_band_pct'][1]:.0f} per cent for "
            f"CPI, both far wider than the shortfall, and the paper's values are read off its "
            f"figure and approximate. This comparison and the fan chart elsewhere on this page "
            f"are different runs: the fan chart is the frozen 2024Q2-edge run of "
            f"{fan['n_draws']:,} draws at seed {fan['seed']}.")
    return grouped_bars(
        "svar-fevd",
        "BoE SVAR: global-shock FEVD shares, ours vs Brignone & Piffer (2025)",
        desc, groups, y_max=60, y_step=20, fmt=lambda v: f"{v:.1f}", unit_suffix="%",
        unit="Share of forecast-error variance from global shocks, %")


def chart_frbus_residuals():
    """Residuals against the Fed's own pyfrbus, on a log axis, as a dot strip.

    Three kinds of comparison, each named in its row label and by its mark:
    ours vs the Fed (filled, series colour), the Fed's two releases vs each
    other (filled slate, and a dashed rule down the chart), and the tracking
    identity rows the page says are *not* evidence (hollow rings), so the
    grouping survives without colour.
    """
    data = load_transcribed()["frbus_residuals"]
    rows = data["rows"]
    W, H = 760, 330
    x0, x1 = 380.0, 692.7      # 1e-18 .. 1e-7
    lo_exp, hi_exp = -18, -7
    per_decade = (x1 - x0) / (hi_exp - lo_exp)

    def group(r):
        return {1: "ours vs the Fed", 2: "the Fed vs itself"}.get(
            r["series"], "tracking identity")

    desc = ("Dot chart on a base-10 logarithmic axis of maximum absolute residuals; "
            "further left is closer. The rows fall into three kinds. " +
            "; ".join(f"{r['label']}: {r['value']:.1e} ({group(r)})" for r in rows) +
            ". The two tracking rows are an identity — init_trac defines the add-factors as "
            "minus the residuals at the input data, so re-solving reproduces the input for any "
            "input at all — and are shown for completeness, not as evidence. The framing "
            "comparison is the last row: the Federal Reserve's own two pyfrbus releases "
            "disagree with each other by as much as this implementation disagrees with either, "
            "so our agreement sits at the scale of the reference implementation's own "
            "numerical noise rather than at a chosen tolerance.")

    # A dot strip, not bars: on a log axis a bar's length is measured from an
    # arbitrary origin (1e-18 here) and encodes nothing. Each row is a track
    # with one dot at the residual; the label (with its value) sits above it.
    # The identity rows are hollow rings, the Fed-vs-itself row sets a dashed
    # reference rule down the whole chart: the scale of the reference
    # implementation's own numerical noise.
    x0, x1 = 0.0, 700.0
    per_decade = (x1 - x0) / (hi_exp - lo_exp)
    pitch, top = 64.0, 40.0
    track = 16.0                       # dot centre below the row label
    base = top + pitch * (len(rows) - 1) + track + 14
    out = svg_open(x1 - x0, base - 4, "frbus-residuals",
                   "FRB/US: residuals against the Fed’s pyfrbus, log scale", desc,
                   origin=(x0, 4))

    def xpos(v):
        return x0 + (math.log10(v) - lo_exp) * per_decade

    for k in range(6):
        e = lo_exp + 2 * k
        x = x0 + (e - lo_exp) * per_decade
        out.append(f'<line class="vc-grid" x1="{n(x)}" y1="{n(top - 30)}" x2="{n(x)}" y2="{n(base)}"/>')
        out.append(chartkit.xtick(x, base, f"10<sup>{str(e).replace('-', chr(0x2212))}</sup>", k, 5))

    fed = [r for r in rows if r["series"] == 2]
    if fed:
        xf = xpos(fed[0]["value"])
        out.append(f'<line class="vc-ref" x1="{n(xf)}" y1="{n(top - 30)}" x2="{n(xf)}" y2="{n(base)}"/>')

    for i, r in enumerate(rows):
        y = top + pitch * i
        value = f'{r["value"]:.1e}'.replace("-", "\u2212")
        out.append(f'<text class="vc-rowlab vc-y" x="{n(x0)}" y="{n(y)}" data-w="{x1 - x0:g}">'
                   f'{esc(r["label"])} <b class="vc-num">{value}</b></text>')
        yd = y + track
        out.append(f'<line class="vc-track" x1="{n(x0)}" y1="{n(yd)}" x2="{n(x1)}" y2="{n(yd)}"/>')
        if r["series"] == 3:
            out.append(f'<circle cx="{n(xpos(r["value"]))}" cy="{n(yd)}" r="5" fill="none" stroke-width="1.5"/>')
        else:
            out.append(f'<circle class="vc-s{r["series"]}-dot" cx="{n(xpos(r["value"]))}" cy="{n(yd)}" r="6"/>')

    out.append("</svg>")
    return chartkit.figure("\n".join(out), min_h=330, legend=[
        ("sw-dot1", "ours vs the Fed&rsquo;s pyfrbus, under shock"),
        ("sw-dot2", "the Fed&rsquo;s two releases vs each other (dashed rule)"),
        ("sw-ring", "tracking identity &mdash; round-off, not fidelity"),
    ], unit="Maximum absolute residual, log scale; further left is closer")


def chart_obr_freerun():
    quarters, free = load_levels("fig_free_running_data.csv", ["GDPM_model", "GDPM_efo"])
    _, anch = load_levels("fig_anchored_data.csv", ["GDPM_model", "GDPM_efo"])
    efo = [v / 1000 for v in free["GDPM_efo"]]        # £bn/qtr
    freerun = [v / 1000 for v in free["GDPM_model"]]
    anchored = [v / 1000 for v in anch["GDPM_model"]]

    W, H = 760, 330
    x0, x1 = 58.0, 724.0
    step = (x1 - x0) / (len(quarters) - 1)
    xs = [x0 + i * step for i in range(len(quarters))]
    lo, hi = 660.0, 740.0
    base_y, top_y = 292.0, 56.0
    per_unit = (base_y - top_y) / (hi - lo)
    def ymap(v):
        return base_y - (v - lo) * per_unit

    mad_a = sum(abs(m / e - 1) for m, e in zip(anch["GDPM_model"], anch["GDPM_efo"])) / len(quarters) * 100
    mad_f = sum(abs(m / e - 1) for m, e in zip(free["GDPM_model"], free["GDPM_efo"])) / len(quarters) * 100
    gap = efo[-1] - freerun[-1]

    desc = (
        f"Line chart of quarterly real GDP levels in billions of pounds, {quarters[0]} to "
        f"{quarters[-1]}. The published March 2026 EFO path rises from {efo[0]:.1f} to "
        f"{efo[-1]:.1f}. The anchored emulator tracks it closely, running "
        f"from {anchored[0]:.1f} to {anchored[-1]:.1f} (mean absolute deviation {mad_a:.2f} per "
        f"cent, recomputed here from the plotted series). The free-running emulator, de-seeded "
        f"and with no add-factors, contracts from {freerun[0]:.1f} to {freerun[-1]:.1f} — a gap "
        f"that widens to {gap:.0f} billion pounds, {mad_f:.2f} per cent mean absolute deviation "
        f"over the horizon. Free-running and EFO paths from "
        f"papers/obr-macro/figures/fig_free_running_data.csv; anchored path from "
        f"papers/obr-macro/figures/fig_anchored_data.csv. Coordinates: value v in billions maps "
        f"to y = {base_y:g} - (v - {lo:g}) * {per_unit:g} on a {lo:g} to {hi:g} axis; quarter i "
        f"of {len(quarters)} maps to x = {x0:g} + i * {step:.3f}."
    )
    out = svg_open(x1 - x0 + 12, base_y - top_y + 12, "obr-freerun",
                   "OBR emulator: real GDP level, anchored vs free-running vs the March 2026 EFO (£bn/qtr)",
                   desc, origin=(x0 - 6, top_y - 6))

    tick = lo
    while tick <= hi + 1e-9:
        y = ymap(tick)
        out.append(f'<line class="vc-grid" x1="{x0:.0f}" y1="{n(y)}" x2="{x1:.0f}" y2="{n(y)}"/>')
        out.append(chartkit.ytick(x0, y, f"{tick:g}"))
        tick += 20

    # Roles (DESIGN.md §6.2): the published EFO is the dashed official line;
    # the anchored emulator is ours, solid; the free-running emulator is a
    # variant of ours, drawn as the neutral.
    for cls, series in (("vc-s2", efo), ("vc-s3", freerun), ("vc-s1", anchored)):
        pts = " L".join(f"{n(xs[i])} {n(ymap(v))}" for i, v in enumerate(series))
        out.append(f'<path class="{cls}" d="M{pts}"/>')

    tick_idx = [i for i, q in enumerate(quarters) if q.endswith("Q1")]
    if 0 not in tick_idx:
        tick_idx.insert(0, 0)
    if len(quarters) - 1 not in tick_idx:
        tick_idx.append(len(quarters) - 1)
    for j, i in enumerate(tick_idx):
        out.append(chartkit.xtick(xs[i], base_y, quarters[i], j, len(tick_idx) - 1,
                                  minor=_crowds_last(tick_idx, j)))

    out.append("</svg>")
    # A legend, not end labels: the anchored and EFO paths end a few £bn
    # apart and both rise into the edge, so a label below either one would sit
    # on the line.
    return chartkit.figure("\n".join(out), unit="Real GDP, £bn per quarter", legend=[
        ("ln-s1", f"anchored ({mad_a:.2f}% MAD)"),
        ("ln-s2", "EFO March 2026"),
        ("ln-s3", f"free-running ({mad_f:.2f}% MAD)"),
    ])


def chart_obr_outturn():
    rows = load_outturn()
    W, H = 760, 304
    base_y, top_y = 258.0, 26.0
    y_max = 0.7
    scale = (base_y - top_y) / y_max
    bar_w, bar_gap = 40.0, 8.0
    group_step = 165.0
    first_centre = 138.5

    parts = "; ".join(f"{q}: emulator {m:.2f}, EFO {e:.2f}, ONS {o:.2f}" for q, m, e, o in rows)
    desc = (
        f"Bar chart with outturn markers, percentage quarter-on-quarter real GDP growth for the four "
        f"quarters with ONS outturns since anchoring. {parts}. The emulator tracks the three "
        f"2025 outturns to within 0.06 points; both the emulator and the November EFO it "
        f"inherits miss the strong 0.6 per cent 2026Q1 outturn by roughly a quarter of a point. "
        f"Data from papers/obr-macro/figures/fig_outturn_data.csv. Coordinates: value v maps to "
        f"y = {base_y:g} - v * {scale:.1f} on a 0 to {y_max:g} axis."
    )
    x0, x1 = 24.0, 724.0      # room for the y labels left of the first bar
    out = svg_open(x1 - x0, base_y - top_y + 12, "obr-outturn",
                   "OBR emulator: quarterly real GDP growth — emulator vs EFO Nov 2025 vs ONS outturn (% q/q)",
                   desc, origin=(x0, top_y - 6))

    t = 0.0
    while t <= 0.6 + 1e-9:
        y = base_y - t * scale
        cls = "vc-zero" if t == 0 else "vc-grid"
        out.append(f'<line class="{cls}" x1="{x0:g}" y1="{n(y)}" x2="{x1:g}" y2="{n(y)}"/>')
        if t:
            out.append(chartkit.ytick(x0, y, f"{t:g}"))
        t += 0.2

    # The two forecasts are bars; the ONS outturn is what they are judged
    # against, so it is a dot on a rule across its quarter's pair of bars
    # (DESIGN.md §6.1: realised data as dots, never a mark that reads as a
    # third forecast). Values sit above each mark where there is room (a chart
    # at least 520 px wide); below that a small table under the chart carries
    # them instead.
    bar_w, bar_gap = 52.0, 8.0
    for g, (q, m, e, o) in enumerate(rows):
        centre = first_centre + g * group_step
        for k, (cls, v) in enumerate((("vc-b1", m), ("vc-b3", e))):
            x = centre - bar_w - bar_gap / 2 + k * (bar_w + bar_gap)
            h = v * scale
            y = base_y - h
            out.append(f'<rect class="{cls}" x="{n(x)}" y="{n(y)}" width="{bar_w:g}" height="{n(h)}"/>')
            out.append(f'<text class="vc-val vc-minor" x="{n(x + bar_w / 2)}" y="{n(min(y, base_y - o * scale) - 6)}" '
                       f'text-anchor="middle">{v:.2f}</text>')
        yo = base_y - o * scale
        half = bar_w + bar_gap / 2 + 10
        out.append(f'<line class="vc-out-rule" x1="{n(centre - half)}" y1="{n(yo)}" x2="{n(centre + half)}" y2="{n(yo)}"/>')
        out.append(f'<circle class="vc-out-dot" cx="{n(centre + half)}" cy="{n(yo)}" r="4.5"/>')
        out.append(f'<text class="vc-val vc-out-val vc-minor" x="{n(centre + half)}" y="{n(yo - 8)}" '
                   f'text-anchor="middle">{o:.2f}</text>')
        out.append(f'<text class="vc-lab vc-x" x="{n(centre)}" y="{n(base_y + 6)}" text-anchor="middle">{q}</text>')

    out.append("</svg>")
    return chartkit.figure("\n".join(out), legend=[
        ("sw-b1", "emulator"), ("sw-b3", "EFO Nov 2025"), ("sw-dot-out", "ONS outturn"),
    ], unit="Real GDP growth, % q/q",
        narrow_table=(["% q/q", "emulator", "EFO", "ONS"],
                      [[q, f"{m:.2f}", f"{e:.2f}", f"{o:.2f}"] for q, m, e, o in rows]))


def chart_svar_fan():
    quarters, series, outturns = load_svar_fan()
    meta = json.loads(
        (ROOT / "papers" / "boe-svar" / "figures" / "figure_numbers.json").read_text()
    )
    W, H = 760, 360
    base_y, top_y = 292.0, 56.0
    per_unit = (base_y - top_y) / 4.0     # 4-unit span on each panel
    panels = {"gdp": {"x0": 58.0, "x1": 366.0, "v_lo": -1.0},
              "cpi": {"x0": 416.0, "x1": 724.0, "v_lo": 1.0}}
    npts = len(quarters)
    for p in panels.values():
        p["step"] = (p["x1"] - p["x0"]) / (npts - 1)
        p["xs"] = [p["x0"] + i * p["step"] for i in range(npts)]
        p["ymap"] = (lambda lo: lambda v: base_y - (v - lo) * per_unit)(p["v_lo"])

    n_out = len(outturns["gdp"])
    rmse = {var: math.sqrt(sum((m - o) ** 2 for m, o in
                               zip(series[var]["median"][:n_out], outturns[var])) / n_out)
            for var in ("gdp", "cpi")}
    med_g = ", ".join(f"{v:.1f}" for v in series["gdp"]["median"][:n_out])
    med_c = ", ".join(f"{v:.1f}" for v in series["cpi"]["median"][:n_out])
    out_g = ", ".join(f"{v:.1f}" for v in outturns["gdp"])
    out_c = ", ".join(f"{v:.1f}" for v in outturns["cpi"])

    desc = (
        f"Two-panel fan chart. Left panel: year-on-year UK GDP growth; right panel: year-on-year "
        f"UK CPI inflation. Each shows the posterior median forecast from the frozen 2024Q2 data "
        f"edge as a line, the 68 per cent credible band as a shaded region over thirteen quarters "
        f"{quarters[0]} to {quarters[-1]}, and ONS outturns for the seven evaluated quarters "
        f"{quarters[0]} to {quarters[n_out - 1]} as dots. All fourteen outturn dots fall inside "
        f"the 68 per cent band; RMSE {rmse['gdp']:.2f} percentage points on GDP and "
        f"{rmse['cpi']:.2f} on CPI. GDP "
        f"medians run {med_g} per cent over the evaluated quarters against outturns of {out_g}; "
        f"CPI medians {med_c} against outturns of {out_c}. A dashed rule in each panel marks "
        f"{quarters[n_out - 1]}, the last quarter with an outturn: the six quarters to its right "
        f"are forecast with nothing yet to check them against, so the fit shown covers seven of "
        f"the thirteen quarters plotted. This run is {meta['n_draws']:,} posterior draws at seed "
        f"{meta['seed']}, {meta['accepted_forecast']} of which were accepted by the sign "
        f"restrictions; it is a different run from the FEVD comparison elsewhere on this page, "
        f"which comes from the production artifact. Medians and 68 per cent bands from "
        f"papers/boe-svar/figures/figure_numbers.json (forecast_table, entries [median, lo68, "
        f"hi68]); ONS outturns from papers/boe-svar/figures/make_figures.py. Coordinates: GDP "
        f"panel maps value v to y = {base_y:g} - (v + 1) * {per_unit:g} for the -1 to 3 per cent "
        f"axis; CPI panel y = {base_y:g} - (v - 1) * {per_unit:g} for the 1 to 5 per cent axis; "
        f"quarter i of {npts} maps to x = 58 + i * {panels['gdp']['step']:.3f} (GDP) or "
        f"416 + i * {panels['cpi']['step']:.3f} (CPI)."
    )
    out = svg_open(724 - 58 + 12, base_y - top_y + 12, "svar-fan",
                   "BoE SVAR: out-of-sample forecast fan from the frozen 2024Q2 edge vs ONS outturns",
                   desc, origin=(52, top_y - 6))

    gdp_labels = {-1: "\u22121%", 0: "0", 1: "+1%", 2: "+2%", 3: "+3%"}
    for var, labels in (("gdp", gdp_labels), ("cpi", None)):
        p = panels[var]
        for k in range(5):
            v = p["v_lo"] + k
            y = p["ymap"](v)
            cls = "vc-zero" if var == "gdp" and v == 0 else "vc-grid"
            out.append(f'<line class="{cls}" x1="{p["x0"]:.0f}" y1="{n(y)}" x2="{p["x1"]:.0f}" y2="{n(y)}"/>')
            label = labels[v] if labels else f"{v:g}%"
            # The panel title takes the top-left corner; the top tick moves
            # to the right-hand end of its gridline.
            if k == 4:
                out.append(f'<text class="vc-tick vc-y" x="{p["x1"]:.0f}" y="{n(y)}" '
                           f'text-anchor="end">{label}</text>')
            else:
                out.append(chartkit.ytick(p["x0"], y, label))
    out.append(f'<text class="vc-lab vc-y" x="58" y="{n(top_y)}">GDP growth</text>')
    out.append(f'<text class="vc-lab vc-y" x="416" y="{n(top_y)}">CPI inflation</text>')

    for var in ("gdp", "cpi"):
        p = panels[var]
        hi_pts = " L".join(f"{n(p['xs'][i])} {n(p['ymap'](v))}" for i, v in enumerate(series[var]["hi68"]))
        lo_pts = " L".join(f"{n(p['xs'][i])} {n(p['ymap'](v))}"
                           for i, v in reversed(list(enumerate(series[var]["lo68"]))))
        out.append(f'<path class="vc-band" d="M{hi_pts} L{lo_pts} Z"/>')

    for var in ("gdp", "cpi"):
        p = panels[var]
        out.append(f'<line class="vc-edge" x1="{p["x0"]:.0f}" y1="{top_y:.0f}" x2="{p["x0"]:.0f}" y2="{base_y:.0f}"/>')
    # Where the evidence stops. Without this the six unevaluated quarters on the
    # right of each panel read as part of the fit. Drawn before the median and
    # the dots so it does not strike through the last outturn.
    for var in ("gdp", "cpi"):
        p = panels[var]
        x_end = p["xs"][n_out - 1]
        out.append(f'<line class="vc-edge" x1="{n(x_end)}" y1="{top_y:.0f}" '
                   f'x2="{n(x_end)}" y2="{base_y:.0f}"/>')
    for var in ("gdp", "cpi"):
        p = panels[var]
        pts = " L".join(f"{n(p['xs'][i])} {n(p['ymap'](v))}" for i, v in enumerate(series[var]["median"]))
        out.append(f'<path class="vc-s1" d="M{pts}"/>')
    for var in ("gdp", "cpi"):
        p = panels[var]
        for i, v in enumerate(outturns[var]):
            out.append(f'<circle class="vc-out-dot" cx="{n(p["xs"][i])}" cy="{n(p["ymap"](v))}" r="3.5"/>')

    for var in ("gdp", "cpi"):
        p = panels[var]
        for j, i in enumerate((0, npts - 1)):
            out.append(chartkit.xtick(p["xs"][i], base_y, quarters[i], j, 1))

    out.append("</svg>")
    return chartkit.figure("\n".join(out), legend=[
        ("ln-s1", "median forecast"), ("sw-band", "68% band"), ("sw-dot-out", "ONS outturn"),
        ("ln-edge", f"last quarter with an outturn ({quarters[n_out - 1]})"),
    ], unit="% change on a year earlier", notes=[f"Each panel starts at the frozen 2024Q2 edge; the "
              f"{npts - n_out} quarters right of the dashed rule are not evaluated."])


def chart_obr_computed_share():
    """Two stacked bars: how much of the OBR scorecard the model actually computes.

    The point of the chart is that a headline "within band" rate is meaningless
    until the passthrough variables — held at the OBR published value, so scoring
    zero error trivially — are separated out from the ones the model computes.
    """
    d = load_transcribed()["obr_computed_share"]
    total = d["total"]
    computed, passthrough = d["computed"], d["passthrough"]
    grades = d["grades"]

    W, H = 760, 314
    x0, x1 = 64.0, 724.0
    span = x1 - x0
    per_var = span / total

    in_band = sum(g["count"] for g in grades if g["in_band"])
    trivial = sum(g["count"] for g in grades if g.get("trivial"))
    nontrivial = computed - trivial
    off = next(g for g in grades if g["key"] == "off")

    desc = (
        f"Two stacked bars. Of {total} headline variables in the OBR emulator "
        f"calibration scorecard, {computed} are actually computed by the model and "
        f"{passthrough} are passthrough, held at the OBR published value and therefore "
        f"scoring zero error trivially. Of the {computed} computed, "
        + ", ".join(f"{g['count']} {grade_phrase(g)}" for g in grades)
        + f". {in_band} of the {computed}, or {100 * in_band / computed:.0f} per cent, land "
        f"within band, but {word(trivial)} of those is an accounting identity that closes "
        f"over passthrough inputs, so {in_band - trivial} of the {nontrivial} non-trivial "
        f"computed variables are in band. The worst are "
        + " and ".join(off["examples"])
        + "."
    )

    rows_y = (40.0, 132.0)
    bar_h = 40.0
    out = svg_open(x1 - x0, rows_y[1] + bar_h - 4, "obr-computed-share",
                   "How much of the OBR emulator scorecard the model actually computes", desc,
                   origin=(x0, 4))

    # Row 1 — computed vs passthrough, out of the full scorecard. Segment labels
    # sit under their segment, at the two ends of the bar, rather than on it.
    split = x0 + computed * per_var
    y = rows_y[0]
    out.append(f'<text class="vc-lab vc-y" x="{n(x0)}" y="{n(y)}">{total} headline scorecard variables</text>')
    out.append(f'<rect class="vc-b1" x="{n(x0)}" y="{n(y)}" width="{n(split - x0 - 2)}" height="{bar_h:g}"/>')
    out.append(f'<rect class="vc-b3" x="{n(split)}" y="{n(y)}" width="{n(x1 - split)}" height="{bar_h:g}"/>')
    out.append(f'<text class="vc-val vc-x" x="{n(x0)}" y="{n(y + bar_h)}" text-anchor="start">'
               f'{computed} computed</text>')
    out.append(f'<text class="vc-rowlab vc-x" x="{n(x1)}" y="{n(y + bar_h)}" text-anchor="end">'
               f'{passthrough} passthrough, held at the OBR value</text>')

    # Row 2 — the computed variables broken down by grade, on the same scale, so
    # the second bar reads as a zoom into the first bar's left-hand segment.
    # The grades are named in the HTML legend: a one-variable segment is too
    # narrow on a phone to carry its own label.
    y = rows_y[1]
    out.append(f'<text class="vc-lab vc-y" x="{n(x0)}" y="{n(y)}">of which, the {computed} the model '
               f'computes</text>')
    x = x0
    for g in grades:
        w = g["count"] * per_var
        # The last two grades share a fill, so 'off' also carries a dashed
        # outline (and its own legend swatch).
        outline = " vc-outline" if g["key"] == "off" else ""
        out.append(f'<rect class="vc-b{g["series"]}{outline}" x="{n(x)}" y="{n(y)}" '
                   f'width="{n(w - 2)}" height="{bar_h:g}"/>')
        x += w
    out.append("</svg>")
    legend = [((f'sw-b{g["series"]}d' if g["key"] == "off" else f'sw-b{g["series"]}'),
               f'{esc(g["label"])} {g["count"]}') for g in grades]
    notes = [
        f'<span class="vc-warn">Only {in_band - trivial} of the {nontrivial} non-trivial '
        f'computed variables are in band.</span>',
        f'{word(trivial).capitalize()} of the {in_band} in-band passes is an accounting '
        f'identity over passthrough inputs.',
        esc(d["bands_note"]),
    ]
    return chartkit.figure("\n".join(out), legend=legend, notes=notes, min_h=170)


def grade_phrase(g) -> str:
    """'are fair', 'is an identity', 'fit badly', 'are off' for the description."""
    if g["key"] == "identity" and g["count"] == 1:
        return "is an identity"
    if g["key"] == "badfit":
        return g["label"]
    return f"{'is' if g['count'] == 1 else 'are'} {g['label']}"


# Display order and labels for the skill matrix. Ordered roughly best to worst so
# the eye can read down the column; the ordering is presentational, the numbers
# come from rolling_evaluation.json.
SKILL_ROWS = [
    ("bank_rate", "Bank Rate"),
    ("cpisa", "UK CPI"),
    ("world_cpi", "World CPI"),
    ("oil_price", "Oil price"),
    ("cpi_energy", "CPI energy"),
    ("uk_gdp", "UK real GDP"),
    ("world_gdp", "World GDP"),
    ("eri", "Exchange rate"),
]

SIGNIF = 0.05



def chart_svar_skill_all():
    horizons, ratio, pval, meta = load_rolling_eval()
    W, H = 760, 420
    x_one, per_unit = 370.8, 883.0        # value 1.0 at x_one
    def xs(v):
        return x_one + (v - 1.0) * per_unit

    last = horizons[-1]
    best = min(SKILL_ROWS, key=lambda r: ratio[last][r[0]])
    worst = max(SKILL_ROWS, key=lambda r: ratio[last][r[0]])
    n_win_1 = sum(1 for k, _ in SKILL_ROWS if ratio[horizons[0]][k] < 1)
    n_win_last = sum(1 for k, _ in SKILL_ROWS if ratio[last][k] < 1)
    adj = meta["multiplicity"]["headline"]["drift"]

    desc = (
        f"Dot matrix of forecast error relative to a random walk with drift, "
        f"{word(len(SKILL_ROWS))} variables by {word(len(horizons))} quarterly horizons, from "
        f"{meta['origins']} expanding-window origins. Position alone carries better or worse: "
        f"a dot left of the 1.0 rule means the model beats the benchmark, right of it means "
        f"the benchmark wins. Filled dots mark differences significant at 5 per cent by a "
        f"Diebold-Mariano test, hollow dots differences that are not statistically "
        f"distinguishable; those p-values are pairwise and the grid runs {adj['tests']} "
        f"tests, none of which clears a 10 per cent false-discovery rate once adjusted "
        f"together — the smallest adjusted q-value is {adj['min_q']:.2f}. "
        + "; ".join(
            f"{label} runs {ratio[horizons[0]][key]:.2f} at one quarter to "
            f"{ratio[last][key]:.2f} at {last}"
            for key, label in SKILL_ROWS
        )
        + f". {best[1]} is the best at the longest horizon and {worst[1]} the worst. "
        f"Against this harder benchmark only {word(n_win_1)} of {word(len(SKILL_ROWS))} "
        f"variables beat naive at one quarter and {word(n_win_last)} at {last}. The number "
        f"at the end of each row is that row's ratio at horizon {last}."
    )

    # Each row: the variable's name and its h=8 ratio above, the dots below,
    # across the full width, so names never squeeze the axis on a phone.
    lo_x, hi_x = xs(0.76), xs(1.36)
    pitch, top = 50.0, 40.0
    base = top + pitch * (len(SKILL_ROWS) - 1) + 14
    out = svg_open(hi_x - lo_x, base - 4, "svar-skill-all",
                   "BoE SVAR forecast skill against a random walk with drift, "
                   "all eight variables", desc, origin=(lo_x, 4))

    for tick in (0.8, 0.9, 1.0, 1.1, 1.2, 1.3):
        x = xs(tick)
        cls = "vc-zero" if tick == 1.0 else "vc-grid"
        out.append(f'<line class="{cls}" x1="{n(x)}" y1="{n(top - 30)}" x2="{n(x)}" y2="{n(base)}"/>')
        out.append(f'<text class="vc-tick vc-x" x="{n(x)}" y="{n(base)}" text-anchor="middle">{tick:.1f}</text>')

    for i, (key, label) in enumerate(SKILL_ROWS):
        y = top + pitch * i
        values = [ratio[h][key] for h in horizons]
        out.append(f'<text class="vc-rowlab vc-y" x="{n(lo_x)}" y="{n(y - 6)}">'
                   f'{esc(label)} <b class="vc-num">{ratio[last][key]:.2f}</b></text>')
        out.append(f'<line class="vc-grid" x1="{n(xs(min(values)))}" y1="{n(y)}" '
                   f'x2="{n(xs(max(values)))}" y2="{n(y)}"/>')
        for h in horizons:
            v, p = ratio[h][key], pval[h][key]
            r = 4.0 if h == last else 3.0
            # One colour for every dot: better-or-worse is already carried by
            # which side of the 1.0 rule the dot sits on, so colouring by that
            # again would be an encoding that adds nothing. Fill vs outline is
            # the only categorical channel here, and it means significance.
            if p < SIGNIF:
                out.append(f'<circle class="vc-s1-dot" cx="{n(xs(v))}" cy="{n(y)}" '
                           f'r="{r}"/>')
            else:
                out.append(f'<circle cx="{n(xs(v))}" cy="{n(y)}" r="{r}" fill="none" '
                           f'stroke-width="1.2"/>')

    out.append("</svg>")
    return chartkit.figure("\n".join(out), min_h=420, legend=[
        ("sw-dot1", "significant at 5%, pairwise"),
        ("sw-ring", "not distinguishable"),
    ], unit="RMSE &divide; drifting-random-walk RMSE, horizons 1&ndash;8 quarters", notes=[
        "Left of the 1.0 rule the model is better; right of it the benchmark is.",
        f"The large dot, and the number after each name, is h={last}. Smallest adjusted q "
        f'over the {adj["tests"]} cells: {adj["min_q"]:.2f}.',
    ])


def chart_svar_winrate():
    """How many of the eight variables beat the drift benchmark, by horizon.

    This was a stacked column of wins / significant wins / losses summing to
    eight at every horizon, so every column was the same height and the height
    carried nothing; the count label was also drawn above the top of the wins
    stack, i.e. inside the losses segment it was not describing. What actually
    varies is the win count, so that is what the bar height encodes now, with
    the eight-variable ceiling drawn as a reference line rather than as a
    segment. Losses are the gap between the column and that line, and are
    stated in the description; the significance split stays as the shaded lower
    part of the column, with the count repeated as text under each column so
    the distinction never rests on fill alone.
    """
    horizons, ratio, pval, meta = load_rolling_eval()
    keys = [k for k, _ in SKILL_ROWS]
    total = len(keys)

    counts = []
    for h in horizons:
        wins = [k for k in keys if ratio[h][k] < 1]
        sig = [k for k in wins if pval[h][k] < SIGNIF]
        lost_sig = [k for k in keys if ratio[h][k] >= 1 and pval[h][k] < SIGNIF]
        counts.append({"h": h, "wins": len(wins), "sig": len(sig),
                       "lost_sig": len(lost_sig)})

    # The pairwise p-values above are not the last word: the same artifact
    # carries the Benjamini-Hochberg adjustment over the whole grid, and
    # against this benchmark nothing survives it.
    adj = meta["multiplicity"]["headline"]["drift"]
    worse = [c["h"] for c in counts if c["lost_sig"]]

    W, H = 760, 344
    x0, x1 = 64, 724
    y_zero, y_full = 248.0, 76.0
    per_var = (y_zero - y_full) / total

    desc = (
        f"Column chart, one column per forecast horizon from one to {word(horizons[-1])} "
        f"quarters. Column height is the number of the model's {word(total)} forecast "
        f"variables whose root mean squared error is below that of a random walk with "
        f"drift; a dashed reference line across the top marks all {word(total)}. The counts "
        f"are "
        + ", ".join(str(c["wins"]) for c in counts)
        + f", so between {min(c['wins'] for c in counts)} and "
        f"{max(c['wins'] for c in counts)} of the {total} beat the benchmark at any horizon "
        f"and the remaining "
        + ", ".join(str(total - c["wins"]) for c in counts)
        + " do not. The shaded lower part of each column is the subset whose difference is "
        "significant at 5 per cent on an unadjusted pairwise Diebold-Mariano test: "
        + ", ".join(str(c["sig"]) for c in counts)
        + f". Those p-values are pairwise and the grid runs {adj['tests']} tests; under a "
        f"Benjamini-Hochberg adjustment none of them reaches a 10 per cent false-discovery "
        f"rate and the smallest adjusted q-value is {adj['min_q']:.2f}, so on the adjusted "
        f"reading the significant-win count is zero at every horizon."
        + (f" At horizon{'s' if len(worse) > 1 else ''} "
           + " and ".join(str(h) for h in worse)
           + " one variable is significantly worse than the benchmark." if worse else "")
    )

    out = svg_open(x1 - x0, y_zero - y_full + 30, "svar-winrate",
                   "How many of eight variables beat a drifting random walk, by horizon", desc,
                   origin=(x0, y_full - 24))

    for k in (2, 4, 6):
        y = y_zero - k * per_var
        out.append(f'<line class="vc-grid" x1="{x0}" y1="{n(y)}" x2="{x1}" y2="{n(y)}"/>')
        out.append(chartkit.ytick(x0, y, str(k)))
    out.append(f'<line class="vc-zero" x1="{x0}" y1="{n(y_zero)}" x2="{x1}" y2="{n(y_zero)}"/>')
    # The eight-variable ceiling is a reference, not a segment: no column's
    # height is fixed by it, and the empty space above each column is the
    # count of variables that do not beat the benchmark.
    out.append(f'<line class="vc-edge" x1="{x0}" y1="{n(y_full)}" x2="{x1}" y2="{n(y_full)}"/>')
    out.append(chartkit.ytick(x0, y_full, f"all {total} variables"))

    # Columns start 40 units in, clear of the y labels inside the plot.
    bar_w, pitch = 54, 78
    for i, c in enumerate(counts):
        bx = x0 + 40 + i * pitch
        mid = bx + bar_w / 2
        y_sig = y_zero - c["sig"] * per_var
        y_win = y_zero - c["wins"] * per_var
        if c["sig"]:
            out.append(f'<rect class="vc-b1" x="{n(bx)}" y="{n(y_sig)}" width="{bar_w}" '
                       f'height="{n(y_zero - y_sig)}"/>')
        if c["wins"] > c["sig"]:
            # 2px of surface between the two parts so they read as two.
            top = y_sig - 2 if c["sig"] else y_sig
            out.append(f'<rect class="vc-b2" x="{n(bx)}" y="{n(y_win)}" width="{bar_w}" '
                       f'height="{n(top - y_win)}"/>')
        # Above the column it counts, not above a segment it does not.
        out.append(f'<text class="vc-val" x="{n(mid)}" y="{n(y_win - 6)}" '
                   f'text-anchor="middle">{c["wins"]}</text>')
        out.append(f'<text class="vc-tick vc-x" x="{n(mid)}" y="{n(y_zero)}" text-anchor="middle">'
                   f'h={c["h"]}</text>')
        # Second label row: the significant part of the column, as a number,
        # so the split never rests on fill alone.
        out.append(f'<text class="vc-tick vc-x2" x="{n(mid)}" y="{n(y_zero)}" text-anchor="middle">'
                   f'{c["sig"]}</text>')
    out.append("</svg>")
    return chartkit.figure("\n".join(out), legend=[
        ("sw-b1", "beats it, p&lt;0.05 unadjusted (count under each column)"),
        ("sw-b2", "beats it, not distinguishable"),
    ], unit=f"Variables (of {total}) with lower RMSE than a random walk with drift", notes=[
        f"Column height = variables with lower RMSE than a random walk with drift, out of "
        f"{total}; the rest do not beat it.",
        f'<span class="vc-warn">Adjusted together, none of the {adj["tests"]} tests clears a '
        f'10% false-discovery rate (smallest q = {adj["min_q"]:.2f}).</span>',
    ], wrap_class="vc-two-rows")


def chart_svar_coverage():
    data = json.loads(
        (ROOT / "papers" / "boe-svar" / "figures" / "coverage_evaluation.json").read_text()
    )
    cov = data["coverage"]
    horizons = list(range(1, data["horizons"] + 1))

    def mean_cov(level, h):
        vals = cov[str(level)][f"h{h}"].values()
        return sum(vals) / len(vals)

    series = {lv: [mean_cov(lv, h) for h in horizons] for lv in (68, 90)}
    # The mean is not the whole story: at every horizon the eight variables are
    # spread across tens of points, and the worst of them is far below the mean.
    # Plot that spread, and set the axis floor below it rather than above it.
    spread = {lv: [(min(cov[str(lv)][f"h{h}"].values()),
                    max(cov[str(lv)][f"h{h}"].values())) for h in horizons]
              for lv in (68, 90)}
    worst_lv, worst_h, worst_key, worst_v = min(
        ((lv, h, k, v) for lv in (68, 90) for h in horizons
         for k, v in cov[str(lv)][f"h{h}"].items()),
        key=lambda t: t[3],
    )
    worst_var = dict(SKILL_ROWS).get(worst_key, worst_key)

    W, H = 760, 330
    x0, x1 = 58.0, 724.0
    step = (x1 - x0) / (len(horizons) - 1)
    xs = [x0 + i * step for i in range(len(horizons))]
    # Floor the axis below the worst cell rather than above it, so nothing is
    # clipped and the shortfall is not compressed against the frame.
    hi_v = 1.0
    lo_v = math.floor((worst_v - 0.03) * 20) / 20
    base_y, top_y = 282.0, 56.0

    def ymap(v):
        return base_y - (v - lo_v) * (base_y - top_y) / (hi_v - lo_v)

    desc = ("Line chart of empirical interval coverage by forecast horizon, averaged "
            "across the eight model variables, against the nominal 68 and 90 percent "
            "levels; a vertical bar at each horizon spans the best and worst variable. " +
            "; ".join(
                f"{lv}% band, mean coverage at horizons one to eight: " +
                ", ".join(f"{v:.0%}" for v in series[lv])
                for lv in (68, 90)
            ) +
            f". The 68 per cent band covers {series[68][0]:.0%} at one quarter, just above "
            f"nominal, and falls below nominal from horizon two onward to {series[68][-1]:.0%} "
            f"at eight; the 90 per cent band under-covers at every horizon, from "
            f"{series[90][0]:.0%} down to {series[90][-1]:.0%}. The mean hides how bad the "
            f"worst variable is: the lowest cell in the grid is {worst_var} at the "
            f"{worst_lv} per cent band, horizon {worst_h}, covering {worst_v:.0%}. The window "
            "includes the Covid quarters and the evaluation model carries no Covid "
            "dummies, which depresses coverage.")

    out = svg_open(x1 - x0 + 16, base_y - top_y + 12, "svar-coverage",
                   f"BoE SVAR: empirical band coverage across {data['origins']} origins", desc,
                   origin=(x0 - 8, top_y - 6))
    for k in range(int(math.ceil(lo_v * 10)), 11):
        v = k / 10
        out.append(f'<line class="vc-grid" x1="{n(x0)}" y1="{n(ymap(v))}" x2="{n(x1)}" y2="{n(ymap(v))}"/>')
        out.append(chartkit.ytick(x0, ymap(v), f"{v:.0%}"))
    # Both bands are this model's, so neither is drawn in the dashed
    # "official" style: 68% is the headline series, 90% the labelled neutral.
    for lv, cls, dodge in ((90, "vc-s3", 4.0), (68, "vc-s1", -4.0)):
        # nominal level as a reference line
        out.append(
            f'<line class="vc-ref" x1="{n(x0)}" y1="{n(ymap(lv / 100))}" '
            f'x2="{n(x1)}" y2="{n(ymap(lv / 100))}"/>'
        )
        for x, (v_lo, v_hi) in zip(xs, spread[lv]):
            out.append(f'<line class="{cls} vc-spread" x1="{n(x + dodge)}" y1="{n(ymap(v_hi))}" '
                       f'x2="{n(x + dodge)}" y2="{n(ymap(v_lo))}"/>')
        pts = " ".join(f"{n(x)},{n(ymap(v))}" for x, v in zip(xs, series[lv]))
        out.append(f'<polyline class="{cls}" points="{pts}"/>')
    # Mid-plot, where neither reference label can be mistaken for a series
    # end-label.
    x_nom = (xs[3] + xs[4]) / 2
    out.append(f'<text class="vc-tick vc-y" x="{n(x_nom)}" y="{n(ymap(0.68))}" text-anchor="middle">nominal 68%</text>')
    out.append(f'<text class="vc-tick vc-y" x="{n(x_nom)}" y="{n(ymap(0.90))}" text-anchor="middle">nominal 90%</text>')
    for i, h in enumerate(horizons):
        out.append(chartkit.xtick(xs[i], base_y, f"h{h}", i, len(horizons) - 1))
    out.append("</svg>")
    return chartkit.figure("\n".join(out), min_h=260, legend=[
        ("ln-s1", "68% band, mean coverage across variables"),
        ("ln-s3", "90% band"),
        ("ln-ref", "nominal coverage"),
    ], unit="Share of outturns inside the band, %", notes=[f"Vertical bars span the best and worst of the eight variables; lowest cell "
              f"{worst_v:.0%} ({worst_var}, {worst_lv}% band, h{worst_h})."])


def chart_hank_targets():
    """The us-hank replication that could actually fail.

    This chart used to tabulate the eight rows of ``targets``, six of which are
    literal entries in the calibration dictionary held fixed through the solve.
    "target 10, achieved 10" on capital is a constant equalling itself: its zero
    deviation is an identity, so the chart was a column of eight passes that no
    implementation could ever fail, and the description told screen-reader users
    that beta was "the calibrated free parameter that hits the wealth targets" —
    the framing the artifact's own ``beta_note`` retired.

    The comparison that has somewhere to miss is ``published_table_b3``: the
    parameters the model solves for internally, against the values Auclert,
    Bardóczy, Rognlie and Straub (2021) print in Table B.III — including the one
    that misses by 17 per cent. That is what the rows show now; the calibration
    inputs are summarised underneath as what they are.
    """
    data = json.loads(
        (ROOT / "papers" / "us-hank" / "figures" / "replication.json").read_text()
    )
    b3 = data["published_table_b3"]
    params = b3["parameters"]
    miss = b3["unexplained_discrepancy"]
    targets = data["targets"]
    res = data["residuals"]

    def how(p):
        return "numerically" if p["solved"].startswith("numerically") else "analytically"

    rows = [{"name": p["name"], "tag": how(p), "pub": p["published"], "ours": p["ours"]}
            for p in params]
    rows.append({"name": miss["name"], "tag": "unresolved",
                 "pub": miss["published"], "ours": miss["ours"]})

    imposed = [t for t in targets if "imposed" in t["kind"]]
    solver = [t for t in targets if "through a solver" in t["kind"]]
    agree = len(params)

    def short(name):
        return name.split(" (")[0]

    notes = [
        "Constants equalling themselves: "
        + ", ".join(f'{short(t["name"])} {t["target"]:g}' for t in imposed) + ".",
        "Solver targets: "
        + ", ".join(f'{short(t["name"])} {t["target"]:g} hit to '
                    f'{abs(t["achieved"] - t["target"]):.1e}' for t in solver)
        + " — tolerances, not accuracies.",
        f'Market clearing: goods {res[0]["value"]:.1e} untargeted (Walras’ law), '
        f'assets {res[1]["value"]:.1e} is the solver’s own target.',
    ]

    # A table, not a drawing: it is rows of numbers, and an HTML table stays
    # readable at 375 px (it scrolls inside its own wrapper) where an SVG
    # table's text shrank to 5 px. The description the SVG carried for screen
    # readers is the table itself now, plus the notes under it.
    body = []
    for r in rows:
        warn = ' class="vc-warn"' if r["tag"] == "unresolved" else ""
        body.append(
            f'<tr><th scope="row">{esc(r["name"])}</th><td{warn}>{r["tag"]}</td>'
            f'<td class="num">{r["pub"]:g}</td><td class="num">{r["ours"]:.7g}</td>'
            f'<td class="num">{abs(r["ours"] - r["pub"]):.1e}</td></tr>')
    parts = [
        '<div class="vc-fig vc-tablefig" data-chart="hank-targets">',
        '<div class="table-scroll"><table class="vc-table">',
        "<caption>US HANK: internally solved parameters vs Auclert et al. (2021) Table B.III</caption>",
        '<thead><tr><th scope="col">parameter</th><th scope="col">solved</th>'
        '<th scope="col" class="num">published</th><th scope="col" class="num">ours</th>'
        '<th scope="col" class="num">|diff|</th></tr></thead>',
        "<tbody>", *body, "</tbody></table></div>",
        f'<p class="vc-notes"><span class="vc-warn">{word(agree).capitalize()} of seven agree '
        f'to the last published digit; {miss["name"].split()[0]} misses by '
        f'{fmt_signed(miss["gap_pct"], 1)}%.</span></p>',
        '<p class="vc-notes"><strong>Calibration inputs</strong>, held fixed through the solve, '
        'so their deviations are identities:<br />' + "<br />".join(esc(t) for t in notes) + "</p>",
        f"</div>{chartkit.END}",
    ]
    return "\n".join(parts)


def chart_define_emissions():
    rows = load_define_emissions()
    # The percentage is the gated quantity and is pinned in the adapter's
    # reference_outputs.json; recomputing it from the whole-MtCO2e levels in the
    # CSV drifts by up to 0.2 points and disagreed with the number the page and
    # VALIDATION.md publish. Levels come from the CSV, percentages from the gate.
    gated = load_transcribed()["define_emissions"]["gated_ratios"]
    gap = {yr: (gated[yr] - 1) * 100 for yr, _, _ in rows}
    W, H = 760, 304
    base_y, top_y = 258.0, 26.0
    y_max = 450.0
    scale = (base_y - top_y) / y_max
    bar_w, bar_gap = 79.2, 11.9
    group_step = 220.0
    first_centre = 174.0

    # One decimal, matching the visible caption and table. At :.0f the 2025
    # gap rendered as "-3 per cent" against the "-3.5%" a sighted reader sees
    # on the same page — a screen-reader user got a different number on a
    # validation page whose whole point is that the numbers are gated.
    parts = "; ".join(f"{yr}: pinned run {p:g}, published table {m:g}, "
                      f"a gated ratio of {gated[yr]:.3f}, a gap of {gap[yr]:.1f} per cent"
                      for yr, p, m in rows)
    desc = (
        "Grouped bar chart of S1 baseline total UK emissions in MtCO2e per year, "
        "the cached pinned run of upstream commit 846081a against the manual's "
        f"published Table 4. {parts}. The pinned code runs below the published "
        "table and the gap widens with horizon; what is gated is the ratio of the "
        "two, pinned to plus or minus 0.02, so any further drift fails loudly. "
        "Bar heights are the levels in "
        "validation/figures/data/define_emissions_divergence.csv, rounded to whole "
        "MtCO2e; the percentages are the gated ratios themselves, which is why they "
        "differ slightly from the ratio of the rounded bars."
    )
    x0, x1 = 24.0, 724.0      # room for the y labels left of the first bar
    out = svg_open(x1 - x0, base_y - top_y + 12, "define-emissions",
                   "DEFINE-UK: S1 baseline total emissions — pinned run vs manual Table 4 (MtCO2e/yr)",
                   desc, origin=(x0, top_y - 6))

    t = 0.0
    while t <= 400 + 1e-9:
        y = base_y - t * scale
        cls = "vc-zero" if t == 0 else "vc-grid"
        out.append(f'<line class="{cls}" x1="{x0:g}" y1="{n(y)}" x2="{x1:g}" y2="{n(y)}"/>')
        if t:
            out.append(chartkit.ytick(x0, y, f"{t:g}"))
        t += 100

    for g, (yr, p, m) in enumerate(rows):
        centre = first_centre + g * group_step
        for k, (cls, v) in enumerate((("vc-b1", p), ("vc-b2", m))):
            x = centre - bar_w - bar_gap / 2 + k * (bar_w + bar_gap)
            h = v * scale
            y = base_y - h
            out.append(f'<rect class="{cls}" x="{n(x)}" y="{n(y)}" width="{bar_w:g}" height="{n(h)}"/>')
            cx = x + bar_w / 2
            out.append(f'<text class="vc-val" x="{n(cx)}" y="{n(y - 6)}" text-anchor="middle">{v:g}</text>')
        gap_txt = f"{gap[yr]:+.1f}%".replace("-", "\u2212")
        out.append(f'<text class="vc-lab vc-x" x="{n(centre)}" y="{n(base_y)}" '
                   f'text-anchor="middle">{esc(yr)} ({gap_txt})</text>')

    out.append("</svg>")
    return chartkit.figure("\n".join(out), legend=[
        ("sw-b1", "pinned run"), ("sw-b2", "published Table 4"),
    ], unit="S1 baseline total UK emissions, MtCO<sub>2</sub>e a year")


# chart id -> (builder, page that owns it). Charts live on the validation
# subtab of the model they provide evidence for, except pe-costing, which sits
# on the microsimulation overview so the platform's central model opens on a
# figure rather than on prose.
BUILDERS = [
    ("pe-costing", chart_pe_costing, "pe/index.html"),
    ("obr-anchored", chart_obr_anchored, "obr/validation/index.html"),
    ("obr-reform", chart_obr_reform, "obr/validation/index.html"),
    ("obr-computed-share", chart_obr_computed_share, "obr/validation/index.html"),
    ("obr-freerun", chart_obr_freerun, "obr/validation/index.html"),
    ("obr-outturn", chart_obr_outturn, "obr/validation/index.html"),
    ("svar-fevd", chart_svar_fevd, "svar/validation/index.html"),
    ("svar-fan", chart_svar_fan, "svar/validation/index.html"),
    ("svar-coverage", chart_svar_coverage, "svar/validation/index.html"),
    ("svar-skill-all", chart_svar_skill_all, "svar/validation/index.html"),
    ("svar-winrate", chart_svar_winrate, "svar/validation/index.html"),
    ("frbus-residuals", chart_frbus_residuals, "frb-us/validation/index.html"),
    ("hank-targets", chart_hank_targets, "us-hank/validation/index.html"),
    ("define-emissions", chart_define_emissions, "define/validation/index.html"),
]


def chart_re(chart_id: str) -> re.Pattern:
    return chartkit.block_re(chart_id)


def as_block(built) -> str:
    """A builder returns a finished vc-fig block, or a bare SVG for figure()."""
    if built.startswith('<div class="vc-fig'):
        return built
    return chartkit.figure(built)


def render_page(page: str, html: str) -> str:
    for chart_id, build, target in BUILDERS:
        if target != page:
            continue
        pattern = chart_re(chart_id)
        matches = pattern.findall(html)
        if len(matches) != 1:
            sys.exit(
                f'expected exactly one data-chart="{chart_id}" SVG in {page}, '
                f"found {len(matches)}"
            )
        svg = as_block(build())
        html = pattern.sub(lambda _m: svg, html)
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if any page is out of date")
    args = ap.parse_args()

    pages = []
    for _, _, target in BUILDERS:
        if target not in pages:
            pages.append(target)

    stale = []
    written = 0
    for page in pages:
        path = ROOT / page
        html = path.read_text()
        new = render_page(page, html)
        if new == html:
            continue
        if args.check:
            stale.append(page)
        else:
            path.write_text(new)
            written += 1
            print(f"rewrote charts in {page}")

    if args.check:
        if stale:
            print("stale chart pages; run: python3 validation/figures/make_charts.py")
            for page in stale:
                print(f"  {page}")
            return 1
        print("validation charts are up to date on all model pages.")
        return 0
    if not written:
        print("no change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
