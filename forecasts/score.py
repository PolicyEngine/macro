#!/usr/bin/env python3
"""Score the archived forecast rounds against realised outturns.

Run:  python3 forecasts/score.py            # rebuild forecasts/scorecard.json
      python3 forecasts/score.py --check    # exit 1 if scorecard.json is stale

Reads ``rounds/*/*.json`` (immutable) and ``outturns.json`` (mutable, revised),
and writes ``scorecard.json``, which the page builder renders. This script never
writes under ``rounds/``.

What it deliberately does not do
--------------------------------
It does not compute a headline accuracy number until there is something to
compute one from. With no scored periods the scorecard reports zero, states the
first date on which a score becomes possible, and the page says so plainly. A
track record that reports an impressive figure derived from one observation is
worse than an empty one, because the empty one is honest.

Errors are signed (forecast minus outturn) as well as absolute, because a model
that is always 0.4pp high is a different problem from one that is 0.4pp off in
random directions, and the mean absolute error hides the difference.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
ROUNDS = HERE / "rounds"
OUTTURNS = HERE / "outturns.json"
SCORECARD = HERE / "scorecard.json"
PAGE = HERE / "index.html"
LATEST = ROOT / "data" / "latest"

# Series behind the naive random-walk baseline: the last value observed at the
# round's data edge, held flat at every horizon. Values are read from the
# current data/latest vintage, so revisions since the round was archived can
# differ from what a real-time forecaster saw — the scorecard says so.
NAIVE_SERIES = {
    "cpi": ("uk_cpi_yoy.json", "level"),
    "gdp": ("uk_gdp_cvm.json", "yoy"),
    "unemployment": ("uk_unemployment_rate.json", "level"),
}

NAIVE_NOTE = (
    "Naive baseline is a random walk: the last outturn available at the "
    "round's data edge, held flat. Read from the current data vintage, not "
    "the real-time one, so revisions can flatter or hurt it slightly."
)


def _quarter_shift(period: str, back: int) -> str:
    year, q = int(period[:4]), int(period[5])
    idx = year * 4 + (q - 1) - back
    return f"{idx // 4}Q{idx % 4 + 1}"


def naive_random_walk(variable: str, data_edge: str) -> float | None:
    """Last observed value at the data edge (y/y growth for GDP levels)."""
    spec = NAIVE_SERIES.get(variable)
    if spec is None:
        return None
    fname, transform = spec
    path = LATEST / fname
    if not path.exists():
        return None
    obs = {
        o["period"]: o["value"]
        for o in json.loads(path.read_text())["observations"]
    }
    if transform == "level":
        return obs.get(data_edge)
    if transform == "yoy":
        now, prev = obs.get(data_edge), obs.get(_quarter_shift(data_edge, 4))
        if now is None or prev is None:
            return None
        return (now / prev - 1.0) * 100.0
    return None

REPO_BLOB = "https://github.com/PolicyEngine/macro/blob/main"


def load_rounds() -> list[dict]:
    rounds = []
    for path in sorted(ROUNDS.glob("*/*.json")):
        data = json.loads(path.read_text())
        data["_path"] = str(path.relative_to(ROOT))
        rounds.append(data)
    return rounds


def latest_outturns(observations: list[dict]) -> dict[tuple[str, str], dict]:
    """Latest vintage per (period, variable). Later vintages supersede earlier."""
    best: dict[tuple[str, str], dict] = {}
    for obs in observations:
        key = (obs["period"], obs["variable"])
        current = best.get(key)
        if current is None or obs.get("vintage", "") >= current.get("vintage", ""):
            best[key] = obs
    return best


def score_round(rnd: dict, outturns: dict[tuple[str, str], dict]) -> dict:
    entries = []
    for period, block in sorted(rnd["forecast"].items()):
        for variable, stats in sorted(block.items()):
            obs = outturns.get((period, variable))
            if obs is None:
                continue

            # A forecast only counts if it was archived before the outturn was
            # published. A round archived after the release still gets listed
            # under rounds/, but its already-answered periods are never scored:
            # scoring them would launder hindsight into the track record.
            archived = (rnd.get("archived_utc") or "")[:10]
            vintage = obs.get("vintage") or ""
            if archived and vintage and archived > vintage:
                continue

            point = stats["median"]
            actual = obs["value"]
            error = point - actual
            naive = naive_random_walk(variable, rnd["information_set"]["data_edge"])
            official = official_paths().get(variable, {}).get(period)

            entries.append(
                {
                    "period": period,
                    "variable": variable,
                    "forecast": point,
                    "outturn": actual,
                    "outturn_vintage": obs.get("vintage"),
                    "error": error,
                    "abs_error": abs(error),
                    # Naive random-walk baseline (see NAIVE_NOTE). None when no
                    # series is mapped for the variable.
                    "naive_rw": naive,
                    "naive_abs_error": (
                        abs(naive - actual) if naive is not None else None
                    ),
                    "beats_naive": (
                        abs(error) < abs(naive - actual)
                        if naive is not None
                        else None
                    ),
                    # Official forecaster's number for the same period, where a
                    # sourced path is stored (currently the March 2026 EFO).
                    "official": official,
                    "official_label": OFFICIAL_LABEL if official is not None else None,
                    "official_abs_error": (
                        abs(official - actual) if official is not None else None
                    ),
                    # Band coverage is the honest test of a fan chart: a model
                    # whose 68% band contains the outturn 68% of the time is
                    # calibrated, however large its point errors are.
                    "in_68": stats["lo68"] <= actual <= stats["hi68"],
                    "in_90": stats["lo90"] <= actual <= stats["hi90"],
                }
            )

    by_variable: dict[str, dict] = {}
    for variable in sorted({e["variable"] for e in entries}):
        rows = [e for e in entries if e["variable"] == variable]
        by_variable[variable] = {
            "n": len(rows),
            "mae": sum(r["abs_error"] for r in rows) / len(rows),
            "bias": sum(r["error"] for r in rows) / len(rows),
            "coverage_68": sum(r["in_68"] for r in rows) / len(rows),
            "coverage_90": sum(r["in_90"] for r in rows) / len(rows),
        }
        with_naive = [r for r in rows if r["naive_abs_error"] is not None]
        if with_naive:
            by_variable[variable]["mae_naive_rw"] = sum(
                r["naive_abs_error"] for r in with_naive
            ) / len(with_naive)
            by_variable[variable]["beats_naive"] = sum(
                r["beats_naive"] for r in with_naive
            )

    return {
        "round_id": rnd["round_id"],
        "model": rnd["model"]["name"],
        "data_edge": rnd["information_set"]["data_edge"],
        "archived_utc": rnd.get("archived_utc"),
        "path": rnd["_path"],
        "periods_forecast": len(rnd["forecast"]),
        "periods_scored": len({e["period"] for e in entries}),
        "entries": entries,
        "by_variable": by_variable,
    }


def build() -> dict:
    rounds = load_rounds()
    outturn_doc = json.loads(OUTTURNS.read_text())
    outturns = latest_outturns(outturn_doc.get("observations", []))

    scored = [score_round(r, outturns) for r in rounds]
    total_scored = sum(s["periods_scored"] for s in scored)

    # The earliest period still waiting on any variable. Checked per variable,
    # not per period: CPI lands roughly six weeks before the quarterly GDP
    # estimate, so a period with one of the two in is not finished.
    pending = sorted(
        {
            period
            for r in rounds
            for period, block in r["forecast"].items()
            if not all((period, v) in outturns for v in block)
        }
    )

    return {
        "_comment": "Generated by forecasts/score.py — do not edit by hand.",
        "rounds": len(rounds),
        "periods_scored": total_scored,
        "next_period_to_score": pending[0] if pending else None,
        "pending_detail": (
            {
                "period": pending[0],
                "variables": sorted(
                    {
                        v
                        for r in rounds
                        for v in r["forecast"].get(pending[0], {})
                        if (pending[0], v) not in outturns
                    }
                ),
            }
            if pending
            else None
        ),
        "naive_note": NAIVE_NOTE,
        "status": (
            "accumulating — no forecast period has an outturn yet"
            if total_scored == 0
            else f"{total_scored} forecast period(s) scored"
        ),
        "detail": scored,
    }


# ------------------------------------------------- model vs official forecast

EFO_CSV = ROOT / "papers" / "obr-macro" / "figures" / "fig_anchored_data.csv"
EFO_CPI_CSV = ROOT / "papers" / "obr-macro" / "figures" / "efo_march_2026_cpi.csv"
SVAR_ROUND = ROUNDS / "2026-07-21" / "boe-svar.json"

OFFICIAL_LABEL = "OBR March 2026 EFO"


def efo_gdp_yoy() -> dict[str, float]:
    """OBR March 2026 EFO real GDP y/y growth, derived from the level path."""
    import csv

    levels: dict[str, float] = {}
    with EFO_CSV.open() as fh:
        for row in csv.DictReader(fh):
            levels[row[""]] = float(row["GDPM_efo"])
    return {
        period: (levels[period] / levels[_quarter_shift(period, 4)] - 1.0) * 100.0
        for period in levels
        if _quarter_shift(period, 4) in levels
    }


def efo_cpi_yoy() -> dict[str, float]:
    """OBR March 2026 EFO CPI y/y path (Table 1.7, transcribed with source)."""
    import csv

    with EFO_CPI_CSV.open() as fh:
        body = [line for line in fh if not line.startswith("#")]
    return {
        row["quarter"]: float(row["cpi_yoy_pct"]) for row in csv.DictReader(body)
    }


BOE_MPR_CSV = HERE / "official" / "boe_mpr_feb_2026_central.csv"
SEF_CSV = HERE / "official" / "boe_sef_april_2026.csv"

BOE_LABEL = "BoE Feb 2026 MPR"


def _official_csv(path: Path) -> dict[str, dict[str, float]]:
    """Read a quarter,cpi_yoy_pct,gdp_yoy_pct file with # comment headers."""
    import csv

    with path.open() as fh:
        body = [line for line in fh if not line.startswith("#")]
    paths: dict[str, dict[str, float]] = {"cpi": {}, "gdp": {}}
    for row in csv.DictReader(body):
        for var, col in (("cpi", "cpi_yoy_pct"), ("gdp", "gdp_yoy_pct")):
            if row[col]:
                paths[var][row["quarter"]] = float(row[col])
    return paths


