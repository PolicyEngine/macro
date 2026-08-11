# PolicyEngine Macro

**PolicyEngine Macro** is an open platform for answering economic and public-policy
questions with transparent, reproducible models. It brings household analysis,
macroeconomic scenarios, forecasts, empirical shock identification, long-run
structural analysis and ecological stock-flow scenarios behind a common
discovery and run surface.

🌐 **[policyengine-macro.vercel.app](https://policyengine-macro.vercel.app)** · a PolicyEngine project

---

## The models

Each model answers a different class of economic question. PolicyEngine Macro provides a
common way to discover, run, and interpret them while preserving the assumptions,
horizons, evidence, and outputs specific to each model. Results from different
model classes are often complementary rather than directly comparable.

Seven models are public, in the order the site presents them
(`site_contract.py`'s `PUBLIC_MODELS`, which is also what the `model NN`
eyebrow on each model page is checked against). Every status below is the
`status` field of that model's entry in
[`integration/src/policyengine_macro/capabilities.py`](integration/src/policyengine_macro/capabilities.py),
verbatim — that registry is authoritative and this table is a copy of it.

| # | model | status | repo |
|---|-------|--------|------|
| 01 | **`pe-microsim`** — PolicyEngine tax-benefit microsimulation | production-ready for selected household applications | [PolicyEngine/policyengine.py](https://github.com/PolicyEngine/policyengine.py) |
| 02 | **`obr-macro`** — OBR macroeconometric emulator | validated for selected scenarios | [PolicyEngine/obr-macroeconomic-model](https://github.com/PolicyEngine/obr-macroeconomic-model) |
| 03 | **`boe-svar`** — Bank of England structural VAR replication | validated replication for selected outputs | [PolicyEngine/boe-var-model](https://github.com/PolicyEngine/boe-var-model) |
| 04 | **`frb-us`** — Federal Reserve FRB-US implementation | validated software replication with scope limits | [PolicyEngine/us-frb-model](https://github.com/PolicyEngine/us-frb-model) |
| 05 | **`us-hank`** — US two-asset HANK (Auclert–Bardóczy–Rognlie–Straub 2021) | validated replication for hosted stylized-shock experiments; VAR-free sequence-space HANK; not a forecaster; distributional outputs are first-order approximations | [PolicyEngine/us-hank-model](https://github.com/PolicyEngine/us-hank-model) |
| 06 | **`psl-og`** — OG-UK overlapping generations model | research prototype; calibrated counterfactual | [PSLmodels/OG-UK](https://github.com/PSLmodels/OG-UK) |
| 07 | **`define-uk`** — DEFINE-UK ecological stock-flow consistent model | experimental; partial replication — baseline macro block replicates manual Table 4; scenario deltas gated on the pinned oracle run, the published scenario definitions, and two paper anchors (no numeric v1.1 scenario results are published); unlicensed upstream is never hosted, so hosted calls return run instructions | [PolicyEngine/define-uk-model](https://github.com/PolicyEngine/define-uk-model) (upstream [DEFINE-model/DEFINE_UK_1.1](https://github.com/DEFINE-model/DEFINE_UK_1.1)) |
| — | More model classes (incl. OG-USA) | planned | — |

**One naming split to know about.** The site calls the overlapping-generations
model `psl-og` (its pages live under `olg/`), while the capability registry
keys it `og-uk`. The registry id is what the tooling takes: the CLI contract is
`pe-macro score --model og`, and `pe-macro model-status og-uk` is how you read
its entry. Reader-facing prose on the site and in this README says `psl-og`.

The registry also carries `og+microsim`, a composite dynamic-scoring path
(OG-UK steady state feeding a second microsimulation run) rather than an eighth
model, so it has no page of its own — see `pe-macro dynamic-score`.

PolicyEngine is the *micro* member and now leads the suite: person/household-
resolution taxes and benefits for the UK and US — the same engine that powers
[policyengine.org](https://policyengine.org) — and the only member covering both
countries.

The models live in their own repositories. This repo hosts the **PolicyEngine Macro
website** and the **integration layer** (`integration/`) — a `pe-macro` CLI
and MCP server over the models, with CI auto-deploying the hosted MCP server
to Modal on every merge to `main` that touches `integration/`
(`.github/workflows/deploy-mcp.yml`) — merges to the model repos trigger the
same redeploy via `repository_dispatch` — so you can drive them from any AI
workflow.

The OBR emulator also runs as a live dashboard:
[obr-macroeconomic-model.vercel.app](https://obr-macroeconomic-model.vercel.app/).

## Quickstart — score a reform

`psl-og` is a Python package (`oguk`); pip installs it straight from GitHub, no
clone needed (Python 3.11+, per `olg/code/01_install.sh`).

```bash
pip install git+https://github.com/PSLmodels/OG-UK
```

```python
from datetime import datetime
from policyengine.core import ParameterValue, Policy
from policyengine.tax_benefit_models.uk import uk_latest
from oguk import solve_steady_state, map_to_real_world

# Build a reform from real PolicyEngine parameters (basic rate 20% → 21%)
param = uk_latest.get_parameter("gov.hmrc.income_tax.rates.uk[0].rate")
reform = Policy(name="Basic rate 21%", parameter_values=[
    ParameterValue(parameter=param, value=0.21,
                   start_date=datetime(2026, 1, 1))])

# Solve baseline and reform steady states (~5–15 min each)
baseline  = solve_steady_state(start_year=2026)
reform_ss = solve_steady_state(start_year=2026, policy=reform)

# Map model units → current-price £bn
impact = map_to_real_world(baseline, reform_ss)
print(f"GDP change: {impact.gdp_change:+.1f}bn ({impact.gdp_pct:+.3f}%)")
```

See the [psl-og model page](https://policyengine-macro.vercel.app/olg) for the full
guide — parameter paths, solver options, structural shocks, and the transition
path. Every model has its own page plus `methodology`, `validation` and `code`
sub-pages: [pe-microsim](https://policyengine-macro.vercel.app/pe),
[obr-macro](https://policyengine-macro.vercel.app/obr),
[boe-svar](https://policyengine-macro.vercel.app/svar),
[frb-us](https://policyengine-macro.vercel.app/frb-us),
[us-hank](https://policyengine-macro.vercel.app/us-hank),
[psl-og](https://policyengine-macro.vercel.app/olg),
[define-uk](https://policyengine-macro.vercel.app/define). The
[model comparison](https://policyengine-macro.vercel.app/models#compare) puts all
seven side by side and says when to use which.

## Connecting to an AI

The [connect page](https://policyengine-macro.vercel.app/connect) covers three ways to use the
models:

- **MCP** — the hosted Model Context Protocol server is **live** at
  `https://policyengine--policyengine-macro-mcp-serve.modal.run/mcp`. Add it as a custom
  connector in Claude or ChatGPT, or in Claude Code:

  ```bash
  claude mcp add --transport http policyengine-macro https://policyengine--policyengine-macro-mcp-serve.modal.run/mcp
  ```

  The server exposes **26 tools** (`@mcp.tool` functions in
  [`integration/src/policyengine_macro/mcp_server.py`](integration/src/policyengine_macro/mcp_server.py);
  `site_contract.check_docs_match_code` fails CI if the count drifts from
  [`integration/README.md`](integration/README.md), which documents each one):

  - **routing and reporting** — `list_model_capabilities`, `get_model_status`,
    `recommend_model`, `format_score_report`
  - **scoring** — `score_reform`, `dynamic_reform_impact`
  - **OBR** — `obr_shock`, `list_reform_variables`
  - **FRB/US** — `frbus_shock`, `frbus_list_variables`, `frbus_summary`
  - **US HANK** — `hank_shock`, `hank_summary`
  - **UK SVAR** — `forecast_uk`, `latest_shocks`, `model_summary`
  - **PolicyEngine microsimulation** — `calculate_household`,
    `household_reform_impact`, `list_reform_parameters`,
    `population_reform_impact`
  - **DEFINE-UK** — `define_list_scenarios`, `define_scenario`,
    `define_scenario_incidence`
  - **experimental incidence overlays** — `frbus_shock_incidence`,
    `hank_shock_incidence`, `svar_inflation_incidence`

  `score_reform` takes `model` from `("og", "obr", "microsim", "og+microsim")`
  and deliberately refuses `'frbus'`, `'hank'`, `'svar'` and `'define'`: those
  models have no PolicyEngine-reform bridge, and inventing one would be a
  guess. `score_reform` with `model='og'` works locally only — OG-UK is
  excluded from the hosted image because a score takes tens of minutes — so
  use `pe-macro score --model og` instead. DEFINE-UK's unlicensed upstream is
  never hosted either, so hosted `define_*` calls return run instructions. The
  OBR reform bridge translates a static population costing through the OBR
  emulator's `HHDI_ADDFACTOR` interface; it is a demand-side approximation, not
  a general reform-incidence model. Direct OBR scenarios use `obr_shock`.
  The server runs serverless and scales to zero — the first call after idle
  may take ~10 s to wake.
- **CLI** — the `pe-macro` CLI lives in [`integration/`](integration/); PyPI
  publish is planned. It has **27 commands** (`@main.command` in
  [`integration/src/policyengine_macro/cli.py`](integration/src/policyengine_macro/cli.py)):
  `model-status`, `score`, `report`, `compare`, `obr-shock`, `variables`,
  `frbus-shock`, `frbus-variables`, `frbus-summary`, `hank-shock`,
  `hank-summary`, `forecast`, `shocks`, `summary`, `household`,
  `household-impact`, `population-impact`, `parameters`, `og-score`,
  `og-baseline`, `dynamic-score`, `define-scenarios`, `define-scenario`,
  `define-incidence`, `frbus-shock-incidence`, `hank-shock-incidence`,
  `svar-inflation-incidence`. Install it with PolicyEngine, the OBR emulator,
  the SVAR, FRB/US and US HANK via:

  ```bash
  pip install "policyengine-macro[models] @ git+https://github.com/PolicyEngine/macro#subdirectory=integration"
  ```

  The `[models]` extra pins every git dependency to a full 40-character commit
  SHA and installs FRB-US with its packaged model and LONGBASE runtime data;
  no separate checkout is required. `oguk` and the DEFINE-UK adapter's R
  runtime are **not** in the extra — both are local-only, and OG-UK needs its
  own environment until [PSLmodels/OG-UK#68](https://github.com/PSLmodels/OG-UK/issues/68)
  lands.
- **Code** — drive each model's Python API yourself.

## The site

A static site in the [populace.dev](https://populace.dev) design language — no
build step.

```bash
python3 -m http.server 8000   # then open http://localhost:8000/
```

84 committed HTML pages, all of them listed in `sitemap.xml`
(`tests/test_site_integrity.py` asserts that bijection both ways).

| path | page |
|------|------|
| `index.html` | the suite — idea, models, pipeline, outputs |
| `models/` | model discovery — choose by question (`#choose`), compare all seven (`#compare`), validation evidence (`#validation`), source literature (`#evidence`), scoring (`#score`) |
| `pe/` | model 01 — PolicyEngine tax-benefit microsimulation: household calculator, reforms, population analysis |
| `obr/` | model 02 — the OBR macroeconometric emulator: quickstart, solver, levers, forecasting |
| `svar/` | model 03 — the Bank of England structural VAR: the model, quickstart, outputs |
| `frb-us/` | model 04 — the Federal Reserve FRB/US model: equations, expectations, LONGBASE |
| `us-hank/` | model 05 — the US two-asset HANK model: stylized shocks, sequence-space solution |
| `olg/` | model 06 — the OG-UK overlapping-generations model (`psl-og`): install, quickstart, options, shocks, outputs |
| `define/` | model 07 — the DEFINE-UK ecological stock-flow model: scenarios, gates, deltas |
| ↳ `<model>/methodology/`, `<model>/validation/`, `<model>/code/` | every model page carries the same three sub-pages — 7 × 4 = 28 pages |
| `economy/` | the UK economy — indicators, markets, trends, releases, and the topic directory |
| `economy/us/` | the same for the US |
| `economy/topics/<topic>/` | six question-first entry pages: `growth`, `inflation`, `jobs`, `rates`, `public-finances`, `reform` |
| `forecasts/` | the forecast track record, plus the data store (`#data`) and the release notes index (`#notes`) |
| `forecasts/us/` | why there is no US track record yet |
| `papers/<slug>/` | the four working-paper pages: `obr-macro`, `boe-svar`, `frb-us`, `psl-og` (`papers/us-hank/` holds figures only, and `papers/*.pdf` are served directly) |
| `reports/` | replication reports — `define-uk-replication/` and `us-hank-open-source.html` |
| `notes/releases/` | index of the generated per-vintage release notes, plus `notes/<date>-<slug>/` note pages |
| `connect/` | connect it or code it — MCP / CLI setup and the Python API |
| `contact/` | who to contact |

**Not pages.** `vercel.json` 308-redirects nine URLs that were once pages, or
that are directory prefixes with no index page. None of them has an
`index.html` on disk, and none may appear in `sitemap.xml`:

| retired URL | 308 → |
|-------------|-------|
| `/docs` | `/models#compare` |
| `/papers` | `/models#evidence` |
| `/validation` | `/models#validation` |
| `/score` | `/models#score` |
| `/data` | `/forecasts#data` |
| `/notes` | `/forecasts#notes` |
| `/economy/topics` | `/economy#topics` |
| `/economy/trends` | `/economy#trends` |
| `/economy/us/trends` | `/economy/us#trends` |

The `data/` directory survives as a served JSON tree (`MANIFEST.json`,
`latest/`, `vintages/`, `calendar.ics`) with its own CORS and cache headers —
it just has no HTML page. `tests/test_site_integrity.py` checks every redirect
destination, including its fragment, still resolves.

Deployed on Vercel (PolicyEngine team). `vercel.json` enables clean URLs
(`cleanUrls`, `trailingSlash: false`), so link to `/models`, never
`/models/index.html` or `/models/`.

## The data

Every official series the site depends on is archived as **dated, immutable
snapshots** under `data/vintages/<source>/<series>/<YYYY-MM-DD>.json`, fetched
from ONS, the Bank of England and FRED. Official statistics get revised, so
reading only "the latest data" means silently rewriting your own history on
every revision — a forecast that never changed can be made to look better or
worse by data it could not have known about, and look-ahead bias becomes
undetectable because only one version of the past is ever on disk.

Dated snapshots make both visible. Nothing under `data/vintages/` is ever
edited or deleted; CI enforces it. A revision arrives as a **new file beside
the old one**, never as an edit.

The store is public JSON, served with permissive CORS, so it can be read
directly from a notebook, a browser, or a dashboard:

| endpoint | what it is | caching |
|----------|-----------|---------|
| `/data/MANIFEST.json` | generated index of every tracked series | short TTL |
| `/data/latest/<series>.json` | newest snapshot, flattened | short TTL |
| `/data/vintages/<source>/<series>/<date>.json` | the series exactly as published on `<date>` | immutable, one year |
| `/data/calendar.ics` | announced upcoming release dates | short TTL |

Reconstructing a series as a forecaster would have seen it on a given date is
one request:

```python
import json, urllib.request

BASE = "https://policyengine-macro.vercel.app/data"
as_of = "2026-07-25"     # the vintage you want to see the world through
snap = json.load(urllib.request.urlopen(
    f"{BASE}/vintages/ons/uk_cpi_yoy/{as_of}.json"))
print(snap["observations"][-1])   # {'period': '2026Q2', 'value': 2.8}
```

Browse it at [`/forecasts#data`](https://policyengine-macro.vercel.app/forecasts#data)
— the full catalogue, the schema, the release calendar and the recipe above,
in the section that explains what a forecast round is scored against. The
[forecast track record](forecasts/) records which vintage each score was
computed against, so any published number can be reproduced.

## Contributing

Many pages here are **generated** from committed data by a script with a
`--check` mode that CI enforces, and two archives (`data/vintages/`,
`forecasts/rounds/`) are **append-only**. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before making changes — it covers both, plus
the model-capability registry and the release process. Security policy is in
[SECURITY.md](SECURITY.md); changes are recorded in [CHANGELOG.md](CHANGELOG.md).

> **Licensing:** this repository does not yet carry a `LICENSE` file. Until it
> does, no open-source grant is in effect. If you intend to depend on it, open
> an issue so the decision gets made.

## Adding a model

The checklist has one canonical home:
[**CONTRIBUTING.md § Adding a model**](CONTRIBUTING.md#adding-a-model). It is
ordered so that following it top-to-bottom ends with green CI, and it names the
command that verifies each step. Adding a model also renumbers the `model NN`
eyebrow on every model inserted after it, because that number is derived from
`site_contract.PUBLIC_MODELS`' index rather than written by hand — so the
checklist is not optional.

## Roadmap

- [x] `pe-macro` CLI (in `integration/`; PyPI publish still to come)
- [x] Local MCP server (`python -m policyengine_macro.mcp_server`)
- [x] Hosted MCP server (`https://policyengine--policyengine-macro-mcp-serve.modal.run/mcp`, auto-deployed by CI)
- [x] OG-UK steady-state scoring (`pe-macro score --model og` / `pe-macro og-score`, local only)
- [x] Population-level PolicyEngine reform scoring (`population_reform_impact`, hosted and local)
- [x] FRB/US Python implementation ([PolicyEngine/us-frb-model](https://github.com/PolicyEngine/us-frb-model)), wired into the CLI (`pe-macro frbus-shock`) and the hosted MCP server
- [x] US HANK model ([PolicyEngine/us-hank-model](https://github.com/PolicyEngine/us-hank-model)), wired into the CLI (`pe-macro hank-shock`) and the hosted MCP server
- [x] DEFINE-UK adapter ([PolicyEngine/define-uk-model](https://github.com/PolicyEngine/define-uk-model)), wired into the CLI (`pe-macro define-scenario`) and the hosted MCP server, which returns run instructions because the unlicensed upstream is never hosted
- [x] Dynamic scoring overlay (`og+microsim`: `pe-macro dynamic-score` / `dynamic_reform_impact`, local only)
- [ ] Additional macroeconomic model classes (incl. OG-USA)

---

A [PolicyEngine](https://policyengine.org) project. Publicly developed; the
licence is still to be decided — see [Contributing](#contributing).
