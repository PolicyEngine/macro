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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import chartkit  # noqa: E402  (stdlib-only, repo root)
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

# Display names for internal model identifiers. Round artifacts under
# forecasts/rounds/ are immutable, so the internal name recorded in an
# archived round is kept as-is in the scorecard; the label is what the
# page shows.
MODEL_LABELS = {
    "okun-unemployment": "svar-unemployment satellite",
}

# What the page shows for each recorded model: a readable name, then the id
# a reader types into pe-macro (none for the satellite, whose archived
# filename is not a registry id). Render-time only; scorecard.json is unchanged.
MODEL_DISPLAY = {
    "boe-svar": ("BoE SVAR", "boe-svar"),
    "okun-unemployment": ("BoE SVAR unemployment satellite", None),
}


def model_html(detail: dict) -> str:
    name, mid = MODEL_DISPLAY.get(
        detail["model"], (detail.get("label", detail["model"]), None))
    return esc(name) + (f'<span class="model-id">{esc(mid)}</span>' if mid else "")


NAIVE_NOTE = (
    "Naive baseline: the last outturn at the round's data edge, held flat "
    "(read from the current vintage, so revisions can shift it slightly)."
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


# ONS stamps a release with midnight UK time, written in UTC
# ("2026-11-12T00:00:00.000Z", or "2026-07-21T23:00:00.000Z" in summer).
# Statistics are published at 07:00 UK time on that day, so the moment of
# publication is the stamp plus seven hours.
ONS_RELEASE_HOUR = timedelta(hours=7)

# Rounds whose forecast was fixed before ``archived_utc``. Rounds are
# append-only, so this cannot be recorded in the round file itself. Each
# entry needs evidence that anyone can check: the commit that first put the
# exact bytes of the round's source file (``provenance.source_sha256``) on
# main, and that commit's time. test_score_guard.py checks the hash.
FIXED_BEFORE_ARCHIVE = {
    "forecasts/rounds/2026-07-21/boe-svar.json": {
        "fixed_utc": "2026-07-21T13:54:00Z",
        "commit": "b66cadf9",
        "source_sha256": (
            "991ba7fcf99a74a971486cb7c286ea5f41e718727b8a21e6f459dbd74e639dfd"
        ),
        "note": (
            "papers/boe-svar/figures/current_forecast.json with this hash was "
            "committed to main at 14:54 BST on 21 July 2026 (#78), before the "
            "ONS published 2026Q2 CPI at 07:00 on 22 July. The round was "
            "archived from it on 25 July."
        ),
    },
}


def _parse_utc(stamp: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def published_utc(obs: dict) -> datetime | None:
    """When the publisher released this observation.

    The ONS release stamp plus the 07:00 release hour, when there is one. If
    there is no stamp, fall back to midnight UTC on the day our store fetched
    it. That is the latest the value can have been published, so the
    comparison errs towards excluding a forecast.
    """
    stamp = _parse_utc(obs.get("release_updated") or "")
    if stamp is not None:
        return stamp + ONS_RELEASE_HOUR
    return _parse_utc(f"{obs['vintage']}T00:00:00Z") if obs.get("vintage") else None


def latest_outturns(observations: list[dict]) -> dict[tuple[str, str], dict]:
    """Latest vintage per (period, variable). Later vintages supersede earlier.

    Each returned observation also carries ``first_published_utc``: the
    earliest publication time across every stored vintage of that period
    and variable. The scoring guard compares against that, because a
    revision does not make an earlier release unpublished.
    """
    best: dict[tuple[str, str], dict] = {}
    first: dict[tuple[str, str], datetime] = {}
    for obs in observations:
        key = (obs["period"], obs["variable"])
        current = best.get(key)
        if current is None or obs.get("vintage", "") >= current.get("vintage", ""):
            best[key] = obs
        when = published_utc(obs)
        if when is not None and (key not in first or when < first[key]):
            first[key] = when
    return {
        key: {
            **obs,
            "first_published_utc": (
                first[key].strftime("%Y-%m-%dT%H:%M:%SZ") if key in first else None
            ),
        }
        for key, obs in best.items()
    }


def forecast_fixed_utc(rnd: dict) -> datetime | None:
    """When the round's numbers were fixed: archived_utc, or an earlier
    documented time from FIXED_BEFORE_ARCHIVE."""
    exception = FIXED_BEFORE_ARCHIVE.get(rnd.get("_path", ""))
    if exception is not None:
        return _parse_utc(exception["fixed_utc"])
    return _parse_utc(rnd.get("archived_utc") or "")


def score_round(rnd: dict, outturns: dict[tuple[str, str], dict]) -> dict:
    entries = []
    for period, block in sorted(rnd["forecast"].items()):
        for variable, stats in sorted(block.items()):
            obs = outturns.get((period, variable))
            if obs is None:
                continue

            # A forecast only counts if it was fixed before the outturn was
            # first published. A round archived after the release still gets
            # listed under rounds/, but its already-answered periods are never
            # scored: scoring them would launder hindsight into the track
            # record. The comparison uses the publisher's release time for the
            # first vintage of the period (#242), not the day our store
            # fetched it, and an unknown time on either side excludes it.
            fixed = forecast_fixed_utc(rnd)
            published = _parse_utc(obs.get("first_published_utc") or "")
            if fixed is None or published is None or fixed >= published:
                continue

            point = stats["median"]
            actual = obs["value"]
            error = point - actual
            naive = naive_random_walk(variable, rnd["information_set"]["data_edge"])
            # The OBR's number is the latest EFO published before the round
            # was fixed; benchmarks likewise only count if they were public by
            # then (an edition fixed after the round never appears beside it).
            obr = latest_edition(OBR_EDITIONS(), fixed, variable, period)
            official = obr[2] if obr else None
            official_label = obr[0] if obr else None
            # Every published path stored for this period and variable, each
            # with the date its information set closed. They are context for
            # the error, not a league table: each was fixed months before the
            # round, on less data (see BENCHMARKS).
            benchmarks = [
                {
                    "label": label,
                    "fixed": closed,
                    "value": value,
                    "abs_error": abs(value - actual),
                }
                for label, closed, paths in BENCHMARKS()
                for value in [paths.get(variable, {}).get(period)]
                if value is not None and published_before(closed, fixed)
            ]

            entries.append(
                {
                    "period": period,
                    "variable": variable,
                    "forecast": point,
                    "outturn": actual,
                    "outturn_vintage": obs.get("vintage"),
                    "outturn_series": obs.get("series"),
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
                    "official_label": official_label,
                    "official_abs_error": (
                        abs(official - actual) if official is not None else None
                    ),
                    # Band coverage is the honest test of a fan chart: a model
                    # whose 68% band contains the outturn 68% of the time is
                    # calibrated, however large its point errors are.
                    "benchmarks": benchmarks,
                    # The archived band, as it was stated: coverage is scored
                    # on the raw quantiles, never on the re-calibrated display
                    # bands of the open-round fans.
                    "lo68": stats["lo68"],
                    "hi68": stats["hi68"],
                    "lo90": stats["lo90"],
                    "hi90": stats["hi90"],
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
        "label": MODEL_LABELS.get(rnd["model"]["name"], rnd["model"]["name"]),
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
            else (
                f"{sum(len(d['entries']) for d in scored)} forecast(s) scored, "
                f"{len({e['period'] for d in scored for e in d['entries']})} period(s)"
            )
        ),
        "detail": scored,
    }


# ------------------------------------------------- model vs official forecast

# Frozen March 2026 EFO GDP levels: papers/obr-macro/figures/fig_anchored_data.csv now
# follows the emulator's current anchor (October 2026), so the March benchmark keeps its own copy.
EFO_CSV = HERE / "official" / "obr_efo_mar_2026_gdp_levels.csv"
EFO_CPI_CSV = ROOT / "papers" / "obr-macro" / "figures" / "efo_march_2026_cpi.csv"
def _latest_svar_round() -> Path:
    """Newest dated round with a boe-svar artifact, for the §03 display.

    Scoring (§02) is unaffected: it walks every archived round and scores each
    against outturns, so the scored-example card keeps using whichever round
    was actually scored. Only the model-vs-official comparison tracks the
    latest archived view.
    """
    candidates = sorted(
        p
        for p in ROUNDS.glob("*/boe-svar.json")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.parent.name)
    )
    if not candidates:
        raise SystemExit("no rounds/<date>/boe-svar.json artifact found")
    return candidates[-1]


SVAR_ROUND = _latest_svar_round()

OFFICIAL_LABEL = "OBR March 2026 EFO"


def efo_gdp_yoy() -> dict[str, float]:
    """OBR March 2026 EFO real GDP y/y growth, derived from the level path."""
    import csv

    levels: dict[str, float] = {}
    with EFO_CSV.open() as fh:
        body = [line for line in fh if not line.startswith("#")]
    for row in csv.DictReader(body):
        levels[row["quarter"]] = float(row["gdpm_efo_m"])
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
SEF_LABEL = "BoE SEF Apr 2026"


def _official_csv(path: Path) -> dict[str, dict[str, float]]:
    """Read a quarter,cpi_yoy_pct,gdp_yoy_pct file with # comment headers."""
    import csv

    with path.open() as fh:
        body = [line for line in fh if not line.startswith("#")]
    paths: dict[str, dict[str, float]] = {"cpi": {}, "gdp": {}, "unemployment": {}}
    for row in csv.DictReader(body):
        for var, col in (("cpi", "cpi_yoy_pct"), ("gdp", "gdp_yoy_pct"),
                         ("unemployment", "unemployment_pct")):
            if row.get(col):
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


OFFICIAL_DIR = HERE / "official"
OBR_OCT_LABEL = "OBR October 2026 EFO"
BOE_NOV_LABEL = "BoE Nov 2026 MPR"
SEF_OCT_LABEL = "BoE SEF Oct 2026"
_EDITION_CACHE: dict[str, dict[str, dict[str, float]]] = {}


def _edition(name: str) -> dict[str, dict[str, float]]:
    if name not in _EDITION_CACHE:
        _EDITION_CACHE[name] = _official_csv(OFFICIAL_DIR / name)
    return _EDITION_CACHE[name]


def OBR_EDITIONS() -> list[tuple[str, str, dict[str, dict[str, float]]]]:
    """Every stored OBR EFO path, oldest first, with its publication date."""
    return [
        (OFFICIAL_LABEL, "2026-03", official_paths()),
        (OBR_OCT_LABEL, "2026-10-28", _edition("obr_efo_oct_2026.csv")),
    ]


def BOE_EDITIONS() -> list[tuple[str, str, dict[str, dict[str, float]]]]:
    return [
        (BOE_LABEL, "2026-02", boe_paths()),
        (BOE_NOV_LABEL, "2026-11-05", _edition("boe_mpr_nov_2026_central.csv")),
    ]


def SEF_EDITIONS() -> list[tuple[str, str, dict[str, dict[str, float]]]]:
    return [
        (SEF_LABEL, "2026-04-16", sef_paths()),
        (SEF_OCT_LABEL, "2026-10-23", _edition("boe_sef_oct_2026.csv")),
    ]


def BENCHMARKS() -> list[tuple[str, str, dict[str, dict[str, float]]]]:
    """(label, date the information set closed, paths) for every stored path.

    The dates are the publications' own (forecasts/official/*.csv headers):
    BoE MPR central projections of February and November 2026, OBR EFOs of
    March and October 2026, and the Survey of External Forecasters as of
    16 April and 23 October 2026. A benchmark appears beside a round only if
    it was published before the round was fixed (published_before), so a
    later edition never sits beside an earlier forecast.
    """
    return BOE_EDITIONS() + OBR_EDITIONS() + SEF_EDITIONS()


def _closed_date(closed: str) -> datetime:
    """'2026-03' -> end of March 2026 (conservative); '2026-10-28' -> that day's end."""
    import calendar
    parts = [int(x) for x in closed.split("-")]
    if len(parts) == 2:
        parts.append(calendar.monthrange(parts[0], parts[1])[1])
    return datetime(parts[0], parts[1], parts[2], 23, 59, 59, tzinfo=timezone.utc)


def published_before(closed: str, fixed: datetime | None) -> bool:
    return fixed is not None and _closed_date(closed) < fixed


def latest_edition(editions, fixed, variable, period):
    """(label, closed, value) from the newest edition published before
    ``fixed``, or None if there is none or it has no value for the period.
    One edition per comparison: an older edition never fills a newer one's
    gaps, so a path is never stitched from two publications."""
    live = [e for e in editions if published_before(e[1], fixed)]
    if not live:
        return None
    label, closed, paths = live[-1]
    value = paths.get(variable, {}).get(period)
    return (label, closed, value) if value is not None else None


BAND_CALIBRATION = HERE / "band_calibration.json"


def _calibration_k(variable: str) -> dict[str, dict[str, float]]:
    """Per-horizon widening factors from forecasts/band_calibration.json."""
    cal = json.loads(BAND_CALIBRATION.read_text())
    return cal["k"][variable]


def _quarter_index(period: str) -> int:
    return int(period[:4]) * 4 + int(period[5]) - 1


def build_vs_official(variable: str) -> list[dict]:
    """SVAR archived medians beside the EFO path, on shared quarters.

    Band half-widths are re-scaled around the archived median by the
    empirical calibration factors in forecasts/band_calibration.json
    (measured under-coverage; h beyond the evaluated 8 holds the h8
    factor). The archived round artifact itself is never modified.
    """
    rnd = json.loads(SVAR_ROUND.read_text())
    fixed = _parse_utc(rnd.get("archived_utc") or "")
    edge = _quarter_index(rnd["information_set"]["data_edge"])
    k = _calibration_k(variable)
    rows = []
    for period in sorted(rnd["forecast"]):
        efo = latest_edition(OBR_EDITIONS(), fixed, variable, period)
        if efo is None or variable not in rnd["forecast"][period]:
            continue
        g = rnd["forecast"][period][variable]
        h = min(max(_quarter_index(period) - edge, 1), 8)
        k68, k90 = k["68"][f"h{h}"], k["90"][f"h{h}"]
        med = g["median"]
        rows.append(
            {
                "period": period,
                "median": med,
                "lo68": med + (g["lo68"] - med) * k68,
                "hi68": med + (g["hi68"] - med) * k68,
                "lo90": med + (g["lo90"] - med) * k90,
                "hi90": med + (g["hi90"] - med) * k90,
                "efo": efo[2],
                "efo_label": efo[0],
                "boe": (latest_edition(BOE_EDITIONS(), fixed, variable, period) or (None, None, None))[2],
                "sef": (latest_edition(SEF_EDITIONS(), fixed, variable, period) or (None, None, None))[2],
            }
        )
    return rows


# Per-variable presentation of the model-vs-official comparison.
VS_OFFICIAL_SPECS = {
    "gdp": {
        "chart_id": "svar-vs-efo",
        "name": "UK real GDP growth",
        "series": "UK real GDP, year-on-year growth, percent",
        "unit": "UK real GDP, % change on a year earlier",
        "source_note": (
            "OBR March 2026 EFO"
        ),
        "intro": (
            "GDP growth from the {round_id} round: our median and bands "
            "beside the OBR's path."
        ),
    },
    "cpi": {
        "chart_id": "svar-vs-efo-cpi",
        "name": "UK CPI inflation",
        "series": "UK CPI, year-on-year inflation, percent",
        "unit": "UK CPI, % change on a year earlier",
        "source_note": (
            "EFO path from Table 1.7 of the March 2026 EFO detailed economy "
            "tables, stored in "
            "<code>papers/obr-macro/figures/efo_march_2026_cpi.csv</code>"
        ),
        "intro": (
            "Same round, CPI: the model sits close to the EFO through 2027Q3, "
            "then stays higher as the EFO returns towards 2% — partly because a "
            "VAR estimated through the 2021–23 surge mean-reverts toward a higher "
            "sample mean."
        ),
    },
}


def outturn_values(variable: str) -> dict[str, float]:
    """Newest stored outturn per period, for the outturn dots on the fans."""
    doc = json.loads(OUTTURNS.read_text())
    return {
        period: obs["value"]
        for (period, var), obs in latest_outturns(doc.get("observations", [])).items()
        if var == variable
    }


OCT_EFO_SOURCE = {
    "gdp": ("OBR October 2026 EFO path: four-quarter growth of Table 1.1 real GDP, "
            "detailed economy tables, stored in "
            "<code>forecasts/official/obr_efo_oct_2026.csv</code>"),
    "cpi": ("EFO path from Table 1.7 of the October 2026 EFO detailed economy "
            "tables, stored in <code>forecasts/official/obr_efo_oct_2026.csv</code>"),
}


def efo_label(rows: list[dict]) -> str:
    """The EFO edition(s) a fan is drawn against: the newest published before
    the open round was fixed (build_vs_official)."""
    return " / ".join(dict.fromkeys(r["efo_label"] for r in rows))


def render_vs_official_variable(variable: str, include_note: bool = False) -> str:
    """Fan chart: archived boe-svar path with 68/90% bands vs the latest EFO
    published before the round."""
    rows = build_vs_official(variable)
    spec = VS_OFFICIAL_SPECS[variable]
    chart_id = spec["chart_id"]
    if not rows:
        return "      <!-- no overlapping quarters -->"
    efo_name = efo_label(rows)
    source_note = OCT_EFO_SOURCE[variable] if efo_name == OBR_OCT_LABEL else spec["source_note"]

    # SVG geometry mirrors the validation-page vchart conventions.
    width, height = 760, 300
    left, right, top, bottom = 56, 16, 34, 40
    plot_w, plot_h = width - left - right, height - top - bottom
    seen = outturn_values(variable)
    dots = [(i, seen[r["period"]]) for i, r in enumerate(rows) if r["period"] in seen]
    values = [v for r in rows for v in (r["lo90"], r["hi90"], r["efo"])]
    values += [v for _, v in dots]
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

    def band_points(lo_key: str, hi_key: str) -> str:
        pts = " ".join(f"{x(i):.1f},{y(r[hi_key]):.1f}" for i, r in enumerate(rows))
        return pts + " " + " ".join(
            f"{x(i):.1f},{y(r[lo_key]):.1f}"
            for i, r in reversed(list(enumerate(rows)))
        )

    band90 = band_points("lo90", "hi90")
    band = band_points("lo68", "hi68")
    median = " ".join(f"{x(i):.1f},{y(r['median']):.1f}" for i, r in enumerate(rows))
    efo = " ".join(f"{x(i):.1f},{y(r['efo']):.1f}" for i, r in enumerate(rows))

    gridlines = []
    # One labelled gridline per point: at 0.5 the labels stacked on a phone.
    step = 1.0
    v = (int(lo / step)) * step
    while v <= hi:
        if v >= lo:
            cls = "vc-zero" if abs(v) < 1e-9 else "vc-grid"
            gridlines.append(
                f'<line class="{cls}" x1="{left}" y1="{y(v):.1f}" '
                f'x2="{width - right}" y2="{y(v):.1f}"/>'
            )
            # More than six labels: odd ones are minor, hidden on a phone,
            # where the plot is ~170 px tall and they crowded the median.
            odd = (hi - lo) > 6 and round(v) % 2 != 0
            gridlines.append(chartkit.ytick(left, y(v), f"{v:g}".replace("-", "\u2212"),
                                            "vc-minor" if odd else ""))
        v += step
    last = len(rows) - 1
    # About seven quarter labels when wide, three when the chart is narrower
    # than 520 px (chartkit.tick_plan).
    xticks = [chartkit.xtick(x(i), top + plot_h, rows[i]["period"], i, last, minor=minor)
              for i, minor in chartkit.tick_plan(len(rows))]

    svg = "\n".join(
        [
            f'<svg class="vchart" data-chart="{chart_id}" viewBox="{left - 4} {top - 4} '
            f'{plot_w + 8} {plot_h + 8}" '
            f'role="img" aria-labelledby="{chart_id}-t {chart_id}-d">',
            f'<title id="{chart_id}-t">BoE SVAR {spec["name"]} forecast vs '
            f"{efo_name}</title>",
            f'<desc id="{chart_id}-d">Fan chart of {spec["series"]}. '
            "The BoE SVAR archived median with its 68 and 90 percent bands, "
            "empirically re-calibrated for measured under-coverage, is shown beside "
            f"the {efo_name} path over the overlapping quarters."
            + "".join(f" ONS outturn for {rows[i]['period']}: {v:.2f} percent." for i, v in dots)
            + "</desc>",
            *gridlines,
            f'<polygon class="vc-band90" points="{band90}"/>',
            f'<polygon class="vc-band68" points="{band}"/>',
            f'<polyline class="vc-s1" points="{median}"/>',
            f'<polyline class="vc-s2" points="{efo}"/>',
            *(f'<circle class="vc-out-dot" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4"/>'
              for i, v in dots),
            *xticks,
            "</svg>",
        ]
    )
    block = chartkit.figure(svg, legend=[
        ("ln-s1", "BoE SVAR median"),
        ("sw-band68", "68% band (re-calibrated)"),
        ("sw-band90", "90% band (re-calibrated)"),
        ("ln-s2", efo_name),
        *([("sw-dot-out", "ONS outturn")] if dots else []),
    ], unit=spec["unit"], y_gutter=True,
       source_short=(f"BoE SVAR round, {chartkit.short_date(SVAR_ROUND.parent.name)} · {efo_name}"
                     + (" · ONS" if dots else "")),
       source=(
        f'archived round <a class="mono" href="/forecasts/rounds/{SVAR_ROUND.parent.name}/'
        f'{SVAR_ROUND.name}">{SVAR_ROUND.parent.name}/{SVAR_ROUND.name}</a>; '
        + source_note
        + ('; outturns from the <a href="/economy#data">data store</a>' if dots else "")
    ))
    return "\n".join([
        '      <p class="chart-intro">'
        f'{spec["intro"].format(round_id=SVAR_ROUND.parent.name)}</p>',
        '      <figure class="vchart-figure">',
        block,
        # Inside the figure: the page's chart-tab script moves each figure
        # into its tab panel, and the numbers must travel with their fan.
        vs_official_table(variable, rows),
        "      </figure>",
    ])


def vs_official_table(variable: str, rows: list[dict]) -> str:
    """The fan's own numbers, quarter by quarter (#220 item 4).

    Same rows the chart draws: the archived median, the re-calibrated bands
    and the EFO path, at two decimals like the topic tables. Nothing here is
    computed that the chart does not already plot.
    """
    spec = VS_OFFICIAL_SPECS[variable]

    def pc(v: float) -> str:
        return f"{v:.2f}%".replace("-", "\u2212")

    body = "\n".join(
        "          <tr>"
        f'<th scope="row">{r["period"]}</th>'
        f'<td class="num">{pc(r["median"])}</td>'
        f'<td class="num">{pc(r["lo68"])}–{pc(r["hi68"])}</td>'
        f'<td class="num">{pc(r["lo90"])}–{pc(r["hi90"])}</td>'
        f'<td class="num">{pc(r["efo"])}</td>'
        "</tr>"
        for r in rows
    )
    return f"""      <details class="about fc-qq">
        <summary>Quarter by quarter: the numbers in this fan</summary>
      <div class="table-scroll">
        <table>
          <caption>BoE SVAR {esc(spec["name"])} forecast, round {SVAR_ROUND.parent.name}, beside the {efo_label(rows)}: % change on a year earlier. Bands are re-calibrated, as drawn.</caption>
          <thead><tr><th scope="col">Quarter</th><th scope="col">Median</th><th scope="col">68% band (re-calibrated)</th><th scope="col">90% band (re-calibrated)</th><th scope="col">EFO</th></tr></thead>
          <tbody>
{body}
          </tbody>
        </table>
      </div>
      </details>"""


# ---------------------------------------------------------------- page

VARIABLE_LABELS = {
    "gdp": "UK real GDP, y/y",
    "cpi": "UK CPI, y/y",
    "unemployment": "UK unemployment rate",
}
MANIFEST = ROOT / "data" / "MANIFEST.json"


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def signed(v: float, unit: str = "pp") -> str:
    """Signed value with a true minus sign (DESIGN.md §2.3)."""
    return f"{v:+.2f}{unit}".replace("-", "\u2212")


def store_last_fetched() -> str:
    """Newest snapshot date anywhere in the vintage store."""
    doc = json.loads(MANIFEST.read_text())
    return max(entry["latest_vintage"] for entry in doc["series"].values())


def vintage_file(series: str, vintage: str) -> str | None:
    """Site path of the immutable snapshot an outturn was read from."""
    for path in sorted((ROOT / "data" / "vintages").glob(f"*/{series}/{vintage}.json")):
        return "/" + path.relative_to(ROOT).as_posix()
    return None


def long_date(iso: str) -> str:
    """'2026-08-26' -> '26 August 2026' (no leading zero, locale-free)."""
    import datetime as _dt
    d = _dt.date.fromisoformat(iso[:10])
    months = ("January February March April May June July August September "
              "October November December").split()
    return f"{d.day} {months[d.month - 1]} {d.year}"


def scored_entries(card: dict) -> list[tuple[dict, dict]]:
    return sorted(
        ((detail, entry) for detail in card["detail"] for entry in detail["entries"]),
        key=lambda r: (r[1]["period"], r[1]["variable"], r[0]["round_id"]),
    )


_ICON_PATHS = {
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "ruler": '<path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.4 2.4 0 0 1 0-3.4l2.6-2.6a2.4 2.4 0 0 1 3.4 0Z"/><path d="m14.5 12.5 2-2"/><path d="m11.5 9.5 2-2"/><path d="m8.5 6.5 2-2"/><path d="m17.5 15.5 2-2"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7l10-5Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "cpi": '<path d="M12 2H2v10l9.29 9.29a1 1 0 0 0 1.41 0l8.59-8.59a1 1 0 0 0 0-1.41Z"/><path d="M7 7h.01"/>',
    "gdp": '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "unemployment": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "inside": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5" fill="currentColor"/>',
    "outside": '<circle cx="10" cy="12" r="7" stroke-dasharray="3 3"/><circle cx="21" cy="12" r="1.5" fill="currentColor"/>',
    "scale": '<path d="M12 3v18"/><path d="M7 21h10"/><path d="M3 7h18"/><path d="m6 7-3 8a3 3 0 0 0 6 0Z"/><path d="m18 7-3 8a3 3 0 0 0 6 0Z"/>',
    "chev": '<path d="m6 9 6 6 6-6"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "equal": '<path d="M5 9h14"/><path d="M5 15h14"/>',
}


def icon(name: str, cls: str = "fc-ic") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">'
            f"{_ICON_PATHS[name]}</svg>")


