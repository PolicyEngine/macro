"""The model commit a page shows is the commit this repository installs.

The class of regression this prevents
-------------------------------------
``integration/pyproject.toml`` pins four model repositories by commit. The
model pages quote figures "at 0e44ec8" and link source files at that commit.
A re-pin edits one line of the pyproject and, until now, nothing connected it
to the forty-odd links and the hero strips that name the old commit: the pages
would go on citing artifacts from a commit the hosted tools no longer run.

Three checks, all structural:

* the hero strip on every model page is what ``tools/model_hero.py`` would
  stamp today, which includes the pin chip read from the pyproject;
* each pinned model's four tabs carry that chip;
* every link from the site into a pinned repository *at a commit* names the
  pinned commit, apart from the few listed below that cite an older commit on
  purpose.

Links to ``blob/main`` are not checked here. Some are deliberate (a section
that exists only on ``main``), and telling those from an oversight needs a
person; the pin chip gives the reader the pinned commit either way.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# (page, 7-character commit) pairs that link an older commit deliberately.
# Each needs the reason: this list is where a stale link would hide.
HISTORICAL_PINS = {
    # "the figures before that are at c827ab8": the pre-refresh run, named as such.
    ("svar/validation/index.html", "c827ab8"),
}


def _model_hero():
    spec = importlib.util.spec_from_file_location("model_hero", ROOT / "tools" / "model_hero.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("model_hero", module)
    spec.loader.exec_module(module)
    return module


HERO = _model_hero()
PINS = HERO.model_pins()
COMMIT_LINK = re.compile(
    r"github\.com/(PolicyEngine/[\w.-]+)/(?:blob|tree|commit|raw)/([0-9a-f]{7,40})(?=[/\"#?])"
)


def test_every_pinned_model_declares_a_full_commit():
    """Forty hex characters: a branch or a tag would move under the pages."""
    assert set(PINS) == set(HERO.PIN_REPOS)
    for key, (repo, commit) in PINS.items():
        assert re.fullmatch(r"[0-9a-f]{40}", commit), f"{key}: {repo} is pinned to {commit!r}"


@pytest.mark.parametrize("rel", sorted(HERO.PAGES))
def test_model_hero_is_current(rel):
    """``python3 tools/model_hero.py`` would change nothing on this page."""
    source = (ROOT / rel).read_text()
    assert HERO.stamp(rel, source) == source, (
        f"{rel}: the model hero strip is stale. Run `python3 tools/model_hero.py` "
        "(after a re-pin in integration/pyproject.toml this is expected)."
    )


@pytest.mark.parametrize("key", sorted(HERO.PIN_REPOS))
def test_model_tabs_show_the_pinned_commit(key):
    repo, commit = PINS[key]
    href = f'href="https://github.com/{repo}/tree/{commit}"'
    for sub in ("", "methodology/", "validation/", "code/"):
        rel = f"{key}/{sub}index.html"
        source = (ROOT / rel).read_text()
        assert 'class="mh-chip mh-pin"' in source and href in source, (
            f"{rel}: no pin chip linking {repo} at {commit[:7]}"
        )


def test_commit_links_into_pinned_repositories_name_the_pin(pages):
    """A source link at a commit other than the pin cites a superseded artifact."""
    pinned = {repo: commit for repo, commit in PINS.values()}
    stale = []
    for page in pages:
        for match in COMMIT_LINK.finditer(page.source):
            repo, commit = match.groups()
            if repo not in pinned or pinned[repo].startswith(commit):
                continue
            if (page.rel, commit[:7]) in HISTORICAL_PINS:
                continue
            line = page.source.count("\n", 0, match.start()) + 1
            stale.append(f"{page.rel}:{line}: {repo} at {commit[:7]}, pinned at {pinned[repo][:7]}")
    assert not stale, (
        "links cite a commit other than the one integration/pyproject.toml pins "
        "(move them, or list the pair in HISTORICAL_PINS with the reason):\n  "
        + "\n  ".join(stale)
    )
