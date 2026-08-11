"""Integrity of the append-only vintage store under ``data/``.

The class of regression this prevents
-------------------------------------
``data/README.md`` makes a strong claim: every number the site publishes can be
reproduced because the exact snapshot it was computed from is still on disk,
unedited. That claim is only as good as the store. Three ways it can quietly
stop being true:

* **A stale ``latest/``.** ``latest/<series>.json`` is a flattened copy of the
  newest vintage, and it is what the page builders read. If a vintage lands and
  ``rebuild_latest()`` does not run — a partial fetch, a hand-edited file, a
  merge that took one side — the site keeps rendering yesterday's numbers while
  the store contains today's, and nothing anywhere says so. Test 3 below is the
  one that catches it.
* **A mislabelled vintage.** The filename *is* the as-of date. A file whose
  ``vintage`` field disagrees with its name destroys the point-in-time
  reconstruction the README promises, silently.
* **A drifted MANIFEST.** ``MANIFEST.json`` is the published index. A series
  present on disk but missing from it is invisible to consumers; a series in it
  that is not on disk is a 404 for anyone who trusts it.

Relationship to ``data/fetch.py --check``
-----------------------------------------
``fetch.py --check`` already validates vintage/filename agreement, ordering and
duplicates, and regenerates MANIFEST.json to compare. These tests overlap on
purpose and go further where it matters: ``--check`` never looks at ``latest/``
at all, never checks period *formats* against the declared frequency, never
compares ``first_period``/``last_period`` against the observations they claim to
summarise, and never checks that a source URL points at the source it names.
Running under pytest also means a failure names one file per test rather than
aborting the whole validation on the first problem.

Conventions are inferred from the committed data, never imposed. The store uses
``YYYYQn`` for quarterly, ``YYYY-MM`` for monthly and ``YYYY-MM-DD`` for daily,
which is what ``fetch.py``'s parsers emit.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

# --------------------------------------------------------------- policy

# Keys every stored snapshot must carry, whatever its source. Deliberately the
# intersection of what the three fetchers emit, not the union: `next_release` is
# ONS/FRED-only (the Bank of England IADB does not announce one) and the three
# oldest ONS vintages predate the field, while `description` is Bank-of-England
# only. Requiring either would fail files that are correct as written — and the
# store is append-only, so those files can never be back-filled.
REQUIRED_KEYS = frozenset(
    {
        "series",
        "source",
        "cdid",
        "title",
        "frequency",
        "units",
        "url",
        "release_updated",
        "first_period",
        "last_period",
        "observations",
        "vintage",
        "fetched_utc",
    }
)

# Period grammar per declared frequency, read off the committed data:
# `parse_quarters` emits `2026Q2`, `parse_months` emits `2026-06`, and the
# Bank of England / FRED daily fetchers emit ISO dates.
PERIOD_PATTERNS = {
    "quarterly": re.compile(r"^\d{4}Q[1-4]$"),
    "monthly": re.compile(r"^\d{4}-(0[1-9]|1[0-2])$"),
    "daily": re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
}

# The host each publisher's data must actually come from. A snapshot that says
# "ONS" while pointing at some third-party mirror is an unattributed copy, and
# the OGL attribution in data/README.md would be wrong.
SOURCE_DOMAINS = {
    "ONS": "ons.gov.uk",
    "Bank of England": "bankofengland.co.uk",
    "FRED": "fred.stlouisfed.org",
}


# --------------------------------------------------------------- helpers

def _load(path: Path) -> dict:
    if not path.is_file():
        pytest.fail(f"{path} does not exist")
    return json.loads(path.read_text())


def _relative(path: Path) -> str:
    """Path as written in data/README.md, for failure messages."""
    return path.as_posix().split("/data/", 1)[-1]


def _parse_timestamp(value: str) -> datetime:
    """Parse the ISO-8601 forms the store uses, always tz-aware.

    ``fetched_utc`` is ``2026-08-10T08:08:49Z``; ``release_updated`` is either
    an ONS ``...T23:00:00.000Z`` stamp or a bare Bank of England date. A bare
    date is read as midnight UTC so the two are comparable.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _newest_vintage(series_dir: Path) -> Path:
    """The newest snapshot for a series.

    Filenames are ``YYYY-MM-DD.json``, so lexical order is date order — the
    same assumption ``fetch.py``'s ``latest_vintage()`` makes.
    """
    return sorted(series_dir.glob("*.json"))[-1]