def record_stats(card: dict) -> dict:
    """Aggregates the scoreboard and the home strip both print.

    Read-only over scorecard.json. The first round was archived
    retroactively, so its scores are counted apart from the ex-ante ones;
    several forecasts can score the same outturn, so outturns are counted too.
    """
    pairs = scored_entries(card)
    first = card["detail"][0]["round_id"] if card["detail"] else None
    retro = [e for d, e in pairs if d["round_id"] == first]
    exante = [e for d, e in pairs if d["round_id"] != first]
    entries = [e for _, e in pairs]
    naive = [e["naive_abs_error"] for e in entries if e.get("naive_abs_error") is not None]
    n = len(entries)
    return {
        "scored": n,
        "outturns": len({(e["period"], e["variable"]) for e in entries}),
        "rounds": len({d["round_id"] for d, _ in pairs}),
        "in68": sum(e["in_68"] for e in entries),
        "in90": sum(e["in_90"] for e in entries),
        "exante": len(exante), "exante_in68": sum(e["in_68"] for e in exante),
        "retro": len(retro), "retro_in68": sum(e["in_68"] for e in retro),
        "mae": sum(e["abs_error"] for e in entries) / n if n else 0.0,
        "naive_mae": sum(naive) / len(naive) if n and len(naive) == n else None,
        "bias": sum(e["error"] for e in entries) / n if n else 0.0,
        "low": sum(e["error"] < 0 for e in entries),
    }