def boe_mpr_paths() -> dict[str, dict[str, float]]:
    """BoE February 2026 MPR central projection (transcribed with source)."""
    return _official_csv(BOE_MPR_CSV)


_OFFICIAL_CACHE: dict[str, dict[str, float]] | None = None
_BOE_CACHE: dict[str, dict[str, float]] | None = None


def official_paths() -> dict[str, dict[str, float]]:
    global _OFFICIAL_CACHE
    if _OFFICIAL_CACHE is None:
        _OFFICIAL_CACHE = {"gdp": efo_gdp_yoy(), "cpi": efo_cpi_yoy()}
    return _OFFICIAL_CACHE


def boe_paths() -> dict[str, dict[str, float]]:
    global _BOE_CACHE
    if _BOE_CACHE is None:
        _BOE_CACHE = boe_mpr_paths()
    return _BOE_CACHE


_SEF_CACHE: dict[str, dict[str, float]] | None = None


def sef_paths() -> dict[str, dict[str, float]]:
    global _SEF_CACHE
    if _SEF_CACHE is None:
        _SEF_CACHE = _official_csv(SEF_CSV)
    return _SEF_CACHE


def build_vs_official(variable: str) -> list[dict]:
    """SVAR archived medians beside the EFO path, on shared quarters."""
    rnd = json.loads(SVAR_ROUND.read_text())
    efo = official_paths()[variable]
    rows = []
    for period in sorted(rnd["forecast"]):
        if period not in efo or variable not in rnd["forecast"][period]:
            continue
        g = rnd["forecast"][period][variable]
        rows.append(
            {
                "period": period,
                "median": g["median"],
                "lo68": g["lo68"],
                "hi68": g["hi68"],
                "efo": efo[period],
                "boe": boe_paths()[variable].get(period),
                "sef": sef_paths()[variable].get(period),
            }
        )
    return rows


