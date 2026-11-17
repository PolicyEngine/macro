#!/usr/bin/env python3
"""Regenerate the data-store block and release calendar from committed vintages.

Writes two artifacts, both committed:

    economy/index.html     the data-store section, spliced between markers
    data/calendar.ics      an iCalendar feed of announced next releases

There is no /data page: the store lives on the UK data hub (/economy#data,
the "Data" tab), beside the long view it feeds. It moved there from
/forecasts, where it was the longest section of the track record; /forecasts
keeps a one-line pointer under the #data anchor so old links still land.
/data and /data/ redirect to /economy#data; the JSON endpoints under /data/
are unaffected.

Nothing here reads the clock or the network: the same store always renders the
same bytes, so ``--check`` is a real drift test rather than a coin flip.
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STORE = ROOT / "data"
FORECASTS = ROOT / "economy" / "index.html"  # the page that hosts the store
BEGIN = "<!-- data-store:begin -->"
END = "<!-- data-store:end -->"
CALENDAR = STORE / "calendar.ics"

SITE = "https://policyengine-macro.vercel.app"
HOST = "policyengine-macro.vercel.app"

# Shared with economy/build.py: the ONS series titles are catalogue strings, not
# reader-facing labels. Anything not listed keeps its published title, which is
# already short and readable for the Bank of England and FRED series.
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

# The worked example in the "as-of" recipe. Chosen because uk_cpi_yoy is the
# one series with two vintages of the same last period, so a reader can change
# the date and watch the answer change.
# Rows shown before the reader asks for the rest. Twenty series is a wall on
# first view; five is enough to show what a row contains and that the list
# is alphabetical, without the section dominating the page.
PREVIEW_ROWS = 5

RECIPE_SOURCE = "ons"
RECIPE_SERIES = "uk_cpi_yoy"
RECIPE_DATE = "2026-07-25"


def manifest() -> dict:
    return json.loads((STORE / "MANIFEST.json").read_text(encoding="utf-8"))


def load(name: str) -> dict:
    return json.loads(
        (STORE / "latest" / f"{name}.json").read_text(encoding="utf-8")
    )


def source_dirs() -> dict[str, str]:
    """Map each series to the ``vintages/<source>/`` directory holding it."""
    found: dict[str, str] = {}
    for directory in sorted((STORE / "vintages").iterdir()):
        if not directory.is_dir():
            continue
        for series in sorted(directory.iterdir()):
            if series.is_dir():
                found[series.name] = directory.name
    return found


def public_label(series: dict) -> str:
    return PUBLIC_LABELS.get(series["cdid"], series["title"])


def display_url(url: str) -> str:
    """ONS serves observations from a JSON `/data` endpoint, which is a bad
    destination for a reader clicking through to the official page. Keep the
    API URL in the committed vintage and link the human-readable page."""
    if "ons.gov.uk/" in url and url.endswith("/data"):
        return url[: -len("/data")]
    return url


def unit_short(series: dict) -> str:
    """The unit beside a latest value: '%' for rates, else the first clause."""
    units = str(series.get("units", "")).split(",")[0].strip()
    if not units:
        return ""
    if units.lower().startswith("percent"):
        return "%"
    return f' <span class="unit">{esc(units)}</span>'


# Releases already published but not yet in the store (the store only grows
# through data/fetch.py; nothing here edits a vintage).
STALE_NOTES = {
    # name: (the published period not yet in the store, note). The note
    # disappears by itself once a vintage carrying that period is fetched.
    "uk_business_investment": ("2026Q3", "2026Q3 first estimate published 12 Nov 2026, not yet ingested"),
}


def stale_note(name: str, latest_period: str) -> str:
    entry = STALE_NOTES.get(name)
    return entry[1] if entry and latest_period < entry[0] else ""


def value_with_unit(value: float, series: dict, name: str = "") -> str:
    """A latest value with its unit placed as readers expect: '£757.0 per
    week', '£83,534m', '4.0%'. The stored number is not rounded."""
    units = str(series.get("units", "")).split(",")[0].strip()
    if name == "uk_public_sector_net_borrowing" or series.get("cdid") == "J5II":
        if units.startswith("£m") and value < 0:
            return f"£{-value / 1000:,.1f}bn borrowed"
    text = f"{int(value):,}" if float(value).is_integer() and units.startswith("£m") else fmt_value(value)
    if units.lower().startswith("percent"):
        return f"{text}%"
    if units.startswith("£m"):
        return f"£{text}m"
    if units.startswith("£ "):
        return f"£{text} {esc(units[2:])}"
    return text + unit_short(series)


