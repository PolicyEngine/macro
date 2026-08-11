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
    def ymap(v):
        return zero_y - v * per_unit

    mape_g = sum(abs(v) for v in gdp) / len(gdp)
    mape_c = sum(abs(v) for v in cons) / len(cons)

    desc = (
        f"Line chart. Quarterly percentage deviation of the anchored emulator from the "
        f"published March 2026 EFO, {quarters[0]} to {quarters[-1]}. Real GDP ranges from "
        f"{min(gdp):+.2f}% to {max(gdp):+.2f}% (mean absolute deviation {mape_g:.2f}%); "
        f"consumption from {min(cons):+.2f}% to {max(cons):+.2f}% (mean absolute deviation "
        f"{mape_c:.2f}%). Both series stay well inside the plus or minus 1% band at which "
        f"continuous integration hard-fails the build, which is off the top and bottom of "
        f"this frame."
    )
    out = svg_open(W, H, "obr-anchored",
                   "obr-macro: anchored baseline vs March 2026 EFO, quarterly deviation",
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
            " The 2028–29 emulator figure is interpolated between the scored endpoints "
            "£6.46bn in 2026 and £7.38bn in 2030.")
    return grouped_bars(
        chart_id, title, desc, groups, y_max=10, y_step=2, fmt=lambda v: f"{v:.2f}")


def chart_obr_reform():
    return _reform_costing(
        "obr-reform",
        "obr-macro: 1p on the basic rate, ours vs HMRC ready reckoner (£bn/yr)")


def chart_pe_costing():
    return _reform_costing(
        "pe-costing",
        "pe-microsim: 1p on the UK basic rate, our static costing vs the HMRC "
        "ready reckoner (£bn/yr)")


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
        f"{efo[-1]:.1f}. The anchored emulator is visually indistinguishable from it, running "
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
    out = svg_open(W, H, "obr-freerun",
                   "obr-macro: real GDP level, anchored vs free-running vs the March 2026 EFO (£bn/qtr)",
                   desc)

    out.append('<line class="vc-s1" x1="58" y1="26" x2="84" y2="26"/><circle class="vc-s1-dot" cx="71" cy="26" r="3"/>')
    out.append(f'<text class="vc-lab" x="92" y="30">anchored ({mad_a:.2f}% MAD)</text>')
    out.append('<line class="vc-s2" x1="288" y1="26" x2="314" y2="26"/><circle class="vc-s2-dot" cx="301" cy="26" r="3"/>')
    out.append(f'<text class="vc-lab vc-lab2" x="322" y="30">free-running ({mad_f:.2f}% MAD)</text>')
    out.append('<line class="vc-grid" x1="540" y1="26" x2="566" y2="26"/><text class="vc-lab" x="574" y="30">EFO Mar 2026</text>')

    tick = lo
    while tick <= hi + 1e-9:
        y = ymap(tick)
        out.append(f'<line class="vc-grid" x1="{x0:.0f}" y1="{n(y)}" x2="{x1:.0f}" y2="{n(y)}"/>')
        out.append(f'<text class="vc-tick" x="48" y="{n(y + 4)}" text-anchor="end">{tick:g}</text>')
        tick += 20

    for cls, series in (("vc-s3", efo), ("vc-s1", anchored), ("vc-s2", freerun)):
        pts = " L".join(f"{n(xs[i])} {n(ymap(v))}" for i, v in enumerate(series))
        out.append(f'<path class="{cls}" d="M{pts}"/>')

    tick_idx = [i for i, q in enumerate(quarters) if q.endswith("Q1")]
    if len(quarters) - 1 not in tick_idx:
        tick_idx.append(len(quarters) - 1)
    for i in tick_idx:
        out.append(f'<text class="vc-tick" x="{n(xs[i])}" y="312" text-anchor="middle">{quarters[i]}</text>')

    out.append("</svg>")
    return "\n".join(out)


