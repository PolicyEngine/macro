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

            point = stats["median"]
            actual = obs["value"]
            error = point - actual

            entries.append(
                {
                    "period": period,
                    "variable": variable,
                    "forecast": point,
                    "outturn": actual,
                    "outturn_vintage": obs.get("vintage"),
                    "error": error,
                    "abs_error": abs(error),
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
        "status": (
            "accumulating — no forecast period has an outturn yet"
            if total_scored == 0
            else f"{total_scored} forecast period(s) scored"
        ),
        "detail": scored,
    }


# ---------------------------------------------------------------- page

VARIABLE_LABELS = {"gdp": "UK real GDP, y/y", "cpi": "UK CPI, y/y"}

def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_status(card: dict) -> str:
    """The headline paragraph. Deliberately refuses to state an accuracy figure
    while the scored count is small — see the module docstring."""
    rounds = card["rounds"]
    scored = card["periods_scored"]

    lines = [
        "      <p>",
        f"        <strong>{rounds} round{'' if rounds == 1 else 's'} archived; "
        f"{scored} forecast period{'' if scored == 1 else 's'} scored.</strong>",
    ]
    pending = card.get("pending_detail")
    if pending:
        who = ", ".join(f"{VARIABLE_LABELS.get(v, v)}" for v in pending["variables"])
        lines.append(
            f"        The next result due is {esc(pending['period'])} "
            f"({esc(who)}), which lands when the ONS publishes it."
        )
    else:
        lines.append("        Every archived period now has an outturn.")
    lines.append("      </p>")
    return "\n".join(lines)


def render_rounds(card: dict) -> str:
    rows = []
    for detail in card["detail"]:
        href = f"{REPO_BLOB}/{detail['path']}"
        label = "/".join(Path(detail["path"]).parts[-2:])
        rows.append(
            "          <tr>\n"
            f"            <th scope=\"row\">{esc(detail['round_id'])}</th>\n"
            f"            <td>{esc(detail['model'])}</td>\n"
            f"            <td>{esc(detail['data_edge'])}</td>\n"
            f"            <td>{detail['periods_forecast']}</td>\n"
            f"            <td>{detail['periods_scored']}</td>\n"
            f"            <td><a href=\"{href}\"><code>{esc(label)}</code></a></td>\n"
            "          </tr>"
        )
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

    body = []
    for detail, e in sorted(rows, key=lambda r: (r[1]["period"], r[1]["variable"])):
        band = "68%" if e["in_68"] else ("90%" if e["in_90"] else "outside 90%")
        body.append(
            "          <tr>\n"
            f"            <th scope=\"row\">{esc(e['period'])}</th>\n"
            f"            <td>{esc(VARIABLE_LABELS.get(e['variable'], e['variable']))}</td>\n"
            f"            <td>{e['forecast']:.2f}%</td>\n"
            f"            <td>{e['outturn']:.2f}%</td>\n"
            f"            <td>{e['error']:+.2f}pp</td>\n"
            f"            <td>{esc(band)}</td>\n"
            f"            <td>{esc(detail['round_id'])}</td>\n"
            "          </tr>"
        )

    return "\n".join(
        [
            "      <div class=\"table-scroll\">",
            "      <table>",
            "        <caption>Scored forecasts. Error is forecast minus outturn; "
            "the band column is the narrowest credible band the outturn fell inside.</caption>",
            "        <thead><tr><th scope=\"col\">Period</th><th scope=\"col\">Variable</th>"
            "<th scope=\"col\">Forecast</th><th scope=\"col\">Outturn</th>"
            "<th scope=\"col\">Error</th><th scope=\"col\">Band</th>"
            "<th scope=\"col\">Round</th></tr></thead>",
            "        <tbody>",
            *body,
            "        </tbody>",
            "      </table>",
            "      </div>",
        ]
    )


def render_page(html: str, card: dict) -> str:
    """Inject the generated blocks between their markers.

    Same contract as validation/figures/make_charts.py: the page is committed,
    the numbers inside it are generated, and --check fails if they drift apart.
    """
    blocks = {
        "scorecard-status": render_status(card),
        "scorecard-results": render_results(card),
        "scorecard-rounds": render_rounds(card),
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
