#!/usr/bin/env python3
"""Archive a forecast round ahead of an announced release.

Run:  python3 forecasts/nowcast.py --due 3      # is a tracked release near?
      python3 forecasts/nowcast.py              # generate and archive a round
      python3 forecasts/nowcast.py --payload f  # from a saved response, no network

Why this exists
---------------
The track record is only evidence once it has scored observations, and it was
accumulating them at the rate rounds happened to be generated: three rounds in
three weeks, because a round was a by-product of someone refreshing the moving
artifact behind the hero chart. Nothing tied a round to the moment it is worth
having one — immediately before an outturn is published.

This ties them together. `data/latest/*.json` already carries each ONS series'
announced ``next_release``, so the release calendar decides when a round is
due, the forecast is generated from the hosted model, and the round is archived
before the answer exists. That is the same claim ``archive.py`` makes, made on
a schedule rather than by hand.

Why the hosted server rather than a local solve
-----------------------------------------------
``forecast_uk`` on the deployed MCP server is the same boe-svar the site
publishes, so a round generated here is the production model's answer, not a
second implementation of it. It also keeps this script dependency-light — the
scheduled job installs an MCP client, not scipy and a VAR package — and it
exercises the public endpoint on a schedule, which is its own small guarantee.

Why this refuses more often than it writes
------------------------------------------
Rounds are append-only and CI enforces it, so a bad round is permanent: it
cannot be corrected, only superseded, and it stays in the denominator of every
accuracy statistic forever. This script therefore treats archiving as the
exceptional outcome and refuses on anything suspicious — a thin posterior, a
weak-identification warning, a data edge it has already archived, an existing
round for today. A missed round costs one observation; a junk round is a
permanent lie about what the model said.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
ROUNDS = HERE / "rounds"
LATEST = ROOT / "data" / "latest"

MCP_URL = "https://policyengine--policyengine-macro-mcp-serve.modal.run/mcp"
MODEL = "boe-svar"
SCHEMA_VERSION = 1

# The series whose releases produce the outturns this model is scored on.
# A release of anything else (debt, vacancies, investment) is not a reason to
# stake a new claim about GDP and CPI.
SCORED_SERIES = ("uk_gdp_cvm", "uk_cpi_yoy", "uk_unemployment_rate")

# forecast_uk's own guidance: below ~5900 draws the sign-identification step
# accepts too few, and the bands are noise. Existing archived rounds used 5600.
DEFAULT_DRAWS = 6000
HORIZONS = 13

# A response carrying any of these is refused. They are the model telling us
# the posterior is too thin to publish, and an archived round cannot be undone.
FATAL_WARNING_MARKERS = (
    "weak identification",
    "effective sample size",
    "may be noisy",
)

# Mapping from the tool's response arrays to the round's variable names.
SERIES_KEYS = {"gdp": "gdp_growth_yoy", "cpi": "cpi_inflation_yoy"}
BAND_KEYS = ("median", "lo68", "hi68", "lo90", "hi90")


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


# ------------------------------------------------------------------ due

def announced_releases() -> list[tuple[date, str]]:
    """(date, series) for every scored series with an announced next release."""
    found = []
    for name in SCORED_SERIES:
        path = LATEST / f"{name}.json"
        if not path.exists():
            continue
        raw = " ".join(
            (json.loads(path.read_text()).get("next_release") or "").split()
        )
        if not raw:
            continue
        try:
            found.append((datetime.strptime(raw, "%d %B %Y").date(), name))
        except ValueError:
            # An unparseable date is reported, never guessed at: guessing here
            # would stake a forecast against the wrong release.
            print(f"warning: {name} has an unparseable next_release {raw!r}")
    return sorted(found)


def due(within_days: int, today: date) -> list[tuple[date, str]]:
    """Releases landing in the next ``within_days`` days, today included."""
    return [
        (when, name)
        for when, name in announced_releases()
        if 0 <= (when - today).days <= within_days
    ]


# ------------------------------------------------------------- generate

def fetch_forecast(draws: int, horizons: int) -> dict:
    """Call forecast_uk on the deployed server. Imported lazily so --due needs
    no MCP client installed."""
    import anyio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def call() -> dict:
        async with streamablehttp_client(MCP_URL, timeout=600) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "forecast_uk", {"horizons": horizons, "draws": draws}
                )
                if result.isError:
                    raise SystemExit(f"forecast_uk failed: {result.content}")
                return json.loads(result.content[0].text)

    return anyio.run(call)


def refuse_on_warnings(response: dict) -> None:
    for warning in response.get("warnings") or []:
        lowered = warning.lower()
        if any(marker in lowered for marker in FATAL_WARNING_MARKERS):
            raise SystemExit(
                "refusing to archive: the model warned about the posterior it "
                f"just produced —\n  {warning}\n"
                "Rounds are append-only, so this would be permanent. Re-run "
                "with more draws."
            )


def to_forecast_block(response: dict) -> dict:
    """Reshape the tool's per-variable arrays into the round's period map."""
    periods: dict[str, dict] = {}
    for variable, key in SERIES_KEYS.items():
        rows = response.get(key)
        if not rows:
            raise SystemExit(f"forecast_uk returned no {key}")
        for row in rows:
            bands = {band: row[band] for band in BAND_KEYS if band in row}
            missing = set(BAND_KEYS) - set(bands)
            if missing:
                raise SystemExit(
                    f"{key} {row.get('quarter')}: missing {sorted(missing)}"
                )
            periods.setdefault(row["quarter"], {})[variable] = bands
    return dict(sorted(periods.items()))


def build_round(response: dict, generated: str) -> dict:
    forecast = to_forecast_block(response)
    periods = sorted(forecast)
    upstream = response.get("provenance") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "model": {
            "name": MODEL,
            "generated": generated,
            "estimation_sample": upstream.get("estimation_sample"),
            "draws": response.get("draws"),
            "accepted": response.get("accepted_draws"),
            "paths_per_draw": None,
            "source_pipeline": (
                f"{upstream.get('package', 'boe_var')} via the hosted MCP server"
            ),
        },
        "information_set": {
            "data_edge": response.get("forecast_origin"),
            "forecast_start": periods[0] if periods else None,
            "first_period": periods[0] if periods else None,
            "last_period": periods[-1] if periods else None,
        },
        "units": response.get("units"),
        "variables": sorted({v for p in forecast.values() for v in p}),
        # No source file to hash: this round came off the wire, so provenance
        # records the endpoint and the server's own version stamps instead.
        "provenance": {
            "source_path": None,
            "source_sha256": None,
            "site_commit": git("rev-parse", "HEAD"),
            "endpoint": MCP_URL,
            "tool": "forecast_uk",
            "model_version": upstream.get("model_version"),
            "adapter_version": upstream.get("adapter_version"),
            "source_revision": upstream.get("source_revision"),
            "ess": response.get("ess"),
            "warnings": response.get("warnings") or [],
        },
        "benchmarks": {
            "random_walk": None, "drift": None, "ar1": None, "official": None
        },
        "forecast": forecast,
    }


def archived_data_edges() -> set[str]:
    """Data edges already on the record for this model."""
    edges = set()
    for path in sorted(ROUNDS.glob(f"*/{MODEL}.json")):
        edge = json.loads(path.read_text()).get("information_set", {}).get("data_edge")
        if edge:
            edges.add(edge)
    return edges


def write_round(payload: dict, round_id: str, allow_same_edge: bool) -> int:
    target = ROUNDS / round_id / f"{MODEL}.json"
    if target.exists():
        print(f"{target.relative_to(ROOT)} already exists; rounds are append-only")
        return 1

    edge = payload["information_set"]["data_edge"]
    if not allow_same_edge and edge in archived_data_edges():
        # Same information set, so the claim is not new. Archiving it would
        # inflate the round count without adding evidence, and every duplicate
        # dilutes the record it is supposed to build.
        print(
            f"data edge {edge} is already archived and nothing new has been "
            "released; no round written (use --allow-same-edge to override)"
        )
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    payload["round_id"] = round_id
    payload["archived_utc"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        .replace("+00:00", "Z")
    )
    target.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"archived {target.relative_to(ROOT)} — data edge {edge}, "
        f"{len(payload['forecast'])} periods, {payload['model']['accepted']} "
        f"accepted draws"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--due", type=int, metavar="DAYS",
        help="exit 0 if a scored series releases within DAYS, else exit 1",
    )
    ap.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    ap.add_argument("--horizons", type=int, default=HORIZONS)
    ap.add_argument("--round", help="round id (default: today, UTC)")
    ap.add_argument(
        "--payload", type=Path,
        help="a saved forecast_uk response; skips the network call",
    )
    ap.add_argument(
        "--allow-same-edge", action="store_true",
        help="archive even if this data edge is already on the record",
    )
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()

    if args.due is not None:
        upcoming = due(args.due, today)
        for when, name in upcoming:
            print(f"{when.isoformat()}  {name}")
        if not upcoming:
            print(f"no scored series releases within {args.due} days of {today}")
            return 1
        return 0

    if args.payload:
        response = json.loads(args.payload.read_text())
    else:
        response = fetch_forecast(args.draws, args.horizons)

    refuse_on_warnings(response)
    payload = build_round(response, generated=today.isoformat())
    return write_round(payload, args.round or today.isoformat(), args.allow_same_edge)


if __name__ == "__main__":
    raise SystemExit(main())