def render_status(card: dict) -> str:
    """The record in three tiles: band coverage, mean error against no change,
    and how much there is to go on.

    Every figure is an aggregate of the per-forecast values in scorecard.json
    (``in_68``/``in_90``, ``abs_error``, ``naive_abs_error``), computed here at
    render time; scorecard.json itself is untouched. A line under the tiles
    says the sample is too small to show skill, so the first two are never
    read as a skill claim on their own (DESIGN.md §7.5).
    """
    rounds = card["rounds"]
    pairs = scored_entries(card)
    entries = [e for _, e in pairs]
    scored_rounds = len({d["round_id"] for d, _ in pairs})
    scored = len(entries)
    pending = card.get("pending_detail")
    fetched = store_last_fetched()
    if pending:
        short = {"gdp": "GDP", "cpi": "CPI", "unemployment": "unemployment"}
        who = ", ".join(short.get(v, v) for v in pending["variables"])
        next_sub = f"Next: <span class=\"nowrap\">{esc(pending['period'])}</span> {esc(who)}."
    else:
        next_sub = "Every archived period has an outturn."
    st = record_stats(card)
    first = card["detail"][0]["round_id"] if card["detail"] else None
    ex = [e for d, e in pairs if d["round_id"] != first]
    # Say plainly how current the record is (r5 usability test, #220): the date
    # is the newest outturn snapshot any scored forecast was read from.
    if scored:
        last = max(e["outturn_vintage"] for e in entries)
        asof = (f'      <p class="record-asof"><strong>Last scored <time datetime="{esc(last)}">'
                f'{esc(long_date(last))}</time>;</strong> data store updated '
                f'<span class="nowrap">{esc(long_date(fetched))}</span>.</p>')
    else:
        asof = '      <p class="record-asof"><strong>Nothing scored yet.</strong></p>'

    def tile(ic: str, label: str, value: str, sub: str, extra: str = "", cls: str = "") -> list[str]:
        return [
            f'        <div class="fc-tile{(" " + cls) if cls else ""}">',
            f'          <span class="fc-tile-l">{icon(ic)}{label}</span>',
            *([f'          <span class="fc-tile-v">{value}</span>'] if value else []),
            *([extra] if extra else []),
            f'          <span class="fc-tile-s">{sub}</span>',
            "        </div>",
        ]

    if not scored:
        return "\n".join([asof, '      <div class="fc-tiles ab-card" aria-label="The record so far"></div>'])
    pips = (f'          <span class="fc-pips" role="img" aria-label="{st["exante_in68"]} of {st["exante"]} '
            'ex-ante forecasts inside the 68% band">'
            + "".join(f'<i class="{"in" if e["in_68"] else "out"}"></i>' for e in ex) + "</span>")
    tiles = tile("target", "Inside the 68% band, made before the outturn",
                 f'{st["exante_in68"]} of {st["exante"]}',
                 f'+{st["retro"]} retroactive · {scored} forecasts of {st["outturns"]} outturns', pips)
    if st["naive_mae"] is not None:
        top = max(st["mae"], st["naive_mae"])
        bars = ('          <div class="fc-bars" role="img" aria-label="Average miss: this model '
                f'{st["mae"]:.2f}pp, no-change forecast {st["naive_mae"]:.2f}pp">'
                f'<span class="fc-bar-l">This model {st["mae"]:.2f}pp</span><span class="fc-bar"><i class="fc-bar-ours" style="width:{st["mae"] / top * 100:.0f}%"></i></span>'
                f'<span class="fc-bar-l">No change {st["naive_mae"]:.2f}pp</span><span class="fc-bar"><i class="fc-bar-naive" style="width:{st["naive_mae"] / top * 100:.0f}%"></i></span>'
                "</div>")
        tiles += tile("ruler", "Average miss", "", "Lower is better; same forecasts, same outturns.", bars)
    sign = "\u2212" if st["bias"] < 0 else "+"
    runs = (f'Ran low on {st["low"]} of {scored}' if st["bias"] < 0
            else f'Ran high on {scored - st["low"]} of {scored}')
    tiles += tile("scale", "Bias, mean error", f'{sign}{abs(st["bias"]):.2f}pp', runs)
    tiles += tile("layers", "Rounds", f'{scored_rounds} scored', next_sub)
    chip = (f'      <p class="fc-skill"><span class="fc-skill-chip">{icon("alert")}Too few to show skill</span>'
            '<a href="#limits">Limits</a></p>')
    return "\n".join([
        asof,
        '      <div class="fc-tiles ab-card" aria-label="The record so far">',
        *tiles,
        "      </div>",
        chip,
    ])


