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
HOME_PAGE = ROOT / "index.html"
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


def quarter_of(period: str) -> str:
    """Map a monthly period like 2026-06 to its quarter (2026Q2)."""
    if "Q" in period:
        return period
    year, month = period.split("-")
    return f"{year}Q{(int(month) + 2) // 3}"


def longbase_baseline() -> list[dict]:
    """FRB/US April 2026 LONGBASE conditioning baseline, near-term y/y path."""
    path = ROOT / "papers" / "frb-us" / "figures" / "longbase_baseline_yoy.csv"
    lines = [
        line for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    header = lines[0].split(",")
    return [
        {key: value if key == "quarter" else float(value)
         for key, value in zip(header, line.split(","))}
        for line in lines[1:]
    ]


def baseline_next_open(rows: list[dict], last_observed: str) -> dict:
    """First baseline quarter with no published outturn yet."""
    last_quarter = quarter_of(last_observed)
    for row in rows:
        if row["quarter"] > last_quarter:
            return row
    return rows[-1]


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
    window_low = min(row["value"] for row in values)
    window_high = max(row["value"] for row in values)
    desc = (
        f"{description.rstrip('.').replace(', latest ', ' over the latest ')}, "
        f"from {first['value']:.1f}{units} in {first['period']} "
        f"to {last['value']:.1f}{units} in {last['period']}; "
        f"range {window_low:.1f}{units} to {window_high:.1f}{units}."
    )
    return f"""      <figure class="economy-figure">
        <svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="{title_id}-title {title_id}-desc">
          <title id="{title_id}-title">{title}</title>
          <desc id="{title_id}-desc">{desc}</desc>
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
    model_line: str | None = None,
    model_source: tuple[str, str, str] | None = None,
) -> str:
    """One stat card; optionally paired with a model line under the outturn."""
    model_html = (
        f"\n          <p class=\"economy-stat-change\">{model_line}</p>"
        if model_line
        else ""
    )
    model_row = ""
    if model_source:
        m_label, m_url, m_vintage = model_source
        model_row = (
            f"\n            <div><dt>Model</dt>"
            f'<dd><a href="{m_url}">{m_label}</a> · {m_vintage}</dd></div>'
        )
    return f"""        <article class="economy-stat">
          <p class="economy-stat-label mono">{label}</p>
          <p class="economy-stat-value">{value}</p>
          <p class="economy-stat-change">{change}</p>{model_html}
          <dl>
            <div><dt>Observation</dt><dd>{period}</dd></div>
            <div><dt>Vintage</dt><dd>{vintage}</dd></div>
            <div><dt>Source</dt><dd><a href="{url}">{source}</a></dd></div>{model_row}
          </dl>
        </article>"""


def cards() -> str:
    gdp = load("uk_gdp_cvm")
    cpi = load("uk_cpi_yoy")
    unemployment = load("uk_unemployment_rate")
    forecast = json.loads(
        (ROOT / "papers" / "boe-svar" / "figures" / "current_forecast.json").read_text()
    )
    # Archived round file keeps its original name; the satellite's display
    # name is "svar-unemployment satellite".
    unemp_round = json.loads(
        (ROOT / "forecasts" / "rounds" / "2026-07-28" / "okun-unemployment.json").read_text()
    )

    growth = gdp_growth(gdp)
    g_now, g_prev = growth[-1], growth[-2]
    c_now, c_prev = latest(cpi), previous(cpi)
    u_now, u_prev = latest(unemployment), previous(unemployment)
    # First forecast quarter with no published outturn yet, per variable —
    # showing a "forecast" for a quarter the ONS has already printed would be
    # stale the moment the release lands.
    def next_open(fc: dict, variable: str, last_observed: str) -> tuple[str, dict]:
        for period, values in fc.items():
            if period > last_observed and variable in values:
                return period, values[variable]
        period = list(fc)[-1]
        return period, fc[period][variable]

    g_period, g_fc = next_open(forecast["forecast"], "gdp", g_now["period"])
    c_period, c_fc = next_open(forecast["forecast"], "cpi", c_now["period"])
    u_period, u_fc = next_open(unemp_round["forecast"], "unemployment", u_now["period"])

    def model_line(fc: dict, period: str) -> str:
        return (
            f"Model: {fmt(fc['median'])}% <span class=\"mono\">{period}</span>"
            f" · 68% {fmt(fc['lo68'])}%–{fmt(fc['hi68'])}%"
        )

    svar_source = ("boe-svar", "/svar", f"generated {forecast['generated']}")
    usat_source = (
        "svar-unemployment satellite",
        "/forecasts",
        f"round {unemp_round['round_id']}",
    )

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
                model_line(g_fc, g_period),
                svar_source,
            ),
            card(
                "CPI INFLATION",
                f"{fmt(c_now['value'])}%",
                c_now["period"],
                f"{c_now['value'] - c_prev['value']:+.1f}pp from prior quarter",
                f"ONS · {cpi['cdid']}",
                cpi["vintage"],
                cpi["url"],
                model_line(c_fc, c_period),
                svar_source,
            ),
            card(
                "UNEMPLOYMENT RATE",
                f"{fmt(u_now['value'])}%",
                u_now["period"],
                f"{u_now['value'] - u_prev['value']:+.1f}pp from prior quarter",
                f"ONS · {unemployment['cdid']}",
                unemployment["vintage"],
                unemployment["url"],
                model_line(u_fc, u_period),
                usat_source,
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

    baseline = longbase_baseline()
    g_base = baseline_next_open(baseline, g_now["period"])
    p_base = baseline_next_open(baseline, p_now["period"])
    u_base = baseline_next_open(baseline, u_now["period"])

    def baseline_line(row: dict, column: str) -> str:
        return (
            f"LONGBASE baseline: {fmt(row[column])}%"
            f" <span class=\"mono\">{row['quarter']}</span>"
        )

    longbase_source = (
        "FRB/US LONGBASE (April 2026)",
        "/frb-us",
        "conditioning baseline, no bands",
    )

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
                baseline_line(g_base, "gdp_yoy_pct"),
                longbase_source,
            ),
            card(
                "CPI INFLATION",
                f"{p_now['value']:.1f}%",
                p_now["period"],
                f"{p_now['value'] - p_prior['value']:+.1f}pp from prior month",
                "BLS via FRED · CPIAUCSL",
                cpi["vintage"],
                cpi["url"],
                baseline_line(p_base, "cpi_yoy_pct"),
                longbase_source,
            ),
            card(
                "UNEMPLOYMENT RATE",
                f"{u_now['value']:.1f}%",
                u_now["period"],
                f"{u_now['value'] - u_prior['value']:+.1f}pp from prior month",
                "BLS via FRED · UNRATE",
                unemployment["vintage"],
                unemployment["url"],
                baseline_line(u_base, "unemployment_pct"),
                longbase_source,
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
                "Percent of the labor force, latest 20 months.",
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
            "Labor",
            unemployment,
            f"{latest(unemployment)['value']:.1f}%",
            f"{latest(unemployment)['value'] - previous(unemployment)['value']:+.1f}pp m/m",
        ),
        (
            "Labor",
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
            f"{'+' if (-now['value'] + year_ago['value']) >= 0 else '-'}£{abs(-now['value'] + year_ago['value']) / 1000:.1f}bn y/y",
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


def home_uk_now() -> str:
    """Homepage 'UK at a glance' table: outturns beside next-open forecasts."""
    gdp = load("uk_gdp_cvm")
    cpi = load("uk_cpi_yoy")
    unemployment = load("uk_unemployment_rate")
    forecast = json.loads(
        (ROOT / "papers" / "boe-svar" / "figures" / "current_forecast.json").read_text()
    )
    # Archived round file keeps its original name; the satellite's display
    # name is "svar-unemployment satellite".
    unemp_round = json.loads(
        (ROOT / "forecasts" / "rounds" / "2026-07-28" / "okun-unemployment.json").read_text()
    )

    growth = gdp_growth(gdp)
    g_now = growth[-1]
    c_now = latest(cpi)
    u_now = latest(unemployment)

    def next_open(fc: dict, variable: str, last_observed: str) -> tuple[str, dict]:
        for period, values in fc.items():
            if period > last_observed and variable in values:
                return period, values[variable]
        period = list(fc)[-1]
        return period, fc[period][variable]

    g_period, g_fc = next_open(forecast["forecast"], "gdp", g_now["period"])
    c_period, c_fc = next_open(forecast["forecast"], "cpi", c_now["period"])
    u_period, u_fc = next_open(unemp_round["forecast"], "unemployment", u_now["period"])

    def rng(fc: dict) -> str:
        return (f'<br><small class="glance-range">68% range '
                f"{fmt(fc['lo68'])}%–{fmt(fc['hi68'])}%</small>")

    caption = (
        "ONS outturns (as of "
        f"{max(gdp['vintage'], cpi['vintage'], unemployment['vintage'])}) beside "
        'archived <a href="/forecasts">forecast rounds</a>. '
        '<a href="/economy">Full horizon &rarr;</a>'
    )
    def row(name, unit, out_v, out_p, fc_v, fc_p, fc_extra):
        return (
            '        <div class="glance-row">\n'
            f'          <span class="g-name">{name} <small>{unit}</small></span>\n'
            f'          <span class="g-cell"><strong>{out_v}</strong> <span class="mono">{out_p}</span></span>\n'
            '          <span class="g-arrow">&rarr;</span>\n'
            f'          <span class="g-cell"><strong>{fc_v}</strong> <span class="mono">{fc_p}</span><small>{fc_extra}</small></span>\n'
            "        </div>"
        )

    def rng(fc: dict) -> str:
        return f"68% range {fmt(fc['lo68'])}%\u2013{fmt(fc['hi68'])}%"

    return "\n".join(
        [
            '      <div class="glance-rows">',
            '        <div class="glance-row glance-row-head mono">'
            '<span class="g-name">indicator</span>'
            '<span>latest outturn</span><span></span>'
            '<span>model near-term forecast</span></div>',
            row("Real GDP growth", "y/y", f"{fmt(g_now['value'])}%", g_now["period"],
                f"{fmt(g_fc['median'])}%", g_period, rng(g_fc)),
            row("CPI inflation", "y/y", f"{fmt(c_now['value'])}%", c_now["period"],
                f"{fmt(c_fc['median'])}%", c_period, rng(c_fc)),
            row("Unemployment rate", "", f"{fmt(u_now['value'])}%", u_now["period"],
                f"{fmt(u_fc['median'])}%", u_period, rng(u_fc)),
            "      </div>",
            f'      <p class="glance-caption">{caption}</p>',
        ]
    )


def home_us_now() -> str:
    """Homepage 'US at a glance' table: outturns beside the LONGBASE baseline."""
    gdp = load("us_real_gdp")
    cpi = load("us_cpi")
    unemployment = load("us_unemployment_rate")
    baseline = longbase_baseline()

    g_now = gdp_growth(gdp)[-1]
    c_now = yoy_growth(cpi, 12)[-1]
    u_now = latest(unemployment)

    g_base = baseline_next_open(baseline, g_now["period"])
    c_base = baseline_next_open(baseline, c_now["period"])
    u_base = baseline_next_open(baseline, u_now["period"])

    caption = (
        "FRED outturns (as of "
        f"{max(gdp['vintage'], cpi['vintage'], unemployment['vintage'])}) beside "
        "the FRB/US LONGBASE conditioning baseline — not a forecast. "
        '<a href="/economy/us">Full sources &rarr;</a>'
    )
    def row(name, unit, out_v, out_p, base_v, base_p):
        return (
            '        <div class="glance-row">\n'
            f'          <span class="g-name">{name} <small>{unit}</small></span>\n'
            f'          <span class="g-cell"><strong>{out_v}</strong> <span class="mono">{out_p}</span></span>\n'
            '          <span class="g-arrow">&rarr;</span>\n'
            f'          <span class="g-cell"><strong>{base_v}</strong> <span class="mono">{base_p}</span></span>\n'
            "        </div>"
        )

    return "\n".join(
        [
            '      <div class="glance-rows">',
            '        <div class="glance-row glance-row-head mono">'
            '<span class="g-name">indicator</span>'
            '<span>latest outturn</span><span></span>'
            '<span>LONGBASE baseline</span></div>',
            row("Real GDP growth", "y/y", f"{fmt(g_now['value'])}%", g_now["period"],
                f"{fmt(g_base['gdp_yoy_pct'])}%", g_base["quarter"]),
            row("CPI inflation", "y/y", f"{fmt(c_now['value'])}%", c_now["period"],
                f"{fmt(c_base['cpi_yoy_pct'])}%", c_base["quarter"]),
            row("Unemployment rate", "", f"{fmt(u_now['value'])}%", u_now["period"],
                f"{fmt(u_base['unemployment_pct'])}%", u_base["quarter"]),
            "      </div>",
            f'      <p class="glance-caption">{caption}</p>',
        ]
    )


def render_home() -> str:
    html = HOME_PAGE.read_text()
    html = replace(html, "home-uk-now", home_uk_now())
    html = replace(html, "home-us-now", home_us_now())
    return html


def render_uk() -> str:
    html = PAGE.read_text()
    html = replace(html, "economy-cards", cards())
    html = replace(html, "economy-trends-figures", uk_figures())
    html = replace(html, "economy-indicators", indicator_rows())
    html = replace(html, "economy-outlook", outlook_rows())
    html = replace(html, "economy-markets", market_rows())
    html = replace(html, "economy-calendar", calendar_rows())
    html = replace(html, "economy-releases", release_rows())
    return html


def render_us() -> str:
    html = US_PAGE.read_text()
    html = replace(html, "us-economy-cards", us_cards())
    html = replace(html, "us-economy-trends-figures", us_figures())
    html = replace(html, "us-economy-indicators", us_indicator_rows())
    html = replace(html, "us-economy-markets", us_market_rows())
    html = replace(html, "us-economy-releases", us_release_rows())
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered_home = render_home()
    rendered_uk = render_uk()
    rendered_us = render_us()
    if args.check:
        stale = []
        for path, rendered in (
            (HOME_PAGE, rendered_home),
            (PAGE, rendered_uk),
            (US_PAGE, rendered_us),
        ):
            if rendered != path.read_text():
                stale.append(str(path.relative_to(ROOT)))
        if stale:
            print(f"{', '.join(stale)} stale; run python3 economy/build.py")
            return 1
        print("UK and US Economy pages match committed data")
        return 0
    HOME_PAGE.write_text(rendered_home)
    PAGE.write_text(rendered_uk)
    US_PAGE.write_text(rendered_us)
    print("updated UK and US Economy pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
