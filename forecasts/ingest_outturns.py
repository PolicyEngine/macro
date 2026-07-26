#!/usr/bin/env python3
"""Turn the data vintage store into scoreable outturns.

Run:  python3 forecasts/ingest_outturns.py           # append newly available outturns
      python3 forecasts/ingest_outturns.py --check   # exit 1 if outturns.json is behind

Maps the variables the models forecast onto the ONS series in ``data/``, converts
them to the forecasts' units (year-on-year percent), and appends them to
``outturns.json`` tagged with the data vintage they were read from.

Appends, never edits. When the ONS revises a quarter's value, a later run adds a
second observation for that period under the new vintage; metadata-only
snapshots with an unchanged value do not create duplicate outturns. ``score.py``
scores against the newest observation but every earlier score stays
reproducible. Only periods that some archived round actually forecast are
ingested — this file is evidence for the track record, not a general data
mirror.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
ROUNDS = HERE / "rounds"
OUTTURNS = HERE / "outturns.json"
DATA = ROOT / "data" / "latest"


def yoy_from_levels(observations: list[dict]) -> dict[str, float]:
    """Year-on-year percent change from a quarterly level series."""
    by_period = {o["period"]: o["value"] for o in observations}
    out = {}
    for period, value in by_period.items():
        year, quarter = int(period[:4]), period[4:]
        prior = by_period.get(f"{year - 1}{quarter}")
        if prior:
            out[period] = (value / prior - 1) * 100
    return out


def passthrough(observations: list[dict]) -> dict[str, float]:
    """The series is already in the forecasts' units."""
    return {o["period"]: o["value"] for o in observations}


# Forecast variable -> the series it is scored against, and how to convert it.
MAPPING = {
    "gdp": {"series": "uk_gdp_cvm", "transform": yoy_from_levels},
    "cpi": {"series": "uk_cpi_yoy", "transform": passthrough},
}


def forecast_periods() -> dict[str, set[str]]:
    """Periods each variable has been forecast for, across all archived rounds."""
    wanted: dict[str, set[str]] = {}
    for path in sorted(ROUNDS.glob("*/*.json")):
        data = json.loads(path.read_text())
        for period, block in data["forecast"].items():
            for variable in block:
                wanted.setdefault(variable, set()).add(period)
    return wanted


def available() -> list[dict]:
    """Every outturn that some archived round forecast and the data now covers."""
    wanted = forecast_periods()
    rows = []

    for variable, periods in sorted(wanted.items()):
        spec = MAPPING.get(variable)
        if spec is None:
            print(f"skip {variable}: no series mapped in MAPPING", file=sys.stderr)
            continue

        path = DATA / f"{spec['series']}.json"
        if not path.exists():
            print(f"skip {variable}: {path.relative_to(ROOT)} not fetched", file=sys.stderr)
            continue

        doc = json.loads(path.read_text())
        values = spec["transform"](doc["observations"])
        for period in sorted(periods & set(values)):
            rows.append(
                {
                    "period": period,
                    "variable": variable,
                    "value": round(values[period], 6),
                    "vintage": doc["vintage"],
                    "series": spec["series"],
                    "release_updated": doc.get("release_updated"),
                }
            )
    return rows


def merge(existing: list[dict], fresh: list[dict]) -> tuple[list[dict], list[dict]]:
    """Append value revisions, ignoring newer snapshots whose value is unchanged."""
    latest: dict[tuple[str, str], dict] = {}
    for row in sorted(existing, key=lambda o: o.get("vintage", "")):
        latest[(row["period"], row["variable"])] = row

    added = []
    for row in fresh:
        key = (row["period"], row["variable"])
        prior = latest.get(key)
        if prior is not None and prior["value"] == row["value"]:
            continue
        added.append(row)
        latest[key] = row
    return existing + added, added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if outturns.json is behind")
    args = ap.parse_args()

    doc = json.loads(OUTTURNS.read_text())
    merged, added = merge(doc.get("observations", []), available())

    if args.check:
        if added:
            for row in added:
                print(f"FAIL missing outturn {row['variable']} {row['period']} "
                      f"({row['value']:.2f}, vintage {row['vintage']})", file=sys.stderr)
            print("run forecasts/ingest_outturns.py", file=sys.stderr)
            return 1
        print(f"OK — {len(merged)} outturn(s) recorded, none pending")
        return 0

    if not added:
        print("no new outturns available")
        return 0

    doc["observations"] = sorted(merged, key=lambda o: (o["period"], o["variable"], o["vintage"]))
    OUTTURNS.write_text(json.dumps(doc, indent=2) + "\n")

    for row in added:
        print(f"added {row['variable']:>4} {row['period']} = {row['value']:.2f} "
              f"(vintage {row['vintage']})")
    print("\nnow run forecasts/score.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
