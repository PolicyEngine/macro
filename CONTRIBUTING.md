# Contributing

Thanks for helping. This repository holds three separable things, and each has
its own rules:

- **the site** — 84 static HTML pages, no build step, many of them *generated*
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
script under `data/`, `economy/`, `forecasts/`, `notes/`, `assets/`,
`validation/`, `olg/figures/` and the repo root is **standard-library only**,
on purpose. Keep it that way — a dependency-free site pipeline is why CI can
regenerate and verify every page in seconds without an environment.

Two deliberate exceptions, both outside that set:

- `forecasts/nowcast.py` imports `mcp` and `anyio` *lazily, inside the function
  that talks to the hosted server*, so `--due` and `--payload` still run on a
  bare interpreter.
- `papers/boe-svar/figures/make_current_forecast.py` calls the boe-svar adapter
  and must be run from the integration environment.

For the integration layer:

```bash
pip install -e "integration[models]" pytest      # full model install
pip install -e integration pytest                # fast: no model packages
```

The repo-root test suite needs nothing but pytest:

```bash
python3 -m pytest tests -q                       # site, data store, hygiene
python3 -m unittest discover -s forecasts/tests -p 'test_*.py'   # outturn ingest
cd integration && pytest tests -q                # integration layer (fast)
cd integration && pytest tests -q --runslow      # + real model solves (slow)
```

And the two contract scripts, which are checks rather than tests and are what
`site-provenance.yml` finishes with:

```bash
python3 site_nav.py                              # nav/crumbs/footer are current
python3 site_contract.py                         # public claims match the code
```

## The rules that are not negotiable

### 1. Generated pages are generated

Many pages are built from committed data by a script that also has a `--check`
mode. **Never hand-edit the generated block of such a page** — regenerate it.
`--check` runs on every pull request and fails the build if a committed page
has drifted from the data it claims to show. Which workflow runs which gate is
in the last column below — it is not all `site-provenance.yml`.

Almost every generated block is spliced between `<!-- name:begin -->` /
`<!-- name:end -->` markers in a committed page, so a page can be part
hand-written and part generated. Edit outside the markers freely; never inside.