def _gap_days(a: str, b: str) -> int:
    import datetime as _dt
    return (_dt.date.fromisoformat(b) - _dt.date.fromisoformat(a)).days


def render_rounds(card: dict) -> str:
    """The archive as a timeline: one node per round, oldest first.

    Below 640 px the rail turns vertical. Every value is the same as the old
    table's: round, model, data edge, archived date, periods, scored, files.
    """
    details = card["detail"]
    items = ['      <ol class="fc-timeline" aria-label="Every archived round, oldest first">']
    for i, detail in enumerate(details):
        href = f"https://github.com/PolicyEngine/macro/commits/main/{detail['path']}"
        archived = (detail.get("archived_utc") or "")[:10] or "—"
        n = len(detail["entries"])
        gap = ""
        if i:
            days = _gap_days(details[i - 1]["round_id"], detail["round_id"])
            gap = f'<span class="fc-gap">{days} day{"" if days == 1 else "s"} later</span>'
        state = "is-scored" if n else "is-open"
        flag = " is-retro" if i == 0 else ""
        name = MODEL_DISPLAY.get(detail["model"], (detail.get("label", detail["model"]), None))[0]
        chips = []
        if i == 0:
            chips.append('<a class="fc-chip fc-chip-retro" href="#retro" title="Archived retroactively; see the note below">Retroactive</a>')
        chips.append(f'<span class="fc-chip fc-chip-scored">Scored {n}</span>' if n
                     else '<span class="fc-chip fc-chip-open">Open</span>')
        items.append(
            f'        <li class="fc-node {state}{flag}">{gap}'
            '<span class="fc-dot" aria-hidden="true"></span>'
            '<div class="fc-node-card">'
            '<div class="fc-node-head"><div>'
            f'<p class="fc-node-date"><time datetime="{esc(detail["round_id"])}">{esc(chartkit.short_date(detail["round_id"]))}</time></p>'
            f'<p class="fc-node-model" title="{esc(name)}">{icon("activity")}<span>{esc(name)}</span></p>'
            f'</div><div class="fc-node-chips">{"".join(chips)}</div></div>'
            '<dl class="fc-mini">'
            f'<div><dt>Data edge</dt><dd>{esc(detail["data_edge"])}</dd></div>'
            f'<div><dt>Periods</dt><dd>{detail["periods_forecast"]}</dd></div>'
            f'<div><dt>Scored</dt><dd>{n}</dd></div>'
            "</dl>"
            '<div class="fc-node-foot">'
            f'<span class="fc-node-arch">{icon("calendar")}Archived {esc(chartkit.short_date(archived))}</span>'
            f'<span class="fc-node-links"><a href="/{esc(detail["path"])}" download title="{esc(Path(detail["path"]).name)}">{icon("file")}Round file</a>'
            f'<a href="{href}" title="Git history of this round file">{icon("history")}History</a></span>'
            "</div></div></li>"
        )
    items.append("      </ol>")
    return "\n".join(items)


