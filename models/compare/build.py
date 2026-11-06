#!/usr/bin/env python3
"""Generate /models/compare ("same question, every model") from results.json.

    python3 models/compare/build.py           write models/compare/index.html
    python3 models/compare/build.py --check   fail if the committed page is stale

The page is the one home for the cross-model comparison (macro#213): a
question selector, then for each question one compact table (model, the run,
peak GDP, peak inflation, timing, the sourced benchmark, the verdict with its
reason and issue) and small multiples of the stored impulse responses. Model
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

# Columns per question. Each is (header, cell key). The monetary +100bp table
# carries the normalisation (rate path, pp-quarters, GDP per pp-quarter)
# because the "+100bp" runs do not share a rate path (macro#213 rule 1).
COLUMNS = {
    "rate-up-100": (("Rate path", "rate"), ("Peak GDP effect", "gdp"),
                    ("Peak inflation effect", "inflation"), ("Timing", "timing"),
                    ("GDP per pp-quarter", "ppq")),
    "rate-down-100": (("Peak GDP effect", "gdp"), ("Against the rise", "symmetry")),
    "rate-up-25": (("Against 100bp ÷ 4", "linearity"),),
    "spending": (("Experiment run", "experiment"), ("Multiplier", "multiplier"),
                 ("Peak GDP effect", "gdp"), ("Peak inflation effect", "inflation")),
    "tax": (("Experiment run", "experiment"), ("Multiplier", "multiplier"),
            ("Peak GDP effect", "gdp"), ("Peak inflation effect", "inflation")),
    "energy": (("Experiment run", "experiment"), ("Peak GDP effect", "gdp"),
               ("Peak price effect", "inflation"), ("What else moves", "result")),
}

VERDICT_CLASS = {
    "plausible": "cmp-v-plausible",
    "plausible-in-model": "cmp-v-mixed",
    "off": "cmp-v-off",
    "questionable": "cmp-v-mixed",
    "unresolved": "cmp-v-open",
    "not-tested": "cmp-v-open",
}


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


def model_cell(data: dict, cell: dict) -> str:
    model = data["models"][cell["model"]]
    head = (
        f'<a href="{model["href"]}">{esc(model["name"])}</a> '
        f'<span class="cmp-ctry">{model["country"]}</span>'
    )
    run = cell.get("run")
    if not run:
        return head
    source = ""
    if run.get("source"):
        source = f' <a href="{esc(run["source"])}">source</a>'
    return (
        f'{head}<span class="cmp-run">{esc(run["label"])}{source}</span>'
        f'<code class="cmp-call">{esc(call_text(run))}</code>'
    )


def value_html(cell: dict, key: str) -> str:
    if key in ("gdp", "inflation"):
        item = cell.get(key)
        if not item:
            return '<span class="cmp-na">not reported</span>'
        parts = [f'<strong class="cmp-num">{signed(item["value"])}</strong>',
                 f'<span class="cmp-unit">{esc(item["units"])}</span>']
        if item.get("measure"):
            parts.append(f'<span class="cmp-unit">{esc(item["measure"])}</span>')
        if item.get("when"):
            parts.append(f'<span class="cmp-unit">at {esc(item["when"])}</span>')
        return "".join(parts)
    if key == "rate":
        ppq = cell.get("pp_quarters")
        text = esc(cell.get("rate_path", ""))
        if ppq is not None:
            note = f", {esc(cell['pp_quarters_note'])}" if cell.get("pp_quarters_note") else ""
            text += f'<span class="cmp-unit">{ppq:g} pp-quarters{note}</span>'
        return text
    if key == "ppq":
        v = cell.get("gdp_per_ppq")
        if v is None:
            return '<span class="cmp-na">not reported</span>'
        return f'<strong class="cmp-num">{v:g}%</strong><span class="cmp-unit">of GDP per pp-quarter</span>'
    text = cell.get(key)
    return esc(text) if text else '<span class="cmp-na">not reported</span>'


def verdict_html(data: dict, cell: dict) -> str:
    cls = VERDICT_CLASS[cell["verdict"]]
    out = [f'<span class="cmp-verdict {cls}">{esc(cell["verdict_label"])}</span>',
           f'<span class="cmp-reason">{esc(cell["reason"])}</span>']
    if cell.get("solver"):
        out.append(f'<span class="cmp-solver">Solver: {esc(cell["solver"])}</span>')
    links = []
    if cell.get("issue"):
        issue = data["issues"][cell["issue"]]
        links.append(f'<a href="{issue["url"]}">{esc(issue["label"])}</a>')
    if cell.get("link"):
        links.append(f'<a href="{cell["link"]["href"]}">{esc(cell["link"]["label"])}</a>')
    if links:
        out.append(f'<span class="cmp-links">{" · ".join(links)}</span>')
    return "".join(out)


def table(data: dict, q: dict) -> str:
    cols = COLUMNS[q["id"]]
    heads = ["Model and run"] + [h for h, _ in cols] + ["Verdict"]
    rows = []
    for cell in q["cells"]:
        if cell["status"] == "no_instrument":
            rows.append(
                f'<tr class="cmp-none"><th scope="row" data-label="Model">{model_cell(data, cell)}</th>'
                f'<td colspan="{len(cols) + 1}" data-label="Cannot answer">'
                f'<span class="cmp-verdict cmp-v-none">No instrument</span>'
                f'<span class="cmp-reason">{esc(cell["reason"])}</span></td></tr>'
            )
            continue
        tds = "".join(
            f'<td data-label="{esc(h)}">{value_html(cell, k)}</td>' for h, k in cols
        )
        rows.append(
            f'<tr><th scope="row" data-label="Model">{model_cell(data, cell)}</th>{tds}'
            f'<td data-label="Verdict">{verdict_html(data, cell)}</td></tr>'
        )
    head = "".join(f'<th scope="col">{esc(h)}</th>' for h in heads)
    return (
        '<div class="table-scroll cmp-scroll">\n'
        f'<table class="cmp-table">\n<caption class="visually-hidden">{esc(q["title"])}: every model\'s answer</caption>\n'
        f"<thead><tr>{head}</tr></thead>\n<tbody>\n" + "\n".join(rows) + "\n</tbody>\n</table>\n</div>"
    )


def benchmarks(data: dict, q: dict) -> str:
    if not q["benchmarks"]:
        return ('<div class="cmp-bench"><p class="cmp-bench-h">Benchmark</p>'
                '<p>None sourced for this question.</p></div>')
    items = []
    for bid in q["benchmarks"]:
        b = data["benchmarks"][bid]
        items.append(
            f'<li><strong>{esc(b["label"])}</strong> ({esc(b["country"])}). {esc(b["text"])} '
            f'<a href="{esc(b["url"])}">{esc(b["source"])}</a></li>'
        )
    return ('<div class="cmp-bench"><p class="cmp-bench-h">Benchmark range</p>'
            f'<ul>{"".join(items)}</ul></div>')


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
        + table(data, q) + "\n" + benchmarks(data, q) + "\n" + notes + "\n" + multiples(data, q)
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
      <p class="section-intro">Models are in the hub order, not ranked. Each row gives the run, the peak effects, a sourced benchmark and a verdict in words.</p></div>
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
