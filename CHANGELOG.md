# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [semantic versioning](https://semver.org/spec/v2.0.0.html).

The version below tracks the `policyengine-macro` package in `integration/`.
`CITATION.cff` and `integration/pyproject.toml` must agree with the topmost
heading here; `tests/test_repo_hygiene.py` asserts that they do.

## [Unreleased]

### Adapters: labels from two open model PRs, `horizon` deprecated

- **`obr_shock`** forwards three more of the model's labels when the model sets them: `subsidy_residual_warning`, `procurement_residual_warning` and `nominal_consistent_legs` (obr-macroeconomic-model #90). The first two say that the listing's subsidy or procurement residual absorbed the shock, so the borrowing figures are not the effect of the spending change. The current pin sets `nominal_consistent_legs` only, for `CGG`; the warnings arrive with a re-pin.
- **`define_scenario`** reports a `BaselineParameterMismatch` (define-uk-model #36) as its own refusal, `"refused": "baseline parameter mismatch"`, like the stock-flow one. It fell into the generic branch, whose hint is about a cached run that does not depart from baseline. The class is matched by name, so the adapter works before and after the DEFINE re-pin.
- **`recommend_model`**: `horizon` is deprecated (#210). It never changed the routing. It stays in the tool schema and is echoed back, so no caller breaks; a caller who passes it now gets `horizon_note` (and Python callers a `DeprecationWarning`) saying it was ignored and pointing at each candidate's own `horizon` under `details`.
- **Drift canary `hank_25bp_easing`** gains a `description`: the 25bp is per quarter, a shift in the Taylor-rule intercept of about 100bp annualised. The id is unchanged, so drift reports and #264 still refer to it.

### BoE SVAR re-pin to `17f5d82`

- **Pin.** BoE SVAR `c827ab86` → `17f5d824` (boe-var-model #34, world CPI seasonal adjustment; #35, November 2026 MPR comparator and 2026Q3 scoring). After a redeploy the hosted `forecast_uk` and `latest_shocks` run this pin.
- **Replication figures** (`results/summary.md` at `17f5d82`): accepted draws 765 → 731, ESS 368.0 → 333.3; global share of UK GDP variance 38.7 → 37.6%, of UK CPI 41.5 → 52.0% (paper about 50%); domestic share of UK CPI 36.8 → 24.8% (paper about 40%), now the open gap.
- **Evaluation figures** (`rolling_evaluation.json`, `coverage_evaluation.json` at `17f5d82`): smallest adjusted q against drift 0.39 → 0.36; no-change wins after adjustment 3 of 64 → 1 of 64; UK CPI 90% band coverage 78% → 76% at one quarter, 54% → 56% at eight.
- **Shock reading, 2026Q2**: world supply "negative, 70%" → no call (55% positive); 430 of 6,000 draws accepted.
- **Band factors** follow the pin: eight of 32 moved, seven by one step of measured coverage (one origin in 50) and one by two (`forecasts/band_calibration.json`). Archived rounds are untouched.
- **Not changed**: the archived 12 Nov 2026 round shown as the current forecast (it predates #34), the working-paper PDF (the #24 vintage, now labelled) and the compare page.

### OBR page: fiscal rules view and conventions

- **Fiscal rules on `/obr`.** A new "Against the fiscal rules" section sets the October 2026 EFO path for the current budget (Table 6.5) and public sector net financial liabilities (derived from Table 6.14) beside what the model books for the four worked examples (`results/demo_shocks.json` at obr-macroeconomic-model `0e44ec8`). Only the spending example moves the public finances; the section says it is not a rule readout. No existing figure changes.
- **Conventions on `/obr/methodology`.** Step 2 gains a table of the OBR conventions the emulator inherits as EFO Table 1.9 input paths, imposes through an opt-in overlay, or does not reproduce.

### Bank of England gap explanation and one multiplier sign convention (#280)

- **`/models/compare`, 100bp question.** A new unfolded block lists why the two UK rows sit either side of the Bank of England's 1999 range: model, shock, horizon and monetary response, plus what narrows each gap. It is generated from a new optional `gaps` key in `results.json`. No figure in any row changed.
- **Multiplier sign convention.** Every multiplier takes the sign of the OBR's table (EFO July 2015, Box 3.2): GDP gained per unit spent, GDP lost per unit of tax raised, so the usual response is positive. The compare columns, `/obr` and `/obr/validation` now use that one wording ("GDP fall per £", "GDP moved per pound" and "ratio" are gone). No number changed sign: the wording was mixed, the values were already positive.
- **SVAR draws.** The 100bp row's description of the published replication run follows boe-var-model `17f5d82`: 765 accepted draws → 731, effective sample size 368.0 → 333.3 (`results/summary.md`). The row's medians are still the fast fixture's.
- **OBR benchmark source.** The spending and tax benchmarks name EFO July 2015 Box 3.2 as the source of 0.6 and 0.3, and note that the OBR's November 2023 article gives 0.45 for public services and 0.33 for tax (obr-macroeconomic-model `docs/published_model_review.md`, G11).

### Model re-pin and site review (#278, #279)

- **#278: model pins.** OBR `2965e82d` → `0e44ec87` (main after obr-macroeconomic-model #74 and #75), BoE SVAR `c13a9c91` → `c827ab86`, FRB/US `846eeb5c` → `162cfe6a`, US HANK `551a40d3` → `58353e5f`. After a redeploy the hosted tools run these pins. The FRB/US and US HANK compare rows with stored paths re-run identically; the OBR rows were re-run at `0e44ec8`.
- **#278: OBR figures at `0e44ec8`.** Anchored GDP MAPE 0.44% → 0.24% (consumption 0.72% → 0.40%); anchored unemployment now follows the EFO by construction (obr #74, the forecast population on the EFO path). Free-running real GDP error (not OBR forecast error) 4.25% → 4.24% (consumption 7.24 → 7.23, unemployment 1.17pp → 0.62pp, company profits 12.32 → 12.88), 9 of 11 lines in band; on the way, holding household taxes on their data path (obr #71) had moved GDP to 4.05%. Spending multiplier 1.01 → 1.04 by q12 (was 1.05), with borrowing now rising by the cash cost (obr #75); tax ratio at q12 0.38 → 0.37 in current prices. FRB/US against Laforte (2018) moves to the Board's own 2020Q1 design (unemployment +0.228pp against +0.219pp, 1.04×); its size-of-responses verdict is re-banded partial → pass on the model repository's ±10% gate. DEFINE-UK headline multiplier 2.30 → 2.25 (2027 policy start to 2040). US HANK: one published magnitude matched within about 2%.
- **#278: tool output.** `hank_shock` returns `i` (the nominal policy rate the Taylor rule sets) and `high_mpc_share`; `obr_shock` gains `price_passthrough` (default off) and a closure-aware capital-spending caveat. README counts 28 MCP tools.
- **#279: site review.** Accuracy, design and function fixes across every in-scope page at 1440, 820 and 375 wide, light and dark. `frbus_summary` quotes the October-vintage 100bp responses (−0.55% → −0.56%, +0.26pp → +0.28pp); the DEFINE-UK default horizon reads 2027–2040 (was 2023–2037). Home-page result chips use the dot-and-word chip style (no tick or warning icon).

### Site redesign stack (#200)

Bullets by PR, in merge order. Every PR listed here merged with #200 on 10 November 2026.

- **#200: site redesign.** Every page uses the Autumn Budget 2026 layout (header band, title band, sub-tabs, cards with expanders), with `DESIGN.md` as the spec. URLs, numbers and data are unchanged.
- **#204: question router on `/models` and a new `/glossary`.** Model cards filter by question and country; `/connect` gives copy-paste setup and `/contact` lists self-serve routes. No numbers changed.
- **#206: model pages.** One-column methodology, one overview order, and model names instead of ids.
- **#206: FRB/US comparators.** The worked-shock reference moves from the 2014 FEDS Note (gap −0.4pp, core PCE −0.08pp) to Laforte (2018) for the current model (gap −0.486pp, core PCE −0.0345pp, unemployment +0.219pp at q8); multiplier ranges move to CBO's converted ranges (for example Coenen 0.7–1.0 → CBO 0.45–1.82).
- **#205: forecast-evaluation scoreboard.** `/forecasts` leads with the record (band coverage, mean absolute error beside the no-change benchmark, forecasts scored), the archive is flat, and charts carry units and sources. `forecasts/scorecard.json` is unchanged.
- **#219: `/models/compare`.** One table per question (six questions × five models) with the exact call, a sourced benchmark and a verdict. The FRB/US benchmark is Laforte (2018) (band −0.53…−0.40 → −0.486…−0.459).
- **#216: integration-layer scenario sweep fixes.** `score_reform(model="obr")` places PolicyEngine-UK costings on fiscal-year quarters (default window `2026Q1..2030Q4` → `2026Q2..2031Q1`); `svar_forecast` returns simple y/y rates rather than log differences; `frbus_shock` reports rates as level deviations; `hank_shock` returns the `tax` series; invalid inputs (NaN sizes, unknown question types, out-of-window years) are refused before solving.
- **#226: hosted OBR pin** `1ed742c` → `e4d7faa` (obr-macroeconomic-model main). After a redeploy, hosted Bank Rate +100bp ΔGDP q4/q8/q12 moves −446/−525/−490 → −431/−482/−416 £m, matching the site, and the default `score_reform` cumulative ΔGDP for a basic-rate rise moves +£5.6bn → −£18.3bn.
- **#229: weekly drift check.** `integration/drift/canaries.json` compares one cheap hosted call per model with the number the site quotes for it and reports value, provenance and revision mismatches.
- **#231: BoE SVAR replication figures** are labelled with their run vintage (boe-var-model `845e2a4`) and their `results/` links are pinned to it. No number changes.
- **#232: BoE SVAR figures updated to the 2026Q2 data refresh** (boe-var-model #24, `d4ec3e7`): accepted draws 744 → 765, ESS 356.1 → 368.0, global FEVD share of UK GDP 37.4 → 38.7 and of UK CPI 42.3 → 41.5, rolling origins 49 → 50, smallest adjusted q 0.36 → 0.39 (published spec 0.40 → 0.42), fast-config GDP/CPI 42.0/37.6 → 40.1/40.1.

<!-- Site redesign stack (#200) entries go above this line; data pipeline (#221, #228) entries go below it. Keeping them apart lets both stacks merge in either order. -->

### Data pipeline (#221, #228)

- **#221: data pipeline.** A scheduled refresh now runs fetch, ingest, score and the CI gates in one driver (`data/refresh.py`) and updates one checked bot PR; the nowcast exits with an error when its calendar is stale instead of doing nothing.
- **#228: snapshot recovery tool.** `data/recover_orphaned_snapshots.py` recovers the 50 orphaned refresh snapshots with repeat days dropped; the refresh carry step also drops repeated releases. No file under `data/vintages/` is added by this change.

### Hosted tools

- **`hank_shock` and `hank_shock_incidence`: `persistence` is required for `fiscal_spending`.** It used to default to 0.9. The spending multiplier depends on it (impact multiplier 0.175 at 0.8, 0.075 at 0.9), so a call without it now fails with that explanation (decision on us-hank-model #5). Monetary and productivity shocks keep the 0.9 default.

## [0.2.0] — 2026-08-11

Access and verification release. Nothing about any model's behaviour or any
published number changed; this makes the data usable from outside the
repository and makes a class of silent regression fail loudly in CI.

### Added

- **A browsable data store at `/forecasts#data`.** The append-only point-in-time
  archive under `data/vintages/` had no route into it from the site at all. It
  now catalogues all 20 tracked ONS, Bank of England and FRED series with their
  vintages, and carries a runnable "as-of" recipe for reconstructing any series
  exactly as it was published on a given date — the reason the archive exists.
  It sits in the forecast record rather than on a page of its own, because
  reproducing a score against the data as it stood is what the store is for.
  Generated by `data/build_page.py`, which has a `--check` mode gated in CI.
- **A release calendar** at `/data/calendar.ics`, built from the `next_release`
  field already present in each snapshot. Ten ONS releases are announced; Bank
  of England and FRED series do not publish the field, and the page says so
  rather than implying nothing is scheduled.
- **CORS on `/data`.** `Access-Control-Allow-Origin: *` plus explicit methods,
  so browser-side notebooks and dashboards can consume the JSON directly.
  Previously this worked only incidentally, as a Vercel platform default.
- **Cache headers matched to mutability.** Vintage snapshots are immutable by
  construction and are now served `max-age=31536000, immutable`; `latest/`,
  `MANIFEST.json` and the calendar move, and get a short TTL with
  `stale-while-revalidate`.
- **A repo-root test suite** (`tests/`, stdlib-only, needs nothing but pytest):
  internal-link resolution across every HTML page honouring `cleanUrls` and the
  `vercel.json` redirect table, page metadata and canonical-path agreement,
  accessibility checks (alt text, single `h1`, no skipped heading levels,
  anchor targets resolve), sitemap coverage, data-store integrity (schema,
  chronology, `latest/` matching the newest vintage, manifest agreement), and
  repository hygiene.
- **`data-immutability.yml`** — CI enforcement that nothing under
  `data/vintages/` is ever modified or deleted, mirroring the existing
  guarantee for `forecasts/rounds/`. The archive's whole value is that a
  snapshot cannot be silently rewritten; that was previously convention.
- **`site-tests.yml`** — runs the repo-root suite on every pull request.
- **`publish-pypi.yml`** — publishes `policyengine-macro` to PyPI on GitHub
  release via Trusted Publishing (OIDC, no stored token). Lands **dormant**:
  a maintainer must configure the trusted publisher on pypi.org first.
- **Project governance files** — `CONTRIBUTING.md` (the generated-page,
  append-only and capability-registry rules that were previously tribal
  knowledge), `SECURITY.md` (including archive tampering as an explicitly
  in-scope report), `CITATION.cff`, and this changelog.
- **PyPI packaging metadata** in `integration/pyproject.toml` — readme,
  authors, keywords, classifiers and project URLs.

### Changed

- `integration/pyproject.toml` version `0.1.0` → `0.2.0`.
- The UK and US Economy pages link to the data store from their release tables.
- `site-provenance.yml` gains the `data/build_page.py --check` gate.

### Not included

- **A DOI.** `CITATION.cff` is ready for the identifier once the repository is
  connected to Zenodo and a release is minted.
- **A browser reform scorer.** Running any model still requires a terminal —
  the CLI, the MCP server, or the Python API. Putting a scoring form on the
  site needs a REST shim on the Modal app, CORS there, and a CSP change, and is
  tracked separately.

## [0.1.0]

Initial integration layer: the `pe-macro` CLI and the MCP server over the OBR
macroeconometric emulator, the Bank of England structural VAR, FRB/US, US HANK,
OG-UK and the PolicyEngine microsimulation, with the hosted server
auto-deployed to Modal by CI.