| generator | what it owns | `--check` in CI |
|-----------|--------------|-----------------|
| `site_nav.py` | the global `<header class="nav">`, the pathway crumbs and the footer link row on **every** page. `--write` rewrites them; the bare invocation is the check, and it also fails on any page with no nav that is not in `NAV_EXEMPT`. | `site-provenance.yml` |
| `site_contract.py` | not a generator — a check-only contract over the public model inventory, the economy navigation, editorial claims, the documented MCP tool count, the `model NN` ordinals and every cross-page fragment anchor. | `site-provenance.yml` |
| `data/fetch.py` | the append-only vintage store under `data/vintages/` and the flattened `data/latest/`, from ONS, the Bank of England and FRED. `--check` validates the store and fetches nothing. | `data-immutability.yml` |
| `data/build_page.py` | the **data-store block inside `forecasts/index.html`** (between the `data-store` markers) and **`data/calendar.ics`**. There is no `/data` page; `/data` 308s to `/forecasts#data`. | `site-provenance.yml` |
| `economy/build.py` | the UK and US Economy pages (`economy-trends-figures`, `economy-series-index`, `economy-market-index`, `economy-calendar`, and the `us-economy-*` blocks) **and the homepage's `home-uk-now` / `home-us-now` blocks**. | `site-provenance.yml` |
| `economy/topics.py` | the six topic pages under `economy/topics/`, plus the `economy-topic-nav` and `economy-topics` blocks on `economy/index.html` **and the `economy-topics` block of `sitemap.xml`**. | `site-provenance.yml` |
| `notes/generate_release_notes.py` | the generated per-vintage note pages under `notes/releases/`, the `notes/releases/` index, the `generated-release-notes` block on `forecasts/index.html` **and in `sitemap.xml`**. | `site-provenance.yml` |
| `forecasts/score.py` | `forecasts/scorecard.json` and the four `scorecard-*` blocks on `forecasts/index.html`. Reads `rounds/` and `outturns.json`; never writes under `rounds/`. | `forecast-archive.yml` |
| `forecasts/make_open_fans.py` | the `open-fan-unemployment` block on `forecasts/index.html` (the svar-unemployment satellite round). | `forecast-archive.yml` |
| `forecasts/make_us_baseline.py` | the `us-longbase-baseline` table on `forecasts/us/index.html`, from the committed LONGBASE CSV. | `forecast-archive.yml` |
| `forecasts/archive.py` | copies the moving `papers/boe-svar/figures/current_forecast.json` into the **append-only** `forecasts/rounds/<round-id>/`. `--check` exits 1 if the history is inconsistent. | `forecast-archive.yml` |
| `forecasts/ingest_outturns.py` | `forecasts/outturns.json` — the data store mapped onto the variables the models forecast. Appends, never edits. | `forecast-archive.yml` |
| `forecasts/nowcast.py` | generates a forecast round from the hosted MCP server and archives it *before* the outturn exists. No `--check`; it is scheduled (`nowcast-round.yml`) and refuses far more often than it writes. | scheduled only |
| `validation/figures/make_charts.py` | every inline `<svg class="vchart" data-chart="…">` on `obr/validation`, `svar/validation`, `frb-us/validation` and `us-hank/validation`. | `site-provenance.yml` |
| `assets/make_hero.py` | the `hero-fan` inline SVG in the homepage hero. | `site-provenance.yml` |
| `assets/make_current_outlooks.py` | `obr-current-outlook` on `obr/index.html` and `boe-current-outlook` on `svar/index.html`. | `site-provenance.yml` |
| `olg/figures/make_showcase.py` | the `olg-stats` headline table on `olg/index.html`. | `site-provenance.yml` |
| `papers/boe-svar/figures/make_current_forecast.py` | `papers/boe-svar/figures/current_forecast.json` — the moving artifact behind the hero fan, the OBR/SVAR outlook charts and every archived round. Calls the hosted adapter, so **run it from the integration environment**; it has no `--check`. | — |

Run the generator, commit both the script change and its output, and check that
`--check` passes. `sitemap.xml` is otherwise **hand-maintained**: only the
`economy-topics` and `generated-release-notes` blocks are generated, so any
other new page needs a `<loc>` added by hand (see *Adding a model* below).

### 2. The archives are append-only

`data/vintages/**` and `forecasts/rounds/**` may be **added to, never edited or
deleted**. `data-immutability.yml` and `forecast-archive.yml` each diff the PR
against its **merge base** with `--diff-filter=MDR`, so Modified, Deleted and
Renamed all fail and only Added passes. A rename counts as a deletion: the path
*is* the identity of a snapshot (`source/series/date`), so moving one makes
every previous citation of it wrong. This is enforced in CI, not by convention,
because a silent rewrite would look like a routine refresh in review and would
destroy exactly the claim the archive exists to support:

- A dated data snapshot that can be edited makes look-ahead bias undetectable.
- A forecast round that can be edited is not evidence that the forecast existed
  before its outturn did.

If upstream revises a series, `data/fetch.py` writes a **new** dated file beside
the old one. That is the intended behaviour, not a duplicate to clean up. The
same goes for a forecast: a round cannot be corrected, only superseded by a
later round — which is why `forecasts/nowcast.py` refuses on anything
suspicious. A missed round costs one observation; a junk round is permanent.

### 3. State limits in the same breath as capabilities

`integration/src/policyengine_macro/capabilities.py` is the authoritative
registry, and it deliberately records capabilities rather than model-level
badges — including a `cannot_answer` list per model. A model can be
production-ready for one use and inappropriate for another. When you extend a
model, update its entry, and keep site copy consistent with it.

