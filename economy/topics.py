#!/usr/bin/env python3
"""Regenerate the topic-first entry pages under /economy/topics.

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
SITEMAP = ROOT / "sitemap.xml"
SITE = "https://policyengine-macro.vercel.app"

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


def listed(items: list[str]) -> str:
    """Join a registry list the way a sentence needs it."""
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def suffix(series: dict) -> str:
    return "%" if series["units"].lower().startswith("percent") else ""


def yoy(series: dict, periods: int) -> list[dict]:
    """Year-on-year percent change computed from the stored levels."""
    observations = series["observations"]
    return [
        {
            "period": row["period"],
            "value": 100 * (row["value"] / observations[index - periods]["value"] - 1),
        }
        for index, row in enumerate(observations)
        if index >= periods
    ]


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

def cli_commands() -> dict[str, set[str]]:
    """``pe-macro`` command names mapped to their declared long options.

    Parsed out of ``cli.py`` rather than imported, because importing the CLI
    would drag in click and the model packages. A command or flag this
    generator prints but the CLI does not declare is a hard failure.
    """
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

def stat_card(series: dict) -> str:
    now = latest(series)
    return f"""        <article class="economy-stat">
          <p class="economy-stat-label mono">{esc(label(series).upper())}</p>
          <p class="economy-stat-value">{esc(stored(now["value"]))}{suffix(series)}</p>
          <p class="economy-stat-change">{esc(series["units"])}</p>
          <dl>
            <div><dt>Observation</dt><dd>{esc(now["period"])}</dd></div>
            <div><dt>Vintage</dt><dd>{esc(series["vintage"])}</dd></div>
            <div><dt>Source</dt><dd><a href="{esc(series["url"])}">{esc(series["source"])} · {esc(series["cdid"])}</a></dd></div>
          </dl>
        </article>"""


def stands(names: tuple[str, ...], note: str) -> str:
    cards = "\n".join(stat_card(load(name)) for name in names)
    return f"""    <div class="economy-grid">
{cards}
    </div>
    <p class="economy-method">{note}</p>"""


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
        f"<a href=\"/olg\">og-uk</a> does report an interest rate, but only as part of a {esc(og['horizon'].split(';')[0])}, and it cannot answer a {esc(og['cannot_answer'][0])}. A long-run comparative static is not a market view.",
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
            "og+microsim", ", ".join(dynamic["geography"]).upper(),
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
        f"<a href=\"/olg\">og+microsim</a> goes further — {esc(dynamic['model_class'])} — but is {esc(dynamic['status'])}.",
        f"og+microsim also cannot answer {(cannot('og+microsim'))}.",
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
        {tool("dynamic_reform_impact")} for the og+microsim overlay.
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


# --------------------------------------------------------------- the six

TOPICS = [
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

TOPIC_BY_SLUG = {topic["slug"]: topic for topic in TOPICS}


def hook(slug: str) -> str:
    return TOPIC_BY_SLUG[slug]["hook"]()


# --------------------------------------------------------------- page render

def subnav(current: str) -> str:
    links = []
    for topic in TOPICS:
        attr = ' aria-current="page"' if topic["slug"] == current else ""
        links.append(
            f'        <a class="model-tabs-link"{attr} '
            f'href="/economy/topics/{topic["slug"]}">{esc(topic["title"])}</a>'
        )
    return f"""  <nav class="economy-subnav" aria-label="Economy topics">
    <div class="economy-subnav-row">
      <div class="economy-subnav-scope">
        <span class="economy-subnav-label mono">Topics</span>
        <a class="model-tabs-link" href="/economy">All UK data</a>
      </div>
      <div class="economy-topics">
{chr(10).join(links)}
      </div>
    </div>
  </nav>"""


def page(topic: dict) -> str:
    slug = topic["slug"]
    url = f"/economy/topics/{slug}"
    lede = topic["hook"]()
    note = topic.get("stands_note")
    stands_body = (
        topic["stands"]()
        if "stands" in topic
        else stands(topic["series"], note() if callable(note) else note)
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
<link rel="stylesheet" href="/style.css?v=3" />
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
      <p class="lede reveal" style="--d:3">
        Four layers, in order: what the data says, what the models see and
        cannot see, the command that reproduces it, and the dated file every
        number came from.
      </p>
    </div>
  </section>

{subnav(slug)}

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
    path = TOPICS_DIR / slug / "index.html"
    return head + site_nav.header(path) + body


# --------------------------------------------------- economy page + sitemap

def directory_block() -> str:
    rows = []
    for topic in TOPICS:
        rows.append(
            f'        <a href="/economy/topics/{topic["slug"]}">'
            f'<span>{esc(topic["hook"]())}</span>'
            f'<strong>{esc(topic["title"])}</strong></a>'
        )
    return "\n".join(rows)


def sitemap_block() -> str:
    return "\n".join(
        f"  <url><loc>{SITE}/economy/topics/{topic['slug']}</loc>"
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
        (TOPICS_DIR / topic["slug"] / "index.html", page(topic))
        for topic in TOPICS
    ]
    artifacts.append(
        (ECONOMY_PAGE,
         replace(ECONOMY_PAGE.read_text(), "economy-topics", directory_block()))
    )
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
        print(f"{len(TOPICS)} topic pages, the economy directory and the "
              "sitemap match committed data")
        return 0
    for path, content in artifacts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print(f"updated {len(TOPICS)} topic pages, the economy directory and the sitemap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
