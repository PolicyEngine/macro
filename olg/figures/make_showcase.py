#!/usr/bin/env python3
"""Regenerate the OLG showcase stats table inlined in olg/index.html.

Run:  python3 olg/figures/make_showcase.py          # rewrite olg/index.html
      python3 olg/figures/make_showcase.py --check  # exit 1 if the page is stale

The showcase charts themselves are rendered in the browser (inline SVG drawn
by the page's script from a runtime fetch of olg/figures/tpi_data.json), so
this script no longer emits chart markup. It still owns the headline stats
tbody between the olg-stats markers: every number comes from the committed
transition-path results in tpi_data.json — the +1pp basic-rate simulation
exported from the OG-UK dashboard (OBR November 2025 EFO baseline; the
committed file carries the first five years, 2026-2030, of the 60-period
solve). Nothing here is computed fresh; this script only formats.
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


def load():
    return json.loads((HERE / "tpi_data.json").read_text())


def macro_levels_2030(data):
    """Baseline and reform 2030 levels per macro panel, for the stats table."""
    out = {}
    for p in data["macro6"]:
        base = dict(zip(p["traces"][0]["x"], p["traces"][0]["y"]))
        reform = dict(zip(p["traces"][1]["x"], p["traces"][1]["y"]))
        out[p["title"]] = (base[2030], reform[2030])
    return out


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
        print("olg/index.html showcase stats are up to date.")
        return 0
    if new == html:
        print("no change.")
    else:
        PAGE.write_text(new)
        print(f"wrote {len(BLOCKS)} generated blocks into {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
