"""One-off recovery of the orphaned refresh snapshots (#222).

The class of regression this prevents
-------------------------------------
From 27 August to 5 November 2026 the refresh bot rebuilt its branch from main
and force-pushed daily, so 50 days of snapshots survive only as orphaned
commits kept alive by ``data/archive-orphaned-snapshots-2026-11``. Each was cut
from main, so consecutive days often repeat one release under a new date.
``data/recover_orphaned_snapshots.py`` puts them back. These tests pin that it:

* keeps the first day a release was seen and drops repeats, comparing payload
  only (``fetch.same_data``), against both the existing store and the files it
  has already kept;
* never overwrites: identical bytes are "present" (so a re-run adds nothing),
  different bytes stop the run;
* writes the fetcher's bytes unchanged, then leaves a store that
  ``data/fetch.py --check`` accepts, with no tracked vintage modified;
* does nothing without ``--apply``.

The end-to-end test builds a synthetic repo: main, two orphan commits cut from
it, and an octopus archive commit whose extra parents are the orphans — the
same shape as the real archive.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


recover = _load("data_recover", ROOT / "data" / "recover_orphaned_snapshots.py")
refresh = _load("data_refresh_for_recover", ROOT / "data" / "refresh.py")

S = "data/vintages/ons/uk_cpi_yoy"


def snap(date: str, value: float = 3.0, release: str = "2026-08-18T23:00:00.000Z") -> dict:
    return {
        "series": "uk_cpi_yoy",
        "source": "ONS",
        "cdid": "D7G7",
        "title": "CPI ANNUAL RATE",
        "frequency": "quarterly",
        "units": "percent, year-on-year",
        "url": "https://www.ons.gov.uk/x/data",
        "release_updated": release,
        "next_release": "16 September 2026",
        "first_period": "2026Q1",
        "last_period": "2026Q2",
        "observations": [{"period": "2026Q1", "value": 3.4}, {"period": "2026Q2", "value": value}],
        "vintage": date,
        "fetched_utc": f"{date}T07:30:00Z",
    }


def blob(d: dict) -> bytes:
    return (json.dumps(d, indent=2) + "\n").encode()


def cand(date: str, sha: str = "a" * 40, **kw) -> "recover.Candidate":
    return recover.Candidate(f"{S}/{date}.json", sha, blob(snap(date, **kw)))


# ------------------------------------------------------------------ plan


def test_repeat_days_are_dropped_and_the_first_day_is_kept():
    existing = {f"{S}/2026-08-26.json": blob(snap("2026-08-26"))}
    cands = [
        cand("2026-08-27"),  # same release as main's 08-26 → drop
        cand("2026-09-16", value=3.8, release="2026-09-15T23:00:00.000Z"),  # new release → keep
        cand("2026-09-17", value=3.8, release="2026-09-15T23:00:00.000Z"),  # repeat → drop
        cand("2026-10-21", value=3.1, release="2026-10-20T23:00:00.000Z"),  # new → keep
    ]
    p = recover.plan(cands, existing)
    assert [c.date for c in p.add] == ["2026-09-16", "2026-10-21"]
    assert [(c.date, Path(prev).stem) for c, prev in p.duplicate] == [
        ("2026-08-27", "2026-08-26"),
        ("2026-09-17", "2026-09-16"),
    ]
    assert not (p.conflict or p.invalid or p.present)


def test_fetch_time_alone_does_not_make_a_new_snapshot():
    a, b = snap("2026-09-01"), snap("2026-09-02")
    assert a["fetched_utc"] != b["fetched_utc"]
    p = recover.plan([cand("2026-09-01"), cand("2026-09-02")], {})
    assert [c.date for c in p.add] == ["2026-09-01"]


def test_a_release_that_reverts_is_kept_because_only_the_predecessor_counts():
    cands = [cand("2026-09-01"), cand("2026-09-02", value=9.9), cand("2026-09-03")]
    p = recover.plan(cands, {})
    assert [c.date for c in p.add] == ["2026-09-01", "2026-09-02", "2026-09-03"]


def test_order_of_input_does_not_matter():
    cands = [cand("2026-09-03"), cand("2026-09-01"), cand("2026-09-02")]
    p = recover.plan(cands, {})
    assert [c.date for c in p.add] == ["2026-09-01"]


def test_identical_existing_file_is_present_and_different_bytes_conflict():
    existing = {f"{S}/2026-11-05.json": blob(snap("2026-11-05"))}
    same = recover.plan([cand("2026-11-05")], existing)
    assert [c.date for c in same.present] == ["2026-11-05"] and not same.add
    changed = recover.plan([cand("2026-11-05", value=1.0)], existing)
    assert [c.date for c in changed.conflict] == ["2026-11-05"] and not changed.add


def test_a_later_existing_file_that_repeats_a_recovered_release_is_reported():
    # #195 already on main: its 11-05 file repeats a release first fetched 10-21.
    rel = dict(value=3.1, release="2026-10-20T23:00:00.000Z")
    existing = {
        f"{S}/2026-08-26.json": blob(snap("2026-08-26")),
        f"{S}/2026-11-05.json": blob(snap("2026-11-05", **rel)),
    }
    p = recover.plan([cand("2026-10-21", **rel), cand("2026-10-22", **rel)], existing)
    assert [c.date for c in p.add] == ["2026-10-21"]
    assert [(Path(a).stem, Path(b).stem) for a, b in p.later_duplicate] == [("2026-11-05", "2026-10-21")]


def test_invalid_candidates_are_refused():
    bad = snap("2026-09-01")
    bad["vintage"] = "2026-09-02"
    p = recover.plan([recover.Candidate(f"{S}/2026-09-01.json", "a" * 40, blob(bad))], {})
    assert p.invalid and not p.add


# ----------------------------------------------------- refresh carry repeats


def test_refresh_carry_drops_a_branch_file_that_repeats_mains_snapshot():
    rel = dict(value=3.1, release="2026-10-20T23:00:00.000Z")
    payloads = {
        f"{S}/2026-10-21.json": snap("2026-10-21", **rel),  # on main (recovered)
        f"{S}/2026-11-05.json": snap("2026-11-05", **rel),  # bot branch, same release
        f"{S}/2026-11-12.json": snap("2026-11-12", value=3.4, release="2026-11-11T23:00:00.000Z"),
    }
    kept, repeats = refresh.drop_repeats(
        [f"{S}/2026-11-05.json", f"{S}/2026-11-12.json"], {f"{S}/2026-10-21.json"}, payloads.__getitem__
    )
    assert kept == [f"{S}/2026-11-12.json"]
    assert repeats == [f"{S}/2026-11-05.json"]


# ------------------------------------------------------------ end to end


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    base = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(repo),
    }
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=base)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _write(repo: Path, rel: str, data: dict) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob(data))


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    r = tmp_path / "repo"
    (r / "data").mkdir(parents=True)
    shutil.copy(ROOT / "data" / "fetch.py", r / "data" / "fetch.py")
    _git(r, "init", "-q", "-b", "main")
    _write(r, f"{S}/2026-08-26.json", snap("2026-08-26"))
    subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0,'data'); import fetch; "
                    "fetch.rebuild_latest(); fetch.rebuild_manifest()"], cwd=r, check=True)
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "main")
    main = _git(r, "rev-parse", "HEAD")

    orphans = []
    for date, value in (("2026-09-16", 3.8), ("2026-09-17", 3.8)):
        _git(r, "checkout", "-q", "--detach", main)
        _write(r, f"{S}/{date}.json", snap(date, value=value, release="2026-09-15T23:00:00.000Z"))
        _write(r, f"data/vintages/boe/uk_bank_rate/{date}.json",
               {**snap(date, value=float(date[-2:])), "series": "uk_bank_rate", "source": "BoE"})
        _write(r, "data/MANIFEST.json", {"regenerated": date})  # not a vintage: ignored
        _git(r, "add", "-A")
        _git(r, "commit", "-qm", f"bot {date}")
        orphans.append(_git(r, "rev-parse", "HEAD"))
    tree = _git(r, "rev-parse", f"{main}^{{tree}}")
    archive = _git(r, "commit-tree", tree, "-p", main, *sum((["-p", o] for o in orphans), []), "-m", "archive")
    _git(r, "checkout", "-q", "main")
    return r, archive


def _run(repo: Path, archive: str, *extra: str) -> int:
    return recover.main(["--root", str(repo), "--archive", archive, "--no-fetch", *extra])


def test_dry_run_writes_nothing(repo, capsys):
    r, archive = repo
    before = sorted(p.relative_to(r) for p in r.rglob("*") if ".git" not in p.parts)
    assert _run(r, archive) == 0
    assert sorted(p.relative_to(r) for p in r.rglob("*") if ".git" not in p.parts) == before
    out = capsys.readouterr().out
    assert "To add: 3" in out and "duplicate days dropped: 1" in out and "dry run" in out


def test_apply_appends_original_bytes_passes_the_store_check_and_is_idempotent(repo, capsys):
    r, archive = repo
    assert _run(r, archive, "--apply") == 0
    added = _git(r, "status", "--porcelain", "--", "data/vintages").splitlines()
    assert sorted(line.split()[-1] for line in added) == [
        "data/vintages/boe/",  # new series directory
        f"{S}/2026-09-16.json",
    ]
    # bytes exactly as the orphan commit holds them, fetched_utc intact
    orphan_blob = subprocess.run(
        ["git", "show", f"{archive}^2:{S}/2026-09-16.json"], cwd=r, capture_output=True
    ).stdout
    assert (r / S / "2026-09-16.json").read_bytes() == orphan_blob
    assert json.loads(orphan_blob)["fetched_utc"] == "2026-09-16T07:30:00Z"
    assert not (r / S / "2026-09-17.json").exists()  # repeat day dropped
    assert sorted(p.name for p in (r / "data/vintages/boe/uk_bank_rate").iterdir()) == [
        "2026-09-16.json", "2026-09-17.json",
    ]
    # the repo's own integrity gate and the append-only diff
    check = subprocess.run([sys.executable, "data/fetch.py", "--check"], cwd=r, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
    assert _git(r, "diff", "--name-only", "--diff-filter=MDR", "HEAD", "--", "data/vintages") == ""
    manifest = json.loads((r / "data/MANIFEST.json").read_text())
    assert manifest["series"]["uk_cpi_yoy"]["vintages"] == ["2026-08-26", "2026-09-16"]
    assert (r / "data/latest/uk_cpi_yoy.json").read_bytes() == orphan_blob

    capsys.readouterr()
    assert _run(r, archive, "--apply") == 0
    assert "To add: 0" in capsys.readouterr().out


def test_apply_refuses_when_a_stored_file_differs(repo):
    r, archive = repo
    _write(r, f"{S}/2026-09-16.json", snap("2026-09-16", value=0.0))
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "someone stored a different 09-16")
    assert _run(r, archive, "--apply") == 1
    assert not (r / "data/vintages/boe").exists()
