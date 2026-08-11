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
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
    index = manifest()["series"]
    dirs = source_dirs()
    rows = []
    for name in sorted(index):
        entry = index[name]
        series = load(name)
        now = series["observations"][-1]
        first, last = entry["coverage"]
        rows.append(
            "          <tr>"
            f'<th scope="row">{esc(public_label(series))}'
            f'<br /><span class="mono">{esc(name)}</span></th>'
            f'<td><a href="{esc(display_url(series["url"]))}">'
            f'{esc(series["source"])} · {esc(series["cdid"])}</a></td>'
            f"<td>{esc(series['frequency'])}</td>"
            f"<td>{esc(series['units'])}</td>"
            f"<td>{esc(first)} – {esc(last)}</td>"
            f"<td>{fmt_value(now['value'])} <span class=\"mono\">{esc(now['period'])}</span></td>"
            # The vintage links straight at the immutable file it names.
            # The path cell is plain text: there is no directory listing to
            # link to, and the two tokens are what the as-of recipe takes.
            f'<td><a href="/data/vintages/{esc(dirs[name])}/{esc(name)}/'
            f'{esc(entry["latest_vintage"])}.json">'
            f"{esc(entry['latest_vintage'])}.json</a></td>"
            f"<td>{len(entry['vintages'])}</td>"
            f'<td><span class="mono">{esc(dirs[name])}/{esc(name)}</span></td>'
            "</tr>"
        )
    return "\n".join(rows)


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

<header class="nav">
  <a class="brand" href="/">
    <img class="brand-logo" src="/assets/policyengine-mark.svg" alt="" width="20" height="20" />PolicyEngine Macro
  </a>
  <nav class="nav-links" aria-label="Primary">
    <a class="nav-mobile" href="/">Home</a>
    <a class="nav-mobile" href="/models">Models</a>
    <a class="nav-mobile" href="/economy">Economy</a>
    <a class="nav-mobile" href="/forecasts">Forecasts</a>
    <a class="nav-mobile nav-start" href="/connect">Use</a>
    <a class="nav-gh" href="https://github.com/PolicyEngine/macro" aria-label="GitHub"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 19c-4.3 1.4 -4.3 -2.5 -6 -3m12 5v-3.5c0 -1 .1 -1.4 -.5 -2c2.8 -.3 5.5 -1.4 5.5 -6a4.6 4.6 0 0 0 -1.3 -3.2a4.2 4.2 0 0 0 -.1 -3.2s-1.1 -.3 -3.5 1.3a12.3 12.3 0 0 0 -6.2 0c-2.4 -1.6 -3.5 -1.3 -3.5 -1.3a4.2 4.2 0 0 0 -.1 3.2c-.9 .9 -1.3 2 -1.3 3.2c0 4.6 2.7 5.7 5.5 6c-.6 .6 -.6 1.2 -.5 2v3.5"/></svg></a>
  </nav>
</header>

<nav class="crumbs mono" aria-label="You are here">
    <a href="/">Home</a>
    <span aria-current="page">Data</span>
</nav>

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
        Official statistics get revised, sometimes years later. A site that
        reads only the current value silently rewrites its own past on every
        revision: a forecast that never changed can be made to look better or
        worse by data it could not have known about. It also makes look-ahead
        bias undetectable, because only one version of the past is ever on
        disk.
      </p>
      <p>
        Storing dated snapshots makes both problems visible. The
        <a href="/forecasts">forecast track record</a> records which vintage
        each score was computed against, so any published number can be
        reproduced from the file it was computed from.
      </p>
      <p>
        The store is JSON rather than Parquet because these series are small
        and a git-diffable format means an upstream revision arrives as a
        reviewable diff rather than an opaque binary blob. The scheduled fetch
        opens a pull request instead of pushing, so a revision is something a
        human sees. A fetch that finds no upstream change writes nothing —
        otherwise real revisions would be buried in a stream of identical
        files — and a transient network failure is reported as a failure,
        never as “no revision”.
      </p>
      <p>
        <code>latest/</code> exists because the published site is static under
        a content-security policy with <code>connect-src 'self'</code>: the
        browser cannot call the ONS, so anything shown on a page has to be
        baked in at build time. It is a flattened copy of the newest snapshot,
        not a separate source of truth.
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
        Latest values below are read from the committed snapshot named in the
        vintage column — not from a live call — so they are as current as the
        last fetch and no more.
      </p>
      <div class="table-scroll">
        <table>
          <caption>Every series in the store. “Snapshots” counts the dated files kept for that series; “vintage” links the newest one. Values are reproduced exactly as stored, including the publisher’s sign convention — J5II, for example, records net borrowing as a negative financial balance.</caption>
          <thead><tr><th scope="col">Series</th><th scope="col">Source</th><th scope="col">Frequency</th><th scope="col">Units</th><th scope="col">Coverage</th><th scope="col">Latest</th><th scope="col">Vintage</th><th scope="col">Snapshots</th><th scope="col">Store path</th></tr></thead>
          <tbody>
{catalogue_rows()}
          </tbody>
        </table>
      </div>
      <p class="chooser-note">
        ONS and Bank of England data are published under the
        <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">Open Government Licence v3.0</a>.
        US series are distributed by the Federal Reserve Bank of St. Louis with
        their original BEA, BLS, and Federal Reserve attribution. Daily Bank of
        England and FRED series retain observations from 2020 onward only.
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