Label anything illustrative as illustrative. Do not publish a number the
committed data does not support.

## Adding a model

**This is the canonical checklist.** `README.md` links here and deliberately
keeps no copy of its own — two drifting versions is how the last one ended up
missing the steps that fail CI.

A model is not one page. It is **four pages**, two registries, three
navigation dicts, a hand-maintained sitemap and a derived ordinal that
renumbers its neighbours. The steps below are ordered so that following them
top-to-bottom ends with green CI, and each names the command that verifies it.

Throughout: the **registry id** and the **site id** are not always the same.
The capability registry keys the overlapping-generations model `og-uk`; the
site and `PUBLIC_MODELS` call it `psl-og` and its pages live under `olg/`. Pick
both ids up front and use each consistently.

### 1. The capability registry

`integration/src/policyengine_macro/capabilities.py` — add `MODELS[<registry-id>]`
with every field in `REQUIRED_CAPABILITY_FIELDS`, **including `cannot_answer`**,
which is the point of the registry: it records capabilities, not badges.
`quality` is filled in automatically — a model with no `MODEL_QUALITY` entry
gets `not_assessed` across all six `QUALITY_DIMENSIONS`, which is the honest
default. `validate_registry()` runs at import, so a missing or empty field
fails the moment anything imports the module.

If the model has no PolicyEngine-reform bridge, add it to
`core.SCORE_MODELS_WITHOUT_REFORM_BRIDGE` with the message saying what to use
instead. `score_reform` must never silently accept it and return a number.

> `cd integration && pytest tests/test_capabilities.py tests/test_site_contract.py -q`

### 2. The site contract

`site_contract.py` — add the **site id** to `PUBLIC_MODELS` *at the position the
site presents it*, and add the matching entry to `MODEL_PAGE_ROOTS` mapping it
to its page directory (plus `papers/<slug>` if it has a working paper).

**Both, or neither.** `check_model_ordinals` ends with
`set(MODEL_PAGE_ROOTS) ^ set(PUBLIC_MODELS)`, so adding to one and not the
other fails immediately.

> `python3 site_contract.py`

### 3. The four pages

Every model has a landing page **and three sub-pages**:

```
<slug>/index.html
<slug>/methodology/index.html
<slug>/validation/index.html
<slug>/code/index.html
```

Copy an existing model directory (`obr/` or `define/`) rather than writing one:
`<body class="doc">`, the shared nav, and the section rhythm (what it is →
quickstart → how it works → levers → calibration). Every page needs
`<!doctype html>` on line 1, `<html lang="en">`, `<meta charset>`, a viewport
meta, a **non-empty** `<meta name="description">`, a non-empty `<title>`,
exactly one `<h1>`, no skipped heading levels, and exactly one
`<link rel="canonical">` naming the URL the file is actually served at — no
`.html`, no trailing slash.

> `python3 -m pytest tests/test_site_integrity.py -q`

### 4. The `model NN` eyebrow

Each model page carries an eyebrow like
`model 04 &mdash; Federal Reserve macroeconomic model · frb-us · US · hosted`.
That number is **not** free text: `site_contract.check_model_ordinals` derives
it from `PUBLIC_MODELS.index(model) + 1` and checks every `index.html` under
each `MODEL_PAGE_ROOTS` entry, papers included.

So inserting a model anywhere other than the end **renumbers every model after
it**, and you must update those pages in the same PR. This check exists
because pe-microsim was promoted to lead the suite and twenty-eight pages went
on saying `model 06` while it was card 01 everywhere ordered.

> `python3 site_contract.py`

### 5. Navigation

`site_nav.py` — three dicts, and it is worth being precise about which:

- **`MODEL_ROOTS`** — add the top-level directory (`"<slug>"`). `section()`
  keys off `relative.parts[0]`, so this one entry makes the landing page *and*
  all three sub-pages highlight the **Models** tab. Miss it and they highlight
  nothing.