def _strip(e: dict) -> str:
    """Where the outturn fell, on the row's own 90% band.

    Each strip is normalised so its 90% band runs from 18% to 82% of the
    width; that makes "where the outturn landed" comparable across variables
    whose bands differ by an order of magnitude. Positions clamp to 3–97%.
    The values are printed as HTML labels; the shapes are aria-hidden.
    """
    lo, hi = e["lo90"], e["hi90"]
    span_ = max(hi - lo, 1e-9)

    def p(v: float) -> float:
        return max(3.0, min(97.0, 18 + 64 * (v - lo) / span_))

    med, out = p(e["forecast"]), p(e["outturn"])
    out_below = abs(med - out) < 16
    # Edge labels sit under the 90% band ends (18% and 82%); drop one only
    # when the outturn label is also below and would collide with it.
    show_lo = not (out_below and abs(out - 18) < 12)
    show_hi = not (out_below and abs(out - 82) < 12)
    return (
        '<div class="fc-strip">'
        '<span class="fc-track" aria-hidden="true"></span>'
        f'<span class="fc-b90" aria-hidden="true" style="left:{p(lo):.1f}%;width:{p(hi) - p(lo):.1f}%"></span>'
        f'<span class="fc-b68" aria-hidden="true" style="left:{p(e["lo68"]):.1f}%;width:{p(e["hi68"]) - p(e["lo68"]):.1f}%"></span>'
        f'<span class="fc-conn" aria-hidden="true" style="left:{min(med, out):.1f}%;width:{abs(med - out):.1f}%"></span>'
        f'<span class="fc-med" aria-hidden="true" style="left:{med:.1f}%"></span>'
        f'<span class="fc-out" aria-hidden="true" style="left:{out:.1f}%"></span>'
        f'<span aria-hidden="true" class="fc-lab fc-lab-med" style="left:{med:.1f}%">{e["forecast"]:.2f}%</span>'
        f'<span aria-hidden="true" class="fc-lab fc-lab-out{" is-below" if out_below else ""}" style="left:{out:.1f}%">{e["outturn"]:.2f}%</span>'
        + (f'<span aria-hidden="true" class="fc-lab fc-lab-lo" style="left:18%">{lo:.2f}</span>' if show_lo else "")
        + (f'<span aria-hidden="true" class="fc-lab fc-lab-hi" style="left:82%">{hi:.2f}</span>' if show_hi else "")
        +         "</div>"
    )


