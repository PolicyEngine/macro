#!/usr/bin/env python3
"""Regenerate the Forecasts section: fifteen pages, one shared bar.

Economy and Forecasts used to be two tabs over one body of work. They are one
section now, and this module renders the parts of it that are derived rather
than written:

    /forecasts, /forecasts/us      the platform band — what a reader can
                                   produce here, pe-microsim first — and the
                                   section bar
    /economy, /economy/us          the topic directory and the section bar
    eleven topic pages             whole, under /economy/topics and
                                   /economy/us/topics

No URL moved in the merge. The eleven topic pages and the two data hubs keep
their /economy prefix because roughly two hundred generated release notes, the
homepage and the models hub link into it in prose; what changed is which tab
they belong to, which ``site_nav.section`` decides, not the URL.

The rest of this site is organised by model — a reader has to know what a
structural VAR is before they can find the inflation forecast. These pages are
the other axis: one page per question, each carrying the same four layers.

    1. Where it stands       values exactly as the committed vintage stores them
    2. What the models see   the model, named and linked, with its stated limits
    3. Run it yourself       a verified pe-macro command and MCP tool name
    4. The data behind it    source, CDID, coverage, snapshots, vintage file

Nothing here is hand-typed. Every number comes from ``data/latest`` or an
archived forecast round, every limitation is quoted out of the capability
registry, every CLI invocation is checked against ``cli.py`` and every MCP tool
name against the golden tool surface. ``--check`` re-renders and compares, so a
refreshed vintage or a renamed tool fails CI instead of quietly rotting on a
public page.

The two countries fill those layers to different depths, and the generator is
built so the difference cannot be papered over. boe-svar is the only member
whose ``question_types`` include "forecast" and it is UK-only, so no US page
may show a forecast with a range; ``no_us_forecaster`` re-derives that from the
registry on every render and raises if it stops being true. The same applies to
the topics that do not exist: ``us_public_finance_gap`` raises if a US fiscal
series ever appears in the store while /economy/us still tells readers there is
none.

Stdlib only, and nothing reads the clock or the network: the same inputs always
produce the same bytes.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOPICS_DIR = ROOT / "economy" / "topics"
ECONOMY_PAGE = ROOT / "economy" / "index.html"
US_TOPICS_DIR = ROOT / "economy" / "us" / "topics"
US_PAGE = ROOT / "economy" / "us" / "index.html"
FORECASTS_PAGE = ROOT / "forecasts" / "index.html"
US_FORECASTS_PAGE = ROOT / "forecasts" / "us" / "index.html"
SITEMAP = ROOT / "sitemap.xml"
SITE = "https://policyengine-macro.vercel.app"

# The two country scopes this generator renders. Everything below is written
# once and parameterised by this table rather than forked per country: a
# second copy of the renderer is how /economy and /economy/us drifted into two
# different shapes in the first place — one with six topic pages and a topic
# strip, the other with four in-page anchors that looked like tabs.
#
# Economy and Forecasts are one section now, so each country has two hub pages
# with different jobs and one bar across both:
#
#   ``hub``   /forecasts     what the platform produces, and the scored record
#   ``data``  /economy       the series, the long view, and the provenance
#
# ``topics_base`` is deliberately separate from ``hub``: the eleven topic pages
# keep their /economy/topics/... URLs because ~200 generated release notes, the
# homepage and the models hub link into that prefix in prose. The section a
# page belongs to is decided by site_nav.section(), not by its URL.
COUNTRIES = {
    "uk": {
        "label": "UK",
        "hub": "/forecasts",
        "hub_page": FORECASTS_PAGE,
        "hub_nav_marker": "forecasts-section-nav",
        "platform_marker": "forecasts-platform",
        "data": "/economy",
        "data_page": ECONOMY_PAGE,
        "topics_base": "/economy",
        "dir": TOPICS_DIR,
        "nav_marker": "economy-topic-nav",
        "directory_marker": "economy-topics",
    },
    "us": {
        "label": "US",
        "hub": "/forecasts/us",
        "hub_page": US_FORECASTS_PAGE,
        "hub_nav_marker": "us-forecasts-section-nav",
        "platform_marker": "us-forecasts-platform",
        "data": "/economy/us",
        "data_page": US_PAGE,
        "topics_base": "/economy/us",
        "dir": US_TOPICS_DIR,
        "nav_marker": "us-economy-topic-nav",
        "directory_marker": "us-economy-topics",
    },
}


def topic_url(topic: dict) -> str:
    """Site path for one topic page, derived from its country."""
    return f"{COUNTRIES[topic['country']]['topics_base']}/topics/{topic['slug']}"

sys.path.insert(0, str(ROOT))
import site_nav  # noqa: E402  (canonical header/crumbs/footer renderer)


def _module(name: str, path: Path):
    """Import a stdlib-only source file without importing its package.

    ``policyengine_macro/__init__`` pulls in the whole integration layer (and
    click, pandas, the model packages); ``capabilities.py`` and the golden tool
    surface are plain data modules that import nothing but the stdlib, so they
    can be read directly and this generator stays runnable with a bare
    interpreter.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAPABILITIES = _module(
    "topics_capabilities",
    ROOT / "integration" / "src" / "policyengine_macro" / "capabilities.py",
)
TOOL_SURFACE = _module(
    "topics_tool_surface", ROOT / "integration" / "tests" / "tool_surface.py"
)
MODELS = CAPABILITIES.MODELS
GOLDEN_TOOLS = TOOL_SURFACE.GOLDEN_TOOLS
CLI_SOURCE = (
    ROOT / "integration" / "src" / "policyengine_macro" / "cli.py"
).read_text()

# Shared with economy/build.py and data/build_page.py: ONS catalogue titles are
# not reader-facing labels.
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
    # FRED titles all begin "US ..." because they are read on a site covering
    # two countries; on a page whose scope is already the US that prefix is
    # noise, and "10-year US Treasury constant maturity rate" is the
    # publisher's catalogue name rather than the one a reader would say.
    "GDPC1": "Real gross domestic product",
    "CPIAUCSL": "Consumer price index, all urban consumers",
    "UNRATE": "Unemployment rate",
    "PAYEMS": "Nonfarm payroll employment",
    "FEDFUNDS": "Effective federal funds rate",
    "DGS10": "10-year Treasury yield",
}

FORECAST_FILE = ROOT / "papers" / "boe-svar" / "figures" / "current_forecast.json"
# The archived round keeps the filename it was generated under; the satellite's
# display name is "svar-unemployment satellite".
UNEMPLOYMENT_ROUND = (
    ROOT / "forecasts" / "rounds" / "2026-07-28" / "okun-unemployment.json"
)


# --------------------------------------------------------------- data access

def esc(value) -> str:
    return html.escape(str(value), quote=True)


def load(name: str) -> dict:
    series = json.loads((ROOT / "data" / "latest" / f"{name}.json").read_text())
    # ONS observations live behind a JSON `/data` endpoint, which is a poor
    # destination for a reader clicking through to the official series.
    if "ons.gov.uk/" in series["url"] and series["url"].endswith("/data"):
        series["url"] = series["url"][: -len("/data")]
    return series


def manifest() -> dict:
    return json.loads((ROOT / "data" / "MANIFEST.json").read_text())["series"]


def source_dirs() -> dict[str, str]:
    """Map each series to the ``vintages/<source>/`` directory holding it."""
    found: dict[str, str] = {}
    for directory in sorted((ROOT / "data" / "vintages").iterdir()):
        if not directory.is_dir():
            continue
        for series in sorted(directory.iterdir()):
            if series.is_dir():
                found[series.name] = directory.name
    return found


def label(series: dict) -> str:
    return PUBLIC_LABELS.get(series["cdid"], series["title"])


def latest(series: dict) -> dict:
    return series["observations"][-1]


def stored(value: float) -> str:
    """The number as the snapshot holds it: grouped, never rounded.

    Same convention as the store catalogue on /forecasts#data — a stored 5.0 is
    printed 5.0, not 5, because the trailing zero is the publisher's precision.
    """
    return f"{value:,}"


def display(series: dict, value: float) -> str:
    """The reading a person would say out loud.

    stored() is right for the method note and for anything asserting fidelity
    to the snapshot, but it is wrong for the number a reader meets first: the
    restructure made the public-finances headline read "-15,989.0" where the
    page it replaced said "£16.0bn borrowed", and dropped "£77.1bn" and
    "£749/week" from the site entirely. Scale and unit here; exact stored
    value stays one line below and in the method note.
    """
    units = series["units"].lower()
    if "£m" in units or "\u00a3m" in units:
        billions = abs(value) / 1000
        borrowed = " borrowed" if value < 0 and "borrowing" in series["title"].lower() else ""
        return f"\u00a3{billions:,.1f}bn{borrowed}"
    if "per week" in units:
        return f"\u00a3{value:,.0f}/week"
    # FRED levels. GDPC1 is billions of chained dollars at an annual rate and
    # PAYEMS is thousands of persons; printed raw they read as "24,270.599"
    # and "158,858k", which is the stored number rather than the reading.
    if "billions of chained" in units:
        return f"${value / 1000:,.1f}tn"
    if "thousands of persons" in units:
        return f"{value / 1000:,.1f}m"
    if "thousand" in units:
        return f"{value:,.0f}k"
    if "percent" in units or units.startswith("%"):
        # Keep the publisher's precision: a stored 5.0 is 5.0%, not 5%. The
        # trailing zero is information about how the figure was published.
        return f"{stored(value)}%"
    return stored(value)


def listed(items: list[str]) -> str:
    """Join a registry list the way a sentence needs it."""
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def suffix(series: dict) -> str:
    return "%" if series["units"].lower().startswith("percent") else ""


def year_earlier(series: dict, period: str) -> dict | None:
    """The observation one calendar year before ``period``, or None.

    By period, never by position. The two are not the same thing: us_cpi and
    us_unemployment_rate are both missing 2025-10, so ``observations[-13]``
    on the CPI index is 2025-05 and a "year-on-year" rate taken from it reads
    3.7% where the true 2026-06 figure is 3.5%. The economy hub already
    matches on period; a topic page that did not would publish a different
    number for the same series on the same site.
    """
    if not re.fullmatch(r"\d{4}Q[1-4]|\d{4}-\d{2}", period):
        return None
    wanted = f"{int(period[:4]) - 1}{period[4:]}"
    return next(
        (row for row in series["observations"] if row["period"] == wanted), None
    )


def yoy(series: dict, periods: int) -> list[dict]:
    """Year-on-year percent change computed from the stored levels.

    ``periods`` is 4 for a quarterly series and 12 for a monthly one — it
    names the frequency, not an offset to index by. A period whose counterpart
    a year earlier is absent from the store is skipped rather than silently
    compared against whatever observation happens to sit that many rows back.
    """
    assert periods in (4, 12), "yoy() compares a period with the same period a year earlier"
    out = []
    for row in series["observations"]:
        before = year_earlier(series, row["period"])
        if before is None:
            continue
        out.append(
            {
                "period": row["period"],
                "value": 100 * (row["value"] / before["value"] - 1),
            }
        )
    return out


def quarter_of(period: str) -> str:
    """Map a monthly or daily period onto the quarter that contains it."""
    if "Q" in period:
        return period
    year, month = period.split("-")[:2]
    return f"{year}Q{(int(month) + 2) // 3}"


def next_open(forecast: dict, variable: str, last_observed: str) -> tuple[str, dict]:
    """First forecast period the official data has not yet printed.

    Showing a "forecast" for a quarter the ONS has already published would be
    stale the moment the release lands.
    """
    for period, values in forecast.items():
        if period > last_observed and variable in values:
            return period, values[variable]
    period = list(forecast)[-1]
    return period, forecast[period][variable]


def band_text(values: dict) -> str:
    return f"{values['lo68']:.1f}%–{values['hi68']:.1f}%"


# --------------------------------------------------- verified run-it-yourself

def shared_option_blocks() -> dict[str, set[str]]:
    """Long options contributed by a shared decorator such as
    ``@_pe_common_options``.

    Without this the parser sees only the options written inline under
    ``@main.command``, so ``pe-macro household-impact`` looks as though it
    declares nothing but ``--reform`` — and ``command()`` would reject the
    ``--country`` and ``--people`` the command in fact requires. Every
    household example on this site went unverified for exactly that reason.
    """
    blocks: dict[str, set[str]] = {}
    for name, body in re.findall(
        r"^def (_[a-z0-9_]*options)\(fn\):\n(.*?)(?=\n@|\ndef |\Z)",
        CLI_SOURCE,
        flags=re.M | re.S,
    ):
        options: set[str] = set()
        for declared in re.findall(r'click\.option\(\s*"(--[^"]+)"', body):
            options.update(declared.split("/"))
        blocks[name] = options
    return blocks