def fmt_value(value: float) -> str:
    """Show the stored number, thousands-separated, with no rounding applied."""
    return f"{value:,}"


def release_date(series: dict) -> datetime | None:
    """Parse an ONS `next_release` string like "19 August 2026".

    Some ONS responses double-space the month, so collapse whitespace first.
    Anything missing or unparseable is skipped rather than guessed at.
    """
    raw = " ".join((series.get("next_release") or "").split())
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d %B %Y")
    except ValueError:
        return None


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


_TOPIC_HOMES: dict[str, tuple[str, str]] | None = None


def topic_home(name: str) -> tuple[str, str] | None:
    """(url, title) of the topic page that reads a series, from economy/topics.py.

    The /economy hubs used to carry this series-to-topic index; the store is
    its home now (DESIGN.md §7.0).
    """
    global _TOPIC_HOMES
    if _TOPIC_HOMES is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "economy_topics", ROOT / "economy" / "topics.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TOPIC_HOMES = {
            series: (module.topic_url(topic), topic["title"])
            for topic in module.TOPICS
            for series in topic["series"]
        }
    return _TOPIC_HOMES.get(name)


_TOPICS_MODULE = None


def _topics():
    """economy/topics.py, loaded once (topic homes and the topic icon set)."""
    global _TOPICS_MODULE
    if _TOPICS_MODULE is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("economy_topics", ROOT / "economy" / "topics.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TOPICS_MODULE = module
    return _TOPICS_MODULE


# Small Lucide icons used only in the catalogue.
_ICON = {
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "chev": '<path d="m6 9 6 6 6-6"/>',
    "landmark": '<line x1="3" x2="21" y1="22" y2="22"/><line x1="6" x2="6" y1="18" y2="11"/><line x1="10" x2="10" y1="18" y2="11"/><line x1="14" x2="14" y1="18" y2="11"/><line x1="18" x2="18" y1="18" y2="11"/><polygon points="12 2 20 7 4 7"/>',
    "chart": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
}


def ic(name: str, size: int = 14, cls: str = "ds-ic") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
            'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{_ICON[name]}</svg>')


# Catalogue groups, in reading order: (topic slug for the icon, heading).
GROUPS = [
    ("inflation", "Prices"),
    ("growth", "Growth"),
    ("jobs", "Jobs"),
    ("rates", "Rates"),
    ("public-finances", "Public finances"),
]
GROUP_OF = {
    "uk_cpi_yoy": "inflation", "uk_core_cpi_yoy": "inflation", "us_cpi": "inflation",
    "uk_gdp_cvm": "growth", "uk_monthly_gva": "growth", "uk_business_investment": "growth", "us_real_gdp": "growth",
    "uk_unemployment_rate": "jobs", "uk_vacancies": "jobs", "uk_average_weekly_earnings": "jobs",
    "us_unemployment_rate": "jobs", "us_payroll_employment": "jobs",
    "uk_bank_rate": "rates", "uk_gilt_5y": "rates", "uk_gilt_10y": "rates", "uk_gilt_20y": "rates",
    "us_federal_funds_rate": "rates", "us_treasury_10y": "rates",
    "uk_public_sector_net_borrowing": "public-finances", "uk_public_sector_net_debt_gdp": "public-finances",
}
PUBLISHER_ICON = {"ONS": "chart", "Bank of England": "landmark", "FRED": "database"}


def group_of(name: str) -> str:
    """The catalogue group a series sits in; a new series must be placed."""
    if name not in GROUP_OF:
        raise KeyError(f"{name}: add it to data/build_page.py GROUP_OF")
    return GROUP_OF[name]