# Per-variable presentation of the model-vs-official comparison.
VS_OFFICIAL_SPECS = {
    "gdp": {
        "chart_id": "svar-vs-efo",
        "name": "UK real GDP growth",
        "series": "UK real GDP, year-on-year growth, percent",
        "source_note": (
            "EFO path derived from the March 2026 EFO real-GDP level path stored "
            "in <code>papers/obr-macro/figures/fig_anchored_data.csv</code>"
        ),
    },
    "cpi": {
        "chart_id": "svar-vs-efo-cpi",
        "name": "UK CPI inflation",
        "series": "UK CPI, year-on-year inflation, percent",
        "source_note": (
            "EFO path from Table 1.7 of the March 2026 EFO detailed economy "
            "tables, stored in "
            "<code>papers/obr-macro/figures/efo_march_2026_cpi.csv</code>"
        ),
    },
}


def render_vs_official_variable(variable: str) -> str:
    """Chart + table: archived boe-svar path with 68% band vs March 2026 EFO."""
    rows = build_vs_official(variable)
    spec = VS_OFFICIAL_SPECS[variable]
    chart_id = spec["chart_id"]
    if not rows:
        return "      <!-- no overlapping quarters -->"

    # SVG geometry mirrors the validation-page vchart conventions.
    width, height = 760, 300
    left, right, top, bottom = 56, 16, 34, 40
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [v for r in rows for v in (r["lo68"], r["hi68"], r["efo"])]
    lo = min(0.0, min(values))
    hi = max(values)
    span = (hi - lo) or 1.0
    lo -= span * 0.08
    hi += span * 0.08
    span = hi - lo

    def x(i: int) -> float:
        return left + plot_w * i / (len(rows) - 1)

    def y(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / span)

    band = " ".join(f"{x(i):.1f},{y(r['hi68']):.1f}" for i, r in enumerate(rows))
    band += " " + " ".join(
        f"{x(i):.1f},{y(r['lo68']):.1f}" for i, r in reversed(list(enumerate(rows)))
    )
    median = " ".join(f"{x(i):.1f},{y(r['median']):.1f}" for i, r in enumerate(rows))
    efo = " ".join(f"{x(i):.1f},{y(r['efo']):.1f}" for i, r in enumerate(rows))

    gridlines, ticks = [], []
    step = 0.5
    v = (int(lo / step)) * step
    while v <= hi:
        if v >= lo:
            gridlines.append(
                f'          <line class="vc-grid" x1="{left}" y1="{y(v):.1f}" '
                f'x2="{width - right}" y2="{y(v):.1f}"/>'
            )
            ticks.append(
                f'          <text class="vc-tick" x="{left - 8}" y="{y(v) + 4:.1f}" '
                f'text-anchor="end">{v:g}</text>'
            )
        v += step
    xticks = [
        f'          <text class="vc-tick" x="{x(i):.1f}" y="{height - 14}" '
        f'text-anchor="middle">{r["period"]}</text>'
        for i, r in enumerate(rows)
    ]

    svg = "\n".join(
        [
            '      <figure class="vchart-figure">',
            f'        <svg class="vchart" data-chart="{chart_id}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-labelledby="{chart_id}-t {chart_id}-d">',
            f'          <title id="{chart_id}-t">boe-svar {spec["name"]} forecast vs '
            "OBR March 2026 EFO</title>",
            f'          <desc id="{chart_id}-d">Line chart of {spec["series"]}. '
            "The boe-svar archived median with its 68 percent band is shown beside the OBR "
            "March 2026 EFO path over the overlapping quarters.</desc>",
            *gridlines,
            *ticks,
            f'          <polygon class="vc-band68" points="{band}"/>',
            f'          <polyline class="vc-s1" points="{median}"/>',
            f'          <polyline class="vc-s2" points="{efo}"/>',
            *xticks,
            f'          <text class="vc-lab" x="{left}" y="{top - 14}">boe-svar median '
            "(68% band)</text>",
            f'          <text class="vc-lab vc-lab2" x="{width - right}" y="{top - 14}" '
            'text-anchor="end">OBR March 2026 EFO</text>',
            "        </svg>",
            f"        <figcaption>{spec['series']}. boe-svar medians and 68% bands "
            f"from the archived 2026-07-21 round; {spec['source_note']}.</figcaption>",
            "      </figure>",
        ]
    )

    table = [
        '      <div class="table-scroll">',
        "        <table>",
        f"          <caption>Model vs official forecast, {spec['name']}, year on "
        f"year. {spec['source_note']}; the boe-svar medians are from the archived "
        "2026-07-21 round.</caption>",
        '          <thead><tr><th scope="col">Quarter</th><th scope="col">boe-svar '
        'median</th><th scope="col">68% band</th><th scope="col">OBR March 2026 EFO'
        '</th><th scope="col">BoE Feb 2026 MPR</th>'
        '<th scope="col">Consensus (SEF, Apr 2026)</th></tr></thead>',
        "          <tbody>",
    ]
    for r in rows:
        boe = f"{r['boe']:.1f}%" if r["boe"] is not None else "—"
        sef = f"{r['sef']:.1f}%" if r["sef"] is not None else "—"
        table.append(
            f'          <tr><th scope="row">{esc(r["period"])}</th>'
            f"<td>{r['median']:.1f}%</td>"
            f"<td>{r['lo68']:.1f}% to {r['hi68']:.1f}%</td>"
            f"<td>{r['efo']:.1f}%</td>"
            f"<td>{boe}</td>"
            f"<td>{sef}</td></tr>"
        )
    table += [
        "          </tbody>",
        "        </table>",
        "      </div>",
        '      <p class="forecast-note">BoE column is the February 2026 MPR '
        "central projection (the April 2026 Report published scenarios rather "
        "than a central path), from the Bank's published projections databank "
        "(<code>forecasts/official/boe_mpr_feb_2026_central.csv</code>). "
        "Consensus is the average of outside forecasters' central projections "
        "in the Bank's Survey of External Forecasters as of 16 April 2026, "
        "published at fixed one-, two- and three-year-ahead quarters only "
        "(<code>forecasts/official/boe_sef_april_2026.csv</code>). "
        "The columns were fixed at different dates on different information "
        "sets.</p>",
    ]
    return svg + "\n" + "\n".join(table)


