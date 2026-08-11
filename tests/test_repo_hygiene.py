"""Repository-level provenance: licence, citation, changelog, and pins.

The class of regression this prevents
-------------------------------------
This repo publishes working papers, asks to be cited, and claims in
``README.md`` and across ``/models`` that its results are reproducible. Four
files carry those claims outside the website, and none of them is exercised by
any other check in the repo:

* **LICENSE** — without one, "open source" is not a licence grant. Nobody may
  legally reuse the models, and the site says they may. The declared SPDX
  identifier and the shipped licence text have to be the same licence, or the
  package metadata is telling installers something the file does not.
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

# Fingerprints for identifying which licence a LICENSE file actually contains,
# so a file whose text disagrees with the declared SPDX id is caught. Ordered
# most-specific first; each entry is (SPDX id, phrases that must all appear).
LICENSE_FINGERPRINTS: list[tuple[str, tuple[str, ...]]] = [
    ("AGPL-3.0", ("GNU AFFERO GENERAL PUBLIC LICENSE", "Version 3")),
    ("GPL-3.0", ("GNU GENERAL PUBLIC LICENSE", "Version 3")),
    ("LGPL-3.0", ("GNU LESSER GENERAL PUBLIC LICENSE", "Version 3")),
    ("Apache-2.0", ("Apache License", "Version 2.0")),
    ("MPL-2.0", ("Mozilla Public License Version 2.0",)),
    ("BSD-3-Clause", ("Redistribution and use", "Neither the name")),
    ("BSD-2-Clause", ("Redistribution and use",)),
    ("MIT", ("Permission is hereby granted, free of charge",)),
]

# Dependency specifiers in the [models] extra that are not git checkouts and so
# have no commit to pin. These come from PyPI, where a version specifier is the
# reproducible form; test_source_pins.py in integration/ covers the deployment
# side of the same question.
NON_GIT_MARKER = "git+"


# --------------------------------------------------------------- helpers

def _pyproject(repo_root: Path) -> dict:
    return tomllib.loads((repo_root / "integration" / "pyproject.toml").read_text())


def _package_version(repo_root: Path) -> str:
    version = _pyproject(repo_root).get("project", {}).get("version")
    assert version, "integration/pyproject.toml declares no [project] version"
    return version


def _declared_license(repo_root: Path) -> str | None:
    """The SPDX identifier ``integration/pyproject.toml`` declares, if any.

    PEP 639 allows a bare string (``license = "MIT"``); the older PEP 621 form
    is a table with ``text`` or ``file``. Classifiers are the last resort,
    because a ``License ::`` classifier is what older packaging used.
    """
    project = _pyproject(repo_root).get("project", {})
    license_field = project.get("license")
    if isinstance(license_field, str):
        return license_field.strip()
    if isinstance(license_field, dict):
        text = license_field.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    for classifier in project.get("classifiers", []):
        if classifier.startswith("License :: OSI Approved ::"):
            return classifier.split("::")[-1].strip()
    return None


def _identify_license(text: str) -> str | None:
    """Which licence the LICENSE file actually contains."""
    explicit = re.search(r"SPDX-License-Identifier:\s*([^\s]+)", text)
    if explicit:
        return explicit.group(1).strip()
    for spdx, phrases in LICENSE_FINGERPRINTS:
        if all(phrase.lower() in text.lower() for phrase in phrases):
            return spdx
    return None


def _same_license(declared: str, detected: str) -> bool:
    """Compare SPDX ids tolerantly.

    ``AGPL-3.0``, ``AGPL-3.0-only`` and ``AGPL-3.0-or-later`` are the same
    licence for this purpose, as are case variants.
    """
    normalise = lambda value: re.sub(  # noqa: E731 - local, single use
        r"-(only|or-later)$", "", value.strip().lower()
    )
    return normalise(declared) == normalise(detected)


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


# --------------------------------------------------------------- 1. licence

# Expected to fail: choosing a licence is a maintainer decision that has been
# deliberately deferred, not an oversight (see CONTRIBUTING.md, "Open questions
# for maintainers"). The test is written to be *correct*, not to pass, so the
# day a LICENSE lands it turns green on its own and starts guarding the real
# invariant — that the file on disk and the SPDX id in pyproject agree.
#
# `strict=False` on purpose: an XPASS here is the good news, not a CI failure.
# Deleting this test instead of xfailing it would delete the only machine-
# readable record that the gap exists.
@pytest.mark.xfail(
    reason=(
        "no LICENSE file yet — licensing decision deferred by the maintainers. "
        "Until one exists there is no open-source grant, and the published "
        "package is strictly all rights reserved."
    ),
    strict=False,
)
def test_repository_ships_a_license_matching_its_declared_spdx_id(repo_root):
    """A LICENSE file exists, has content, and is the licence we declare.

    The site and README describe this work as open source and invite reuse of
    the models and the papers. Without a LICENSE file that is not a licence
    grant — default copyright reserves every right — so the invitation is one
    nobody can legally accept.
    """
    candidates = [
        repo_root / name
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
    ]
    present = [path for path in candidates if path.is_file()]
    assert present, (
        "no LICENSE file at the repository root (looked for "
        + ", ".join(path.name for path in candidates)
        + "). README.md and the site describe this work as open source, which "
        "is not true without one."
    )

    license_file = present[0]
    text = license_file.read_text()
    assert text.strip(), f"{license_file.name} is empty"

    declared = _declared_license(repo_root)
    assert declared, (
        "integration/pyproject.toml declares no license: add "
        f'`license = "<SPDX id>"` under [project] to match {license_file.name}'
    )

    detected = _identify_license(text)
    assert detected is not None, (
        f"{license_file.name} does not match any known licence text and carries "
        "no `SPDX-License-Identifier:` line, so it cannot be checked against "
        f"the {declared!r} declared in integration/pyproject.toml"
    )
    assert _same_license(declared, detected), (
        f"integration/pyproject.toml declares license = {declared!r} but "
        f"{license_file.name} contains the {detected!r} licence text"
    )


# --------------------------------------------------------------- 2. citation

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


# --------------------------------------------------------------- 3. changelog

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


# --------------------------------------------------------------- 4. pins

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


# --------------------------------------------------------------- 5. readme

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