def _band_label(e: dict) -> str:
    return ("inside 68%" if e["in_68"]
            else "inside 90%, outside 68%" if e["in_90"]
            else "outside 90%")


def _target(e: dict) -> str:
    return (f'<span class="mono">{esc(e["period"])}</span> '
            f'{esc(VARIABLE_LABELS.get(e["variable"], e["variable"]))}')


def render_results(card: dict) -> str:
    """The scoreboard: the home of every scored number (DESIGN.md §7.0).

    The record is one row per scored forecast: target and round, a band strip
    (90% and 68% bands as archived, median, outturn, all labelled), the
    signed error and where the outturn fell. The benchmark grid (the same
    outturn against the no-change forecast and each published path) sits in
    an expander under it. Every figure is read from scorecard.json; nothing
    is ranked or highlighted. Absent entirely until something is scored.
    """
    rows = scored_entries(card)
    if not rows:
        return "      <!-- nothing scored yet -->"

    body = [
        f'      <h3 class="sb-h" id="record">{icon("layers", "fc-ic fc-th-ic")}The record</h3>',
        '      <ul class="fc-legend" aria-hidden="true">'
        '<li><span class="fc-sw fc-sw-90"></span>90% band</li>'
        '<li><span class="fc-sw fc-sw-68"></span>68% band</li>'
        '<li><span class="fc-sw fc-sw-med"></span>median</li>'
        '<li><span class="fc-sw fc-sw-out"></span>outturn</li>'
        f'<li class="fc-legend-note">{icon("info", "fc-ic fc-th-ic")}Each strip spans its own 90% band.</li></ul>',
        '      <div class="fc-board ab-card" role="table" aria-label="Every scored forecast: archived median and bands, outturn, error">',
        f'        <div class="fc-row fc-head" role="row"><span role="columnheader">{icon("target", "fc-ic fc-th-ic")}Target and round</span>'
        f'<span role="columnheader">{icon("gdp", "fc-ic fc-th-ic")}Median, archived bands and outturn</span>'
        f'<span role="columnheader">{icon("ruler", "fc-ic fc-th-ic")}Error</span><span role="columnheader">{icon("inside", "fc-ic fc-th-ic")}Where it fell</span></div>',
    ]
    first_round = card["detail"][0]["round_id"] if card["detail"] else None
    for detail, e in rows:
        retro = ('<a class="fc-retro-mark" href="#retro" title="Archived retroactively; see the archive" '
                 '>Retroactive</a>'
                 if detail["round_id"] == first_round else "")
        vfile = vintage_file(e.get("outturn_series") or "", e["outturn_vintage"] or "")
        vint = (f'<a class="fc-vint" href="{vfile}">vintage {esc(e["outturn_vintage"])}</a>'
                if vfile else "")
        band = _band_label(e)
        inside = e["in_68"] or e["in_90"]
        badge_cls = "fc-in" if e["in_68"] else ("fc-mid" if e["in_90"] else "fc-out-b")
        h = _quarter_index(e["period"]) - _quarter_index(detail["data_edge"])
        y, q = int(e["period"][:4]), int(e["period"][-1])
        q_end = f"{y}-{3 * q:02d}-{[31, 30, 30, 31][q - 1]}"
        back = detail["round_id"] > q_end
        horizon = (f'<span class="fc-h" title="Quarters after the round\'s data edge">h{h}</span>'
                   + ('<span class="fc-h fc-h-back" title="The quarter had already ended when the round was archived">backcast</span>' if back else ""))
        note = ('<a class="fc-row-note" href="#limits">Satellite band understates uncertainty</a>'
                if e["variable"] == "unemployment" else "")
        body.append(
            '        <div class="fc-row" role="row">'
            f'<div class="fc-tgt" role="rowheader"><span class="fc-var">{icon(e["variable"] if e["variable"] in _ICON_PATHS else "target")}</span>'
            f'<span><strong>{_target(e)}</strong>'
            f'<span class="fc-round-line"><a class="fc-round" href="#rounds">{esc(detail["round_id"])} · {esc(MODEL_DISPLAY.get(detail["model"], (detail.get("label", detail["model"]), None))[0].replace("BoE SVAR unemployment satellite", "unemployment satellite"))}</a>{retro}{horizon}</span></span></div>'
            f'<div role="cell"><span class="visually-hidden">Median {e["forecast"]:.2f}%, 68% band '
            f'{e["lo68"]:.2f}–{e["hi68"]:.2f}, 90% band {e["lo90"]:.2f}–{e["hi90"]:.2f}, outturn {e["outturn"]:.2f}%.</span>'
            f"{_strip(e)}</div>"
            f'<div role="cell" class="fc-err"><span class="fc-err-chip">{signed(e["error"])}</span></div>'
            f'<div role="cell" class="fc-where"><span class="fc-badge2 {badge_cls}">{icon("inside" if inside else "outside")}{esc(band[0].upper() + band[1:])}</span>{vint}{note}</div>'
            "</div>"
        )
    body.append("      </div>")
    body.append('      <p class="fc-cap">Error is the archived median minus the outturn, in percentage points: positive means the forecast ran high.</p>')

    # Benchmark grid: one column per published path that scores anything,
    # in the order the scorecard lists them (earliest fixed first).
    labels: list[str] = []
    for _, e in rows:
        for b in e.get("benchmarks", []):
            if b["label"] not in labels:
                labels.append(b["label"])
    has_naive = any(e.get("naive_rw") is not None for _, e in rows)
    errs = [e["abs_error"] for _, e in rows]
    errs += [e["naive_abs_error"] for _, e in rows if e.get("naive_abs_error") is not None]
    errs += [b["abs_error"] for _, e in rows for b in e.get("benchmarks", [])]
    top = max(errs) or 1.0

    def bar(v: float, ours: bool = False) -> str:
        return (f'<span class="fc-mbar" aria-hidden="true"><i class="{"is-ours" if ours else ""}" '
                f'style="width:{v / top * 100:.0f}%"></i></span>')

    head = ['<th scope="col">Target</th>',
            f'<th scope="col" class="num">{icon("target", "fc-ic fc-th-ic")}This round</th>']
    if has_naive:
        head.append(f'<th scope="col" class="num">{icon("equal", "fc-ic fc-th-ic")}No change</th>')
    show = {SEF_LABEL: "BoE survey of external forecasters (Apr 2026)"}
    head += [f'<th scope="col" class="num">{icon("file", "fc-ic fc-th-ic")}{esc(show.get(lbl, lbl).replace("BoE SEF", "BoE survey of external forecasters"))}</th>' for lbl in labels]
    body += [
        '      <details class="fc-more" id="benchmarks">',
        f'        <summary>{icon("scale")}<span>Against the benchmarks <span class="fc-more-sub">absolute error on the same outturns</span></span>{icon("chev", "fc-ic fc-chev")}</summary>',
        '        <div class="fc-more-body">',
        '      <div class="table-scroll">',
        '        <table class="scoreboard sb-grid" data-stack="yes">',
        "          <caption>Absolute error against the same outturn, in percentage "
        "points; each benchmark's own value beneath. A benchmark appears only beside "
        "rounds fixed after it was published, so a later edition never sits beside an "
        "earlier forecast; the October 2026 EFO and November 2026 MPR, published after "
        "2026Q3 ended, are close to nowcasts for it. They show where views differed, "
        "not a test of skill.</caption>",
        "          <thead><tr>" + "".join(head) + "</tr></thead>",
        "          <tbody>",
    ]
    for _, e in rows:
        cells = [f'<th scope="row">{_target(e)}</th>',
                 f'<td class="num"><strong>{e["abs_error"]:.2f}</strong>{bar(e["abs_error"], True)}</td>']
        if has_naive:
            cells.append(
                f'<td class="num">{e["naive_abs_error"]:.2f}{bar(e["naive_abs_error"])}'
                f'<span class="sb-sub">{e["naive_rw"]:.2f}%</span></td>'
                if e.get("naive_rw") is not None else '<td class="num">—</td>'
            )
        by_label = {b["label"]: b for b in e.get("benchmarks", [])}
        if labels and not by_label:
            cells.append(f'<td colspan="{len(labels)}"><span class="sb-sub">'
                         "no published quarterly path</span></td>")
        else:
            for lbl in labels:
                b = by_label.get(lbl)
                cells.append(
                    f'<td class="num">{b["abs_error"]:.2f}{bar(b["abs_error"])}'
                    f'<span class="sb-sub">{b["value"]:.2f}%</span></td>'
                    if b else '<td class="num">—</td>'
                )
        body.append("          <tr>" + "".join(cells) + "</tr>")
    body += ["          </tbody>", "        </table>", "      </div>"]

    notes = []
    if has_naive:
        notes.append(
            "No change is the naive baseline: "
            + esc(NAIVE_NOTE.split(": ", 1)[1]) + " This is the driftless walk; the "
            '<a href="#limits">limits</a> say what happens against a walk with drift.'
        )
    body += [f"        <p>{n}</p>" for n in notes]
    body += ["        </div>", "      </details>"]
    return "\n".join(body)


