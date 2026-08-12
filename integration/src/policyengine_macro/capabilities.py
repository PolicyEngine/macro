"""Authoritative capability registry for routing and status surfaces.

This deliberately records capabilities, not model-level marketing badges. A
model can be production-ready for one use and inappropriate for another.
"""

from __future__ import annotations

from copy import deepcopy


MODELS = {
    "pe-microsim": {
        "display_name": "PolicyEngine tax-benefit microsimulation",
        "model_class": "microsimulation",
        "geography": ["uk", "us"],
        "question_types": ["household", "population", "policy_reform"],
        "inputs": ["household data", "population data", "parameter reform"],
        "outputs": ["taxes", "benefits", "net_income", "revenue", "distribution"],
        "cannot_answer": ["GDP", "inflation", "interest rates", "macro feedback"],
        "horizon": "single policy year",
        "access": ["hosted", "CLI", "Python"],
        "runtime": "sub-second household; minutes population",
        "uncertainty": "none for household arithmetic; survey/calibration uncertainty for population estimates",
        "status": "production-ready for selected household applications",
        "data_vintage": "country package and dataset dependent; recorded per run",
    },
    "og+microsim": {
        "site_id": "psl-og+microsim",
        "display_name": "OG-UK overlay dynamic scoring (og+microsim)",
        "model_class": "olg-ge overlay on microsimulation",
        "geography": ["uk"],
        "question_types": ["dynamic_scoring", "policy_reform"],
        "inputs": ["parameter reform", "optional pre-computed OG payload"],
        "outputs": ["revenue (dynamic)", "distribution", "distribution under GE feedback"],
        "cannot_answer": [
            "transition paths (steady-state factor applied flat)",
            "price-level effects (the OG model is real)",
            "distributional incidence of effective-labour changes (reported, not allocated)",
        ],
        "horizon": "one policy year under long-run steady-state assumptions",
        "access": ["CLI", "Python"],
        "runtime": "two OG steady-state solves (baseline cached; >10 min cold) + one microsim run",
        "uncertainty": "none quantified; steady-state comparative statics",
        "status": (
            "experimental; local-only (oguk excluded from the hosted image), "
            "and until PSLmodels/OG-UK#68 the OG solve needs its own "
            "environment — use the two-step --og-payload pipeline"
        ),
        "data_vintage": "PolicyEngine dataset + OG-UK packaged calibration inputs",
    },
    "obr-macro": {
        "display_name": "OBR macroeconometric emulator",
        "model_class": "macroeconometric",
        "geography": ["uk"],
        "question_types": ["economic_shock", "translated_policy_scenario"],
        "inputs": ["curated model-variable shock", "reviewed reform translation"],
        "outputs": ["gdp", "consumption", "investment"],
        "cannot_answer": ["arbitrary statutory reform incidence", "borrowing through the current adapter"],
        "horizon": "quarterly, typically 3-5 years",
        "access": ["hosted", "CLI", "Python"],
        "runtime": "seconds for raw shocks; minutes for translated reform scenarios",
        "uncertainty": "not comprehensive",
        "status": "validated for selected scenarios",
        "data_vintage": "March 2026 EFO baseline",
    },
    "boe-svar": {
        "display_name": "Bank of England structural VAR replication",
        "model_class": "structural VAR",
        "geography": ["uk"],
        "question_types": ["forecast", "economic_diagnosis"],
        "inputs": ["packaged quarterly macroeconomic data"],
        "outputs": ["GDP forecast", "inflation forecast", "identified shocks", "uncertainty ranges"],
        "cannot_answer": ["statutory policy reform effects"],
        "horizon": "quarterly short-run forecast",
        "access": ["hosted forecast and latest shocks", "CLI", "Python package for wider analysis"],
        "runtime": "minutes per estimation and identification run",
        "uncertainty": "posterior 68% and 90% intervals",
        "status": "validated replication for selected outputs",
        "estimation_sample": "1992Q1-2025Q1",
        "data_edge": "2026Q1",
        "data_vintage": "2026Q1 conditioning data; estimation ends 2025Q1",
    },
    "frb-us": {
        "display_name": "Federal Reserve FRB-US implementation",
        "model_class": "macroeconometric",
        "geography": ["us"],
        "question_types": ["economic_shock"],
        "inputs": ["reviewed FRB-US add-factor shock"],
        "outputs": ["GDP", "unemployment", "inflation", "prices", "federal funds rate"],
        "cannot_answer": ["PolicyEngine reforms", "model-consistent-expectations scenarios"],
        "horizon": "quarterly",
        "access": ["hosted raw shocks", "CLI with editable model checkout", "Python"],
        "runtime": "seconds to minutes",
        "uncertainty": "not comprehensive",
        "status": "validated software replication with scope limits",
        "data_vintage": "LONGBASE file from the installed frbus package",
    },
    "us-hank": {
        "display_name": "US two-asset HANK (Auclert-Bardóczy-Rognlie-Straub 2021)",
        "model_class": "heterogeneous-agent New Keynesian (sequence-space)",
        "geography": ["us"],
        "question_types": ["economic_shock"],
        "inputs": ["stylized shock (kind, size, persistence)"],
        "outputs": ["gdp", "consumption", "investment", "inflation", "real_rate"],
        "cannot_answer": [
            "forecasts (IRFs around a calibrated steady state, not a forecaster)",
            "detailed tax reforms (only monetary/fiscal-spending/productivity instruments; the labor tax is endogenous)",
            "PolicyEngine reforms",
            "nonlinear or state-dependent dynamics (responses are first-order)",
        ],
        "horizon": "quarterly impulse responses, typically 5 years",
        "access": ["hosted stylized shocks", "CLI", "Python"],
        "runtime": "~18s cold per variant (steady state + jacobian, cached); instant warm",
        "uncertainty": "none quantified; deterministic linear IRFs",
        "status": (
            "validated replication for hosted stylized-shock experiments; "
            "VAR-free sequence-space HANK; not a forecaster; distributional "
            "outputs are first-order approximations"
        ),
        "data_vintage": "Auclert-Bardóczy-Rognlie-Straub (2021) calibration",
    },
    "og-uk": {
        # The website calls this model psl-og — the PSL brand, which is what
        # every model page, the papers directory and site_contract.PUBLIC_MODELS
        # use. The registry key stays og-uk because it is the public
        # MCP/CLI contract (score["model"], `--model og`) and is asserted in
        # the integration tests. Anything rendering a model name for a reader
        # must use site_id, or the site ends up calling one model four things.
        "site_id": "psl-og",
        "display_name": "OG-UK overlapping generations model",
        "model_class": "overlapping-generations general equilibrium",
        "geography": ["uk"],
        "question_types": ["policy_reform", "structural_change"],
        "inputs": ["PolicyEngine parameter reform", "calibration parameters"],
        "outputs": ["GDP", "work", "saving", "capital", "wages", "interest rates", "debt"],
        "cannot_answer": ["short-run forecast", "fast hosted custom scenario"],
        "horizon": "long-run steady state; package also supports transition paths",
        "access": ["local CLI steady state", "Python package"],
        "runtime": "17+ minutes per steady-state solve; transition paths can take hours",
        "uncertainty": "sensitivity analysis not yet comprehensive",
        "status": "research prototype; calibrated counterfactual",
        "data_vintage": "OG-UK packaged calibration inputs",
    },
    "define-uk": {
        "display_name": "DEFINE-UK ecological stock-flow consistent model",
        "model_class": "ecological stock-flow consistent (E-SFC)",
        "geography": ["uk"],
        "question_types": ["climate_policy_scenario"],
        "inputs": ["curated scenario name from the upstream scenario set"],
        "outputs": ["scenario deltas vs baseline: real GDP, emissions, unemployment, real consumption"],
        "cannot_answer": [
            "reform scoring (no statute mapping; score_reform refuses it)",
            "forecasts or baseline levels (deltas only — the baseline is not validated against outturns)",
        ],
        "horizon": "annual scenario deltas, 2023-2037",
        "access": [
            "local CLI scenarios", "Python package",
            "microsim incidence overlay (define_scenario_incidence, "
            "experimental; hosted with a define_payload of locally "
            "produced deltas)",
        ],
        "runtime": "instant from the cached upstream run; a fresh run needs local R (full notebook)",
        "uncertainty": "none quantified; deterministic scenario deltas from one calibration",
        "status": (
            "experimental; partial replication — baseline macro block "
            "replicates manual Table 4; scenario deltas gated on the pinned "
            "oracle run, the published scenario definitions, and two paper "
            "anchors (no numeric v1.1 scenario results are published); "
            "unlicensed upstream is never hosted, so hosted calls return "
            "run instructions"
        ),
        "data_vintage": "DEFINE-UK 1.1 upstream at pinned commit 846081a (April 2026 manual)",
    },
}

