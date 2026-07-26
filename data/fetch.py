#!/usr/bin/env python3
"""Fetch UK official statistics and market data into an append-only vintage store.

Run:  python3 data/fetch.py                  # fetch every series
      python3 data/fetch.py --series uk_cpi_yoy
      python3 data/fetch.py --check          # validate the store, fetch nothing

Why vintages
------------
Official statistics are revised, sometimes years later. A site that always reads
"the latest data" quietly rewrites its own history every time the ONS revises a
quarter: a forecast that never changed can be made to look better or worse by a
revision it could not have known about. Worse, it makes look-ahead bias
invisible — you cannot tell whether an analysis used data that existed at the
time, because only one version is ever on disk.

So every fetch writes a dated snapshot under ``vintages/`` and nothing is ever
edited in place. ``latest/`` holds a flattened copy for the site to read at build
time, because the published pages are static under a CSP that forbids
cross-origin fetches — the browser never talks to the ONS.

Storage format is JSON rather than Parquet on purpose: these series are small,
and a git-diffable format means a revision shows up as a reviewable diff instead
of an opaque binary blob.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VINTAGES = HERE / "vintages"
LATEST = HERE / "latest"
MANIFEST = HERE / "MANIFEST.json"

# ONS rejects the default urllib agent with a 403.
USER_AGENT = "PolicyEngine-Macro/1.0 (+https://policyengine-macro.vercel.app)"

# The ONS time-series API is keyed by CDID and source dataset, reached through
# the topic path the series is published under.
ONS_SERIES = {
    "uk_gdp_cvm": {
        "path": "economy/grossdomesticproductgdp/timeseries/abmi/qna",
        "title": "UK real GDP, chained volume measure, seasonally adjusted",
        "frequency": "quarterly",
        "units": "£m, chained volume measure",
        "cdid": "ABMI",
    },
    "uk_cpi_yoy": {
        "path": "economy/inflationandpriceindices/timeseries/d7g7/mm23",
        "title": "UK CPI annual rate, all items",
        "frequency": "quarterly",
        "units": "percent, year-on-year",
        "cdid": "D7G7",
    },
    "uk_unemployment_rate": {
        "path": "employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms",
        "title": "UK unemployment rate, aged 16 and over, seasonally adjusted",
        "frequency": "quarterly",
        "units": "percent",
        "cdid": "MGSX",
    },
    "uk_core_cpi_yoy": {
        "path": "economy/inflationandpriceindices/timeseries/dko8/mm23",
        "title": "UK core CPI annual rate",
        "frequency": "monthly",
        "units": "percent, year-on-year",
        "cdid": "DKO8",
    },
    "uk_average_weekly_earnings": {
        "path": (
            "employmentandlabourmarket/peopleinwork/earningsandworkinghours/"
            "timeseries/kab9/lms"
        ),
        "title": "Average weekly earnings, whole economy, total pay",
        "frequency": "monthly",
        "units": "£ per week, seasonally adjusted",
        "cdid": "KAB9",
    },
    "uk_vacancies": {
        "path": (
            "employmentandlabourmarket/peopleinwork/employmentandemployeetypes/"
            "timeseries/ap2y/lms"
        ),
        "title": "UK vacancies",
        "frequency": "monthly",
        "units": "thousands, seasonally adjusted three-month average",
        "cdid": "AP2Y",
    },
    "uk_monthly_gva": {
        "path": "economy/grossdomesticproductgdp/timeseries/ecy2/mgdp",
        "title": "UK monthly gross value added",
        "frequency": "monthly",
        "units": "index, chained volume measure, seasonally adjusted",
        "cdid": "ECY2",
    },
    "uk_public_sector_net_borrowing": {
        "path": (
            "economy/governmentpublicsectorandtaxes/publicsectorfinance/"
            "timeseries/j5ii/pusf"
        ),
        "title": "Public sector net borrowing excluding public sector banks",
        "frequency": "monthly",
        "units": "£m, current prices, not seasonally adjusted",
        "cdid": "J5II",
    },
    "uk_public_sector_net_debt_gdp": {
        "path": (
            "economy/governmentpublicsectorandtaxes/publicsectorfinance/"
            "timeseries/hf6x/pusf"
        ),
        "title": "Public sector net debt excluding public sector banks",
        "frequency": "monthly",
        "units": "percent of GDP, not seasonally adjusted",
        "cdid": "HF6X",
    },
    "uk_business_investment": {
        "path": "economy/grossdomesticproductgdp/timeseries/npel/ukea",
        "title": "UK business investment",
        "frequency": "quarterly",
        "units": "£m, chained volume measure, seasonally adjusted",
        "cdid": "NPEL",
    },
}

BOE_URL = "https://www.bankofengland.co.uk/boeapps/database/"
BOE_CSV = BOE_URL + "_iadb-fromshowcolumns.asp"
BOE_START = "01/Jan/2020"
BOE_SERIES = {
    "uk_bank_rate": {
        "cdid": "IUDBEDR",
        "title": "Official Bank Rate",
        "description": "Wholesale interest and discount rates, Official Bank Rate, Daily",
    },
    "uk_gilt_5y": {
        "cdid": "IUDSNPY",
        "title": "UK nominal par yield, 5 year",
        "description": "British Government Securities nominal par yield, 5 year, Daily",
    },
    "uk_gilt_10y": {
        "cdid": "IUDMNPY",
        "title": "UK nominal par yield, 10 year",
        "description": "British Government Securities nominal par yield, 10 year, Daily",
    },
    "uk_gilt_20y": {
        "cdid": "IUDLNPY",
        "title": "UK nominal par yield, 20 year",
        "description": "British Government Securities nominal par yield, 20 year, Daily",
    },
}


# ---------------------------------------------------------------- fetching

def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8-sig")


def parse_quarters(payload: dict) -> list[dict]:
    """ONS quarterly rows -> [{period: '2026Q1', value: float}], oldest first."""
    out = []
    for row in payload.get("quarters", []):
        year, quarter = row.get("year"), row.get("quarter")
        if not year or not quarter:
            continue
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            # A published-but-empty cell is not a zero. Skip it rather than
            # invent an observation.
            continue
        out.append({"period": f"{year}{quarter}", "value": value})
    out.sort(key=lambda r: r["period"])
    return out


def parse_months(payload: dict) -> list[dict]:
    """ONS monthly rows -> [{period: '2026-06', value: float}], oldest first."""
    month_numbers = {
        name: number
        for number, name in enumerate(
            (
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ),
            start=1,
        )
    }
    out = []
    for row in payload.get("months", []):
        year, month = row.get("year"), row.get("month")
        if not year or month not in month_numbers:
            continue
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(
            {"period": f"{year}-{month_numbers[month]:02d}", "value": value}
        )
    out.sort(key=lambda row: row["period"])
    return out


def release_stamp(payload: dict) -> str | None:
    """Latest updateDate across observations — when this vintage was published."""
    stamps = [
        row.get("updateDate")
        for row in payload.get("quarters", []) + payload.get("months", [])
        if row.get("updateDate")
    ]
    return max(stamps) if stamps else None


def build_snapshot(name: str, spec: dict, payload: dict) -> dict:
    observations = (
        parse_months(payload)
        if spec["frequency"] == "monthly"
        else parse_quarters(payload)
    )
    if not observations:
        raise SystemExit(f"{name}: no quarterly observations parsed — refusing to write")

    return {
        "series": name,
        "source": "ONS",
        "cdid": spec["cdid"],
        "title": payload.get("description", {}).get("title") or spec["title"],
        "frequency": spec["frequency"],
        "units": spec["units"],
        "url": f"https://www.ons.gov.uk/{spec['path']}/data",
        "release_updated": release_stamp(payload),
        "next_release": payload.get("description", {}).get("nextRelease") or None,
        "first_period": observations[0]["period"],
        "last_period": observations[-1]["period"],
        "observations": observations,
    }


def same_data(a: dict, b: dict) -> bool:
    """Compare only the payload, ignoring when we happened to fetch it."""
    keys = (
        "observations",
        "release_updated",
        "next_release",
        "last_period",
        "title",
        "units",
    )
    return all(a.get(k) == b.get(k) for k in keys)


def latest_vintage(series_dir: Path) -> Path | None:
    files = sorted(series_dir.glob("*.json"))
    return files[-1] if files else None


def fetch_series(name: str, spec: dict, vintage: str) -> str:
    """Returns one of 'written', 'unchanged', 'exists'."""
    payload = get_json(f"https://www.ons.gov.uk/{spec['path']}/data")
    snapshot = build_snapshot(name, spec, payload)

    series_dir = VINTAGES / "ons" / name
    previous = latest_vintage(series_dir)
    if previous and same_data(json.loads(previous.read_text()), snapshot):
        # Nothing changed upstream. Writing a new vintage anyway would bury the
        # real revisions in a stream of identical files.
        return "unchanged"

    out = series_dir / f"{vintage}.json"
    if out.exists():
        return "exists"

    snapshot["vintage"] = vintage
    snapshot["fetched_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    series_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2) + "\n")
    return "written"


def fetch_boe_series(name: str, spec: dict, vintage: str) -> str:
    query = urllib.parse.urlencode(
        {
            "csv.x": "yes",
            "Datefrom": BOE_START,
            "Dateto": "now",
            "SeriesCodes": spec["cdid"],
            "CSVF": "TN",
            "UsingCodes": "Y",
            "VPD": "Y",
            "VFD": "N",
        }
    )
    rows = csv.DictReader(io.StringIO(get_text(f"{BOE_CSV}?{query}")))
    observations = []
    for row in rows:
        raw_date, raw_value = row.get("DATE"), row.get(spec["cdid"])
        if not raw_date or raw_value in (None, ""):
            continue
        period = datetime.strptime(raw_date.strip(), "%d %b %Y").strftime("%Y-%m-%d")
        observations.append({"period": period, "value": float(raw_value)})
    if not observations:
        raise SystemExit(f"{name}: no Bank of England observations parsed")

    snapshot = {
        "series": name,
        "source": "Bank of England",
        "cdid": spec["cdid"],
        "title": spec["title"],
        "description": spec["description"],
        "frequency": "daily",
        "units": "percent",
        "url": BOE_URL,
        "release_updated": observations[-1]["period"],
        "first_period": observations[0]["period"],
        "last_period": observations[-1]["period"],
        "observations": observations,
    }
    series_dir = VINTAGES / "boe" / name
    previous = latest_vintage(series_dir)
    if previous and same_data(json.loads(previous.read_text()), snapshot):
        return "unchanged"
    out = series_dir / f"{vintage}.json"
    if out.exists():
        return "exists"
    snapshot["vintage"] = vintage
    snapshot["fetched_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    series_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2) + "\n")
    return "written"


# ---------------------------------------------------------------- derived files

def rebuild_latest() -> list[str]:
    """Flatten the newest vintage of each series into latest/ for the site."""
    LATEST.mkdir(parents=True, exist_ok=True)
    written = []
    for source_dir in sorted(VINTAGES.glob("*")):
        for series_dir in sorted(source_dir.glob("*")):
            newest = latest_vintage(series_dir)
            if not newest:
                continue
            (LATEST / f"{series_dir.name}.json").write_text(newest.read_text())
            written.append(series_dir.name)
    return written


def rebuild_manifest() -> dict:
    entries = {}
    for source_dir in sorted(VINTAGES.glob("*")):
        for series_dir in sorted(source_dir.glob("*")):
            vintages = sorted(p.stem for p in series_dir.glob("*.json"))
            if not vintages:
                continue
            newest = json.loads((series_dir / f"{vintages[-1]}.json").read_text())
            entries[series_dir.name] = {
                "source": newest["source"],
                "cdid": newest["cdid"],
                "title": newest["title"],
                "units": newest["units"],
                "frequency": newest["frequency"],
                "url": newest["url"],
                "vintages": vintages,
                "latest_vintage": vintages[-1],
                "release_updated": newest.get("release_updated"),
                "next_release": newest.get("next_release"),
                "coverage": [newest["first_period"], newest["last_period"]],
            }

    manifest = {
        "_comment": (
            "Generated by data/fetch.py. Every series is stored as dated, "
            "append-only vintages under data/vintages/; latest/ is a flattened "
            "copy for the static site. Licence: ONS and Bank of England data "
            "are released under the Open Government Licence v3.0."
        ),
        "licence": "Open Government Licence v3.0",
        "series": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# ---------------------------------------------------------------- check

def check() -> int:
    problems = []

    if not (VINTAGES / "ons").exists():
        print("no vintages stored yet")
        return 0

    for path in sorted(VINTAGES.glob("*/*/*.json")):
        rel = path.relative_to(HERE)
        data = json.loads(path.read_text())
        if data.get("vintage") != path.stem:
            problems.append(f"{rel}: vintage {data.get('vintage')!r} does not match its filename")
        if not data.get("observations"):
            problems.append(f"{rel}: no observations")
        periods = [o["period"] for o in data.get("observations", [])]
        if periods != sorted(periods):
            problems.append(f"{rel}: observations are not in period order")
        if len(set(periods)) != len(periods):
            problems.append(f"{rel}: duplicate periods")

    fresh = json.dumps(rebuild_manifest(), indent=2) + "\n"
    if MANIFEST.read_text() != fresh:
        problems.append("MANIFEST.json is stale — run data/fetch.py")

    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1

    files = list(VINTAGES.glob("*/*/*.json"))
    series = list(VINTAGES.glob("*/*"))
    print(f"OK — {len(files)} vintage file(s) across {len(series)} series")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--series", help="fetch a single series by name")
    ap.add_argument("--check", action="store_true", help="validate the store, fetch nothing")
    ap.add_argument("--vintage", help="vintage date (default: today, UTC)")
    args = ap.parse_args()

    if args.check:
        return check()

    vintage = args.vintage or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_series = {
        **{name: ("ons", spec) for name, spec in ONS_SERIES.items()},
        **{name: ("boe", spec) for name, spec in BOE_SERIES.items()},
    }
    if args.series and args.series not in all_series:
        ap.error(f"unknown series {args.series!r}")
    wanted = {args.series: all_series[args.series]} if args.series else all_series

    failures = 0
    for name, (source, spec) in wanted.items():
        try:
            result = (
                fetch_series(name, spec, vintage)
                if source == "ons"
                else fetch_boe_series(name, spec, vintage)
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            # A transient upstream failure must not look like "no revision".
            print(f"FAIL {name}: {type(exc).__name__} {exc}", file=sys.stderr)
            failures += 1
            continue
        print(f"{result:>9}  {name}")

    rebuild_latest()
    rebuild_manifest()
    print(f"\nmanifest and latest/ rebuilt")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