def period_label(period: str) -> str:
    """One date format: 'Aug 2026', '13 Nov 2026', '2026Q3'."""
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    parts = period.split("-")
    if len(parts) == 3:
        return f"{int(parts[2])} {months[int(parts[1]) - 1]} {parts[0]}"
    if len(parts) == 2:
        return f"{months[int(parts[1]) - 1]} {parts[0]}"
    return period


def catalogue_rows() -> str:
    """One <tbody> per series: a scannable row plus an expandable detail row.

    A table, because the point of a catalogue is comparing series against
    each other down a column. Expandable, because the nine columns needed to
    say everything forced horizontal scrolling and still hid the vintage
    history — the thing the store exists for.

    Progressive enhancement: the detail rows are OPEN in the HTML and the
    script collapses them on load. With JavaScript unavailable the page is
    verbose but complete, never a table of rows that cannot be opened.
    """
    index = manifest()["series"]
    dirs = source_dirs()
    groups = []
    order = [n for slug, _ in GROUPS for n in sorted(index) if group_of(n) == slug]
    last_group = None
    for position, name in enumerate(order):
        entry = index[name]
        slug = group_of(name)
        if slug != last_group:
            heading = dict(GROUPS)[slug]
            count = sum(1 for n in order if group_of(n) == slug)
            groups.append(
                f'            <tbody class="series-cat" data-cat="{slug}">\n'
                f'              <tr><th scope="rowgroup" colspan="5">{_topics().topic_icon(slug, 16)}'
                f'<span>{heading}</span><span class="series-cat-n">{count}</span></th></tr>\n'
                f"            </tbody>"
            )
            last_group = slug
        series = load(name)
        now = series["observations"][-1]
        first, last = entry["coverage"]
        source_dir = dirs[name]
        vintages = sorted(entry["vintages"], reverse=True)
        detail_id = f"detail-{name}"

        listed = "\n".join(
            f'                  <li><a href="/data/vintages/{esc(source_dir)}/'
            f'{esc(name)}/{esc(vintage)}.json">{esc(vintage)}</a></li>'
            for vintage in vintages
        )
        next_release = series.get("next_release")
        released = series.get("release_updated")
        home = topic_home(name)
        facts = [
            ("Topic", f'<a href="{home[0]}">{esc(home[1])}</a>' if home else "none"),
            ("Units", esc(series["units"])),
            ("Coverage", f"{esc(first)} – {esc(last)}"),
            ("Observations", f"{len(series['observations']):,}"),
            ("Store path", f'<span class="mono">{esc(source_dir)}/{esc(name)}</span>'),
            ("Released", esc(released[:10]) if released else "not supplied by the source"),
            ("Next release", esc(next_release) if next_release else "not announced"),
            *([("Note", esc(stale_note(name, now["period"])))] if stale_note(name, now["period"]) else []),
            ("Official source",
             f'<a href="{esc(display_url(series["url"]))}">'
             f'{esc(series["source"])} · {esc(series["cdid"])}</a>'),
        ]
        dl = "\n".join(
            f"                  <div><dt>{label}</dt><dd>{value}</dd></div>"
            for label, value in facts
        )
        note = stale_note(name, now["period"])
        freq = series["frequency"]
        publisher = series["source"]
        groups.append(
            f'            <tbody class="series-group" data-index="{position}" data-cat="{slug}">\n'
            f'              <tr class="series-row">\n'
            f'                <th scope="row">\n'
            f'                  <button type="button" class="series-toggle"'
            f' aria-expanded="true" aria-controls="{esc(detail_id)}">'
            f'<span class="series-name">{esc(public_label(series))}</span>'
            f'<span class="mono">{esc(name)}</span></button>\n'
            f"                </th>\n"
            f'                <td class="ds-src"><span class="ds-chip ds-pub">{ic(PUBLISHER_ICON.get(publisher, "database"))}{esc(publisher)}</span></td>\n'
            f'                <td class="ds-freq"><span class="ds-chip">{ic("clock" if freq == "daily" else "calendar")}{esc(freq)}</span></td>\n'
            f'                <td class="num ds-latest"><strong class="ds-val">{value_with_unit(now["value"], series, name)}</strong>'
            f'<span class="ds-date">{esc(period_label(now["period"]))}</span>'
            + (f'<span class="ds-stale" title="{esc(note)}">{ic("alert", 12)}{esc(STALE_NOTES[name][0])} not yet ingested</span>' if note else "")
            + "</td>\n"
            f'                <td class="num ds-snaps"><span title="{len(vintages)} snapshots">{ic("layers")}{len(vintages)}</span></td>\n'
            f"              </tr>\n"
            f'              <tr class="series-detail-row" id="{esc(detail_id)}">\n'
            f'                <td colspan="5">\n'
            f"                  <dl>\n{dl}\n                  </dl>\n"
            f'                  <p class="series-vintages-head">Every snapshot '
            f"taken, newest first — each file immutable.</p>\n"
            f'                  <ul class="vintage-list mono">\n{listed}\n'
            f"                  </ul>\n"
            f"                </td>\n"
            f"              </tr>\n"
            f"            </tbody>"
        )
    return "\n".join(groups)


