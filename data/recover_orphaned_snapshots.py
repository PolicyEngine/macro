#!/usr/bin/env python3
"""Recover the daily vintage snapshots the refresh bot orphaned (issue #222).

Run:  python3 data/recover_orphaned_snapshots.py                 # dry run: print the plan
      python3 data/recover_orphaned_snapshots.py --against 18442ea   # dry run vs another tree
      python3 data/recover_orphaned_snapshots.py --apply          # write files, rebuild MANIFEST/latest
      python3 data/recover_orphaned_snapshots.py --apply --summary recovery.md

One-off, idempotent. Dry run is the default; nothing is written without ``--apply``.

What happened
-------------
From 27 August to 5 November 2026 ``fetch-vintages.yml`` rebuilt
``data/vintage-refresh`` from main every weekday and force-pushed it, so each
day's snapshot commit replaced the one before. The 50 replaced commits are kept
reachable by ``data/archive-orphaned-snapshots-2026-11``: one octopus commit
whose first parent is main and whose other 50 parents are the bot commits. Its
own tree is main's; the data lives only in the parents.

Each bot commit was cut from main, so it holds that day's snapshots measured
against main's 26 August store, not against the day before. Consecutive commits
therefore often hold the same release under a new date. ``data/refresh.py
--carry-from`` cannot recover them: it reads one branch tree, and it skips any
file dated at or before main's newest snapshot of the series.

What this does
--------------
1. Lists every vintage file each orphan *added* against its own parent
   (``git diff-tree --diff-filter=A``), keeping ``<source>/<series>/<date>.json``.
2. Per series, walks those candidates oldest first. The predecessor of a
   candidate is the newest file dated before it, among the target store's
   files and the candidates already kept. A candidate whose payload equals its
   predecessor's (``fetch.same_data``: observations, release stamp, next
   release, last period, title, units — not ``fetched_utc``) is a duplicate
   day and is dropped. The first day a release was seen is the one kept, which
   is what the fetcher itself would have written had the branch accumulated.
3. A candidate whose path already exists in the target is ``present`` when the
   bytes are identical (re-runs and #195's own files) and a conflict, which
   stops the run, when they are not. Nothing is ever overwritten.
4. With ``--apply``, writes each kept file byte for byte from the orphan commit
   (``fetched_utc`` and ``vintage`` exactly as the fetcher wrote them), then
   rebuilds MANIFEST.json and latest/ with ``fetch.py``'s own functions and
   checks that no tracked vintage was modified, renamed or deleted.

It also reports, per series, a kept candidate whose *next* existing file in
the target has the same payload (for example a 5 November file from #195 that
repeats a release first seen on 23 October). That later file cannot be removed
(the store is append-only); the count says how much the order relative to
#195 matters.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VINTAGES = "data/vintages"
ARCHIVE = "origin/data/archive-orphaned-snapshots-2026-11"
ARCHIVE_BRANCH = "data/archive-orphaned-snapshots-2026-11"
PATH_RE = re.compile(r"^data/vintages/[a-z]+/[a-z0-9_]+/\d{4}-\d{2}-\d{2}\.json$")


def _load_fetch():
    spec = importlib.util.spec_from_file_location("data_fetch", Path(__file__).with_name("fetch.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = _load_fetch()
same_data = fetch.same_data


# ------------------------------------------------------------------ model


@dataclass(frozen=True)
class Candidate:
    path: str  # data/vintages/<source>/<series>/<date>.json
    sha: str  # orphan commit that added it
    blob: bytes

    @property
    def series(self) -> str:
        return str(Path(self.path).parent)

    @property
    def date(self) -> str:
        return Path(self.path).stem

    @property
    def payload(self) -> dict:
        return json.loads(self.blob)


@dataclass
class Plan:
    add: list[Candidate] = field(default_factory=list)
    present: list[Candidate] = field(default_factory=list)
    duplicate: list[tuple[Candidate, str]] = field(default_factory=list)  # (dropped, equal-to path)
    conflict: list[Candidate] = field(default_factory=list)
    later_duplicate: list[tuple[str, str]] = field(default_factory=list)  # (existing later path, first-seen path)
    invalid: list[tuple[Candidate, str]] = field(default_factory=list)


def validate(c: Candidate) -> str | None:
    try:
        data = c.payload
    except json.JSONDecodeError as exc:
        return f"not JSON: {exc}"
    if data.get("vintage") != c.date:
        return f"vintage {data.get('vintage')!r} does not match its filename"
    if not str(data.get("fetched_utc", "")).startswith(c.date):
        return f"fetched_utc {data.get('fetched_utc')!r} is not on {c.date}"
    if not data.get("observations"):
        return "no observations"
    return None


def plan(candidates: list[Candidate], existing: dict[str, bytes]) -> Plan:
    """Pure: decide what to add given candidates and the target's vintage files.

    ``existing`` maps path → bytes for every vintage file in the target store.
    Candidates with the same path from several orphans are considered once (the
    earliest commit's copy; the bot never rewrote a dated file).
    """
    out = Plan()
    seen: set[str] = set()
    by_series: dict[str, list[Candidate]] = defaultdict(list)
    for c in sorted(candidates, key=lambda c: (c.date, c.path)):
        if c.path in seen:
            continue
        seen.add(c.path)
        problem = validate(c)
        if problem:
            out.invalid.append((c, problem))
            continue
        by_series[c.series].append(c)

    existing_by_series: dict[str, dict[str, bytes]] = defaultdict(dict)
    for path, blob in existing.items():
        existing_by_series[str(Path(path).parent)][Path(path).stem] = blob

    for series, cands in sorted(by_series.items()):
        # date → (path, payload) for the store as it grows
        chain: dict[str, tuple[str, dict]] = {
            d: (f"{series}/{d}.json", json.loads(b)) for d, b in existing_by_series[series].items()
        }
        for c in cands:
            if c.date in chain:
                if existing_by_series[series].get(c.date) == c.blob:
                    out.present.append(c)
                else:
                    out.conflict.append(c)
                continue
            earlier = [d for d in chain if d < c.date]
            if earlier:
                pred_path, pred = chain[max(earlier)]
                if same_data(pred, c.payload):
                    out.duplicate.append((c, pred_path))
                    continue
            out.add.append(c)
            chain[c.date] = (c.path, c.payload)
        # An existing file whose predecessor, once the recovered files are in,
        # is a recovered file with the same payload.
        added_dates = {c.date for c in out.add if c.series == series}
        dates = sorted(chain)
        for prev, cur in zip(dates, dates[1:]):
            if prev in added_dates and cur in existing_by_series[series]:
                if same_data(chain[prev][1], chain[cur][1]):
                    out.later_duplicate.append((chain[cur][0], chain[prev][0]))
    return out


# ------------------------------------------------------------------ git


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def git_bytes(root: Path, *args: str) -> bytes:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.decode().strip()}")
    return out.stdout


def orphans(root: Path, archive: str) -> list[str]:
    """The archive commit's parents after the first (which is main)."""
    parents = git(root, "rev-list", "--parents", "-n", "1", archive).split()[1:]
    if len(parents) < 2:
        raise SystemExit(f"{archive}: expected an octopus commit (main + orphans), got {len(parents)} parent(s)")
    return parents[1:]


def added_vintages(root: Path, sha: str) -> list[str]:
    out = git(root, "diff-tree", "-r", "--no-commit-id", "--name-only", "--diff-filter=A",
              f"{sha}^", sha, "--", VINTAGES)
    return [p for p in out.splitlines() if PATH_RE.match(p)]


def collect(root: Path, archive: str) -> tuple[list[Candidate], dict[str, int]]:
    cands, per_commit = [], {}
    for sha in orphans(root, archive):
        paths = added_vintages(root, sha)
        per_commit[sha] = len(paths)
        for p in paths:
            cands.append(Candidate(p, sha, git_bytes(root, "show", f"{sha}:{p}")))
    return cands, per_commit


def existing_from_disk(root: Path) -> dict[str, bytes]:
    base = root / VINTAGES
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in base.glob("*/*/*.json")}


