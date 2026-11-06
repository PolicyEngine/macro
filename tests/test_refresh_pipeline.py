"""The scheduled data refresh carries new data all the way to the scorecard.

The class of regression this prevents
-------------------------------------
From 27 August to 6 November 2026 the track record did not move although
UK GDP 2026Q2 and CPI 2026Q3 had been published:

* ``fetch-vintages.yml`` fetched, wrote notes and regenerated pages, but never
  ran ``forecasts/ingest_outturns.py`` or ``forecasts/score.py``. Those existed
  only as ``--check`` gates in forecast-archive.yml, which never runs on the
  bot's PR (pushes made with ``GITHUB_TOKEN`` do not start ``pull_request``
  workflows) — so the refresh PR (#195) had no CI and could not be merged
  without turning main red on ``ingest_outturns.py --check``.
* From 26 October ``peter-evans/create-pull-request`` failed outright: it tries
  to create before it updates, and creating returns 403 once "Allow GitHub
  Actions to create and approve pull requests" is off.
* The branch was rebuilt from main and force-pushed daily, so while the PR
  waited each day's snapshots were overwritten by the next day's.

These tests pin the fix: one driver (``data/refresh.py``) in a fixed order, a
gate list that cannot fall behind the PR-time workflows, a carry rule that
keeps earlier snapshots, and a PR step that updates an existing PR without the
create permission and can never push to main.

Stdlib + pytest only, like the rest of ``tests/``: workflows are read with
line patterns, not a YAML parser.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPT = ROOT / ".github" / "scripts" / "open-bot-pr.sh"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


refresh = _load("data_refresh", ROOT / "data" / "refresh.py")


def _run_lines(workflow: str) -> list[str]:
    """Single-line `run: python3 ...` commands of a workflow."""
    text = (WORKFLOWS / workflow).read_text()
    return [m.group(1).strip() for m in re.finditer(r"^\s+run:\s+(python3 .+)$", text, re.M)]


# ------------------------------------------------------------------ order


def test_pipeline_order_is_fetch_then_ingest_then_score_then_gates():
    names = [step.name for step in refresh.STEPS]
    assert names == [
        "carry", "fetch", "notes", "ingest", "score", "fans", "pages",
        "gates", "append-only",
    ]


def test_ingest_and_score_write_rather_than_check():
    by_name = {step.name: step for step in refresh.STEPS}
    assert by_name["ingest"].commands == (("python3", "forecasts/ingest_outturns.py"),)
    assert by_name["score"].commands == (("python3", "forecasts/score.py"),)


@pytest.mark.parametrize(
    "workflow",
    ["forecast-archive.yml", "site-provenance.yml", "data-immutability.yml", "site-tests.yml"],
)
def test_driver_runs_every_check_the_pr_workflows_run(workflow):
    """A refresh PR cannot start these workflows, so the driver must run each
    of their checks before pushing. Adding a check to one of them without
    adding it to GATES fails here."""
    gates = {" ".join(shlex.quote(a) for a in cmd) for cmd in refresh.GATES}
    gates |= {" ".join(cmd) for cmd in refresh.GATES}
    missing = [
        line for line in _run_lines(workflow)
        if not line.startswith("python3 -m pip ") and line not in gates
    ]
    assert missing == [], f"{workflow} checks not run by data/refresh.py: {missing}"


def test_notes_step_uses_only_flags_both_generators_accept():
    """--vintage is accepted by the per-series generator on main and by the
    per-date digest generator in the redesign (#200)."""
    cmds = refresh.notes_commands(["2026-11-05", "2026-11-06"])
    assert cmds == [
        ("python3", "notes/generate_release_notes.py", "--vintage", "2026-11-05"),
        ("python3", "notes/generate_release_notes.py", "--vintage", "2026-11-06"),
    ]
    source = (ROOT / "notes" / "generate_release_notes.py").read_text()
    assert '"--vintage"' in source and '"--check"' in source


# --------------------------------------------------------------- workflow


def test_fetch_workflow_runs_the_driver_before_the_pr_step():
    text = (WORKFLOWS / "fetch-vintages.yml").read_text()
    assert "peter-evans/create-pull-request" not in text
    driver = text.index("python3 data/refresh.py")
    pr = text.index(".github/scripts/open-bot-pr.sh")
    assert driver < pr


def test_nowcast_workflow_fails_on_a_stale_calendar_and_uses_the_pr_script():
    text = (WORKFLOWS / "nowcast-round.yml").read_text()
    assert "peter-evans/create-pull-request" not in text
    assert ".github/scripts/open-bot-pr.sh forecasts/nowcast-round" in text
    stale_arm = re.search(r"^\s+2\)(.*?);;", text, re.M | re.S)
    assert stale_arm and "exit 1" in stale_arm.group(1)


# ------------------------------------------------------------------ carry


def test_carry_keeps_branch_snapshots_newer_than_main():
    main = {
        "data/vintages/ons/uk_gdp_cvm/2026-07-26.json",
        "data/vintages/boe/uk_bank_rate/2026-08-26.json",
    }
    branch = main | {
        "data/vintages/ons/uk_gdp_cvm/2026-11-05.json",
        "data/vintages/boe/uk_bank_rate/2026-11-05.json",
        # Older than main's newest bank-rate snapshot: would sit behind a
        # snapshot main has already published.
        "data/vintages/boe/uk_bank_rate/2026-08-20.json",
        # A brand-new series is carried too.
        "data/vintages/fred/us_new/2026-11-04.json",
    }
    carry, skipped = refresh.carry_plan(branch, main)
    assert carry == [
        "data/vintages/boe/uk_bank_rate/2026-11-05.json",
        "data/vintages/fred/us_new/2026-11-04.json",
        "data/vintages/ons/uk_gdp_cvm/2026-11-05.json",
    ]
    assert skipped == ["data/vintages/boe/uk_bank_rate/2026-08-20.json"]


def test_carry_never_touches_files_main_already_has():
    main = {"data/vintages/ons/uk_cpi_yoy/2026-08-26.json"}
    carry, skipped = refresh.carry_plan(set(main), main)
    assert carry == [] and skipped == []


def test_carry_ignores_non_dated_files():
    carry, skipped = refresh.carry_plan({"data/vintages/ons/x/notes.json"}, set())
    assert carry == [] and skipped == ["data/vintages/ons/x/notes.json"]


# -------------------------------------------------------------- PR script


@pytest.mark.parametrize("branch", ["main", "master", "feature/x", "vahid/r5-pipeline"])
def test_pr_script_refuses_branches_outside_the_bot_namespaces(tmp_path, branch):
    out = subprocess.run(
        ["bash", str(SCRIPT), branch, "title", str(tmp_path / "body.md")],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert out.returncode == 1
    assert "refusing to push" in out.stdout


def test_pr_script_updates_an_existing_pr_before_trying_to_create_one():
    """Creating needs the Actions PR permission; updating does not. Looking
    for the open PR first is what keeps #195 moving with the setting off."""
    text = SCRIPT.read_text()
    assert text.index("gh pr list --head") < text.index("gh pr create")
