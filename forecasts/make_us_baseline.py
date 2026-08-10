#!/usr/bin/env python3
"""Render the FRB/US LONGBASE baseline table on the US forecasts page.

Run:  python3 forecasts/make_us_baseline.py          # rewrite forecasts/us/index.html
      python3 forecasts/make_us_baseline.py --check  # exit 1 if the page is stale

Same contract as forecasts/score.py and forecasts/make_open_fans.py: the page
is committed, the table between the ``us-longbase-baseline`` markers is
generated from the committed CSV, and --check fails if they drift apart. The
CSV is the Fed's April 2026 LONGBASE conditioning baseline extracted by the
frb-us adapter — not a PolicyEngine forecast, no uncertainty bands, never
scored.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "papers" / "frb-us" / "figures" / "longbase_baseline_yoy.csv"
PAGE = Path(__file__).resolve().parent / "us" / "index.html"

MARKER = "us-longbase-baseline"


def rows() -> list[dict]:
    lines = [
        line for line in CSV.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    header = lines[0].split(",")
    return [dict(zip(header, line.split(","))) for line in lines[1:]]


def render() -> str:
    body = "\n".join(
        f"            <tr><th scope=\"row\">{r['quarter']}</th>"
        f"<td>{float(r['gdp_yoy_pct']):.1f}%</td>"
        f"<td>{float(r['cpi_yoy_pct']):.1f}%</td>"
        f"<td>{float(r['unemployment_pct']):.1f}%</td></tr>"
        for r in rows()
    )
    return "\n".join(
        [
            "      <div class=\"table-scroll\">",
            "        <table>",
            "          <caption>FRB/US April 2026 LONGBASE conditioning "
            "baseline — the Fed-style path frb-us shocks deviate from. Not a "
            "PolicyEngine forecast; no bands; never scored.</caption>",
            "          <thead><tr><th scope=\"col\">Quarter</th>"
            "<th scope=\"col\">Real GDP, y/y</th>"
            "<th scope=\"col\">CPI, y/y</th>"
            "<th scope=\"col\">Unemployment</th></tr></thead>",
            "          <tbody>",
            body,
            "          </tbody>",
            "        </table>",
            "      </div>",
        ]
    )


def render_page(html: str) -> str:
    pattern = re.compile(
        rf"(<!-- {MARKER}:begin -->\n).*?(<!-- {MARKER}:end -->)", re.DOTALL
    )
    if not pattern.search(html):
        raise SystemExit(f"{PAGE}: marker {MARKER} not found")
    return pattern.sub(
        lambda m: m.group(1) + render() + "\n" + m.group(2), html, count=1
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the page is stale")
    args = ap.parse_args()

    page_now = PAGE.read_text()
    page_fresh = render_page(page_now)

    if args.check:
        if page_now != page_fresh:
            print(
                "FAIL forecasts/us/index.html us-longbase-baseline block is "
                "stale — run forecasts/make_us_baseline.py",
                file=sys.stderr,
            )
            return 1
        print("OK — US LONGBASE baseline table current")
        return 0

    if page_now != page_fresh:
        PAGE.write_text(page_fresh)
        print(f"updated {PAGE.relative_to(ROOT)}")
    else:
        print("no change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