def cli_commands() -> dict[str, set[str]]:
    """``pe-macro`` command names mapped to their declared long options.

    Parsed out of ``cli.py`` rather than imported, because importing the CLI
    would drag in click and the model packages. A command or flag this
    generator prints but the CLI does not declare is a hard failure.
    """
    shared = shared_option_blocks()
    commands: dict[str, set[str]] = {}
    blocks = re.split(r"^@main\.command", CLI_SOURCE, flags=re.M)[1:]
    for block in blocks:
        explicit = re.match(r'\("([a-z0-9-]+)"\)', block)
        if explicit:
            name = explicit.group(1)
        else:
            function = re.search(r"^def ([a-z0-9_]+)\(", block, flags=re.M)
            if function is None:
                continue
            name = function.group(1).replace("_", "-")
        options: set[str] = set()
        head = block.split("\ndef ", 1)[0]
        for declared in re.findall(r'click\.option\(\s*"(--[^"]+)"', head):
            options.update(declared.split("/"))
        for decorator, declared in shared.items():
            if f"@{decorator}" in head:
                options.update(declared)
        commands[name] = options
    return commands


CLI_COMMANDS = cli_commands()


def command(line: str, comment: str = "") -> str:
    """Render one verified ``pe-macro`` invocation as a code line."""
    tokens = shlex.split(line)
    if tokens[0] != "pe-macro":
        raise RuntimeError(f"not a pe-macro invocation: {line}")
    name = tokens[1]
    if name not in CLI_COMMANDS:
        raise RuntimeError(
            f"{line!r}: cli.py declares no `pe-macro {name}` command "
            f"(have: {', '.join(sorted(CLI_COMMANDS))})"
        )
    for token in tokens[2:]:
        if token.startswith("--") and token not in CLI_COMMANDS[name]:
            raise RuntimeError(
                f"{line!r}: `pe-macro {name}` declares no {token} option "
                f"(have: {', '.join(sorted(CLI_COMMANDS[name])) or 'none'})"
            )
    rendered = esc(line)
    if comment:
        rendered += f'   <span class="cm"># {esc(comment)}</span>'
    return rendered


def tool(name: str) -> str:
    """A hosted MCP tool name, checked against the published tool surface."""
    if name not in GOLDEN_TOOLS:
        raise RuntimeError(
            f"{name!r} is not in the golden MCP tool surface "
            f"(integration/tests/tool_surface.py)"
        )
    return f'<span class="mono">{esc(name)}</span>'


def codeblock(*lines: str) -> str:
    body = "\n".join(lines)
    return f'      <div class="codeblock"><pre><code>{body}</code></pre></div>'


def satellite_has_no_surface() -> bool:
    """True when no CLI command or MCP tool exposes the Okun satellite."""
    pattern = re.compile(r"okun|unemploy", re.I)
    return not any(pattern.search(name) for name in CLI_COMMANDS) and not any(
        pattern.search(name) for name in GOLDEN_TOOLS
    )


# --------------------------------------------------------------- page pieces

def _card(heading: str, value: str, note: str, series: dict, period: str) -> str:
    return f"""        <article class="economy-stat">
          <p class="economy-stat-label mono">{heading}</p>
          <p class="economy-stat-value">{value}</p>
          <p class="economy-stat-change">{note}</p>
          <dl>
            <div><dt>Observation</dt><dd>{esc(period)}</dd></div>
            <div><dt>Vintage</dt><dd>{esc(series["vintage"])}</dd></div>
            <div><dt>Source</dt><dd><a href="{esc(series["url"])}">{esc(series["source"])} · {esc(series["cdid"])}</a></dd></div>
          </dl>
        </article>"""


def stat_card(series: dict, kind: str | None = None) -> str:
    """One reading, as the snapshot stores it — or explicitly derived from it.

    The ONS publishes CPI and the unemployment rate as rates, so a UK card can
    print the stored value and be done. FRED stores GDPC1 as a level in
    billions of chained dollars and CPIAUCSL as an index, so the reading a US
    page needs is not in the file at all: it is computed here, the card says
    it was, and both endpoints it was computed from are printed beside it.
    """
    now = latest(series)
    if kind is None:
        return _card(
            esc(label(series).upper()),
            esc(display(series, now["value"])),
            f'stored as {esc(stored(now["value"]))} &middot; {esc(series["units"])}',
            series,
            now["period"],
        )
    before = year_earlier(series, now["period"])
    if before is None:
        raise RuntimeError(
            f"{series['series']}: no {now['period']} counterpart a year "
            "earlier in the store, so a year-on-year card cannot be derived"
        )
    change = 100 * (now["value"] / before["value"] - 1)
    return _card(
        esc(f"{label(series).upper()} · YEAR ON YEAR"),
        f"{change:+.1f}%",
        f'derived here, not stored: {esc(stored(now["value"]))} in '
        f'{esc(now["period"])} against {esc(stored(before["value"]))} in '
        f'{esc(before["period"])} &middot; {esc(series["units"])}',
        series,
        now["period"],
    )


# How each series' movement is read. /economy used to carry these period
# comparisons in an indicator table beside the same values the topic pages
# show; the comparison belongs with the series, on the page that reads it.
# (kind, periods back, decimals, how to name the comparison window)
MOVEMENT: dict[str, tuple[str, int, int, str]] = {
    "uk_gdp_cvm": ("yoy_pp", 1, 1, "the prior quarter"),
    "uk_monthly_gva": ("pct", 1, 1, "the prior month"),
    "uk_business_investment": ("pct", 1, 1, "the prior quarter"),
    "uk_cpi_yoy": ("pp", 1, 1, "the prior quarter"),
    "uk_core_cpi_yoy": ("pp", 1, 1, "the prior month"),
    "uk_unemployment_rate": ("pp", 1, 1, "the prior quarter"),
    "uk_average_weekly_earnings": ("pct", 12, 1, "a year earlier"),
    "uk_vacancies": ("thousands", 12, 1, "a year earlier"),
    "uk_public_sector_net_borrowing": ("borrowed", 12, 1, "a year earlier"),
    "uk_public_sector_net_debt_gdp": ("pp", 1, 1, "the prior month"),
    "uk_bank_rate": ("pp", 5, 3, "five observations earlier"),
    "uk_gilt_5y": ("pp", 5, 3, "five observations earlier"),
    "uk_gilt_10y": ("pp", 5, 3, "five observations earlier"),
    "uk_gilt_20y": ("pp", 5, 3, "five observations earlier"),
    # FRED. GDPC1 and CPIAUCSL are levels, so the comparison that means
    # anything is a move in the derived year-on-year rate, not in the level.
    "us_real_gdp": ("yoy_pp", 1, 1, "the prior quarter"),
    "us_cpi": ("yoy12_pp", 1, 1, "the prior month"),
    "us_unemployment_rate": ("pp", 1, 1, "the prior month"),
    "us_payroll_employment": ("pct", 12, 1, "a year earlier"),
    "us_federal_funds_rate": ("pp", 5, 3, "five months earlier"),
    "us_treasury_10y": ("pp", 5, 3, "five observations earlier"),
}


def movement(name: str) -> str:
    """One period comparison, computed from the stored observations.

    The comparison each series supports is not the same: a published rate moves
    in percentage points, a level in percent, and J5II is a negative balance so
    the honest comparison is between amounts borrowed, not between balances.

    A window of "a year earlier" is resolved by period, not by counting rows
    back, so a series with a hole in it — us_cpi is missing 2025-10 — compares
    against the month it names rather than the month that happens to sit there.
    """
    kind, periods, digits, window = MOVEMENT[name]
    series = load(name)
    observations = series["observations"]
    now = observations[-1]
    if window == "a year earlier":
        before = year_earlier(series, now["period"])
        if before is None:
            raise RuntimeError(
                f"{name}: MOVEMENT compares against a year earlier, but the "
                f"store has no counterpart for {now['period']}"
            )
    else:
        before = observations[-1 - periods]
    if kind in ("yoy_pp", "yoy12_pp"):
        rates = yoy(series, 4 if kind == "yoy_pp" else 12)
        gap = rates[-1]["value"] - rates[-1 - periods]["value"]
        change = f"{gap:+.{digits}f}pp on the year-on-year rate"
        before = rates[-1 - periods]
    elif kind == "pp":
        change = f"{now['value'] - before['value']:+.{digits}f}pp"
    elif kind == "pct":
        change = f"{100 * (now['value'] / before['value'] - 1):+.{digits}f}%"
    elif kind == "thousands":
        change = f"{now['value'] - before['value']:+,.{digits}f} thousand"
    else:  # "borrowed"
        gap = (-now["value"] + before["value"]) / 1000
        sign = "+" if gap >= 0 else "-"
        change = f"{sign}£{abs(gap):,.{digits}f}bn on the amount borrowed"
    return (
        f"{esc(label(series))} {change} against {window} "
        f"({esc(before['period'])})"
    )


def movement_note(names: tuple[str, ...]) -> str:
    joined = "; ".join(movement(name) for name in names)
    return (
        '    <p class="economy-method">How those readings have moved, derived '
        f"from the same stored observations rather than typed in: {joined}.</p>"
    )


def stands(cards: tuple[tuple[str, str | None], ...], note: str,
           names: tuple[str, ...]) -> str:
    """The card grid, the method note, and the period comparisons.

    ``cards`` is (series, derivation) pairs — a series can appear twice, as a
    derived rate and as the level it was derived from. ``names`` is the
    distinct series the topic reads, which is what the movement note and the
    provenance table are keyed on.
    """
    rendered = "\n".join(stat_card(load(name), kind) for name, kind in cards)
    return f"""    <div class="economy-grid">
{rendered}
    </div>
    <p class="economy-method">{note}</p>
{movement_note(names)}"""