def chart_obr_outturn():
    rows = load_outturn()
    W, H = 760, 304
    base_y, top_y = 258.0, 26.0
    y_max = 0.7
    scale = (base_y - top_y) / y_max
    bar_w, bar_gap = 40.0, 8.0
    group_step = 165.0
    first_centre = 138.5

    parts = "; ".join(f"{q}: emulator {m:.2f}, EFO {e:.2f}, ONS {o:g}" for q, m, e, o in rows)
    desc = (
        f"Grouped bar chart, percentage quarter-on-quarter real GDP growth for the four "
        f"quarters with ONS outturns since anchoring. {parts}. The emulator tracks the three "
        f"2025 outturns to within 0.06 points; both the emulator and the November EFO it "
        f"inherits miss the strong 0.6 per cent 2026Q1 outturn by roughly a quarter of a point. "
        f"Data from papers/obr-macro/figures/fig_outturn_data.csv. Coordinates: value v maps to "
        f"y = {base_y:g} - v * {scale:.1f} on a 0 to {y_max:g} axis."
    )
    out = svg_open(W, H, "obr-outturn",
                   "obr-macro: quarterly real GDP growth — emulator vs EFO Nov 2025 vs ONS outturn (% q/q)",
                   desc)

    out.append('<rect class="vc-b1" x="64" y="8" width="14" height="10"/><text class="vc-lab" x="84" y="17">emulator</text>')
    out.append('<rect class="vc-b3" x="196" y="8" width="14" height="10"/><text class="vc-lab" x="216" y="17">EFO Nov 2025</text>')
    out.append('<rect class="vc-b2" x="356" y="8" width="14" height="10"/><text class="vc-lab" x="376" y="17">ONS outturn</text>')

    t = 0.0
    while t <= 0.6 + 1e-9:
        y = base_y - t * scale
        cls = "vc-axis" if t == 0 else "vc-grid"
        out.append(f'<line class="{cls}" x1="64" y1="{n(y)}" x2="724" y2="{n(y)}"/>')
        out.append(f'<text class="vc-tick" x="54" y="{n(y + 4)}" text-anchor="end">{t:g}</text>')
        t += 0.2

    for g, (q, m, e, o) in enumerate(rows):
        centre = first_centre + g * group_step
        for k, (cls, v) in enumerate((("vc-b1", m), ("vc-b3", e), ("vc-b2", o))):
            x = centre - 60.0 + k * (bar_w + bar_gap)
            h = v * scale
            y = base_y - h
            out.append(f'<rect class="{cls}" x="{n(x)}" y="{n(y)}" width="{bar_w:g}" height="{n(h)}"/>')
            out.append(f'<text class="vc-val" x="{n(x + bar_w / 2)}" y="{n(y - 6)}" text-anchor="middle">{v:.2f}</text>')
        out.append(f'<text class="vc-lab" x="{n(centre)}" y="296" text-anchor="middle">{q}</text>')

    out.append("</svg>")
    return "\n".join(out)


