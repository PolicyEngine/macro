#!/usr/bin/env python3
"""Regenerate the UK Economy page from committed vintages and forecasts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "economy" / "index.html"


def load(name: str) -> dict:
    return json.loads((ROOT / "data" / "latest" / f"{name}.json").read_text())


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def latest(series: dict) -> dict:
    return series["observations"][-1]


def previous(series: dict, periods: int = 1) -> dict:
    return series["observations"][-1 - periods]


def gdp_growth(series: dict) -> list[dict]:
    obs = series["observations"]
    return [
        {
            "period": row["period"],
            "value": 100 * (row["value"] / obs[i - 4]["value"] - 1),
        }
        for i, row in enumerate(obs)
        if i >= 4
    ]


def card(
    label: str,
    value: str,
    period: str,
    change: str,
    source: str,
    vintage: str,
    url: str,
) -> str:
    return f"""        <article class="economy-stat">
          <p class="economy-stat-label mono">{label}</p>
          <p class="economy-stat-value">{value}</p>
          <p class="economy-stat-change">{change}</p>
          <dl>
            <div><dt>Observation</dt><dd>{period}</dd></div>
            <div><dt>Vintage</dt><dd>{vintage}</dd></div>
            <div><dt>Source</dt><dd><a href="{url}">{source}</a></dd></div>
          </dl>
        </article>"""


def cards() -> str:
    gdp = load("uk_gdp_cvm")
    cpi = load("uk_cpi_yoy")
    unemployment = load("uk_unemployment_rate")
    bank_rate = load("uk_bank_rate")
    gilt_5y = load("uk_gilt_5y")
    gilt_10y = load("uk_gilt_10y")
    gilt_20y = load("uk_gilt_20y")
    forecast = json.loads(
        (ROOT / "papers" / "boe-svar" / "figures" / "current_forecast.json").read_text()
    )
    scorecard = json.loads((ROOT / "forecasts" / "scorecard.json").read_text())

    growth = gdp_growth(gdp)
    g_now, g_prev = growth[-1], growth[-2]
    c_now, c_prev = latest(cpi), previous(cpi)
    u_now, u_prev = latest(unemployment), previous(unemployment)
    first_period = forecast["forecast_start"]
    first = forecast["forecast"][first_period]
    scored = scorecard["periods_scored"]
    rounds = scorecard["rounds"]

    return "\n".join(
        [
            card(
                "REAL GDP · YEAR ON YEAR",
                f"{fmt(g_now['value'])}%",
                g_now["period"],
                f"{g_now['value'] - g_prev['value']:+.1f}pp from prior quarter",
                f"ONS · {gdp['cdid']}",
                gdp["vintage"],
                gdp["url"],
            ),
            card(
                "CPI INFLATION",
                f"{fmt(c_now['value'])}%",
                c_now["period"],
                f"{c_now['value'] - c_prev['value']:+.1f}pp from prior quarter",
                f"ONS · {cpi['cdid']}",
                cpi["vintage"],
                cpi["url"],
            ),
            card(
                "UNEMPLOYMENT RATE",
                f"{fmt(u_now['value'])}%",
                u_now["period"],
                f"{u_now['value'] - u_prev['value']:+.1f}pp from prior quarter",
                f"ONS · {unemployment['cdid']}",
                unemployment["vintage"],
                unemployment["url"],
            ),
            card(
                "MODEL GDP OUTLOOK",
                f"{fmt(first['gdp']['median'])}%",
                first_period,
                f"68% range {fmt(first['gdp']['lo68'])}% to {fmt(first['gdp']['hi68'])}%",
                "PolicyEngine · boe-svar",
                forecast["generated"],
                "/svar/",
            ),
            card(
                "MODEL CPI OUTLOOK",
                f"{fmt(first['cpi']['median'])}%",
                first_period,
                f"68% range {fmt(first['cpi']['lo68'])}% to {fmt(first['cpi']['hi68'])}%",
                "PolicyEngine · boe-svar",
                forecast["generated"],
                "/svar/",
            ),
            card(
                "REAL-TIME FORECAST RECORD",
                f"{scored} scored",
                "current scorecard",
                f"{rounds} archived round{'s' if rounds != 1 else ''}",
                "PolicyEngine forecast archive",
                "generated scorecard",
                "/forecasts/",
            ),
            card(
                "BANK RATE",
                f"{fmt(latest(bank_rate)['value'], 2)}%",
                latest(bank_rate)["period"],
                f"{latest(bank_rate)['value'] - previous(bank_rate, 5)['value']:+.2f}pp over five observations",
                f"Bank of England · {bank_rate['cdid']}",
                bank_rate["vintage"],
                bank_rate["url"],
            ),
            card(
                "10-YEAR GILT YIELD",
                f"{fmt(latest(gilt_10y)['value'], 2)}%",
                latest(gilt_10y)["period"],
                f"{latest(gilt_10y)['value'] - previous(gilt_10y, 5)['value']:+.2f}pp over five observations",
                f"Bank of England · {gilt_10y['cdid']}",
                gilt_10y["vintage"],
                gilt_10y["url"],
            ),
            card(
                "GILT CURVE · 20Y MINUS 5Y",
                f"{latest(gilt_20y)['value'] - latest(gilt_5y)['value']:+.2f}pp",
                latest(gilt_20y)["period"],
                f"5y {latest(gilt_5y)['value']:.2f}% · 20y {latest(gilt_20y)['value']:.2f}%",
                "Bank of England yield curve",
                gilt_20y["vintage"],
                gilt_20y["url"],
            ),
        ]
    )


def outlook_rows() -> str:
    forecast = json.loads(
        (ROOT / "papers" / "boe-svar" / "figures" / "current_forecast.json").read_text()
    )
    rows = []
    for period, values in list(forecast["forecast"].items())[:5]:
        rows.append(
            "          <tr>"
            f'<th scope="row">{period}</th>'
            f"<td>{values['gdp']['median']:.2f}%</td>"
            f"<td>{values['gdp']['lo68']:.2f}%–{values['gdp']['hi68']:.2f}%</td>"
            f"<td>{values['cpi']['median']:.2f}%</td>"
            f"<td>{values['cpi']['lo68']:.2f}%–{values['cpi']['hi68']:.2f}%</td>"
            "</tr>"
        )
    return "\n".join(rows)


def indicator_rows() -> str:
    specs = []

    gva = load("uk_monthly_gva")
    now, prior = latest(gva), previous(gva)
    specs.append(
        (
            "Activity",
            gva,
            f"{100 * (now['value'] / prior['value'] - 1):+.1f}% m/m",
            f"index {now['value']:.1f}",
        )
    )

    core = load("uk_core_cpi_yoy")
    now, prior = latest(core), previous(core)
    specs.append(
        ("Prices", core, f"{now['value'] - prior['value']:+.1f}pp m/m", f"{now['value']:.1f}%")
    )

    earnings = load("uk_average_weekly_earnings")
    now, year_ago = latest(earnings), previous(earnings, 12)
    specs.append(
        (
            "Labour",
            earnings,
            f"{100 * (now['value'] / year_ago['value'] - 1):+.1f}% y/y",
            f"£{now['value']:,.0f}/week",
        )
    )

    vacancies = load("uk_vacancies")
    now, year_ago = latest(vacancies), previous(vacancies, 12)
    specs.append(
        (
            "Labour",
            vacancies,
            f"{now['value'] - year_ago['value']:+,.0f}k y/y",
            f"{now['value']:,.0f}k",
        )
    )

    borrowing = load("uk_public_sector_net_borrowing")
    now, year_ago = latest(borrowing), previous(borrowing, 12)
    # J5II records net borrowing as a negative financial balance. Present the
    # conventional positive "amount borrowed" and document the sign conversion.
    specs.append(
        (
            "Fiscal",
            borrowing,
            f"{(-now['value'] + year_ago['value']) / 1000:+.1f}bn y/y",
            f"£{-now['value'] / 1000:,.1f}bn borrowed",
        )
    )

    debt = load("uk_public_sector_net_debt_gdp")
    now, prior = latest(debt), previous(debt)
    specs.append(
        ("Fiscal", debt, f"{now['value'] - prior['value']:+.1f}pp m/m", f"{now['value']:.1f}% GDP")
    )

    investment = load("uk_business_investment")
    now, prior = latest(investment), previous(investment)
    specs.append(
        (
            "Investment",
            investment,
            f"{100 * (now['value'] / prior['value'] - 1):+.1f}% q/q",
            f"£{now['value'] / 1000:,.1f}bn",
        )
    )

    rows = []
    for area, series, change, value in specs:
        now = latest(series)
        rows.append(
            "          <tr>"
            f"<td>{area}</td>"
            f'<th scope="row">{series["title"]}</th>'
            f"<td>{value}</td>"
            f"<td>{change}</td>"
            f"<td>{now['period']}</td>"
            f"<td>{series['vintage']}</td>"
            f'<td><a href="{series["url"]}">ONS · {series["cdid"]}</a></td>'
            "</tr>"
        )
    return "\n".join(rows)


def release_rows() -> str:
    rows = []
    for name in (
        "uk_gdp_cvm",
        "uk_cpi_yoy",
        "uk_unemployment_rate",
        "uk_core_cpi_yoy",
        "uk_average_weekly_earnings",
        "uk_vacancies",
        "uk_monthly_gva",
        "uk_public_sector_net_borrowing",
        "uk_public_sector_net_debt_gdp",
        "uk_business_investment",
        "uk_bank_rate",
        "uk_gilt_5y",
        "uk_gilt_10y",
        "uk_gilt_20y",
    ):
        series = load(name)
        now = latest(series)
        rows.append(
            "          <tr>"
            f'<th scope="row">{series["title"]}</th>'
            f"<td>{now['period']}</td>"
            f"<td>{(series.get('release_updated') or 'not supplied').split('T')[0]}</td>"
            f"<td>{series['vintage']}</td>"
            f'<td><a href="{series["url"]}">{series["source"]} · {series["cdid"]}</a></td>'
            "</tr>"
        )
    return "\n".join(rows)


def market_rows() -> str:
    rows = []
    for name in ("uk_bank_rate", "uk_gilt_5y", "uk_gilt_10y", "uk_gilt_20y"):
        series = load(name)
        now = latest(series)
        five = previous(series, 5)
        rows.append(
            "          <tr>"
            f'<th scope="row">{series["title"]}</th>'
            f"<td>{now['value']:.3f}%</td>"
            f"<td>{now['value'] - five['value']:+.3f}pp</td>"
            f"<td>{now['period']}</td>"
            f"<td>{series['vintage']}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def replace(html: str, name: str, value: str) -> str:
    start, end = f"<!-- {name}:begin -->", f"<!-- {name}:end -->"
    updated, count = re.subn(
        re.escape(start) + ".*?" + re.escape(end),
        lambda _: f"{start}\n{value}\n{end}",
        html,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError(f"expected one {name} block, found {count}")
    return updated


def render() -> str:
    html = PAGE.read_text()
    html = replace(html, "economy-cards", cards())
    html = replace(html, "economy-indicators", indicator_rows())
    html = replace(html, "economy-outlook", outlook_rows())
    html = replace(html, "economy-markets", market_rows())
    html = replace(html, "economy-releases", release_rows())
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        if rendered != PAGE.read_text():
            print("economy/index.html is stale; run python3 economy/build.py")
            return 1
        print("economy/index.html matches committed data")
        return 0
    PAGE.write_text(rendered)
    print("updated economy/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