# --------------------------------------------------------------- 1. shape

def test_vintage_file_is_valid_json_with_the_required_keys(vintage_path):
    """Each snapshot parses and carries the full documented key set."""
    try:
        payload = _load(vintage_path)
    except json.JSONDecodeError as error:  # pragma: no cover - failure path
        pytest.fail(f"data/{_relative(vintage_path)}: invalid JSON — {error}")

    assert isinstance(payload, dict), (
        f"data/{_relative(vintage_path)}: top level is "
        f"{type(payload).__name__}, expected an object"
    )
    missing = sorted(REQUIRED_KEYS - set(payload))
    assert not missing, (
        f"data/{_relative(vintage_path)}: missing required key(s) "
        f"{', '.join(missing)}"
    )


def test_vintage_matches_its_filename(vintage_path):
    """The filename is the as-of date; the field must agree with it.

    They are two independent records of the same fact, and point-in-time
    reconstruction reads the filename while consumers read the field.
    """
    payload = _load(vintage_path)
    assert payload.get("vintage") == vintage_path.stem, (
        f"data/{_relative(vintage_path)}: vintage field is "
        f"{payload.get('vintage')!r} but the file is named "
        f"{vintage_path.stem!r}"
    )
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", vintage_path.stem), (
        f"data/{_relative(vintage_path)}: filename is not a YYYY-MM-DD vintage date"
    )


def test_fetched_utc_is_iso_8601(vintage_path):
    """``fetched_utc`` has to be machine-readable to be evidence of anything."""
    payload = _load(vintage_path)
    raw = payload.get("fetched_utc")
    assert isinstance(raw, str) and raw, (
        f"data/{_relative(vintage_path)}: fetched_utc is {raw!r}"
    )
    try:
        _parse_timestamp(raw)
    except ValueError as error:  # pragma: no cover - failure path
        pytest.fail(
            f"data/{_relative(vintage_path)}: fetched_utc {raw!r} is not "
            f"ISO-8601 — {error}"
        )


# --------------------------------------------------------------- 2. series

def test_observations_are_well_formed(vintage_path):
    """The series itself: ordered, unique, numeric, and correctly labelled.

    All four problems are reported together — a corrupted fetch usually trips
    several at once, and fixing them one CI run at a time is wasteful.
    """
    payload = _load(vintage_path)
    name = f"data/{_relative(vintage_path)}"
    observations = payload.get("observations")

    assert isinstance(observations, list) and observations, (
        f"{name}: observations is empty — an empty snapshot is not a snapshot"
    )

    frequency = payload.get("frequency")
    pattern = PERIOD_PATTERNS.get(frequency)
    assert pattern is not None, (
        f"{name}: unknown frequency {frequency!r}; expected one of "
        f"{sorted(PERIOD_PATTERNS)}"
    )

    problems: list[str] = []
    periods: list[str] = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict) or "period" not in observation:
            problems.append(f"observations[{index}] = {observation!r} has no period")
            continue
        period = observation["period"]
        periods.append(period)
        if not isinstance(period, str) or not pattern.fullmatch(period):
            problems.append(
                f"observations[{index}].period = {period!r} does not match the "
                f"{frequency} convention {pattern.pattern}"
            )
        value = observation.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(
                f"observations[{index}] ({period}) value = {value!r} is not a number"
            )

    if periods != sorted(periods):
        first_break = next(
            (
                index
                for index in range(1, len(periods))
                if periods[index] < periods[index - 1]
            ),
            None,
        )
        problems.append(
            "periods are not in chronological order — "
            f"observations[{first_break}] ({periods[first_break]}) follows "
            f"{periods[first_break - 1]}"
            if first_break is not None
            else "periods are not in chronological order"
        )

    duplicates = sorted({period for period in periods if periods.count(period) > 1})
    if duplicates:
        problems.append(f"duplicate period(s): {', '.join(duplicates[:10])}")

    if periods:
        if payload.get("first_period") != periods[0]:
            problems.append(
                f"first_period is {payload.get('first_period')!r} but the first "
                f"observation is {periods[0]!r}"
            )
        if payload.get("last_period") != periods[-1]:
            problems.append(
                f"last_period is {payload.get('last_period')!r} but the last "
                f"observation is {periods[-1]!r}"
            )

    assert not problems, f"{name}:\n  " + "\n  ".join(problems)