# Evidence is deliberately split into dimensions. A model can reproduce its
# reference software perfectly while still having limited independent evidence
# for forecasts or policy counterfactuals. These are categorical audit
# judgements, not a synthetic score that invites false precision.
QUALITY_LEVELS = {"strong", "moderate", "weak", "not_assessed", "not_applicable"}
QUALITY_DIMENSIONS = {
    "implementation_fidelity",
    "predictive_validation",
    "identification_robustness",
    "policy_counterfactual_validity",
    "uncertainty_calibration",
    "vintage_reproducibility",
}


def _quality(level: str, evidence: str, next_gate: str) -> dict:
    return {"level": level, "evidence": evidence, "next_gate": next_gate}


MODEL_QUALITY = {
    "obr-macro": {
        "implementation_fidelity": _quality(
            "moderate",
            "Anchored GDP/consumption reproduce the March 2026 EFO within 1%, "
            "but passthrough and inactive equations limit equation coverage.",
            "Exercise every published behavioural equation and eliminate or "
            "explicitly scope every inactive channel.",
        ),
        "predictive_validation": _quality(
            "weak",
            "Free-running GDP and consumption MAPE are 4.48% and 7.49%; the "
            "anchored fit is by construction.",
            "Pass rolling-origin historical-vintage tests against simple "
            "benchmarks and first-release outturns.",
        ),
        "identification_robustness": _quality(
            "not_applicable",
            "The model is an equation-based emulator rather than an identified "
            "structural-shock model.",
            "Keep this dimension explicitly not applicable.",
        ),
        "policy_counterfactual_validity": _quality(
            "weak",
            "One income-tax costing is independently compared with HMRC; trade, "
            "labour, prices and parts of household income remain constrained.",
            "Validate a frozen suite of fiscal shocks against independent "
            "official costings and published multiplier ranges.",
        ),
        "uncertainty_calibration": _quality(
            "weak",
            "Results are point scenarios without comprehensive uncertainty over "
            "add factors, closures or missing-input proxies.",
            "Publish sensitivity envelopes for judgement, closure and bridge "
            "assumptions.",
        ),
        "vintage_reproducibility": _quality(
            "moderate",
            "The live March 2026 baseline and November 2025 paper vintage are "
            "labelled, but a multi-vintage archive is not yet a test fixture.",
            "Archive source hashes and reproduce at least three historical EFO "
            "vintages end to end.",
        ),
    },
    "boe-svar": {
        "implementation_fidelity": _quality(
            "strong",
            "Zero/sign restrictions and decomposition identities are tested on "
            "real data to numerical precision.",
            "Keep all exact invariants hard-gated for every specification.",
        ),
        "predictive_validation": _quality(
            "weak",
            "No demonstrated skill against a random walk WITH DRIFT on any "
            "variable at any horizon once the 64 variable-by-horizon tests "
            "are adjusted together: minimum Benjamini-Hochberg q = 0.36, and "
            "0.40 under the published specification. A driftless walk on a "
            "trending log level is too weak a benchmark, so the strong-looking "
            "CPI result (0.63 at h=1) becomes 0.83 at h=1 and 1.03 at h=8 "
            "against drift. Bank Rate comes closest (0.79 at h=1, unadjusted "
            "p=0.018 -- the smallest of the 64) but does not survive the "
            "adjustment. UK GDP is not distinguishable from drift at any "
            "horizon (p=0.33-0.43). Two caveats on figures quoted elsewhere: "
            "the ex-Covid ratio of 0.77 and the p=0.38-0.67 range are against "
            "the weaker no-change benchmark, not drift. Separately, the "
            "rolling evaluation had estimated without the six Covid dummies "
            "that every published forecast carries; under the published "
            "specification UK GDP goes 1.06 to 0.99 at h=1 and 1.12 to 0.95 "
            "at h=8 -- level with naive rather than worse, still not better. "
            "The frozen-edge run gives 0.32pp RMSE from a single origin.",
            "Score the predictive densities rather than point forecasts, "
            "report rolling interval coverage, and re-run once the estimation "
            "sample extends past the Covid dummies.",
        ),
        "identification_robustness": _quality(
            "moderate",
            "On the paper's own definition -- the posterior mean of the "
            "per-draw group share of TOTAL forecast-error variance, four "
            "quarters ahead -- UK GDP replicates (37.4% against ~40%) and UK "
            "CPI falls about 8pp short (42.3% against ~50%). The earlier "
            "match on both came from summing per-shock medians and "
            "renormalising them to 100%, which inflated the identified shares "
            "by about a third. The 68% posterior band is roughly +/-14pp, "
            "wider than the shortfall, and proxy world data and undisclosed "
            "source settings matter.",
            "Show conclusions across lag, prior, proxy-data and weighting grids "
            "with effective-sample-size diagnostics.",
        ),
        "policy_counterfactual_validity": _quality(
            "not_applicable",
            "The model diagnoses shocks and forecasts; it does not score statutory "
            "policy reforms.",
            "Continue to refuse reform-scoring requests.",
        ),
        "uncertainty_calibration": _quality(
            "moderate",
            "Posterior 68% and 90% intervals are produced, but empirical coverage "
            "has been checked over only seven forecast quarters.",
            "Report rolling empirical coverage and proper predictive scores.",
        ),
        "vintage_reproducibility": _quality(
            "moderate",
            "The estimation sample and conditioning edge are recorded, while key "
            "internal Bank world aggregates require public proxies.",
            "Freeze input manifests and retain both real-time and revised vintages.",
        ),
    },
    "frb-us": {
        "implementation_fidelity": _quality(
            "strong",
            "The baseline and four like-for-like scenarios (monetary, fiscal "
            "egfe, tax trp, non-inertial Taylor) match LONGBASE and pyfrbus at "
            "the reference solver's numerical noise floor.",
            "Extend like-for-like gates across further official demos, closures "
            "and recodes; add the MCE expectations path.",
        ),
        "predictive_validation": _quality(
            "not_assessed",
            "LONGBASE is an illustrative tracking baseline, not an official Fed "
            "forecast, and no historical forecast evaluation is published here.",
            "Run vintage-preserving pseudo-out-of-sample forecast evaluation.",
        ),
        "identification_robustness": _quality(
            "not_applicable",
            "FRB/US is a large behavioural equation model, not a structural VAR "
            "identified by sign or zero restrictions.",
            "Keep this dimension explicitly not applicable.",
        ),
        "policy_counterfactual_validity": _quality(
            "moderate",
            "Selected monetary and fiscal multipliers lie in published ranges, but "
            "only VAR expectations are supported.",
            "Implement and cross-validate model-consistent expectations before "
            "forward-guidance or permanent-policy use.",
        ),
        "uncertainty_calibration": _quality(
            "weak",
            "A seeded joint historical-residual bootstrap now exists upstream, but "
            "the public run surface and published experiments remain deterministic.",
            "Review residual windows and closures, expose the stochastic surface, "
            "and publish coverage and convergence diagnostics.",
        ),
        "vintage_reproducibility": _quality(
            "moderate",
            "Model and LONGBASE archives are independently SHA-256 gated because "
            "the Board updates their pages and artifacts on separate schedules.",
            "Retain and test multiple historical model/data artifact pairs.",
        ),
    },
    "us-hank": {
        "implementation_fidelity": _quality(
            "strong",
            "Built directly on the authors' sequence-jacobian toolkit at the "
            "paper's production grids; the model repo's replication suite gates "
            "steady-state targets, market clearing, and shock responses "
            "against the published Econometrica 2021 results.",
            "Keep the replication gates hard-failing and extend them across "
            "all three shock kinds and both variants.",
        ),
        "predictive_validation": _quality(
            "not_applicable",
            "The model produces impulse responses around a calibrated steady "
            "state; it is not a forecaster and makes no predictive claims.",
            "Keep this dimension explicitly not applicable and continue to "
            "refuse forecast framing.",
        ),
        "identification_robustness": _quality(
            "not_applicable",
            "A calibrated structural model, not a VAR identified by sign or "
            "zero restrictions.",
            "Keep this dimension explicitly not applicable.",
        ),
        "policy_counterfactual_validity": _quality(
            "weak",
            "Stylized monetary/fiscal-spending/productivity shocks only; the "
            "labor tax is endogenous, so no detailed tax-reform "
            "counterfactuals exist, and responses are first-order.",
            "Validate the fiscal-spending multiplier and monetary responses "
            "against published HANK estimates before broader policy use.",
        ),
        "uncertainty_calibration": _quality(
            "weak",
            "Deterministic linear IRFs with no parameter or shock "
            "uncertainty; distributional outputs are first-order "
            "approximations from steady-state policies.",
            "Publish sensitivity of headline IRFs to key calibration "
            "parameters (sticky-price/wage slopes, MPC targets).",
        ),
        "vintage_reproducibility": _quality(
            "strong",
            "No data vintages: the calibration is the published paper's and "
            "is pinned in the package, so identical versions reproduce "
            "identical numbers exactly.",
            "Record the package version in every result (done via "
            "provenance) and keep the calibration frozen unless deliberately "
            "revised.",
        ),
    },
    "pe-microsim": {
        "implementation_fidelity": _quality(
            "strong",
            "Statutory rules are implemented and tested rule-by-rule in the "
            "policyengine-uk and policyengine-us packages, and a household "
            "result is exact arithmetic over those rules — no sampling, no "
            "weights, no estimated coefficients. A single case is hand-"
            "checkable end to end: £50,000 employment income gives a £12,570 "
            "personal allowance, £37,430 taxed at 20% = £7,486, NI at 8% = "
            "£2,994, net £39,520.",
            "Publish per-country statutory test coverage, so 'tested against "
            "statute' is a measured share rather than a description.",
        ),
        "predictive_validation": _quality(
            "not_applicable",
            "The model does not forecast. It evaluates statute on a given "
            "population for a given year, so there is no out-of-sample error "
            "to report and a forecast-skill score would be a category error.",
            "None. This dimension stays not_applicable by construction.",
        ),
        "identification_robustness": _quality(
            "not_applicable",
            "No structural shocks are identified; the model is an accounting "
            "evaluation of legislation, not an econometric identification.",
            "None.",
        ),
        "policy_counterfactual_validity": _quality(
            "moderate",
            "The static costing of a 1p basic-rate rise gives £6.46bn in 2026 "
            "rising to £7.38bn by 2030, against HMRC's published ready "
            "reckoner at £6.9bn and £8.2bn — within range, and the gap is "
            "reported rather than tuned away. That is one reform, one "
            "country, one tax, against another estimate on a different data "
            "basis, so it is a benchmark and not a validation.",
            "Benchmark a US reform and a distributional result against an "
            "independent published costing.",
        ),
        "uncertainty_calibration": _quality(
            "weak",
            "The distinction is the model's central one and is stated "
            "honestly: household arithmetic carries no error distribution, "
            "while a population estimate is a weighted sum whose uncertainty "
            "sits entirely in the survey weights and imputed microdata. But "
            "that population uncertainty is never quantified — ScoreQuantity "
            "records 'not estimated in this result' — so a revenue total is "
            "published as a point with no interval.",
            "Produce replicate-weight or bootstrap intervals for population "
            "aggregates, so a costing carries a range.",
        ),
        "vintage_reproducibility": _quality(
            "moderate",
            "Household results reproduce for anyone from the pinned country "
            "packages. Population runs need the enhanced-FRS microdata, which "
            "is gated behind a HuggingFace token, so an outside reader cannot "
            "reproduce a revenue total independently. Every result records "
            "its dataset and package versions in provenance.",
            "Publish a reproducibility path for population aggregates that "
            "does not require gated microdata access.",
        ),
    },
    "og-uk": {
        "implementation_fidelity": _quality(
            "moderate",
            "Built on PSL's OG-Core, whose solver and household problem are "
            "maintained and tested upstream; the UK calibration is this "
            "project's. No independent check of the UK parameterisation "
            "against an outside implementation exists.",
            "Cross-check the UK calibration against an independent OLG "
            "implementation or the OG-Core reference results.",
        ),
        "predictive_validation": _quality(
            "not_applicable",
            "A long-run steady-state comparative static, not a forecast. "
            "cannot_answer names short-run forecasting explicitly.",
            "None.",
        ),
        "identification_robustness": _quality(
            "not_applicable",
            "No shocks are identified; behaviour comes from the calibrated "
            "lifecycle structure.",
            "None.",
        ),
        "policy_counterfactual_validity": _quality(
            "weak",
            "This is the model's defining limitation and the site says so: "
            "targets are met by construction and no independent outcome "
            "benchmark exists. A reform score is internally consistent with "
            "the calibration and cannot be checked against anything outside "
            "it.",
            "Identify any published OLG reform result for the UK to score "
            "against, or state permanently that none exists.",
        ),
        "uncertainty_calibration": _quality(
            "weak",
            "No interval is produced and sensitivity analysis is not "
            "comprehensive, so a steady-state result is a single number "
            "conditional on one parameterisation.",
            "Run and publish a sensitivity sweep over the elasticities the "
            "result is most exposed to.",
        ),
        "vintage_reproducibility": _quality(
            "weak",
            "Local-only: excluded from the hosted image because one steady-"
            "state solve exceeds the request timeout. Reproduction needs the "
            "gated enhanced-FRS microdata plus UN demographics fetched at "
            "runtime, and the baseline cache is in-process only, so nothing "
            "persists between runs.",
            "Cache the demographic and microdata inputs so a solve is "
            "reproducible from committed artifacts.",
        ),
    },
    "og+microsim": {
        "implementation_fidelity": _quality(
            "moderate",
            "The overlay itself is small and tested — a steady-state factor "
            "applied to a microsimulation run, with the ratio-not-level "
            "invariant and bounds enforced. Its fidelity is bounded by "
            "og-uk's, since the factor comes from there.",
            "Inherit og-uk's calibration cross-check.",
        ),
        "predictive_validation": _quality(
            "not_applicable",
            "Not a forecast: one policy year under long-run steady-state "
            "assumptions.",
            "None.",
        ),
        "identification_robustness": _quality(
            "not_applicable",
            "No identification step.",
            "None.",
        ),
        "policy_counterfactual_validity": _quality(
            "weak",
            "Inherits og-uk's no-ground-truth problem and adds an "
            "approximation of its own: the steady-state factor is applied "
            "flat, so no transition path is represented, and the "
            "distributional incidence of effective-labour changes is reported "
            "rather than allocated.",
            "Score the overlay against a transition-path run to measure what "
            "the flat factor costs.",
        ),
        "uncertainty_calibration": _quality(
            "weak",
            "No interval on either leg: the OG factor is a point comparative "
            "static and the microsimulation aggregate carries unquantified "
            "survey uncertainty.",
            "Quantify the microsimulation leg first; the OG leg needs a "
            "sensitivity sweep.",
        ),
        "vintage_reproducibility": _quality(
            "weak",
            "Local-only and two-step: it needs an og-uk solve in its own "
            "environment and a --og-payload handoff, so a single command does "
            "not reproduce a result.",
            "Single-command reproduction once the OG environment constraint "
            "is resolved upstream.",
        ),
    },
    "define-uk": {
        "implementation_fidelity": _quality(
            "moderate",
            "The upstream R code runs unmodified at pinned commit 846081a and "
            "the manual's Table 4 macro block replicates within stated "
            "tolerances. The clean-room Python reimplementation has landed "
            "§2.2 accounting and §3.2, §3.3.1 and §3.3.2 — 118 equations, "
            "Eqs. (21)-(138) contiguous — and surfaced some thirty-five "
            "defects in the manual itself, each pinned by a test rather than "
            "absorbed into a tolerance.",
            "Complete §3.3 and the oracle comparison, closing milestone 2.",
        ),
        "predictive_validation": _quality(
            "not_applicable",
            "Explicitly not a forecaster: cannot_answer names forecasts and "
            "baseline levels, and the manual itself says the baseline should "
            "not be seen as a prediction.",
            "None.",
        ),
        "identification_robustness": _quality(
            "not_applicable",
            "Scenario deltas from a deterministic stock-flow consistent "
            "system; nothing is identified statistically.",
            "None.",
        ),
        "policy_counterfactual_validity": _quality(
            "weak",
            "No numeric v1.1 scenario results are published anywhere, so a "
            "published-figure replication is impossible — the ceiling, not an "
            "omission. What is checkable is checked: every scenario toggles "
            "exactly its published policy switches, and two coarse anchors "
            "from the open 2023 vintage hold.",
            "Reopens if the authors publish scenario tables or the paper "
            "becomes accessible.",
        ),
        "uncertainty_calibration": _quality(
            "weak",
            "Deterministic deltas from one calibration, with no interval and "
            "no sensitivity sweep.",
            "Sweep the parameters the scenario deltas are most exposed to.",
        ),
        "vintage_reproducibility": _quality(
            "weak",
            "The baseline sits far from outturns — 2025 growth 4.66% against "
            "an ONS 1.31%, 2024 emissions 401.5 against 371 MtCO2e — which is "
            "why deltas are served and never levels. Reproduction needs local "
            "R and the unlicensed upstream fetched at a pinned commit, so "
            "nothing is hosted and the comparison table is recomputed and "
            "regression-tested rather than asserted.",
            "The clean-room reimplementation removes the R and licensing "
            "dependency entirely.",
        ),
    },
}

