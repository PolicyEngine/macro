#!/usr/bin/env python3
"""Regenerate the data-store block and release calendar from committed vintages.

Writes two artifacts, both committed:

    forecasts/index.html   the data-store section, spliced between markers
    data/calendar.ics      an iCalendar feed of announced next releases

There is no /data page: the store exists to make the forecast record
reproducible, so it lives in the section explaining what a round is scored
against. /data and /data/ redirect to /forecasts#data; the JSON endpoints
under /data/ are unaffected.

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
FORECASTS = ROOT / "forecasts" / "index.html"
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
    """ONS serves observations from a JSON `/data` endpoint, which is a poor
    destination for a reader clicking through to the official page. Keep the
    API URL in the committed vintage and link the human-readable page."""
    if "ons.gov.uk/" in url and url.endswith("/data"):
        return url[: -len("/data")]
    return url


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
    for position, name in enumerate(sorted(index)):
        entry = index[name]
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
        facts = [
            ("Units", esc(series["units"])),
            ("Coverage", f"{esc(first)} – {esc(last)}"),
            ("Observations", f"{len(series['observations']):,}"),
            ("Store path", f'<span class="mono">{esc(source_dir)}/{esc(name)}</span>'),
            ("Next release", esc(next_release) if next_release else "not announced"),
            ("Official source",
             f'<a href="{esc(display_url(series["url"]))}">'
             f'{esc(series["source"])} · {esc(series["cdid"])}</a>'),
        ]
        dl = "\n".join(
            f"                  <div><dt>{label}</dt><dd>{value}</dd></div>"
            for label, value in facts
        )
        groups.append(
            f'            <tbody class="series-group" data-index="{position}">\n'
            f'              <tr class="series-row">\n'
            f'                <th scope="row">\n'
            f'                  <button type="button" class="series-toggle"'
            f' aria-expanded="true" aria-controls="{esc(detail_id)}">'
            f'<span class="series-name">{esc(public_label(series))}</span>'
            f'<span class="mono">{esc(name)}</span></button>\n'
            f"                </th>\n"
            f'                <td>{esc(series["source"])}</td>\n'
            f'                <td>{esc(series["frequency"])}</td>\n'
            f'                <td class="num">{fmt_value(now["value"])} '
            f'<span class="mono">{esc(now["period"])}</span></td>\n'
            f'                <td class="num">{len(vintages)}</td>\n'
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
    return "\n".join(lines)


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
    """The data-store block inside /forecasts, between the markers.

    Not a page of its own. The vintage store exists to make the forecast
    record reproducible, so it lives in the section that explains what a
    round is scored against rather than as a sixth destination competing
    with Models and Economy.
    """
    series_count, snapshot_count, earliest = counts()
    calendar_count = len(upcoming())
    return f"""{BEGIN}
    <div class="prose">
      <p>
        Rounds are scored against official data, and official data gets
        revised. Every series this site reads is therefore archived as dated
        snapshots that are never edited and never deleted — {series_count}
        series, {snapshot_count} snapshots since {earliest} — so a score can
        be reproduced against the data as it stood, not as it was later
        revised. Reading only the current value would make look-ahead bias
        undetectable, because only one version of the past would ever exist.
      </p>

      <h3>What is tracked</h3>
      <div class="table-scroll">
        <table id="series-table" class="series-table">
          <caption>Values come from the committed snapshot, not a live call. Expand a row for its snapshot history and store path.</caption>
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
        <button type="button" id="show-all" class="series-show-all" hidden
                aria-controls="series-table" aria-expanded="false"></button>
      </p>

      <h3>Reconstruct a series as it was published on a date</h3>
      <p>
        <code>MANIFEST.json</code> lists every snapshot date held for every
        series. Take the newest on or before the date you want, and read that
        file. Standard library only, no key, no account.
      </p>
{recipe_block()}
      <p>
        A later date returns a later snapshot, which may carry revised values
        for periods the earlier one already covered. That difference is the
        revision. The store begins {earliest}, when the first snapshot was
        taken — it is a forward-looking real-time record from that date, not a
        reconstruction of vintages predating it.
      </p>

      <h3>Announced releases</h3>
      <div class="table-scroll">
        <table>
          <caption>{calendar_count} announced releases, from the committed snapshots. Only the ONS publishes the field; dates are the publisher's and can move. Also an iCalendar feed: <a href="/data/calendar.ics">/data/calendar.ics</a>.</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Series</th><th scope="col">Source</th></tr></thead>
          <tbody>
{calendar_rows()}
          </tbody>
        </table>
      </div>

      <h3>Endpoints</h3>
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
    </div>
    {END}"""


def splice(page: str, fragment: str) -> str:
    """Replace the marked block in /forecasts, leaving the rest untouched."""
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
        print("Forecasts data block and release calendar match committed data")
        return 0
    for path, content in rendered:
        path.write_bytes(content)
    print("updated the forecasts data block and release calendar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
