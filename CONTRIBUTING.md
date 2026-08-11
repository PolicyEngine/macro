# Contributing

Thanks for helping. This repository holds three separable things, and each has
its own rules:

- **the site** — ~78 static HTML pages, no build step, many of them *generated*
- **the integration layer** (`integration/`) — the `pe-macro` CLI and the MCP
  server, published as the `policyengine-macro` package
- **two append-only archives** — `data/vintages/` and `forecasts/rounds/`

Read the section that matches what you are changing.

## Setup

```bash
git clone https://github.com/PolicyEngine/macro
cd macro
python3 -m http.server 8000        # the site, at http://localhost:8000/
```

Nothing needs installing to work on the site or the data pipelines: every
script under `data/`, `economy/`, `forecasts/`, `notes/`, `assets/` and the
repo root is **standard-library only**, on purpose. Keep it that way — a
dependency-free site pipeline is why CI can regenerate and verify every page in
seconds without an environment.

For the integration layer:

```bash
pip install -e "integration[models]" pytest      # full model install
pip install -e integration pytest                # fast: no model packages
```

The repo-root test suite needs nothing but pytest:

```bash
python3 -m pytest tests -q                       # site, data store, hygiene
cd integration && pytest tests -q                # integration layer (fast)
cd integration && pytest tests -q --runslow      # + real model solves (slow)
```

## The rules that are not negotiable

### 1. Generated pages are generated

Many pages are built from committed data by a script that also has a `--check`
mode. **Never hand-edit the generated block of such a page** — regenerate it.
`--check` runs in CI (`.github/workflows/site-provenance.yml`) and fails the
build if a committed page has drifted from the data it claims to show.

| generator | what it owns |
|-----------|--------------|
| `data/build_page.py` | `/data` catalogue and the release calendar |
| `economy/build.py` | the UK and US Economy pages |
| `forecasts/score.py` | `forecasts/scorecard.json` |
| `forecasts/make_open_fans.py` | open-round fan charts |
| `validation/figures/make_charts.py` | the model validation charts |
| `olg/figures/make_showcase.py` | the OLG showcase table |
| `assets/make_hero.py`, `assets/make_current_outlooks.py` | homepage and model-page charts |
| `notes/generate_release_notes.py` | release-note indexes |

Run the generator, commit both the script change and its output, and check that
`--check` passes.

### 2. The archives are append-only

`data/vintages/**` and `forecasts/rounds/**` may be **added to, never edited or
deleted**. This is enforced in CI, not by convention, because a silent rewrite
would look like a routine refresh in review and would destroy exactly the claim
the archive exists to support:

- A dated data snapshot that can be edited makes look-ahead bias undetectable.
- A forecast round that can be edited is not evidence that the forecast existed
  before its outturn did.

If upstream revises a series, `data/fetch.py` writes a **new** dated file beside
the old one. That is the intended behaviour, not a duplicate to clean up.

### 3. State limits in the same breath as capabilities

`integration/src/policyengine_macro/capabilities.py` is the authoritative
registry, and it deliberately records capabilities rather than model-level
badges — including a `cannot_answer` list per model. A model can be
production-ready for one use and inappropriate for another. When you extend a
model, update its entry, and keep site copy consistent with it.

Label anything illustrative as illustrative. Do not publish a number the
committed data does not support.

## Adding a model

A new model touches a fixed set of places; update all of them:

1. `<slug>/index.html` — the model reference page. Copy `olg/` or `obr/`:
   `<body class="doc">`, the shared nav, and the section rhythm (what it is →
   quickstart → how it works → levers → calibration).
2. `index.html` — a `.strategy-card` in the `#models` grid.
3. `models/index.html` — a `.doc-index` card, a comparison-table column, and a
   when-to-use bullet.
4. `connect/index.html` — a `<div class="model-pane" data-model="<slug>">` and a
   button in `#model-seg`.
5. `capabilities.py` — the registry entry, including `cannot_answer`.
6. `site_contract.py` — add the slug to `PUBLIC_MODELS`.
7. `README.md` — the models table and the site-paths table.

Pin the model dependency in `integration/pyproject.toml`'s `[models]` extra to
a **full 40-character commit SHA**, never a branch or tag. `tests/test_repo_hygiene.py`
asserts this: a tag can be moved and a branch always moves, and either would
silently change what a "reproducible" install produces.

## Pull requests

- One concern per PR. The CI gates are granular so a failure names the problem.
- Explain *why* in the code, not just what. The comments in this repository
  routinely cite the incident that motivated a guard — that convention is
  deliberate and worth continuing.
- Do not weaken a CI gate to make a PR pass. If a gate is wrong, fix the gate in
  its own PR and say what it was failing to protect.
- New public claims on the site need a source in the repository.

CI on a pull request runs: the repo-root suite (`site-tests.yml`), the
generator `--check` gates and navigation contracts (`site-provenance.yml`),
archive immutability (`data-immutability.yml`, `forecast-archive.yml`), and —
when `integration/**` changes — the fast integration suite. Slow full-model
contracts run nightly (`contract.yml`) and against the live deployment
(`validate-deployment.yml`).

## Releases

`integration/` publishes to PyPI as `policyengine-macro` when a GitHub release
is published (`.github/workflows/publish-pypi.yml`). Before releasing:

1. Bump `version` in `integration/pyproject.toml`.
2. Update `CHANGELOG.md` — the topmost heading must match that version.
3. Update `version` in `CITATION.cff` to match.

`tests/test_repo_hygiene.py` asserts all three agree, because a changelog that
disagrees with the published package is worse than no changelog.

## Open questions for maintainers

- **This repository has no `LICENSE` file.** Until it does, "open source" in the
  README is not accurate and the published package is, strictly, all rights
  reserved — which blocks adoption by universities and by any institution with
  a compliance review. `tests/test_repo_hygiene.py` carries an expected-failure
  test that will start passing the moment a licence is added.
- **No DOI.** Connecting the repository to Zenodo and minting a release would
  make the archives and figures citable; `CITATION.cff` is ready for the
  identifier.
