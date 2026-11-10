#!/usr/bin/env python3
"""Refresh the data store and carry it all the way to a scored track record.

Run:  python3 data/refresh.py                              # the whole pipeline
      python3 data/refresh.py --carry-from data/vintage-refresh --summary out.md
      python3 data/refresh.py --plan                       # print the steps, run nothing

This is what ``.github/workflows/fetch-vintages.yml`` runs. One command, in a
fixed order, so the pull request it produces is complete:

    carry → fetch → notes → ingest → score → fans → pages → gates

Why one driver rather than more workflow steps
----------------------------------------------
Until November 2026 the workflow fetched, wrote notes and regenerated pages,
then opened a PR. It never ran ``forecasts/ingest_outturns.py`` or
``forecasts/score.py``. Those existed only as ``--check`` gates in
forecast-archive.yml — and that workflow never runs on the bot's PR, because
GitHub does not start ``pull_request`` workflows for pushes made with
``GITHUB_TOKEN``. So new outturns could reach the record only by hand, and the
refresh PR could not be merged without turning main red (#195: every gate
passed except ``ingest_outturns.py --check``, with GDP 2026Q2 and CPI 2026Q3
published and unrecorded).

So the driver writes the outturns and the scorecard itself, then runs every
gate the PR-time CI would have run (``GATES`` — tests/test_refresh_pipeline.py
fails if a CI workflow gains a check this list lacks). The PR it hands to a
human is already green.

Why carry
---------
The bot branch used to be rebuilt from main on every run and force-pushed, so
while a refresh PR waited for review each day's snapshots were overwritten by
the next day's: from 27 August to 4 November 2026 only the newest day survived.
Snapshots are the store's evidence that a forecast was made without hindsight,
and a day that was fetched but never kept is a hole in that evidence.
``--carry-from`` copies the vintage files the open refresh branch holds and
main does not, before fetching, so the branch accumulates dated snapshots
until it is merged. Only files under data/vintages/ are carried — everything
else (MANIFEST, latest/, notes, pages, outturns, scorecard) is regenerated
from them, so a stale branch can never conflict with main.

Nothing here edits or deletes an existing vintage or archived round; the last
gate proves it against HEAD.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VINTAGES = "data/vintages"
ROUNDS = "forecasts/rounds"
NOTES = "notes/generate_release_notes.py"

PY = sys.executable or "python3"


@dataclass(frozen=True)
class Step:
    name: str
    commands: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    why: str = ""


def py(*args: str) -> tuple[str, ...]:
    return ("python3", *args)


# Every check the PR-time workflows run (forecast-archive, site-provenance,
# data-immutability, site-tests). A refresh PR cannot trigger them itself, so
# the driver runs them before the PR exists. Order is cheap-first.
GATES: tuple[tuple[str, ...], ...] = (
    py("data/fetch.py", "--check"),
    py("forecasts/archive.py", "--check"),
    py("forecasts/ingest_outturns.py", "--check"),
    py("forecasts/score.py", "--check"),
    py("forecasts/make_open_fans.py", "--check"),
    py("forecasts/make_us_baseline.py", "--check"),
    py("-m", "unittest", "discover", "-s", "forecasts/tests", "-p", "test_*.py"),
    py(NOTES, "--check"),
    py("economy/topics.py", "--check"),
    py("economy/build.py", "--check"),
    py("data/build_page.py", "--check"),
    py("validation/figures/make_charts.py", "--check"),
    py("olg/figures/make_showcase.py", "--check"),
    py("assets/make_hero.py", "--check"),
    py("assets/make_current_outlooks.py", "--check"),
    py("site_nav.py"),
    py("site_contract.py"),
    py("-m", "pytest", "tests", "-q"),
)

# The pipeline, in order. "carry", "notes" and "append-only" are computed at
# run time (they depend on which vintage files are new); the rest are fixed.
STEPS: tuple[Step, ...] = (
    Step("carry", why="keep snapshots the open refresh branch already fetched"),
    Step("fetch", (py("data/fetch.py"),), "new dated snapshots; MANIFEST and latest/ rebuilt"),
    Step("notes", why="one factual note/digest per new vintage date"),
    Step("ingest", (py("forecasts/ingest_outturns.py"),), "append newly available outturns"),
    Step("score", (py("forecasts/score.py"),), "rescore every archived round"),
    Step("fans", (py("forecasts/make_open_fans.py"),), "open-round fan reads the scorecard"),
    Step(
        "pages",
        (py("economy/topics.py"), py("economy/build.py"), py("data/build_page.py")),
        "pages that render data/latest and the release calendar",
    ),
    Step("gates", GATES, "everything PR-time CI would check"),
    Step("append-only", why="no existing vintage or round edited, renamed or deleted"),
)


# ------------------------------------------------------------------ git


def git(*args: str, check: bool = True) -> str:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if check and out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def tracked_vintages(ref: str = "HEAD") -> set[str]:
    out = git("ls-tree", "-r", "--name-only", ref, "--", VINTAGES, check=False)
    return {line for line in out.splitlines() if line.endswith(".json")}


def vintages_on_disk() -> set[str]:
    base = ROOT / VINTAGES
    return {str(p.relative_to(ROOT)) for p in base.glob("*/*/*.json")}


def vintage_date(path: str) -> str:
    return Path(path).stem


def series_dir(path: str) -> str:
    return str(Path(path).parent)


# ---------------------------------------------------------------- carry


def carry_plan(branch_files: set[str], main_files: set[str]) -> tuple[list[str], list[str]]:
    """Which of the refresh branch's vintage files to bring onto main.

    Carried: files main does not have, dated after main's newest snapshot of
    the same series. Skipped: anything older than or equal to main's newest —
    inserting it would put a snapshot *behind* one main already published,
    which would make the store's "each file differs from the one before"
    invariant false. Returns (carry, skipped), both sorted.
    """
    newest: dict[str, str] = {}
    for path in main_files:
        d = series_dir(path)
        newest[d] = max(newest.get(d, ""), vintage_date(path))
    carry, skipped = [], []
    for path in sorted(branch_files - main_files):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", vintage_date(path)):
            skipped.append(path)
        elif vintage_date(path) > newest.get(series_dir(path), ""):
            carry.append(path)
        else:
            skipped.append(path)
    return carry, skipped


def drop_repeats(plan: list[str], main_files: set[str], load) -> tuple[list[str], list[str]]:
    """Drop carried files whose payload repeats the snapshot before them.

    ``load(path)`` returns a vintage's payload (from the branch for carried
    paths, from HEAD for main's). The predecessor of a carried file is the
    newest file of its series dated before it, among main's files and the
    files already kept. Without this, a release main already holds (for
    example one recovered by data/recover_orphaned_snapshots.py, #222) would
    be stored a second time under the branch's later date, because the bot
    branch measured it against an older main. Same test as the fetcher:
    ``fetch.same_data``. Returns (kept, repeats).
    """
    same_data = _fetch_module().same_data
    chain: dict[str, list[str]] = {}
    for path in main_files:
        chain.setdefault(series_dir(path), []).append(path)
    kept, repeats = [], []
    for path in sorted(plan, key=lambda p: (series_dir(p), vintage_date(p))):
        earlier = [p for p in chain.get(series_dir(path), []) if vintage_date(p) < vintage_date(path)]
        if earlier:
            pred = max(earlier, key=vintage_date)
            if same_data(load(pred), load(path)):
                repeats.append(path)
                continue
        kept.append(path)
        chain.setdefault(series_dir(path), []).append(path)
    return sorted(kept), sorted(repeats)


def _fetch_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("data_fetch", ROOT / "data" / "fetch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def carry(branch: str | None) -> list[str]:
    if not branch:
        print("carry: no --carry-from branch; starting from HEAD")
        return []
    fetched = subprocess.run(
        ["git", "fetch", "--no-tags", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if fetched.returncode != 0:
        print(f"carry: origin/{branch} does not exist; nothing to carry")
        return []
    ref = f"origin/{branch}"
    plan, skipped = carry_plan(tracked_vintages(ref), tracked_vintages("HEAD"))
    for path in skipped:
        print(f"carry: skip {path} (not newer than main's newest for the series)")
    main_files = tracked_vintages("HEAD")

    def load(path: str) -> dict:
        source = ref if path in plan else "HEAD"
        return json.loads(git("show", f"{source}:{path}"))

    plan, repeats = drop_repeats(plan, main_files, load)
    for path in repeats:
        print(f"carry: skip {path} (same release as the snapshot before it)")
    if plan:
        # `git show` per file, not `git checkout ref -- paths`: nothing is
        # staged, and only the listed paths are touched.
        for path in plan:
            target = ROOT / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                subprocess.run(
                    ["git", "show", f"{ref}:{path}"], cwd=ROOT,
                    capture_output=True, check=True,
                ).stdout
            )
    print(f"carry: {len(plan)} vintage file(s) carried from {ref}")
    return plan


# ---------------------------------------------------------------- notes


def new_vintage_dates() -> list[str]:
    return sorted({vintage_date(p) for p in vintages_on_disk() - tracked_vintages("HEAD")})


def notes_commands(dates: list[str]) -> list[tuple[str, ...]]:
    # Only --vintage: the flag both the per-series generator on main and the
    # per-date digest generator in the redesign (#200) accept, so this step is
    # correct whichever is merged.
    return [py(NOTES, "--vintage", d) for d in dates]


# ----------------------------------------------------------- append-only


def rewritten_history() -> list[str]:
    """Tracked vintage or round files modified, deleted or renamed vs HEAD."""
    out = git("diff", "--name-only", "--diff-filter=MDR", "HEAD", "--", VINTAGES, ROUNDS)
    return [line for line in out.splitlines() if line]


# ----------------------------------------------------------------- run


def run(cmd: tuple[str, ...], log: list[str]) -> str:
    argv = [PY if cmd[0] == "python3" else cmd[0], *cmd[1:]]
    print(f"$ {' '.join(cmd)}", flush=True)
    out = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(out.stdout)
    sys.stderr.write(out.stderr)
    log.append(out.stdout)
    if out.returncode != 0:
        raise SystemExit(f"FAILED ({out.returncode}): {' '.join(cmd)}")
    return out.stdout


def summarise(carried: list[str], dates: list[str], ingest_out: str) -> str:
    added = sorted(vintages_on_disk() - tracked_vintages("HEAD"))
    outturns = [line.strip() for line in ingest_out.splitlines() if line.startswith("added")]
    card = json.loads((ROOT / "forecasts" / "scorecard.json").read_text())
    lines = [
        "## What this refresh contains",
        "",
        f"- **{len(added)} new vintage file(s)** under `data/vintages/`"
        + (f", {len(carried)} of them carried from earlier runs of this branch" if carried else "")
        + ".",
        f"- Vintage dates: {', '.join(dates) if dates else 'none'}.",
        f"- **Outturns added to `forecasts/outturns.json`: {len(outturns)}**"
        + ("" if outturns else " (none newly available)."),
    ]
    lines += [f"  - `{o}`" for o in outturns]
    lines += [
        f"- Scorecard: {card.get('status', '?')}; next period to score "
        f"{card.get('next_period_to_score', '?')}.",
        "",
        "Every gate PR-time CI runs passed in the job that built this branch "
        "(`data/refresh.py` → `GATES`), including the append-only checks on "
        "`data/vintages/` and `forecasts/rounds/`.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--carry-from", metavar="BRANCH",
                    help="open refresh branch whose new vintages to keep")
    ap.add_argument("--summary", type=Path, help="write a markdown PR summary here")
    ap.add_argument("--plan", action="store_true", help="print the steps and exit")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="no network: run everything after fetch (for local checks)")
    args = ap.parse_args()

    if args.plan:
        for step in STEPS:
            print(f"{step.name:>11}  {step.why}")
            for cmd in step.commands:
                print(f"{'':>13}{' '.join(cmd)}")
        return 0

    if rewritten_history():
        raise SystemExit("refusing to start: the working tree already edits stored history")

    log: list[str] = []
    carried: list[str] = []
    dates: list[str] = []
    ingest_out = ""
    for step in STEPS:
        print(f"\n== {step.name}", flush=True)
        if step.name == "carry":
            carried = carry(args.carry_from)
        elif step.name == "fetch" and args.skip_fetch:
            # MANIFEST and latest/ must still reflect any carried files.
            run(py("-c", "import sys; sys.path.insert(0, 'data'); import fetch; "
                         "fetch.rebuild_latest(); fetch.rebuild_manifest()"), log)
        elif step.name == "notes":
            dates = new_vintage_dates()
            for cmd in notes_commands(dates):
                run(cmd, log)
            if not dates:
                print("notes: no new vintage date")
        elif step.name == "append-only":
            touched = rewritten_history()
            if touched:
                for path in touched:
                    print(f"::error::stored history rewritten: {path}", file=sys.stderr)
                raise SystemExit("FAILED: append-only")
            print("OK — no stored vintage or archived round was edited")
        else:
            for cmd in step.commands:
                out = run(cmd, log)
                if step.name == "ingest":
                    ingest_out += out

    if args.summary:
        args.summary.write_text(summarise(carried, dates, ingest_out))
        print(f"\nsummary written to {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
