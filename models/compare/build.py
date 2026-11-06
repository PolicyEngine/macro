#!/usr/bin/env python3
"""Generate /models/compare ("same question, every model") from results.json.

    python3 models/compare/build.py           write models/compare/index.html
    python3 models/compare/build.py --check   fail if the committed page is stale

The page is the one home for the cross-model comparison (macro#213): a
question selector, then for each question a one-sentence count of the
verdicts and one compact table: the sourced benchmark as the first row, then
per model only the headline numbers and a short verdict, with the run call,
full units, scaling, solver flags and issue links behind each row's Details
button. Small multiples of the stored impulse responses follow. Model
pages keep their own validation facts; rows link to them rather than repeat
them. Stdlib only.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import chartkit  # noqa: E402
import site_nav  # noqa: E402

PAGE = HERE / "index.html"
RESULTS = HERE / "results.json"
URL = "/models/compare"
ORIGIN = "https://policyengine-macro.vercel.app"
REPO_BLOB = "https://github.com/PolicyEngine/macro/blob/main/models/compare"

TITLE = "Same question, every model"
DESCRIPTION = (
    "Six macro questions put to every PolicyEngine Macro model on the same day: "
    "a 100bp rate rise and cut, a 25bp rise, 1% of GDP of spending, an income-tax "
    "rise and an energy shock, each answer next to a sourced benchmark and a verdict in words."
)

# Columns per question: (header, unit line under the header, cell key). The
# table shows only the headline per model; everything else (the run call, the
# rate path, full units and scaling, solver flags, issue links) sits in the
# row's Details panel, so no fact is dropped (macro#213).
GDP = ("Peak GDP", "% of GDP", "gdp")
INFL = ("Peak inflation", "pp, annual rate", "inflation")
COLUMNS = {
    "rate-up-100": (GDP, INFL, ("Timing", "", "timing"), ("GDP per pp-quarter", "% of GDP", "ppq")),
    "rate-down-100": (("Against the rise", "peak GDP, % of GDP: cut vs rise", "result"),),
    "rate-up-25": (("Against 100bp ÷ 4", "peak GDP per bp", "result"),),
    "spending": (("Multiplier", "GDP per unit spent", "multiplier"), GDP, INFL),
    "tax": (("Multiplier", "GDP per unit of tax", "multiplier"), GDP, INFL),
    "energy": (GDP, ("Peak price effect", "% on the CPI level", "inflation"),
               ("Policy rate", "", "result")),
}

# Full-text fields that move into the Details panel, in display order.
DETAIL_FIELDS = (
    ("experiment", "Experiment"), ("rate_path", "Rate path"), ("timing", "Timing"),
    ("multiplier", "Multiplier"), ("symmetry", "Against the rise"),
    ("linearity", "Against 100bp ÷ 4"), ("result", "What else moves"),
)

VERDICT_CLASS = {
    "plausible": "cmp-v-plausible",
    "plausible-in-model": "cmp-v-mixed",
    "off": "cmp-v-off",
    "questionable": "cmp-v-mixed",
    "unresolved": "cmp-v-open",
    "not-tested": "cmp-v-open",
}

VERDICT_WORD = {
    "plausible": "plausible", "plausible-in-model": "plausible in-model", "off": "off",
    "questionable": "questionable", "unresolved": "unresolved", "not-tested": "not tested (linear)",
}

NUMBER_WORD = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def load() -> dict:
    return json.loads(RESULTS.read_text())


def _validator():
    spec = importlib.util.spec_from_file_location("compare_battery", HERE / "run_battery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signed(value: float, digits: int | None = None) -> str:
    """A number with an explicit sign and a true minus."""
    if value == 0:
        return "0"
    text = f"{abs(value):.{digits}f}" if digits is not None else f"{abs(value):g}"
    return ("+" if value > 0 else "−") + text


def call_text(run: dict) -> str:
    args = ", ".join(
        f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in run["args"].items()
    )
    return f"{run['tool']}({args})" if run["kind"] != "committed" else f"{run['tool']}: {args}"


def model_head(data: dict, cell: dict) -> str:
    model = data["models"][cell["model"]]
    return (
        f'<a href="{model["href"]}">{esc(model["name"])}</a> '
        f'<span class="cmp-ctry">{model["country"]}</span>'
    )


def value_html(cell: dict, key: str) -> str:
    short = cell.get("short", {})
    if key in ("gdp", "inflation"):
        item = cell.get(key)
        if not item:
            return '<span class="cmp-na">not reported</span>'
        sub = short.get(key) or (f'at {item["when"]}' if item.get("when") else "")
        return (f'<strong class="cmp-num">{signed(item["value"])}</strong>'
                + (f'<span class="cmp-unit">{esc(sub)}</span>' if sub else ""))
    if key == "ppq":
        v = cell.get("gdp_per_ppq")
        if v is None:
            return '<span class="cmp-na">not reported</span>'
        return f'<strong class="cmp-num">{v:g}%</strong>'
    if key == "multiplier":
        text = short.get("multiplier")
        return f'<strong class="cmp-num">{esc(text)}</strong>' if text else '<span class="cmp-na">not reported</span>'
    text = short.get(key)
    return esc(text) if text else '<span class="cmp-na">not reported</span>'


def verdict_html(cell: dict) -> str:
    cls = VERDICT_CLASS[cell["verdict"]]
    return (f'<span class="cmp-verdict {cls}">{esc(cell["short"]["tag"])}</span>'
            f'<span class="cmp-why">{esc(cell["short"]["why"])}</span>')


def toggle(row_id: str, name: str) -> str:
    return (f'<button type="button" class="cmp-more" aria-expanded="true" aria-controls="{row_id}" hidden>'
            f'Details<span class="visually-hidden"> for {esc(name)}</span></button>')


def details_html(data: dict, q: dict, cell: dict) -> str:
    """Everything the headline row leaves out, with nothing dropped."""
    run = cell["run"]
    items = []
    source = f' <a href="{esc(run["source"])}">source</a>' if run.get("source") else ""
    items.append(("Run", f'{esc(run["label"])}{source}<code class="cmp-call">{esc(call_text(run))}</code>'))
    for key, label in DETAIL_FIELDS:
        if not cell.get(key):
            continue
        text = esc(cell[key])
        if key == "rate_path" and cell.get("pp_quarters") is not None:
            note = f", {esc(cell['pp_quarters_note'])}" if cell.get("pp_quarters_note") else ""
            text += f'; {cell["pp_quarters"]:g} pp-quarters{note}'
        items.append((label, text))
    for key, label in (("gdp", "Peak GDP"), ("inflation", "Peak price" if q["id"] == "energy" else "Peak inflation")):
        item = cell.get(key)
        if not item:
            continue
        bits = [f'{signed(item["value"])}', esc(item["units"])]
        if item.get("measure"):
            bits.append(esc(item["measure"]))
        if item.get("when"):
            bits.append(f'at {esc(item["when"])}')
        items.append((label, ", ".join(bits)))
    if cell.get("gdp_per_ppq") is not None:
        items.append(("GDP per pp-quarter", f'{cell["gdp_per_ppq"]:g}% of GDP per pp-quarter'))
    items.append(("Verdict", f'{esc(cell["verdict_label"])}. {esc(cell["reason"])}'))
    if cell.get("draws"):
        items.append(("Draws", esc(cell["draws"])))
    if cell.get("solver"):
        items.append(("Solver", f'<span class="cmp-solver">{esc(cell["solver"])}</span>'))
    links = []
    if cell.get("issue"):
        issue = data["issues"][cell["issue"]]
        links.append(f'<a href="{issue["url"]}">{esc(issue["label"])}</a>')
    if cell.get("link"):
        links.append(f'<a href="{cell["link"]["href"]}">{esc(cell["link"]["label"])}</a>')
    if links:
        items.append(("Open issue" if cell.get("issue") and not cell.get("link") else "See also", " · ".join(links)))
    return '<dl class="cmp-dl">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in items) + "</dl>"


def takeaway(data: dict, q: dict) -> str:
    """One neutral sentence built only from the verdicts, in hub order."""
    answered = [c for c in q["cells"] if c["status"] == "answered"]
    by_verdict: dict[str, list[str]] = {}
    for c in answered:
        by_verdict.setdefault(c["verdict"], []).append(data["models"][c["model"]]["name"])

    def join(xs: list[str]) -> str:
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]

    # Name the models behind each verdict, so "which answer holds up" is read
    # off this line instead of by scanning the table (r5 usability test, #220).
    verdicts = "; ".join(f"{VERDICT_WORD[v]}: {join(ns)}" for v, ns in by_verdict.items())
    none = [data["models"][c["model"]]["name"] for c in q["cells"] if c["status"] == "no_instrument"]
    text = (f"{NUMBER_WORD[len(answered)].capitalize()} of {NUMBER_WORD[len(q['cells'])]} models answer. "
            f"{verdicts[0].upper()}{verdicts[1:]}.")
    if none:
        names = none[0] if len(none) == 1 else ", ".join(none[:-1]) + " and " + none[-1]
        text += f" {names} {'has' if len(none) == 1 else 'have'} no instrument for it."
    return f'<p class="cmp-takeaway">{esc(text)}</p>'


def bench_rows(data: dict, q: dict, ncols: int) -> list[str]:
    rows = []
    if not q["benchmarks"]:
        return [f'<tr class="cmp-bench-row"><th scope="row" data-label="Benchmark">Benchmark</th>'
                f'<td colspan="{ncols + 2}" data-label="Benchmark">None sourced for this question.</td></tr>']
    for i, r in enumerate(q.get("benchmark_rows", [])):
        b = data["benchmarks"][r["benchmark"]]
        row_id = f'cmp-{q["id"]}-bench-{i}'
        tds = "".join(
            f'<td data-label="{esc(h)}{(", " + esc(u)) if u else ""}">'
            + (f'<span class="cmp-num">{esc(r[k])}</span>' if r.get(k) else '<span class="cmp-na">—</span>') + "</td>"
            for h, u, k in COLUMNS[q["id"]]
        )
        rows.append(
            f'<tr class="cmp-bench-row"><th scope="row" data-label="Benchmark">{esc(r["name"])} '
            f'<span class="cmp-ctry">{esc(b["country"])}</span></th>{tds}'
            f'<td data-label="Verdict"><span class="cmp-why">Reference, sourced</span></td>'
            f'<td class="cmp-more-cell" data-label="">{toggle(row_id, r["name"])}</td></tr>'
        )
        rows.append(
            f'<tr class="cmp-detail cmp-bench-detail" id="{row_id}"><td colspan="{ncols + 3}" data-label="">'
            f'<dl class="cmp-dl"><dt>Benchmark</dt><dd>{esc(b["label"])} ({esc(b["country"])}). {esc(b["text"])}</dd>'
            f'<dt>Source</dt><dd><a href="{esc(b["url"])}">{esc(b["source"])}</a></dd></dl></td></tr>'
        )
    return rows


def table(data: dict, q: dict) -> str:
    cols = COLUMNS[q["id"]]
    head = '<th scope="col">Model</th>' + "".join(
        f'<th scope="col">{esc(h)}' + (f'<span class="cmp-hunit">{esc(u)}</span>' if u else "") + "</th>"
        for h, u, _ in cols
    ) + '<th scope="col">Verdict</th><th scope="col"><span class="visually-hidden">Details</span></th>'
    rows = bench_rows(data, q, len(cols))
    for cell in q["cells"]:
        name = data["models"][cell["model"]]["name"]
        if cell["status"] == "no_instrument":
            rows.append(
                f'<tr class="cmp-none"><th scope="row" data-label="Model">{model_head(data, cell)}</th>'
                f'<td colspan="{len(cols) + 2}" data-label="Cannot answer">'
                f'<span class="cmp-verdict cmp-v-none">No instrument</span>'
                f'<span class="cmp-why">{esc(cell["reason"])}</span></td></tr>'
            )
            continue
        row_id = f'cmp-{q["id"]}-{cell["model"]}'
        tds = "".join(
            f'<td data-label="{esc(h)}{(", " + esc(u)) if u else ""}">{value_html(cell, k)}</td>' for h, u, k in cols
        )
        rows.append(
            f'<tr class="cmp-row"><th scope="row" data-label="Model">{model_head(data, cell)}</th>{tds}'
            f'<td data-label="Verdict">{verdict_html(cell)}</td>'
            f'<td class="cmp-more-cell" data-label="">{toggle(row_id, name)}</td></tr>'
        )
        rows.append(
            f'<tr class="cmp-detail" id="{row_id}"><td colspan="{len(cols) + 3}" data-label="">'
            f'{details_html(data, q, cell)}</td></tr>'
        )
    return (
        takeaway(data, q) + "\n"
        '<div class="table-scroll cmp-scroll">\n'
        f'<table class="cmp-table">\n<caption class="visually-hidden">{esc(q["title"])}: every model\'s answer, with the sourced benchmark first</caption>\n'
        f"<thead><tr>{head}</tr></thead>\n<tbody>\n" + "\n".join(rows) + "\n</tbody>\n</table>\n</div>"
    )


# --- small multiples -------------------------------------------------------

W, H = 320, 170
X0, X1, Y0, Y1 = 8, 312, 22, 146


def _ticks(lo: float, hi: float) -> list[float]:
    span = hi - lo
    raw = span / 3 if span else 1
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    first = math.floor(lo / step) * step
    out, v = [], first
    while v <= hi + step * 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    text = f"{abs(v):.3f}".rstrip("0").rstrip(".")
    return ("−" if v < 0 else "") + text


def panel(chart_id: str, title: str, unit: str, ys: list[float], band=None, band_label="") -> str:
    lo = min(ys + [0.0] + ([band[0], band[1]] if band else []))
    hi = max(ys + [0.0] + ([band[0], band[1]] if band else []))
    pad = (hi - lo) * 0.08 or 0.01
    lo, hi = lo - pad, hi + pad
    ticks = _ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])

    def y(v):
        return Y1 - (v - lo) / (hi - lo) * (Y1 - Y0)

    n = len(ys)

    def x(i):
        return X0 + i / (n - 1) * (X1 - X0)

    parts = [
        f'<svg class="vchart cmp-sm" data-chart="{chart_id}" viewBox="0 0 {W} {H + 18}" role="img" '
        f'aria-labelledby="{chart_id}-t {chart_id}-d">',
        f'<title id="{chart_id}-t">{esc(title)}</title>',
        f'<desc id="{chart_id}-d">{esc(unit)}, quarters 1 to {n}: '
        + ", ".join(_fmt(round(v, 3)) for v in ys)
        + (f". Shaded: {esc(band_label)}, {_fmt(band[0])} to {_fmt(band[1])}." if band else ".")
        + "</desc>",
    ]
    for t in ticks:
        cls = "cmp-zero" if abs(t) < 1e-12 else "cmp-grid"
        parts.append(f'<line class="{cls}" x1="{X0}" x2="{X1}" y1="{y(t):.1f}" y2="{y(t):.1f}" vector-effect="non-scaling-stroke"/>')
        parts.append(chartkit.ytick(X0, y(t) - 3, _fmt(t)))
    if band:
        top, bot = y(max(band)), y(min(band))
        parts.append(f'<rect class="cmp-band" x="{X0}" y="{top:.1f}" width="{X1 - X0}" height="{bot - top:.1f}"/>')
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(ys))
    parts.append(f'<polyline class="cmp-line" points="{pts}" fill="none" vector-effect="non-scaling-stroke"/>')
    last = n - 1
    for i in (0, (n - 1) // 2, last):
        parts.append(chartkit.xtick(x(i), Y1 + 18, f"q{i + 1}", 0 if i == 0 else (last if i == last else 1), last))
    parts.append("</svg>")
    legend = [("sw-band", esc(band_label))] if band else None
    return chartkit.figure("\n".join(parts), unit=esc(unit), legend=legend, keep_ratio=True,
                           wrap_class="cmp-fig")


def multiples(data: dict, q: dict) -> str:
    cells = [c for c in q["cells"] if c.get("path")]
    if not cells:
        return ""
    figs = []
    for cell in cells:
        model = data["models"][cell["model"]]
        p = cell["path"]
        band = band_label = None
        if cell.get("benchmark"):
            b = data["benchmarks"][cell["benchmark"]]
            band = (b["gdp_low"], b["gdp_high"])
            band_label = f'{b["label"]}: {b["gdp_units"]}'
        infl = [v * p["inflation_scale"] for v in p["inflation"]]
        infl_unit = "Inflation, " + p["inflation_units"].split(";")[0]
        if p["inflation_scale"] == 4:
            infl_unit = "Inflation, pp, annual rate (quarterly rate × 4)"
        base = f'cmp-{q["id"]}-{cell["model"]}'
        figs.append(
            f'<div class="cmp-sm-model"><h3>{esc(model["name"])}</h3>'
            + panel(f"{base}-gdp", f'{model["name"]}: GDP, {TITLE_Q[q["id"]]}', "GDP, % deviation", p["gdp"], band, band_label or "")
            + panel(f"{base}-infl", f'{model["name"]}: {"prices" if q["id"] == "energy" else "inflation"}, {TITLE_Q[q["id"]]}',
                    infl_unit if q["id"] != "energy" else "CPI level, % deviation", infl)
            + "</div>"
        )
    missing = [data["models"][c["model"]]["name"] for c in q["cells"]
               if c["status"] == "answered" and not c.get("path")]
    note = ""
    if missing:
        note = (f'<p class="cmp-sm-note">No stored path for {esc(", ".join(missing))}: '
                "those rows are peaks from the battery or committed outputs.</p>")
    return (
        '<figure class="cmp-sm-wrap">'
        f'<figcaption><strong>How the response unfolds, quarter by quarter.</strong> '
        "The paths behind the peaks and timing in the table; each panel has its own scale. "
        f'Source: <a href="{REPO_BLOB}/results.json">results.json</a>, hosted runs of 6 Nov 2026.</figcaption>'
        f'<div class="cmp-sm-grid">{"".join(figs)}</div>{note}</figure>'
    )


TITLE_Q = {
    "rate-up-100": "100bp rate rise",
    "rate-down-100": "100bp rate cut",
    "rate-up-25": "25bp rate rise",
    "spending": "spending shock",
    "tax": "income-tax rise",
    "energy": "oil-price shock",
}


def question(data: dict, q: dict, first: bool) -> str:
    notes = "".join(f'<p class="cmp-note">{esc(n)}</p>' for n in q["notes"])
    return (
        f'<section class="band cmp-q" id="q-{q["id"]}" data-q="{q["id"]}"'
        + ("" if first else " data-later")
        + ">\n"
        f'<div class="band-head" data-icon="table"><h2>{esc(q["title"])}</h2>'
        f'<p class="section-intro">{esc(q["experiment"])}</p></div>\n'
        + table(data, q) + "\n" + notes + "\n" + multiples(data, q)
        + "\n</section>"
    )


SCRIPT = """<script>
(function () {
  var chips = Array.from(document.querySelectorAll("[data-q-chip]"));
  var panels = Array.from(document.querySelectorAll("section[data-q]"));
  if (!chips.length) return;
  function show(id, push) {
    if (!panels.some(function (p) { return p.dataset.q === id; })) id = panels[0].dataset.q;
    panels.forEach(function (p) { p.hidden = p.dataset.q !== id; });
    chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.qChip === id)); });
    if (push) history.replaceState(null, "", "#q-" + id);
  }
  chips.forEach(function (c) {
    c.addEventListener("click", function () { show(c.dataset.qChip, true); });
  });
  function fromHash() { show((location.hash || "").replace("#q-", ""), false); }
  window.addEventListener("hashchange", fromHash);
  fromHash();
  document.querySelectorAll("button.cmp-more").forEach(function (b) {
    var row = document.getElementById(b.getAttribute("aria-controls"));
    if (!row) return;
    b.hidden = false;
    b.setAttribute("aria-expanded", "false");
    row.hidden = true;
    b.addEventListener("click", function () {
      var open = b.getAttribute("aria-expanded") !== "true";
      b.setAttribute("aria-expanded", String(open));
      row.hidden = !open;
    });
  });
})();
</script>"""


def body(data: dict) -> str:
    chips = "".join(
        f'<button type="button" class="chip-btn" data-q-chip="{q["id"]}" aria-controls="q-{q["id"]}" '
        f'aria-pressed="{"true" if i == 0 else "false"}">{esc(q["chip"])}</button>'
        for i, q in enumerate(data["questions"])
    )
    sections = "\n".join(question(data, q, i == 0) for i, q in enumerate(data["questions"]))
    cards = site_nav.where_next([
        ("/models#choose", "list", "Which model answers your question", "Pick a model by question and country"),
        ("/models#validation", "target", "How each model is checked", "The evidence behind every model"),
        (data["issue"], "data", "The battery and its method", "macro #213, with every call"),
    ])
    return f"""<main id="top">
  <section class="hero model-hero">
    <div class="hero-inner">
      <h1 class="reveal page-title" style="--d:1">{TITLE}</h1>
      <p class="lede reveal" style="--d:2">Six questions put to every macro model on {esc("6 Nov 2026")}, each answer next to a sourced benchmark where one exists. A model that cannot answer says why.</p>
    </div>
  </section>
  <nav class="model-tabs" aria-label="Models pages">
    <div class="model-tabs-row"></div>
  </nav>
  <section class="band cmp-pick" id="pick">
    <div class="band-head" data-icon="list"><h2>Pick a question</h2>
      <p class="section-intro">Models are in the hub order, not ranked. The sourced benchmark sits in the first row; each model row gives its peak effects and a verdict, and Details holds the run, full units and caveats.</p></div>
    <div class="router-row cmp-chips" role="group" aria-label="Question">{chips}</div>
    <details class="about cmp-howto"><summary>How to read the verdicts</summary>
      <p>Each verdict starts with one of six words: plausible, off, questionable, unresolved, not tested or no instrument; some add a qualifier (such as &ldquo;off, sign right&rdquo;), and each carries its reason and the open issue. These words grade one experiment; each model&rsquo;s overall standing uses the <a class="gloss-link" href="/glossary#verification-class">status vocabulary</a> on its model card. Results file version {esc(data["version"])}; <a href="{REPO_BLOB}/run_battery.py">how it is checked and regenerated</a>.</p></details>
  </section>
{sections}
{cards}
</main>"""


def page(data: dict) -> str:
    canonical = ORIGIN + URL
    shell = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{TITLE} — PolicyEngine Macro</title>
<meta name="description" content="{esc(DESCRIPTION)}" />
<link rel="canonical" href="{canonical}" />
<meta property="og:title" content="{TITLE} — PolicyEngine Macro" />
<meta property="og:description" content="{esc(DESCRIPTION)}" />
<meta property="og:image" content="{ORIGIN}/assets/og-image.png" />
<link rel="icon" type="image/svg+xml" href="/assets/policyengine-mark.svg" />
<meta name="theme-color" content="#FFFFFF" />
<link rel="stylesheet" href="/vendor/fonts/fonts.css" />
<link rel="stylesheet" href="/vendor/ui-kit-tokens.css" />
<link rel="stylesheet" href="{site_nav.STYLE_HREF}" />
</head>
<body class="doc models-page compare-page">
<a class="skip-link" href="#top">Skip to main content</a>
<header class="nav"></header>

{body(data)}
<footer class="foot foot-bar">
  <p class="footer-legal">© 2026 PolicyEngine. All rights reserved.</p>
  <nav class="footer-links" aria-label="PolicyEngine links">
  </nav>
</footer>
<script src="/reveal.js?v=2" defer></script>
{SCRIPT}
</body>
</html>
"""
    return site_nav.render(PAGE, shell)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = load()
    found = _validator().problems(data)
    if found:
        for line in found:
            print(f"FAIL results.json: {line}", file=sys.stderr)
        return 1
    out = page(data)
    if args.check:
        if not PAGE.exists() or PAGE.read_text() != out:
            print("FAIL models/compare/index.html is stale: run python3 models/compare/build.py", file=sys.stderr)
            return 1
        print("OK — models/compare/index.html current")
        return 0
    PAGE.write_text(out)
    print(f"wrote {PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
