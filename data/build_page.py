#!/usr/bin/env python3
"""Regenerate the public Data page and release calendar from committed vintages.

Writes two artifacts, both committed:

    data/index.html    the /data page
    data/calendar.ics  an iCalendar feed of announced next releases

Nothing here reads the clock or the network: the same store always renders the
same bytes, so ``--check`` is a real drift test rather than a coin flip.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The global header and pathway line are OWNED by site_nav.py, which is the
# contract every other page is checked against. Import and call it rather
# than copying its markup: `data/` sits in site_nav's SKIP_ROOTS (this page
# is generated, so site_nav must not rewrite it), and a hand-copied header
# silently drifts the moment a nav tab is added — which is exactly what
# happened when /data joined the nav.
sys.path.insert(0, str(ROOT))
import site_nav  # noqa: E402
STORE = ROOT / "data"
PAGE = STORE / "index.html"
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


def render_page() -> str:
    series_count, snapshot_count, earliest = counts()
    calendar_count = len(upcoming())
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Data — PolicyEngine Macro</title>
<meta name="description" content="The append-only point-in-time store behind every number on this site: {series_count} UK and US official series, dated snapshots that are never edited, JSON endpoints with open CORS, and an as-of recipe for reconstructing a series as it was published." />
<link rel="canonical" href="{SITE}/data" />
<meta property="og:type" content="website" />
<meta property="og:url" content="{SITE}/data" />
<meta property="og:site_name" content="PolicyEngine Macro" />
<meta property="og:title" content="PolicyEngine Macro — data" />
<meta property="og:description" content="Dated, append-only snapshots of the UK and US official statistics this site depends on, published as JSON anyone can read." />
<meta property="og:image" content="{SITE}/assets/og-image.png" />
<meta property="og:image:alt" content="PolicyEngine Macro — open economic models for the UK and US" />
<meta name="twitter:card" content="summary_large_image" />
<link rel="icon" type="image/svg+xml" href="/assets/policyengine-mark.svg" />
<meta name="theme-color" content="#FFFFFF" />
<link rel="stylesheet" href="/vendor/fonts/fonts.css" />
<link rel="stylesheet" href="/vendor/ui-kit-tokens.css" />
<link rel="stylesheet" href="/style.css?v=3" />
</head>
<body class="doc">
<a class="skip-link" href="#top">Skip to main content</a>
<div class="grain" aria-hidden="true"></div>

{site_nav.header(ROOT / 'data' / 'index.html')}
<main id="top">
  <section class="hero model-hero">
    <div class="hero-inner">
      <p class="eyebrow">open data · point-in-time</p>
      <h1 class="page-title">Every number on this site, as it was published.</h1>
      <p class="lede">
        {series_count} UK and US official series are stored as dated snapshots that are
        never edited and never deleted. {snapshot_count} snapshots have accumulated since
        {earliest}. They are plain JSON on this domain, readable from a browser,
        a notebook, or a shell.
      </p>
    </div>
  </section>

  <section id="why" class="band">
    <div class="band-head">
      <span class="kicker mono">01 — why vintages</span>
      <h2>Reading only the latest data rewrites your own history.</h2>
    </div>
    <div class="prose">
      <p>
        Official statistics get revised, sometimes years later. Reading only
        the current value silently rewrites the past: a forecast that never
        changed can be made to look better or worse by data it could not have
        known. Look-ahead bias becomes undetectable, because only one version
        of the past is ever on disk.
      </p>
      <p>
        Dated snapshots fix both. Nothing here is edited or deleted — a
        revision arrives as a new file beside the old one, as a reviewable
        pull request. The <a href="/forecasts">forecast record</a> stores which
        vintage each score used, so any published number can be reproduced
        from the file it came from. <code>latest/</code> is a flattened copy of
        the newest snapshot for the site to build against, not a second source
        of truth.
      </p>
    </div>
  </section>

  <section id="catalogue" class="band band-alt">
    <div class="band-head">
      <span class="kicker mono">02 — catalogue</span>
      <h2>What is tracked.</h2>
    </div>
    <div class="prose">
      <p>
        Values come from the committed snapshot, not a live call — as current
        as the last fetch and no more. Expand a row for its full snapshot
        history and store path.
      </p>
      <div class="table-scroll">
        <table id="series-table" class="series-table">
          <caption>Every series in the store, stored exactly as published — including sign conventions.</caption>
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
      <p class="chooser-note">
        ONS and Bank of England series are published under the
        <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">Open Government Licence v3.0</a>;
        US series come via FRED with their original BEA, BLS and Federal
        Reserve attribution. Daily series keep observations from 2020 onward.
      </p>
    </div>
  </section>

  <section id="recipe" class="band">
    <div class="band-head">
      <span class="kicker mono">03 — as-of recipe</span>
      <h2>Reconstruct a series exactly as it was published on a date.</h2>
    </div>
    <div class="prose">
      <p>
        <code>MANIFEST.json</code> lists every snapshot date held for every
        series. Take the newest one on or before the date you care about, and
        read that file. Standard library only, no key, no account.
      </p>
      <div class="codeblock"><button class="cb-copy" data-copy>copy</button><pre><code>{recipe_block()}</code></pre></div>
      <p>
        Passing a later date returns a later snapshot, which may carry revised
        values for periods the earlier snapshot already covered. That
        difference is the revision, and it is the entire point of keeping both
        files.
      </p>
      <p class="chooser-note">
        The store only goes back to {earliest}, when the first snapshot was
        taken. It is a forward-looking real-time record from that date on, not
        a reconstruction of historical vintages that predate it.
      </p>
    </div>
  </section>

  <section id="calendar" class="band band-alt">
    <div class="band-head">
      <span class="kicker mono">04 — release calendar</span>
      <h2>Announced next releases.</h2>
    </div>
    <div class="prose">
      <p>
        Each row is the <code>next_release</code> date carried in that series’
        own snapshot, as announced by the publisher. Only the ONS supplies one;
        Bank of England and FRED series are omitted because the field is empty
        for them, not because nothing is scheduled. Dates are the publisher’s
        and can move.
      </p>
      <div class="table-scroll">
        <table>
          <caption>{calendar_count} announced releases, from the committed snapshots.</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Series</th><th scope="col">Name</th><th scope="col">Source</th></tr></thead>
          <tbody>
{calendar_rows()}
          </tbody>
        </table>
      </div>
      <p class="chooser-note">
        Subscribe to the same list as an iCalendar feed:
        <a href="/data/calendar.ics">/data/calendar.ics</a> — one all-day event
        per release, regenerated whenever the store is refetched.
      </p>
    </div>
  </section>

  <section id="access" class="band">
    <div class="band-head">
      <span class="kicker mono">05 — access</span>
      <h2>Endpoints, caching, and CORS.</h2>
    </div>
    <div class="prose">
      <div class="table-scroll">
        <table>
          <caption>Everything is a static file served over HTTPS. GET and HEAD only; there is no API to authenticate against.</caption>
          <thead><tr><th scope="col">Endpoint</th><th scope="col">Contains</th><th scope="col">Stability</th></tr></thead>
          <tbody>
          <tr><th scope="row"><span class="mono">/data/MANIFEST.json</span></th><td>Index of every series: source, CDID, units, frequency, coverage, and the full list of snapshot dates.</td><td>Rewritten on every fetch; short cache with <span class="mono">stale-while-revalidate</span>.</td></tr>
          <tr><th scope="row"><span class="mono">/data/latest/&lt;series&gt;.json</span></th><td>The newest snapshot, flattened. Same schema as a vintage file.</td><td>Moves. Do not cite it as a fixed reference.</td></tr>
          <tr><th scope="row"><span class="mono">/data/vintages/&lt;source&gt;/&lt;series&gt;/&lt;YYYY-MM-DD&gt;.json</span></th><td>One dated snapshot, exactly as fetched.</td><td>Immutable by construction — never edited, never deleted. Served with a one-year <span class="mono">immutable</span> cache.</td></tr>
          <tr><th scope="row"><span class="mono">/data/calendar.ics</span></th><td>The release calendar above, as iCalendar.</td><td>Regenerated with the store; short cache.</td></tr>
          </tbody>
        </table>
      </div>
      <p>
        Every file under <code>/data/</code> is served with
        <code>Access-Control-Allow-Origin: *</code> and
        <code>Access-Control-Allow-Methods: GET, HEAD, OPTIONS</code>, so a
        browser-side notebook or dashboard on any origin can read it directly.
        This is public open data under the licences above; the header grants
        read access to already-public files and nothing else.
      </p>
      <p>
        Each JSON file carries <code>series</code>, <code>source</code>,
        <code>cdid</code>, <code>title</code>, <code>frequency</code>,
        <code>units</code>, <code>url</code>, <code>release_updated</code>,
        <code>first_period</code>, <code>last_period</code>,
        <code>observations</code> as a list of
        <code>{{"period", "value"}}</code> objects, <code>vintage</code>, and
        <code>fetched_utc</code>. <code>latest/</code> files additionally carry
        <code>next_release</code> where the publisher supplies one.
      </p>
      <p class="chooser-note">
        Snapshot dates are the dates a change was recorded, not a daily
        calendar: a fetch that found no upstream change wrote no file, so gaps
        between dates mean “nothing moved”. The whole store is in the
        <a href="https://github.com/PolicyEngine/macro/tree/main/data">repository</a>
        if you would rather clone it than fetch it.
      </p>
    </div>
  </section>
</main>

<footer class="foot foot-bar">
  <p class="footer-legal">© 2026 PolicyEngine. All rights reserved.</p>
  <nav class="footer-links" aria-label="PolicyEngine links">
    <a class="footer-text footer-policyengine" href="https://policyengine.org"><img src="/assets/policyengine-mark.svg" alt="" width="17" height="17" />PolicyEngine</a>
    <a class="footer-text" href="https://github.com/PolicyEngine/macro">GitHub</a>
    <a class="footer-text" href="/contact">Contact</a>
  </nav>
</footer>

<script src="/reveal.js?v=2" defer></script>
<script>
document.addEventListener("click", function (e) {{
  var btn = e.target.closest("[data-copy]"); if (!btn) return;
  var code = btn.parentElement.querySelector("code");
  navigator.clipboard.writeText(code.textContent).then(function () {{
    btn.textContent = "copied";
    setTimeout(function () {{ btn.textContent = "copy"; }}, 1400);
  }});
}});

// Catalogue. Two independent collapses, both progressive enhancements:
// the table ships whole with every detail row OPEN, and script does the
// hiding. Without JavaScript the page is long but complete — never a table
// with rows that cannot be reached.
(function () {{
  var table = document.getElementById("series-table");
  if (!table) return;
  var groups = table.querySelectorAll(".series-group");
  var toggles = table.querySelectorAll(".series-toggle");
  var preview = {PREVIEW_ROWS};

  // 1. Per-row detail.
  function setOpen(btn, open) {{
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    var row = document.getElementById(btn.getAttribute("aria-controls"));
    if (row) row.hidden = !open;
  }}
  toggles.forEach(function (btn) {{ setOpen(btn, false); }});
  document.addEventListener("click", function (e) {{
    var btn = e.target.closest(".series-toggle");
    if (!btn) return;
    setOpen(btn, btn.getAttribute("aria-expanded") !== "true");
  }});

  // 2. Row count. Nothing to collapse if the store is small enough to show.
  var showAll = document.getElementById("show-all");
  if (!showAll || groups.length <= preview) return;
  var hiddenCount = groups.length - preview;

  function setListOpen(open) {{
    groups.forEach(function (group) {{
      if (+group.getAttribute("data-index") >= preview) group.hidden = !open;
    }});
    showAll.setAttribute("aria-expanded", open ? "true" : "false");
    showAll.textContent = open
      ? "Show fewer"
      : "Show all " + groups.length + " series (" + hiddenCount + " more)";
  }}

  showAll.hidden = false;
  setListOpen(false);
  showAll.addEventListener("click", function () {{
    var open = showAll.getAttribute("aria-expanded") !== "true";
    setListOpen(open);
    // Collapsing can leave the reader below the table; put them back on it.
    if (!open) table.scrollIntoView({{ block: "start", behavior: "smooth" }});
  }});
}})();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    # Compared and written as bytes: the calendar uses the CRLF line endings
    # RFC 5545 requires, and text mode would silently translate them.
    rendered = (
        (PAGE, render_page().encode("utf-8")),
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
        print("Data page and release calendar match committed data")
        return 0
    for path, content in rendered:
        path.write_bytes(content)
    print("updated Data page and release calendar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
