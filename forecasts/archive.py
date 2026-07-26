#!/usr/bin/env python3
"""Archive a generated forecast into the immutable round history.

Run:  python3 forecasts/archive.py                    # archive the current artifact
      python3 forecasts/archive.py --check            # exit 1 if the history is inconsistent
      python3 forecasts/archive.py --round 2026-07-21 # override the round id

Why this exists
---------------
``papers/boe-svar/figures/current_forecast.json`` is a *moving* artifact: each
refresh of the data edge overwrites it in place, so the site always shows one
current forecast and the previous one survives only in git history. That is the
right behaviour for the hero chart and the wrong behaviour for a track record.

A forecast track record is only evidence if the forecast provably existed before
the outturn did. This script copies the moving artifact into
``forecasts/rounds/<round-id>/forecast.json``, which is **append-only**: rounds
are added, never edited. The commit timestamp on that file is what makes the
claim falsifiable, so the immutability is enforced in CI
(``.github/workflows/forecast-immutability.yml``) rather than by convention.

Scoring against outturns lives in ``forecasts/score.py`` and reads, but never
writes, the files under ``rounds/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
ROUNDS = HERE / "rounds"

# The moving artifacts this script snapshots. Adding a model here is how a new
# forecast joins the track record; the round layout is one file per model.
SOURCES = {
    "boe-svar": ROOT / "papers" / "boe-svar" / "figures" / "current_forecast.json",
}

SCHEMA_VERSION = 1


# ---------------------------------------------------------------- helpers

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str | None:
    """Return git output, or None when git is unavailable or the command fails."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def model_provenance(name: str, raw: dict) -> dict:
    """Everything needed to re-run this forecast, taken from the artifact itself.

    We deliberately do not invent fields the generator did not record: a missing
    value is stored as null so that a later reader can tell "not captured" from
    "captured as zero".
    """
    return {
        "name": name,
        "generated": raw.get("generated"),
        "estimation_sample": raw.get("estimation_sample"),
        "draws": raw.get("draws"),
        "accepted": raw.get("accepted"),
        "paths_per_draw": raw.get("paths_per_draw"),
        "source_pipeline": raw.get("source"),
    }


# ---------------------------------------------------------------- archive

def build_round(name: str, path: Path) -> dict:
    raw = json.loads(path.read_text())
    forecast = raw.get("forecast")
    if not forecast:
        raise SystemExit(f"{path}: no 'forecast' block to archive")

    periods = sorted(forecast)
    variables = sorted({v for p in forecast.values() for v in p})

    return {
        "schema_version": SCHEMA_VERSION,
        "model": model_provenance(name, raw),
        "information_set": {
            "data_edge": raw.get("data_edge"),
            "forecast_start": raw.get("forecast_start"),
            "first_period": periods[0] if periods else None,
            "last_period": periods[-1] if periods else None,
        },
        "units": raw.get("units"),
        "variables": variables,
        "provenance": {
            "source_path": str(path.relative_to(ROOT)),
            "source_sha256": sha256(path),
            "site_commit": git("rev-parse", "HEAD"),
        },
        # Benchmarks are the point of the exercise: a forecast with no naive
        # baseline beside it cannot be judged. boe-svar already computes
        # random-walk / drift / AR(1) comparisons pseudo-out-of-sample in
        # papers/boe-svar/figures/rolling_evaluation.json; the real-time
        # equivalents are filled in by score.py once outturns land.
        "benchmarks": {"random_walk": None, "drift": None, "ar1": None, "official": None},
        "forecast": forecast,
    }


def archive(round_id: str, force: bool = False) -> int:
    target = ROUNDS / round_id
    written = []

    for name, path in SOURCES.items():
        if not path.exists():
            print(f"skip {name}: {path} not found", file=sys.stderr)
            continue

        out = target / f"{name}.json"
        if out.exists() and not force:
            # Refusing here is the whole safety property. A round is a claim
            # about what was known on a date; silently rewriting it destroys
            # the claim.
            print(
                f"refusing to overwrite {out.relative_to(ROOT)} — "
                f"archive a new round id instead",
                file=sys.stderr,
            )
            return 1

        payload = build_round(name, path)
        payload["round_id"] = round_id
        payload["archived_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        target.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        written.append(out.relative_to(ROOT))

    if not written:
        print("nothing archived", file=sys.stderr)
        return 1

    for w in written:
        print(f"archived {w}")
    print("\ncommit this round before the outturn is published, or it is not evidence.")
    return 0


# ---------------------------------------------------------------- check

def check() -> int:
    """Validate the archived history without touching it."""
    problems = []

    if not ROUNDS.exists():
        print("no rounds archived yet")
        return 0

    for path in sorted(ROUNDS.glob("*/*.json")):
        rel = path.relative_to(ROOT)
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            problems.append(f"{rel}: unparseable ({exc})")
            continue

        if data.get("schema_version") != SCHEMA_VERSION:
            problems.append(
                f"{rel}: schema_version {data.get('schema_version')!r} "
                f"!= {SCHEMA_VERSION}"
            )
        if data.get("round_id") != path.parent.name:
            problems.append(
                f"{rel}: round_id {data.get('round_id')!r} does not match its directory"
            )
        if not data.get("forecast"):
            problems.append(f"{rel}: empty forecast block")
        if not data.get("information_set", {}).get("data_edge"):
            problems.append(f"{rel}: no data edge recorded — the forecast is unfalsifiable")

    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)

    if problems:
        return 1

    rounds = sorted({p.parent.name for p in ROUNDS.glob("*/*.json")})
    print(f"OK — {len(rounds)} round(s) archived: {', '.join(rounds)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="validate the archive, write nothing")
    ap.add_argument("--round", help="round id (default: the artifact's generated date)")
    ap.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing round — only for correcting a same-day mistake",
    )
    args = ap.parse_args()

    if args.check:
        return check()

    round_id = args.round
    if not round_id:
        # Default to the date the forecast was generated, not today: the round
        # is named for the information set, not for when someone got round to
        # archiving it.
        for path in SOURCES.values():
            if path.exists():
                round_id = json.loads(path.read_text()).get("generated")
                break
    if not round_id:
        print("could not determine a round id; pass --round", file=sys.stderr)
        return 1

    return archive(round_id, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