def test_no_observation_runs_past_last_period(vintage_path):
    """``last_period`` is the store's advertised data edge.

    Anything beyond it is a value the snapshot claims not to have. Consumers
    slice on ``last_period`` — the release notes and the economy pages both do
    — so an observation past the edge is data that exists but is unreachable,
    or worse, a forecast that has leaked into an outturn file.
    """
    payload = _load(vintage_path)
    edge = payload.get("last_period")
    beyond = [
        observation["period"]
        for observation in payload.get("observations", [])
        if isinstance(observation, dict)
        and isinstance(observation.get("period"), str)
        and observation["period"] > edge
    ]
    assert not beyond, (
        f"data/{_relative(vintage_path)}: {len(beyond)} observation(s) past "
        f"last_period={edge!r}: {', '.join(beyond[:5])}"
    )


def test_fetch_is_not_older_than_the_release_it_captured(vintage_path):
    """A snapshot cannot have been taken before the data it contains existed.

    ``release_updated`` is when the publisher last revised the series;
    ``fetched_utc`` is when we read it. ``fetched_utc`` earlier than
    ``release_updated`` means the file was assembled from something other than
    a live fetch — a hand edit, a replayed fixture, or a clock problem — and
    the provenance chain is broken.
    """
    payload = _load(vintage_path)
    release = payload.get("release_updated")
    if release is None:
        # FRED does not expose a revision stamp; fetch.py records None rather
        # than inventing one.
        pytest.skip("source publishes no release_updated stamp")
    fetched = _parse_timestamp(payload["fetched_utc"])
    published = _parse_timestamp(release)
    assert fetched >= published, (
        f"data/{_relative(vintage_path)}: fetched_utc {payload['fetched_utc']} "
        f"is before release_updated {release}"
    )


def test_series_url_is_https_and_points_at_its_declared_source(vintage_path):
    """The provenance link must go to the publisher the file names.

    ``data/README.md`` attributes ONS and Bank of England series under the OGL
    and US series to their publishers via FRED. That attribution is only
    correct if the recorded URL actually resolves to that publisher.
    """
    payload = _load(vintage_path)
    name = f"data/{_relative(vintage_path)}"
    source = payload.get("source")
    url = payload.get("url", "")
    expected = SOURCE_DOMAINS.get(source)
    assert expected is not None, (
        f"{name}: unknown source {source!r}; known sources are "
        f"{sorted(SOURCE_DOMAINS)}"
    )
    assert url.startswith("https://"), (
        f"{name}: url {url!r} is not https — the site is served under HSTS and "
        "an http provenance link is a mixed-content dead end"
    )
    host = url.split("/", 3)[2]
    assert host == expected or host.endswith("." + expected), (
        f"{name}: source is {source!r} but url {url!r} is served from {host!r}, "
        f"not {expected!r}"
    )


# --------------------------------------------------------------- 3. latest

def test_latest_is_the_newest_vintage_byte_for_byte(series_dir, repo_root):
    """``latest/<series>.json`` must be the newest vintage, exactly.

    This is the test that catches a stale ``latest/`` misrepresenting current
    data. The published pages read ``latest/``; the store's integrity lives in
    ``vintages/``. Nothing else in the repo compares them, so the two can drift
    apart indefinitely with every individual file looking perfectly valid.

    Compared as parsed JSON, not as bytes, so a reformat is not a failure — the
    claim is that the *content* is identical.
    """
    newest = _newest_vintage(series_dir)
    latest = repo_root / "data" / "latest" / f"{series_dir.name}.json"

    assert latest.is_file(), (
        f"data/latest/{series_dir.name}.json is missing although "
        f"data/{_relative(newest)} exists — run `python3 data/fetch.py`"
    )

    published = _load(latest)
    stored = _load(newest)
    if published == stored:
        return

    differing = sorted(
        key for key in set(published) | set(stored)
        if published.get(key) != stored.get(key)
    )
    detail = []
    for key in differing:
        if key == "observations":
            here = published.get(key, [])
            there = stored.get(key, [])
            summary = (
                f"observations: latest has {len(here)}, "
                f"newest vintage has {len(there)}"
            )
            first = next(
                (
                    index
                    for index in range(min(len(here), len(there)))
                    if here[index] != there[index]
                ),
                None,
            )
            if first is not None:
                summary += (
                    f"; first difference at index {first}: "
                    f"latest={here[first]!r} newest vintage={there[first]!r}"
                )
            detail.append(summary)
        else:
            detail.append(
                f"{key}: latest={published.get(key)!r} "
                f"newest vintage={stored.get(key)!r}"
            )
    pytest.fail(
        f"data/latest/{series_dir.name}.json is stale: it does not match the "
        f"newest vintage data/{_relative(newest)}. The site reads latest/, so "
        f"it is currently publishing superseded data. Differing key(s):\n  "
        + "\n  ".join(detail)
        + "\nRun `python3 data/fetch.py` to rebuild latest/."
    )