# ---------------------------------------------------------------- page

VARIABLE_LABELS = {"gdp": "UK real GDP, y/y", "cpi": "UK CPI, y/y"}

def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_status(card: dict) -> str:
    """Visual record totals without turning a one-period sample into a claim."""
    rounds = card["rounds"]
    scored = card["periods_scored"]
    entries = [
        entry
        for detail in card["detail"]
        for entry in detail["entries"]
    ]
    latest_entry = sorted(entries, key=lambda entry: entry["period"])[-1] if entries else None
    latest_error = (
        f"{latest_entry['abs_error']:.2f}pp" if latest_entry else "Awaiting outturn"
    )
    lines = [
        '      <div class="forecast-summary" aria-label="Current forecast record">',
        f"        <article><strong>{rounds}</strong><span>Archived "
        f"round{'' if rounds == 1 else 's'}</span></article>",
        f"        <article><strong>{scored}</strong><span>Scored "
        f"period{'' if scored == 1 else 's'}</span></article>",
        f"        <article><strong>{latest_error}</strong><span>Latest absolute "
        "error</span></article>",
        "      </div>",
        '      <p class="forecast-next">',
    ]
    pending = card.get("pending_detail")
    if pending:
        who = ", ".join(f"{VARIABLE_LABELS.get(v, v)}" for v in pending["variables"])
        lines.append(
            f"        <strong>Next due:</strong> {esc(pending['period'])} "
            f"({esc(who)}), which lands when the ONS publishes it."
        )
    else:
        lines.append("        Every archived period now has an outturn.")
    lines.append("      </p>")
    return "\n".join(lines)