def data_rows(names: tuple[str, ...]) -> str:
    index = manifest()
    dirs = source_dirs()
    rows = []
    for name in names:
        series = load(name)
        entry = index[name]
        first, last = entry["coverage"]
        vintage = series["vintage"]
        file_url = f"/data/vintages/{dirs[name]}/{name}/{vintage}.json"
        announced = " ".join((series.get("next_release") or "").split())
        rows.append(
            "          <tr>"
            f'<th scope="row">{esc(label(series))}</th>'
            f'<td><a href="{esc(series["url"])}">{esc(series["source"])} · {esc(series["cdid"])}</a></td>'
            f"<td>{esc(first)} – {esc(last)}</td>"
            f"<td>{len(entry['vintages'])}</td>"
            f'<td><a class="mono" href="{esc(file_url)}">{esc(vintage)}.json</a></td>'
            f"<td>{esc(announced) if announced else 'not announced'}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def data_layer(names: tuple[str, ...], closing: str) -> str:
    return f"""    <div class="prose">
      <div class="table-scroll">
        <table>
          <caption>Every value on this page is read from the vintage file linked here, not from a live call.</caption>
          <thead><tr><th scope="col">Series</th><th scope="col">Publisher</th><th scope="col">Coverage</th><th scope="col">Snapshots</th><th scope="col">This vintage</th><th scope="col">Next release</th></tr></thead>
          <tbody>
{data_rows(names)}
          </tbody>
        </table>
      </div>
      <p class="chooser-note">{closing}</p>
      <p class="chooser-note">The snapshot files are append-only and never edited, so a number published here can be reproduced against the data as it stood — <a href="/forecasts#data">browse the store, its release calendar, and the as-of recipe →</a></p>
    </div>"""


def limits_list(items: list[str]) -> str:
    entries = "\n".join(f"        <li>{item}</li>" for item in items)
    return f"      <ul>\n{entries}\n      </ul>"


def site_name(model_id: str) -> str:
    """The name the website uses for a model.

    The registry keys models by their MCP/CLI contract id (og-uk), which is
    not always what the site calls them (psl-og). Rendering the key leaked
    two names onto public pages that appear nowhere else on the site.
    """
    return MODELS[model_id].get("site_id", model_id)


def cannot(model_id: str) -> str:
    return listed([esc(item) for item in MODELS[model_id]["cannot_answer"]])


def registry_terms(items: list[str]) -> str:
    """Registry field values are machine identifiers; show them as such."""
    return ", ".join(f'<span class="mono">{esc(item)}</span>' for item in items)


def band(ident: str, number: str, kicker: str, heading: str, body: str,
         alt: bool = False) -> str:
    classes = "band band-alt" if alt else "band"
    return f"""  <section id="{ident}" class="{classes}">
    <div class="band-head">
      <span class="kicker mono">{number} — {kicker}</span>
      <h2>{heading}</h2>
    </div>
{body}
  </section>"""


# --------------------------------------------------------------- 01 growth

def growth_facts() -> dict:
    gdp = load("uk_gdp_cvm")
    growth = yoy(gdp, 4)
    now = growth[-1]
    forecast = json.loads(FORECAST_FILE.read_text())
    period, values = next_open(forecast["forecast"], "gdp", now["period"])
    return {
        "gdp": gdp, "now": now, "forecast": forecast,
        "period": period, "values": values,
    }


def growth_hook() -> str:
    facts = growth_facts()
    return (
        f"Real GDP is {facts['now']['value']:.1f}% up on the year in "
        f"{facts['now']['period']}; boe-svar's first open quarter, "
        f"{facts['period']}, is {facts['values']['median']:.1f}%."
    )


def growth_note() -> str:
    gdp = load("uk_gdp_cvm")
    now = gdp["observations"][-1]
    year_ago = gdp["observations"][-5]
    change = 100 * (now["value"] / year_ago["value"] - 1)
    return (
        "Levels exactly as the snapshot stores them — chained volume measures "
        "in £m and an index, not growth rates. The year-on-year figure quoted "
        "on this page is derived from these same stored levels rather than "
        f"typed in: {stored(now['value'])} in {esc(now['period'])} against "
        f"{stored(year_ago['value'])} in {esc(year_ago['period'])} is "
        f"{change:.1f}%."
    )


def growth_model() -> str:
    facts = growth_facts()
    model = MODELS["boe-svar"]
    quality = model["quality"]["predictive_validation"]
    forecast = facts["forecast"]
    rows = []
    for period, values in list(forecast["forecast"].items())[:5]:
        rows.append(
            "          <tr>"
            f'<th scope="row">{esc(period)}</th>'
            f"<td>{values['gdp']['median']:.2f}%</td>"
            f"<td>{values['gdp']['lo68']:.2f}%–{values['gdp']['hi68']:.2f}%</td>"
            f"<td>{values['gdp']['lo90']:.2f}%–{values['gdp']['hi90']:.2f}%</td>"
            "</tr>"
        )
    return f"""    <div class="prose">
      <p>
        One model in the suite forecasts UK output: <a href="/svar">boe-svar</a>,
        the {esc(model["display_name"])}. The round generated
        {esc(forecast["generated"])} conditions on data through
        {esc(forecast["data_edge"])} and puts year-on-year growth at
        {facts["values"]["median"]:.1f}% in {esc(facts["period"])},
        68% {band_text(facts["values"])} — and in the same breath:
      </p>
{limits_list([
        f"Status: {esc(model['status'])}.",
        f"It cannot answer {(cannot('boe-svar'))}.",
        f"Uncertainty is {esc(model['uncertainty'])} — the bands are the forecast, not decoration.",
        f"Estimated on {esc(model['estimation_sample'])} but conditioned on {esc(model['data_edge'])} data, so the estimation sample stops well short of the quarters being forecast.",
    ])}
      <div class="table-scroll">
        <table>
          <caption>boe-svar year-on-year real GDP growth: median and predictive ranges, from the archived round.</caption>
          <thead><tr><th scope="col">Quarter</th><th scope="col">Median</th><th scope="col">68%</th><th scope="col">90%</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
      </div>
      <p class="callout">
        <strong>Predictive validation: {esc(quality["level"])}.</strong>
        {esc(quality["evidence"])}
        <a href="/svar/validation">Read the validation page →</a>
      </p>
      <p class="chooser-note">
        Every round is archived before the outturn exists, and scored against
        the vintage it was made on — <a href="/forecasts">see the record →</a>
      </p>
    </div>"""


def growth_run() -> str:
    return f"""    <div class="prose">
      <p>
        The forecast above is one command. It re-estimates and re-identifies the
        model, so it takes minutes rather than seconds ({esc(MODELS["boe-svar"]["runtime"])}).
      </p>
{codeblock(
        command("pe-macro forecast --horizons 8", "GDP and CPI, medians with 68% and 90% bands"),
        command("pe-macro summary", "headline replication results, instant, from committed files"),
    )}
      <p>
        Over MCP the same forecast is the {tool("forecast_uk")} tool, the
        identified shocks behind it are {tool("latest_shocks")}, and
        {tool("get_model_status")} returns the limitations quoted above as
        structured data rather than prose. <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


# --------------------------------------------------------------- 02 inflation

def inflation_facts() -> dict:
    cpi = load("uk_cpi_yoy")
    core = load("uk_core_cpi_yoy")
    forecast = json.loads(FORECAST_FILE.read_text())
    now = latest(cpi)
    period, values = next_open(forecast["forecast"], "cpi", now["period"])
    above = next(
        (
            quarter
            for quarter, entry in forecast["forecast"].items()
            if quarter > now["period"] and entry["cpi"]["median"] >= 3.0
        ),
        None,
    )
    return {
        "cpi": cpi, "core": core, "now": now, "forecast": forecast,
        "period": period, "values": values, "above": above,
    }


def inflation_hook() -> str:
    facts = inflation_facts()
    core_now = latest(facts["core"])
    tail = (
        f"the model's median does not reach 3% again until {facts['above']}"
        if facts["above"]
        else "the model's median stays below 3% across the archived horizon"
    )
    return (
        f"CPI is {stored(facts['now']['value'])}% in {facts['now']['period']} and "
        f"core {stored(core_now['value'])}% in {core_now['period']}; {tail}."
    )


def inflation_model() -> str:
    facts = inflation_facts()
    model = MODELS["boe-svar"]
    quality = model["quality"]["predictive_validation"]
    rows = []
    for period, values in list(facts["forecast"]["forecast"].items())[:5]:
        rows.append(
            "          <tr>"
            f'<th scope="row">{esc(period)}</th>'
            f"<td>{values['cpi']['median']:.2f}%</td>"
            f"<td>{values['cpi']['lo68']:.2f}%–{values['cpi']['hi68']:.2f}%</td>"
            f"<td>{values['cpi']['lo90']:.2f}%–{values['cpi']['hi90']:.2f}%</td>"
            "</tr>"
        )
    reaches = (
        f"Its median does not return to 3% until {esc(facts['above'])}."
        if facts["above"]
        else "Its median stays below 3% across the archived horizon."
    )
    return f"""    <div class="prose">
      <p>
        <a href="/svar">boe-svar</a> — the {esc(model["display_name"])} — forecasts
        headline CPI. The round generated {esc(facts["forecast"]["generated"])} puts
        the first open quarter, {esc(facts["period"])}, at
        {facts["values"]["median"]:.1f}% with a 68% range of
        {band_text(facts["values"])}. {reaches} And in the same breath:
      </p>
{limits_list([
        f"Status: {esc(model['status'])}.",
        f"It cannot answer {(cannot('boe-svar'))}.",
        "It forecasts headline CPI only. Core CPI is shown above as an outturn; no model in this suite forecasts it.",
        f"Uncertainty is {esc(model['uncertainty'])}; the sample ends {esc(model['estimation_sample'].split('-')[-1])} while the conditioning data run to {esc(model['data_edge'])}.",
    ])}
      <div class="table-scroll">
        <table>
          <caption>boe-svar year-on-year CPI inflation: median and predictive ranges, from the archived round.</caption>
          <thead><tr><th scope="col">Quarter</th><th scope="col">Median</th><th scope="col">68%</th><th scope="col">90%</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
      </div>
      <p class="callout">
        <strong>Predictive validation: {esc(quality["level"])}.</strong>
        {esc(quality["evidence"])}
        <a href="/svar/validation">Read the validation page →</a>
      </p>
    </div>"""


def inflation_run() -> str:
    return f"""    <div class="prose">
      <p>
        The CPI path above comes from the same command as the growth forecast.
        A second command carries it into household incomes: it scales the
        statutorily CPI-uprated benefit parameters by the model-versus-reference
        gap and scores that as a real reform.
      </p>
{codeblock(
        command("pe-macro forecast --horizons 8", "GDP and CPI, medians with 68% and 90% bands"),
        command("pe-macro svar-inflation-incidence --year 2027 --reference obr", "who bears the CPI gap, by decile"),
    )}
      <p>
        Over MCP: {tool("forecast_uk")} for the path and
        {tool("svar_inflation_incidence")} for the uprating incidence. The
        incidence run excludes the triple lock and frozen thresholds, and says
        so in its own caveats. <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


# --------------------------------------------------------------- 03 jobs

def jobs_facts() -> dict:
    unemployment = load("uk_unemployment_rate")
    round_file = json.loads(UNEMPLOYMENT_ROUND.read_text())
    now = latest(unemployment)
    period, values = next_open(round_file["forecast"], "unemployment", now["period"])
    return {
        "unemployment": unemployment, "now": now, "round": round_file,
        "period": period, "values": values,
    }


def jobs_hook() -> str:
    facts = jobs_facts()
    vacancies = load("uk_vacancies")
    quarters = len(facts["round"]["forecast"])
    return (
        f"Unemployment is {stored(facts['now']['value'])}% in "
        f"{facts['now']['period']} and vacancies "
        f"{stored(latest(vacancies)['value'])} thousand in "
        f"{latest(vacancies)['period']}; the satellite forecast runs "
        f"{quarters} quarters and then stops."
    )


def jobs_model() -> str:
    facts = jobs_facts()
    round_file = facts["round"]
    model = round_file["model"]
    information = round_file["information_set"]
    caveats = limits_list([esc(caveat) for caveat in round_file["caveats"]])
    registry = (
        "The satellite has no entry in the capability registry that backs the "
        "other model pages, and no CLI command or MCP tool of its own: its "
        "limits are the ones the archived round file states, quoted above."
        if satellite_has_no_surface()
        else "The satellite is exposed in the run surface below."
    )
    return f"""    <div class="prose">
      <p>
        The labour market is covered by a satellite, not a model of its own: the
        svar-unemployment satellite maps the <a href="/svar">boe-svar</a> GDP
        forecast onto the ONS unemployment rate through a fitted Okun relation.
        Round {esc(round_file["round_id"])} reads GDP from
        {esc(information["gdp_input"])} and unemployment from
        {esc(information["unemployment_input"])}, and puts
        {esc(facts["period"])} at {facts["values"]["median"]:.1f}%, 68%
        {band_text(facts["values"])}.
      </p>
      <p>
        The round file's own description of the mapping, verbatim:
        {esc(model["description"])}
      </p>
      <p>The round states its own limits, and they are strict:</p>
{caveats}
      <p class="callout">{registry}
        <a href="/forecasts">See the archived rounds →</a>
      </p>
      <p class="chooser-note">
        Vacancies and average weekly earnings above have no model view at all.
        They are outturns, shown because they move before the unemployment rate
        does — not because anything here forecasts them.
      </p>
    </div>"""


def jobs_run() -> str:
    return f"""    <div class="prose">
      <p>
        The satellite is a deterministic mapping applied to the GDP forecast, so
        the runnable half is the forecast itself; the mapping's coefficients are
        in the archived round file, not behind a command.
      </p>
{codeblock(
        command("pe-macro forecast --horizons 4", "the GDP path the satellite maps"),
        command("pe-macro model-status boe-svar", "supported uses, access, and stated limitations"),
    )}
      <p>
        Over MCP: {tool("forecast_uk")} for the GDP path and
        {tool("get_model_status")} for the limitations as structured data. The
        archived round itself is a committed JSON file under
        <span class="mono">forecasts/rounds/</span>, readable with no client at
        all. <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


# --------------------------------------------------------------- 04 rates

def rates_hook() -> str:
    bank = load("uk_bank_rate")
    ten = load("uk_gilt_10y")
    return (
        f"Bank Rate is {stored(latest(bank)['value'])}% and the 10-year gilt "
        f"{stored(latest(ten)['value'])}% — and no model on this site forecasts "
        "either."
    )


def rates_model() -> str:
    svar = MODELS["boe-svar"]
    microsim = MODELS["pe-microsim"]
    og = MODELS["og-uk"]
    frbus = MODELS["frb-us"]
    return f"""    <div class="prose">
      <p>
        <strong>No model in this suite forecasts Bank Rate or gilt yields.</strong>
        That is the honest answer, and this page will not dress it up as
        coverage. What the registry actually says:
      </p>
{limits_list([
        f"<a href=\"/svar\">boe-svar</a> outputs {registry_terms(svar['outputs'])} — no interest-rate path is among them.",
        f"<a href=\"/pe\">pe-microsim</a> lists {esc(microsim['cannot_answer'][2])} in its own cannot-answer field.",
        f"<a href=\"/olg\">{site_name('og-uk')}</a> does report an interest rate, but only as part of a {esc(og['horizon'].split(';')[0])}, and it cannot answer a {esc(og['cannot_answer'][0])}. A long-run comparative static is not a market view.",
        f"<a href=\"/frb-us\">frb-us</a> produces a {esc(frbus['outputs'][-1])}, for the {esc(', '.join(frbus['geography']).upper())} only.",
    ])}
      <p>
        So the numbers above stand alone: observed Bank of England data, dated
        and archived, with no forecast beside them. They still do work here —
        they are the market backdrop the other topics are read against, and the
        conditioning environment any future rate model would have to beat.
      </p>
      <p class="callout">
        This is the one topic where the useful output is a refusal. If you need
        a rate forecast, the suite does not have one; the
        <a href="/models">model directory</a> shows what it does have, and
        <a href="/models#validation">the evidence page</a> shows how well.
      </p>
    </div>"""


def rates_run() -> str:
    bank = load("uk_bank_rate")
    dirs = source_dirs()
    path = f"vintages/{dirs['uk_bank_rate']}/uk_bank_rate/{bank['vintage']}.json"
    return f"""    <div class="prose">
      <p>
        With no model to run, what is runnable is the data itself and the claim
        above. The vintage store is static files over HTTPS — no key, no
        account, stdlib only:
      </p>
{codeblock(
        esc("import json, urllib.request"),
        "",
        esc(f'BASE = "{SITE}/data"'),
        esc(f'with urllib.request.urlopen(f"{{BASE}}/{path}") as response:'),
        esc("    bank_rate = json.load(response)"),
        esc('print(bank_rate["vintage"], bank_rate["observations"][-1])')
        + f'   <span class="cm"># {esc(bank["vintage"])} '
        + f'{esc(repr(latest(bank)))}</span>',
    )}
      <p>And the refusal is checkable rather than asserted:</p>
{codeblock(
        command("pe-macro model-status", "every model, its country, status and access"),
        command("pe-macro model-status boe-svar --json", "outputs and cannot_answer, verbatim"),
    )}
      <p>
        Over MCP the same registry is {tool("list_model_capabilities")} and
        {tool("get_model_status")}; {tool("recommend_model")} returns an
        explicit warning rather than a guess when no model supports a request.
        <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


# ------------------------------------------------------- 05 public finances

def public_finances_hook() -> str:
    borrowing = load("uk_public_sector_net_borrowing")
    debt = load("uk_public_sector_net_debt_gdp")
    now = latest(borrowing)
    return (
        f"Net borrowing is stored as {stored(now['value'])} (£m, a negative "
        f"balance) for {now['period']} and debt is {stored(latest(debt)['value'])}% "
        "of GDP; the OBR emulator runs scenarios, not a forecast."
    )


def public_finances_note() -> str:
    borrowing = load("uk_public_sector_net_borrowing")
    now = latest(borrowing)
    return (
        "The ONS records J5II as a negative financial balance, and that is the "
        f"number shown above: a stored value of {stored(now['value'])} "
        f"({esc(borrowing['units'])}) means £{-now['value'] / 1000:,.1f}bn was "
        f"borrowed in {esc(now['period'])}. The sign is the publisher's "
        "convention, kept rather than silently flipped."
    )


def public_finances_model() -> str:
    model = MODELS["obr-macro"]
    predictive = model["quality"]["predictive_validation"]
    counterfactual = model["quality"]["policy_counterfactual_validity"]
    return f"""    <div class="prose">
      <p>
        The <a href="/obr">OBR emulator</a> — the {esc(model["display_name"])} —
        is the model closest to this topic, and the first thing to say about it
        is what it is not. Its question types in the registry are
        {registry_terms(model["question_types"])}: <strong>forecast is not among
        them</strong>. It answers "what would this shock do to the
        {esc(model["data_vintage"])}", never "what will borrowing be".
      </p>
{limits_list([
        f"Outputs: {registry_terms(model['outputs'])}. Neither number above is one of them.",
        f"It cannot answer {(cannot('obr-macro'))}. The second of those is decisive here: the emulator cannot report borrowing at all.",
        f"Status: {esc(model['status'])}. Uncertainty: {esc(model['uncertainty'])}.",
        f"Baseline: {esc(model['data_vintage'])}, so every scenario is a deviation from that vintage, not from today's outturn.",
    ])}
      <p class="callout">
        <strong>Predictive validation: {esc(predictive["level"])}.</strong>
        {esc(predictive["evidence"])}
        <strong>Policy counterfactuals: {esc(counterfactual["level"])}.</strong>
        {esc(counterfactual["evidence"])}
        <a href="/obr/validation">Read the validation page →</a>
      </p>
      <p>
        So the borrowing and debt figures above are outturns with no model path
        beside them. What the emulator adds is the counterfactual: run a
        spending or corporation-tax change through it and read the GDP,
        consumption and investment response — then take the fiscal arithmetic
        from <a href="/economy/topics/reform">tax and benefit reform</a>, which
        is where the costing actually lives.
      </p>
    </div>"""


def public_finances_run() -> str:
    return f"""    <div class="prose">
      <p>
        A raw shock in model units, and the list of variables that can be
        shocked. £1,250m per quarter is a £5bn-a-year increase in real
        government consumption, held for four quarters:
      </p>
{codeblock(
        command("pe-macro variables", "shockable OBR variables and their units"),
        command("pe-macro obr-shock --var CGG --shock 1250 --periods 4", "£5bn/year of government consumption"),
    )}
      <p>
        Over MCP: {tool("list_reform_variables")} and {tool("obr_shock")}. The
        result carries the per-quarter GDP, consumption and investment
        deviations — and nothing about borrowing, for the reason stated above.
        <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


# --------------------------------------------------------------- 06 reform

def reform_hook() -> str:
    microsim = MODELS["pe-microsim"]
    return (
        "No series stands behind this one: pe-microsim scores a reform over a "
        f"{microsim['horizon']} and cannot see "
        f"{listed(microsim['cannot_answer'])} without a macro bridge."
    )


def reform_capability_card(title: str, value: str, note: str, facts: list[tuple[str, str]]) -> str:
    rows = "\n".join(
        f"            <div><dt>{esc(name)}</dt><dd>{esc(text)}</dd></div>"
        for name, text in facts
    )
    return f"""        <article class="economy-stat">
          <p class="economy-stat-label mono">{esc(title.upper())}</p>
          <p class="economy-stat-value">{esc(value)}</p>
          <p class="economy-stat-change">{esc(note)}</p>
          <dl>
{rows}
          </dl>
        </article>"""


def reform_stands() -> str:
    microsim = MODELS["pe-microsim"]
    obr = MODELS["obr-macro"]
    dynamic = MODELS["og+microsim"]
    cards = "\n".join((
        reform_capability_card(
            "pe-microsim", ", ".join(microsim["geography"]).upper(),
            microsim["model_class"],
            [("Horizon", microsim["horizon"]), ("Runtime", microsim["runtime"]),
             ("Access", ", ".join(microsim["access"]))],
        ),
        reform_capability_card(
            "obr-macro bridge", ", ".join(obr["geography"]).upper(),
            obr["model_class"],
            [("Horizon", obr["horizon"]), ("Runtime", obr["runtime"]),
             ("Access", ", ".join(obr["access"]))],
        ),
        reform_capability_card(
            site_name("og+microsim"), ", ".join(dynamic["geography"]).upper(),
            dynamic["model_class"],
            [("Horizon", dynamic["horizon"]), ("Runtime", dynamic["runtime"]),
             ("Access", ", ".join(dynamic["access"]))],
        ),
    ))
    return f"""    <div class="economy-grid">
{cards}
    </div>
    <p class="economy-method">
      This is the one topic with no official series behind it, so there is no
      vintage to date: what stands is a capability, and the cards above are read
      straight out of the committed capability registry rather than written by
      hand. A reform is one <span class="mono">{{parameter_path: value}}</span>
      dictionary, and the same dictionary is accepted by every route below.
    </p>"""


def reform_model() -> str:
    microsim = MODELS["pe-microsim"]
    obr = MODELS["obr-macro"]
    dynamic = MODELS["og+microsim"]
    return f"""    <div class="prose">
      <p>
        <a href="/pe">pe-microsim</a> is the scorer: it applies the reform to
        household microdata and reports {registry_terms(microsim["outputs"])}.
        It is {esc(microsim["status"])}, and its uncertainty is
        {esc(microsim["uncertainty"])}. The limit is structural, and it is the
        reason this topic needs a bridge at all:
      </p>
{limits_list([
        f"pe-microsim cannot answer {(cannot('pe-microsim'))}. A costing from it is a static costing.",
        f"The <a href=\"/obr\">OBR emulator</a> supplies the macro feedback through a reviewed reform translation, but only for {registry_terms(obr['question_types'])}, and it cannot answer {(cannot('obr-macro'))}.",
        f"<a href=\"/olg\">{site_name('og+microsim')}</a> goes further — {esc(dynamic['model_class'])} — but is {esc(dynamic['status'])}.",
        f"{site_name('og+microsim')} also cannot answer {(cannot('og+microsim'))}.",
    ])}
      <p>
        Nothing here averages those answers together. They use different
        horizons and mechanisms, so the comparison command prints them side by
        side with an explicit comparability field on every row and a warning
        that related-but-not-like-for-like results must not be added, averaged
        or ranked.
      </p>
      <p class="chooser-note">
        Reform scoring is the one place where the macro models and the household
        model meet — <a href="/models#score">see how a score is put together →</a>
      </p>
    </div>"""


def reform_run() -> str:
    reform = '{"gov.hmrc.income_tax.rates.uk[0].rate":0.21}'
    return f"""    <div class="prose">
      <p>
        One reform vocabulary, three routes. The static costing first, then the
        same reform through the macro bridge, then both side by side:
      </p>
{codeblock(
        command("pe-macro parameters", "curated reform parameter paths, live-resolved"),
        command(f"pe-macro score --country uk --reform '{reform}' --model microsim", "static population costing"),
        command(f"pe-macro score --country uk --reform '{reform}' --model obr", "the same reform with OBR macro feedback"),
        command(f"pe-macro compare --country uk --reform '{reform}' --models microsim,obr", "both, with comparability warnings"),
    )}
      <p>
        Over MCP: {tool("list_reform_parameters")}, {tool("score_reform")},
        {tool("population_reform_impact")} for the population costing,
        {tool("household_reform_impact")} for a single household, and
        {tool("dynamic_reform_impact")} for the {site_name("og+microsim")} overlay.
        {tool("recommend_model")} routes a question to a model, or refuses.
        <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


def reform_data() -> str:
    microsim = MODELS["pe-microsim"]
    return f"""    <div class="prose">
      <p>
        There is no vintage table on this page because no series in the store
        feeds a reform score. The provenance is different in kind: the microdata
        and parameter tree come from the PolicyEngine country package, and the
        registry describes that vintage as
        &ldquo;{esc(microsim["data_vintage"])}&rdquo;. Every run records its own,
        which is why two scores taken months apart can differ without either
        being wrong.
      </p>
      <p>
        The store still matters here, one step removed: it holds the outturns
        the macro side of any score is judged against, and the dated snapshots
        that make a past score reproducible.
      </p>
      <p class="chooser-note">
        Dated, immutable JSON snapshots of every series this site reads —
        <a href="/forecasts#data">browse the store, its release calendar, and the as-of recipe →</a>
      </p>
    </div>"""


# --------------------------------------------- the platform band on the hubs
#
# Band 01 of /forecasts and /forecasts/us: what a reader can actually produce
# here, with pe-microsim at the centre of it. Everything below is derived —
# the "core" claim from the registry, the commands from cli.py, the tool names
# from the golden surface — so the band cannot outlive the capability it
# advertises. The three raise-instead-of-print helpers are the same contract
# ``no_us_forecaster`` has held on the US topic pages.

# Registry key -> the model's page on this site.
MODEL_PAGES = {
    "pe-microsim": "/pe",
    "obr-macro": "/obr",
    "boe-svar": "/svar",
    "frb-us": "/frb-us",
    "us-hank": "/us-hank",
    "og-uk": "/olg",
    "og+microsim": "/olg",
    "define-uk": "/define",
}


def model_link(model_id: str) -> str:
    return f'<a href="{MODEL_PAGES[model_id]}">{esc(site_name(model_id))}</a>'


def only_household_member() -> str:
    """pe-microsim is the only member that answers a household question."""
    members = sorted(
        model_id
        for model_id, model in MODELS.items()
        if "household" in model["question_types"]
    )
    if members != ["pe-microsim"]:
        raise RuntimeError(
            "the Forecasts hub is built on pe-microsim being the only member "
            'whose question_types include "household", but the registry now '
            f"lists {', '.join(members)} — rewrite the band rather than the claim"
        )
    return (
        'the only member whose question types include '
        f'<span class="mono">household</span>'
    )


def only_two_country_member() -> str:
    """pe-microsim is the only member covering both countries."""
    members = sorted(
        model_id
        for model_id, model in MODELS.items()
        if {"uk", "us"} <= set(model["geography"])
    )
    if members != ["pe-microsim"]:
        raise RuntimeError(
            "the Forecasts hub says pe-microsim is the only member covering "
            f"both countries, but the registry now lists {', '.join(members)}"
        )
    return "the only one that covers both countries"


def distribution_members() -> str:
    """The members that report a distribution — pe-microsim and its overlay."""
    members = sorted(
        model_id
        for model_id, model in MODELS.items()
        if any("distribution" in output for output in model["outputs"])
    )
    if members != ["og+microsim", "pe-microsim"]:
        raise RuntimeError(
            "the Forecasts hub says the only members reporting a distribution "
            "are pe-microsim and the og+microsim overlay that runs it, but the "
            f"registry now lists {', '.join(members)}"
        )
    return (
        f"The only two members that report a distribution are {model_link('pe-microsim')} "
        f"and {model_link('og+microsim')}, and the second is an overlay that "
        "runs the first."
    )


def route_row(title: str, chain: list[str], line: str, comment: str) -> str:
    """One producible output: what it is, which models run, and the command."""
    rendered_chain = (
        " &rarr; ".join(model_link(model_id) for model_id in chain)
        if chain
        else "&mdash;"
    )
    return (
        "          <tr>"
        f'<th scope="row">{esc(title)}</th>'
        f"<td>{rendered_chain}</td>"
        f"<td>{esc(comment)}</td>"
        f'<td><code class="mono">{command(line)}</code></td>'
        "</tr>"
    )


UK_REFORM = '{"gov.hmrc.income_tax.rates.uk[0].rate":0.21}'
US_REFORM = '{"gov.irs.credits.ctc.amount.adult_dependent":1000}'
PEOPLE = '[{"age":35,"employment_income":50000}]'


def uk_platform() -> str:
    """Band 01 of /forecasts: the six things this section can produce."""
    microsim = MODELS["pe-microsim"]
    svar = MODELS["boe-svar"]
    rows = [
        route_row(
            "One household, exactly",
            ["pe-microsim"],
            f"pe-macro household-impact --country uk --people '{PEOPLE}' --reform '{UK_REFORM}'",
            "arithmetic over the statutory rules; no sampling, no weights",
        ),
        route_row(
            "The whole population, one policy year",
            ["pe-microsim"],
            f"pe-macro score --country uk --reform '{UK_REFORM}' --model microsim",
            "revenue and distribution; a static costing",
        ),
        route_row(
            "The same reform, with a macro second round",
            ["pe-microsim", "obr-macro"],
            f"pe-macro score --country uk --reform '{UK_REFORM}' --model obr",
            "the static costing becomes a held add-factor on household income",
        ),
        route_row(
            "The same reform, with long-run general equilibrium",
            ["og-uk", "pe-microsim"],
            f"pe-macro dynamic-score --reform '{UK_REFORM}'",
            "steady-state earnings ratio scales the microsim's income inputs",
        ),
        route_row(
            "A GDP and CPI forecast, standing alone",
            ["boe-svar"],
            "pe-macro forecast --horizons 8",
            "medians with 68% and 90% bands; archived and scored below",
        ),
        route_row(
            "That forecast carried into household incomes",
            ["boe-svar", "pe-microsim"],
            "pe-macro svar-inflation-incidence --year 2027 --reference obr",
            "the model-versus-OBR CPI gap, scored as a real uprating reform",
        ),
    ]
    return f"""    <div class="prose">
      <p>
        The engine underneath this section is
        {model_link("pe-microsim")} — PolicyEngine's own
        {esc(microsim["model_class"])}, {only_household_member()} and
        {only_two_country_member()}. It applies a reform to household microdata
        and reports {registry_terms(microsim["outputs"])} over a
        {esc(microsim["horizon"])}. {distribution_members()}
      </p>
      <p>
        The macro members are what it cannot do on its own. pe-microsim
        cannot answer {(cannot('pe-microsim'))} — so every macro number in this
        section comes from a member that produces one, and the table says which,
        in the order they run. Four of the six routes below put pe-microsim in
        the chain; two are a macro model standing alone, which is also a fine
        thing to publish.
      </p>
      <div class="table-scroll">
        <table>
          <caption>What this section can produce for the UK. Every command is checked against <code>cli.py</code> when this page is generated; a route that stopped running would fail the build rather than sit here.</caption>
          <thead><tr><th scope="col">What you get</th><th scope="col">Models, in the order they run</th><th scope="col">What the chain does</th><th scope="col">Command</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
      </div>
      <p class="callout">
        <strong>pe-microsim does not forecast, and this section does not
        pretend it does.</strong> Its question types are
        {registry_terms(microsim["question_types"])} —
        <span class="mono">forecast</span> is not among them, and its
        predictive validation is recorded as
        {registry_terms([microsim["quality"]["predictive_validation"]["level"]])}.
        The forecast rows are {model_link("boe-svar")}, whose uncertainty is
        {esc(svar["uncertainty"])}; the record below is what those rounds have
        been worth so far. <a href="/models#score">See how a score is put together →</a>
      </p>
      <p>
        Over MCP the same six routes are {tool("household_reform_impact")},
        {tool("population_reform_impact")}, {tool("score_reform")},
        {tool("dynamic_reform_impact")}, {tool("forecast_uk")} and
        {tool("svar_inflation_incidence")}; {tool("recommend_model")} routes a
        question to a member, or refuses when none supports it.
        <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


def us_platform() -> str:
    """Band 01 of /forecasts/us: what runs, and the two things that do not."""
    microsim = MODELS["pe-microsim"]
    rows = [
        route_row(
            "One household, exactly",
            ["pe-microsim"],
            f"pe-macro household-impact --country us --people '{PEOPLE}' --reform '{US_REFORM}'",
            "arithmetic over the statutory rules; no sampling, no weights",
        ),
        route_row(
            "The whole population, one policy year",
            ["pe-microsim"],
            f"pe-macro score --country us --reform '{US_REFORM}' --model microsim",
            "revenue and distribution; a static costing",
        ),
        route_row(
            "A macro shock carried into household earnings",
            ["frb-us", "pe-microsim"],
            "pe-macro frbus-shock-incidence --var rffintay_aerr --shock 1.0 --year 2027",
            "the wage-bill change applied through the automatic stabilisers",
        ),
        route_row(
            "The same question in the HANK member",
            ["us-hank", "pe-microsim"],
            "pe-macro hank-shock-incidence --kind monetary --size -0.0025 --year 2026",
            "impulse responses around a calibrated steady state",
        ),
    ]
    return f"""    <div class="prose">
      <p>
        The engine underneath this section is
        {model_link("pe-microsim")} — {only_two_country_member()}, so the two
        household rows below are the same command as the UK ones with
        <span class="mono">--country us</span>. It reports
        {registry_terms(microsim["outputs"])} over a {esc(microsim["horizon"])}.
      </p>
      <div class="table-scroll">
        <table>
          <caption>What this section can produce for the US. Every command is checked against <code>cli.py</code> when this page is generated.</caption>
          <thead><tr><th scope="col">What you get</th><th scope="col">Models, in the order they run</th><th scope="col">What the chain does</th><th scope="col">Command</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
      </div>
      <p>
        Two rows that exist on the UK side are missing here, and both absences
        are the registry's, not an oversight:
      </p>
{limits_list([
        "<strong>No reform with a macro second round.</strong> Both US "
        f'members — {model_link("frb-us")} and {model_link("us-hank")} — record '
        f'{registry_terms([registry_cannot("frb-us", "policyengine")])} in '
        "their own cannot-answer field, and us-hank adds "
        f'{registry_terms([registry_cannot("us-hank", "detailed tax")])}. No '
        "mapping exists from a US statutory reform to a US macro model, and "
        "none is invented here.",
        f"<strong>No forecast.</strong> {no_us_forecaster()} A section called "
        "Forecasts that showed a US path anyway would be the one dishonest "
        "thing on this site.",
    ])}
      <p>
        The bridge that does exist runs the other way: the incidence rows take
        a <em>macro shock</em>, not a reform, and push its earnings
        consequences through the microsimulation. So this section can answer
        &ldquo;who bears this shock&rdquo; for the US, and cannot answer
        &ldquo;what would this reform do to output&rdquo;.
      </p>
      <p>
        Over MCP the four routes are {tool("household_reform_impact")},
        {tool("population_reform_impact")}, {tool("frbus_shock_incidence")} and
        {tool("hank_shock_incidence")}; {tool("recommend_model")} refuses a US
        reform needing macro feedback, which is the correct answer.
        <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


# ------------------------------------------------------ US: shared apparatus

LONGBASE_FILE = (
    ROOT / "papers" / "frb-us" / "figures" / "longbase_baseline_yoy.csv"
)


def longbase() -> list[dict]:
    """The committed FRB/US LONGBASE conditioning baseline, near-term path."""
    lines = [
        line
        for line in LONGBASE_FILE.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    header = lines[0].split(",")
    return [
        {
            key: value if key == "quarter" else float(value)
            for key, value in zip(header, line.split(","))
        }
        for line in lines[1:]
    ]


def next_baseline(last_observed: str) -> dict:
    """First baseline quarter the official data has not printed yet."""
    edge = quarter_of(last_observed)
    rows = longbase()
    for row in rows:
        if row["quarter"] > edge:
            return row
    return rows[-1]


def forecasters(country: str) -> list[str]:
    """Registry models whose question types include a forecast, by country."""
    return sorted(
        model_id
        for model_id, model in MODELS.items()
        if "forecast" in model["question_types"] and country in model["geography"]
    )


def no_us_forecaster() -> str:
    """The sentence every US topic page is built on, checked before printing.

    boe-svar is the only member whose ``question_types`` include "forecast",
    and its geography is UK-only; both US models are shock models that say so
    themselves. If that stops being true this raises rather than letting five
    public pages keep printing a refusal that has quietly become false.
    """
    us = forecasters("us")
    if us:
        raise RuntimeError(
            "every US topic page states that no model here forecasts the US "
            f"economy, but the capability registry now lists {', '.join(us)} "
            'with "forecast" in question_types — write the forecast layer '
            "instead of shipping the refusal"
        )
    return (
        "No model in this suite forecasts the US economy. The only member "
        'whose question types include <span class="mono">forecast</span> is '
        f'<a href="/svar">{listed(forecasters("uk"))}</a>, and its geography '
        "is UK-only."
    )


def us_hub_forecast_note() -> str:
    """The claim /economy/us is built on, re-derived on every render.

    The hub used to assert this in hand-written prose above six stat cards and
    a band of model cards. The cards are gone — every reading they carried is
    on the topic page that owns the series — so the claim is what remains, and
    it is generated rather than typed: ``no_us_forecaster`` fails the build,
    not the reader, if a US forecaster ever enters the registry.
    """
    frbus = MODELS["frb-us"]["quality"]["predictive_validation"]
    hank = MODELS["us-hank"]["quality"]["predictive_validation"]
    return f"""      <p class="lede reveal" style="--d:3">
        <strong>{no_us_forecaster()}</strong> Both US members are shock models
        and the registry says so in their own words:
        <a href="/frb-us">frb-us</a> records predictive validation
        {registry_terms([frbus["level"]])} —
        &ldquo;{esc(frbus["evidence"])}&rdquo; — and
        <a href="/us-hank">us-hank</a> records
        {registry_terms([hank["level"]])}. Where a model view exists at all it
        is on the topic page that reads the series, in the same breath as the
        limits that qualify it.
      </p>"""


def us_model_limits(extra: list[str] | None = None) -> str:
    """Both US models, quoted out of the registry rather than characterised."""
    frbus, hank = MODELS["frb-us"], MODELS["us-hank"]
    frbus_quality = frbus["quality"]["predictive_validation"]
    hank_quality = hank["quality"]["predictive_validation"]
    return limits_list([
        f'<a href="/frb-us">frb-us</a> answers '
        f'{registry_terms(frbus["question_types"])} and nothing else. Its '
        f'predictive validation is {registry_terms([frbus_quality["level"]])} '
        f'— &ldquo;{esc(frbus_quality["evidence"])}&rdquo;',
        f'<a href="/us-hank">us-hank</a> answers '
        f'{registry_terms(hank["question_types"])}, and the first thing it '
        f'cannot answer is {esc(hank["cannot_answer"][0])}. Its predictive '
        f'validation is {registry_terms([hank_quality["level"]])} — '
        f'&ldquo;{esc(hank_quality["evidence"])}&rdquo;',
    ] + (extra or []))


LONGBASE_COLUMNS = {
    "gdp_yoy_pct": ("year-on-year real GDP growth", "%"),
    "cpi_yoy_pct": ("year-on-year CPI inflation", "%"),
    "unemployment_pct": ("the unemployment rate", "%"),
}


def longbase_layer(column: str, last_observed: str) -> str:
    """The conditioning baseline, framed as what it is: not a forecast.

    /economy/us and the homepage already show this path beside the outturns.
    It is repeated here rather than omitted because the alternative is a topic
    page that is silent about the one model artifact covering the series — but
    it carries no interval, because it has none, and the caption and the row
    labels say what it is every time it appears.
    """
    description, unit = LONGBASE_COLUMNS[column]
    edge = quarter_of(last_observed)
    rows = []
    for row in longbase():
        published = row["quarter"] <= edge
        rows.append(
            "          <tr>"
            f'<th scope="row">{esc(row["quarter"])}</th>'
            f"<td>{row[column]:.2f}{unit}</td>"
            f"<td>{'outturn already published' if published else 'no outturn yet'}</td>"
            "<td>none — the baseline carries no interval</td>"
            "</tr>"
        )
    return f"""      <div class="table-scroll">
        <table>
          <caption>FRB/US April 2026 LONGBASE, {esc(description)}. This is the conditioning baseline that frb-us shock experiments deviate from — not a forecast, and not scored on <a href="/forecasts">the forecast record</a>.</caption>
          <thead><tr><th scope="col">Quarter</th><th scope="col">Baseline</th><th scope="col">Status against the outturn</th><th scope="col">Uncertainty</th></tr></thead>
          <tbody>
{chr(10).join(rows)}
          </tbody>
        </table>
      </div>"""


def us_run_note() -> str:
    return f"""      <p>
        Over MCP the same two models are {tool("frbus_shock")} and
        {tool("hank_shock")}, their metadata and scope limits are
        {tool("frbus_summary")} and {tool("hank_summary")}, and
        {tool("get_model_status")} returns the limitations quoted above as
        structured data rather than prose. {tool("recommend_model")} returns an
        explicit warning rather than a guess when no model supports a request.
        <a href="/connect">Connect a client →</a>
      </p>"""


US_DATA_CLOSING = (
    "FRED supplies no announced next-release date through this site's "
    "fetcher, so the column says so rather than guessing a schedule from the "
    "publisher's calendar."
)


# ------------------------------------------------------------- US 01 growth

def us_growth_facts() -> dict:
    gdp = load("us_real_gdp")
    return {"gdp": gdp, "now": yoy(gdp, 4)[-1]}


def us_growth_hook() -> str:
    facts = us_growth_facts()
    now = latest(facts["gdp"])
    baseline = next_baseline(facts["now"]["period"])
    return (
        f"Real GDP is {facts['now']['value']:.1f}% up on the year in "
        f"{facts['now']['period']}, derived here from a stored level of "
        f"{stored(now['value'])}; no model on this site forecasts US output, "
        f"and the {baseline['gdp_yoy_pct']:.1f}% shown for "
        f"{baseline['quarter']} below is a conditioning baseline, not a "
        "forecast."
    )


def us_growth_note() -> str:
    gdp = load("us_real_gdp")
    now = gdp["observations"][-1]
    year_ago = year_earlier(gdp, now["period"])
    change = 100 * (now["value"] / year_ago["value"] - 1)
    return (
        "GDPC1 is a level, not a growth rate: FRED stores it as "
        f"{esc(gdp['units'])}. The UK growth topic can print a published "
        "year-on-year rate because the ONS publishes one; there is no "
        "equivalent series in this store for the US, so the rate above is "
        f"derived from the stored levels — {stored(now['value'])} in "
        f"{esc(now['period'])} against {stored(year_ago['value'])} in "
        f"{esc(year_ago['period'])} is {change:.1f}%."
    )


def us_growth_model() -> str:
    facts = us_growth_facts()
    frbus = MODELS["frb-us"]
    return f"""    <div class="prose">
      <p>
        <strong>{no_us_forecaster()}</strong> What the two US models do
        instead is trace deviations from a fixed baseline, and the registry is
        specific about how far that goes:
      </p>
{us_model_limits([
        f'frb-us outputs {registry_terms(frbus["outputs"])} — as responses to a '
        f'reviewed shock under a declared policy rule, over a {esc(frbus["horizon"])} '
        'horizon, never as a path anyone is asked to believe in.',
    ])}
      <p>
        The baseline those deviations are measured from is published, so it is
        shown rather than hidden. It is the Federal Reserve staff-style
        conditioning path packaged with the model, extracted from
        <span class="mono">LONGBASE.TXT</span>, and it carries no bands because
        none exist:
      </p>
{longbase_layer("gdp_yoy_pct", facts["now"]["period"])}
      <p class="callout">
        <strong>Predictive validation: {registry_terms([frbus["quality"]["predictive_validation"]["level"]])}.</strong>
        {esc(frbus["quality"]["predictive_validation"]["evidence"])}
        <a href="/frb-us/validation">Read the validation page →</a>
      </p>
      <p class="chooser-note">
        The UK growth topic carries a model forecast with 68% and 90% ranges
        because boe-svar produces one and it is scored before the outturn
        exists. This page has no such layer, and inventing one out of a
        tracking baseline is the specific mistake it refuses to make —
        <a href="/economy/topics/growth">see the UK page for the contrast →</a>
      </p>
    </div>"""


def us_growth_run() -> str:
    return f"""    <div class="prose">
      <p>
        There is no forecast command to run. What is runnable is the model's
        own account of itself, the levers it exposes, and a shock: a 1
        percentage-point funds-rate surprise under the default inertial Taylor
        rule, read out over twenty quarters.
      </p>
{codeblock(
        command("pe-macro frbus-summary", "implementation, provenance and scope limits"),
        command("pe-macro frbus-variables", "the shockable FRB/US levers and their units"),
        command("pe-macro frbus-shock --var rffintay_aerr --shock 1.0 --horizon 20", "output response to a 1pp policy surprise"),
        command("pe-macro hank-shock --kind monetary --size -0.0025 --persistence 0.6", "the same question in the HANK model, as an IRF"),
    )}
{us_run_note()}
    </div>"""


# ---------------------------------------------------------- US 02 inflation

def us_inflation_facts() -> dict:
    cpi = load("us_cpi")
    return {"cpi": cpi, "now": yoy(cpi, 12)[-1]}


def us_inflation_hook() -> str:
    facts = us_inflation_facts()
    now = latest(facts["cpi"])
    return (
        f"CPI is {facts['now']['value']:.1f}% up on the year in "
        f"{facts['now']['period']}, derived here from a stored index of "
        f"{stored(now['value'])}; the store carries no US core CPI series, so "
        "this page has no core reading — and no model here forecasts the "
        "headline either."
    )


def us_inflation_note() -> str:
    cpi = load("us_cpi")
    now = cpi["observations"][-1]
    year_ago = year_earlier(cpi, now["period"])
    change = 100 * (now["value"] / year_ago["value"] - 1)
    months = len(cpi["observations"])
    span = 12 * (int(now["period"][:4]) - int(cpi["first_period"][:4])) + (
        int(now["period"][5:]) - int(cpi["first_period"][5:])
    ) + 1
    missing = span - months
    hole = (
        f" {'One' if missing == 1 else missing} month"
        f"{'s are' if missing != 1 else ' is'} missing from "
        f"the stored index between {esc(cpi['first_period'])} and "
        f"{esc(now['period'])}, which is why the comparison above is matched "
        "on the period it names rather than counted back twelve rows."
        if missing > 0
        else ""
    )
    return (
        f"CPIAUCSL is an index ({esc(cpi['units'])}), not a rate. The UK "
        "inflation topic shows two published rates because the ONS publishes "
        "them as rates; the figure above is derived from the stored index "
        f"instead — {stored(now['value'])} in {esc(now['period'])} against "
        f"{stored(year_ago['value'])} in {esc(year_ago['period'])} is "
        f"{change:.1f}%.{hole}"
    )


def us_inflation_model() -> str:
    facts = us_inflation_facts()
    hank = MODELS["us-hank"]
    return f"""    <div class="prose">
      <p>
        <strong>{no_us_forecaster()}</strong> Both US models report a price
        response, and neither reports a price <em>path</em>:
      </p>
{us_model_limits([
        f'us-hank outputs {registry_terms(hank["outputs"])} as '
        f'{esc(hank["horizon"])} around a calibrated steady state, with '
        f'uncertainty {esc(hank["uncertainty"])}.',
        "Neither model is scored against an inflation outturn anywhere on this "
        "site, because neither produces one to score.",
    ])}
      <p>
        The conditioning baseline the frb-us experiments deviate from does
        carry a CPI path, and it is shown for the same reason as on the growth
        page — with the same caveat, in the same table:
      </p>
{longbase_layer("cpi_yoy_pct", facts["now"]["period"])}
      <p class="callout">
        <strong>No core CPI.</strong> The UK inflation topic carries core CPI
        beside the headline because the ONS series DKO8 is in the store. There
        is no US core series in the store at all: adding one means adding
        CPILFESL to the FRED table in
        <span class="mono">data/fetch.py</span> and letting the append-only
        fetcher accumulate vintages for it. Until that happens this page shows
        headline only, and says so rather than leaving the gap to be noticed.
      </p>
    </div>"""


def us_inflation_run() -> str:
    return f"""    <div class="prose">
      <p>
        The price response to a policy surprise, in both models. The FRB/US
        run is a reviewed add-factor shock in model units; the HANK run is a
        first-order impulse response around the paper's calibration.
      </p>
{codeblock(
        command("pe-macro frbus-shock --var rffintay_aerr --shock 1.0 --horizon 20", "price response to a 1pp policy surprise"),
        command("pe-macro hank-summary", "shock catalogue, units and scope limits"),
        command("pe-macro hank-shock --kind monetary --size -0.0025 --persistence 0.6", "a 25bp easing, quarterly IRF"),
    )}
{us_run_note()}
    </div>"""


# --------------------------------------------------------------- US 03 jobs

def us_jobs_hook() -> str:
    unemployment = load("us_unemployment_rate")
    payrolls = load("us_payroll_employment")
    now = latest(unemployment)
    return (
        f"Unemployment is {stored(now['value'])}% in {now['period']} and "
        f"payrolls {display(payrolls, latest(payrolls)['value'])} in "
        f"{latest(payrolls)['period']}; there is no US vacancies series in the "
        "store, and no model here forecasts either number."
    )


def registry_output(model_id: str, needle: str) -> str:
    """One named output, found by what it is rather than by list position."""
    for output in MODELS[model_id]["outputs"]:
        if needle in output.lower():
            return output
    raise RuntimeError(
        f"{model_id} no longer lists an output matching {needle!r}; a US topic "
        "page names it, so update the page rather than the claim"
    )


def us_jobs_model() -> str:
    unemployment = load("us_unemployment_rate")
    frbus = MODELS["frb-us"]
    hank = MODELS["us-hank"]
    return f"""    <div class="prose">
      <p>
        <strong>{no_us_forecaster()}</strong> The labor market is also where
        the two US models differ most from each other, and the difference is
        worth stating plainly:
      </p>
{us_model_limits([
        f'frb-us does list {registry_terms([registry_output("frb-us", "unemploy")])} among its '
        "outputs — but as a deviation from the conditioning baseline under a "
        "declared policy rule, not a level anyone should read as a projection.",
        f'us-hank outputs {registry_terms(hank["outputs"])}. There is no labor '
        "market variable in that list at all: it reports no unemployment rate "
        "and no employment level, so on this topic it has nothing to say.",
        "Neither model reports payroll employment, so the second series above "
        "has no model view of any kind beside it.",
    ])}
      <p>
        The unemployment path in the conditioning baseline is the one model
        artifact covering this topic, and it is a baseline rather than a view:
      </p>
{longbase_layer("unemployment_pct", latest(unemployment)["period"])}
      <p class="chooser-note">
        The UK jobs topic has a satellite that maps the boe-svar GDP forecast
        onto the unemployment rate through a fitted Okun relation, and archives
        every round before the outturn exists. Nothing equivalent exists for
        the US, because the forecast it would map does not exist —
        <a href="/economy/topics/jobs">see the UK page →</a>
      </p>
      <p class="chooser-note">
        The UK page also carries vacancies and average weekly earnings as
        outturns. Neither has a US counterpart in this store: no JOLTS openings
        series and no earnings series is tracked, so this page is two series
        where the UK page is three.
      </p>
    </div>"""


def us_jobs_run() -> str:
    return f"""    <div class="prose">
      <p>
        <span class="mono">lur</span> is the FRB/US unemployment rate, so the
        runnable question on this topic is what a policy or spending surprise
        does to it — and, through the incidence bridge, whose earnings move
        when it does.
      </p>
{codeblock(
        command("pe-macro frbus-variables", "the shockable levers and their units"),
        command("pe-macro frbus-shock --var rffintay_aerr --shock 1.0 --horizon 20", "unemployment response to a 1pp policy surprise"),
        command("pe-macro frbus-shock-incidence --var rffintay_aerr --shock 1.0 --year 2027", "the same shock carried into household earnings, by decile"),
    )}
      <p>
        Over MCP: {tool("frbus_shock")} for the macro response and
        {tool("frbus_shock_incidence")} for the household overlay, which
        applies the wage-bill change uniformly and reports that it did.
        {tool("hank_shock_incidence")} is the same bridge for the HANK model.
        <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


# -------------------------------------------------------------- US 04 rates

def us_rates_hook() -> str:
    funds = load("us_federal_funds_rate")
    ten = load("us_treasury_10y")
    return (
        f"The effective federal funds rate is {stored(latest(funds)['value'])}% "
        f"in {latest(funds)['period']} and the 10-year Treasury "
        f"{stored(latest(ten)['value'])}% on {latest(ten)['period']} — and no "
        "model on this site forecasts either."
    )


def us_rates_model() -> str:
    frbus = MODELS["frb-us"]
    hank = MODELS["us-hank"]
    microsim = MODELS["pe-microsim"]
    return f"""    <div class="prose">
      <p>
        <strong>No model in this suite forecasts the federal funds rate or the
        Treasury curve.</strong> That is the honest answer, and this page will
        not dress it up as coverage. What the registry actually says:
      </p>
{limits_list([
        f'<a href="/frb-us">frb-us</a> does list a '
        f'{esc(registry_output("frb-us", "federal funds"))} among its outputs — but its question '
        f'types are {registry_terms(frbus["question_types"])}, so that rate is '
        "a reaction-function response to a shock under a declared policy rule, "
        "computed as a deviation from a fixed baseline. It is not a rate view.",
        f'<a href="/us-hank">us-hank</a> reports a '
        f'{registry_terms([registry_output("us-hank", "real_rate")])} — the '
        "model-consistent real rate implied by its own calibrated steady "
        f'state, as {esc(hank["horizon"])}. That is not a market yield, and '
        f'the model cannot answer {esc(hank["cannot_answer"][0])}.',
        f'<a href="/pe">pe-microsim</a> lists {esc(microsim["cannot_answer"][2])} '
        "in its own cannot-answer field.",
        "Nothing in the suite models the Treasury term structure at any "
        "maturity. There is no US counterpart to the gilt curve on the UK page "
        "because there is no US model that would read one.",
    ])}
      <p>
        So the two readings above stand alone: observed Federal Reserve data,
        dated and archived, with no model path beside them. They still do work
        here — they are the market backdrop the other US topics are read
        against, and the conditioning environment any future rate model would
        have to beat.
      </p>
      <p class="callout">
        This is the one US topic where the useful output is a refusal, and it
        is the same refusal the <a href="/economy/topics/rates">UK rates and
        gilts page</a> reaches for Bank Rate and gilt yields. If you need a
        rate forecast, the suite does not have one; the
        <a href="/models">model directory</a> shows what it does have, and
        <a href="/models#validation">the evidence page</a> shows how well.
      </p>
    </div>"""


def us_rates_run() -> str:
    funds = load("us_federal_funds_rate")
    dirs = source_dirs()
    path = (
        f"vintages/{dirs['us_federal_funds_rate']}/us_federal_funds_rate/"
        f"{funds['vintage']}.json"
    )
    return f"""    <div class="prose">
      <p>
        With no model to run, what is runnable is the data itself and the claim
        above. The vintage store is static files over HTTPS — no key, no
        account, stdlib only:
      </p>
{codeblock(
        esc("import json, urllib.request"),
        "",
        esc(f'BASE = "{SITE}/data"'),
        esc(f'with urllib.request.urlopen(f"{{BASE}}/{path}") as response:'),
        esc("    fed_funds = json.load(response)"),
        esc('print(fed_funds["vintage"], fed_funds["observations"][-1])')
        + f'   <span class="cm"># {esc(funds["vintage"])} '
        + f'{esc(repr(latest(funds)))}</span>',
    )}
      <p>And the refusal is checkable rather than asserted:</p>
{codeblock(
        command("pe-macro model-status", "every model, its country, status and access"),
        command("pe-macro model-status frb-us --json", "outputs, question types and cannot_answer, verbatim"),
        command("pe-macro model-status us-hank --json", "the same for the HANK member"),
    )}
      <p>
        Over MCP the same registry is {tool("list_model_capabilities")} and
        {tool("get_model_status")}; {tool("recommend_model")} returns an
        explicit warning rather than a guess when no model supports a request.
        <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


# ------------------------------------------------------------- US 05 reform

def registry_cannot(model_id: str, needle: str) -> str:
    """One cannot-answer entry, found by what it says rather than its index."""
    for item in MODELS[model_id]["cannot_answer"]:
        if needle in item.lower():
            return item
    raise RuntimeError(
        f"{model_id} no longer records a cannot_answer entry matching "
        f"{needle!r}, but the US reform page quotes it"
    )


def us_reform_hook() -> str:
    microsim = MODELS["pe-microsim"]
    return (
        "No series stands behind this one: pe-microsim scores a US reform over "
        f"a {microsim['horizon']}, and neither US macro model accepts a "
        "PolicyEngine reform at all."
    )


def us_reform_stands() -> str:
    microsim = MODELS["pe-microsim"]
    frbus = MODELS["frb-us"]
    hank = MODELS["us-hank"]
    cards = "\n".join((
        reform_capability_card(
            "pe-microsim", ", ".join(microsim["geography"]).upper(),
            microsim["model_class"],
            [("Horizon", microsim["horizon"]), ("Runtime", microsim["runtime"]),
             ("Access", ", ".join(microsim["access"]))],
        ),
        reform_capability_card(
            "frb-us", ", ".join(frbus["geography"]).upper(),
            frbus["model_class"],
            [("Horizon", frbus["horizon"]), ("Runtime", frbus["runtime"]),
             ("Reform bridge",
              f"none; cannot answer {registry_cannot('frb-us', 'policyengine')}")],
        ),
        reform_capability_card(
            "us-hank", ", ".join(hank["geography"]).upper(),
            hank["model_class"],
            [("Horizon", hank["horizon"]), ("Runtime", hank["runtime"]),
             ("Reform bridge",
              f"none; cannot answer {registry_cannot('us-hank', 'policyengine')}")],
        ),
    ))
    return f"""    <div class="economy-grid">
{cards}
    </div>
    <p class="economy-method">
      This is the one topic with no official series behind it, so there is no
      vintage to date: what stands is a capability, and the cards above are
      read straight out of the committed capability registry rather than
      written by hand. pe-microsim is the only member covering both countries —
      the two US macro models are shock models, and the last row of each of
      their cards is the reason this page stops where it does.
    </p>"""


def us_reform_model() -> str:
    microsim = MODELS["pe-microsim"]
    obr = MODELS["obr-macro"]
    dynamic = MODELS["og+microsim"]
    return f"""    <div class="prose">
      <p>
        <a href="/pe">pe-microsim</a> is the scorer, and for the US it is the
        whole of it: it applies the reform to household microdata and reports
        {registry_terms(microsim["outputs"])}. It is
        {esc(microsim["status"])}, and its uncertainty is
        {esc(microsim["uncertainty"])}.
      </p>
      <p>
        The limit is the same structural one the UK page describes — a static
        costing has no macro feedback in it — but the US answer to it is
        different, and worse:
      </p>
{limits_list([
        f"pe-microsim cannot answer {(cannot('pe-microsim'))}. A US costing "
        "from it is a static costing.",
        f'On the UK side that gap is bridged: <a href="/obr">obr-macro</a> '
        f'supplies macro feedback through a reviewed reform translation, and '
        f'<a href="/olg">{site_name("og+microsim")}</a> adds '
        f'{esc(dynamic["model_class"])}. Both are '
        f'{registry_terms(obr["geography"])}-only.',
        "<strong>There is no US equivalent of either.</strong> Both US models "
        f'record {esc(registry_cannot("frb-us", "policyengine"))} in their own '
        "cannot-answer field, and us-hank adds "
        f'{esc(registry_cannot("us-hank", "detailed tax"))}. No mapping exists '
        "from a US statutory reform to a US macro model, and none is invented "
        "here.",
    ])}
      <p>
        One bridge does exist, and it runs the other way. The incidence
        commands take a <em>macro shock</em>, not a reform, and push its
        earnings consequences through the microsimulation — so the suite can
        answer &ldquo;who bears this shock&rdquo; for the US, and cannot answer
        &ldquo;what would this reform do to output&rdquo;.
      </p>
      <p class="chooser-note">
        Reform scoring is the one place where the macro models and the
        household model meet — <a href="/models#score">see how a score is put
        together →</a>
      </p>
    </div>"""


def us_reform_run() -> str:
    reform = '{"gov.irs.credits.ctc.amount.adult_dependent":1000}'
    return f"""    <div class="prose">
      <p>
        One reform vocabulary, and for the US one scoring route. A $1,000
        adult-dependent credit, scored statically on the population, then the
        macro-to-household bridge that does exist:
      </p>
{codeblock(
        command("pe-macro parameters", "curated reform parameter paths, live-resolved, both countries"),
        command(f"pe-macro score --country us --reform '{reform}' --model microsim", "static population costing"),
        command(f"pe-macro population-impact --country us --reform '{reform}' --year 2027", "revenue and distribution for one policy year"),
        command("pe-macro frbus-shock-incidence --var rffintay_aerr --shock 1.0 --year 2027", "a macro shock's earnings incidence — not a reform"),
    )}
      <p>
        Over MCP: {tool("list_reform_parameters")}, {tool("score_reform")},
        {tool("population_reform_impact")} for the population costing and
        {tool("household_reform_impact")} for a single household.
        {tool("recommend_model")} routes a question to a model, or refuses —
        and for a US reform needing macro feedback it refuses, which is the
        correct answer.
        <a href="/connect">Connect a client →</a>
      </p>
    </div>"""


def us_reform_data() -> str:
    microsim = MODELS["pe-microsim"]
    return f"""    <div class="prose">
      <p>
        There is no vintage table on this page because no series in the store
        feeds a reform score. The provenance is different in kind: the
        microdata and parameter tree come from the
        <span class="mono">policyengine-us</span> country package, and the
        registry describes that vintage as
        &ldquo;{esc(microsim["data_vintage"])}&rdquo;. Every run records its
        own, which is why two scores taken months apart can differ without
        either being wrong.
      </p>
      <p>
        The store still matters here, one step removed: the six FRED series it
        holds are the outturns any macro leg of a US score would have to be
        judged against — and the absence of a US fiscal series in it is why
        this site has no US public-finances topic to carry the other half of a
        costing.
      </p>
      <p class="chooser-note">
        Dated, immutable JSON snapshots of every series this site reads —
        <a href="/forecasts#data">browse the store, its release calendar, and the as-of recipe →</a>
      </p>
    </div>"""


# ------------------------------------------------------------ the UK's six

UK_TOPICS = [
    {
        "slug": "growth",
        "title": "Growth",
        "eyebrow": "UK topic · output and investment",
        "heading": "Is the economy growing, and what does the model expect next?",
        "series": ("uk_gdp_cvm", "uk_monthly_gva", "uk_business_investment"),
        "hook": growth_hook,
        "stands_note": growth_note,
        "model": growth_model,
        "run": growth_run,
        "data_note": (
            "Quarterly national accounts are revised for years after first "
            "publication, which is why the snapshot date matters as much as the "
            "observation period."
        ),
    },
    {
        "slug": "inflation",
        "title": "Inflation",
        "eyebrow": "UK topic · prices",
        "heading": "Where are prices now, and where does the model put them?",
        "series": ("uk_cpi_yoy", "uk_core_cpi_yoy"),
        "hook": inflation_hook,
        "stands_note": (
            "Both series are published by the ONS as year-on-year rates, so the "
            "values above are the published rates themselves, not a "
            "transformation applied here."
        ),
        "model": inflation_model,
        "run": inflation_run,
        "data_note": (
            "Headline CPI is stored quarterly and core CPI monthly, so the two "
            "observation periods above do not line up — that is the data, not a "
            "presentation choice."
        ),
    },
    {
        "slug": "jobs",
        "title": "Jobs",
        "eyebrow": "UK topic · labour market",
        "heading": "What is happening to work, pay, and hiring?",
        "series": ("uk_unemployment_rate", "uk_vacancies",
                   "uk_average_weekly_earnings"),
        "hook": jobs_hook,
        "stands_note": (
            "Vacancies are a seasonally adjusted three-month average in "
            "thousands and earnings are £ per week in cash terms — neither is "
            "deflated here, and neither is annualised."
        ),
        "model": jobs_model,
        "run": jobs_run,
        "data_note": (
            "The labour market series are survey based and revised; the "
            "unemployment rate is the only one of the three that the satellite "
            "forecast touches."
        ),
    },
    {
        "slug": "rates",
        "title": "Rates and gilts",
        "eyebrow": "UK topic · policy rate and the gilt curve",
        "heading": "What do rates say — and what can this site honestly say back?",
        "series": ("uk_bank_rate", "uk_gilt_5y", "uk_gilt_10y", "uk_gilt_20y"),
        "hook": rates_hook,
        "stands_note": (
            "Bank of England daily observations, to the precision the Bank "
            "publishes them. Nothing is rounded on the way in or out, so the "
            "yields carry four decimal places."
        ),
        "model": rates_model,
        "run": rates_run,
        "data_note": (
            "The Bank publishes no announced next-release date for these "
            "series, so the column says so rather than guessing a schedule."
        ),
    },
    {
        "slug": "public-finances",
        "title": "Public finances",
        "eyebrow": "UK topic · borrowing and debt",
        "heading": "How much is being borrowed, and what can a model add?",
        "series": ("uk_public_sector_net_borrowing",
                   "uk_public_sector_net_debt_gdp"),
        "hook": public_finances_hook,
        "stands_note": public_finances_note,
        "model": public_finances_model,
        "run": public_finances_run,
        "data_note": (
            "Public-sector finance series are revised heavily and often; the "
            "snapshot column is the difference between a reproducible number "
            "and a moving one."
        ),
    },
    {
        "slug": "reform",
        "title": "Tax and benefit reform",
        "eyebrow": "UK topic · scoring a policy change",
        "heading": "What would a reform do — and how far can the models follow it?",
        "series": (),
        "hook": reform_hook,
        "stands": reform_stands,
        "model": reform_model,
        "run": reform_run,
        "data": reform_data,
    },
]


# ------------------------------------------------------------ the US's five
#
# Five, not six. The UK's public-finances topic has no US counterpart and this
# is a deliberate omission rather than an oversight: `data/vintages/` holds no
# US fiscal series at all — no federal balance, no debt-to-GDP — so layer 01
# of that page would have no number, no period and no vintage in it, and layer
# 02 no model either (obr-macro is UK-only, and neither US model outputs a
# fiscal balance). Every other page here can fill at least one layer from a
# dated artifact. A sixth tab leading to four empty layers would be a worse
# answer than an absent tab and a stated reason, so the reason is stated: on
# /economy/us, in the topic directory, where a reader comparing the two
# countries meets it.

US_TOPICS = [
    {
        "slug": "growth",
        "title": "Growth",
        "eyebrow": "US topic · output",
        "heading": "Is the US economy growing, and what can these models honestly say?",
        "series": ("us_real_gdp",),
        "cards": (("us_real_gdp", "yoy"), ("us_real_gdp", None)),
        "hook": us_growth_hook,
        "stands_note": us_growth_note,
        "model": us_growth_model,
        "run": us_growth_run,
        "data_note": (
            "BEA revises the national accounts three times in the quarter "
            "after a first estimate and again at annual and comprehensive "
            "revisions, so the snapshot date matters as much as the "
            "observation quarter. " + US_DATA_CLOSING
        ),
    },
    {
        "slug": "inflation",
        "title": "Inflation",
        "eyebrow": "US topic · prices",
        "heading": "Where are US prices now — and what is missing from this page?",
        "series": ("us_cpi",),
        "cards": (("us_cpi", "yoy"), ("us_cpi", None)),
        "hook": us_inflation_hook,
        "stands_note": us_inflation_note,
        "model": us_inflation_model,
        "run": us_inflation_run,
        "data_note": (
            "One series, where the UK inflation topic has two: no US core CPI "
            "is tracked in this store. " + US_DATA_CLOSING
        ),
    },
    {
        "slug": "jobs",
        "title": "Jobs",
        "eyebrow": "US topic · labor market",
        "heading": "What is happening to US work and hiring?",
        "series": ("us_unemployment_rate", "us_payroll_employment"),
        "cards": (
            ("us_unemployment_rate", None),
            ("us_payroll_employment", None),
            ("us_payroll_employment", "yoy"),
        ),
        "hook": us_jobs_hook,
        "stands_note": (
            "The unemployment rate is published as a rate and is shown as "
            "stored. Payroll employment is a level in thousands of persons: "
            "the headline reads it in millions and the year-on-year card is "
            "derived from the stored levels, neither of which is a "
            "transformation the publisher applied."
        ),
        "model": us_jobs_model,
        "run": us_jobs_run,
        "data_note": (
            "PAYEMS is revised twice after first publication and again at the "
            "annual benchmark, and UNRATE comes from a household survey with "
            "its own sampling error; the snapshot column is the difference "
            "between a reproducible number and a moving one. " + US_DATA_CLOSING
        ),
    },
    {
        "slug": "rates",
        "title": "Rates and Treasuries",
        "eyebrow": "US topic · policy rate and the Treasury curve",
        "heading": "What do US rates say — and what can this site honestly say back?",
        "series": ("us_federal_funds_rate", "us_treasury_10y"),
        "hook": us_rates_hook,
        "stands_note": (
            "Federal Reserve observations as FRED distributes them: FEDFUNDS "
            "is a monthly average of the effective rate and DGS10 a "
            "business-day constant-maturity quote. Nothing is rounded on the "
            "way in or out."
        ),
        "model": us_rates_model,
        "run": us_rates_run,
        "data_note": (
            "One monthly series and one daily series, so the two observation "
            "dates above never line up — that is the data, not a presentation "
            "choice. " + US_DATA_CLOSING
        ),
    },
    {
        "slug": "reform",
        "title": "Tax and benefit reform",
        "eyebrow": "US topic · scoring a policy change",
        "heading": "What would a US reform do — and how far can the models follow it?",
        "series": (),
        "hook": us_reform_hook,
        "stands": us_reform_stands,
        "model": us_reform_model,
        "run": us_reform_run,
        "data": us_reform_data,
    },
]

for _topic in UK_TOPICS:
    _topic["country"] = "uk"
for _topic in US_TOPICS:
    _topic["country"] = "us"

TOPICS = UK_TOPICS + US_TOPICS
TOPIC_BY_SLUG = {(topic["country"], topic["slug"]): topic for topic in TOPICS}


def topics_for(country: str) -> list[dict]:
    return [topic for topic in TOPICS if topic["country"] == country]


def hook(country: str, slug: str) -> str:
    return TOPIC_BY_SLUG[(country, slug)]["hook"]()


# --------------------------------------------------------------- page render

def scope_target(country: str, current: str | None) -> str:
    """Where the UK/US switch goes: the same kind of page, other country.

    The switch used to land on the country hub from everywhere, so a reader
    comparing the two inflation pages went topic -> hub -> topic. Here it is
    the counterpart of the page they are on, and it falls back to that
    country's data hub only when the counterpart does not exist — which is
    exactly the two UK-only cases, public finances and (on the US side) a
    scored record.
    """
    entry = COUNTRIES[country]
    if current is None:
        return entry["hub"]
    if current == "data":
        return entry["data"]
    topic = TOPIC_BY_SLUG.get((country, current))
    return topic_url(topic) if topic else entry["data"]


def subnav(country: str, current: str | None) -> str:
    """The one control shared by all fifteen pages of the Forecasts section.

    Same markup, same vocabulary, same order in both countries, so moving
    between a hub and a topic reads as one section rather than a page swap.
    Two groups: the scope switch (UK / US) and the page strip for the scope
    the reader is in.

    ``current`` is ``None`` on the section hub (/forecasts), ``"data"`` on the
    country data hub (/economy), or a topic slug. Overview and Data exist as
    tabs because the strip is a tab set and a tab set with nothing selected
    tells the reader they are nowhere; they are also the way back.

    The strip names pages, not in-page anchors. /forecasts used to carry its
    own anchor bar here and /economy a page bar, which is how one section
    ended up with two different controls in the same slot. The bands on
    /forecasts keep every id they had — /data and /notes still redirect onto
    them — they are simply no longer the section's navigation.

    The page the reader is on is the only element carrying
    ``aria-current="page"``. On a topic page the country scope link is an
    ancestor, not the current URL, so it takes ``aria-current="true"``.
    """
    entry = COUNTRIES[country]
    scope = []
    for code, other in COUNTRIES.items():
        target = scope_target(code, current)
        if code == country:
            state = "page" if target == _self_url(country, current) else "true"
        else:
            state = None
        attr = f' aria-current="{state}"' if state else ""
        scope.append(
            f'        <a class="model-tabs-link"{attr} '
            f'href="{target}">{other["label"]}</a>'
        )
    overview_attr = ' aria-current="page"' if current is None else ""
    data_attr = ' aria-current="page"' if current == "data" else ""
    links = [
        f'        <a class="model-tabs-link"{overview_attr} '
        f'href="{entry["hub"]}">Overview</a>',
        f'        <a class="model-tabs-link"{data_attr} '
        f'href="{entry["data"]}">Data</a>',
    ]
    for topic in topics_for(country):
        attr = ' aria-current="page"' if topic["slug"] == current else ""
        links.append(
            f'        <a class="model-tabs-link"{attr} '
            f'href="{topic_url(topic)}">{esc(topic["title"])}</a>'
        )
    return f"""  <nav class="economy-subnav" aria-label="Forecasts">
    <div class="economy-subnav-row">
      <div class="economy-subnav-scope">
        <span class="economy-subnav-label mono">Forecasts</span>
{chr(10).join(scope)}
      </div>
      <div class="economy-topics">
{chr(10).join(links)}
      </div>
    </div>
  </nav>"""


def _self_url(country: str, current: str | None) -> str:
    """The URL of the page ``subnav`` is being rendered into."""
    entry = COUNTRIES[country]
    if current is None:
        return entry["hub"]
    if current == "data":
        return entry["data"]
    return topic_url(TOPIC_BY_SLUG[(country, current)])


def page(topic: dict) -> str:
    slug = topic["slug"]
    url = topic_url(topic)
    lede = topic["hook"]()
    note = topic.get("stands_note")
    cards = topic.get("cards") or tuple((name, None) for name in topic["series"])
    stands_body = (
        topic["stands"]()
        if "stands" in topic
        else stands(cards, note() if callable(note) else note, topic["series"])
    )
    data_body = (
        topic["data"]()
        if "data" in topic
        else data_layer(topic["series"], topic["data_note"])
    )
    head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{esc(topic["title"])} — PolicyEngine Macro</title>
<meta name="description" content="{esc(lede)}" />
<link rel="canonical" href="{SITE}{url}" />
<meta property="og:type" content="website" />
<meta property="og:url" content="{SITE}{url}" />
<meta property="og:site_name" content="PolicyEngine Macro" />
<meta property="og:title" content="PolicyEngine Macro — {esc(topic["title"])}" />
<meta property="og:description" content="{esc(lede)}" />
<meta property="og:image" content="{SITE}/assets/og-image.png" />
<meta property="og:image:alt" content="PolicyEngine Macro — open economic models for the UK and US" />
<meta name="twitter:card" content="summary_large_image" />
<link rel="icon" type="image/svg+xml" href="/assets/policyengine-mark.svg" />
<meta name="theme-color" content="#FFFFFF" />
<link rel="stylesheet" href="/vendor/fonts/fonts.css" />
<link rel="stylesheet" href="/vendor/ui-kit-tokens.css" />
<link rel="stylesheet" href="/style.css?v=7" />
</head>
<body class="doc economy-page">
<a class="skip-link" href="#top">Skip to main content</a>
<div class="grain" aria-hidden="true"></div>

"""
    body = f"""<main id="top">
  <section class="hero model-hero">
    <div class="hero-inner">
      <p class="eyebrow reveal" style="--d:0">{esc(topic["eyebrow"])}</p>
      <h1 class="reveal page-title" style="--d:1">{esc(topic["heading"])}</h1>
      <p class="lede reveal" style="--d:2">{esc(lede)}</p>
    </div>
  </section>

{subnav(topic["country"], slug)}

{band("stands", "01", "where it stands", "The numbers, as the snapshot stores them.", stands_body)}

{band("model", "02", "what the models see", "The model view, and the same breath its limits.", topic["model"](), alt=True)}

{band("run", "03", "run it yourself", "Every number above is a command away.", topic["run"]())}

{band("data", "04", "the data behind it", "Source, coverage, and the immutable file.", data_body, alt=True)}
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
</body>
</html>
"""
    path = COUNTRIES[topic["country"]]["dir"] / slug / "index.html"
    return head + site_nav.header(path) + body


# --------------------------------------------------- economy page + sitemap

def directory_block(country: str) -> str:
    rows = []
    for topic in topics_for(country):
        rows.append(
            f'        <a href="{topic_url(topic)}">'
            f'<span>{esc(topic["hook"]())}</span>'
            f'<strong>{esc(topic["title"])}</strong></a>'
        )
    return "\n".join(rows)


# Words that would identify a US fiscal series if one were ever added to the
# store. Checked rather than assumed, so the reason the US has five topics
# cannot outlive the fact behind it.
US_FISCAL_HINTS = ("borrow", "deficit", "surplus", "net debt", "fiscal")


def us_public_finance_gap() -> str:
    """The sixth UK topic, and why /economy/us does not have it."""
    index = manifest()
    found = sorted(
        name
        for name, entry in index.items()
        if name.startswith("us_")
        and any(hint in entry["title"].lower() for hint in US_FISCAL_HINTS)
    )
    if found:
        raise RuntimeError(
            f"{', '.join(found)} looks like a US fiscal series in the store, "
            "but /economy/us still tells readers there is none — give public "
            "finances a US topic page or narrow US_FISCAL_HINTS"
        )
    obr = MODELS["obr-macro"]
    return f"""      <p class="callout">
        <strong>Five topics here, six on the UK side.</strong> The missing one
        is public finances, and it is missing for a reason worth stating: the
        vintage store holds no US fiscal series — no federal balance, no
        debt-to-GDP — so that page would open with no number, no observation
        period and no vintage. Nor is there a model to put beside one:
        <a href="/obr">obr-macro</a> is
        {registry_terms(obr["geography"])}-only, and neither US model reports a
        fiscal balance among its outputs. Filling it needs two things in this
        order — the FRED series added to the append-only fetcher so vintages
        accumulate, and a US model that answers a fiscal question. Until then
        the tab is absent rather than empty.
      </p>"""


def sitemap_block() -> str:
    return "\n".join(
        f"  <url><loc>{SITE}{topic_url(topic)}</loc>"
        "<priority>0.8</priority></url>"
        for topic in TOPICS
    )


def replace(text: str, name: str, value: str) -> str:
    start, end = f"<!-- {name}:begin -->", f"<!-- {name}:end -->"
    updated, count = re.subn(
        re.escape(start) + ".*?" + re.escape(end),
        lambda _: f"{start}\n{value}\n{end}",
        text,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError(f"expected one {name} block, found {count}")
    return updated


def rendered() -> list[tuple[Path, str]]:
    artifacts = [
        (COUNTRIES[topic["country"]]["dir"] / topic["slug"] / "index.html",
         page(topic))
        for topic in TOPICS
    ]
    # The topic cards and the shared bar on each data hub belong to this
    # generator. economy/build.py owns the readings and the provenance tables
    # on the same two pages and touches neither marker, so the two --check
    # gates never contend for the same region.
    platform = {"uk": uk_platform, "us": us_platform}
    for country, entry in COUNTRIES.items():
        data_hub = entry["data_page"].read_text()
        data_hub = replace(
            data_hub, entry["directory_marker"], directory_block(country)
        )
        data_hub = replace(data_hub, entry["nav_marker"], subnav(country, "data"))
        if country == "us":
            data_hub = replace(data_hub, "us-economy-gaps", us_public_finance_gap())
            data_hub = replace(
                data_hub, "us-economy-forecast-note", us_hub_forecast_note()
            )
        artifacts.append((entry["data_page"], data_hub))

        # The section hub carries the same bar and the platform band.
        # forecasts/score.py and data/build_page.py own other markers on the
        # UK one; none of the three regions overlap.
        section_hub = entry["hub_page"].read_text()
        section_hub = replace(
            section_hub, entry["hub_nav_marker"], subnav(country, None)
        )
        section_hub = replace(
            section_hub, entry["platform_marker"], platform[country]()
        )
        artifacts.append((entry["hub_page"], section_hub))
    artifacts.append(
        (SITEMAP, replace(SITEMAP.read_text(), "economy-topics", sitemap_block()))
    )
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    artifacts = rendered()
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path, content in artifacts
            if not path.exists() or content != path.read_text()
        ]
        if stale:
            print(f"{', '.join(stale)} stale; run python3 economy/topics.py")
            return 1
        print(f"{len(TOPICS)} topic pages ({len(topics_for('uk'))} UK, "
              f"{len(topics_for('us'))} US), both section hubs, both data "
              "hubs and the sitemap match committed data")
        return 0
    for path, content in artifacts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print(f"updated {len(TOPICS)} topic pages, both section hubs, both data "
          "hubs and the sitemap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
