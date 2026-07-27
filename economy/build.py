#!/usr/bin/env python3
"""Regenerate the UK and US Economy pages from committed vintages."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "economy" / "index.html"
US_PAGE = ROOT / "economy" / "us" / "index.html"

PUBLIC_LABELS = {
    "ABMI": "Real gross domestic product",
    "D7G7": "CPI inflation",
    "MGSX": "Unemployment rate",
    "DKO8": "Core CPI inflation",
    "KAB9": "Average weekly earnings",
    "AP2Y": "UK vacancies",
    "ECY2": "Monthly gross value added index",
    "J5II": "Public-sector net borrowing",
    "HF6X": "Public-sector net debt",
    "NPEL": "Real business investment",
}


def load(name: str) -> dict:
    series = json.loads((ROOT / "data" / "latest" / f"{name}.json").read_text())
    # ONS stores observations behind a JSON `/data` endpoint, but that is a
    # poor destination for a reader clicking "View source". Keep the API URL
    # in the committed vintage and expose the matching human-readable page.
    if "ons.gov.uk/" in series["url"] and series["url"].endswith("/data"):
        series["url"] = series["url"][: -len("/data")]
    return series


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def latest(series: dict) -> dict:
    return series["observations"][-1]


def public_label(series: dict) -> str:
    return PUBLIC_LABELS.get(series["cdid"], series["title"])


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


def yoy_growth(series: dict, periods: int) -> list[dict]:
    obs = series["observations"]
    by_period = {row["period"]: row["value"] for row in obs}
    out = []
    for row in obs:
        period = row["period"]
        if periods == 12 and re.fullmatch(r"\d{4}-\d{2}", period):
            comparison = f"{int(period[:4]) - 1}{period[4:]}"
        elif periods == 4 and re.fullmatch(r"\d{4}Q[1-4]", period):
            comparison = f"{int(period[:4]) - 1}{period[4:]}"
        else:
            continue
        if comparison not in by_period:
            continue
        out.append(
            {
                "period": period,
                "value": 100 * (row["value"] / by_period[comparison] - 1),
            }
        )
    return out


def line_chart(
    title: str,
    description: str,
    values: list[dict],
    units: str,
    source: str,
    url: str,
) -> str:
    """Small accessible trend figure generated from committed observations."""
    values = values[-20:]
    width, height = 520, 230
    left, right, top, bottom = 52, 18, 28, 38
    low = min(row["value"] for row in values)
    high = max(row["value"] for row in values)
    padding = max((high - low) * 0.12, 0.25)
    low, high = low - padding, high + padding

    def x(index: int) -> float:
        return left + index * (width - left - right) / (len(values) - 1)

    def y(value: float) -> float:
        return top + (high - value) * (height - top - bottom) / (high - low)

    points = " ".join(
        f"{x(i):.1f},{y(row['value']):.1f}" for i, row in enumerate(values)
    )
    first, last = values[0], values[-1]
    title_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"""      <figure class="economy-figure">
        <svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="{title_id}-title {title_id}-desc">
          <title id="{title_id}-title">{title}</title>
          <desc id="{title_id}-desc">{description}</desc>
          <line class="economy-chart-grid" x1="{left}" y1="{y(high - padding):.1f}" x2="{width - right}" y2="{y(high - padding):.1f}" />
          <line class="economy-chart-grid" x1="{left}" y1="{y(low + padding):.1f}" x2="{width - right}" y2="{y(low + padding):.1f}" />
          <polyline class="economy-chart-line" points="{points}" />
          <circle class="economy-chart-dot" cx="{x(len(values) - 1):.1f}" cy="{y(last['value']):.1f}" r="4" />
          <text class="economy-chart-label" x="{left}" y="{height - 12}">{first['period']}</text>
          <text class="economy-chart-label" x="{width - right}" y="{height - 12}" text-anchor="end">{last['period']}</text>
          <text class="economy-chart-value" x="{width - right}" y="{max(y(last['value']) - 10, 16):.1f}" text-anchor="end">{last['value']:.1f}{units}</text>
        </svg>
        <figcaption><strong>{title}</strong><span>{description}</span><a href="{url}">View source · {source} →</a></figcaption>
      </figure>"""


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
        ]
    )


def uk_figures() -> str:
    gdp = load("uk_gdp_cvm")
    cpi = load("uk_cpi_yoy")
    unemployment = load("uk_unemployment_rate")
    return "\n".join(
        (
            line_chart(
                "UK real GDP growth",
                "Year-on-year percent, latest 20 quarters.",
                gdp_growth(gdp),
                "%",
                f"ONS · {gdp['cdid']}",
                gdp["url"],
            ),
            line_chart(
                "UK CPI inflation",
                "Year-on-year percent, latest 20 quarters.",
                cpi["observations"],
                "%",
                f"ONS · {cpi['cdid']}",
                cpi["url"],
            ),
            line_chart(
                "UK unemployment",
                "Percent of the labour force, latest 20 quarters.",
                unemployment["observations"],
                "%",
                f"ONS · {unemployment['cdid']}",
                unemployment["url"],
            ),
        )
    )


def us_cards() -> str:
    gdp = load("us_real_gdp")
    cpi = load("us_cpi")
    unemployment = load("us_unemployment_rate")
    payrolls = load("us_payroll_employment")
    fed_funds = load("us_federal_funds_rate")
    treasury = load("us_treasury_10y")

    growth = gdp_growth(gdp)
    inflation = yoy_growth(cpi, 12)
    payroll_growth = yoy_growth(payrolls, 12)
    g_now, g_prior = growth[-1], growth[-2]
    p_now, p_prior = inflation[-1], inflation[-2]
    u_now, u_prior = latest(unemployment), previous(unemployment)
    jobs_now = payroll_growth[-1]

    return "\n".join(
        (
            card(
                "REAL GDP · YEAR ON YEAR",
                f"{g_now['value']:.1f}%",
                g_now["period"],
                f"{g_now['value'] - g_prior['value']:+.1f}pp from prior quarter",
                "BEA via FRED · GDPC1",
                gdp["vintage"],
                gdp["url"],
            ),
            card(
                "CPI INFLATION",
                f"{p_now['value']:.1f}%",
                p_now["period"],
                f"{p_now['value'] - p_prior['value']:+.1f}pp from prior month",
                "BLS via FRED · CPIAUCSL",
                cpi["vintage"],
                cpi["url"],
            ),
            card(
                "UNEMPLOYMENT RATE",
                f"{u_now['value']:.1f}%",
                u_now["period"],
                f"{u_now['value'] - u_prior['value']:+.1f}pp from prior month",
                "BLS via FRED · UNRATE",
                unemployment["vintage"],
                unemployment["url"],
            ),
            card(
                "PAYROLL EMPLOYMENT",
                f"{jobs_now['value']:+.1f}%",
                jobs_now["period"],
                "year-on-year employment growth",
                "BLS via FRED · PAYEMS",
                payrolls["vintage"],
                payrolls["url"],
            ),
            card(
                "EFFECTIVE FED FUNDS RATE",
                f"{latest(fed_funds)['value']:.2f}%",
                latest(fed_funds)["period"],
                f"{latest(fed_funds)['value'] - previous(fed_funds, 5)['value']:+.2f}pp over five months",
                "Federal Reserve via FRED · FEDFUNDS",
                fed_funds["vintage"],
                fed_funds["url"],
            ),
            card(
                "10-YEAR TREASURY YIELD",
                f"{latest(treasury)['value']:.2f}%",
                latest(treasury)["period"],
                f"{latest(treasury)['value'] - previous(treasury, 5)['value']:+.2f}pp over five observations",
                "Federal Reserve via FRED · DGS10",
                treasury["vintage"],
                treasury["url"],
            ),
        )
    )


def us_figures() -> str:
    gdp = load("us_real_gdp")
    cpi = load("us_cpi")
    unemployment = load("us_unemployment_rate")
    return "\n".join(
        (
            line_chart(
                "US real GDP growth",
                "Year-on-year percent, latest 20 quarters.",
                gdp_growth(gdp),
                "%",
                "BEA via FRED · GDPC1",
                gdp["url"],
            ),
            line_chart(
                "US CPI inflation",
                "Year-on-year percent, latest 20 months.",
                yoy_growth(cpi, 12),
                "%",
                "BLS via FRED · CPIAUCSL",
                cpi["url"],
            ),
            line_chart(
                "US unemployment",
                "Percent of the labour force, latest 20 months.",
                unemployment["observations"],
                "%",
                "BLS via FRED · UNRATE",
                unemployment["url"],
            ),
        )
    )


def us_indicator_rows() -> str:
    gdp = load("us_real_gdp")
    cpi = load("us_cpi")
    unemployment = load("us_unemployment_rate")
    payrolls = load("us_payroll_employment")
    specs = (
        ("Activity", gdp, f"{gdp_growth(gdp)[-1]['value']:.1f}%", "year on year"),
        ("Prices", cpi, f"{yoy_growth(cpi, 12)[-1]['value']:.1f}%", "year on year"),
        (
            "Labour",
            unemployment,
            f"{latest(unemployment)['value']:.1f}%",
            f"{latest(unemployment)['value'] - previous(unemployment)['value']:+.1f}pp m/m",
        ),
        (
            "Labour",
            payrolls,
            f"{latest(payrolls)['value'] / 1000:,.1f}m",
            f"{latest(payrolls)['value'] - previous(payrolls)['value']:+,.0f}k m/m",
        ),
    )
    rows = []
    for area, series, value, change in specs:
        now = latest(series)
        rows.append(
            "          <tr>"
            f"<td>{area}</td>"
            f'<th scope="row">{public_label(series)}</th>'
            f"<td>{value}</td>"
            f"<td>{change}</td>"
            f"<td>{now['period']}</td>"
            f"<td>{series['vintage']}</td>"
            f'<td><a href="{series["url"]}">FRED · {series["cdid"]}</a></td>'
            "</tr>"
        )
    return "\n".join(rows)


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
            f'<th scope="row">{public_label(series)}</th>'
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
            f'<th scope="row">{public_label(series)}</th>'
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


def us_market_rows() -> str:
    rows = []
    for name in ("us_federal_funds_rate", "us_treasury_10y"):
        series = load(name)
        now, five = latest(series), previous(series, 5)
        rows.append(
            "          <tr>"
            f'<th scope="row">{series["title"]}</th>'
            f"<td>{now['value']:.3f}%</td>"
            f"<td>{now['value'] - five['value']:+.3f}pp</td>"
            f"<td>{now['period']}</td>"
            f"<td>{series['vintage']}</td>"
            f'<td><a href="{series["url"]}">FRED · {series["cdid"]}</a></td>'
            "</tr>"
        )
    return "\n".join(rows)


def us_release_rows() -> str:
    rows = []
    for name in (
        "us_real_gdp",
        "us_cpi",
        "us_unemployment_rate",
        "us_payroll_employment",
        "us_federal_funds_rate",
        "us_treasury_10y",
    ):
        series = load(name)
        now = latest(series)
        rows.append(
            "          <tr>"
            f'<th scope="row">{series["title"]}</th>'
            f"<td>{now['period']}</td>"
            f"<td>{series['vintage']}</td>"
            f'<td><a href="{series["url"]}">FRED · {series["cdid"]}</a></td>'
            "</tr>"
        )
    return "\n".join(rows)


def calendar_rows() -> str:
    names = (
        "uk_monthly_gva",
        "uk_unemployment_rate",
        "uk_average_weekly_earnings",
        "uk_vacancies",
        "uk_cpi_yoy",
        "uk_core_cpi_yoy",
        "uk_public_sector_net_borrowing",
        "uk_public_sector_net_debt_gdp",
        "uk_gdp_cvm",
        "uk_business_investment",
    )
    releases: dict[str, list[dict]] = {}
    for name in names:
        series = load(name)
        date = " ".join((series.get("next_release") or "").split())
        if date:
            releases.setdefault(date, []).append(series)

    def sort_key(item: tuple[str, list[dict]]) -> datetime:
        return datetime.strptime(item[0], "%d %B %Y")

    rows = []
    for date, series_list in sorted(releases.items(), key=sort_key):
        labels = ", ".join(public_label(series) for series in series_list)
        sources = ", ".join(series["cdid"] for series in series_list)
        rows.append(
            "          <tr>"
            f'<th scope="row">{date}</th>'
            f"<td>{labels}</td>"
            f"<td>ONS · {sources}</td>"
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


def render_uk() -> str:
    html = PAGE.read_text()
    html = replace(html, "economy-cards", cards())
    html = replace(html, "economy-figures", uk_figures())
    html = replace(html, "economy-indicators", indicator_rows())
    html = replace(html, "economy-outlook", outlook_rows())
    html = replace(html, "economy-markets", market_rows())
    html = replace(html, "economy-calendar", calendar_rows())
    html = replace(html, "economy-releases", release_rows())
    return html


def render_us() -> str:
    html = US_PAGE.read_text()
    html = replace(html, "us-economy-cards", us_cards())
    html = replace(html, "us-economy-figures", us_figures())
    html = replace(html, "us-economy-indicators", us_indicator_rows())
    html = replace(html, "us-economy-markets", us_market_rows())
    html = replace(html, "us-economy-releases", us_release_rows())
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered_uk = render_uk()
    rendered_us = render_us()
    if args.check:
        stale = []
        if rendered_uk != PAGE.read_text():
            stale.append("economy/index.html")
        if rendered_us != US_PAGE.read_text():
            stale.append("economy/us/index.html")
        if stale:
            print(f"{', '.join(stale)} stale; run python3 economy/build.py")
            return 1
        print("UK and US Economy pages match committed data")
        return 0
    PAGE.write_text(rendered_uk)
    US_PAGE.write_text(rendered_us)
    print("updated UK and US Economy pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
