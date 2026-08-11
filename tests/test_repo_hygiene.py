"""Repository-level provenance: citation, changelog, and dependency pins.

The class of regression this prevents
-------------------------------------
This repo publishes working papers, asks to be cited, and claims in
``README.md`` and across ``/models`` that its results are reproducible. Three
files carry those claims outside the website, and none of them is exercised by
any other check in the repo:

* **CITATION.cff** — the papers give a citation block; a machine-readable
  ``CITATION.cff`` is what GitHub and Zenodo read. A ``version`` that has
  drifted from the package version means every automated citation records the
  wrong release.
* **CHANGELOG.md** — the changelog's top entry is the released version. When it
  lags ``pyproject.toml`` the released version is undocumented; when it leads,
  a version is announced that nobody can install.
* **The ``[models]`` extra** — this is the reproducibility claim, load-bearing.
  A model dependency pinned to a branch or a tag re-resolves to different code
  over time, so "the same command gives the same numbers" quietly stops being
  true and no test anywhere would notice. ``integration/tests/test_source_pins.py``
  checks the Modal deployment pins agree with pyproject; nothing checked that
  the pins are full commit SHAs in the first place.

Parsed with the stdlib only. ``CITATION.cff`` is YAML, but the suite must not
add a YAML dependency to a repo that is deliberately dependency-free, and the
handful of top-level scalars these tests need are recoverable with a targeted
line parse.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

# --------------------------------------------------------------- policy



# Only git dependencies can be SHA-pinned; PyPI requirements have no commit to
# pin, where a version specifier is the reproducible form instead.
# test_source_pins.py in integration/ covers the deployment side of the same
# question.
NON_GIT_MARKER = "git+"


# --------------------------------------------------------------- helpers

def _pyproject(repo_root: Path) -> dict:
    return tomllib.loads((repo_root / "integration" / "pyproject.toml").read_text())


def _package_version(repo_root: Path) -> str:
    version = _pyproject(repo_root).get("project", {}).get("version")
    assert version, "integration/pyproject.toml declares no [project] version"
    return version






def _cff_scalars(text: str) -> dict[str, str]:
    """Top-level ``key: value`` pairs from a CITATION.cff.

    Deliberately shallow: only unindented scalar keys are read, which is where
    ``cff-version``, ``version``, ``title`` and ``date-released`` live. Nested
    blocks (``authors:``) are skipped rather than half-parsed, because a
    half-parsed YAML tree is worse than no tree.
    """
    scalars: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if not match:
            continue
        value = match.group(2).strip()
        if value in ("", "|", ">", "|-", ">-"):
            continue  # a nested block or folded scalar, not a top-level value
        scalars[match.group(1)] = value.strip("'\"")
    return scalars


# --------------------------------------------------------------- 1. citation

def test_citation_metadata_matches_the_package_version(repo_root):
    """``CITATION.cff`` exists, parses, and cites the current version.

    This repo publishes four working papers with explicit citation blocks.
    ``CITATION.cff`` is the machine-readable form GitHub's "Cite this
    repository" button and Zenodo read; a stale ``version`` in it means every
    automatically generated citation names the wrong release of the software
    the paper describes.
    """
    citation = repo_root / "CITATION.cff"
    assert citation.is_file(), (
        "CITATION.cff is missing from the repository root. The papers under "
        "papers/ ask to be cited, so the repository needs a machine-readable "
        "citation record."
    )

    fields = _cff_scalars(citation.read_text())
    assert fields, "CITATION.cff has no parseable top-level keys"

    for required in ("cff-version", "title", "version"):
        assert required in fields, (
            f"CITATION.cff has no top-level `{required}:` key "
            f"(found: {', '.join(sorted(fields))})"
        )

    expected = _package_version(repo_root)
    assert fields["version"] == expected, (
        f"CITATION.cff version is {fields['version']!r} but "
        f"integration/pyproject.toml declares {expected!r}"
    )


# --------------------------------------------------------------- 2. changelog

def test_changelog_top_entry_is_the_current_version(repo_root):
    """The newest changelog heading names the version we ship.

    Checked against the top entry rather than "does the version appear
    anywhere", because a changelog that merely mentions the version somewhere
    in its history is exactly the failure mode: the release ships and its entry
    is never written.
    """
    changelog = repo_root / "CHANGELOG.md"
    assert changelog.is_file(), (
        "CHANGELOG.md is missing from the repository root"
    )

    heading = None
    for number, line in enumerate(changelog.read_text().splitlines(), start=1):
        match = re.match(r"^#{1,6}\s*\[?v?(\d+\.\d+\.\d+[^\]\s]*)\]?", line.strip())
        if match:
            heading = (number, match.group(1), line.strip())
            break
    assert heading is not None, (
        "CHANGELOG.md contains no version heading of the form "
        "`## [0.1.0]`, `## v0.1.0` or `## 0.1.0`"
    )

    line_number, version, raw = heading
    expected = _package_version(repo_root)
    assert version == expected, (
        f"CHANGELOG.md:{line_number}: newest entry is {raw!r} (version "
        f"{version!r}) but integration/pyproject.toml declares {expected!r}"
    )


# --------------------------------------------------------------- 3. pins

def test_model_extra_pins_every_git_dependency_to_a_commit_sha(repo_root):
    """Reproducibility depends on the ``[models]`` extra being immutable.

    A ``@main`` or ``@v1.2.0`` git reference re-resolves: the branch moves, and
    a tag can be moved or deleted. Either way the "same command, same numbers"
    claim on /models silently stops holding, and the drift is invisible because
    the pin still *looks* specific. Only a full 40-character commit SHA is an
    immutable reference.
    """
    optional = (
        _pyproject(repo_root)
        .get("project", {})
        .get("optional-dependencies", {})
    )
    assert "models" in optional, (
        "integration/pyproject.toml has no [project.optional-dependencies] "
        f"`models` extra (found: {', '.join(sorted(optional)) or 'none'})"
    )

    git_requirements = [
        requirement
        for requirement in optional["models"]
        if NON_GIT_MARKER in requirement
    ]
    assert git_requirements, (
        "the [models] extra declares no git dependencies — the model packages "
        "install from GitHub, so this is either a regression or this test needs "
        "updating"
    )

    problems: list[str] = []
    for requirement in git_requirements:
        match = re.search(r"git\+[^@\s]+@([^\s\"#]+)", requirement)
        if match is None:
            problems.append(
                f"{requirement!r} pins no revision at all — it will install "
                "whatever the default branch holds today"
            )
            continue
        revision = match.group(1)
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            problems.append(
                f"{requirement!r} is pinned to {revision!r}, which is not a "
                "full 40-character commit SHA (a branch or tag can move)"
            )
    assert not problems, (
        "integration/pyproject.toml [models] extra is not reproducibly "
        "pinned:\n  " + "\n  ".join(problems)
    )


# --------------------------------------------------------------- 4. readme

def test_readme_links_to_repo_paths_that_exist(repo_root):
    """No README link points at a file or directory that is not here.

    The README is the entry point for anyone arriving from the papers or from
    GitHub search. Its relative links are the ones that rot when a directory is
    renamed, and unlike the site's links nothing else in the repo resolves
    them.
    """
    readme = repo_root / "README.md"
    assert readme.is_file(), "README.md is missing from the repository root"

    broken: list[str] = []
    for number, line in enumerate(readme.read_text().splitlines(), start=1):
        for match in re.finditer(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", line):
            target = match.group(1)
            if target.startswith(
                ("http://", "https://", "#", "mailto:", "tel:", "data:")
            ):
                continue
            path = target.split("#", 1)[0].split("?", 1)[0]
            if not path:
                continue
            if not (repo_root / path).exists():
                broken.append(f"README.md:{number}: [{path}] does not exist in the repo")
    assert not broken, "\n  " + "\n  ".join(broken)


# --------------------------------------------------------------- 6. sanity

@pytest.mark.parametrize(
    "path",
    [
        "integration/pyproject.toml",
        "README.md",
        "vercel.json",
        "data/MANIFEST.json",
    ],
)
def test_files_the_rest_of_this_suite_reads_are_present(repo_root, path):
    """Fail loudly rather than vacuously if the repo layout moves."""
    assert (repo_root / path).is_file(), f"{path} is missing"