_LUCIDE = {
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "archive": '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
}


def _lucide(name: str, size: int, cls: str = "i", hidden: bool = False) -> str:
    return (f'<svg{" hidden" if hidden else ""} class="{cls}" viewBox="0 0 24 24" width="{size}" height="{size}" '
            'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{_LUCIDE[name]}</svg>')


def render_home_record(card: dict) -> str:
    """The home page's record card (index.html), from the same scorecard as
    the /forecasts scoreboard, so the two can never disagree: a dot per scored
    forecast, grouped by target quarter, coloured by where the outturn fell.
    "Expected" is the nominal coverage of the 68% band times the count. The
    small-sample warning stays beside the counts (DESIGN.md §7.5)."""
    pairs = scored_entries(card)
    scored = len(pairs)
    rounds = len({d["round_id"] for d, _ in pairs})
    in68 = sum(1 for _, e in pairs if e["in_68"])
    st = record_stats(card)
    name = {"gdp": "GDP", "cpi": "CPI", "unemployment": "Unemployment"}
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

    def who(d: dict) -> str:
        m = str(d.get("model", ""))
        return ", BoE SVAR satellite" if m == "okun-unemployment" else ""

    def day(round_id: str) -> str:
        y, mo, dd = round_id[:10].split("-")
        return f"{int(dd)} {months[int(mo) - 1]}"

    def where(e: dict) -> tuple[str, str]:
        if e["in_68"]:
            return "lp-rdot-68", "Inside the 68% band."
        if e["in_90"]:
            return "lp-rdot-90", "Inside the 90% band."
        return "lp-rdot-out", "Outside the 90% band."

    periods = sorted({e["period"] for _, e in pairs})
    groups = []
    for g, period in enumerate(periods, 1):
        items = []
        for d, e in pairs:
            if e["period"] != period:
                continue
            cls, verdict = where(e)
            text = esc(f"{name.get(e['variable'], e['variable'])}{who(d)}, {day(d['round_id'])} forecast: "
                       f"{e['forecast']:.2f} vs outturn {e['outturn']:.2f}. {verdict}")
            items.append(f'<li><span class="lp-rdot {cls}" aria-hidden="true" title="{text}"></span>'
                         f'<span class="visually-hidden">{text}</span></li>')
        groups.append(
            f'          <div class="lp-dotgroup"><span class="lp-dotgroup-l mono" id="rec-g{g}">{period}</span>'
            f'<ol aria-labelledby="rec-g{g}">{"".join(items)}</ol></div>'
        )
    misses = list(dict.fromkeys(f"{name.get(e['variable'], e['variable'])}{who(d)}"
                                for d, e in pairs if not e["in_90"]))
    order = [v for v in ("cpi", "gdp", "unemployment") if any(e["variable"] == v for _, e in pairs)]
    subjects = ", ".join(name[v] if v != "unemployment" else "unemployment" for v in order)
    if periods and periods[0][:4] == periods[-1][:4]:
        span = (f'<span class="mono">{periods[0]}</span>&ndash;<span class="mono">{periods[-1][4:]}</span>'
                if len(periods) > 1 else f'<span class="mono">{periods[0]}</span>')
    elif periods:
        span = f'<span class="mono">{periods[0]}</span>&ndash;<span class="mono">{periods[-1]}</span>'
    else:
        span = ""
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return "\n".join([
        '        <div class="lp-score-head">',
        f'          <span class="icon-tile">{_lucide("target", 20)}</span>',
        '          <div class="lp-score-title">',
        '            <h2 id="record-h">Forecast record</h2>',
        f'            <p>UK &middot; {subjects} &middot; {span}</p>',
        "          </div>",
        "        </div>",
        '        <div class="lp-rec">',
        '          <div class="lp-rec-viz">',
        '          <div class="lp-dots">',
        *groups,
        "          </div>",
        '          <ul class="lp-dotkey">',
        '            <li><span class="lp-rdot lp-rdot-68" aria-hidden="true"></span>Inside 68%</li>',
        '            <li><span class="lp-rdot lp-rdot-90" aria-hidden="true"></span>Inside 90%</li>',
        f'            <li><span class="lp-rdot lp-rdot-out" aria-hidden="true"></span>Outside 90%: {esc("; ".join(misses)) if misses else "none"}</li>',
        "          </ul>",
        "          </div>",
        '          <dl class="lp-recstats">',
        f'            <div><dt>inside the 68% band, made before the outturn</dt><dd>{st["exante_in68"]}<small> of {st["exante"]}</small></dd></div>',
        f'            <div><dt>bias, mean error</dt><dd>{"&minus;" if st["bias"] < 0 else "+"}{abs(st["bias"]):.2f}<small>pp</small></dd></div>',
        "          </dl>",
        "        </div>",
        f'        <p class="lp-score-foot"><span class="chip chip-warn">{_lucide("alert", 14)}Too few to show skill</span>'
        f'<span>{plural(scored, "forecast")} of {plural(st["outturns"], "outturn")}; {st["retro"]} archived retroactively.</span>'
        '<a href="/forecasts#scored">See every score &rarr;</a></p>',
    ])


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
            + render_vs_official_variable("cpi", include_note=True)
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


HOME = ROOT / "index.html"


def render_home(html: str, card: dict) -> str:
    pattern = re.compile(r"(<!-- home-record:begin -->\n).*?(<!-- home-record:end -->)", re.DOTALL)
    if not pattern.search(html):
        raise SystemExit(f"{HOME}: marker home-record not found")
    return pattern.sub(lambda m: m.group(1) + render_home_record(card) + "\n" + m.group(2), html, count=1)


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
    home_now = HOME.read_text()
    home_fresh = render_home(home_now, fresh)

    if args.check:
        stale = []
        if not SCORECARD.exists():
            stale.append("scorecard.json missing")
        elif SCORECARD.read_text() != rendered:
            stale.append("scorecard.json is stale")
        if page_now != page_fresh:
            stale.append("forecasts/index.html is stale")
        if home_now != home_fresh:
            stale.append("index.html record strip is stale")
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
    if home_now != home_fresh:
        HOME.write_text(home_fresh)
        print(f"updated {HOME.relative_to(ROOT)}")
    print(f"wrote {SCORECARD.relative_to(ROOT)} — {fresh['status']}")
    if fresh["next_period_to_score"]:
        print(f"next period to score: {fresh['next_period_to_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