for _model_id, _model in MODELS.items():
    _model["quality"] = deepcopy(MODEL_QUALITY.get(_model_id, {
        dimension: _quality(
            "not_assessed",
            "No evidence review has been completed for this model yet.",
            "Complete a model-specific evidence review before assigning a level.",
        )
        for dimension in QUALITY_DIMENSIONS
    }))

REQUIRED_CAPABILITY_FIELDS = {
    "display_name", "model_class", "geography", "question_types", "inputs",
    "outputs", "cannot_answer", "horizon", "access", "runtime", "uncertainty",
    "status", "data_vintage", "quality",
}


def validate_registry(registry: dict | None = None) -> None:
    """Fail fast when a model bypasses the public capability contract."""
    registry = MODELS if registry is None else registry
    for model_id, model in registry.items():
        missing = REQUIRED_CAPABILITY_FIELDS - set(model)
        if missing:
            raise ValueError(f"{model_id} missing capability fields: {sorted(missing)}")
        for field in (
            "geography", "question_types", "inputs", "outputs", "cannot_answer", "access"
        ):
            if not isinstance(model[field], list) or not model[field]:
                raise ValueError(f"{model_id}.{field} must be a non-empty list")
        quality = model["quality"]
        if set(quality) != QUALITY_DIMENSIONS:
            raise ValueError(
                f"{model_id}.quality must contain exactly "
                f"{sorted(QUALITY_DIMENSIONS)}"
            )
        for dimension, assessment in quality.items():
            if assessment.get("level") not in QUALITY_LEVELS:
                raise ValueError(
                    f"{model_id}.quality.{dimension}.level must be one of "
                    f"{sorted(QUALITY_LEVELS)}"
                )
            for field in ("evidence", "next_gate"):
                if not assessment.get(field):
                    raise ValueError(
                        f"{model_id}.quality.{dimension}.{field} is required"
                    )