def upcoming() -> list[tuple[datetime, str, dict]]:
    """Announced next releases, sorted by date then series name."""
    index = manifest()["series"]
    releases = []
    for name in sorted(index):
        series = load(name)
        when = release_date(series)
        if when is not None:
            releases.append((when, name, series))
    return sorted(releases, key=lambda row: (row[0], row[1]))


def last_fetch() -> str:
    """Newest snapshot date anywhere in the store: the store's own 'as of'."""
    return max(entry["latest_vintage"] for entry in manifest()["series"].values())


def release_status(when: datetime, series: dict) -> str:
    """Whether an announced date is still ahead of the store, or has passed.

    Deterministic: compares the announcement with the store's own newest
    snapshot, never the clock. A date before the last fetch with no newer
    snapshot of the series means the release has not been captured yet.
    """
    fetched = datetime.strptime(last_fetch(), "%Y-%m-%d")
    if when > fetched:
        return "ahead of the last fetch"
    return f"passed; not in the store as of {fetched:%Y-%m-%d}"


def calendar_rows() -> str:
    rows = []
    for when, name, series in upcoming():
        rows.append(
            "          <tr>"
            f'<th scope="row">{when.strftime("%d %B %Y")}</th>'
            f"<td>{esc(public_label(series))}</td>"
            f'<td><span class="mono">{esc(name)}</span></td>'
            f'<td><a href="{esc(display_url(series["url"]))}">'
            f'{esc(series["source"])} · {esc(series["cdid"])}</a></td>'
            f"<td>{esc(release_status(when, series))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def recipe() -> list[tuple[str, str]]:
    """The as-of snippet, as (code, trailing comment) pairs.

    The expected output is read out of the committed vintage rather than typed
    in, so the snippet cannot drift away from what the endpoint returns.
    """
    vintage = json.loads(
        (
            STORE / "vintages" / RECIPE_SOURCE / RECIPE_SERIES / f"{RECIPE_DATE}.json"
        ).read_text(encoding="utf-8")
    )
    expected = f"{vintage['vintage']} {vintage['observations'][-1]!r}"
    return [
        ("import json, urllib.request", ""),
        ("", ""),
        (f'BASE = "{SITE}/data"', ""),
        ("", ""),
        ("def get(path):", ""),
        ('    with urllib.request.urlopen(f"{BASE}/{path}") as response:', ""),
        ("        return json.load(response)", ""),
        ("", ""),
        ("def as_of(source, series, date):", ""),
        (
            '    dates = get("MANIFEST.json")["series"][series]["vintages"]',
            "# every snapshot ever taken",
        ),
        ("    dates = [d for d in dates if d <= date]", ""),
        ("    if not dates:", ""),
        (
            '        raise LookupError(f"no {series} vintage on or before {date}")',
            "",
        ),
        (
            '    return get(f"vintages/{source}/{series}/{max(dates)}.json")',
            "# immutable file",
        ),
        ("", ""),
        (
            f'cpi = as_of("{RECIPE_SOURCE}", "{RECIPE_SERIES}", "{RECIPE_DATE}")',
            "",
        ),
        ('print(cpi["vintage"], cpi["observations"][-1])', f"# {expected}"),
    ]


def recipe_block() -> str:
    width = max(len(code) for code, comment in recipe() if comment)
    lines = []
    for code, comment in recipe():
        if comment:
            padding = " " * (width - len(code) + 3)
            lines.append(
                f'{esc(code)}{padding}<span class="cm">{esc(comment)}</span>'
            )
        else:
            lines.append(esc(code))
    # In a code block, not loose in the prose: unwrapped, the recipe ran as
    # running text and its long unbreakable lines pushed /forecasts 51 px
    # past a 375 px viewport. The block scrolls inside itself instead.
    body = "\n".join(lines)
    return f'      <div class="codeblock"><pre><code>{body}</code></pre></div>'


def counts() -> tuple[int, int, str]:
    index = manifest()["series"]
    snapshots = sum(len(entry["vintages"]) for entry in index.values())
    earliest = min(entry["vintages"][0] for entry in index.values())
    return len(index), snapshots, earliest


def fold(line: str) -> str:
    """Fold an iCalendar content line to 75 octets, per RFC 5545 §3.1.

    Folding is measured in octets, not characters, so split the encoded form
    and never cut a multi-byte character in half.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    chunks, start = [], 0
    limit = 75
    while start < len(encoded):
        end = min(start + limit, len(encoded))
        while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(encoded[start:end].decode("utf-8"))
        start = end
        limit = 74  # continuation lines carry a leading space
    return "\r\n ".join(chunks)


def ics_text(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def render_calendar() -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PolicyEngine Macro//Data release calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:PolicyEngine Macro — official statistics releases",
        "X-WR-CALDESC:Announced next release dates for the series in the "
        "PolicyEngine Macro vintage store.",
    ]
    for when, name, series in upcoming():
        day = when.strftime("%Y%m%d")
        # DTSTAMP is the moment the snapshot carrying this announcement was
        # fetched, not the moment this file was generated: a build with no new
        # data must produce byte-identical output.
        stamp = series["fetched_utc"].replace("-", "").replace(":", "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{name}-{day}@{HOST}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day}",
            f"DTEND;VALUE=DATE:{(when + timedelta(days=1)).strftime('%Y%m%d')}",
            "SUMMARY:" + ics_text(
                f"{series['source']} release: {public_label(series)}"
            ),
            "DESCRIPTION:" + ics_text(
                f"{series['title']} ({series['cdid']}). Announced by "
                f"{series['source']} in the {series['vintage']} snapshot of "
                f"{name}. Units: {series['units']}."
            ),
            f"URL:{SITE}/data",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(f"{fold(line)}\r\n" for line in lines)


def render_fragment() -> str:
    """The data-store block inside /economy, between the markers.

    The one home of data provenance (DESIGN.md §7.0): the /economy hubs used
    to repeat its series list and calendar, and now link here instead.

    Not a page of its own. The vintage store exists to make the forecast
    record reproducible, so it lives in the section that explains what a
    round is scored against rather than as a sixth destination competing
    with Models and Economy.
    """
    series_count, snapshot_count, earliest = counts()
    calendar_count = len(upcoming())
    return f"""{BEGIN}
    <div class="prose">
      <p class="store-chips"><span>{series_count} series</span><span>{snapshot_count} snapshots</span><span>since {earliest}</span></p>
      <div class="table-scroll">
        <table id="series-table" class="series-table ds-table">
          <caption><span class="ds-hint">{ic("chev")}Expand a row for its snapshot history and store path.</span></caption>
          <thead>
            <tr>
              <th scope="col">Series</th>
              <th scope="col">Source</th>
              <th scope="col">Frequency</th>
              <th scope="col">Latest</th>
              <th scope="col">Snapshots</th>
            </tr>
          </thead>
{catalogue_rows()}
        </table>
      </div>
      <p class="table-controls">
        <button type="button" id="show-all" class="btn btn-secondary series-show-all" hidden
                aria-controls="series-table" aria-expanded="false"></button>
      </p>

      <details class="about">
        <summary>Why the store exists</summary>
        <p>
          Rounds are scored against official data, and official data gets
          revised. Dated snapshots let a score be reproduced against the data
          as it stood, not as it was later revised. Reading only the current
          value would make look-ahead bias undetectable, because only one
          version of the past would ever exist.
        </p>
      </details>

      <details class="about">
        <summary>Read a series as it was published on a date</summary>
      <p>
        Take the newest snapshot on or before your date. No key, no account,
        standard library only.
      </p>
{recipe_block()}
      <p>
        Two dates, two snapshots: the difference between them is the revision.
        The store starts {earliest} and runs forward from there — it does not
        reconstruct vintages older than itself.
      </p>
      </details>

      <details class="about">
        <summary>Announced releases</summary>
      <div class="table-scroll">
        <table>
          <caption>{calendar_count} announced releases, from the committed snapshots; the store was last updated {last_fetch()}. Only the ONS publishes the field; dates are the publisher's and can move. Also an iCalendar feed: <a href="/data/calendar.ics">/data/calendar.ics</a>.</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Series</th><th scope="col">Store id</th><th scope="col">Source</th><th scope="col">Status</th></tr></thead>
          <tbody>
{calendar_rows()}
          </tbody>
        </table>
      </div>
      </details>

      <details class="about">
        <summary>Endpoints and file format</summary>
      <div class="table-scroll">
        <table>
          <caption>Static files over HTTPS, GET and HEAD only — there is no API to authenticate against. Everything under <code>/data/</code> is served with <code>Access-Control-Allow-Origin: *</code>, so a browser-side notebook or dashboard on any origin can read it directly.</caption>
          <thead><tr><th scope="col">Endpoint</th><th scope="col">Contains</th><th scope="col">Stability</th></tr></thead>
          <tbody>
          <tr><th scope="row"><span class="mono">/data/MANIFEST.json</span></th><td>Index of every series: source, CDID, units, frequency, coverage, and every snapshot date.</td><td>Rewritten on each fetch; short cache.</td></tr>
          <tr><th scope="row"><span class="mono">/data/latest/&lt;series&gt;.json</span></th><td>The newest snapshot, flattened. Same schema as a vintage file.</td><td>Moves. Do not cite as a fixed reference.</td></tr>
          <tr><th scope="row"><span class="mono">/data/vintages/&lt;source&gt;/&lt;series&gt;/&lt;YYYY-MM-DD&gt;.json</span></th><td>One dated snapshot, exactly as fetched.</td><td>Immutable by construction; one-year cache.</td></tr>
          <tr><th scope="row"><span class="mono">/data/calendar.ics</span></th><td>The release calendar above, as iCalendar.</td><td>Regenerated with the store.</td></tr>
          </tbody>
        </table>
      </div>
      <p class="chooser-note">
        Each file carries <span class="mono">series, source, cdid, title, frequency, units, url,
        release_updated, first_period, last_period, observations, vintage, fetched_utc</span>.
        Snapshot dates are when a change was recorded, not a daily calendar: a fetch
        that found nothing new wrote no file. ONS and Bank of England series are under the
        <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">Open Government Licence v3.0</a>;
        US series come via FRED with their original BEA, BLS and Federal Reserve attribution.
      </p>
      </details>
    </div>
    {END}"""


def splice(page: str, fragment: str) -> str:
    """Replace the marked block in /economy, leaving the rest untouched."""
    start = page.index(BEGIN)
    end = page.index(END) + len(END)
    return page[:start] + fragment + page[end:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    page = FORECASTS.read_text(encoding="utf-8")
    if BEGIN not in page or END not in page:
        print(f"{FORECASTS.relative_to(ROOT)} is missing the data-store markers")
        return 1

    # Compared and written as bytes: the calendar uses the CRLF line endings
    # RFC 5545 requires, and text mode would silently translate them.
    rendered = (
        (FORECASTS, splice(page, render_fragment()).encode("utf-8")),
        (CALENDAR, render_calendar().encode("utf-8")),
    )
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path, content in rendered
            if not path.exists() or content != path.read_bytes()
        ]
        if stale:
            print(f"{', '.join(stale)} stale; run python3 data/build_page.py")
            return 1
        print("Data-store block and release calendar match committed data")
        return 0
    for path, content in rendered:
        path.write_bytes(content)
    print("updated the economy data-store block and release calendar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