def render_rounds(card: dict) -> str:
    rows = ['      <div class="forecast-round-list">']
    for detail in card["detail"]:
        href = f"{REPO_BLOB}/{detail['path']}"
        label = "/".join(Path(detail["path"]).parts[-2:])
        rows.append(
            "        <article class=\"forecast-round\">\n"
            f"          <div><span class=\"mono\">{esc(detail['round_id'])}</span>"
            f"<strong>{esc(detail['model'])}</strong></div>\n"
            "          <dl>\n"
            f"            <div><dt>Data edge</dt><dd>{esc(detail['data_edge'])}</dd></div>\n"
            f"            <div><dt>Periods</dt><dd>{detail['periods_forecast']}</dd></div>\n"
            f"            <div><dt>Scored</dt><dd>{detail['periods_scored']}</dd></div>\n"
            "          </dl>\n"
            f"          <a class=\"mono\" href=\"/{esc(detail['path'])}\" download>"
            f"Download artifact · <code>{esc(label)}</code> →</a>\n"
            f"          <a class=\"mono\" href=\"{href}\">"
            "Open on GitHub with commit history →</a>\n"
            "        </article>"
        )
    rows.append("      </div>")
    return "\n".join(rows)


def render_results(card: dict) -> str:
    """The scored entries. Absent entirely until something has been scored."""
    rows = [
        (detail, entry)
        for detail in card["detail"]
        for entry in detail["entries"]
    ]
    if not rows:
        return "      <!-- nothing scored yet -->"

    body = ['      <div class="forecast-result-list">']
    for detail, e in sorted(rows, key=lambda r: (r[1]["period"], r[1]["variable"])):
        band = "68%" if e["in_68"] else ("90%" if e["in_90"] else "outside 90%")
        naive = e.get("naive_rw")
        official = e.get("official")
        scale = max(
            abs(e["forecast"]),
            abs(e["outturn"]),
            abs(naive) if naive is not None else 0.0,
            abs(official) if official is not None else 0.0,
            1.0,
        )
        forecast_width = abs(e["forecast"]) / scale * 100
        outturn_width = abs(e["outturn"]) / scale * 100
        naive_row = ""
        naive_footer = ""
        if naive is not None:
            naive_width = abs(naive) / scale * 100
            naive_row = (
                f"            <div><span>Naive</span>"
                f"<i class=\"forecast-naive\" style=\"width:{naive_width:.1f}%\"></i>"
                f"<strong>{naive:.2f}%</strong></div>\n"
            )
            verdict = "beats" if e["beats_naive"] else "does not beat"
            naive_footer = (
                f"<span>{verdict} naive error "
                f"<strong>{e['naive_abs_error']:.2f}pp</strong></span>"
            )
        official_row = ""
        official_footer = ""
        if official is not None:
            official_width = abs(official) / scale * 100
            official_row = (
                f"            <div><span>Official</span>"
                f"<i class=\"forecast-official\" style=\"width:{official_width:.1f}%\"></i>"
                f"<strong>{official:.2f}%</strong></div>\n"
            )
            official_footer = (
                f"<span>{esc(e['official_label'])} error "
                f"<strong>{e['official_abs_error']:.2f}pp</strong></span>"
            )
        body.append(
            "        <article class=\"forecast-result\">\n"
            "          <header>\n"
            f"            <div><span class=\"mono\">{esc(e['period'])}</span>"
            f"<h3>{esc(VARIABLE_LABELS.get(e['variable'], e['variable']))}</h3></div>\n"
            f"            <span class=\"forecast-band\">Inside {esc(band)} band</span>\n"
            "          </header>\n"
            "          <div class=\"forecast-result-plot\" "
            f"aria-label=\"Forecast {e['forecast']:.2f} percent; outturn {e['outturn']:.2f} percent\">\n"
            f"            <div><span>Forecast</span><i style=\"width:{forecast_width:.1f}%\"></i>"
            f"<strong>{e['forecast']:.2f}%</strong></div>\n"
            f"            <div><span>Outturn</span><i style=\"width:{outturn_width:.1f}%\"></i>"
            f"<strong>{e['outturn']:.2f}%</strong></div>\n"
            + naive_row
            + official_row
            + "          </div>\n"
            f"          <footer><span>Error <strong>{e['error']:+.2f}pp</strong></span>"
            f"{naive_footer}"
            f"{official_footer}"
            f"<span>Round {esc(detail['round_id'])}</span></footer>\n"
            "        </article>"
        )
    body.append("      </div>")
    if any(e.get("naive_rw") is not None for _, e in rows):
        body.append(
            f'      <p class="forecast-note">{esc(NAIVE_NOTE)}</p>'
        )
    if any(e.get("official") is not None for _, e in rows):
        body.append(
            '      <p class="forecast-note">The official number is the OBR '
            "March 2026 EFO. It was fixed months before these rounds, on less "
            "data, so its larger error here reflects an information gap as "
            "much as forecasting skill — the comparison shows where the views "
            "differed, not who forecasts better.</p>"
        )
    return "\n".join(body)