def chart_svar_fan():
    quarters, series, outturns = load_svar_fan()
    W, H = 760, 340
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
        f"the 68 per cent band; RMSE {rmse['gdp']:.2f} percentage points for both variables. GDP "
        f"medians run {med_g} per cent over the evaluated quarters against outturns of {out_g}; "
        f"CPI medians {med_c} against outturns of {out_c}. Medians and 68 per cent bands from "
        f"papers/boe-svar/figures/figure_numbers.json (forecast_table, entries [median, lo68, "
        f"hi68]); ONS outturns from papers/boe-svar/figures/make_figures.py. Coordinates: GDP "
        f"panel maps value v to y = {base_y:g} - (v + 1) * {per_unit:g} for the -1 to 3 per cent "
        f"axis; CPI panel y = {base_y:g} - (v - 1) * {per_unit:g} for the 1 to 5 per cent axis; "
        f"quarter i of {npts} maps to x = 58 + i * {panels['gdp']['step']:.3f} (GDP) or "
        f"416 + i * {panels['cpi']['step']:.3f} (CPI)."
    )
    out = svg_open(W, H, "svar-fan",
                   "boe-svar: out-of-sample forecast fan from the frozen 2024Q2 edge vs ONS outturns",
                   desc)

    out.append('<line class="vc-s1" x1="58" y1="26" x2="84" y2="26"/><text class="vc-lab" x="92" y="30">median forecast + 68% band</text>')
    out.append('<circle class="vc-s2-dot" cx="352" cy="26" r="3.5"/><text class="vc-lab vc-lab2" x="362" y="30">ONS outturn</text>')
    out.append('<text class="vc-note" x="540" y="30">frozen 2024Q2 edge at left of each panel</text>')

    gdp_labels = {-1: "-1%", 0: "0", 1: "+1%", 2: "+2%", 3: "+3%"}
    for var, labels in (("gdp", gdp_labels), ("cpi", None)):
        p = panels[var]
        for k in range(5):
            v = p["v_lo"] + k
            y = p["ymap"](v)
            cls = "vc-axis" if var == "gdp" and v == 0 else "vc-grid"
            out.append(f'<line class="{cls}" x1="{p["x0"]:.0f}" y1="{n(y)}" x2="{p["x1"]:.0f}" y2="{n(y)}"/>')
            label = labels[v] if labels else f"{v:g}%"
            out.append(f'<text class="vc-tick" x="{p["x0"] - 6:.0f}" y="{n(y + 4)}" text-anchor="end">{label}</text>')

    for var in ("gdp", "cpi"):
        p = panels[var]
        hi_pts = " L".join(f"{n(p['xs'][i])} {n(p['ymap'](v))}" for i, v in enumerate(series[var]["hi68"]))
        lo_pts = " L".join(f"{n(p['xs'][i])} {n(p['ymap'](v))}"
                           for i, v in reversed(list(enumerate(series[var]["lo68"]))))
        out.append(f'<path class="vc-band" d="M{hi_pts} L{lo_pts} Z"/>')

    for var in ("gdp", "cpi"):
        p = panels[var]
        out.append(f'<line class="vc-edge" x1="{p["x0"]:.0f}" y1="{top_y:.0f}" x2="{p["x0"]:.0f}" y2="{base_y:.0f}"/>')
    for var in ("gdp", "cpi"):
        p = panels[var]
        pts = " L".join(f"{n(p['xs'][i])} {n(p['ymap'](v))}" for i, v in enumerate(series[var]["median"]))
        out.append(f'<path class="vc-s1" d="M{pts}"/>')
    for var in ("gdp", "cpi"):
        p = panels[var]
        for i, v in enumerate(outturns[var]):
            out.append(f'<circle class="vc-s2-dot" cx="{n(p["xs"][i])}" cy="{n(p["ymap"](v))}" r="3.5"/>')

    out.append('<text class="vc-lab" x="212" y="318" text-anchor="middle">GDP growth (YoY, %)</text>')
    out.append('<text class="vc-lab" x="570" y="318" text-anchor="middle">CPI inflation (YoY, %)</text>')
    for var in ("gdp", "cpi"):
        p = panels[var]
        for i in (0, (npts - 1) // 2, npts - 1):
            out.append(f'<text class="vc-tick" x="{n(p["xs"][i])}" y="334" text-anchor="middle">{quarters[i][2:]}</text>')

    out.append("</svg>")
    return "\n".join(out)


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

    W, H = 760, 290
    x0, x1 = 64.0, 724.0
    span = x1 - x0
    per_var = span / total

    in_band = sum(g["count"] for g in grades if g["in_band"])
    trivial = sum(g["count"] for g in grades if g.get("trivial"))
    off = next(g for g in grades if g["key"] == "off")

    desc = (
        f"Two stacked bars. Of {total} headline variables in the OBR emulator "
        f"calibration scorecard, {computed} are actually computed by the model and "
        f"{passthrough} are passthrough, held at the OBR published value and therefore "
        f"scoring zero error trivially. Of the {computed} computed, "
        + ", ".join(
            f"{g['count']} {'is' if g['count'] == 1 else 'are'} "
            f"{'an identity' if g['count'] == 1 and g['key'] == 'identity' else g['label']}"
            for g in grades
        )
        + f". {in_band} of the {computed}, or {100 * in_band / computed:.0f} per cent, land "
        f"within band, and {word(trivial)} of those is a trivial accounting identity, so only "
        f"{in_band - trivial} non-trivial computed variables are in band. The worst are "
        + " and ".join(off["examples"])
        + "."
    )

    out = svg_open(W, H, "obr-computed-share",
                   "How much of the OBR emulator scorecard the model actually computes", desc)

    # Row 1 — computed vs passthrough, out of the full scorecard.
    split = x0 + computed * per_var
    out.append(f'<text class="vc-lab" x="64" y="30">{total} headline scorecard variables</text>')
    out.append(f'<rect class="vc-b1" x="{n(x0)}" y="52" width="{n(split - x0)}" height="40"/>')
    out.append(f'<rect class="vc-b3" x="{n(split)}" y="52" width="{n(x1 - split)}" height="40"/>')
    out.append(f'<text class="vc-val" x="{n((x0 + split) / 2)}" y="77" text-anchor="middle">'
               f'{computed} computed</text>')
    out.append(f'<text class="vc-rowlab" x="{n((split + x1) / 2)}" y="77" text-anchor="middle">'
               f'{passthrough} passthrough &mdash; held at the OBR value</text>')
    out.append(f'<line class="vc-edge" x1="{n(x0)}" y1="92" x2="{n(x0)}" y2="120"/>')
    out.append(f'<line class="vc-edge" x1="{n(split)}" y1="92" x2="{n(split)}" y2="120"/>')

    # Row 2 — the computed variables broken down by grade, on the same scale, so
    # the second bar reads as a zoom into the first bar's left-hand segment.
    out.append(f'<text class="vc-lab" x="64" y="140">of which, the {computed} the model '
               f'computes</text>')
    x = x0
    for g in grades:
        w = g["count"] * per_var
        dash = ' stroke="currentColor" stroke-dasharray="3 2" stroke-width="1"' if g["key"] == "off" else ""
        out.append(f'<rect class="vc-b{g["series"]}" x="{n(x)}" y="152" width="{n(w)}" '
                   f'height="40"{dash}/>')
        out.append(f'<text class="vc-rowlab" x="{n(x + w / 2)}" y="207" text-anchor="middle">'
                   f'{esc(g["label"])} {g["count"]}</text>')
        x += w

    out.append(f'<text class="vc-warn" x="64" y="232">Only {in_band - trivial} of {computed} '
               f'non-trivial variables are in band.</text>')
    out.append('<text class="vc-warn" x="64" y="250">A fourth pass is an identity over '
               'passthrough inputs.</text>')
    out.append(f'<text class="vc-note" x="64" y="274">{esc(d["bands_note"])}</text>')
    out.append("</svg>")
    return "\n".join(out)


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
    W, H = 760, 404
    x_one, per_unit = 370.8, 883.0        # value 1.0 at x_one
    def xs(v):
        return x_one + (v - 1.0) * per_unit

    last = horizons[-1]
    best = min(SKILL_ROWS, key=lambda r: ratio[last][r[0]])
    worst = max(SKILL_ROWS, key=lambda r: ratio[last][r[0]])
    n_win_1 = sum(1 for k, _ in SKILL_ROWS if ratio[horizons[0]][k] < 1)
    n_win_last = sum(1 for k, _ in SKILL_ROWS if ratio[last][k] < 1)

    desc = (
        f"Dot matrix of forecast error relative to a random walk with drift, "
        f"{word(len(SKILL_ROWS))} variables by {word(len(horizons))} quarterly horizons, from "
        f"{meta['origins']} expanding-window origins. A ratio below 1.0 means the model "
        f"beats the benchmark; filled dots mark differences significant at 5 per cent by a "
        f"Diebold-Mariano test, hollow dots differences that are not statistically "
        f"distinguishable. "
        + "; ".join(
            f"{label} runs {ratio[horizons[0]][key]:.2f} at one quarter to "
            f"{ratio[last][key]:.2f} at {last}"
            for key, label in SKILL_ROWS
        )
        + f". {best[1]} is the best at the longest horizon and {worst[1]} the worst. "
        f"Against this harder benchmark only {word(n_win_1)} of {word(len(SKILL_ROWS))} "
        f"variables beat naive at one quarter and {word(n_win_last)} at {last}."
    )

    out = svg_open(W, H, "svar-skill-all",
                   "boe-svar forecast skill against a random walk with drift, "
                   "all eight variables", desc)
    out.append('<text class="vc-lab" x="150" y="30">RMSE &divide; drifting-random-walk RMSE '
               '&middot; horizons 1&ndash;8 quarters</text>')
    out.append('<text class="vc-note" x="150" y="48">filled = difference significant at 5% '
               '(Diebold&ndash;Mariano); hollow = not distinguishable</text>')

    for tick in (0.8, 0.9, 1.1, 1.2, 1.3):
        x = xs(tick)
        out.append(f'<line class="vc-grid" x1="{n(x)}" y1="62" x2="{n(x)}" y2="362"/>')
        out.append(f'<text class="vc-tick" x="{n(x)}" y="378" text-anchor="middle">{tick}</text>')
    out.append(f'<line class="vc-axis" x1="{n(x_one)}" y1="62" x2="{n(x_one)}" y2="362"/>')
    out.append(f'<text class="vc-tick" x="{n(x_one)}" y="378" text-anchor="middle">1.0</text>')
    out.append(f'<text class="vc-note" x="{n(x_one - 8)}" y="396" text-anchor="end">'
               f'&larr; model better</text>')
    out.append(f'<text class="vc-note" x="{n(x_one + 8)}" y="396">benchmark better &rarr;</text>')

    for i, (key, label) in enumerate(SKILL_ROWS):
        y = 78.0 + 38 * i
        values = [ratio[h][key] for h in horizons]
        out.append(f'<text class="vc-rowlab" x="140" y="{n(y + 4)}" text-anchor="end">'
                   f'{esc(label)}</text>')
        out.append(f'<line class="vc-grid" x1="{n(xs(min(values)))}" y1="{n(y)}" '
                   f'x2="{n(xs(max(values)))}" y2="{n(y)}"/>')
        for h in horizons:
            v, p = ratio[h][key], pval[h][key]
            r = 4.0 if h == last else 2.6
            if p < SIGNIF:
                series = 1 if v < 1 else 2
                out.append(f'<circle class="vc-s{series}-dot" cx="{n(xs(v))}" cy="{n(y)}" '
                           f'r="{r}"/>')
            else:
                out.append(f'<circle cx="{n(xs(v))}" cy="{n(y)}" r="{r}" fill="none" '
                           f'stroke="currentColor" stroke-width="1.2" opacity="0.55"/>')
        out.append(f'<text class="vc-val" x="{n(xs(max(values)) + 10)}" y="{n(y + 4)}">'
                   f'{ratio[last][key]:.2f}</text>')

    out.append("</svg>")
    return "\n".join(out)


def chart_svar_winrate():
    horizons, ratio, pval, _meta = load_rolling_eval()
    keys = [k for k, _ in SKILL_ROWS]
    total = len(keys)

    counts = []
    for h in horizons:
        wins = [k for k in keys if ratio[h][k] < 1]
        sig = [k for k in wins if pval[h][k] < SIGNIF]
        counts.append({"h": h, "wins": len(wins), "sig": len(sig)})

    W, H = 760, 300
    x0, x1 = 64, 724
    y_zero, y_top = 250.0, 60.0
    per_var = (y_zero - y_top) / total

    first_dry = next((c["h"] for c in counts if c["sig"] == 0), None)
    desc = (
        f"Stacked column chart. Of the model's {word(total)} forecast variables, how many have "
        f"lower root mean squared error than a random walk with drift, at horizons one to "
        f"{word(horizons[-1])} quarters. The counts are "
        + ", ".join(str(c["wins"]) for c in counts)
        + " respectively. Each column also separates wins whose difference is statistically "
        "significant at 5 per cent by a Diebold-Mariano test from wins that are not: "
        "significant wins number "
        + ", ".join(str(c["sig"]) for c in counts)
        + "."
        + (f" From horizon {first_dry} onward no variable beats the benchmark by a "
           f"statistically significant margin." if first_dry else "")
    )

    out = svg_open(W, H, "svar-winrate",
                   "How many of eight variables beat a drifting random walk, by horizon", desc)
    out.append(f'<text class="vc-lab" x="64" y="30">Of {total} forecast variables, how many '
               f'beat a random walk with drift</text>')

    for k in (2, 4, 6, 8):
        y = y_zero - k * per_var
        out.append(f'<line class="vc-grid" x1="{x0}" y1="{n(y)}" x2="{x1}" y2="{n(y)}"/>')
        out.append(f'<text class="vc-tick" x="54" y="{n(y + 4)}" text-anchor="end">{k}</text>')
    out.append(f'<line class="vc-axis" x1="{x0}" y1="{n(y_zero)}" x2="{x1}" y2="{n(y_zero)}"/>')
    out.append(f'<text class="vc-tick" x="54" y="{n(y_zero + 4)}" text-anchor="end">0</text>')

    bar_w, pitch = 56, 80
    for i, c in enumerate(counts):
        bx = x0 + 12 + i * pitch
        mid = bx + bar_w / 2
        # Bottom-up: significant wins, then the rest of the wins, then the losses.
        y_sig = y_zero - c["sig"] * per_var
        y_win = y_zero - c["wins"] * per_var
        if c["sig"]:
            out.append(f'<rect class="vc-b1" x="{n(bx)}" y="{n(y_sig)}" width="{bar_w}" '
                       f'height="{n(y_zero - y_sig)}"/>')
        if c["wins"] > c["sig"]:
            out.append(f'<rect class="vc-b2" x="{n(bx)}" y="{n(y_win)}" width="{bar_w}" '
                       f'height="{n(y_sig - y_win)}"/>')
        out.append(f'<rect class="vc-b3" x="{n(bx)}" y="{n(y_top)}" width="{bar_w}" '
                   f'height="{n(y_win - y_top)}"/>')
        out.append(f'<text class="vc-val" x="{n(mid)}" y="{n(y_win - 6)}" '
                   f'text-anchor="middle">{c["wins"]}</text>')
        out.append(f'<text class="vc-tick" x="{n(mid)}" y="270.0" text-anchor="middle">'
                   f'h={c["h"]}</text>')

    out.append('<rect class="vc-b1" x="64" y="272" width="14" height="10"/>'
               '<text class="vc-note" x="84" y="281">beats it, and the difference is '
               'significant</text>')
    out.append('<rect class="vc-b2" x="330" y="272" width="14" height="10"/>'
               '<text class="vc-note" x="350" y="281">beats it, not significantly</text>')
    out.append('<rect class="vc-b3" x="560" y="272" width="14" height="10"/>'
               '<text class="vc-note" x="580" y="281">does not beat it</text>')
    out.append("</svg>")
    return "\n".join(out)


# Order must match the order the SVGs appear in validation/index.html: the
# substitution below is positional.
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

    W, H = 760, 330
    x0, x1 = 58.0, 724.0
    step = (x1 - x0) / (len(horizons) - 1)
    xs = [x0 + i * step for i in range(len(horizons))]
    lo_v, hi_v = 0.4, 1.0
    base_y, top_y = 282.0, 40.0

    def ymap(v):
        return base_y - (v - lo_v) * (base_y - top_y) / (hi_v - lo_v)

    desc = ("Line chart of empirical interval coverage by forecast horizon, averaged "
            "across the eight model variables, against the nominal 68 and 90 percent "
            "levels. " +
            "; ".join(
                f"{lv}% band, horizons one to eight: " +
                ", ".join(f"{v:.0%}" for v in series[lv])
                for lv in (68, 90)
            ) +
            ". Both bands under-cover, and coverage worsens with horizon. The window "
            "includes the Covid quarters and the evaluation model carries no Covid "
            "dummies, which depresses coverage.")

    out = svg_open(W, H, "svar-coverage",
                   "boe-svar: empirical band coverage across 49 origins", desc)
    for v in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        out.append(f'<line class="vc-grid" x1="{n(x0)}" y1="{n(ymap(v))}" x2="{n(x1)}" y2="{n(ymap(v))}"/>')
        out.append(f'<text class="vc-tick" x="{n(x0 - 8)}" y="{n(ymap(v) + 4)}" text-anchor="end">{v:.0%}</text>')
    for lv, cls in ((90, "vc-s2"), (68, "vc-s1")):
        # nominal level as a reference line
        out.append(
            f'<line class="vc-grid" x1="{n(x0)}" y1="{n(ymap(lv / 100))}" '
            f'x2="{n(x1)}" y2="{n(ymap(lv / 100))}" stroke-dasharray="2 4"/>'
        )
        pts = " ".join(f"{n(x)},{n(ymap(v))}" for x, v in zip(xs, series[lv]))
        out.append(f'<polyline class="{cls}" points="{pts}"/>')
        out.append(
            f'<text class="vc-lab{" vc-lab2" if lv == 90 else ""}" x="{n(x1 + 2)}" '
            f'y="{n(ymap(series[lv][-1]) + 4)}" text-anchor="end"> </text>'
        )
    out.append(f'<text class="vc-lab" x="{n(x0)}" y="26">68% band, mean coverage across variables</text>')
    out.append(f'<text class="vc-lab vc-lab2" x="{n(x1)}" y="26" text-anchor="end">90% band</text>')
    out.append(f'<text class="vc-note" x="{n(x0)}" y="{n(ymap(0.68) - 6)}">nominal 68%</text>')
    out.append(f'<text class="vc-note" x="{n(x0)}" y="{n(ymap(0.90) - 6)}">nominal 90%</text>')
    for i, h in enumerate(horizons):
        out.append(f'<text class="vc-tick" x="{n(xs[i])}" y="{H - 14}" text-anchor="middle">h{h}</text>')
    out.append("</svg>")
    return "\n".join(out)


def chart_hank_targets():
    data = json.loads(
        (ROOT / "papers" / "us-hank" / "figures" / "replication.json").read_text()
    )
    rows = data["targets"]
    W, H = 760, 300
    row_h = (264.0 - 40.0) / len(rows)

    def dev(r):
        d = abs(r["achieved"] - r["target"])
        return "0" if d == 0 else f"{d:.1e}"

    desc = ("Table-style chart of the hosted two-asset steady state against the "
            "published calibration targets of Auclert, Bardóczy, Rognlie and Straub (2021). " +
            "; ".join(
                f"{r['name']}: target {r['target']:g}, achieved {r['achieved']:.6g}, "
                f"deviation {dev(r)}"
                for r in rows
            ) +
            ". Goods and asset market clearing residuals are "
            f"{data['residuals'][0]['value']:.1e} and {data['residuals'][1]['value']:.1e}. "
            "Beta is the calibrated free parameter that hits the wealth targets.")

    out = svg_open(W, H, "hank-targets",
                   "us-hank: steady state vs published calibration targets", desc)

    hdr_y = 30.0
    col_target, col_achieved, col_dev = 400, 545, 700
    out.append(f'<text class="vc-tick" x="{col_target}" y="{n(hdr_y)}" text-anchor="end">target</text>')
    out.append(f'<text class="vc-tick" x="{col_achieved}" y="{n(hdr_y)}" text-anchor="end">achieved</text>')
    out.append(f'<text class="vc-tick" x="{col_dev}" y="{n(hdr_y)}" text-anchor="end">|deviation|</text>')
    for i, r in enumerate(rows):
        y = 40.0 + row_h * i
        ty = y + row_h / 2 + 4
        if i:
            out.append(f'<line class="vc-grid" x1="24" y1="{n(y)}" x2="736" y2="{n(y)}"/>')
        out.append(f'<text class="vc-lab vc-rowlab" x="24" y="{n(ty)}">{esc(r["name"])}</text>')
        out.append(f'<text class="vc-val" x="{col_target}" y="{n(ty)}" text-anchor="end">{r["target"]:g}</text>')
        out.append(f'<text class="vc-val" x="{col_achieved}" y="{n(ty)}" text-anchor="end">{r["achieved"]:.6g}</text>')
        out.append(f'<text class="vc-tick" x="{col_dev}" y="{n(ty)}" text-anchor="end">{dev(r)}</text>')
    res = data["residuals"]
    out.append(
        f'<text class="vc-note" x="24" y="290">Market clearing: goods {res[0]["value"]:.1e}, '
        f'assets {res[1]["value"]:.1e}. Achieved values solved from the hosted adapter; '
        "targets from the upstream test suite citing the paper.</text>"
    )
    out.append("</svg>")
    return "\n".join(out)


def chart_define_emissions():
    rows = load_define_emissions()
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
                      f"a gap of {(p / m - 1) * 100:.1f} per cent"
                      for yr, p, m in rows)
    desc = (
        "Grouped bar chart of S1 baseline total UK emissions in MtCO2e per year, "
        "the cached pinned run of upstream commit 846081a against the manual's "
        f"published Table 4. {parts}. The pinned code runs below the published "
        "table and the gap widens with horizon; the divergence is gated at the "
        "observed ratios so any further drift fails loudly. Data from "
        "validation/figures/data/define_emissions_divergence.csv."
    )
    out = svg_open(W, H, "define-emissions",
                   "define-uk: S1 baseline total emissions — pinned run vs manual Table 4 (MtCO2e/yr)",
                   desc)

    t = 0.0
    while t <= 400 + 1e-9:
        y = base_y - t * scale
        cls = "vc-axis" if t == 0 else "vc-grid"
        out.append(f'<line class="{cls}" x1="64" y1="{n(y)}" x2="724" y2="{n(y)}"/>')
        out.append(f'<text class="vc-tick" x="54" y="{n(y + 4)}" text-anchor="end">{t:g}</text>')
        t += 100

    for g, (yr, p, m) in enumerate(rows):
        centre = first_centre + g * group_step
        for k, (name, cls, v) in enumerate((("pinned run", "vc-b1", p),
                                            ("published", "vc-b2", m))):
            x = centre - bar_w - bar_gap / 2 + k * (bar_w + bar_gap)
            h = v * scale
            y = base_y - h
            out.append(f'<rect class="{cls}" x="{n(x)}" y="{n(y)}" width="{bar_w:g}" height="{n(h)}"/>')
            cx = x + bar_w / 2
            out.append(f'<text class="vc-val" x="{n(cx)}" y="{n(y - 8)}" text-anchor="middle">{v:g}</text>')
            out.append(f'<text class="vc-tick" x="{n(cx)}" y="276" text-anchor="middle">{name}</text>')
        out.append(f'<text class="vc-lab" x="{n(centre)}" y="296" text-anchor="middle">'
                   f'{esc(yr)} ({(p / m - 1) * 100:.0f}%)</text>')

    out.append("</svg>")
    return "\n".join(out)


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
    return re.compile(
        rf'<svg class="vchart" data-chart="{re.escape(chart_id)}".*?</svg>', re.DOTALL
    )


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
        svg = build().replace("\\", "\\\\")
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