def existing_from_ref(root: Path, ref: str) -> dict[str, bytes]:
    paths = [p for p in git(root, "ls-tree", "-r", "--name-only", ref, "--", VINTAGES).splitlines()
             if PATH_RE.match(p)]
    return {p: git_bytes(root, "show", f"{ref}:{p}") for p in paths}


def rewritten(root: Path) -> list[str]:
    out = git(root, "diff", "--name-only", "--diff-filter=MDR", "HEAD", "--", VINTAGES)
    return [p for p in out.splitlines() if p]


# ------------------------------------------------------------------ report


def report(p: Plan, per_commit: dict[str, int], against: str) -> str:
    def series_name(path: str) -> str:
        return "/".join(Path(path).parent.parts[-2:])

    added = Counter(series_name(c.path) for c in p.add)
    dup = Counter(series_name(c.path) for c, _ in p.duplicate)
    pres = Counter(series_name(c.path) for c in p.present)
    later = Counter(series_name(path) for path, _ in p.later_duplicate)
    rows = sorted(set(added) | set(dup) | set(pres))
    total_candidates = sum(per_commit.values())
    lines = [
        f"## Orphaned snapshot recovery — against `{against}`",
        "",
        f"- Orphan commits read: {len(per_commit)}; vintage files they added: {total_candidates} "
        f"({len({c.path for c, _ in p.duplicate} | {c.path for c in p.add} | {c.path for c in p.present})} distinct paths).",
        f"- **To add: {len(p.add)}**; duplicate days dropped: {len(p.duplicate)}; "
        f"already present (identical bytes): {len(p.present)}; conflicts: {len(p.conflict)}; "
        f"invalid: {len(p.invalid)}.",
        f"- Existing later files that repeat a release first seen in a recovered file: {len(p.later_duplicate)}.",
        "",
        "| series | add | duplicate days dropped | already present | later file repeats it |",
        "|---|---:|---:|---:|---:|",
    ]
    for s in rows:
        lines.append(f"| {s} | {added[s]} | {dup[s]} | {pres[s]} | {later[s]} |")
    lines.append(f"| **total** | **{len(p.add)}** | **{len(p.duplicate)}** | **{len(p.present)}** | **{len(p.later_duplicate)}** |")
    if p.add:
        lines += ["", "<details><summary>Files to add (path ← source commit)</summary>", ""]
        lines += [f"- `{c.path}` ← `{c.sha[:12]}`" for c in p.add]
        lines += ["", "</details>"]
    if p.later_duplicate:
        lines += ["", "Existing files that repeat a recovered release (kept; append-only):", ""]
        lines += [f"- `{later}` repeats `{first}`" for later, first in p.later_duplicate]
    for c in p.conflict:
        lines.append(f"- CONFLICT `{c.path}` from `{c.sha[:12]}` differs from the file already in the store")
    for c, why in p.invalid:
        lines.append(f"- INVALID `{c.path}` from `{c.sha[:12]}`: {why}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ main


def apply(root: Path, p: Plan) -> None:
    for c in p.add:
        target = root / c.path
        if target.exists():  # plan() is computed from disk, so this is a race
            raise SystemExit(f"refusing to overwrite {c.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(c.blob)
    # fetch.py's paths are module constants pinned to its own checkout.
    fetch.HERE, fetch.VINTAGES = root / "data", root / VINTAGES
    fetch.LATEST, fetch.MANIFEST = root / "data" / "latest", root / "data" / "MANIFEST.json"
    fetch.rebuild_latest()
    fetch.rebuild_manifest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--archive", default=ARCHIVE, help=f"octopus archive commit (default {ARCHIVE})")
    ap.add_argument("--against", metavar="REF",
                    help="dry run against this commit's store instead of the working tree")
    ap.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    ap.add_argument("--summary", type=Path, help="also write the report here (markdown)")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--no-fetch", action="store_true", help="do not fetch the archive branch first")
    args = ap.parse_args(argv)
    root = args.root.resolve()

    if args.apply and args.against:
        ap.error("--apply writes the working tree; it cannot be combined with --against")
    if not args.no_fetch and args.archive == ARCHIVE:
        subprocess.run(["git", "fetch", "--no-tags", "origin",
                        f"+refs/heads/{ARCHIVE_BRANCH}:refs/remotes/{ARCHIVE}"],
                       cwd=root, capture_output=True)
    if args.apply and rewritten(root):
        raise SystemExit("refusing to start: the working tree already edits stored vintages")

    cands, per_commit = collect(root, args.archive)
    existing = existing_from_ref(root, args.against) if args.against else existing_from_disk(root)
    p = plan(cands, existing)
    text = report(p, per_commit, args.against or "working tree")
    print(text)
    if args.summary:
        args.summary.write_text(text)
    if p.conflict or p.invalid:
        print("FAILED: conflicts or invalid files; nothing written", file=sys.stderr)
        return 1
    if not args.apply:
        print("dry run: nothing written (use --apply)")
        return 0

    apply(root, p)
    touched = rewritten(root)
    if touched:
        raise SystemExit(f"FAILED: stored vintages rewritten: {touched}")
    print(f"applied: {len(p.add)} file(s) written; MANIFEST.json and latest/ rebuilt; "
          "no tracked vintage modified. Next: python3 data/fetch.py --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