def test_latest_has_no_orphan_series(repo_root):
    """Nothing in ``latest/`` without a vintage behind it.

    An orphan is a series that was removed from the fetcher but whose flattened
    copy stayed behind — the site would keep publishing a number that has no
    provenance and will never be updated again.
    """
    latest_dir = repo_root / "data" / "latest"
    stored = {path.name for path in (repo_root / "data" / "vintages").glob("*/*") if path.is_dir()}
    orphans = sorted(
        path.stem for path in latest_dir.glob("*.json") if path.stem not in stored
    )
    assert not orphans, (
        "data/latest/ contains series with no vintages on disk: "
        + ", ".join(f"{name}.json" for name in orphans)
    )


# --------------------------------------------------------------- 4. manifest

def test_manifest_lists_exactly_the_series_on_disk(repo_root):
    """``MANIFEST.json`` is the published index and must match reality.

    Reported in both directions in one message: a phantom entry is a broken
    promise to consumers, a missing entry is data nobody can find.
    """
    manifest = _load(repo_root / "data" / "MANIFEST.json")
    listed = set(manifest.get("series", {}))
    on_disk = {
        path.name
        for path in (repo_root / "data" / "vintages").glob("*/*")
        if path.is_dir() and any(path.glob("*.json"))
    }

    problems = []
    if missing := sorted(on_disk - listed):
        problems.append(
            f"on disk but absent from MANIFEST.json: {', '.join(missing)}"
        )
    if phantom := sorted(listed - on_disk):
        problems.append(
            f"listed in MANIFEST.json with no vintages on disk: {', '.join(phantom)}"
        )
    assert not problems, (
        "data/MANIFEST.json has drifted from data/vintages/ — run "
        "`python3 data/fetch.py`:\n  " + "\n  ".join(problems)
    )


def test_manifest_entry_matches_its_series(series_dir, repo_root):
    """Each manifest entry agrees with the newest vintage it summarises."""
    manifest = _load(repo_root / "data" / "MANIFEST.json")
    entry = manifest.get("series", {}).get(series_dir.name)
    assert entry is not None, (
        f"data/MANIFEST.json has no entry for {series_dir.name}"
    )

    vintages = sorted(path.stem for path in series_dir.glob("*.json"))
    newest = _load(_newest_vintage(series_dir))
    problems = []
    if entry.get("vintages") != vintages:
        problems.append(
            f"vintages list is {entry.get('vintages')} but the directory holds "
            f"{vintages}"
        )
    if entry.get("latest_vintage") != vintages[-1]:
        problems.append(
            f"latest_vintage is {entry.get('latest_vintage')!r} but the newest "
            f"file is {vintages[-1]!r}"
        )
    expected_coverage = [newest["first_period"], newest["last_period"]]
    if entry.get("coverage") != expected_coverage:
        problems.append(
            f"coverage is {entry.get('coverage')} but the newest vintage covers "
            f"{expected_coverage}"
        )
    for key in ("source", "cdid", "title", "units", "frequency", "url"):
        if entry.get(key) != newest.get(key):
            problems.append(
                f"{key} is {entry.get(key)!r} but the newest vintage says "
                f"{newest.get(key)!r}"
            )
    assert not problems, (
        f"data/MANIFEST.json entry for {series_dir.name} is stale — run "
        "`python3 data/fetch.py`:\n  " + "\n  ".join(problems)
    )


# --------------------------------------------------------------- 5. sanity

def test_the_store_was_actually_discovered(repo_root):
    """Guard against a silently empty run over the data store."""
    files = list((repo_root / "data" / "vintages").glob("*/*/*.json"))
    assert len(files) >= 20, (
        f"only {len(files)} vintage file(s) discovered under data/vintages/; "
        "the store holds ~57. Check the glob in tests/conftest.py"
    )