def render_page(html: str, card: dict) -> str:
    """Inject the generated blocks between their markers.

    Same contract as validation/figures/make_charts.py: the page is committed,
    the numbers inside it are generated, and --check fails if they drift apart.
    """
    blocks = {
        "scorecard-status": render_status(card),
        "scorecard-results": render_results(card),
        "scorecard-rounds": render_rounds(card),
        "scorecard-vs-official": (
            render_vs_official_variable("gdp")
            + "\n"
            + render_vs_official_variable("cpi")
        ),
    }
    for marker, body in blocks.items():
        pattern = re.compile(
            rf"(<!-- {marker}:begin -->\n).*?(<!-- {marker}:end -->)", re.DOTALL
        )
        if not pattern.search(html):
            raise SystemExit(f"{PAGE}: marker {marker} not found")
        html = pattern.sub(lambda m: m.group(1) + body + "\n" + m.group(2), html, count=1)
    return html


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--check", action="store_true", help="exit 1 if scorecard.json or the page is stale"
    )
    args = ap.parse_args()

    fresh = build()
    rendered = json.dumps(fresh, indent=2) + "\n"
    page_now = PAGE.read_text()
    page_fresh = render_page(page_now, fresh)

    if args.check:
        stale = []
        if not SCORECARD.exists():
            stale.append("scorecard.json missing")
        elif SCORECARD.read_text() != rendered:
            stale.append("scorecard.json is stale")
        if page_now != page_fresh:
            stale.append("forecasts/index.html is stale")
        if stale:
            for item in stale:
                print(f"FAIL {item} — run forecasts/score.py", file=sys.stderr)
            return 1
        print(f"OK — scorecard and page current ({fresh['status']})")
        return 0

    SCORECARD.write_text(rendered)
    if page_now != page_fresh:
        PAGE.write_text(page_fresh)
        print(f"updated {PAGE.relative_to(ROOT)}")
    print(f"wrote {SCORECARD.relative_to(ROOT)} — {fresh['status']}")
    if fresh["next_period_to_score"]:
        print(f"next period to score: {fresh['next_period_to_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
