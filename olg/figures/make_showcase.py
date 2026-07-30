#!/usr/bin/env python3
"""Regenerate the OLG showcase charts and stats inlined in olg/index.html.

Run:  python3 olg/figures/make_showcase.py          # rewrite olg/index.html
      python3 olg/figures/make_showcase.py --check  # exit 1 if the page is stale

Same idiom as validation/figures/make_charts.py: hand-emitted inline SVG so
every fill and stroke sits on a `vc-*` class from style.css and the charts
retheme with the site. Every plotted number comes from the committed
transition-path results in olg/figures/tpi_data.json — the +1pp basic-rate
simulation exported from the OG-UK dashboard (OBR November 2025 EFO baseline;
the committed file carries the first five years, 2026-2030, of the 60-period
solve). Nothing here is computed fresh; this script only draws.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PAGE = ROOT / "olg" / "index.html"

MACRO_LABELS = [
    ("Consumption (% GDP)", "Consumption"),
    ("Investment (% GDP)", "Investment"),
    ("Gov. Consumption (% GDP)", "Government"),
    ("Tax revenue (% GDP)", "Tax revenue"),
    ("Debt (% GDP)", "Debt"),
    ("GDP (£bn)", "GDP"),
]

SECTOR_SHORT = [
    ("Energy", "Energy"),
    ("Manufacturing", "Manuf."),
    ("Construction", "Constr."),
    ("Trade & Transport", "Trade"),
    ("Info & Finance", "Info/Fin"),
    ("Real Estate", "Real est."),
    ("Business Services", "Bus. serv."),
    ("Public & Other", "Public"),
]


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def n(x: float) -> str:
    return f"{x:.1f}"


def load():
    return json.loads((HERE / "tpi_data.json").read_text())


def macro_deviations(data):
    """Per macro panel: (label, years, % deviation of the plotted series).

    Baseline traces run 2000-2030; the reform trace covers 2026-2030. The
    deviation is (reform / baseline - 1) * 100 over the overlap years — for
    GDP that is the % change in the level, for the five ratio series the %
    change in the GDP share.
    """
    out = []
    by_title = {p["title"]: p for p in data["macro6"]}
    for title, label in MACRO_LABELS:
        p = by_title[title]
        base = dict(zip(p["traces"][0]["x"], p["traces"][0]["y"]))
        years = p["traces"][1]["x"]
        dev = [(y / base[x] - 1) * 100 for x, y in zip(years, p["traces"][1]["y"])]
        out.append((label, years, dev))
    return out


def macro_levels_2030(data):
    """Baseline and reform 2030 levels per macro panel, for the stats table."""
    out = {}
    for p in data["macro6"]:
        base = dict(zip(p["traces"][0]["x"], p["traces"][0]["y"]))
        reform = dict(zip(p["traces"][1]["x"], p["traces"][1]["y"]))
        out[p["title"]] = (base[2030], reform[2030])
    return out


def sector_2030(data):
    """% change from baseline at 2030 for each sector x variable."""
    out = {}
    for p in data["sector3"]:
        var = p["title"].replace("Sector ", "").replace(" (% change)", "").lower()
        out[var] = [t["y"][-1] for t in p["traces"]]
    # trace names come from panel 0 (Plotly subplot pattern)
    out["names"] = [t["name"] for t in data["sector3"][0]["traces"]]
    out["year"] = data["sector3"][0]["traces"][0]["x"][-1]
    return out


def svg_open(view_w, view_h, chart_id, title, desc):
    tid, did = f"{chart_id}-t", f"{chart_id}-d"
    return [
        f'<svg class="vchart" data-chart="{chart_id}" viewBox="0 0 {view_w} {view_h}" '
        f'role="img" aria-labelledby="{tid} {did}">',
        f'<title id="{tid}">{esc(title)}</title>',
        f'<desc id="{did}">{esc(desc)}</desc>',
    ]


# ---------------------------------------------------------------- builders

def chart_macro():
    panels = macro_deviations(load())
    W, H = 760, 420
    cols, rows = 3, 2
    px0, py0 = 58.0, 56.0
    pw, ph = 200.0, 122.0
    gx, gy = 34.0, 66.0
    lo, hi = -2.0, 1.5

    parts = []
    for label, years, dev in panels:
        parts.append(
            f"{label}: " + ", ".join(f"{x} {v:+.2f}%" for x, v in zip(years, dev))
        )
    desc = (
        "Six small-multiple line charts, one per macro aggregate, showing the % "
        "deviation of the reform path from the OBR November 2025 baseline over "
        "2026 to 2030 under a +1pp basic-rate reform starting fiscal 2027-28. "
        "For GDP the series is the % change in the £bn level; for the other "
        "five it is the % change in the aggregate's share of GDP. "
        + "; ".join(parts)
        + ". Source: olg/figures/tpi_data.json."
    )
    out = svg_open(W, H, "olg-macro",
                   "OG-UK +1pp basic rate: macro aggregates, % deviation from baseline",
                   desc)
    out.append('<line class="vc-s1" x1="58" y1="26" x2="84" y2="26"/>'
               '<circle class="vc-s1-dot" cx="71" cy="26" r="3"/>')
    out.append('<text class="vc-lab" x="92" y="30">reform vs baseline, %</text>')
    out.append('<line class="vc-edge" x1="288" y1="20" x2="288" y2="32"/>')
    out.append('<text class="vc-note" x="296" y="30">reform start (2027)</text>')

    for k, (label, years, dev) in enumerate(panels):
        c, r = k % cols, k // cols
        x0 = px0 + c * (pw + gx)
        y0 = py0 + r * (ph + gy)
        step = pw / (len(years) - 1)
        xs = [x0 + i * step for i in range(len(years))]

        def ymap(v):
            return y0 + (hi - v) * ph / (hi - lo)

        out.append(f'<text class="vc-lab" x="{n(x0)}" y="{n(y0 - 10)}">{esc(label)}</text>')
        for tick in (-2.0, -1.0, 0.0, 1.0):
            y = ymap(tick)
            cls = "vc-axis" if tick == 0 else "vc-grid"
            out.append(f'<line class="{cls}" x1="{n(x0)}" y1="{n(y)}" x2="{n(x0 + pw)}" y2="{n(y)}"/>')
            if c == 0:
                lab = "0" if tick == 0 else f"{tick:+g}%"
                out.append(f'<text class="vc-tick" x="{n(x0 - 8)}" y="{n(y + 4)}" '
                           f'text-anchor="end">{lab}</text>')
        # reform-start marker at 2027
        x27 = xs[years.index(2027)]
        out.append(f'<line class="vc-edge" x1="{n(x27)}" y1="{n(y0)}" x2="{n(x27)}" y2="{n(y0 + ph)}"/>')
        pts = " L".join(f"{n(xs[i])} {n(ymap(v))}" for i, v in enumerate(dev))
        out.append(f'<path class="vc-s1" d="M{pts}"/>')
        for i, v in enumerate(dev):
            out.append(f'<circle class="vc-s1-dot" cx="{n(xs[i])}" cy="{n(ymap(v))}" r="2.6"/>')
        for i in (0, len(years) - 1):
            out.append(f'<text class="vc-tick" x="{n(xs[i])}" y="{n(y0 + ph + 16)}" '
                       f'text-anchor="middle">{years[i]}</text>')

    out.append("</svg>")
    return "\n".join(out)


def chart_sectors():
    d = sector_2030(load())
    names = d["names"]
    year = d["year"]
    series = [("output", 1), ("capital", 2), ("labour", 3)]
    W, H = 760, 348
    x0, x1 = 70.0, 724.0
    pitch = (x1 - x0) / 8
    bar_w, bar_gap = 21.0, 3.0
    lo, hi = -0.5, 0.5
    top_y, base_y = 46.0, 286.0

    def ymap(v):
        return top_y + (hi - v) * (base_y - top_y) / (hi - lo)

    parts = []
    for i, name in enumerate(names):
        parts.append(f"{name}: output {d['output'][i]:+.2f}%, capital "
                     f"{d['capital'][i]:+.2f}%, labour {d['labour'][i]:+.2f}%")
    desc = (
        f"Grouped bar chart. % change from baseline in {year} for output, capital "
        f"and labour across the eight UK industry sectors under the +1pp "
        f"basic-rate reform. " + "; ".join(parts) +
        ". Seven of the eight sectors contract by roughly 0.3 to 0.4 per cent; "
        "public & other alone expands. Source: olg/figures/tpi_data.json."
    )
    out = svg_open(W, H, "olg-sectors",
                   f"OG-UK +1pp basic rate: sector output, capital and labour, "
                   f"% change from baseline in {year}", desc)

    out.append('<rect class="vc-b1" x="70" y="8" width="14" height="10"/>'
               '<text class="vc-lab" x="90" y="17">output</text>')
    out.append('<rect class="vc-b2" x="180" y="8" width="14" height="10"/>'
               '<text class="vc-lab" x="200" y="17">capital</text>')
    out.append('<rect class="vc-b3" x="290" y="8" width="14" height="10"/>'
               '<text class="vc-lab" x="310" y="17">labour</text>')

    for tick in (-0.4, -0.2, 0.0, 0.2, 0.4):
        y = ymap(tick)
        cls = "vc-axis" if tick == 0 else "vc-grid"
        out.append(f'<line class="{cls}" x1="{n(x0)}" y1="{n(y)}" x2="{n(x1)}" y2="{n(y)}"/>')
        lab = "0" if tick == 0 else f"{tick:+g}%"
        out.append(f'<text class="vc-tick" x="{n(x0 - 8)}" y="{n(y + 4)}" '
                   f'text-anchor="end">{lab}</text>')

    zero_y = ymap(0.0)
    for g, (name, short) in enumerate(SECTOR_SHORT):
        assert names[g] == name
        centre = x0 + (g + 0.5) * pitch
        gx = centre - 1.5 * bar_w - bar_gap
        for k, (var, sclass) in enumerate(series):
            v = d[var][g]
            x = gx + k * (bar_w + bar_gap)
            y = ymap(v)
            top, hgt = (y, zero_y - y) if v >= 0 else (zero_y, y - zero_y)
            out.append(f'<rect class="vc-b{sclass}" x="{n(x)}" y="{n(top)}" '
                       f'width="{bar_w:g}" height="{n(hgt)}"/>')
        out.append(f'<text class="vc-tick" x="{n(centre)}" y="306" '
                   f'text-anchor="middle">{esc(short)}</text>')

    out.append('<text class="vc-note" x="70" y="332">Committed reform path ends '
               f'{year}; values are the last transition year available.</text>')
    out.append("</svg>")
    return "\n".join(out)


def chart_energy():
    data = load()
    panel = next(p for p in data["sector24"] if p["title"] == "Energy — Output")
    base, reform = panel["traces"][0], panel["traces"][1]
    W, H = 760, 330
    x0, x1 = 58.0, 724.0
    yr_lo, yr_hi = base["x"][0], base["x"][-1]

    def xmap(year):
        return x0 + (year - yr_lo) * (x1 - x0) / (yr_hi - yr_lo)

    lo, hi = 20.0, 70.0
    base_y, top_y = 282.0, 46.0

    def ymap(v):
        return base_y - (v - lo) * (base_y - top_y) / (hi - lo)

    last_dev = (reform["y"][-1] / base["y"][-1] - 1) * 100
    desc = (
        f"Line chart of the energy sector's output index (2000 = 100 basis, "
        f"chained ONS outturn stitched to the OBR November 2025 baseline), "
        f"{yr_lo} to {yr_hi}. The baseline runs from {base['y'][0]:.1f} to "
        f"{base['y'][-1]:.1f}; the dashed reform path covers {reform['x'][0]} to "
        f"{reform['x'][-1]} and ends at {reform['y'][-1]:.1f}, {last_dev:+.2f}% "
        f"from baseline. Vertical markers at 2023 (outturn/forecast boundary) "
        f"and 2027 (reform start). Source: olg/figures/tpi_data.json."
    )
    out = svg_open(W, H, "olg-energy",
                   "OG-UK +1pp basic rate: energy sector output, baseline vs reform (index)",
                   desc)
    out.append('<line class="vc-s1" x1="58" y1="26" x2="84" y2="26"/>'
               '<text class="vc-lab" x="92" y="30">ONS outturn / OBR baseline</text>')
    out.append('<line class="vc-s2" x1="300" y1="26" x2="326" y2="26"/>'
               '<text class="vc-lab vc-lab2" x="334" y="30">reform +1pp basic rate</text>')

    for tick in (20, 30, 40, 50, 60, 70):
        y = ymap(tick)
        out.append(f'<line class="vc-grid" x1="{n(x0)}" y1="{n(y)}" x2="{n(x1)}" y2="{n(y)}"/>')
        out.append(f'<text class="vc-tick" x="{n(x0 - 8)}" y="{n(y + 4)}" '
                   f'text-anchor="end">{tick}</text>')
    for year, label in ((2023, "outturn | forecast"), (2027, "reform start")):
        x = xmap(year)
        out.append(f'<line class="vc-edge" x1="{n(x)}" y1="{n(top_y)}" x2="{n(x)}" y2="{n(base_y)}"/>')
        out.append(f'<text class="vc-note" x="{n(x + 5)}" y="{n(top_y + 12)}">{label}</text>')

    pts = " L".join(f"{n(xmap(x))} {n(ymap(y))}" for x, y in zip(base["x"], base["y"]))
    out.append(f'<path class="vc-s1" d="M{pts}"/>')
    pts = " L".join(f"{n(xmap(x))} {n(ymap(y))}" for x, y in zip(reform["x"], reform["y"]))
    out.append(f'<path class="vc-s2" d="M{pts}"/>')

    for year in range(2000, 2031, 5):
        out.append(f'<text class="vc-tick" x="{n(xmap(year))}" y="302" '
                   f'text-anchor="middle">{year}</text>')
    out.append("</svg>")
    return "\n".join(out)


def stats_tbody():
    lv = macro_levels_2030(load())
    rows = []

    def pp_row(title, label):
        b, r = lv[title]
        return (f'<tr><th scope="row">{label} (% of GDP)</th>'
                f'<td>{b:.2f}%</td><td>{r:.2f}%</td>'
                f'<td>{r - b:+.2f}pp</td></tr>')

    b, r = lv["GDP (£bn)"]
    rows.append(f'<tr><th scope="row">GDP (£bn, current prices)</th>'
                f'<td>{b:,.1f}</td><td>{r:,.1f}</td>'
                f'<td>{r - b:+,.1f} ({(r / b - 1) * 100:+.2f}%)</td></tr>')
    rows.append(pp_row("Tax revenue (% GDP)", "Tax revenue"))
    rows.append(pp_row("Consumption (% GDP)", "Consumption"))
    rows.append(pp_row("Investment (% GDP)", "Investment"))
    rows.append(pp_row("Gov. Consumption (% GDP)", "Government consumption"))
    rows.append(pp_row("Debt (% GDP)", "Debt"))
    return "\n".join(rows)


BLOCKS = [
    ("olg-stats", stats_tbody),
    ("olg-fig-macro", chart_macro),
    ("olg-fig-sectors", chart_sectors),
    ("olg-fig-energy", chart_energy),
]


def render_page(html: str) -> str:
    for name, build in BLOCKS:
        marker = re.compile(
            rf"(<!-- {name}:begin -->).*?(<!-- {name}:end -->)", re.DOTALL
        )
        if not marker.search(html):
            sys.exit(f"marker block {name} not found in {PAGE}")
        # A function replacement is used (not a template string) so the
        # content is inserted literally, backslashes included.
        content = build()
        html = marker.sub(
            lambda m: m.group(1) + "\n" + content + "\n" + m.group(2), html
        )
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the page is out of date")
    args = ap.parse_args()

    html = PAGE.read_text()
    new = render_page(html)
    if args.check:
        if new != html:
            print(f"{PAGE} is out of date; run: python3 olg/figures/make_showcase.py")
            return 1
        print("olg/index.html showcase charts are up to date.")
        return 0
    if new == html:
        print("no change.")
    else:
        PAGE.write_text(new)
        print(f"wrote {len(BLOCKS)} generated blocks into {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
