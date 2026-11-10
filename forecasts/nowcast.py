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
import re
import subprocess
import urllib.request
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
ROUNDS = HERE / "rounds"
LATEST = ROOT / "data" / "latest"

MCP_URL = "https://policyengine--policyengine-macro-mcp-serve.modal.run/mcp"

# The hosted forecast_uk reads boe-var-model's bundled data at the commit the
# Modal image is built from (BOE_REVISION in integration/modal_app.py). Its
# last row is the data edge every round from the server will carry, so it can
# be read from GitHub for free instead of from a cold Modal container.
MODAL_APP = ROOT / "integration" / "modal_app.py"
BOE_DATA_URL = (
    "https://raw.githubusercontent.com/PolicyEngine/boe-var-model/{rev}/data/boe_var_data.csv"
)
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


def stale_calendar(today: date) -> list[tuple[date, str]] | None:
    """The announced releases, if every one of them is already in the past.

    ``next_release`` is only as current as data/latest. When the data store
    stops refreshing, each series' announced date slides into the past and
    ``due`` finds nothing — which looks exactly like a quiet week. That is how
    this job reported green every weekday from 17 September to November 2026
    while GDP, CPI and unemployment were all released unforecast. A calendar
    with no future date is not "nothing due"; it is a stale store, and it is
    reported as one. An empty calendar counts too: nothing to schedule against.
    """
    releases = announced_releases()
    if releases and any(when >= today for when, _ in releases):
        return None
    return releases


def due(within_days: int, today: date) -> list[tuple[date, str]]:
    """Releases landing in the next ``within_days`` days, today included."""
    return [
        (when, name)
        for when, name in announced_releases()
        if 0 <= (when - today).days <= within_days
    ]


# ------------------------------------------------------------ edge gate

def next_quarter(quarter: str) -> str:
    year, q = int(quarter[:4]), int(quarter[5])
    return f"{year + q // 4}Q{q % 4 + 1}"


def quarter_key(quarter: str) -> tuple[int, int]:
    return int(quarter[:4]), int(quarter[5])


def hosted_revision(text: str | None = None) -> str | None:
    """boe-var-model commit the deployed MCP image is built from."""
    if text is None:
        if not MODAL_APP.exists():
            return None
        text = MODAL_APP.read_text()
    found = re.search(r'^BOE_REVISION\s*=\s*"([0-9a-f]{7,40})"', text, re.M)
    return found.group(1) if found else None


def last_quarter(csv_text: str) -> str | None:
    """The last ``YYYYQn`` in the first column of boe_var_data.csv."""
    rows = [line.split(",", 1)[0].strip() for line in csv_text.splitlines()]
    quarters = [r for r in rows if re.fullmatch(r"\d{4}Q[1-4]", r)]
    return max(quarters, key=quarter_key) if quarters else None


def hosted_data_edge(revision: str) -> str | None:
    try:
        with urllib.request.urlopen(BOE_DATA_URL.format(rev=revision), timeout=30) as r:
            return last_quarter(r.read().decode())
    except OSError as exc:
        print(f"warning: could not read the hosted model's data ({exc})")
        return None


def edge_gate(hosted_edge: str | None, archived: set[str]) -> tuple[bool, str]:
    """(proceed, reason). A round is only worth a Modal call when the hosted
    model conditions on a quarter after every archived round's data edge;
    otherwise ``write_round`` refuses it as "already archived" after the
    container has done the whole solve. An unknown edge proceeds, so a GitHub
    outage can never silently stop rounds."""
    if hosted_edge is None:
        return True, "hosted data edge unknown; calling the model and letting write_round decide"
    if not archived:
        return True, f"hosted data edge {hosted_edge}; no round archived yet"
    latest = max(archived, key=quarter_key)
    required = next_quarter(latest)
    if quarter_key(hosted_edge) < quarter_key(required):
        return False, (
            f"skip: the hosted model's data ends {hosted_edge}, before {required}, "
            f"the first quarter a new round needs (latest archived edge {latest}); "
            "a call would only be refused as already archived, so no Modal call. "
            "Refresh boe-var-model data and re-pin BOE_REVISION in "
            "integration/modal_app.py (issue #224)"
        )
    return True, f"hosted data edge {hosted_edge} >= {required}; a new round is possible"


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
        help="exit 0 if a scored series releases within DAYS, 1 if none does, "
             "2 if the release calendar in data/latest is stale (no future date)",
    )
    ap.add_argument(
        "--edge-gate", action="store_true",
        help="exit 0 if the hosted model's data edge (read from GitHub, no Modal "
             "call) is newer than every archived round's, 1 if a round would "
             "only be refused as already archived",
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
        stale = stale_calendar(today)
        if stale is not None:
            last = max((when for when, _ in stale), default=None)
            print(
                "stale release calendar: no scored series has an announced "
                f"release on or after {today}"
                + (f" (latest announced {last.isoformat()})" if last else "")
                + " — data/latest has not been refreshed; merge the data "
                "vintage PR before a round can be scheduled"
            )
            for when, name in stale:
                print(f"{when.isoformat()}  {name}  (past)")
            return 2
        upcoming = due(args.due, today)
        for when, name in upcoming:
            print(f"{when.isoformat()}  {name}")
        if not upcoming:
            print(f"no scored series releases within {args.due} days of {today}")
            return 1
        return 0

    if args.edge_gate:
        revision = hosted_revision()
        edge = hosted_data_edge(revision) if revision else None
        proceed, reason = edge_gate(edge, archived_data_edges())
        print(f"boe-var-model {revision or 'unknown'}: {reason}")
        return 0 if proceed else 1

    if args.payload:
        response = json.loads(args.payload.read_text())
    else:
        response = fetch_forecast(args.draws, args.horizons)

    refuse_on_warnings(response)
    payload = build_round(response, generated=today.isoformat())
    return write_round(payload, args.round or today.isoformat(), args.allow_same_edge)


if __name__ == "__main__":
    raise SystemExit(main())
