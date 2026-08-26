#!/usr/bin/env python3
"""Regenerate the UK and US Economy pages from committed vintages."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "economy" / "index.html"
US_PAGE = ROOT / "economy" / "us" / "index.html"


def _topics_module():
    """The topic generator, imported for its series-to-topic table.

    /economy is a hub: it indexes the series and points at the topic page that
    reads each one. The mapping is the topic table itself rather than a second
    copy here, so a series can never be advertised on the hub as belonging to a
    topic that has stopped carrying it — ``topic_link`` raises instead.
    """
    spec = importlib.util.spec_from_file_location(
        "economy_topics", Path(__file__).resolve().parent / "topics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TOPICS = _topics_module()
TOPIC_PAGES = _TOPICS.TOPICS
# Keyed by series rather than by slug, because the same slug now exists in two
# countries: /economy/topics/growth and /economy/us/topics/growth are different
# pages reading different series. Series names carry their country prefix, so
# the mapping stays unambiguous and each hub links into its own scope.
SERIES_TOPIC = {
    name: (_TOPICS.topic_url(topic), topic["title"])
    for topic in TOPIC_PAGES
    for name in topic["series"]
}

# Reading order on the hub index: the ONS series grouped the way the topics
# are, then the Bank of England rate series under their own subhead.
ONS_SERIES = (
    "uk_gdp_cvm",
    "uk_monthly_gva",
    "uk_business_investment",
    "uk_cpi_yoy",
    "uk_core_cpi_yoy",
    "uk_unemployment_rate",
    "uk_average_weekly_earnings",
    "uk_vacancies",
    "uk_public_sector_net_borrowing",
    "uk_public_sector_net_debt_gdp",
)
MARKET_SERIES = ("uk_bank_rate", "uk_gilt_5y", "uk_gilt_10y", "uk_gilt_20y")

# The same two groups for the US hub, in the same reading order: the series
# the topic pages read, then the two rate series under their own subhead.
FRED_SERIES = (
    "us_real_gdp",
    "us_cpi",
    "us_unemployment_rate",
    "us_payroll_employment",
)
US_MARKET_SERIES = ("us_federal_funds_rate", "us_treasury_10y")

# Catalogue titles are not reader-facing labels. One table, shared with the
# topic generator, so a series is called the same thing on the hub that indexes
# it and on the topic page that reads it.
PUBLIC_LABELS = _TOPICS.PUBLIC_LABELS


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


def us_trends_note() -> str:
    """The long view, and the two respects in which it is shorter than the UK's.

    The UK hub draws three quarterly series over 20 quarters. Two of the three
    US series are monthly, so the identical 20-point window is 20 months, and
    every US series in this store begins in 2020 where the ONS series behind
    the UK charts run back decades. Both facts are derived from the manifest
    and the observations rather than asserted, so the sentence cannot outlive
    the data it describes.
    """
    index = _TOPICS.manifest()
    gdp = gdp_growth(load("us_real_gdp"))[-20:]
    cpi = yoy_growth(load("us_cpi"), 12)[-20:]
    unemployment = load("us_unemployment_rate")["observations"][-20:]
    us_start = min(
        index[name]["coverage"][0] for name in FRED_SERIES + US_MARKET_SERIES
    )
    uk_start = min(index[name]["coverage"][0] for name in ONS_SERIES)
    return f"""    <p class="economy-method">
      The topic pages carry the current reading and, where one exists, the
      conditioning baseline beside it; these three charts are the one place the
      whole path is drawn. Each is generated from the same committed
      point-in-time observations, and the source link opens the corresponding
      official series. Two of the three are shorter than their UK counterparts:
      GDPC1 is quarterly, so twenty points span {gdp[0]['period']}–{gdp[-1]['period']}, but CPIAUCSL
      and UNRATE are monthly, so the same twenty-point window covers only
      {cpi[0]['period']}–{cpi[-1]['period']} and {unemployment[0]['period']}–{unemployment[-1]['period']}. And no US series in this store
      starts before {us_start}, where the ONS series behind the UK charts reach
      back to {uk_start}: the long view here is as long as the store, not as long
      as the published record.
    </p>"""


def us_release_dates_absent(names: tuple[str, ...]) -> None:
    """/economy/us says FRED announces no release dates. Check, do not assume.

    The US hub carries no ``Released`` column and no release calendar, and
    tells the reader why. Both absences are claims about the data, so they are
    re-derived here: if a US snapshot ever arrives with either field populated,
    the build fails instead of the page quietly under-reporting what is known.
    """
    announced = sorted(
        name
        for name in names
        if load(name).get("release_updated") or load(name).get("next_release")
    )
    if announced:
        raise RuntimeError(
            f"{', '.join(announced)} now carries a release date, but "
            "/economy/us tells readers FRED supplies none — give the US hub "
            "its Released column and its release calendar back"
        )


def topic_link(name: str) -> str:
    """The topic page that reads this series, or a hard failure.

    The hub advertises a topic home for every series it indexes. If a topic
    stops carrying a series, this raises rather than printing a link into a
    page where the number is no longer shown.
    """
    entry = SERIES_TOPIC.get(name)
    if entry is None:
        raise RuntimeError(
            f"{name} is indexed on an economy hub but no topic page in "
            f"economy/topics.py reads it — give it a topic home or drop it "
            f"from the hub index"
        )
    url, title = entry
    return f'<a href="{url}">{title}</a>'


def series_index_rows(names: tuple[str, ...], released: bool = True) -> str:
    """The hub index: what is tracked, which topic reads it, where it came from.

    Deliberately carries no readings. The values, their period comparisons and
    the model view of each one live on the topic pages; repeating them here is
    what turned /economy and /economy/topics into two dashboards over one set
    of numbers.

    ``released`` drops the publisher's release date, which the US hub does: the
    ONS stamps every series with one, FRED stamps none of them through this
    site's fetcher, and a column of six identical "not supplied" cells says
    less than one sentence of prose. ``us_release_dates_absent`` is what keeps
    that sentence true.
    """
    rows = []
    for name in names:
        series = load(name)
        now = latest(series)
        release = (
            f"<td>{(series.get('release_updated') or 'not supplied').split('T')[0]}</td>"
            if released
            else ""
        )
        rows.append(
            "          <tr>"
            f'<th scope="row">{public_label(series)}</th>'
            f"<td>{topic_link(name)}</td>"
            f"<td>{now['period']}</td>"
            f"{release}"
            f"<td>{series['vintage']}</td>"
            f'<td><a href="{series["url"]}">{series["source"]} · {series["cdid"]}</a></td>'
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
    """The UK hub. ``economy-topics`` belongs to economy/topics.py, not here."""
    html = PAGE.read_text()
    html = replace(html, "economy-trends-figures", uk_figures())
    html = replace(html, "economy-series-index", series_index_rows(ONS_SERIES))
    html = replace(html, "economy-market-index", series_index_rows(MARKET_SERIES))
    html = replace(html, "economy-calendar", calendar_rows())
    return html


def render_us() -> str:
    """The US hub, the same shape as the UK one: directory, long view, index.

    No stat cards and no indicator table: every reading they carried is on the
    topic page that owns the series, and the hub's job is the provenance
    behind them.
    """
    us_release_dates_absent(FRED_SERIES + US_MARKET_SERIES)
    html = US_PAGE.read_text()
    html = replace(html, "us-economy-trends-note", us_trends_note())
    html = replace(html, "us-economy-trends-figures", us_figures())
    html = replace(
        html, "us-economy-series-index", series_index_rows(FRED_SERIES, released=False)
    )
    html = replace(
        html,
        "us-economy-market-index",
        series_index_rows(US_MARKET_SERIES, released=False),
    )
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered_uk = render_uk()
    rendered_us = render_us()
    if args.check:
        stale = []
        for path, rendered in (
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
    PAGE.write_text(rendered_uk)
    US_PAGE.write_text(rendered_us)
    print("updated UK and US Economy pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