- **`PAGE_NAMES`** — add four entries: `/<slug>` with the model's display name,
  and `/<slug>/methodology`, `/<slug>/validation`, `/<slug>/code`. The crumb
  leaf falls back to the raw URL slug without them, so a reader sees
  `frb-us / methodology` instead of `FRB-US / Methodology`.
- **`CRUMB_PARENTS`** — add `"/<slug>": "/models"` only. The URL hierarchy is
  not the reading hierarchy at the top level (a model page reads as living
  under Models), but the sub-pages *do* sit under their model in both, so they
  need no override and adding one is noise.

A working paper under `papers/<slug>/` or a report under `reports/<slug>/`
needs its own `PAGE_NAMES` **and** `CRUMB_PARENTS` entry, both pointing at
`/models`.

Then regenerate; the header, crumbs and footer are generated on every page, so
never hand-write them:

> `python3 site_nav.py --write` then `python3 site_nav.py`

### 6. `sitemap.xml`

**Hand-maintained, and a hard CI gate.** Only the `economy-topics` and
`generated-release-notes` blocks have a generator; everything else is typed in.
`tests/test_site_integrity.py` asserts a bijection in both directions —
`test_sitemap_lists_every_public_page` fails if a committed page has no
`<loc>`, and `test_sitemap_entries_resolve` fails if a `<loc>` points at
nothing, or at a `vercel.json` redirect source that can never return 200.

So add **one `<loc>` per new page** — four for a model, plus one for any paper
or report page. This is the step that is easiest to forget and the one that
turns CI red.

> `python3 -m pytest tests/test_site_integrity.py -q`

### 7. The inventory pages

- **`index.html`** — a `.verification-card` in the `#validation` grid, placed
  in `PUBLIC_MODELS` order, and bump the "Explore all seven models" count.
- **`models/index.html`** — a `.strategy-card` in the all-models
  `.strategy-grid`, a `<details class="qa">` in `#choose`, a column in the
  `.comparison-table`, and a row in **both** `#validation` tables. Bump the
  count in the `#compare` heading and the table `<caption>` — and note that
  `check_public_model_inventory` asserts the **literal** string
  `"The seven models support"`, so that sentence has to be updated by hand or
  the contract fails.
- **`connect/index.html`** — a `<div class="model-pane" data-model="<slug>">`
  in `#code` and a matching button in `#model-seg`; the selector JS toggles on
  `data-model`, so the two must agree.

`check_public_model_inventory` also requires the site id to appear literally on
`index.html` and `models/index.html`.

Both files carry generated blocks (`hero-fan`, `home-uk-now`, `home-us-now` on
the homepage), so edit outside the markers and re-run the owning generators'
`--check`.

> `python3 site_contract.py` and `python3 -m pytest tests -q`

### 8. The integration layer, if the model is runnable

Adapter in `core.py`, a `pe-macro` command in `cli.py`, an `@mcp.tool` in
`mcp_server.py`. Then:

- Pin the model dependency in `integration/pyproject.toml`'s `[models]` extra
  to a **full 40-character commit SHA**, never a branch or tag.
  `tests/test_repo_hygiene.py` asserts this: a tag can be moved and a branch
  always moves, and either would silently change what a "reproducible" install
  produces. Leave it out of the extra if the model is local-only (as `oguk`
  and the DEFINE-UK R runtime are).
- Document every new tool in `integration/README.md`, **including the tool
  count in words** — `site_contract.check_docs_match_code` counts `@mcp.tool`
  in the server and fails if the README disagrees.
- Update the tool count in `integration/modal_app.py`'s module docstring. It is
  the other hand-written inventory, and it is checked for the same reason it
  once drifted to "20 tools" while the server had grown to 26.

> `python3 site_contract.py` and `cd integration && pytest tests -q`

### 9. Anything that quotes the registry

