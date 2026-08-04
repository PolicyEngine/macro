"""PolicyEngine Macro MCP server (stdio transport).

Run with:  python -m policyengine_macro.mcp_server

Exposes the same adapter functions as the `pe-macro` CLI as MCP tools.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from policyengine_macro import core
from policyengine_macro import capabilities
from policyengine_macro import reporting

mcp = FastMCP("policyengine-macro")


@mcp.tool()
def list_model_capabilities() -> list[dict]:
    """List supported questions, outputs, access, runtime, evidence status,
    and explicit non-capabilities for every model."""
    return capabilities.list_capabilities()


@mcp.tool()
def get_model_status(model_id: str) -> dict:
    """Return the capability and operational status for one model id."""
    return capabilities.get_status(model_id)


@mcp.tool()
def recommend_model(
    question_type: str,
    country: str = "uk",
    needs_distribution: bool = False,
    horizon: str | None = None,
) -> dict:
    """Deterministically recommend only models registered for a question.

    question_type must be one of household, population, policy_reform,
    dynamic_scoring, economic_shock, translated_policy_scenario, forecast,
    economic_diagnosis, or structural_change. Unsupported combinations return
    no model rather than an invented mapping.
    """
    return capabilities.recommend(
        question_type=question_type,
        country=country,
        needs_distribution=needs_distribution,
        horizon=horizon,
    )


@mcp.tool()
def format_score_report(score: dict, output_format: str = "json") -> dict | str:
    """Convert a common ScoreResult into a stable report envelope or Markdown.

    The report preserves quantities and units, time basis, uncertainty,
    assumptions, limitations, model/package versions, data and baseline
    vintages, run time, validation evidence, warnings, and reproduction
    instructions. ``output_format`` must be ``json`` or ``markdown``.
    """
    if output_format == "json":
        return reporting.build_report(score)
    if output_format == "markdown":
        return reporting.render_markdown(score)
    raise ValueError("output_format must be 'json' or 'markdown'")


@mcp.tool()
def score_reform(
    country: str | None = None,
    reform: dict | None = None,
    model: str | None = None,
    start_year: int = 2026,
    max_iter: int = 250,
    years: int = 5,
    dataset: str | None = None,
) -> dict:
    """Score a tax/benefit reform with one of the suite's scoring models, using
    the SAME PolicyEngine reform dict as the microsimulation tools. Every
    result carries a common `score` block (ScoreResult: model class, horizon,
    provenance, per-quantity units/time basis, assumptions, caveats, and a
    comparability label). Cross-class results are often complementary rather
    than like-for-like and must not be averaged or ranked.

    Args:
        country: 'uk' (macro members are UK models; 'us' works for microsim).
        reform: Flat {parameter_path: value} dict — the same shape as
            population_reform_impact / household_reform_impact, e.g.
            {"gov.hmrc.income_tax.rates.uk[0].rate": 0.21}. A value may
            also be a {effective_date: value} dict, e.g.
            {"gov.hmrc.income_tax.rates.uk[0].rate": {"2026-01-01": 0.21}}.
            Dates are single YYYY-MM-DD effective dates; date RANGES
            ("2026-01-01.2029-12-31") are not supported, because a
            PolicyEngine reform value applies from its effective date with
            no expiry. Call list_reform_parameters for verified paths.
        model: Which model consumes the reform, via its contract:
            'og'  — OG-UK overlapping-generations model: long-run steady-state
                    general-equilibrium comparison; the reform enters through
                    PolicyEngine-estimated tax functions. VERY SLOW (tens of
                    minutes) and excluded from the hosted server — run it
                    locally via `pe-macro score --model og`; calling it here
                    returns install/CLI instructions.
            'obr' — OBR macroeconometric emulator via the microsim
                    static-costing bridge: the reform is costed per year with
                    the PolicyEngine population microsimulation, the annual
                    budgetary impacts enter the emulator as a quarterly
                    HHDI_ADDFACTOR costing path (positive revenue is converted
                    to a negative held household-income add-factor), and the
                    second-round demand effects on GDP/consumption/investment
                    come out. Demand-side incidence only; corporation-tax
                    reforms are refused (use obr_shock var='TCPRO'). Takes a
                    few minutes (one microsim run per year + two OBR solves).
            'microsim' — the PolicyEngine population costing itself (static,
                    no macro feedback), wrapped in the same ScoreResult.
            'og+microsim' — dynamic scoring: the OG-UK long-run wage change
                    becomes an earnings overlay on the reform simulation
                    (see dynamic_reform_impact for details and the
                    local-only caveat). UK only.
            'frbus' — NOT ACCEPTED, and deliberately so: it raises an error.
                    FRB/US has no PolicyEngine-reform bridge, because no
                    mapping exists today from a PolicyEngine US reform to
                    FRB/US fiscal levers and inventing one would return
                    plausible-looking wrong numbers. For FRB/US, use the
                    frbus_shock tool with raw variable shocks in model units
                    (frbus_list_variables lists the levers).
            'hank' — NOT ACCEPTED, likewise: the US HANK member scores
                    stylized shocks, not detailed tax reforms, and its labor
                    tax is endogenous, so no reform mapping exists. Use the
                    hank_shock tool instead.
        start_year: Reform start year (default 2026).
        max_iter: og only — steady-state solver iteration cap (default 250).
        years: obr only — costing window length in years (default 5).
        dataset: obr/microsim only — microdata dataset name override.

    For population-level budget/distributional impacts WITHOUT macro feedback,
    population_reform_impact is the direct (equivalent, faster) tool.
    """
    return core.score_reform(
        country=country, reform=reform, model=model, start_year=start_year,
        max_iter=max_iter, years=years, dataset=dataset,
    )


@mcp.tool()
def obr_shock(
    var: str,
    shock: float,
    periods: Annotated[int, Field(ge=1, le=40)] = 12,
    name: str | None = None,
    investment_closure: bool | None = None,
) -> dict:
    """Shock one OBR model variable directly, in model units (the escape
    hatch under score_reform — no PolicyEngine reform translation).

    Runs a baseline and a shocked solve of the OBR model and returns per-quarter
    GDP deltas plus a headline cumulative GDP effect.

    Args:
        var: Policy variable to shock. Common choices (see list_reform_variables):
            CGG (real government consumption), TCPRO (corporation tax main rate),
            CGIPS (nominal central government investment).
        shock: Shock size, applied each quarter. UNITS DEPEND ON THE VARIABLE:
            CGG and CGIPS are in £ million per quarter (e.g. 1250 = £5bn/year);
            TCPRO is a rate change in decimal (e.g. -0.05 = 5 percentage point cut).
        periods: Number of quarters the shock is applied (1-40; default 12 =
            3 years).
        name: Optional label for the reform.
        investment_closure: Omit to use the safe per-variable default (True
            for TCPRO, False otherwise). It activates the cost-of-capital
            investment channel; a TCPRO shock without it solves to misleading
            all-zero deltas, which is why the default is per-variable.

    Returns per-period rows (period, delta_gdp_bn, pct_gdp, delta_cons_m,
    delta_if_m), the cumulative GDP effect in £bn over the shocked periods, and
    the peak percent-of-GDP effect. Takes roughly 10-60 seconds.
    """
    return core.obr_shock(
        var=var, shock=shock, periods=periods, name=name,
        investment_closure=investment_closure,
    )


@mcp.tool()
def list_reform_variables() -> list[dict]:
    """List the OBR policy variables commonly shocked with obr_shock.

    Returns each variable's code, description, shock units (£m per quarter vs
    decimal rate change), and whether it defaults investment_closure=True.
    Instant; call this before obr_shock if unsure of units. (score_reform
    takes PolicyEngine reform dicts, not these raw variables.)
    """
    return core.obr_list_variables()


@mcp.tool()
def frbus_shock(
    var: str,
    shock: float,
    start: str = "2026Q1",
    periods: int = 1,
    horizon: int = 20,
    policy_rule: str = "inertial_taylor",
    variables: list[str] | None = None,
    name: str | None = None,
) -> dict:
    """Shock one FRB/US variable and return the US impulse responses — the
    US counterpart of obr_shock, using the Federal Reserve Board's FRB/US
    model (VAR/backward-looking expectations, 284 endogenous equations,
    April 2026 LONGBASE vintage).

    Solves an add-factored baseline that reproduces LONGBASE to machine
    precision, then the same model with the shock applied, and returns
    per-quarter DEVIATIONS FROM BASELINE for the headline series: xgdp (real
    GDP, %), lur (unemployment rate, pp), picxfe (core PCE inflation, pp),
    pcpi (CPI price level, %) and rff (federal funds rate, pp).

    NOTE: this takes raw model variables, NOT PolicyEngine reform dicts.
    There is deliberately no PolicyEngine-reform bridge for FRB/US (see
    score_reform), so this tool is the only supported entry point.

    Args:
        var: Lever to shock — call frbus_list_variables first. Most are
            add-errors (`<name>_aerr`): 'rffintay_aerr' (monetary policy),
            'egfe_aerr' (federal purchases), 'trp_aerr' (personal tax rate),
            'trci_aerr' (corporate tax rate), 'ecnia_aerr' (consumption).
            Endogenous variables cannot be shocked directly — their own
            equation would overwrite the level, so shock the add-error.
        shock: Shock size, added each shocked quarter. UNITS DIFFER PER LEVER
            AND ARE NOT INTERCHANGEABLE. rffintay_aerr is in percentage points
            (1.0 = a 100bp tightening); trp_aerr/trci_aerr are decimal rate
            changes (0.01 = 1pp); egfe_aerr/ecnia_aerr and the other spending
            levers are in LOG POINTS OF QUARTERLY GROWTH (0.01 ~ a 1% higher
            level), NOT billions of dollars — passing a dollar-sized number
            there diverges the solver and returns an error.
        start: First shocked quarter, e.g. '2026Q1' (default).
        periods: Quarters the shock is held from `start` (default 1 = a
            single-quarter impulse, matching the Fed's demo).
        horizon: Quarters simulated and reported (default 20 = 5 years).
        policy_rule: How monetary policy responds — this materially changes
            the answer and is often the economic point of the exercise:
            'inertial_taylor' (default, the LONGBASE/validation rule),
            'taylor' (non-inertial), or 'fixed_funds_rate' (funds rate held
            on its baseline path, no endogenous monetary offset, so fiscal
            multipliers are markedly larger). Each rule reads its OWN
            add-error, so shocking 'rffintay_aerr' under a non-inertial rule
            is rejected with an explanation rather than silently returning
            all-zero responses.
        variables: Optional extra model variables to report alongside the
            headline series.
        name: Optional label for the experiment.

    Returns per-quarter rows, a `peaks` block giving each series' largest
    absolute deviation and when it occurs, and `series_meaning` documenting
    each series' units. Roughly 3 seconds cold, well under a second warm.
    """
    return core.frbus_shock(
        var=var, shock=shock, start=start, periods=periods, horizon=horizon,
        policy_rule=policy_rule, variables=variables, name=name,
    )


@mcp.tool()
def frbus_list_variables() -> list[dict]:
    """List the FRB/US levers that can be shocked with frbus_shock.

    Returns each lever's name, description, units, a typical shock size, and
    which monetary policy rule it requires (if any). Instant — call this
    before frbus_shock, because units differ per lever and a shock sized for
    the wrong units either diverges the solver or silently produces nonsense.
    """
    return core.frbus_list_variables()


@mcp.tool()
def frbus_summary() -> dict:
    """Metadata and validation provenance for the FRB/US member.

    No solve, so effectively instant once the model package is loaded (the
    very first FRB/US call in a fresh container pays a ~3s import of frbus and
    its scipy/sympy stack): what the model is (284 endogenous equations, April
    2026 LONGBASE vintage, VAR expectations — MCE is not implemented), the
    available monetary policy rules, and how the implementation was validated
    against the Federal Reserve's own pyfrbus: the tracking invariant holds to
    5.6e-17 and the 100bp monetary shock matches pyfrbus 1.0.0 to 6.0e-9
    across all 284 variables. Also states plainly that FRB/US has NO
    PolicyEngine-reform bridge and that frbus_shock is the supported entry
    point.
    """
    return core.frbus_summary()


@mcp.tool()
def hank_shock(
    kind: str,
    size: float,
    persistence: float = 0.9,
    horizon: int = 20,
    variant: str = "two_asset",
    include_distribution: bool = False,
    name: str | None = None,
) -> dict:
    """Run a stylized shock through the US HANK model (Auclert, Bardóczy,
    Rognlie & Straub, Econometrica 2021 — two-asset heterogeneous-agent New
    Keynesian, solved in the sequence space) and return the impulse responses.

    HONEST FRAMING: a validated replication scoring STYLIZED shocks — a
    VAR-free sequence-space HANK. It is NOT a forecaster and does NOT score
    detailed tax reforms (score_reform rejects model='hank'); distributional
    outputs are first-order approximations. Responses are linear deviations
    around a calibrated steady state and scale exactly with the shock size.

    Args:
        kind: 'monetary' (Taylor-rule intercept rstar), 'fiscal_spending'
            (real G, implicitly financed by the endogenous labor tax;
            two_asset only), or 'productivity' (TFP Z). There is deliberately
            NO transfer or tax-rate shock: the labor tax is endogenous, so no
            such instrument exists in the model.
        size: Impact size of the shock, in model units — UNITS DIFFER PER
            KIND: monetary is a level change in the QUARTERLY policy rate
            (-0.0025 = a 25bp easing); fiscal_spending is a level change in G
            (steady-state Y = 1, so 0.01 = 1% of GDP); productivity is a
            level change in Z (0.01 ~ 1% TFP). See hank_summary for the
            catalogue.
        persistence: AR(1) decay of the shock path size * persistence**t
            (default 0.9; must be in [0, 1)).
        horizon: Quarters reported (default 20 = 5 years; max 300).
        variant: 'two_asset' (default — the paper model) or 'one_asset' (fast
            no-capital variant: monetary/productivity only, no investment
            series).
        include_distribution: two_asset only — add steady-state MPC by
            liquid-wealth quartile, the hand-to-mouth share, and the impact
            consumption response by total-wealth quartile (first-order
            approximation from steady-state policies: the MPC-heterogeneity
            channel only, not full household-level dynamics).
        name: Optional label for the experiment.

    Returns per-quarter rows (Y, C, I in % deviation from steady state; pi
    and r in pp deviations of quarterly rates; plus the shock path), a
    `peaks` block, and `series_meaning`. First call per variant pays the
    steady-state (~13s) and jacobian (~5s) solves; both are cached, so warm
    calls are effectively instant.
    """
    return core.hank_shock(
        kind=kind, size=size, persistence=persistence, horizon=horizon,
        variant=variant, include_distribution=include_distribution, name=name,
    )


@mcp.tool()
def hank_summary() -> dict:
    """Metadata and validation provenance for the US HANK member (instant,
    no solve).

    States what the model is (a validated replication of Auclert, Bardóczy,
    Rognlie & Straub, Econometrica 2021, at the paper's production grids),
    the available shock kinds and their units, the two variants, and the
    scope limits: stylized shocks only, VAR-free sequence-space HANK, not a
    forecaster, no PolicyEngine-reform bridge (hank_shock is the supported
    entry point), distributional outputs are first-order approximations, and
    there is no transfer or tax-rate instrument because the labor tax is
    endogenous.
    """
    return core.hank_summary()


@mcp.tool()
def frbus_shock_incidence(
    var: str,
    shock: float,
    year: int = 2027,
    start: str = "2026Q1",
    periods: int = 1,
    horizon: int = 20,
    policy_rule: str = "inertial_taylor",
    income_concept: str = "wage_bill",
    dataset: str | None = None,
) -> dict:
    """Who bears a FRB/US shock, at household resolution (EXPERIMENTAL) —
    the macro-to-micro incidence layer, NOT reform scoring (FRB/US still
    has no PolicyEngine-reform bridge; score_reform keeps refusing
    model='frbus').

    Pipeline: frbus_shock with the real labour-market series (pl
    compensation per hour, lhp hours, leh employment; % deviations from
    baseline) -> the annual mean of the `year` quarters becomes a pre-tax
    earnings factor -> the factor scales the US population microsim's
    employment-income inputs with policy IDENTICAL on both sides. The
    result is the shock's incidence through the AUTOMATIC STABILIZERS:
    a negative earnings shock reduces tax revenue and raises means-tested
    benefits (budgetary_impact_bn in $bn/year, positive = the shock
    improves the government balance), with decile impacts and
    winner/loser counts.

    Args:
        var: FRB/US lever, e.g. 'rffintay_aerr' — see frbus_list_variables;
            units differ per lever.
        shock: Shock size in the lever's model units.
        year: Calendar year averaged into the overlay and scored by the
            microsim (default 2027; its four quarters must fall inside
            start+horizon).
        start / periods / horizon / policy_rule: As in frbus_shock.
        income_concept: 'wage_bill' (default: pl+lhp — the aggregate
            labour-income change, applied uniformly) or 'wage' (pl alone).
        dataset: Optional microdata dataset name override.

    What this tool CANNOT do: score a tax reform (no reform bridge);
    allocate job losses to individual households (uniform scaling
    understates the concentration of real incidence in job losers —
    stated in caveats). US only. Runtime: seconds for the FRB/US solve
    plus a US microsim run (~tens of seconds warm; the first-ever call
    downloads microdata).

    Returns the frbus payload, the economic_assumptions factors, an
    `application` block, the microsim incidence block, and a common
    `score` block (model 'frbus+microsim', result_type 'illustration').
    """
    return core.frbus_shock_incidence(
        var=var, shock=shock, year=year, start=start, periods=periods,
        horizon=horizon, policy_rule=policy_rule,
        income_concept=income_concept, dataset=dataset,
    )


@mcp.tool()
def hank_shock_incidence(
    kind: str,
    size: float,
    year: int = 2026,
    persistence: float = 0.9,
    horizon: int = 20,
    variant: str = "two_asset",
    income_concept: str = "wage_bill",
    start_year: int = 2026,
    dataset: str | None = None,
) -> dict:
    """Who bears a US HANK shock, at household resolution (EXPERIMENTAL) —
    the macro-to-micro incidence layer, NOT reform scoring (HANK still has
    no PolicyEngine-reform bridge; score_reform keeps refusing
    model='hank').

    Pipeline: hank_shock — which surfaces the model's pre-tax real wage
    (w) and labor (N) IRFs, % deviations from steady state, computed from
    the GE sequence-space Jacobian — then the annual mean of the `year`
    quarters becomes a pre-tax earnings factor scaling the US population
    microsim's employment-income inputs, policy identical on both sides.
    Reports the automatic-stabilizer budget change (budgetary_impact_bn,
    $bn/year), decile impacts and winner/loser counts.

    Args:
        kind / size / persistence / horizon / variant: As in hank_shock
            (units differ per kind; see hank_summary). horizon must cover
            the incidence year's quarters.
        year: Calendar year averaged into the overlay and scored by the
            microsim (default 2026).
        income_concept: 'wage_bill' (default: w+N, applied uniformly) or
            'wage' (w alone).
        start_year: Calendar year the shock's quarter 0 maps to (HANK
            quarters are offsets from the shock start; default 2026).
        dataset: Optional microdata dataset name override.

    What this tool CANNOT do: score a tax reform; forecast (HANK is a
    stylized model around the Auclert-Bardóczy-Rognlie-Straub 2021
    calibrated steady state, not a US forecast baseline); allocate job
    losses to individual households (uniform scaling — stated in
    caveats). US only.

    Returns the hank payload, the economic_assumptions factors, an
    `application` block, the microsim incidence block, and a common
    `score` block (model 'hank+microsim', result_type 'illustration').
    """
    return core.hank_shock_incidence(
        kind=kind, size=size, year=year, persistence=persistence,
        horizon=horizon, variant=variant, income_concept=income_concept,
        start_year=start_year, dataset=dataset,
    )


@mcp.tool()
def svar_inflation_incidence(
    year: int = 2027,
    horizons: Annotated[int, Field(ge=1, le=40)] = 12,
    draws: Annotated[int, Field(ge=50, le=10_000)] = 2000,
    reference: str = "obr",
    dataset: str | None = None,
) -> dict:
    """Cost and household incidence of the UK SVAR's CPI gap through
    statutory benefit uprating (EXPERIMENTAL) — a price-side incidence
    mechanism, unlike the earnings-overlay tools.

    Computes the CPI gap = the SVAR's median YoY CPI inflation for `year`
    (annual mean of its four quarters, in %) minus the reference path,
    then builds a REAL PolicyEngine reform: a short curated list of
    statutorily CPI-uprated UK parameters (Universal Credit standard
    allowances and child element, Child Benefit rates) each scaled by
    (1 + gap/100) from 6 April `year+1` against its baseline value in
    force then, scored with the UK population microsim for `year+1`.
    budgetary_impact_bn is in £bn/year; a positive gap costs money
    (negative budgetary impact) and lands in the deciles shown.

    Args:
        year: Forecast year whose CPI gap drives the following April's
            uprating (default 2027; must be within the SVAR horizon).
        horizons: SVAR forecast horizon in quarters (1-40; default 12 —
            must cover the year's four quarters).
        draws: SVAR posterior draws (50-10,000; default 2000). The first
            call estimates the SVAR — a couple of minutes cold, like
            forecast_uk; results are cached in-process.
        reference: 'obr' (default) — the March 2026 EFO CPI path packaged
            with obr_macro — or 'target' — a flat 2.0%.
        dataset: Optional microdata dataset name override.

    What this tool CANNOT do (stated in caveats): the state pension
    (triple lock is not a pure CPI link), income tax and NI thresholds
    (frozen by statute), Local Housing Allowance, and the benefit cap are
    NOT included, so the true fiscal sensitivity to inflation is larger
    than this curated slice; only the SVAR median is propagated, not its
    uncertainty bands; the statutory September-CPI reference month is
    approximated by the annual average. UK only.

    Returns the gap arithmetic, the curated parameters with baseline and
    counterfactual values, the reform dict, the microsim result, and a
    common `score` block (model 'svar+microsim', result_type
    'illustration').
    """
    return core.svar_inflation_incidence(
        year=year, horizons=horizons, draws=draws, reference=reference,
        dataset=dataset,
    )


@mcp.tool()
def forecast_uk(
    horizons: Annotated[int, Field(ge=1, le=40)] = 12,
    draws: Annotated[int, Field(ge=50, le=10_000)] = 2000,
) -> dict:
    """Forecast UK YoY GDP growth and CPI inflation with the UK SVAR model.

    Estimates a Bayesian VAR (1992Q1-2025Q1 sample, sign-identified structural
    shocks) and simulates the predictive distribution from the latest data
    quarter. Returns, per future quarter, the median and 68%/90% bands for YoY
    GDP growth and YoY CPI inflation, both in percent. The response includes a
    `warnings` list flagging weak inference (fewer than 100 accepted draws or
    importance-weight ESS below 100) with a recommended draw count.

    Args:
        horizons: Forecast horizon in quarters (1-40; default 12 = 3 years).
        draws: Posterior draws (default 2000: ~135 accepted draws, ESS ~65,
            a couple of minutes on first call; ~3500 draws reaches ESS >= 100;
            500 is faster but yields ~35 accepted, ESS ~14, and a warning).
            Must be between 50 and 10,000. Results are cached in-process, so
            repeated calls with the same
            (horizons, draws) are instant.
    """
    return core.svar_forecast(horizons=horizons, draws=draws)


@mcp.tool()
def latest_shocks(
    draws: Annotated[int, Field(ge=50, le=10_000)] = 2000,
) -> dict:
    """Structural-shock reading for the latest data quarter from the UK SVAR.

    For each of the 6 identified shocks (world demand/energy/supply, UK
    demand/supply/monetary policy) returns the posterior probability the shock
    was positive vs negative in the latest quarter, plus a one-line reading.

    The response includes a `warnings` list flagging weak inference (fewer
    than 100 accepted draws or importance-weight ESS below 100).

    Args:
        draws: Posterior draws (50-10,000; default 2000, ~2 minutes on first
            call; can be raised for precision). Cached in-process, so repeat
            calls are instant.
    """
    return core.svar_latest_shocks(draws=draws)


@mcp.tool()
def model_summary() -> dict:
    """Headline results of the UK SVAR replication, parsed from committed files.

    Instant (no estimation): returns last-run metadata (draws, acceptance, ESS,
    sample) and headline 1-year FEVD shares (how much of UK GDP and CPI variance
    is explained by global vs domestic identified shocks), plus the latest
    forecast-revision exercise's shock-sign table.
    """
    return core.svar_summary()


@mcp.tool()
def calculate_household(
    country: str | None = None,
    people: list[dict] | None = None,
    year: int = 2026,
    reform: dict | None = None,
    benunit: dict | None = None,
    tax_unit: dict | None = None,
    household: dict | None = None,
) -> dict:
    """Calculate taxes and benefits for a custom household with the
    PolicyEngine microsimulation model (full UK/US tax-benefit rules).

    Args:
        country: 'uk' or 'us'.
        people: List of person dicts. All money amounts are ANNUAL and in the
            country's currency (GBP for uk, USD for us), as plain numbers.
            Example: [{"age": 35, "employment_income": 50000}, {"age": 5}].
        year: Tax year (default 2026).
        reform: Optional parametric reform as {parameter_path: value}, e.g.
            {"gov.hmrc.income_tax.rates.uk[0].rate": 0.25} (UK basic rate to
            25%, a decimal) or {"gov.irs.credits.ctc.amount.base[0].amount":
            3000} (US CTC to $3,000). A value may also be a
            {effective_date: value} dict with a single YYYY-MM-DD date, e.g.
            {"gov.hmrc.income_tax.rates.uk[0].rate": {"2026-01-01": 0.21}};
            date ranges are not supported. Call list_reform_parameters for
            verified paths and units.
        benunit: UK only, optional benefit-unit dict, e.g.
            {"would_claim_uc": true, "would_claim_child_benefit": true}.
        tax_unit: US only, optional, e.g. {"filing_status": "SINGLE"} or "JOINT".
        household: Optional household dict. US: {"state_code_str": "CA"} --
            the state is HOUSEHOLD-level and must use the key
            `state_code_str` (two-letter code). If omitted, PolicyEngine US
            defaults to CA, which materially changes state income tax
            (e.g. TX and FL levy none), so always set it for US households.
            UK: {"rent": 12000, "region": "NORTH_WEST"}.

    Returns a dict with a headline `summary` (UK: per-person income tax and
    National Insurance in £, household net income, tax, benefits, Universal
    Credit, Child Benefit; US: federal income tax, payroll tax, state income
    tax, CTC, EITC, household net income in $) plus full per-entity variable
    dicts. Takes a few seconds per call.
    """
    return core.pe_household(
        country=country, people=people, year=year, reform=reform,
        benunit=benunit, tax_unit=tax_unit, household=household,
    )


@mcp.tool()
def household_reform_impact(
    country: str | None = None,
    people: list[dict] | None = None,
    reform: dict | None = None,
    year: int = 2026,
    benunit: dict | None = None,
    tax_unit: dict | None = None,
    household: dict | None = None,
) -> dict:
    """What does a tax/benefit reform do to a specific family? Runs the
    PolicyEngine household calculation twice (baseline and reform) and
    returns both summaries plus the change in each headline number.

    Args are as in calculate_household, but `reform` is REQUIRED:
    {parameter_path: value}, e.g. {"gov.hmrc.income_tax.allowances.
    personal_allowance.amount": 15000} raises the UK personal allowance to
    £15,000/year. Rates are decimals (0.25 = 25%); amounts are annual £/$
    unless list_reform_parameters says otherwise (e.g. Child Benefit is
    £/week). The `change` dict and `net_income_change` are reform minus
    baseline, so a positive net_income_change means the family gains.
    """
    return core.pe_household_impact(
        country=country, people=people, reform=reform, year=year,
        benunit=benunit, tax_unit=tax_unit, household=household,
    )


@mcp.tool()
def list_reform_parameters() -> list[dict]:
    """List curated, verified PolicyEngine reform parameters for use in the
    `reform` argument of calculate_household / household_reform_impact.

    Returns ~10 well-known UK and US parameters with their exact path,
    description, units (decimal rates vs annual £/$ amounts), and the current
    baseline_value resolved live from the policyengine parameter tree (so it
    is never stale). An entry with "live": false failed to resolve upstream —
    trust its live_error over its static description. Other parameter paths
    from the policyengine-uk/-us parameter trees also work, but are not
    listed here.
    """
    return core.pe_list_common_parameters()


@mcp.tool()
def population_reform_impact(
    country: str = "uk",
    reform: dict | None = None,
    year: int = 2026,
    dataset: str | None = None,
) -> dict:
    """Score a tax/benefit reform for the WHOLE population with the
    PolicyEngine microsimulation — the tool for questions like "what would
    equalising capital gains tax rates with income tax rates raise?".

    Runs baseline and reform simulations over representative household
    microdata (UK: enhanced FRS, ~54k households; US: CPS-based) and returns:
    - budgetary_impact_bn: change in government revenue net of spending, in
      £bn (UK) or $bn (US) PER YEAR; positive = the reform raises revenue.
    - household_net_income_change_bn, winner/loser counts, and per-income-
      decile average income changes.

    Args:
        country: 'uk' (default) or 'us'.
        reform: REQUIRED flat {parameter_path: value} dict, same shape as
            household_reform_impact. Example — equalise CGT with income tax
            rates: {"gov.hmrc.cgt.basic_rate": 0.20,
            "gov.hmrc.cgt.higher_rate": 0.40,
            "gov.hmrc.cgt.additional_rate": 0.45}. Rates are decimals.
        year: Simulation year (default 2026).
        dataset: Optional dataset name override (UK default:
            enhanced_frs_2023_24).

    Runtime (measured): ~6 seconds per simulation run plus ~20s of model
    import on the first call in a fresh process — expect ~30-40s for the
    first reform scored, then ~10s per further reform (the baseline is
    cached in-process). The VERY FIRST call ever in an environment also
    downloads the microdata (~125MB; UK data is private and needs
    HUGGING_FACE_TOKEN) and builds a ~92MB per-year dataset file — allow a
    few extra minutes for that one call. Peak memory ~2GB.
    """
    return core.pe_population_impact(
        country=country, reform=reform, year=year, dataset=dataset,
    )


@mcp.tool()
def dynamic_reform_impact(
    country: str = "uk",
    reform: dict | None = None,
    year: int = 2026,
    dataset: str | None = None,
    max_iter: int = 250,
) -> dict:
    """Dynamic population score (issue #11): the OG-UK overlapping-
    generations model's long-run wage change becomes an EconomicAssumptions
    overlay applied as DIRECT INPUT SCALING — the reform simulation's
    employment-income arrays are multiplied by the wage factor through the
    engine's Dynamic(simulation_modifier=...) hook — and the reform is
    re-scored against the untouched stock baseline. (Input scaling, not a
    parameter overlay: uprating-parameter overrides are dead in population
    runs because the per-year microdata are pre-uprated at dataset build
    time; reforms touching gov.economic_assumptions.* are refused — they
    would double-drive the overlay's channel, and the input-uprating index
    paths among them are additionally inert; see the reform arg below.)

    The overlay carries only the reform/baseline RATIO from the macro
    model (the stock baseline already embeds the OBR forecast), so the
    static effect is never double-counted; a null macro result attaches no
    modifier and reduces this exactly to population_reform_impact.

    Args:
        country: 'uk' only (OG-UK is a UK model).
        reform: REQUIRED flat {parameter_path: value} dict, same shape as
            population_reform_impact. Must NOT touch
            gov.economic_assumptions.*: the overlay already carries the
            macro model's economic assumptions (an override would
            double-drive the channel), and the input-uprating index paths
            there are additionally inert in population runs — so such
            reforms are refused. Some paths in that namespace ARE live at
            simulation time; apply those via a static run if intended.
        year: Reform start year / microsim year (default 2026).
        dataset: Optional microdata dataset name override.
        max_iter: OG steady-state solver iteration cap (default 250).

    Runtime: ~two OG-UK steady-state solves (the baseline is cached
    in-process, but a cold solve takes >10 minutes) plus one microsim run.
    NOT AVAILABLE on the hosted server: oguk is deliberately excluded from
    the Modal image (a solve cannot fit the 600s request timeout), so this
    tool returns an actionable error there — run it locally instead, as
    the TWO-STEP pipeline (oguk needs its own environment until
    PSLmodels/OG-UK#68): in an OG env, `pe-macro og-score --reform '...'
    --json > og.json`; then `pe-macro dynamic-score --reform '...'
    --og-payload og.json`.

    Returns the microsim result plus the OG payload, the
    economic_assumptions factors, an `application` block describing the
    input scaling actually applied,
    and a common `score` block (model 'og+microsim').
    """
    # Errors — including the hosted "oguk not importable" case — surface as
    # MCP tool errors (isError=true), never as a successful result whose
    # payload happens to contain an "error" key; core raises the actionable
    # two-step guidance itself, so score_reform(model="og+microsim") gets
    # the identical behaviour.
    return core.dynamic_population_reform_impact(
        country=country, reform=reform, year=year, dataset=dataset,
        max_iter=max_iter,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")


@mcp.tool()
def define_list_scenarios() -> dict:
    """List DEFINE-UK climate-policy scenarios (ecological stock-flow
    consistent model, UK; experimental).

    DEFINE-UK is LOCAL-ONLY: the upstream code is unlicensed and never
    hosted, so on the hosted server this returns installation and run
    instructions rather than results. Locally (adapter installed + cached
    run present) it returns the 22 curated scenarios across four blocks:
    power-sector regulation, housing regulation, green public investment,
    and mixed policy packages.
    """
    return core.define_list_scenarios()


@mcp.tool()
def define_scenario(name: str, horizon_years: int = 15) -> dict:
    """Run a DEFINE-UK climate-policy scenario and return annual DELTAS vs
    baseline (real GDP, emissions, unemployment, real consumption), 2023-2037.

    Deltas only, by design: the model's baseline levels are not validated
    against outturns, and every result carries mandatory caveats (demand-led
    closure; emissions vintage divergence; experimental, oracle-gated).
    LOCAL-ONLY like the OG model — hosted calls return run instructions.
    score_reform does not accept this model: no statute mapping exists.

    Args:
        name: Scenario name from define_list_scenarios (e.g.
            "green_public_investment", "fossil_fuel_ban",
            "housing_regulation_subsidy").
        horizon_years: Annual delta horizon (default 15 = 2023-2037).
    """
    return core.define_scenario(name, horizon_years=horizon_years)