validate_registry()


def list_capabilities() -> list[dict]:
    return [{"model_id": model_id, **deepcopy(data)} for model_id, data in MODELS.items()]


# Public site names that are not registry keys. site_id exists so pages render
# one name per model; without the reverse mapping the alias was one-directional
# — every page said psl-og and get_status("psl-og") raised, so a reader taking
# the documented name into the documented API hit a hard error whose message
# did not connect the two.
SITE_ID_TO_KEY = {
    model["site_id"]: key for key, model in MODELS.items() if model.get("site_id")
}


def resolve_model_id(model_id: str) -> str:
    """Registry key for a registry key or a public site name."""
    return SITE_ID_TO_KEY.get(model_id, model_id)


def get_status(model_id: str) -> dict:
    key = resolve_model_id(model_id)
    if key not in MODELS:
        known = sorted(set(MODELS) | set(SITE_ID_TO_KEY))
        raise ValueError(f"unknown model_id {model_id!r}; choose one of {known}")
    # Echo the key, so a caller who passed a site name learns the contract id.
    return {"model_id": key, **deepcopy(MODELS[key])}


def recommend(
    question_type: str,
    country: str = "uk",
    needs_distribution: bool = False,
    horizon: str | None = None,
) -> dict:
    """Deterministic router; it never invents an unsupported model mapping."""
    country = country.lower()
    candidates = []
    for model_id, model in MODELS.items():
        if country not in model["geography"]:
            continue
        if question_type not in model["question_types"]:
            continue
        if needs_distribution and model_id not in ("pe-microsim", "og+microsim"):
            continue
        candidates.append(model_id)
    return {
        "question_type": question_type,
        "country": country,
        "needs_distribution": needs_distribution,
        "horizon": horizon,
        "primary_model": candidates[0] if candidates else None,
        "candidate_models": candidates,
        "warning": None if candidates else (
            "No registered model supports this request. Do not infer a mapping; "
            "refine the question or add an explicitly reviewed capability."
        ),
        "details": [get_status(model_id) for model_id in candidates],
    }