`economy/topics.py` renders each topic's model limitations straight out of
`capabilities.py` and verifies every CLI invocation against `cli.py` and every
tool name against the golden tool surface — so a new or renamed model can make
a committed topic page stale.

> `python3 economy/topics.py` then `python3 economy/topics.py --check`

### 10. `README.md`

The models table (statuses copied verbatim from `capabilities.py`), the
model-page links, and the site-paths table.
`tests/test_repo_hygiene.py::test_readme_links_to_repo_paths_that_exist`
fails on any relative link to a path that does not exist.

### 11. Verify the whole thing

```bash
python3 site_nav.py
python3 site_contract.py
python3 -m pytest tests -q
cd integration && pytest tests -q
```

Keep model copy grounded in the model's own repo and docs, and label any
non-real numbers as illustrative.

## Pull requests

- One concern per PR. The CI gates are granular so a failure names the problem.
- Explain *why* in the code, not just what. The comments in this repository
  routinely cite the incident that motivated a guard — that convention is
  deliberate and worth continuing.
- Do not weaken a CI gate to make a PR pass. If a gate is wrong, fix the gate in
  its own PR and say what it was failing to protect.
- New public claims on the site need a source in the repository.

CI on a pull request runs, on every PR:

| workflow | what it gates |
|----------|---------------|
| `site-tests.yml` | the repo-root suite — `tests/test_site_integrity.py`, `tests/test_data_store.py`, `tests/test_repo_hygiene.py`. pytest and nothing else installed. |
| `site-provenance.yml` | nine generator `--check` gates, then `site_nav.py` and `site_contract.py`. |
| `data-immutability.yml` | `data/vintages/**` is append-only, plus `data/fetch.py --check`. |
| `forecast-archive.yml` | `forecasts/rounds/**` is append-only, plus `archive.py`, `ingest_outturns.py`, `score.py`, `make_open_fans.py` and `make_us_baseline.py` `--check`, and the `forecasts/tests` unittest suite. |
| `test-integration.yml` | the fast integration suite — **only when `integration/**` changes** (path-filtered), or on manual dispatch. |

Scheduled, not on a PR: slow full-model upstream contracts nightly
(`contract.yml`), the live deployment daily and deeply on Sundays
(`validate-deployment.yml`), the weekday vintage fetch (`fetch-vintages.yml`),
and the pre-release forecast round (`nowcast-round.yml`). Merging to `main`
with changes under `integration/` redeploys the hosted MCP server
(`deploy-mcp.yml`), as does a `repository_dispatch` from a model repo.

A path-filtered gate is a gate that does not run: a change to `core.py`'s model
list will not trigger `test-integration.yml` from a site-only PR. Dispatch it
by hand if you touched something it covers indirectly.

## Releases

`integration/` publishes to PyPI as `policyengine-macro` when a GitHub release
is published (`.github/workflows/publish-pypi.yml`; `workflow_dispatch` is also
available). The current version is **0.2.0**. Before releasing:

1. Bump `version` in `integration/pyproject.toml`.
2. Update `CHANGELOG.md` — the **topmost** version heading must match, not just
   a mention somewhere in the history. That is the exact failure mode: the
   release ships and its entry is never written.
3. Update `version` in `CITATION.cff` to match, and `date-released` with it.

`tests/test_repo_hygiene.py` asserts all three agree, because a changelog that
disagrees with the published package is worse than no changelog. The workflow
gates the upload on the fast integration suite plus
`tests/test_tool_surface.py`, because the ordinary PR suite does not run on
release events at all — and an upload that reaches PyPI cannot be taken back.

Note the workflow's own caveat: until the PyPI trusted publisher is configured,
the publish step fails with `invalid-publisher`. That is the workflow working
correctly against an unconfigured project, not a broken build.

## Open questions for maintainers

- **No DOI.** Connecting the repository to Zenodo and minting a release would
  make the archives and figures citable; `CITATION.cff` is ready for the
  identifier.
