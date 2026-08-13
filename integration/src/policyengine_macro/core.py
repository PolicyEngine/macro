"""Model adapters. Single source of truth for the CLI and the MCP server.

Every public function returns plain dicts/lists that are directly JSON
serialisable.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

# Fallback checkout of boe-var-model for svar_summary when the boe_var
# package is not installed; unset means no fallback.
BOE_VAR_REPO_ENV = "POLICYENGINE_MACRO_BOE_VAR_REPO"

# boe_var column names for the two headline series. Resolved to indices by
# name against the loaded dataset's own columns, so an upstream reorder can
# never silently mislabel a series.
_COL_CPI, _COL_GDP = "cpisa", "uk_gdp"


def _package_version(distribution: str) -> str:
    """Installed distribution version, without making provenance optional."""
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "not-installed"


def _provenance(
    *,
    model_id: str,
    distribution: str,
    data_vintage: str,
    baseline: str,
    estimation_sample: str | None = None,
) -> dict:
    """Common model/run provenance returned by every public adapter."""
    package_version = _package_version(distribution)
    source_urls = {
        "og-uk": "https://github.com/PolicyEngine/og-uk",
        "pe-microsim": "https://github.com/PolicyEngine/policyengine",
        "obr-macro": "https://github.com/PolicyEngine/obr-macroeconomic-model",
        "boe-svar": "https://github.com/PolicyEngine/boe-var-model",
        "frb-us": "https://github.com/PolicyEngine/us-frb-model",
        "og+microsim": "https://github.com/PolicyEngine/macro",
        "us-hank": "https://github.com/PolicyEngine/us-hank-model",
    }
    revision_env = {
        "obr-macro": "POLICYENGINE_MACRO_SOURCE_REVISION_OBR",
        "boe-svar": "POLICYENGINE_MACRO_SOURCE_REVISION_BOE",
        "frb-us": "POLICYENGINE_MACRO_SOURCE_REVISION_FRB",
        "us-hank": "POLICYENGINE_MACRO_SOURCE_REVISION_HANK",
    }
    source_revision = os.environ.get(revision_env.get(model_id, ""))
    if not source_revision:
        source_revision = f"installed {distribution} {package_version}"
    reproducibility = (
        "Check out the recorded source URL at the recorded source revision, "
        "install the recorded adapter version, and rerun the serialized "
        "request against the recorded baseline and data vintage."
        if re.fullmatch(r"[0-9a-f]{40}", source_revision)
        else
        "Install the recorded package versions and rerun the serialized "
        "request against the recorded baseline and data vintage."
    )
    return {
        "model_id": model_id,
        "package": distribution,
        "package_version": package_version,
        "model_version": package_version,
        "adapter_version": _package_version("policyengine-macro"),
        "source_url": source_urls.get(model_id, "https://github.com/PolicyEngine/macro"),
        "source_revision": source_revision,
        "data_vintage": data_vintage,
        "baseline_vintage": baseline,
        "baseline": baseline,
        "estimation_sample": estimation_sample,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "reproducibility": reproducibility,
    }


# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

def _import_obr():
    try:
        import obr_macro  # noqa: F401
        from obr_macro import run_reform
    except ImportError as e:
        raise ImportError(
            "The OBR emulator package `obr_macro` is not importable. "
            "Install it with: pip install git+https://github.com/PolicyEngine/obr-macroeconomic-model"
        ) from e
    return run_reform


def _import_boe_var():
    try:
        import boe_var  # noqa: F401
        from boe_var import analysis, forecast
        from boe_var.bvar import BVAR
        from boe_var.data import load_data
        from boe_var.identification import ess, identify
    except ImportError as e:
        raise ImportError(
            "The UK SVAR package `boe_var` is not importable. "
            "Install it with: pip install git+https://github.com/PolicyEngine/boe-var-model"
        ) from e
    return analysis, forecast, BVAR, load_data, identify, ess


# ---------------------------------------------------------------------------
# OBR emulator adapters
# ---------------------------------------------------------------------------

# Curated list of commonly shocked exogenous policy variables (from the repo's
# reform_analysis examples and docs).
OBR_VARIABLES = [
    {
        "var": "CGG",
        "description": "Real government consumption",
        "units": "£m per quarter (e.g. 1250 = £5bn/year increase)",
        "investment_closure": False,
    },
    {
        "var": "TCPRO",
        "description": "Corporation tax (main) rate",
        "units": "rate change in decimal (e.g. -0.05 = 5pp cut from 25% to 20%)",
        "investment_closure": True,
        # The investment closure's stabiliser anchors the LEVEL, not the
        # deviation, and the deviation does not converge at any horizon: for a
        # sustained +5pp rise |delta_IF| runs £97m at q3, £2,876m at q12 and
        # £43,387m at q25, growing 1.21-1.27x every quarter for 25 quarters.
        # Truncating the shock from 12 quarters to 8 barely moves the q12
        # response, so the number is carried by accumulated drift rather than
        # by the tax rate. The 12-quarter default is not where this settles;
        # it is where the magnitude still looks plausible.
        "caveat": (
            "the response does not converge: it compounds at roughly "
            "25%/quarter with no steady state, so read the sign and the "
            "first few quarters, not the level or the cumulative total"
        ),
    },
    {
        "var": "CGIPS",
        "description": "Nominal central government investment (feeds real GGI via the GGIPS/GGIDEF chain)",
        "units": "£m nominal per quarter (e.g. 3000 ≈ £2.5bn real per quarter)",
        "investment_closure": False,
        # Measured: delta_IF is exactly 0.0 in all twelve quarters and the
        # residual GDP effect goes negative (-0.047 by q12) against the OBR's
        # published 1.0. The channel is not weak, it is absent.
        "caveat": (
            "this channel is dead under the demand closure: business "
            "investment does not respond at all and the residual GDP effect "
            "is wrong-signed. Do not use it to score capital spending"
        ),
    },
]


def obr_list_variables() -> list[dict]:
    """Commonly shocked policy variables with descriptions and units."""
    return [dict(v) for v in OBR_VARIABLES]


def _obr_result_rows(df) -> list[dict]:
    """run_reform results DataFrame -> plain per-quarter row dicts."""
    return [
        {
            "period": str(r.period),
            "delta_gdp_bn": round(float(r.delta_gdp_bn), 4),
            "pct_gdp": round(float(r.pct_gdp), 4),
            "delta_cons_m": round(float(r.delta_cons_m), 1),
            "delta_if_m": round(float(r.delta_if_m), 1),
        }
        for r in df.itertuples()
    ]


def obr_shock(
    var: str,
    shock: float,
    periods: int = 12,
    name: str | None = None,
    investment_closure: bool | None = None,
) -> dict:
    """Shock one OBR exogenous variable directly, in model units.

    The escape hatch under score_reform: no PolicyEngine reform translation,
    just a raw additive shock (£m per quarter for CGG/CGIPS, decimal rate
    change for TCPRO). Runs baseline vs shocked solves and returns per-period
    GDP deltas plus a headline cumulative GDP effect over the shocked periods.

    ``investment_closure`` defaults per variable from the curated list
    (e.g. True for TCPRO): a corporation-tax shock without the investment
    closure solves to all-zero deltas, which would read as a misleading
    "no effect" result rather than a mis-specified run.
    """
    periods = _bounded_int(
        "periods", periods, _OBR_MIN_PERIODS, _OBR_MAX_PERIODS
    )
    run_reform = _import_obr()
    if investment_closure is None:
        known = {v["var"]: v["investment_closure"] for v in OBR_VARIABLES}
        investment_closure = known.get(var, False)
    if name is None:
        name = f"{var} shock {shock:+g}"
    df = run_reform(
        name=name,
        var=var,
        shock=float(shock),
        periods=periods,
        investment_closure=bool(investment_closure),
    )
    rows = _obr_result_rows(df)
    shocked = rows[: int(periods)]
    peak = max(rows, key=lambda r: abs(r["pct_gdp"]))
    # A lever whose channel is dead or non-convergent must say so in the
    # payload, not only in a docstring nobody reads over MCP. Of the four
    # fiscal instruments here exactly one contains behaviour: CGG is an
    # accounting identity (multiplier exactly 1.0000, flat, against the OBR's
    # published 0.6), CGIPS is dead, TCPRO never converges, and the
    # household-income lever is the only one with a response worth reading.
    caveat = next(
        (v.get("caveat") for v in OBR_VARIABLES if v["var"] == var), None
    )
    result = {
        "name": name,
        "provenance": _provenance(
            model_id="obr-emulator",
            distribution="obr-macro-model",
            data_vintage="March 2026 EFO",
            baseline="March 2026 EFO anchored baseline",
        ),
        "var": var,
        "shock": float(shock),
        "periods": int(periods),
        "investment_closure": bool(investment_closure),
        "results": rows,
        "cumulative_delta_gdp_bn_over_shock_periods": round(
            sum(r["delta_gdp_bn"] for r in shocked), 3
        ),
        "peak_pct_gdp": peak["pct_gdp"],
        "peak_period": peak["period"],
    }
    if caveat:
        result["caveat"] = caveat
    return result


# ---------------------------------------------------------------------------
# FRB/US adapters
# ---------------------------------------------------------------------------

# Optional checkout override for legacy editable installs. Current frbus wheels
# ship their runtime files under frbus/_data and need no repository path.
FRB_REPO_ENV = "POLICYENGINE_MACRO_FRB_REPO"

# The model is only defined out to the LONGBASE horizon and the demo/validation
# window is 2026Q1-2030Q4; these are the defaults every published number uses.
FRBUS_DEFAULT_START = "2026Q1"
FRBUS_DEFAULT_HORIZON = 20  # quarters

# Monetary policy rule selectors. FRB/US picks the rule feeding `rffrule` from a
# family of dmp* dummies; exactly one is switched on. This matters a lot: the
# same shock under a fixed funds rate and under the inertial Taylor rule gives
# materially different answers, because the endogenous policy response is the
# main propagation channel.
FRBUS_POLICY_RULES = {
    "inertial_taylor": {
        "description": "Inertial Taylor rule (dmpintay=1) — the LONGBASE "
                       "default and the rule used in VALIDATION.md",
        "switches": {"dmpintay": 1, "dmptay": 0, "dmpalt": 0, "dmprr": 0,
                     "dmptlr": 0, "dmpex": 0},
        "exogenize": [],
        # Each rule reads its own add-error; a shock to another rule's error
        # term is silently inert (see _frbus_check_rule_lever).
        "shock_lever": "rffintay_aerr",
    },
    "taylor": {
        "description": "Non-inertial (contemporaneous) Taylor rule (dmptay=1)",
        "switches": {"dmpintay": 0, "dmptay": 1, "dmpalt": 0, "dmprr": 0,
                     "dmptlr": 0, "dmpex": 0},
        "exogenize": [],
        "shock_lever": "rfftay_aerr",
    },
    "fixed_funds_rate": {
        "description": "Funds rate held on its baseline path (rff exogenized) "
                       "— no endogenous monetary response, so fiscal "
                       "multipliers are markedly larger",
        "switches": {},
        "exogenize": ["rff"],
        "shock_lever": None,
    },
}

# Headline series always returned, with how a deviation from baseline is
# meaningful for each. "pct" = percent difference in the level; "pp" = simple
# difference, already in percentage points in model units.
FRBUS_HEADLINE = {
    "xgdp": ("pct", "Real GDP, % deviation from baseline"),
    "lur": ("pp", "Unemployment rate, pp deviation from baseline"),
    "picxfe": ("pp", "Core PCE inflation (annual rate), pp deviation"),
    "pcpi": ("pct", "CPI price level, % deviation from baseline"),
    "rff": ("pp", "Federal funds rate, pp deviation from baseline"),
}

# Curated shockable levers. UNITS ARE THE TRAP HERE and are stated per entry:
# FRB/US behavioural equations are written in a mix of levels, rates and
# log-differences, so the add-error `<var>_aerr` inherits the units of ITS
# equation's left-hand side. egfe's equation is in log-differences, so
# egfe_aerr is in log points of quarterly growth, NOT billions of dollars —
# passing 10 there (as if it were $10bn) diverges the Newton solver.
FRBUS_VARIABLES = [
    {
        "var": "rffintay_aerr",
        "description": "Add-error on the inertial Taylor rule — the standard "
                       "monetary policy shock (vendor demos/example1.py)",
        "units": "percentage points on the funds rate, PER SHOCKED PERIOD "
                 "(1.0 = 100bp). With periods>1 the add-factors stack: "
                 "shock=1.0, periods=4 peaks near +3pp on the funds "
                 "rate, not +1pp — set periods=1 for a one-quarter "
                 "100bp move.",
        "typical_shock": 1.0,
        "requires_policy_rule": "inertial_taylor",
    },
    {
        "var": "rfftay_aerr",
        "description": "Add-error on the non-inertial Taylor rule — the "
                       "monetary policy shock when policy_rule='taylor'",
        "units": "percentage points on the funds rate, PER SHOCKED PERIOD "
                 "(1.0 = 100bp). With periods>1 the add-factors stack: "
                 "shock=1.0, periods=4 peaks near +3pp on the funds "
                 "rate, not +1pp — set periods=1 for a one-quarter "
                 "100bp move.",
        "typical_shock": 1.0,
        "requires_policy_rule": "taylor",
    },
    {
        "var": "egfe_aerr",
        "description": "Add-error on federal government purchases (defence + "
                       "non-defence consumption and investment)",
        "units": "LOG POINTS of quarterly growth in egfe (0.01 ~ a 1% higher "
                 "level of federal purchases; egfe is ~4.6% of GDP, so 0.01 "
                 "is roughly 0.046% of GDP). NOT billions of dollars — a "
                 "shock of order 1 or more diverges the solver.",
        "typical_shock": 0.01,
        "requires_policy_rule": None,
    },
    {
        "var": "egse_aerr",
        "description": "Add-error on state and local government purchases",
        "units": "log points of quarterly growth in egse (0.01 ~ a 1% higher "
                 "level of S&L purchases)",
        "typical_shock": 0.01,
        "requires_policy_rule": None,
    },
    {
        "var": "trp_aerr",
        "description": "Add-error on the personal income tax rate",
        "units": "decimal rate change (0.01 = a 1 percentage point rise in the "
                 "effective personal tax rate)",
        "typical_shock": 0.01,
        "requires_policy_rule": None,
    },
    {
        "var": "trci_aerr",
        "description": "Add-error on the corporate income tax rate",
        "units": "decimal rate change (0.01 = a 1pp rise in the effective "
                 "corporate tax rate)",
        "typical_shock": 0.01,
        "requires_policy_rule": None,
    },
    {
        "var": "ecnia_aerr",
        "description": "Add-error on aggregate consumption — a direct demand "
                       "shock",
        "units": "log points of quarterly consumption growth (0.01 ~ 1% higher "
                 "consumption; large, since consumption is ~68% of GDP)",
        "typical_shock": 0.01,
        "requires_policy_rule": None,
    },
    {
        "var": "ebfi_aerr",
        "description": "Add-error on business fixed investment",
        "units": "log points of quarterly BFI growth (0.01 ~ 1% higher BFI)",
        "typical_shock": 0.01,
        "requires_policy_rule": None,
    },
]

_FRBUS_VAR_INDEX = {v["var"]: v for v in FRBUS_VARIABLES}

# Cache the compiled model + its add-factored baseline. Building an Frbus
# instance symbolically differentiates 284 equations (~0.7s one-off) and
# init_trac costs ~2.3s, so caching per (policy_rule, start, end) makes every
# repeat call in a warm container a bare ~0.3s solve.
_FRBUS_BASELINE_CACHE: dict[tuple[str, str, str], tuple] = {}


def _import_frbus():
    try:
        import frbus  # noqa: F401
        from frbus import Frbus, load_data
    except ImportError as e:
        raise ImportError(
            "The FRB/US package `frbus` is not importable. "
            "Install it with: pip install git+https://github.com/PolicyEngine/us-frb-model"
        ) from e
    return frbus, Frbus, load_data


def _frbus_repo() -> Path:
    """Locate a legacy checkout holding vendor/ (model.xml + LONGBASE.TXT).

    Current frbus wheels expose packaged data through ``_frbus_paths``. This
    fallback remains for older editable installs and explicit repository
    overrides.
    """
    env = os.environ.get(FRB_REPO_ENV)
    candidates = []
    if env:
        candidates.append(Path(env))
    frbus_mod, _, _ = _import_frbus()
    candidates.append(Path(frbus_mod.__file__).resolve().parents[2])
    for root in candidates:
        if (root / "vendor" / "pyfrbus_package" / "models" / "model.xml").exists():
            return root
    raise FileNotFoundError(
        "Could not locate the us-frb-model checkout containing "
        "vendor/pyfrbus_package/models/model.xml (tried: "
        f"{', '.join(str(c) for c in candidates)}). Upgrade frbus to a wheel "
        f"that includes package data, install it editably, or set {FRB_REPO_ENV}."
    )


def _frbus_paths() -> tuple[str, str]:
    """Resolve (model.xml path, LONGBASE.TXT path).

    Prefers the packaged-data accessors added to the frbus package
    (``frbus.default_model_path()`` / ``frbus.default_data_path()``, which
    look in frbus/_data/ and fall back to the repo vendor/ dir for editable
    installs). An explicit POLICYENGINE_MACRO_FRB_REPO env override, or an
    older frbus without the accessors, falls back to the checkout-based
    ``_frbus_repo()`` resolution.
    """
    if not os.environ.get(FRB_REPO_ENV):
        try:
            frbus_mod, _, _ = _import_frbus()
            model_path = str(frbus_mod.default_model_path())
            data_path = str(frbus_mod.default_data_path())
            if Path(model_path).exists() and Path(data_path).exists():
                return model_path, data_path
        except (ImportError, AttributeError):
            pass  # older frbus without the accessors
        except Exception as e:  # frbus.MissingDataError, without importing it
            if type(e).__name__ != "MissingDataError":
                raise
    repo = _frbus_repo()
    return (
        str(repo / "vendor" / "pyfrbus_package" / "models" / "model.xml"),
        str(repo / "vendor" / "data_only_package" / "LONGBASE.TXT"),
    )


def _frbus_period(value, *, argument: str):
    import pandas as pd

    try:
        return pd.Period(str(value), freq="Q")
    except Exception as e:
        raise ValueError(
            f"{argument} must be a quarter like '2026Q1', got {value!r}"
        ) from e


def _frbus_baseline(policy_rule: str, start, end):
    """Compiled model + add-factored baseline that solves to LONGBASE exactly.

    After init_trac the tracking residuals are set so a baseline solve
    reproduces the data to machine precision (VALIDATION.md Test 1, 5.6e-17);
    every reported number is a deviation from THAT baseline, so the shock is
    the only thing moving.
    """
    key = (policy_rule, str(start), str(end))
    if key in _FRBUS_BASELINE_CACHE:
        return _FRBUS_BASELINE_CACHE[key]

    _, Frbus, load_data = _import_frbus()
    model_xml, longbase = _frbus_paths()
    data = load_data(longbase)
    model = Frbus(model_xml)

    spec = FRBUS_POLICY_RULES[policy_rule]
    # Standard demo fiscal configuration: surplus-ratio targeting, so the
    # solve has a stable long-run fiscal anchor instead of drifting debt.
    data.loc[start:end, "dfpdbt"] = 0
    data.loc[start:end, "dfpsrp"] = 1
    for switch, value in spec["switches"].items():
        data.loc[start:end, switch] = value
    if spec["exogenize"]:
        model.exogenize(list(spec["exogenize"]))

    with_adds = model.init_trac(start, end, data)
    _FRBUS_BASELINE_CACHE[key] = (model, with_adds)
    return model, with_adds


def _frbus_check_rule_lever(var: str, policy_rule: str) -> None:
    """Refuse a shock that the chosen policy rule makes silently inert.

    `rffintay_aerr` only enters `rffrule` when dmpintay=1. Under 'taylor' or
    'fixed_funds_rate' it is still a valid column, the solve still converges,
    and every response is exactly zero — which reads as "monetary policy has
    no effect" rather than "you shocked a disconnected term". Same failure mode
    as the OBR emulator's investment_closure trap, so it gets the same
    treatment: a loud error, not a plausible-looking zero.
    """
    entry = _FRBUS_VAR_INDEX.get(var)
    required = entry and entry.get("requires_policy_rule")
    if required and required != policy_rule:
        alt = FRBUS_POLICY_RULES[policy_rule]["shock_lever"]
        hint = (
            f"under policy_rule={policy_rule!r} the corresponding lever is "
            f"{alt!r}"
            if alt else
            f"policy_rule={policy_rule!r} holds the funds rate on its baseline "
            "path, so no monetary-rule add-error can move it; shock a fiscal "
            "or demand lever instead to see multipliers under fixed rates"
        )
        raise ValueError(
            f"{var!r} only feeds the policy rule when "
            f"policy_rule={required!r}; with policy_rule={policy_rule!r} it is "
            f"disconnected and every response would solve to exactly zero. "
            f"Either pass policy_rule={required!r}, or {hint}."
        )


def frbus_list_variables() -> list[dict]:
    """Shockable FRB/US levers with descriptions, units and policy-rule needs."""
    return [dict(v) for v in FRBUS_VARIABLES]


def frbus_shock(
    var: str,
    shock: float,
    start: str = FRBUS_DEFAULT_START,
    periods: int = 1,
    horizon: int = FRBUS_DEFAULT_HORIZON,
    policy_rule: str = "inertial_taylor",
    variables: list[str] | None = None,
    name: str | None = None,
) -> dict:
    """Shock one FRB/US exogenous variable or add-factor and return the IRFs.

    The FRB/US analogue of obr_shock: a raw shock in model units, with no
    PolicyEngine reform translation (there is deliberately no such bridge —
    see score_reform). Solves an add-factored baseline that reproduces
    LONGBASE exactly, then the same model with the shock applied, and returns
    per-quarter deviations for the headline series plus anything in
    ``variables``.

    Units differ per lever and are NOT interchangeable — call
    frbus_list_variables first. ``periods`` is how many quarters from ``start``
    the shock is held (1 = a single-quarter impulse, the vendor demo).
    """
    import pandas as pd

    if policy_rule not in FRBUS_POLICY_RULES:
        raise ValueError(
            f"policy_rule must be one of {tuple(FRBUS_POLICY_RULES)}, "
            f"got {policy_rule!r}"
        )
    periods, horizon = int(periods), int(horizon)
    if periods < 1:
        raise ValueError(f"periods must be >= 1, got {periods}")
    if horizon < periods:
        raise ValueError(
            f"horizon ({horizon}) must be at least periods ({periods})"
        )
    _frbus_check_rule_lever(var, policy_rule)

    start_p = _frbus_period(start, argument="start")
    end_p = start_p + horizon - 1
    model, with_adds = _frbus_baseline(policy_rule, start_p, end_p)

    if var not in with_adds.columns:
        known = ", ".join(sorted(v["var"] for v in FRBUS_VARIABLES))
        raise ValueError(
            f"{var!r} is not a column of the FRB/US dataset. Curated levers: "
            f"{known} (see frbus_list_variables). Endogenous variables cannot "
            "be shocked directly — shock their add-error '<var>_aerr' instead, "
            "because the equation would otherwise just overwrite the level."
        )

    shocked = with_adds.copy()
    shock_end = start_p + periods - 1
    shocked.loc[start_p:shock_end, var] += float(shock)
    try:
        sim = model.solve(start_p, end_p, shocked)
    except Exception as e:
        entry = _FRBUS_VAR_INDEX.get(var)
        units = f" Units for {var}: {entry['units']}" if entry else ""
        raise ValueError(
            f"the FRB/US Newton solver failed for a {shock:+g} shock to {var!r} "
            f"({e}). This is almost always a shock that is far too large for "
            f"the variable's units.{units}"
        ) from e

    wanted = list(FRBUS_HEADLINE)
    for extra in variables or []:
        if extra not in with_adds.columns:
            raise ValueError(f"requested variable {extra!r} is not in the model")
        if extra not in wanted:
            wanted.append(extra)

    index = pd.period_range(start_p, end_p, freq="Q")
    series: dict[str, list[float]] = {}
    for v in wanted:
        mode = FRBUS_HEADLINE.get(v, ("pct", ""))[0]
        base, new = with_adds.loc[start_p:end_p, v], sim.loc[start_p:end_p, v]
        if mode == "pct":
            delta = 100.0 * (new / base - 1.0)
        else:
            delta = new - base
        series[v] = [round(float(x), 6) for x in delta]

    rows = [
        {"period": str(p), **{v: series[v][i] for v in wanted}}
        for i, p in enumerate(index)
    ]

    def _peak(values):
        best = max(range(len(values)), key=lambda i: abs(values[i]))
        return {"value": values[best], "period": str(index[best])}

    peaks = {v: _peak(series[v]) for v in wanted}

    result = {
        "name": name or f"{var} shock {shock:+g}",
        "provenance": _provenance(
            model_id="frb-us",
            distribution="frbus",
            data_vintage="April 2026 LONGBASE",
            baseline="Federal Reserve April 2026 LONGBASE",
        ),
        "var": var,
        "shock": float(shock),
        "units": _FRBUS_VAR_INDEX.get(var, {}).get("units", "model units"),
        "start": str(start_p),
        "periods": periods,
        "horizon": horizon,
        "policy_rule": policy_rule,
        "policy_rule_description": FRBUS_POLICY_RULES[policy_rule]["description"],
        "expectations": "VAR (backward-looking); MCE is not implemented",
        "series_meaning": {
            v: FRBUS_HEADLINE.get(v, ("pct", f"{v}, % deviation from baseline"))[1]
            for v in wanted
        },
        "results": rows,
        "peaks": peaks,
    }

    # A converged solve in which nothing moves is a mis-specified experiment,
    # not a finding. The rule/lever guard catches the common case up front;
    # this catches the rest (e.g. a shock of 0, or a lever that happens to be
    # disconnected under the chosen configuration).
    if all(abs(peaks[v]["value"]) < 1e-9 for v in FRBUS_HEADLINE):
        result["warning"] = (
            f"every headline response is numerically zero: the {shock:+g} shock "
            f"to {var!r} did not propagate under policy_rule={policy_rule!r}. "
            "Treat this as a mis-specified experiment, not as evidence of no "
            "effect. Check the lever and its units with frbus_list_variables."
        )
    return result


def frbus_summary() -> dict:
    """Static metadata and validation provenance for the FRB/US member.

    No solve: reports what the model is and how it was validated. Effectively
    instant, except that the first call in a fresh process pays the one-off
    ~3s import of frbus and its scipy/sympy stack via _frbus_repo().
    The figures come from the model repo's VALIDATION.md and are the numbers
    its CI gates on; they are stated here so a caller can see the provenance
    without leaving the tool surface.
    """
    out = {
        "model": "FRB/US (VAR expectations)",
        "implementation": "frbus — PolicyEngine/us-frb-model, a from-scratch "
                          "numpy/scipy/sympy reimplementation",
        "upstream": "Federal Reserve Board FRB/US; model.xml, LONGBASE.TXT and "
                    "the pyfrbus reference implementation are public domain",
        "equations": 284,
        "equation_note": "284 endogenous variables solved simultaneously per "
                         "period by a damped Newton method with an analytic "
                         "sparse Jacobian (xtol=1e-8)",
        "data_vintage": "April 2026 LONGBASE",
        "expectations": "VAR (backward-looking) only; MCE (model-consistent "
                        "expectations) raises NotImplementedError",
        "default_window": f"{FRBUS_DEFAULT_START} + {FRBUS_DEFAULT_HORIZON} quarters",
        "policy_rules": [
            {"rule": k, "description": v["description"],
             "shock_lever": v["shock_lever"]}
            for k, v in FRBUS_POLICY_RULES.items()
        ],
        "validation": {
            "tracking_invariant": {
                "metric": "max abs error, all 284 endogenous variables x 20 "
                          "quarters, baseline solve vs LONGBASE after init_trac",
                "value": 5.6e-17,
                "gate": 1e-8,
                # Served alongside the number because a consumer reading
                # validation off this payload would otherwise take the
                # smallest figure here as the strongest evidence, when it is
                # the only one that carries none.
                "is_evidence": False,
                "caveat": (
                    "NOT evidence about the economy. init_trac sets each "
                    "add-factor to minus that equation's residual at the "
                    "input data, so the solve is algebraically the identity "
                    "on whatever it was tracked to -- for any input. The "
                    "model repo gates the demonstration: the same check "
                    "passes at 6.7e-9 on a baseline whose every series has "
                    "been scrambled by a random factor, with every "
                    "accounting identity destroyed. It gates the software. "
                    "Read vs_vendor_pyfrbus and the multipliers instead."
                ),
            },
            "vs_vendor_pyfrbus": {
                "metric": "max abs difference vs the Fed's pyfrbus 1.0.0 on the "
                          "100bp rffintay_aerr experiment, all endos x 20 quarters",
                "value": 6.0e-9,
                "gate": 1e-6,
                "note": "pyfrbus 1.1.1 differs from pyfrbus 1.0.0 by 1.3e-8 — "
                        "the Fed's own two releases differ from each other by "
                        "as much as this implementation differs from either, so "
                        "the residual is solver tolerance, not semantics",
            },
            "monetary_tightening_properties": {
                "shock": "100bp rffintay_aerr, 2026Q1, inertial Taylor rule",
                "rff_impact_pp": 1.0,
                "xgdp_trough_pct": -0.55,
                "lur_peak_pp": 0.26,
                "picxfe_trough_pp": -0.034,
                "note": "consistent with the published FRB/US VAR simulation "
                        "properties (output falls a few tenths to ~1% after "
                        "~2 years; unemployment rises ~0.1-0.3pp)",
            },
        },
        "reform_bridge": (
            "NONE. There is deliberately no PolicyEngine-reform bridge for "
            "FRB/US: no mapping exists today from a PolicyEngine US reform to "
            "FRB/US fiscal levers, and inventing one would produce "
            "plausible-looking wrong numbers. score_reform rejects "
            "model='frbus'; frbus_shock (raw variable shocks in model units) "
            "is the supported entry point."
        ),
    }
    try:
        out["source"] = str(Path(_frbus_paths()[0]).parent)
    except Exception as e:  # frbus not installed: metadata is still useful
        out["source_error"] = str(e)
    out["provenance"] = _provenance(
        model_id="frb-us",
        distribution="frbus",
        data_vintage="April 2026 LONGBASE",
        baseline="Federal Reserve LONGBASE tracking baseline",
    )
    return out


# ---------------------------------------------------------------------------
# US HANK adapters
# ---------------------------------------------------------------------------
#
# us_hank (PolicyEngine/us-hank-model) is a validated replication of the
# two-asset HANK of Auclert, Bardóczy, Rognlie & Straub (Econometrica 2021),
# solved in the sequence space at the paper's production grids. It scores
# STYLIZED shocks (monetary / fiscal spending / productivity AR(1) paths),
# not detailed tax reforms, and it is NOT a forecaster: IRFs are linear
# deviations around a calibrated steady state. Distributional outputs are
# first-order approximations built from steady-state policies.

# Model variants. 'two_asset' is the paper model; 'one_asset' is a fast
# textbook variant with no capital (no investment IRF, no fiscal instrument).
HANK_VARIANTS = ("two_asset", "one_asset")

# The internal IRF length. The GE Jacobian is a T x T object solved once per
# (variant); 300 matches the model package's default and is long enough that
# truncation error at any reported horizon is negligible. Fixed rather than
# caller-set so the expensive jacobian is computed exactly once per variant.
HANK_T = 300

HANK_DEFAULT_HORIZON = 20  # quarters reported (5 years), matching frbus

# Curated shock catalogue: the HANK analogue of FRBUS_VARIABLES. Units differ
# per kind and are stated per entry; there is deliberately no transfer or
# tax-rate instrument (the labor tax is endogenous — a G shock is implicitly
# tax-financed), so such requests are rejected upstream with an explanation.
HANK_SHOCK_KINDS = [
    {
        "kind": "monetary",
        "input": "rstar",
        "description": "Taylor-rule intercept (monetary policy) shock",
        "units": "level change in the QUARTERLY real policy rate "
                 "(-0.0025 = a 25bp-per-quarter easing on impact)",
        "typical_size": -0.0025,
        "variants": ["two_asset", "one_asset"],
    },
    {
        "kind": "fiscal_spending",
        "input": "G",
        "description": "Real government spending shock, implicitly financed "
                       "by the endogenous labor tax (the fiscal block "
                       "balances the budget)",
        "units": "level change in G; steady-state Y = 1, so 0.01 = 1% of "
                 "steady-state GDP on impact",
        "typical_size": 0.01,
        "variants": ["two_asset"],
    },
    {
        "kind": "productivity",
        "input": "Z",
        "description": "Total factor productivity shock",
        "units": "level change in Z around its steady-state value "
                 "(a LEVEL change: steady-state Z is 0.468, so 0.01 is a "
                 "~2.1% TFP improvement, not 1%)",
        "typical_size": 0.01,
        "variants": ["two_asset", "one_asset"],
    },
]

_HANK_KIND_INDEX = {k["kind"]: k for k in HANK_SHOCK_KINDS}

# Series meaning per variant. Y/C/I/w/N are % deviations from steady state;
# pi/r are level deviations of QUARTERLY rates in percentage points. w and N
# are not in the model package's shock() output; hank_shock computes them
# from the same GE sequence-space Jacobian (they are solved unknowns/outputs
# in both variants) so the macro->micro incidence layer has a pre-tax wage
# and labor path to build on.
HANK_HEADLINE = {
    "Y": "Output, % deviation from steady state",
    "C": "Aggregate consumption, % deviation from steady state",
    "I": "Investment, % deviation from steady state (two_asset only)",
    "pi": "Inflation (quarterly rate), pp deviation from steady state",
    "r": "Real interest rate (quarterly rate), pp deviation from steady state",
    "w": "Pre-tax real wage, % deviation from steady state",
    "N": "Labor, % deviation from steady state",
}

# Cache the steady state + GE jacobian per (variant, T). The steady state
# takes ~13s and the jacobian ~5s at production grids; with both cached every
# repeat IRF is a matrix-vector product and effectively instant. The us_hank
# package keeps its own module-level cache too, but this one also pins the
# (ss, G) pair the adapters report against, keyed the same way as
# _FRBUS_BASELINE_CACHE.
_HANK_CACHE: dict[tuple[str, int], tuple] = {}


def _import_us_hank():
    try:
        import us_hank  # noqa: F401
        from us_hank import distributional, model, one_asset
    except ImportError as e:
        raise ImportError(
            "The US HANK package `us_hank` is not importable. Install it "
            "with: pip install git+https://github.com/PolicyEngine/us-hank-model"
        ) from e
    return us_hank, model, one_asset, distributional


def _hank_module(variant: str):
    _, model, one_asset, _ = _import_us_hank()
    return {"two_asset": model, "one_asset": one_asset}[variant]


def _hank_solved(variant: str, T: int = HANK_T):
    """(steady state, GE jacobian) for a variant, cached at module level."""
    key = (variant, int(T))
    if key in _HANK_CACHE:
        return _HANK_CACHE[key]
    mod = _hank_module(variant)
    ss = mod.solve_steady_state()
    G = mod.solve_jacobian(ss, T=int(T))
    _HANK_CACHE[key] = (ss, G)
    return ss, G


def _hank_check_kind(kind: str, variant: str) -> None:
    if variant not in HANK_VARIANTS:
        raise ValueError(
            f"variant must be one of {HANK_VARIANTS}, got {variant!r}. "
            "'two_asset' is the Auclert-Bardóczy-Rognlie-Straub (2021) paper "
            "model; 'one_asset' is a fast no-capital variant (monetary and "
            "productivity shocks only)."
        )
    entry = _HANK_KIND_INDEX.get(kind)
    if entry is None:
        known = ", ".join(sorted(_HANK_KIND_INDEX))
        raise ValueError(
            f"kind must be one of: {known}; got {kind!r}. There is "
            "deliberately no transfer or tax-rate shock: the model's labor "
            "tax is endogenous (the fiscal block balances the budget), so no "
            "such exogenous instrument exists in the DAG — inventing one "
            "would produce plausible-looking wrong numbers."
        )
    if variant not in entry["variants"]:
        raise ValueError(
            f"kind {kind!r} is not available in the {variant!r} variant "
            f"(available there: monetary, productivity). The one-asset DAG "
            "has no exogenous G — use variant='two_asset' for fiscal shocks."
        )


def hank_list_shocks() -> list[dict]:
    """Shockable HANK instruments with descriptions, units and variants."""
    return [dict(k) for k in HANK_SHOCK_KINDS]


def hank_shock(
    kind: str,
    size: float,
    persistence: float = 0.9,
    horizon: int = HANK_DEFAULT_HORIZON,
    variant: str = "two_asset",
    include_distribution: bool = False,
    name: str | None = None,
) -> dict:
    """Run one stylized HANK shock experiment and return the IRFs.

    The HANK analogue of frbus_shock: a raw shock in model units, no
    PolicyEngine reform translation (there is deliberately no such bridge —
    the model scores stylized shocks, not detailed tax reforms). The shock is
    an AR(1) path ``size * persistence**t``; responses are LINEAR (first-order
    sequence-space) deviations around the calibrated steady state, so they
    scale exactly with ``size`` and carry no state-dependence.

    ``include_distribution`` (two_asset only) adds steady-state MPC statistics
    and the impact consumption response by total-wealth quartile — a
    first-order approximation from steady-state policies, capturing the
    MPC-heterogeneity channel only, not full household-level dynamics.

    Alongside the package's Y/C/I/pi/r, the result surfaces the pre-tax
    real wage ``w`` and labor ``N`` IRFs (% deviations from steady state),
    computed from the same GE Jacobian — the inputs hank_shock_incidence
    builds its household-level overlay on.

    First call per variant pays the steady-state (~13s) + jacobian (~5s)
    solves; both are cached, so every later call is effectively instant.
    """
    _hank_check_kind(kind, variant)
    horizon = int(horizon)
    if not 1 <= horizon <= HANK_T:
        raise ValueError(f"horizon must be between 1 and {HANK_T}, got {horizon}")
    persistence = float(persistence)
    if not 0.0 <= persistence < 1.0:
        raise ValueError(
            f"persistence must be in [0, 1) — the shock path is "
            f"size * persistence**t and must decay — got {persistence}"
        )
    if include_distribution and variant != "two_asset":
        raise ValueError(
            "include_distribution requires variant='two_asset': the one-asset "
            "variant has no illiquid asset, so the liquid/total-wealth "
            "distributional cuts are not defined for it."
        )

    mod = _hank_module(variant)
    ss, G = _hank_solved(variant)
    irf = mod.shock(kind, float(size), persistence, T=HANK_T, ss=ss, G_jac=G)

    # The package's shock() returns Y/C/I/pi/r only; surface the pre-tax
    # real wage w and labor N the same way it computes the others — from
    # the GE Jacobian and the exogenous path — as % deviations from steady
    # state. Both variants expose w and N (w is a solved unknown; N is a
    # block output); if an upstream change ever drops one, the series is
    # omitted rather than invented, and from_hank_result errors clearly.
    for extra in ("w", "N"):
        if extra not in irf:
            # Membership checks, not a broad try/except: a genuine
            # computation bug (shape mismatch, degenerate steady state) must
            # raise here, not surface later as a confusing "series missing".
            if (
                extra not in G
                or irf["shock_input"] not in G[extra]
                or extra not in ss
            ):
                continue
            if not float(ss[extra]):
                # Present but zero is a calibration anomaly, not an absent
                # series — surface it rather than masking it as "omitted".
                raise RuntimeError(
                    f"HANK steady state has {extra} == 0; refusing to "
                    "divide a wage/labor IRF by a degenerate steady state — "
                    "inspect the calibration"
                )
            irf[extra] = (
                100.0 * (G[extra][irf["shock_input"]] @ irf["shock"])
                / float(ss[extra])
            )

    series_names = [v for v in HANK_HEADLINE if v in irf]
    series = {
        v: [round(float(x), 6) for x in irf[v][:horizon]] for v in series_names
    }
    shock_path = [round(float(x), 8) for x in irf["shock"][:horizon]]
    rows = [
        {"quarter": t, **{v: series[v][t] for v in series_names},
         "shock": shock_path[t]}
        for t in range(horizon)
    ]

    def _peak(values):
        best = max(range(len(values)), key=lambda i: abs(values[i]))
        return {"value": values[best], "quarter": best}

    peaks = {v: _peak(series[v]) for v in series_names}

    entry = _HANK_KIND_INDEX[kind]
    result = {
        "name": name or f"{kind} shock {size:+g} (persistence {persistence:g})",
        "provenance": _provenance(
            model_id="us-hank",
            distribution="us-hank-model",
            data_vintage="Auclert-Bardóczy-Rognlie-Straub (2021) calibration",
            baseline="calibrated steady state (production grids)",
        ),
        "kind": kind,
        "shock_input": irf["shock_input"],
        "size": float(size),
        "units": entry["units"],
        "persistence": persistence,
        "horizon": horizon,
        "variant": variant,
        "framing": (
            "Validated replication of Auclert, Bardóczy, Rognlie & Straub "
            "(Econometrica 2021); stylized shocks around a calibrated steady "
            "state; VAR-free sequence-space HANK; NOT a forecaster and does "
            "not score detailed tax reforms; responses are linear/first-order."
        ),
        "series_meaning": {v: HANK_HEADLINE[v] for v in series_names},
        "results": rows,
        "peaks": peaks,
    }

    # Same misuse guard as frbus_shock: a converged run in which nothing moves
    # is a mis-specified experiment (e.g. size=0), not a finding.
    if all(abs(peaks[v]["value"]) < 1e-12 for v in series_names):
        result["warning"] = (
            f"every response is numerically zero: the {size:+g} {kind} shock "
            "did not move the model. Treat this as a mis-specified experiment "
            "(check the size and its units in hank_summary), not as evidence "
            "of no effect."
        )

    if include_distribution:
        _, _, _, distributional = _import_us_hank()
        result["distributional"] = {
            "note": (
                "FIRST-ORDER APPROXIMATION from steady-state policies: the "
                "by-quantile impact consumption response allocates the "
                "aggregate response in proportion to each group's liquid-asset "
                "MPC. It captures the MPC-heterogeneity channel, not full "
                "household-level dynamics."
            ),
            "aggregate_quarterly_mpc_liquid": round(
                float(distributional.aggregate_mpc(ss)), 4
            ),
            "mpc_by_liquid_quartile": {
                k: round(float(v), 4)
                for k, v in distributional.mpc_by_liquid_quartile(ss).items()
            },
            "hand_to_mouth_share": round(
                float(distributional.hand_to_mouth_share(ss)), 4
            ),
            "impact_consumption_response_pct_by_wealth_quartile": {
                k: round(float(v), 4)
                for k, v in distributional.consumption_response_by_wealth_quantile(
                    ss, irf
                ).items()
            },
        }
    return result


def hank_summary() -> dict:
    """Static metadata and validation provenance for the US HANK member.

    No solve: instant, like frbus_summary. States what the model is, the
    available shock kinds and variants, and the honest scope limits.
    """
    out = {
        "model": "US two-asset HANK (sequence-space)",
        "implementation": "us_hank — PolicyEngine/us-hank-model, built on the "
                          "authors' sequence-jacobian toolkit at the paper's "
                          "production grids (nB=50, nA=70, nK=50)",
        "upstream": "Auclert, Bardóczy, Rognlie & Straub, 'Using the "
                    "Sequence-Space Jacobian to Solve and Estimate "
                    "Heterogeneous-Agent Models', Econometrica 2021",
        "package_version": _package_version("us-hank-model"),
        "framing": (
            "Validated replication; stylized shocks; VAR-free sequence-space "
            "HANK; not a forecaster; distributional outputs are first-order "
            "approximations."
        ),
        "variants": {
            "two_asset": "the paper model: liquid + illiquid assets, sticky "
                         "prices and wages, capital; all three shock kinds",
            "one_asset": "fast textbook variant: no capital (no investment "
                         "IRF), no exogenous G; monetary and productivity "
                         "shocks only",
        },
        "shock_kinds": hank_list_shocks(),
        "no_tax_or_transfer_instrument": (
            "The labor tax rate is endogenous — the fiscal block balances the "
            "government budget (tax = (r*Bg + G)/(w*N)) — so a fiscal_spending "
            "shock is implicitly tax-financed and there is NO transfer or "
            "tax-rate shock kind."
        ),
        "solution_method": "first-order (linear) impulse responses via the "
                           "general-equilibrium sequence-space Jacobian "
                           f"(T={HANK_T}); responses scale exactly with the "
                           "shock size",
        "runtime": "steady state ~13s and jacobian ~5s on first use per "
                   "variant, both cached in-process; IRFs are then instant",
        "validation": {
            "suite": "the model repo's replication suite gates the steady-state "
                     "calibration targets, market clearing, and shock-response "
                     "signs/magnitudes against the published paper results",
            "note": "a replication gate, not a forecast-accuracy claim: no "
                    "predictive validation exists or is claimed for this model",
        },
        "reform_bridge": (
            "NONE. There is deliberately no PolicyEngine-reform bridge for "
            "the HANK member: it scores stylized aggregate shocks, not "
            "detailed tax reforms, and no mapping exists from a PolicyEngine "
            "US reform to its three exogenous instruments. score_reform "
            "rejects model='hank'; hank_shock is the supported entry point."
        ),
    }
    out["provenance"] = _provenance(
        model_id="us-hank",
        distribution="us-hank-model",
        data_vintage="Auclert-Bardóczy-Rognlie-Straub (2021) calibration",
        baseline="calibrated steady state (production grids)",
    )
    return out


# ---------------------------------------------------------------------------
# UK SVAR adapters
# ---------------------------------------------------------------------------

# In-process caches. Estimation + identification is the slow part; keyed by
# draws. Forecast results keyed by (horizons, draws).
_ESTIMATION_CACHE: dict[int, dict] = {}
_FORECAST_CACHE: dict[tuple[int, int], dict] = {}
_SHOCKS_CACHE: dict[int, dict] = {}


def _covid_dummies(index) -> np.ndarray:
    import pandas as pd

    quarters = pd.period_range("2020Q1", "2021Q2", freq="Q")
    D = np.zeros((len(index), len(quarters)))
    for j, q in enumerate(quarters):
        D[:, j] = (index == q).astype(float)
    return D


# Estimation window for the hosted SVAR (start of Great-Moderation sample;
# end held fixed so hosted results only move on a deliberate refresh). The
# provenance strings are derived from the actual df_est index, never retyped.
#
# 2026-07-24 refresh: bumped 2023Q2 -> 2025Q1 (126 -> 133 observations) to match
# the sample boe-var-model's production replication now runs on. Held one
# quarter short of the 2026Q1 data edge, matching the repo, so the forecast
# origin sits outside the estimation sample.
_SVAR_EST_START = "1992Q1"
_SVAR_EST_END = "2025Q1"

# Default posterior draws for hosted calls. Re-measured on the 1992Q1-2025Q1
# estimation sample (seed 0), since the longer sample tightens the posterior
# and lowers the sign-restriction acceptance rate: draws=500 -> 35 accepted,
# ESS 13.6; 1000 -> 69, ESS 31.5; 2000 -> 135, ESS 65.3; 3500 -> 233,
# ESS 101.4. Acceptance is ~6.8% and ESS ~3.3% of draws (was ~8% and ~3% on
# the old 2023Q2 sample), so 2000 remains the smallest default that clears
# the 100-accepted-draws reliability threshold -- 1000 would not (69).
# Full ESS >= 100 still needs ~3500 draws; a `warnings` entry flags the
# residual ESS shortfall honestly instead of hiding it. First-call runtime is
# a couple of minutes end to end and results are cached in-process.
_SVAR_DEFAULT_DRAWS = 2000
_SVAR_MIN_DRAWS = 50
_SVAR_MAX_DRAWS = 10_000
_SVAR_MIN_HORIZONS = 1
_SVAR_MAX_HORIZONS = 40
_OBR_MIN_PERIODS = 1
_OBR_MAX_PERIODS = 40


def _bounded_int(name: str, value: int, minimum: int, maximum: int) -> int:
    """Normalize a public integer input and reject unsafe work requests."""
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if normalized != value:
        raise ValueError(f"{name} must be an integer")
    if not minimum <= normalized <= maximum:
        raise ValueError(
            f"{name} must be between {minimum} and {maximum}; got {value}"
        )
    return normalized


def _estimate(draws: int = _SVAR_DEFAULT_DRAWS, seed: int = 0) -> dict:
    """Estimate the BVAR and identify structural shocks. Cached by draws."""
    if draws in _ESTIMATION_CACHE:
        return _ESTIMATION_CACHE[draws]
    analysis, forecast, BVAR, load_data, identify, ess = _import_boe_var()
    import pandas as pd

    rng = np.random.default_rng(seed)
    df_full = load_data()
    df_full = df_full.loc[df_full.index >= pd.Period(_SVAR_EST_START, "Q")]
    df_est = df_full.loc[df_full.index <= pd.Period(_SVAR_EST_END, "Q")]
    dummies_est = _covid_dummies(df_est.index)
    dummies_full = _covid_dummies(df_full.index)

    model = BVAR(df_est.to_numpy(dtype=float), lags=4, dummies=dummies_est)
    posterior = model.sample_posterior(draws, seed=seed)
    triples = identify(posterior, rng=rng)
    if not triples:
        raise RuntimeError(
            f"No accepted identified draws out of {draws}; raise draws."
        )
    pairs = [(d, B) for d, B, _ in triples]
    w = np.array([t[2] for t in triples], dtype=float)
    try:
        from boe_var.identification import weak_inference_warnings
        warnings = weak_inference_warnings(len(pairs), float(ess(w)), draws)
    except ImportError:  # older boe_var without the helper
        warnings = []
        if len(pairs) < 100 or float(ess(w)) < 100.0:
            warnings.append(
                f"Weak inference: {len(pairs)} accepted draws, "
                f"importance-weight ESS {float(ess(w)):.1f} (thresholds "
                "100/100); bands may be noisy. Re-run with a higher draw "
                "count."
            )
    out = {
        "df_full": df_full,
        "y_full": df_full.to_numpy(dtype=float),
        "dummies_full": dummies_full,
        "pairs": pairs,
        "weights": w,
        "n_accepted": len(pairs),
        "n_draws": draws,
        "ess": float(ess(w)),
        "estimation_sample": f"{df_est.index[0]}-{df_est.index[-1]}",
        "warnings": warnings,
        "rng": rng,
        "modules": (analysis, forecast),
    }
    _ESTIMATION_CACHE[draws] = out
    return out


def svar_forecast(horizons: int = 12,
                  draws: int = _SVAR_DEFAULT_DRAWS) -> dict:
    """YoY UK GDP growth and CPI inflation forecast from the UK SVAR.

    Returns median and 68/90 percent bands per future quarter. Bands combine
    parameter and shock uncertainty. Cached in-process by (horizons, draws).
    """
    horizons = _bounded_int(
        "horizons", horizons, _SVAR_MIN_HORIZONS, _SVAR_MAX_HORIZONS
    )
    draws = _bounded_int("draws", draws, _SVAR_MIN_DRAWS, _SVAR_MAX_DRAWS)
    key = (horizons, draws)
    if key in _FORECAST_CACHE:
        return _FORECAST_CACHE[key]
    est = _estimate(draws)
    analysis, forecast = est["modules"]
    y_full = est["y_full"]
    rng = np.random.default_rng(1)

    tail = y_full[-4:]  # last 4 actual levels for the YoY transform
    yoy_paths, pw = [], []
    n_paths = 5
    for i, (d, _B) in enumerate(est["pairs"]):
        for _ in range(n_paths):
            path = forecast.sample_forecast(d, y_full, horizons=horizons, rng=rng)
            yoy_paths.append(forecast.yoy(np.vstack([tail, path])))
            pw.append(est["weights"][i])
    bands = analysis.aggregate(yoy_paths, weights=np.asarray(pw))

    last_q = est["df_full"].index[-1]
    quarters = [str(last_q + h) for h in range(1, horizons + 1)]

    def _series(idx: int) -> list[dict]:
        return [
            {
                "quarter": quarters[h],
                "median": round(float(bands["median"][h, idx]), 3),
                "lo68": round(float(bands["lo68"][h, idx]), 3),
                "hi68": round(float(bands["hi68"][h, idx]), 3),
                "lo90": round(float(bands["lo90"][h, idx]), 3),
                "hi90": round(float(bands["hi90"][h, idx]), 3),
            }
            for h in range(horizons)
        ]

    out = {
        "model": "UK SVAR (BVAR, sign-identified)",
        "provenance": _provenance(
            model_id="boe-svar",
            distribution="boe_var",
            data_vintage=f"conditioned through {last_q}",
            baseline=f"unconditional forecast from {last_q}",
            estimation_sample=est["estimation_sample"],
        ),
        "forecast_origin": str(last_q),
        "horizons": horizons,
        "draws": draws,
        "accepted_draws": est["n_accepted"],
        "ess": round(est["ess"], 1),
        "warnings": list(est["warnings"]),
        "units": "YoY percent (4-quarter log difference of 100*log levels)",
        "gdp_growth_yoy": _series(list(est["df_full"].columns).index(_COL_GDP)),
        "cpi_inflation_yoy": _series(list(est["df_full"].columns).index(_COL_CPI)),
    }
    _FORECAST_CACHE[key] = out
    return out


def svar_latest_shocks(draws: int = _SVAR_DEFAULT_DRAWS) -> dict:
    """P(sign) of the 6 identified structural shocks in the latest data quarter."""
    key = _bounded_int("draws", draws, _SVAR_MIN_DRAWS, _SVAR_MAX_DRAWS)
    if key in _SHOCKS_CACHE:
        return _SHOCKS_CACHE[key]
    est = _estimate(key)
    analysis, forecast = est["modules"]
    from boe_var.analysis import SHOCK_NAMES

    y_full, dummies_full = est["y_full"], est["dummies_full"]

    resid_cache: dict[int, np.ndarray] = {}

    def resid_fn(draw):
        k = id(draw)
        if k not in resid_cache:
            resid_cache[k] = forecast.reduced_form_residuals(draw, y_full, dummies_full)
        return resid_cache[k]

    dist = forecast.shock_distribution_T(est["pairs"], resid_fn, weights=est["weights"])
    last_q = str(est["df_full"].index[-1])

    # Canonical upstream schema (boe_var's own index lists), not a label
    # heuristic; the contract test asserts SHOCK_NAMES stays aligned with it.
    from boe_var.analysis import UK_SHOCKS, WORLD_SHOCKS

    identified = sorted(WORLD_SHOCKS + UK_SHOCKS)

    shocks = []
    for j in identified:
        p = float(dist["p_pos"][j])
        p_dom = max(p, 1 - p)
        sign = "positive" if p >= 0.5 else "negative"
        conf = "clearly" if p_dom >= 0.8 else ("probably" if p_dom >= 0.65 else "ambiguously")
        shocks.append(
            {
                "shock": SHOCK_NAMES[j],
                "p_positive": round(p, 3),
                "p_negative": round(1 - p, 3),
                "reading": f"{SHOCK_NAMES[j]} shock was {conf} {sign} in {last_q} "
                           f"(P({'+' if p >= 0.5 else '−'}) = {p_dom:.2f}).",
            }
        )
    out = {
        "quarter": last_q,
        "provenance": _provenance(
            model_id="boe-svar",
            distribution="boe_var",
            data_vintage=f"conditioned through {last_q}",
            baseline="identified structural shocks",
            estimation_sample=est["estimation_sample"],
        ),
        "draws": key,
        "accepted_draws": est["n_accepted"],
        "ess": round(est["ess"], 1),
        "warnings": list(est["warnings"]),
        "shocks": shocks,
    }
    _SHOCKS_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# PolicyEngine microsimulation adapters (household calculator)
# ---------------------------------------------------------------------------
#
# policyengine imports its full UK+US country models on first import (~20s),
# so it is imported lazily inside the adapters, never at module level.
# Population-level scoring lives in pe_population_impact below; UK data
# requires a HUGGING_FACE_TOKEN for the first download.

def _import_pe():
    try:
        import policyengine as pe
    except ImportError as e:
        raise ImportError(
            "The `policyengine` package is not importable. "
            "Install it with: pip install policyengine"
        ) from e
    return pe


# Curated well-known reform parameters. Every path below has been verified to
# resolve through a calculate_household(reform=...) run.
PE_PARAMETERS = [
    {
        "country": "uk",
        "path": "gov.hmrc.income_tax.rates.uk[0].rate",
        "description": "Income tax basic rate (England/Wales/NI)",
        "unit": "decimal rate",
    },
    {
        "country": "uk",
        "path": "gov.hmrc.income_tax.rates.uk[1].rate",
        "description": "Income tax higher rate",
        "unit": "decimal rate",
    },
    {
        "country": "uk",
        "path": "gov.hmrc.income_tax.allowances.personal_allowance.amount",
        "description": "Income tax personal allowance",
        "unit": "GBP per year",
    },
    {
        "country": "uk",
        "path": "gov.dwp.universal_credit.means_test.reduction_rate",
        "description": "Universal Credit taper (earnings reduction) rate",
        "unit": "decimal rate",
    },
    {
        "country": "uk",
        "path": "gov.hmrc.national_insurance.class_1.rates.employee.main",
        "description": "Employee National Insurance main rate",
        "unit": "decimal rate",
    },
    {
        "country": "uk",
        "path": "gov.hmrc.child_benefit.amount.eldest",
        "description": "Child Benefit weekly amount for the eldest child",
        "unit": "GBP per week",
    },
    {
        "country": "uk",
        "path": "gov.hmrc.cgt.basic_rate",
        "description": "Capital gains tax rate for basic-rate taxpayers",
        "unit": "decimal rate",
        "note": "valid reform path, but calculate_household does not compute CGT: household results will not move. Use with population_reform_impact / pe_population_impact.",
    },
    {
        "country": "uk",
        "path": "gov.hmrc.cgt.higher_rate",
        "description": "Capital gains tax rate for higher/additional-rate taxpayers",
        "unit": "decimal rate",
        "note": "valid reform path, but calculate_household does not compute CGT: household results will not move. Use with population_reform_impact / pe_population_impact.",
    },
    {
        "country": "uk",
        "path": "gov.hmrc.cgt.annual_exempt_amount",
        "description": "Capital gains tax annual exempt amount",
        "unit": "GBP per year",
        "note": "valid reform path, but calculate_household does not compute CGT: household results will not move. Use with population_reform_impact / pe_population_impact.",
    },
    {
        "country": "us",
        "path": "gov.irs.credits.ctc.amount.base[0].amount",
        "description": "Child Tax Credit base amount per child",
        "unit": "USD per year",
    },
    {
        "country": "us",
        "path": "gov.irs.credits.ctc.amount.adult_dependent",
        "description": "CTC amount for adult dependents (credit for other dependents)",
        "unit": "USD per year",
    },
    {
        "country": "us",
        "path": "gov.irs.income.bracket.rates.2",
        "description": "Federal income tax rate (bracket 2 — the 12% bracket)",
        "unit": "decimal rate",
    },
    {
        "country": "us",
        "path": "gov.irs.deductions.standard.amount.JOINT",
        "description": "Standard deduction for joint filers",
        "unit": "USD per year",
    },
]


def _pe_current_value(param):
    """The parameter value in force today, from upstream's own value history.

    The value with the latest start_date that is <= today. end_date is
    deliberately ignored: upstream builds parameter_values from a
    newest-first values_list, so each entry's end_date is the chronologically
    *previous* instant, not a validity end. "Today" is the server's local
    date (date.today()): around midnight a UK/US effective-date boundary can
    differ by a few hours — acceptable for listing metadata.
    """
    from datetime import date

    return _pe_value_at(param, date.today())


def _pe_value_at(param, on_date):
    """The parameter value in force on ``on_date`` (same rules as
    _pe_current_value: latest start_date <= on_date, end_date ignored)."""

    def _d(v):
        return v.date() if hasattr(v, "date") else v

    best_start, current = None, None
    for pv in param.parameter_values:
        start = _d(pv.start_date) if pv.start_date else None
        if start is not None and start <= on_date and (
            best_start is None or start > best_start
        ):
            best_start, current = start, pv.value
    return current


def pe_list_common_parameters(resolve: bool = True) -> list[dict]:
    """Curated PolicyEngine reform parameters, enriched from the live model.

    The path list is curated here, but baseline values, labels, and units are
    resolved from the policyengine package's own parameter tree at call time,
    so they can never go stale. A path that no longer resolves upstream is
    returned with ``"live": False`` and an explicit ``"live_error"`` instead
    of a silently wrong entry. ``resolve=False`` skips the (heavy) policyengine
    import and returns just the static catalogue.
    """
    out = [dict(p) for p in PE_PARAMETERS]
    if not resolve:
        return out
    try:
        pe = _import_pe()
    except Exception as e:
        # policyengine missing or its import broken: return the static
        # catalogue rather than failing the whole listing, but say so.
        for p in out:
            p["live"] = False
            p["live_error"] = f"{type(e).__name__}: {e}"
        return out
    for p in out:
        try:
            # getattr can return None on a base-only policyengine install
            # (no country models), so the whole lookup is guarded, not just
            # the parameter resolution.
            model = getattr(pe, p["country"]).model
            param = model.get_parameter(p["path"])
        except Exception as e:
            p["live"] = False
            p["live_error"] = f"{type(e).__name__}: {e}"
            continue
        p["live"] = True
        if param.label:
            p["label"] = param.label
        if param.unit:
            p["upstream_unit"] = param.unit
        p["baseline_value"] = _pe_jsonify_exact(_pe_current_value(param))
    return out


def _pe_jsonify_exact(value):
    """numpy scalar -> python scalar, NO rounding: policy values are exact
    (the display-rounding _pe_jsonify below would turn NI 0.1325 into 0.13)."""
    if isinstance(value, np.generic):
        return value.item()
    return value


def _pe_jsonify(value):
    """numpy scalar -> python scalar; round floats for readability."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return round(value, 2)
    return value


def _pe_entity_dict(mapping) -> dict:
    return {k: _pe_jsonify(v) for k, v in mapping.items()}


# ---------------------------------------------------------------------------
# Reform-dict validation (shared by every tool that accepts a reform)
# ---------------------------------------------------------------------------
#
# PolicyEngine's compile_reform (policyengine.tax_benefit_models.common.reform)
# accepts exactly two shapes per parameter path:
#
#   {"gov.path": 0.21}                  -> applied from {year}-01-01
#   {"gov.path": {"2026-01-01": 0.21}}  -> applied from that effective date
#
# Each (date, value) pair becomes a ParameterValue with start_date parsed by
# datetime.strptime(key, "%Y-%m-%d") and end_date=None — i.e. values are
# OPEN-ENDED with no expiry. A "start.end" range key therefore fails in
# strptime ("unconverted data remains: .2029-12-31"), and there is no
# supported way to express an end date: silently dropping the end would score
# a permanent reform while the caller asked for a temporary one. So ranges are
# rejected up front with an explicit explanation rather than faked.

_REFORM_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REFORM_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[.:](\d{4}-\d{2}-\d{2})$")

_REFORM_SHAPES_HELP = (
    "Supported reform shapes (per parameter path):\n"
    '  - flat value:      {"gov.hmrc.income_tax.rates.uk[0].rate": 0.21}\n'
    "  - effective date:  "
    '{"gov.hmrc.income_tax.rates.uk[0].rate": {"2026-01-01": 0.21}}\n'
    "A flat value takes effect from 1 January of the simulation year; a dated "
    "value takes effect from that date. Values are open-ended (no end date). "
    "Call list_reform_parameters for verified parameter paths and units."
)


def validate_reform(reform, *, argument: str = "reform") -> dict:
    """Validate a reform dict and return it normalised to {path: {date: value}}.

    Raises ValueError with an actionable message naming the supported shapes
    for anything else, so callers never see a raw pydantic/strptime dump.
    """
    if reform is None or (isinstance(reform, dict) and not reform):
        raise ValueError(
            f"{argument} must be a non-empty {{parameter_path: value}} dict.\n"
            + _REFORM_SHAPES_HELP
        )
    if not isinstance(reform, dict):
        raise ValueError(
            f"{argument} must be a non-empty {{parameter_path: value}} "
            f"dict, got {type(reform).__name__}.\n"
            + _REFORM_SHAPES_HELP
        )

    normalised: dict[str, object] = {}
    for path, spec in reform.items():
        if not isinstance(path, str) or not path:
            raise ValueError(
                f"{argument} keys must be parameter-path strings, got "
                f"{path!r}.\n" + _REFORM_SHAPES_HELP
            )
        if not isinstance(spec, dict):
            if isinstance(spec, (int, float, bool)):
                # Left as a scalar: PolicyEngine applies it from
                # {year}-01-01, which is the documented behaviour.
                normalised[path] = spec
                continue
            raise ValueError(
                f"{argument}['{path}'] must be a number or a "
                f"{{date: value}} dict, got {type(spec).__name__} "
                f"({spec!r}).\n" + _REFORM_SHAPES_HELP
            )
        if not spec:
            raise ValueError(
                f"{argument}['{path}'] is an empty dict; give it a value or a "
                "{date: value} mapping.\n" + _REFORM_SHAPES_HELP
            )
        dated: dict[str, object] = {}
        for key, value in spec.items():
            key = str(key)
            range_match = _REFORM_RANGE_RE.match(key)
            if range_match:
                start, end = range_match.groups()
                raise ValueError(
                    f"{argument}['{path}'] uses the date-range key '{key}', "
                    "which the PolicyEngine reform-dict API does "
                    "not support: a reform value is applied from an effective "
                    "date and stays in force indefinitely (end_date is always "
                    f"None), so the end date {end} cannot be expressed.\n"
                    f"Use the start date alone to score the reform as "
                    f'permanent: {{"{start}": {value!r}}}. To approximate a '
                    "time-limited reform, score the affected years "
                    "individually (e.g. one population_reform_impact call per "
                    "year in the window) and treat later years as baseline.\n"
                    + _REFORM_SHAPES_HELP
                )
            if not _REFORM_DATE_RE.match(key):
                raise ValueError(
                    f"{argument}['{path}'] has the invalid date key '{key}'. "
                    "Effective dates must be YYYY-MM-DD.\n"
                    + _REFORM_SHAPES_HELP
                )
            if not isinstance(value, (int, float, bool)):
                raise ValueError(
                    f"{argument}['{path}']['{key}'] must be a number, got "
                    f"{type(value).__name__} ({value!r}).\n"
                    + _REFORM_SHAPES_HELP
                )
            dated[key] = value
        normalised[path] = dated
    return normalised


def _validate_country(country, *, argument: str = "country") -> str:
    """Validate the country argument with an actionable message.

    Deliberately has NO default: 'uk' and 'us' are different tax-benefit
    models, and defaulting would silently score the wrong country for a US
    household. pe_population_impact keeps its historical country='uk' default
    for backwards compatibility; the household tools require it explicitly.
    """
    if country is None or country == "":
        raise ValueError(
            f"{argument} is required and must be 'uk' or 'us' — there is no "
            "default, because the two are different tax-benefit models and "
            "guessing would silently score the wrong country. Example: "
            'country="uk".'
        )
    if not isinstance(country, str):
        raise ValueError(
            f"{argument} must be the string 'uk' or 'us', got "
            f"{type(country).__name__} ({country!r})."
        )
    country = country.lower()
    if country not in ("uk", "us"):
        raise ValueError(f"{argument} must be 'uk' or 'us', got {country!r}")
    return country


def _validate_people(people, *, argument: str = "people") -> list[dict]:
    """Validate the people argument with an actionable message."""
    if not people:
        raise ValueError(
            f"{argument} is required: a non-empty list of person dicts with "
            "ANNUAL money amounts, e.g. "
            '[{"age": 35, "employment_income": 50000}, {"age": 5}].'
        )
    if not isinstance(people, list) or not all(
        isinstance(p, dict) for p in people
    ):
        raise ValueError(
            f"{argument} must be a list of person dicts, e.g. "
            '[{"age": 35, "employment_income": 50000}].'
        )
    return people


US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
    "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA "
    "WV WI WY".split()
)


def _validate_us_household(household):
    """Catch US household dicts that would silently be ignored.

    PolicyEngine US takes the state as household-level ``state_code_str``
    and defaults to CA when it is absent. A misspelled key (``state_code``)
    or a bad code therefore produced a silently-wrong California answer
    instead of an error.
    """
    if household is None:
        return None
    if not isinstance(household, dict):
        raise ValueError(
            "household must be a dict, e.g. {\"state_code_str\": \"CA\"}."
        )
    household = dict(household)
    if "state_code" in household and "state_code_str" not in household:
        raise ValueError(
            "US household uses the key 'state_code_str', not 'state_code'. "
            'Example: {"state_code_str": "TX"}. (Passing the wrong key would '
            "silently fall back to the CA default and return the wrong "
            "state income tax.)"
        )
    state = household.get("state_code_str")
    if state is not None:
        if not isinstance(state, str) or state.upper() not in US_STATE_CODES:
            raise ValueError(
                f"state_code_str must be a two-letter US state or DC code, "
                f"got {state!r}. Example: {{\"state_code_str\": \"TX\"}}."
            )
        household["state_code_str"] = state.upper()
    return household


def _pe_run(country, people, year, reform, benunit, tax_unit, household):
    # Validate country before importing PolicyEngine so bad input fails fast
    # with a clear ValueError even where PE is not installed (matches
    # pe_population_impact and lets the wiring tests run without the heavy dep).
    country = _validate_country(country)
    people = _validate_people(people)
    if reform is not None:
        reform = validate_reform(reform)
    if country == "us":
        household = _validate_us_household(household)
    pe = _import_pe()
    if country == "uk":
        return pe.uk.calculate_household(
            people=people, benunit=benunit, household=household,
            year=int(year), reform=reform,
        )
    if country == "us":
        return pe.us.calculate_household(
            people=people, tax_unit=tax_unit, household=household,
            year=int(year), reform=reform,
        )
    raise ValueError(f"country must be 'uk' or 'us', got {country!r}")


def _pe_summary(country, result) -> dict:
    """Key headline outputs, robust across UK/US result shapes."""
    hh = result.household
    if country == "uk":
        return {
            "income_tax_by_person": [_pe_jsonify(p.income_tax) for p in result.person],
            "national_insurance_by_person": [
                _pe_jsonify(p.national_insurance) for p in result.person
            ],
            "household_net_income": _pe_jsonify(hh.hbai_household_net_income),
            "household_tax": _pe_jsonify(hh.household_tax),
            "household_benefits": _pe_jsonify(hh.household_benefits),
            "universal_credit": _pe_jsonify(result.benunit.universal_credit),
            "child_benefit": _pe_jsonify(result.benunit.child_benefit),
        }
    return {
        "federal_income_tax": _pe_jsonify(result.tax_unit.income_tax),
        "employee_payroll_tax": _pe_jsonify(result.tax_unit.employee_payroll_tax),
        "state_income_tax": _pe_jsonify(result.tax_unit.state_income_tax),
        "ctc": _pe_jsonify(result.tax_unit.ctc),
        "eitc": _pe_jsonify(result.tax_unit.eitc),
        "household_net_income": _pe_jsonify(hh.household_net_income),
        "household_tax": _pe_jsonify(hh.household_tax),
        "household_benefits": _pe_jsonify(hh.household_benefits),
    }


def pe_household(
    country: str,
    people: list[dict],
    year: int = 2026,
    reform: dict | None = None,
    benunit: dict | None = None,
    tax_unit: dict | None = None,
    household: dict | None = None,
) -> dict:
    """Calculate taxes and benefits for a custom household with PolicyEngine.

    country: 'uk' or 'us'. people: list of person dicts, e.g.
    [{"age": 35, "employment_income": 50000}]. reform: optional
    {"gov.param.path": value} dict. UK groups people into a benunit; US uses
    tax_unit (e.g. {"filing_status": "SINGLE"}) and household
    (e.g. {"state_code_str": "CA"}; defaults to CA if omitted).
    """
    country = _validate_country(country)
    result = _pe_run(country, people, year, reform, benunit, tax_unit, household)
    out = {
        "country": country,
        "year": int(year),
        "currency": "GBP" if country == "uk" else "USD",
        "reform": dict(reform) if reform else None,
        "summary": _pe_summary(country, result),
        "person": [_pe_entity_dict(p) for p in result.person],
        "household": _pe_entity_dict(result.household),
        "provenance": _provenance(
            model_id="pe-microsim",
            distribution="policyengine-uk" if country == "uk" else "policyengine-us",
            data_vintage=f"{year} policy parameters",
            baseline="current law" if not reform else "submitted reform",
        ),
    }
    if country == "uk":
        out["benunit"] = _pe_entity_dict(result.benunit)
    else:
        out["tax_unit"] = _pe_entity_dict(result.tax_unit)
        out["spm_unit"] = _pe_entity_dict(result.spm_unit)
    return out


def pe_household_impact(
    country: str,
    people: list[dict],
    reform: dict,
    year: int = 2026,
    benunit: dict | None = None,
    tax_unit: dict | None = None,
    household: dict | None = None,
) -> dict:
    """Baseline vs reform for one household: what does this reform do to
    this family? Returns baseline and reform summaries plus their deltas."""
    reform = validate_reform(reform)
    country = _validate_country(country)
    people = _validate_people(people)
    base = _pe_summary(
        country, _pe_run(country, people, year, None, benunit, tax_unit, household)
    )
    ref = _pe_summary(
        country, _pe_run(country, people, year, reform, benunit, tax_unit, household)
    )

    def _delta(b, r):
        if isinstance(b, list):
            return [round(rv - bv, 2) for bv, rv in zip(b, r)]
        if isinstance(b, (int, float)) and isinstance(r, (int, float)):
            return round(r - b, 2)
        return None

    deltas = {k: _delta(base[k], ref[k]) for k in base}
    return {
        "country": country,
        "year": int(year),
        "currency": "GBP" if country == "uk" else "USD",
        "reform": dict(reform),
        "baseline": base,
        "with_reform": ref,
        "change": deltas,
        "net_income_change": deltas.get("household_net_income"),
        "provenance": _provenance(
            model_id="pe-microsim",
            distribution="policyengine-uk" if country == "uk" else "policyengine-us",
            data_vintage=f"{year} policy parameters",
            baseline="current law compared with submitted reform",
        ),
    }


# ---------------------------------------------------------------------------
# PolicyEngine population-level reform scoring
# ---------------------------------------------------------------------------
#
# Runs the reform against the full representative household microdata
# (UK: enhanced FRS, ~125MB download from a private HuggingFace repo the
# first time — set HUGGING_FACE_TOKEN; US: CPS-based, public). Measured on
# the UK 2026 enhanced FRS (53,508 households): ~6s per simulation run,
# ~1.8GB peak RSS, ~92MB derived per-year .h5 on disk. The baseline
# simulation is cached in-process per (country, year, dataset), so repeat
# reform scores only pay one ~6s reform run.

PE_POP_DEFAULT_DATASET = {"uk": "enhanced_frs_2023_24", "us": None}

# (country, year, dataset_name) -> (dataset_obj, baseline_simulation)
_PE_POP_BASELINE_CACHE: dict[tuple[str, int, str | None], tuple] = {}


def _pe_pop_data_folder() -> str:
    import os

    # Mirrors where the hosted Modal volume is mounted.
    return os.environ.get(
        "POLICYENGINE_MACRO_PE_DATA_DIR",
        os.path.expanduser("~/.cache/policyengine-macro/policyengine-data"),
    )


def _pe_pop_extra_variables(country: str) -> dict:
    # gov_balance (tax minus spending, includes CGT and employer NI) is the
    # UK budget headline; it is not in the model's default output set.
    return {"household": ["gov_balance", "gov_tax"]} if country == "uk" else {}


def _pe_pop_dataset(pe, country: str, year: int, dataset: str | None):
    """Download/build (first call) and load the population dataset."""
    module = getattr(pe, country)
    name = dataset or PE_POP_DEFAULT_DATASET[country]
    kwargs = {"years": [int(year)], "data_folder": _pe_pop_data_folder()}
    if name is not None:
        kwargs["datasets"] = [name]
    try:
        datasets = module.ensure_datasets(**kwargs)
    except Exception as e:
        import os

        hint = ""
        if country == "uk" and not (
            os.environ.get("HUGGING_FACE_TOKEN") or os.environ.get("HF_TOKEN")
        ):
            hint = (
                " The UK population microdata lives in a private HuggingFace"
                " repo: set HUGGING_FACE_TOKEN to a token from an account"
                " with access to policyengine/policyengine-uk-data-private."
            )
        raise RuntimeError(
            f"Could not obtain the {country.upper()} population dataset "
            f"{name!r} for {year} ({type(e).__name__}: {e}).{hint}"
        ) from e
    for ds in datasets.values():
        if int(ds.year) == int(year):
            return ds
    raise RuntimeError(
        f"ensure_datasets returned no dataset for year {year}: "
        f"{sorted(datasets)}"
    )


def _pe_pop_baseline(country: str, year: int, dataset: str | None):
    """Dataset + baseline simulation, cached in-process."""
    key = (country, int(year), dataset)
    if key in _PE_POP_BASELINE_CACHE:
        return _PE_POP_BASELINE_CACHE[key]
    pe = _import_pe()
    from policyengine.core import Simulation

    ds = _pe_pop_dataset(pe, country, year, dataset)
    sim = Simulation(
        dataset=ds,
        tax_benefit_model_version=getattr(pe, country).model,
        extra_variables=_pe_pop_extra_variables(country),
    )
    sim.run()
    _PE_POP_BASELINE_CACHE[key] = (ds, sim)
    return ds, sim


def _pe_pop_sum(sim, variable: str) -> float:
    from policyengine.outputs.aggregate import Aggregate, AggregateType

    agg = Aggregate(
        simulation=sim, variable=variable,
        aggregate_type=AggregateType.SUM, entity="household",
    )
    agg.run()
    return float(agg.result)


def _pe_pop_outcomes(country: str, base, ref) -> dict:
    """Budget, net-income and decile deltas of a counterfactual vs baseline.

    Shared measurement core of pe_population_impact (reform runs) and
    _pe_population_incidence (macro-shock runs): everything here is
    counterfactual-minus-baseline, whatever produced the counterfactual.
    """
    from policyengine.outputs.decile_impact import calculate_decile_impacts

    if country == "uk":
        budget_bn = (
            _pe_pop_sum(ref, "gov_balance") - _pe_pop_sum(base, "gov_balance")
        ) / 1e9
        budget_basis = (
            "change in gov_balance (all modelled taxes incl. CGT and "
            "employer NI, minus benefit spending)"
        )
    else:
        d_tax = _pe_pop_sum(ref, "household_tax") - _pe_pop_sum(base, "household_tax")
        d_ben = (
            _pe_pop_sum(ref, "household_benefits")
            - _pe_pop_sum(base, "household_benefits")
        )
        budget_bn = (d_tax - d_ben) / 1e9
        budget_basis = "change in household_tax minus change in household_benefits"

    net_income_change_bn = (
        _pe_pop_sum(ref, "household_net_income")
        - _pe_pop_sum(base, "household_net_income")
    ) / 1e9

    # Measure the change in household_net_income (which, unlike the UK's
    # HBAI income concept, moves under e.g. CGT reforms), grouped by the
    # baseline income decile.
    decile_kwargs = {
        "income_variable": "household_net_income",
        "entity": "household",
    }
    if country == "uk":
        decile_kwargs["decile_variable"] = "household_income_decile"
    deciles = calculate_decile_impacts(
        baseline_simulation=base, reform_simulation=ref, **decile_kwargs
    )
    decile_rows, winners, losers = [], 0.0, 0.0
    for d in deciles.outputs:
        avg_change = float(d.reform_mean - d.baseline_mean)
        decile_rows.append(
            {
                "decile": int(d.decile),
                "avg_income_change": round(avg_change, 2),
                # Change in the decile's mean income, in percent. (The
                # library's DecileImpact.relative_change is the mean of
                # per-household percent changes, which tiny-income outliers
                # dominate.)
                "relative_change_pct": round(
                    100 * avg_change / d.baseline_mean, 3
                ) if d.baseline_mean else None,
                "count_better_off": int(d.count_better_off),
                "count_worse_off": int(d.count_worse_off),
            }
        )
        # Accumulate the SAME integers the decile rows display, so the
        # headline totals always equal the sum of the rows (truncating the
        # floats independently let them disagree).
        winners += int(d.count_better_off)
        losers += int(d.count_worse_off)

    return {
        "budgetary_impact_bn": round(budget_bn, 3),
        "budgetary_impact_basis": budget_basis,
        "household_net_income_change_bn": round(net_income_change_bn, 3),
        "decile_impacts": decile_rows,
        "winners": int(winners),
        "losers": int(losers),
    }


def pe_population_impact(
    country: str = "uk",
    reform: dict | None = None,
    year: int = 2026,
    dataset: str | None = None,
    reform_modifier=None,
) -> dict:
    """Score a reform against the whole population with PolicyEngine.

    Runs baseline and reform microsimulations over representative household
    microdata (UK: enhanced FRS; US: CPS-based) and returns the budgetary
    impact — the change in government revenue net of spending, in £bn/$bn
    per year (positive = the reform raises revenue) — plus income-decile
    impacts and winner/loser counts.

    reform is a flat {parameter_path: value} dict, e.g. equalising CGT with
    income tax rates: {"gov.hmrc.cgt.basic_rate": 0.20,
    "gov.hmrc.cgt.higher_rate": 0.40, "gov.hmrc.cgt.additional_rate": 0.45}.

    The baseline simulation is cached in-process per (country, year,
    dataset). UK data needs HUGGING_FACE_TOKEN on first download.

    ``reform_modifier`` (internal; used by dynamic_population_reform_impact)
    is an optional callable applied to the underlying engine simulation of
    the REFORM run only, attached via the engine's supported
    ``Dynamic(simulation_modifier=...)`` hook. The baseline — cached and
    shared with static scores — NEVER sees it, which is the structural
    guarantee that a macro overlay is applied exactly once, to the reform
    side only.
    """
    reform = validate_reform(reform)
    country = _validate_country(country)

    ds, base = _pe_pop_baseline(country, year, dataset)
    pe = _import_pe()
    from policyengine.core import Simulation

    ref_kwargs = {}
    if reform_modifier is not None:
        from policyengine.core import Dynamic

        ref_kwargs["dynamic"] = Dynamic(
            name="policyengine-macro EconomicAssumptions overlay",
            simulation_modifier=reform_modifier,
            # Exogenous macro input scaling, not a behavioural response:
            # do not trigger the engine's labour-supply-response outputs.
            affects_labor_supply_response=False,
        )
    ref = Simulation(
        dataset=ds,
        tax_benefit_model_version=getattr(pe, country).model,
        policy=dict(reform),
        extra_variables=_pe_pop_extra_variables(country),
        **ref_kwargs,
    )
    ref.run()

    outcomes = _pe_pop_outcomes(country, base, ref)
    budget_bn = outcomes["budgetary_impact_bn"]

    sym = "£" if country == "uk" else "$"
    out = {
        "model": "PolicyEngine population microsimulation",
        "provenance": _provenance(
            model_id="pe-microsim",
            distribution="policyengine",
            data_vintage=ds.name,
            baseline=f"baseline policy for {year}",
        ),
        "country": country,
        "year": int(year),
        "dataset": ds.name,
        "n_households": int(len(ds.data.household)),
        "currency": "GBP" if country == "uk" else "USD",
        "reform": dict(reform),
        **outcomes,
        "headline": (
            f"The reform {'raises' if budget_bn >= 0 else 'costs'} "
            f"{sym}{abs(budget_bn):.1f}bn/year in {year}."
        ),
    }
    out["score"] = _pop_score_block(out)
    return out


def _pe_population_incidence(
    country: str,
    year: int,
    dataset: str | None,
    modifier,
    label: str,
) -> dict:
    """Population-level incidence of a macro shock: NO reform involved.

    Runs the cached stock baseline against a second simulation that differs
    ONLY by the macro overlay — a ``Dynamic(simulation_modifier=...)``
    scaling the employment-income inputs (assumptions.py) — and measures
    the same outcomes as pe_population_impact. budgetary_impact_bn is the
    change in the government balance caused by the macro shock through the
    automatic stabilizers (a negative earnings shock reduces tax revenue
    and raises means-tested benefits), NOT the cost of any reform: policy
    is identical on both sides.

    ``modifier`` may be None (a no-op macro result): the shocked simulation
    is then construction-identical to the baseline and every delta is zero
    by design — callers surface that as the honest null, not an error.
    Deliberately NOT routed through validate_reform: there is no reform.
    """
    country = _validate_country(country)
    ds, base = _pe_pop_baseline(country, year, dataset)
    pe = _import_pe()
    from policyengine.core import Simulation

    kwargs = {}
    if modifier is not None:
        from policyengine.core import Dynamic

        kwargs["dynamic"] = Dynamic(
            name=label,
            simulation_modifier=modifier,
            # Exogenous macro input scaling, not a behavioural response.
            affects_labor_supply_response=False,
        )
    shocked = Simulation(
        dataset=ds,
        tax_benefit_model_version=getattr(pe, country).model,
        extra_variables=_pe_pop_extra_variables(country),
        **kwargs,
    )
    shocked.run()

    outcomes = _pe_pop_outcomes(country, base, shocked)
    budget_bn = outcomes["budgetary_impact_bn"]
    sym = "£" if country == "uk" else "$"
    return {
        "model": "PolicyEngine population microsimulation (macro-shock incidence)",
        "provenance": _provenance(
            model_id="pe-microsim",
            distribution="policyengine",
            data_vintage=ds.name,
            baseline=f"baseline policy for {year}",
        ),
        "country": country,
        "year": int(year),
        "dataset": ds.name,
        "n_households": int(len(ds.data.household)),
        "currency": "GBP" if country == "uk" else "USD",
        "shock_label": label,
        **outcomes,
        "headline": (
            f"Through the automatic stabilizers, the macro shock "
            f"{'improves' if budget_bn >= 0 else 'worsens'} the government "
            f"balance by {sym}{abs(budget_bn):.1f}bn/year in {year} "
            "(policy unchanged)."
        ),
    }


# ---------------------------------------------------------------------------
# OG-UK overlapping-generations adapters (steady state only)
# ---------------------------------------------------------------------------
#
# Cheapest sensible configuration, which is oguk's own default: pooled ages
# (one tax function for all ages), single representative sector (M=1),
# steady-state comparison only (no transition path). A single solve —
# PolicyEngine microdata calibration + OG-Core SS solve — takes minutes of
# CPU, so the baseline solve is cached at module level per (start_year,
# max_iter) and reused across reform scores in the same process.

_OG_BASELINE_CACHE: dict[tuple[int, int], object] = {}

OG_DEFAULT_MAX_ITER = 250


def _import_oguk():
    try:
        from oguk import map_to_real_world, solve_steady_state
    except ImportError as e:
        raise ImportError(
            "The OG-UK package `oguk` is not importable. Install it with: "
            "pip install git+https://github.com/PSLmodels/OG-UK"
        ) from e
    return solve_steady_state, map_to_real_world


def _og_build_policy(reform: dict, start_year: int):
    """Build a PolicyEngine Policy from a {parameter_path: value} reform."""
    from datetime import datetime

    from policyengine.core import ParameterValue, Policy
    from policyengine.tax_benefit_models.uk import uk_latest

    default_start = datetime(int(start_year), 1, 1)
    values = []
    for path, spec in reform.items():
        # validate_reform leaves flat values as scalars and dated values as
        # {"YYYY-MM-DD": value}; both are supported here.
        dated = spec if isinstance(spec, dict) else {None: spec}
        for date_key, value in dated.items():
            start = (
                default_start
                if date_key is None
                else datetime.strptime(str(date_key), "%Y-%m-%d")
            )
            values.append(
                ParameterValue(
                    parameter=uk_latest.get_parameter(path),
                    value=value,
                    start_date=start,
                )
            )
    return Policy(
        name=", ".join(f"{p} = {v}" for p, v in reform.items()),
        parameter_values=values,
    )


def _og_solve(solve_fn, **kwargs):
    """Run an oguk steady-state solve, failing fast with an actionable error.

    oguk's calibration builds tax functions from the PolicyEngine
    enhanced-FRS UK microdata, downloaded via
    policyengine.tax_benefit_models.uk.ensure_datasets. Known environment
    failures are translated into clear messages: (a) no HuggingFace access to
    the dataset — set HUGGING_FACE_TOKEN; (b) policyengine-uk >= 2.89 renamed
    the dataset keys from enhanced_frs_2023_24_<year> to populace_uk_*, which
    makes oguk 0.3.2 (pinning policyengine-uk==2.88.0) fail with a KeyError.
    """
    try:
        return solve_fn(**kwargs)
    except KeyError as e:
        raise RuntimeError(
            "OG-UK calibration could not find the PolicyEngine enhanced-FRS "
            f"microdata dataset (missing dataset key {e}). Likely causes: "
            "(a) no access to the enhanced-FRS dataset on HuggingFace — set "
            "HUGGING_FACE_TOKEN to a token with access "
            "(policyengine.tax_benefit_models.uk.ensure_datasets downloads "
            "it); (b) incompatible policyengine-uk version — oguk 0.3.2 "
            "requires policyengine-uk==2.88.0 (>= 2.89 renamed the datasets)"
            ": pip install 'policyengine-uk==2.88.0'."
        ) from e


def _og_solve_baseline(start_year: int, max_iter: int, use_cache: bool = True):
    solve_steady_state, _ = _import_oguk()
    key = (int(start_year), int(max_iter))
    if use_cache and key in _OG_BASELINE_CACHE:
        return _OG_BASELINE_CACHE[key]
    ss = _og_solve(
        solve_steady_state, start_year=int(start_year), max_iter=int(max_iter)
    )
    if use_cache:
        _OG_BASELINE_CACHE[key] = ss
    return ss


def _og_ss_dict(ss) -> dict:
    """SteadyStateResult -> plain dict (model units), FULL PRECISION.

    No rounding here: the dynamic overlay computes reform/baseline ratios
    from these values, and 4dp rounding quantized small reforms to an exact
    factor of 1.0 — silently returning static results as dynamic (Sol
    review of #72, blocking #2). Round for display only, at the CLI."""
    return {k: float(v) for k, v in ss.model_dump().items()}


def og_baseline(start_year: int = 2026, max_iter: int = OG_DEFAULT_MAX_ITER) -> dict:
    """Baseline long-run steady state of the OG-UK overlapping-generations model.

    Solves (or reuses a cached) baseline steady state under the simplest
    assumptions: pooled-age tax functions, single representative firm/sector.
    Returns model-unit aggregates (r, w, Y, K, L, C, I, G, tax_revenue, debt).
    """
    ss = _og_solve_baseline(start_year, max_iter)
    return {
        "model": "OG-UK overlapping generations (steady state)",
        "provenance": _provenance(
            model_id="og-uk",
            distribution="oguk",
            data_vintage="OG-UK packaged calibration inputs",
            baseline=f"steady state starting {start_year}",
        ),
        "assumptions": "pooled ages, single representative sector, "
                       "steady state only",
        "start_year": int(start_year),
        "max_iter": int(max_iter),
        "steady_state_model_units": _og_ss_dict(ss),
    }


def og_score_reform(
    reform: dict,
    start_year: int = 2026,
    max_iter: int = OG_DEFAULT_MAX_ITER,
    baseline_cache: bool = True,
) -> dict:
    """Score a PolicyEngine parametric reform with the OG-UK OLG model.

    ``reform`` is the suite's shared reform shape — a flat
    {parameter_path: value} dict, the same one pe_population_impact and the
    household tools take. Solves baseline (module-level cached) and reform
    steady states, and maps the long-run changes to real-world £bn via
    oguk.map_to_real_world.
    """
    reform = validate_reform(reform)
    solve_steady_state, map_to_real_world = _import_oguk()
    policy = _og_build_policy(dict(reform), int(start_year))
    baseline_ss = _og_solve_baseline(start_year, max_iter, use_cache=baseline_cache)
    reform_ss = _og_solve(
        solve_steady_state, start_year=int(start_year), policy=policy,
        max_iter=int(max_iter),
    )
    impact = map_to_real_world(baseline_ss, reform_ss)
    imp = impact.model_dump()
    out = {
        "model": "OG-UK overlapping generations (steady state)",
        "provenance": _provenance(
            model_id="og-uk",
            distribution="oguk",
            data_vintage="OG-UK packaged calibration inputs",
            baseline=f"steady state starting {start_year}",
        ),
        "assumptions": "pooled ages, single representative sector, "
                       "long-run steady-state comparison (not a budget-window "
                       "costing)",
        "reform": dict(reform),
        "start_year": int(start_year),
        "impact": {
            "levels_bn": {k: imp[k] for k in
                          ("gdp", "consumption", "investment", "government",
                           "tax_revenue", "debt")},
            "changes_bn": {k: imp[k] for k in imp if k.endswith("_change")},
            "changes_pct": {k: imp[k] for k in imp if k.endswith("_pct")},
            "interest_rate": {"baseline": imp["r_baseline"],
                              "reform": imp["r_reform"]},
        },
        "baseline_steady_state_model_units": _og_ss_dict(baseline_ss),
        "reform_steady_state_model_units": _og_ss_dict(reform_ss),
    }
    out["score"] = _og_score_block(out)
    return out


# ---------------------------------------------------------------------------
# Common ScoreResult schema across all scoring adapters (issue #10)
# ---------------------------------------------------------------------------
#
# Every scoring entry point (og_score_reform, obr_score_reform,
# pe_population_impact) returns its existing model-specific dict UNCHANGED
# plus a "score" key holding this common, pydantic-validated shape — additive,
# so existing consumers keep working while comparisons across model classes
# ("the same reform through different models, side by side") have one
# programmatic object. Emitted as .model_dump() dicts, per this module's
# plain-dicts-out convention.

SCORE_QUANTITIES = (
    "gdp", "consumption", "investment", "government", "revenue", "debt"
)


class ScoreQuantity(BaseModel):
    """One model quantity with enough metadata to assess comparability.

    A shared name does not make two values like-for-like: units, basis,
    time_basis, and comparability must all be inspected.
    """

    level_bn: float | None = None
    delta_bn: float | None = None
    delta_pct: float | None = None
    units: str = Field(min_length=1)
    unit_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    basis: str
    time_basis: str
    price_basis: str
    geography: str = Field(pattern=r"^[a-z]{2}$")
    baseline_definition: str
    uncertainty: str
    comparability: str = Field(
        default="related-not-like-for-like",
        pattern=r"^(comparable|related-not-like-for-like|not-comparable)$"
    )


class ScoreDistribution(BaseModel):
    """Distributional block; only the microsim fills it today."""

    decile_impacts: list[dict]
    winners: int
    losers: int


class ScoreProvenance(BaseModel):
    """Mandatory, validated identity and reproduction metadata."""

    model_config = ConfigDict(protected_namespaces=())

    model_id: str = Field(min_length=1)
    package: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    source_url: HttpUrl
    source_revision: str = Field(min_length=1)
    data_vintage: str = Field(min_length=1)
    baseline_vintage: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    estimation_sample: str | None = None
    run_at: datetime
    reproducibility: str = Field(min_length=1)

    @field_validator("run_at")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run_at must be timezone-aware")
        return value


class ScoreResult(BaseModel):
    """The common result shape for every scoring adapter (issue #10)."""

    model_config = ConfigDict(protected_namespaces=())

    model: str        # canonical registry id
    model_class: str  # "microsim" | "semi-structural" | "olg-ge"
    analysis_type: str
    result_type: str = Field(
        pattern=r"^(forecast|scenario|historical-estimate|calibration|illustration)$"
    )
    country: str
    reform: dict
    baseline: str
    provenance: ScoreProvenance
    horizon: str      # "steady-state" | "quarterly window ..." | "annual ..."
    quantities: dict[str, ScoreQuantity]
    assumptions: list[str] = Field(min_length=1)
    caveats: list[str] = Field(min_length=1)
    validation: list[str] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    uncertainty: dict | None = None      # bands where the model produces them
    distributional: ScoreDistribution | None = None

    @field_validator("provenance")
    @classmethod
    def provenance_matches_model(cls, value: ScoreProvenance, info):
        model = info.data.get("model")
        if model and value.model_id != model:
            raise ValueError("provenance model_id must match result model")
        return value


def _og_score_block(res: dict) -> dict:
    """Common ScoreResult from an og_score_reform payload."""
    imp = res["impact"]
    units = "GBP bn per year, long-run steady state"
    q = {}
    for k in ("gdp", "consumption", "investment", "government",
              "tax_revenue", "debt"):
        name = "revenue" if k == "tax_revenue" else k
        q[name] = ScoreQuantity(
            level_bn=imp["levels_bn"][k],
            delta_bn=imp["changes_bn"][f"{k}_change"],
            delta_pct=imp["changes_pct"][f"{k}_pct"],
            units=units,
            unit_code="GBP_BN",
            basis="oguk.map_to_real_world baseline-vs-reform steady states",
            time_basis="long-run annual steady-state level",
            price_basis="real, model calibration basis",
            geography="uk",
            baseline_definition=f"OG-UK steady state starting {res.get('start_year', 2026)}",
            uncertainty="not estimated; sensitivity analysis required",
        )
    start_year = int(res.get("start_year", 2026))
    return ScoreResult(
        model="og-uk",
        model_class="olg-ge",
        analysis_type="long-run structural reform",
        result_type="scenario",
        country="uk",
        reform=res["reform"],
        baseline=f"OG-UK steady state starting {start_year}",
        provenance=_provenance(
            model_id="og-uk",
            distribution="oguk",
            data_vintage="OG-UK packaged calibration inputs",
            baseline=f"steady state starting {start_year}",
        ),
        horizon="steady-state",
        quantities=q,
        assumptions=[res["assumptions"]],
        caveats=[
            "long-run steady-state comparison, not a budget-window costing",
        ],
        validation=["calibrated counterfactual; solver and calibration tests"],
    ).model_dump(mode="json")


def _pop_score_block(res: dict) -> dict:
    """Common ScoreResult from a pe_population_impact payload."""
    cur = res["currency"]
    return ScoreResult(
        model="pe-microsim",
        model_class="microsim",
        analysis_type="population policy reform",
        result_type="scenario",
        country=res["country"],
        reform=res["reform"],
        baseline=f"PolicyEngine baseline policy for {res['year']}",
        provenance=_provenance(
            model_id="pe-microsim",
            distribution="policyengine",
            data_vintage=res["dataset"],
            baseline=f"baseline policy for {res['year']}",
        ),
        horizon=f"annual {res['year']}",
        quantities={
            "revenue": ScoreQuantity(
                delta_bn=res["budgetary_impact_bn"],
                units=f"{cur} bn per year",
                unit_code=f"{cur}_BN",
                basis=res["budgetary_impact_basis"],
                time_basis=f"annual {res['year']}",
                price_basis="nominal survey-weighted annual amount",
                geography=res["country"],
                baseline_definition=f"PolicyEngine baseline policy for {res['year']}",
                uncertainty="not estimated in this result",
            ),
        },
        assumptions=[
            "static microsimulation: no behavioural or macro feedback",
            f"dataset {res['dataset']} ({res['n_households']} households)",
        ],
        caveats=["GDP/consumption/investment are out of scope for a "
                 "static microsim; only the budgetary impact is filled"],
        validation=["deterministic rule tests plus population contract tests"],
        distributional=ScoreDistribution(
            decile_impacts=res["decile_impacts"],
            winners=res["winners"],
            losers=res["losers"],
        ),
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# OBR bridge: microsim static costing in, second-round effects out (issue #9)
# ---------------------------------------------------------------------------

# Declared virtual injection point for externally costed household reforms.
# The OBR adapter translates positive quarterly revenue costings into negative
# held add-factors on nominal HHDI, preserving the endogenous HHDI identity and
# its HHDI -> RHHDI -> CONS -> GDPM transmission chain.
OBR_BRIDGE_VAR = "HHDI_ADDFACTOR"

_OBR_CORP_TAX_MARKERS = ("corporation_tax", "corporate_tax")


def _obr_corp_tax_paths(reform: dict) -> list[str]:
    return [p for p in reform
            if any(m in p for m in _OBR_CORP_TAX_MARKERS)]


def obr_costing_to_shock(annual_budget_bn) -> list[float]:
    """Pure translation: annual static costings -> the OBR add-factor path.

    Takes the microsim's annual budgetary impacts (£bn per year, positive =
    the reform raises revenue) and returns the quarterly additive shock on
    ``OBR_BRIDGE_VAR`` (HHDI_ADDFACTOR, £m per quarter) that run_reform consumes:

    - Sign: positive means revenue raised. The OBR adapter applies the minus
      sign when it converts the costing into an HHDI held add-factor.
    - Units: £bn/year -> £m/quarter is * 1000 / 4.
    - Interpolation: flat within each year (deliberately crude and declared;
      the microsim only produces annual numbers).

    Pure arithmetic — no model imports — so it is unit-testable everywhere.
    """
    path: list[float] = []
    for bn in annual_budget_bn:
        quarterly_m = float(bn) * 1000.0 / 4.0
        path.extend([round(quarterly_m, 4)] * 4)
    return path


def obr_score_reform(
    reform: dict,
    start_year: int = 2026,
    years: int = 5,
    dataset: str | None = None,
) -> dict:
    """Score a PolicyEngine reform through the OBR emulator (issue #9).

    The OBR's own workflow: static costing in, second-round effects out.

    Pipeline:
      1. pe_population_impact(country="uk", reform=..., year=y) for each year
         in [start_year, start_year+years) -> annual budgetary_impact_bn path
         (needs the private UK microdata; set HUGGING_FACE_TOKEN).
      2. obr_costing_to_shock: annual £bn -> quarterly £m revenue costings, flat
         within each year (positive = revenue raised).
      3. run_reform(var="HHDI_ADDFACTOR", shock=[path]) converts the costing
         to a negative held HHDI add-factor and returns per-quarter GDP,
         consumption and investment deltas.

    What the translation assumes (be honest):
    - The costing enters as a held add-factor on nominal household disposable
      income (HHDI), where a household tax/benefit change first bites. Unlike
      the former direct HHDI shock, the declared injection point preserves the
      endogenous HHDI identity while propagating HHDI -> RHHDI -> CONS -> GDP.
    - Demand-side incidence only. Supply-side channels (participation,
      savings, capital) are the OG member's job — that division of labour is
      the point of the suite.
    - Corporation tax is not household-borne in the microsim, so a
      corporation-tax reform is refused here with a pointer to
      obr_shock(var="TCPRO", ...), the direct lever.

    UK only (the OBR is a UK model). Runtime: one microsim run per year in
    the window (~6s each after the first) plus two OBR solves.
    """
    reform = validate_reform(reform)
    corp = _obr_corp_tax_paths(reform)
    if corp:
        raise ValueError(
            "corporation tax is not household-borne in the microsim, so the "
            "static-costing bridge cannot carry it (paths: "
            f"{', '.join(corp)}). Use the direct lever instead: "
            "obr_shock(var='TCPRO', shock=<rate change in decimal>)."
        )
    years = int(years)
    if years < 1:
        raise ValueError(f"years must be >= 1, got {years}")
    run_reform = _import_obr()

    window = list(range(int(start_year), int(start_year) + years))
    costings = [
        pe_population_impact(
            country="uk", reform=reform, year=y, dataset=dataset
        )
        for y in window
    ]
    annual_bn = [c["budgetary_impact_bn"] for c in costings]
    shock_path = obr_costing_to_shock(annual_bn)

    start, end = f"{window[0]}Q1", f"{window[-1]}Q4"
    name = f"PE static costing via {OBR_BRIDGE_VAR}: {reform}"
    df = run_reform(
        name=name,
        var=OBR_BRIDGE_VAR,
        shock=shock_path,
        start=start,
        end=end,
        investment_closure=False,
    )
    rows = _obr_result_rows(df)
    shocked = rows[: len(shock_path)]
    cumulative_gdp_bn = round(sum(r["delta_gdp_bn"] for r in shocked), 3)
    peak = max(rows, key=lambda r: abs(r["pct_gdp"]))
    mean_costing_bn = round(sum(annual_bn) / len(annual_bn), 3)

    caveats = [
        "static costing enters through the declared HHDI_ADDFACTOR path "
        "(positive revenue is converted to a negative held HHDI add-factor)",
        "demand-side incidence only; supply-side channels belong to the "
        "OG member",
        "annual costings applied flat within each year",
        "corporation-tax reforms are out of scope (direct TCPRO lever via "
        "obr_shock)",
    ]
    out = {
        "model": "OBR emulator via PolicyEngine static costing",
        "country": "uk",
        "reform": dict(reform),
        "start_year": int(start_year),
        "years": years,
        "window": {"start": start, "end": end},
        "bridge_variable": OBR_BRIDGE_VAR,
        "annual_costings_bn": [
            {"year": y, "budgetary_impact_bn": bn}
            for y, bn in zip(window, annual_bn)
        ],
        "quarterly_shock_path_m": shock_path,
        "results": rows,
        "cumulative_delta_gdp_bn_over_shock_periods": cumulative_gdp_bn,
        "peak_pct_gdp": peak["pct_gdp"],
        "peak_period": peak["period"],
        "caveats": caveats,
    }
    out["score"] = ScoreResult(
        model="obr-macro",
        model_class="semi-structural",
        analysis_type="translated fiscal scenario",
        result_type="scenario",
        country="uk",
        reform=dict(reform),
        baseline="OBR Economic and Fiscal Outlook, March 2026",
        provenance=_provenance(
            model_id="obr-macro",
            distribution="obr-macro-model",
            data_vintage="March 2026 EFO",
            baseline="March 2026 EFO anchored baseline",
        ),
        horizon=f"quarterly window {start}..{end}",
        quantities={
            "gdp": ScoreQuantity(
                delta_bn=cumulative_gdp_bn,
                units="GBP bn, cumulative over the shocked quarters",
                unit_code="GBP_BN",
                basis="GDPM delta vs baseline, OBR emulator solve",
                time_basis=f"cumulative quarterly {start}..{end}",
                price_basis="real",
                geography="uk",
                baseline_definition="March 2026 EFO anchored baseline",
                uncertainty="not estimated",
            ),
            "consumption": ScoreQuantity(
                delta_bn=round(
                    sum(r["delta_cons_m"] for r in shocked) / 1000.0, 3
                ),
                units="GBP bn, cumulative over the shocked quarters",
                unit_code="GBP_BN",
                basis="CONS delta vs baseline, OBR emulator solve",
                time_basis=f"cumulative quarterly {start}..{end}",
                price_basis="real",
                geography="uk",
                baseline_definition="March 2026 EFO anchored baseline",
                uncertainty="not estimated",
            ),
            "investment": ScoreQuantity(
                delta_bn=round(
                    sum(r["delta_if_m"] for r in shocked) / 1000.0, 3
                ),
                units="GBP bn, cumulative over the shocked quarters",
                unit_code="GBP_BN",
                basis="IF delta vs baseline, OBR emulator solve",
                time_basis=f"cumulative quarterly {start}..{end}",
                price_basis="real",
                geography="uk",
                baseline_definition="March 2026 EFO anchored baseline",
                uncertainty="not estimated",
            ),
            "revenue": ScoreQuantity(
                delta_bn=mean_costing_bn,
                units="GBP bn per year, mean over the window",
                unit_code="GBP_BN",
                basis="PolicyEngine static costing (the bridge INPUT, not "
                      "an emulator output)",
                time_basis=f"mean annual {window[0]}..{window[-1]}",
                price_basis="nominal",
                geography="uk",
                baseline_definition="PolicyEngine baseline policy in each year",
                uncertainty="not estimated",
            ),
        },
        assumptions=[
            "microsim static costing injected as an HHDI add path "
            "(demand-side incidence)",
            "flat quarterly interpolation within each year",
        ],
        caveats=caveats,
        validation=[
            "selected OBR emulator scenarios are regression-tested against fixtures"
        ],
    ).model_dump(mode="json")
    return out


# ---------------------------------------------------------------------------
# Dynamic scoring: OG-UK EconomicAssumptions overlay on the microsim (#11)
# ---------------------------------------------------------------------------

def _check_overlay_collision(reform: dict) -> None:
    """Refuse user reforms under gov.economic_assumptions.* in dynamic runs.

    Empirical finding (2026-07-20, production engine): uprating-parameter
    overrides there are DEAD in population runs — the per-year datasets are
    pre-uprated at build time, so such a reform silently does nothing (two
    index-override calls returned exactly zero everywhere; see
    assumptions.py). A dynamic score must never carry a silently inert
    piece of reform, so it is refused here. The overlay itself no longer
    touches parameters at all — it scales the reform simulation's
    employment-income inputs directly — so this guard is about honesty,
    not merge collisions.
    """
    from policyengine_macro.assumptions import OVERLAY_PARAM_PREFIX

    hit = [p for p in reform if p.startswith(OVERLAY_PARAM_PREFIX)]
    if hit:
        raise ValueError(
            "dynamic scoring refuses user overrides under "
            "gov.economic_assumptions.*: the overlay already carries the "
            "macro model's economic assumptions, so a user override would "
            "double-drive the same channel — and for input-uprating index "
            "paths (e.g. indices.obr.average_earnings) such overrides are "
            "additionally inert in population runs, because the per-year "
            "microdata are pre-uprated at dataset build time (verified "
            "2026-07-20). Some paths in this namespace ARE consulted at "
            "simulation time; apply those in a STATIC population run if "
            f"intended. (paths: {', '.join(hit)})"
        )


def dynamic_population_reform_impact(
    country: str = "uk",
    reform: dict | None = None,
    year: int = 2026,
    dataset: str | None = None,
    max_iter: int = OG_DEFAULT_MAX_ITER,
    baseline_cache: bool = True,
    og_payload: dict | None = None,
) -> dict:
    """Dynamic population score: OG-UK macro overlay on the microsim (#11).

    Pipeline:
      1. og_score_reform (baseline steady state cached in-process) —
         long-run wage and labour-supply changes under the reform;
      2. EconomicAssumptions.from_og_result — reform/baseline factors;
      3. the earnings factor becomes DIRECT INPUT SCALING of the reform
         simulation's employment-income arrays, attached through the
         engine's Dynamic(simulation_modifier=...) hook (parameter
         overrides on the uprating indices are dead in population runs:
         the per-year microdata are pre-uprated at build time — see
         assumptions.py for the empirical evidence);
      4. one pe_population_impact run: user reform as policy + the scaling
         modifier on the reform side only, against the stock baseline
         (cached; NEVER modified — the structural once-and-reform-side-only
         guarantee).

    Double-counting rule: the overlay carries only the reform/baseline
    RATIO from the macro model; the stock baseline already embeds the OBR
    forecast the OG baseline is calibrated to, so the static effect is
    never counted twice — a null macro result attaches no modifier and
    reduces this exactly to the static score.

    UK only (OG-UK is UK-only). Runtime: two OG steady-state solves
    (baseline cached; ~10+ min cold) plus one microsim run.
    """
    from policyengine_macro.assumptions import (
        SCALED_INPUT_VARIABLES, EconomicAssumptions,
    )

    country = _validate_country(country)
    if country != "uk":
        raise ValueError(
            "dynamic scoring is UK-only (OG-UK is a UK model); country "
            "must be 'uk'"
        )
    reform = validate_reform(reform)
    _check_overlay_collision(reform)

    # TWO-ENVIRONMENT REALITY (until PSLmodels/OG-UK#68): oguk pins
    # policyengine-uk==2.88.0, and importing the current policyengine
    # wrapper alongside it raises a mixed-computation-mode error — the OG
    # solve and the population microsim cannot share one process today.
    # ``og_payload`` accepts a pre-computed og_score_reform result (run in
    # the OG environment: `pe-macro og-score --json`), so the pipeline is
    # runnable NOW as an explicit two-step rather than an impossible
    # single-process import.
    if og_payload is not None:
        required = {"baseline_steady_state_model_units",
                    "reform_steady_state_model_units", "start_year"}
        missing = required - set(og_payload)
        if missing:
            raise ValueError(
                f"og_payload missing required keys: {sorted(missing)} — "
                "pass the unmodified JSON output of `pe-macro og-score`"
            )
        if og_payload.get("reform") != reform:
            raise ValueError(
                "og_payload was produced for a different reform than the "
                "one being scored (payload reform "
                f"{og_payload.get('reform')!r} vs {reform!r}); refusing to "
                "mix them"
            )
        if int(og_payload["start_year"]) != int(year):
            raise ValueError(
                f"og_payload start_year {og_payload['start_year']} does not "
                f"match the requested year {year}"
            )
        og = og_payload
    else:
        try:
            og = og_score_reform(
                reform=reform, start_year=year, max_iter=max_iter,
                baseline_cache=baseline_cache,
            )
        except (ImportError, ValueError) as e:
            if isinstance(e, ValueError) and (
                "computation mode" not in str(e).lower()
            ):
                raise  # an unrelated ValueError, not the mixed-mode import clash
            raise RuntimeError(
                "dynamic scoring needs an OG-UK solve, and oguk is not "
                "usable in this process (on the hosted server it is deliberately "
                "excluded: a solve cannot fit the request timeout; locally "
                "it needs its own environment until PSLmodels/OG-UK#68 — "
                "oguk pins policyengine-uk==2.88.0, which cannot share a "
                "process with the current policyengine wrapper). Run the "
                "two-step: in an OG env, `pe-macro og-score --reform '...' "
                "--json > og.json`; then here, `pe-macro dynamic-score "
                f"--reform '...' --og-payload og.json`. (underlying: {e})"
            ) from e
    ea = EconomicAssumptions.from_og_result(og)
    modifier = ea.input_scaling_modifier()

    micro = pe_population_impact(
        country="uk", reform=reform, year=year, dataset=dataset,
        reform_modifier=modifier,
    )

    assumptions = ea.assumption_strings()
    caveats = ea.caveat_strings() + [
        "corporation-tax incidence stops at the OG model's boundary: any "
        "wage effect it implies flows through the overlay, but the "
        "microsim itself still treats corporation tax as not "
        "household-borne",
    ]
    out = {
        "model": "OG-UK overlay + PolicyEngine population microsimulation",
        "country": "uk",
        "year": int(year),
        "reform": dict(reform),
        "economic_assumptions": ea.model_dump(),
        "application": {
            "method": "input-scaling",
            "variables_tried": list(SCALED_INPUT_VARIABLES),
            "earnings_factor": ea.earnings_factor,
            "applied": modifier is not None,
        },
        "og": og,
        "microsim": micro,
        "assumptions": assumptions,
        "caveats": caveats,
    }
    # The embedded microsim payload was produced WITH the overlay attached;
    # its own nested `score` block, generated by the static scorer, would
    # carry a "static microsimulation: no behavioural or macro feedback"
    # basis that contradicts this dynamic result. The outer ScoreResult
    # below is authoritative — drop the nested one rather than shipping two
    # scores that disagree about what was run.
    micro = dict(micro)
    micro.pop("score", None)
    out["microsim"] = micro
    out["score"] = ScoreResult(
        model="og+microsim",
        model_class="olg-ge overlay on microsim",
        analysis_type="experimental steady-state earnings overlay",
        result_type="illustration",
        country="uk",
        reform=dict(reform),
        baseline=(
            f"PolicyEngine baseline policy for {year}, with OG-UK steady-state "
            "reform-to-baseline earnings feedback"
        ),
        provenance=_provenance(
            model_id="og+microsim",
            distribution="policyengine-macro",
            data_vintage=(
                f"PolicyEngine dataset {micro.get('dataset', dataset or 'default')}; "
                "OG-UK packaged calibration inputs"
            ),
            baseline=f"baseline policy for {year} and OG-UK steady state",
        ),
        horizon=f"annual {year} under long-run steady-state assumptions",
        quantities={
            "revenue": ScoreQuantity(
                delta_bn=micro["budgetary_impact_bn"],
                units=f"{micro['currency']} bn per year",
                unit_code=f"{micro['currency']}_BN",
                basis=(
                    f"{micro['budgetary_impact_basis']}, under the OG-UK "
                    "earnings overlay"
                ),
                time_basis=(
                    f"annual {year}, applying a long-run steady-state wage "
                    "ratio from the first year"
                ),
                price_basis="nominal microsimulation result with real wage ratio overlay",
                geography="uk",
                baseline_definition=f"PolicyEngine baseline policy for {year}",
                uncertainty="not estimated; experimental overlay",
            ),
        },
        assumptions=assumptions,
        caveats=caveats,
        validation=[
            "input-scaling mechanism empirically gated; economic overlay remains experimental"
        ],
        distributional=ScoreDistribution(
            decile_impacts=micro["decile_impacts"],
            winners=micro["winners"],
            losers=micro["losers"],
        ),
    ).model_dump(mode="json")
    return out


# ---------------------------------------------------------------------------
# Macro -> micro shock incidence: who bears a macro shock, at household
# resolution. NOT reform scoring — there is still no reform bridge for
# FRB/US or HANK (SCORE_MODELS_WITHOUT_REFORM_BRIDGE stands). These tools
# answer the opposite question: given a raw macro shock, what do its
# labour-market (or price) deviations do to household incomes and the
# government balance through the automatic stabilizers?
# ---------------------------------------------------------------------------

# The real labour-market series the FRB/US incidence overlay is built on.
FRBUS_INCIDENCE_VARIABLES = ("pl", "lhp", "leh")


def _incidence_score_block(
    *,
    model_id: str,
    model_class: str,
    analysis_type: str,
    country: str,
    year: int,
    reform: dict,
    micro: dict,
    assumptions: list[str],
    caveats: list[str],
    baseline: str,
    data_vintage: str,
    horizon: str,
    basis_suffix: str,
) -> dict:
    """Common ScoreResult for the shock-incidence tools (illustrations)."""
    return ScoreResult(
        model=model_id,
        model_class=model_class,
        analysis_type=analysis_type,
        result_type="illustration",
        country=country,
        reform=reform,
        baseline=baseline,
        provenance=_provenance(
            model_id=model_id,
            distribution="policyengine-macro",
            data_vintage=data_vintage,
            baseline=baseline,
        ),
        horizon=horizon,
        quantities={
            "revenue": ScoreQuantity(
                delta_bn=micro["budgetary_impact_bn"],
                units=f"{micro['currency']} bn per year",
                unit_code=f"{micro['currency']}_BN",
                basis=f"{micro['budgetary_impact_basis']}, {basis_suffix}",
                time_basis=f"annual {year}",
                price_basis=(
                    "nominal microsimulation result with real "
                    "macro-deviation overlay"
                ),
                geography=country,
                baseline_definition=(
                    f"PolicyEngine baseline policy for {year}"
                ),
                uncertainty="not estimated; experimental incidence overlay",
            ),
        },
        assumptions=assumptions,
        caveats=caveats,
        validation=[
            "input-scaling mechanism empirically gated; the shock-incidence "
            "overlay itself is experimental"
        ],
        distributional=ScoreDistribution(
            decile_impacts=micro["decile_impacts"],
            winners=micro["winners"],
            losers=micro["losers"],
        ),
    ).model_dump(mode="json")


def frbus_shock_incidence(
    var: str,
    shock: float,
    year: int = 2027,
    start: str = FRBUS_DEFAULT_START,
    periods: int = 1,
    horizon: int = FRBUS_DEFAULT_HORIZON,
    policy_rule: str = "inertial_taylor",
    income_concept: str = "wage_bill",
    dataset: str | None = None,
    frbus_payload: dict | None = None,
) -> dict:
    """Household-level incidence of a FRB/US shock (experimental).

    ``frbus_payload`` accepts a pre-computed frbus_shock result (run with
    ``variables=["pl", "lhp", "leh"]``) so the FRB/US solve and the microsim
    can run in separate processes — the combined process peaks well past
    small-machine memory (observed: an 8GB host jetsam-kills it), the same
    two-step reality as ``og_payload`` in dynamic scoring. The payload's
    var/shock must match the arguments; mixing is refused. When a payload
    is given, ``start``/``periods``/``horizon``/``policy_rule`` are ignored
    — the payload's own solve parameters govern the shock, not these
    arguments.

    Pipeline:
      1. frbus_shock with the real labour-market series requested
         (pl compensation per hour, lhp hours, leh employment — all
         % deviations from baseline);
      2. EconomicAssumptions.from_frbus_result — the annual mean of the
         ``year`` quarters becomes a pre-tax earnings factor
         (income_concept: 'wage_bill' = pl+lhp, 'wage' = pl alone);
      3. the factor scales the US population microsimulation's
         employment-income inputs (reform-free: policy is identical on
         both sides), so the deciles/winners/losers and the budget change
         are the shock's incidence THROUGH THE AUTOMATIC STABILIZERS —
         a negative earnings shock reduces tax revenue and raises
         means-tested benefits.

    NOT reform scoring: FRB/US still has no PolicyEngine-reform bridge
    (score_reform keeps refusing model='frbus'). Uniform scaling
    understates the concentration of real incidence in job losers; the
    caveats say so. US only. Runtime: one FRB/US solve (~seconds) plus
    one microsim run (~tens of seconds warm; first-ever call downloads
    microdata).
    """
    from policyengine_macro.assumptions import (
        SCALED_INPUT_VARIABLES, EconomicAssumptions,
    )

    if frbus_payload is not None:
        got = (frbus_payload.get("var"), frbus_payload.get("shock"))
        if got != (var, float(shock)):
            raise ValueError(
                f"frbus_payload was produced for {got[0]!r} shock {got[1]!r}, "
                f"not for {var!r} shock {shock!r}; refusing to mix them — "
                "pass the unmodified output of frbus_shock run with "
                "variables=['pl', 'lhp', 'leh']"
            )
        payload = frbus_payload
    else:
        payload = frbus_shock(
            var=var, shock=shock, start=start, periods=periods,
            horizon=horizon, policy_rule=policy_rule,
            variables=list(FRBUS_INCIDENCE_VARIABLES),
        )
    ea = EconomicAssumptions.from_frbus_result(
        payload, year=year, income_concept=income_concept,
    )
    modifier = ea.input_scaling_modifier()
    micro = _pe_population_incidence(
        country="us", year=year, dataset=dataset, modifier=modifier,
        label=f"FRB/US {var} {shock:+g} earnings incidence ({year})",
    )

    assumptions = ea.assumption_strings()
    caveats = ea.caveat_strings() + [
        "automatic-stabilizer incidence of a raw macro shock, not a reform "
        "score: FRB/US has no PolicyEngine-reform bridge, and policy is "
        "identical on both sides of this comparison",
    ]
    out = {
        "model": "FRB/US shock + PolicyEngine population microsimulation",
        "country": "us",
        "year": int(year),
        "income_concept": income_concept,
        "frbus": payload,
        "economic_assumptions": ea.model_dump(),
        "application": {
            "method": "input-scaling",
            "variables_tried": list(SCALED_INPUT_VARIABLES),
            "earnings_factor": ea.earnings_factor,
            "applied": modifier is not None,
        },
        "microsim": micro,
        "assumptions": assumptions,
        "caveats": caveats,
    }
    out["score"] = _incidence_score_block(
        model_id="frbus+microsim",
        model_class="semi-structural overlay on microsim",
        analysis_type="shock incidence (experimental)",
        country="us",
        year=year,
        reform={},
        micro=micro,
        assumptions=assumptions,
        caveats=caveats,
        baseline=(
            f"PolicyEngine baseline policy for {year}, with FRB/US "
            f"{var} {shock:+g} labour-market deviations applied as a "
            "pre-tax earnings overlay"
        ),
        data_vintage=(
            f"PolicyEngine dataset {micro.get('dataset', dataset or 'default')}; "
            "FRB/US April 2026 LONGBASE"
        ),
        horizon=f"annual {year}, transition-quarter average deviations",
        basis_suffix=(
            "from the macro shock through the automatic stabilizers "
            "(no reform)"
        ),
    )
    return out


def hank_shock_incidence(
    kind: str,
    size: float,
    year: int = 2026,
    persistence: float = 0.9,
    horizon: int = HANK_DEFAULT_HORIZON,
    variant: str = "two_asset",
    income_concept: str = "wage_bill",
    start_year: int = 2026,
    dataset: str | None = None,
    hank_payload: dict | None = None,
) -> dict:
    """Household-level incidence of a US HANK shock (experimental).

    ``hank_payload`` accepts a pre-computed hank_shock result so the HANK
    solve and the microsim can run in separate processes on
    memory-constrained machines (same two-step escape hatch as
    ``frbus_payload`` / ``og_payload``). The payload's kind/size must match
    the arguments; mixing is refused. When a payload is given,
    ``persistence``/``horizon``/``variant`` are ignored — the payload's own
    solve parameters govern the shock, not these arguments.

    Same pattern as frbus_shock_incidence: hank_shock (which surfaces the
    pre-tax real wage w and labor N IRFs, % deviations from steady state)
    -> EconomicAssumptions.from_hank_result (annual mean over ``year``'s
    quarters; HANK quarters are offsets from the shock start, which
    ``start_year`` maps to that calendar year's Q1) -> a pre-tax earnings
    factor scaling the US microsim's employment-income inputs, reform-free.

    The result is the shock's incidence through the automatic stabilizers
    around the model's CALIBRATED steady state — HANK is a stylized model,
    not a forecaster, and it still has no PolicyEngine-reform bridge
    (score_reform keeps refusing model='hank'). US only.
    """
    from policyengine_macro.assumptions import (
        SCALED_INPUT_VARIABLES, EconomicAssumptions,
    )

    if hank_payload is not None:
        got = (hank_payload.get("kind"), hank_payload.get("size"))
        if got != (kind, float(size)):
            raise ValueError(
                f"hank_payload was produced for kind {got[0]!r} size "
                f"{got[1]!r}, not for {kind!r} size {size!r}; refusing to "
                "mix them — pass the unmodified output of hank_shock"
            )
        payload = hank_payload
    else:
        payload = hank_shock(
            kind=kind, size=size, persistence=persistence, horizon=horizon,
            variant=variant,
        )
    ea = EconomicAssumptions.from_hank_result(
        payload, year=year, income_concept=income_concept,
        start_year=start_year,
    )
    modifier = ea.input_scaling_modifier()
    micro = _pe_population_incidence(
        country="us", year=year, dataset=dataset, modifier=modifier,
        label=f"HANK {kind} {size:+g} earnings incidence ({year})",
    )

    assumptions = ea.assumption_strings()
    caveats = ea.caveat_strings() + [
        "automatic-stabilizer incidence of a stylized macro shock, not a "
        "reform score: HANK has no PolicyEngine-reform bridge, and policy "
        "is identical on both sides of this comparison",
    ]
    out = {
        "model": "US HANK shock + PolicyEngine population microsimulation",
        "country": "us",
        "year": int(year),
        "income_concept": income_concept,
        "start_year": int(start_year),
        "hank": payload,
        "economic_assumptions": ea.model_dump(),
        "application": {
            "method": "input-scaling",
            "variables_tried": list(SCALED_INPUT_VARIABLES),
            "earnings_factor": ea.earnings_factor,
            "applied": modifier is not None,
        },
        "microsim": micro,
        "assumptions": assumptions,
        "caveats": caveats,
    }
    out["score"] = _incidence_score_block(
        model_id="hank+microsim",
        model_class="hank overlay on microsim",
        analysis_type="shock incidence (experimental)",
        country="us",
        year=year,
        reform={},
        micro=micro,
        assumptions=assumptions,
        caveats=caveats,
        baseline=(
            f"PolicyEngine baseline policy for {year}, with US HANK "
            f"{kind} {size:+g} wage/labor deviations applied as a "
            "pre-tax earnings overlay"
        ),
        data_vintage=(
            f"PolicyEngine dataset {micro.get('dataset', dataset or 'default')}; "
            "Auclert-Bardóczy-Rognlie-Straub (2021) calibration"
        ),
        horizon=f"annual {year}, transition-quarter average deviations",
        basis_suffix=(
            "from the macro shock through the automatic stabilizers "
            "(no reform)"
        ),
    )
    return out


# The SHORT curated list of UK parameters that CPI inflation uprates by
# statute: working-age benefit and Child Benefit rates are uprated each
# April by the previous September's CPI (Social Security Administration Act
# 1992 s.150, as amended; annual Benefits Up-rating Orders). Deliberately
# EXCLUDED, and stated in caveats: the state pension (triple lock — highest
# of CPI, earnings, 2.5%, not a pure CPI link), income tax and NI
# thresholds (frozen by statute through the current freeze), Local Housing
# Allowance rates (frozen/periodically reset), and the benefit cap (not
# routinely uprated). Paths must resolve through pe.uk.model.get_parameter;
# svar_inflation_incidence errors clearly on any that do not.
SVAR_CPI_UPRATED_PARAMETERS = [
    {
        "path": "gov.dwp.universal_credit.standard_allowance.amount.SINGLE_OLD",
        "description": "Universal Credit standard allowance, single 25+",
        "unit": "GBP per month",
    },
    {
        "path": "gov.dwp.universal_credit.standard_allowance.amount.COUPLE_OLD",
        "description": "Universal Credit standard allowance, couple 25+",
        "unit": "GBP per month",
    },
    {
        "path": "gov.dwp.universal_credit.elements.child.amount",
        "description": "Universal Credit child element",
        "unit": "GBP per month",
    },
    {
        "path": "gov.hmrc.child_benefit.amount.eldest",
        "description": "Child Benefit, eldest or only child",
        "unit": "GBP per week",
    },
    {
        "path": "gov.hmrc.child_benefit.amount.additional",
        "description": "Child Benefit, additional children",
        "unit": "GBP per week",
    },
]

_SVAR_INCIDENCE_REFERENCES = ("obr", "target")


def _obr_efo_cpi_annual(year: int) -> float:
    """Annual mean of the OBR EFO YoY CPI inflation path (CPIGR) for a year.

    Reads the March 2026 EFO economy tables packaged with the obr_macro
    distribution. Raises with the reference='target' fallback named when the
    package or the year is unavailable.
    """
    try:
        from obr_macro import load_obr_data
    except ImportError as e:
        raise ImportError(
            "reference='obr' needs the obr_macro package for the EFO CPI "
            f"path ({e}). Install it with: pip install "
            "git+https://github.com/PolicyEngine/obr-macroeconomic-model — "
            "or use reference='target' (a flat 2.0% path)."
        ) from e
    import pandas as pd

    series = load_obr_data()["CPIGR"].dropna()
    quarters = [pd.Period(f"{year}Q{q}") for q in (1, 2, 3, 4)]
    missing = [str(q) for q in quarters if q not in series.index]
    if missing:
        raise ValueError(
            f"the packaged OBR EFO CPI path does not cover {missing} "
            f"(available {series.index[0]}-{series.index[-1]}); use a year "
            "inside that window or reference='target'."
        )
    return float(sum(float(series.loc[q]) for q in quarters) / 4.0)


def svar_inflation_incidence(
    year: int = 2027,
    horizons: int = 12,
    draws: int = _SVAR_DEFAULT_DRAWS,
    reference: str = "obr",
    dataset: str | None = None,
) -> dict:
    """Household incidence of the SVAR-vs-reference CPI gap via uprating.

    A price-side mechanism, unlike the earnings-overlay incidence tools:
    if the UK SVAR's median CPI inflation for ``year`` runs above (below)
    the reference path, the statutory CPI uprating of working-age benefits
    the following April is higher (lower). This tool builds that as a REAL
    PolicyEngine reform — each parameter in SVAR_CPI_UPRATED_PARAMETERS is
    scaled by (1 + gap/100) from 6 April ``year+1`` against its baseline
    value in force then — and scores it with the UK population microsim
    for ``year+1``.

    ``reference``: 'obr' (default) compares against the March 2026 EFO CPI
    path packaged with obr_macro; 'target' against a flat 2.0%. The gap is
    an annual-average approximation of the statutory September-CPI
    reference month (stated in caveats).

    Deliberately NOT covered (see SVAR_CPI_UPRATED_PARAMETERS): the state
    pension triple lock, frozen tax/NI thresholds, LHA, the benefit cap.
    Runtime: svar_forecast takes a couple of minutes cold (cached
    in-process, like forecast_uk on the hosted server) plus one microsim
    run. UK only.
    """
    year = int(year)
    if reference not in _SVAR_INCIDENCE_REFERENCES:
        raise ValueError(
            f"reference must be one of {_SVAR_INCIDENCE_REFERENCES}, got "
            f"{reference!r}: 'obr' is the March 2026 EFO CPI path, "
            "'target' a flat 2.0%."
        )

    fc = svar_forecast(horizons=horizons, draws=draws)
    quarters = [f"{year}Q{q}" for q in (1, 2, 3, 4)]
    cpi_rows = {r["quarter"]: r for r in fc["cpi_inflation_yoy"]}
    absent = [q for q in quarters if q not in cpi_rows]
    if absent:
        origin_year, origin_q = fc["forecast_origin"].split("Q")
        needed = (year - int(origin_year)) * 4 + (4 - int(origin_q))
        raise ValueError(
            f"the SVAR forecast (origin {fc['forecast_origin']}, horizons="
            f"{horizons}) does not cover {absent}; re-run with horizons>="
            f"{needed} (max {_SVAR_MAX_HORIZONS})."
        )
    svar_cpi = sum(float(cpi_rows[q]["median"]) for q in quarters) / 4.0

    if reference == "obr":
        ref_cpi = _obr_efo_cpi_annual(year)
        ref_desc = ("OBR March 2026 EFO CPI inflation path (CPIGR, annual "
                    f"mean of the {year} quarters)")
    else:
        ref_cpi = 2.0
        ref_desc = "flat 2.0% inflation target"
    gap_pp = svar_cpi - ref_cpi

    pe = _import_pe()
    from datetime import date

    if getattr(pe, "uk", None) is None or pe.uk.model is None:
        raise RuntimeError(
            "policyengine imported without its UK country model; install "
            "policyengine[models] to resolve the uprated parameters."
        )
    apply_date = f"{year + 1}-04-06"
    factor = 1.0 + gap_pp / 100.0
    reform: dict[str, dict] = {}
    parameters = []
    for entry in SVAR_CPI_UPRATED_PARAMETERS:
        path = entry["path"]
        try:
            param = pe.uk.model.get_parameter(path)
        except Exception as e:
            raise ValueError(
                f"could not resolve the curated uprating parameter {path!r} "
                f"in the policyengine-uk parameter tree ({type(e).__name__}: "
                f"{e}). The curated list (SVAR_CPI_UPRATED_PARAMETERS) has "
                "gone stale against upstream — fix the list; refusing to "
                "skip it silently."
            ) from e
        baseline_value = _pe_value_at(param, date(year + 1, 4, 6))
        if baseline_value is None:
            raise ValueError(
                f"the parameter {path!r} has no value in force on "
                f"{apply_date}; cannot build the uprating counterfactual."
            )
        baseline_value = float(baseline_value)
        new_value = baseline_value * factor
        reform[path] = {apply_date: new_value}
        parameters.append({
            **entry,
            "baseline_value": round(baseline_value, 6),
            "counterfactual_value": round(new_value, 6),
        })

    micro = pe_population_impact(
        country="uk", reform=reform, year=year + 1, dataset=dataset,
    )
    # One authoritative score: drop the nested static-microsim score block,
    # as dynamic_population_reform_impact does.
    micro = dict(micro)
    micro.pop("score", None)

    budget_bn = micro["budgetary_impact_bn"]
    assumptions = [
        f"CPI gap: SVAR median YoY CPI for {year} "
        f"({svar_cpi:+.2f}%) minus the reference ({ref_desc}: "
        f"{ref_cpi:+.2f}%) = {gap_pp:+.2f}pp",
        "statutory pass-through: working-age benefit and Child Benefit "
        "rates are CPI-uprated each April (SSAA 1992 s.150 as amended), so "
        f"the gap scales each curated parameter's {apply_date} baseline "
        f"value by {factor:.5f}",
        "annual-average approximation: the statute references September "
        "CPI, this tool the annual mean of the year's four quarters",
    ]
    caveats = [
        "NOT included: the state pension (triple lock, not a pure CPI "
        "link), income tax and NI thresholds (frozen by statute), Local "
        "Housing Allowance, and the benefit cap — the true fiscal "
        "sensitivity to inflation is larger than this curated slice",
        "SVAR median only: the forecast's 68/90% bands are reported in the "
        "embedded svar block but not propagated to the costing",
        "price side only: no earnings or debt-interest channel is applied",
    ]
    out = {
        "model": "UK SVAR CPI gap + PolicyEngine population microsimulation",
        "country": "uk",
        "year": int(year),
        "uprating_year": year + 1,
        "reference": reference,
        "reference_description": ref_desc,
        "svar_cpi_yoy_pct": round(svar_cpi, 3),
        "reference_cpi_yoy_pct": round(ref_cpi, 3),
        "cpi_gap_pp": round(gap_pp, 3),
        "svar": {
            "forecast_origin": fc["forecast_origin"],
            "provenance": fc["provenance"],
            "draws": fc["draws"],
            "accepted_draws": fc["accepted_draws"],
            "ess": fc["ess"],
            "warnings": fc["warnings"],
            "cpi_inflation_yoy": [cpi_rows[q] for q in quarters],
        },
        "parameters": parameters,
        "reform": reform,
        "microsim": micro,
        "assumptions": assumptions,
        "caveats": caveats,
        "headline": (
            f"If CPI inflation runs {gap_pp:+.2f}pp against the reference "
            f"in {year}, the April {year + 1} uprating of these benefits "
            f"{'saves' if budget_bn >= 0 else 'costs'} "
            f"£{abs(budget_bn):.1f}bn/year."
        ),
    }
    out["score"] = _incidence_score_block(
        model_id="svar+microsim",
        model_class="svar overlay on microsim",
        analysis_type="inflation uprating incidence (experimental)",
        country="uk",
        year=year + 1,
        reform=reform,
        micro=micro,
        assumptions=assumptions,
        caveats=caveats,
        baseline=(
            f"PolicyEngine baseline policy for {year + 1}, uprating gap "
            f"referenced to {ref_desc}"
        ),
        data_vintage=(
            f"PolicyEngine dataset {micro.get('dataset', dataset or 'default')}; "
            f"UK SVAR conditioned through {fc['forecast_origin']}"
        ),
        horizon=f"annual {year + 1} (April uprating of the {year} CPI gap)",
        basis_suffix=(
            "from CPI-gap-scaled statutory uprating of the curated "
            "benefit parameters"
        ),
    )
    return out


# ---------------------------------------------------------------------------
# Unified reform scoring across the suite
# ---------------------------------------------------------------------------

SCORE_MODELS = ("og", "obr", "microsim", "og+microsim")

# Models that exist in the suite but deliberately have NO PolicyEngine-reform
# bridge, mapped to the error explaining what to use instead. score_reform must
# never silently accept one of these and return a number: there is no mapping
# from a PolicyEngine reform to these models' levers, so anything it returned
# would be a plausible-looking wrong answer.
SCORE_MODELS_WITHOUT_REFORM_BRIDGE = {
    "frbus": (
        "FRB/US has no PolicyEngine-reform bridge, by design: there is no "
        "mapping today from a PolicyEngine US reform to FRB/US fiscal levers, "
        "and inventing one would produce plausible-looking wrong numbers. Raw "
        "variable shocks are the supported entry point — use the frbus_shock "
        "tool (or `pe-macro frbus-shock`) with a lever and shock size in model "
        "units, and frbus_list_variables to discover the levers and their "
        "units. For who bears a FRB/US shock at household resolution "
        "(deciles, winners/losers through the automatic stabilizers), use "
        "frbus_shock_incidence (`pe-macro frbus-shock-incidence`)."
    ),
    "hank": (
        "The US HANK member has no PolicyEngine-reform bridge, by design: it "
        "scores stylized aggregate shocks (monetary, fiscal_spending, "
        "productivity), not detailed tax reforms, and no mapping exists from "
        "a PolicyEngine US reform to its three exogenous instruments — "
        "inventing one would produce plausible-looking wrong numbers. Use the "
        "hank_shock tool (or `pe-macro hank-shock`) with a shock kind, size "
        "and persistence in model units; hank_summary documents the kinds "
        "and their units. For who bears a HANK shock at household "
        "resolution (deciles, winners/losers through the automatic "
        "stabilizers), use hank_shock_incidence "
        "(`pe-macro hank-shock-incidence`)."
    ),
    "define": (
        "DEFINE-UK has no PolicyEngine-reform bridge, by design: it runs a "
        "curated set of upstream climate-policy scenarios, and no mapping "
        "exists from a PolicyEngine statutory reform to those scenario "
        "definitions — inventing one would produce plausible-looking wrong "
        "numbers. Use the define_scenario tool (or `pe-macro define-scenario "
        "<name>`) with a scenario from define_list_scenarios; it returns "
        "deltas against the model's own baseline, never levels. For who "
        "bears a scenario at household resolution, use "
        "define_scenario_incidence (`pe-macro define-incidence`)."
    ),
    "svar": (
        "The Bank of England SVAR has no PolicyEngine-reform bridge, by "
        "design: it is the baseline/conditioning member — it identifies "
        "shocks and forecasts the economy that reforms are scored against, "
        "and no mapping exists from a PolicyEngine reform to its structural "
        "shocks, so inventing one would produce plausible-looking wrong "
        "numbers. Use forecast_uk (`pe-macro forecast`) for the outlook and "
        "latest_shocks (`pe-macro shocks`) for the identified shocks. To "
        "score a reform against that economy, use model='obr'. For who bears "
        "the SVAR's inflation path at household resolution, use "
        "svar_inflation_incidence (`pe-macro svar-inflation-incidence`)."
    ),
}
SCORE_MODELS_WITHOUT_REFORM_BRIDGE["us-hank"] = (
    SCORE_MODELS_WITHOUT_REFORM_BRIDGE["hank"]
)
SCORE_MODELS_WITHOUT_REFORM_BRIDGE["define-uk"] = (
    SCORE_MODELS_WITHOUT_REFORM_BRIDGE["define"]
)
# The site prints "frb-us"; the registry key for the refusal was only "frbus",
# so the id a reader copies off the page fell through to the bare enum error
# while every other display id got the written-for-it explanation.
SCORE_MODELS_WITHOUT_REFORM_BRIDGE["frb-us"] = (
    SCORE_MODELS_WITHOUT_REFORM_BRIDGE["frbus"]
)
SCORE_MODELS_WITHOUT_REFORM_BRIDGE["boe-svar"] = (
    SCORE_MODELS_WITHOUT_REFORM_BRIDGE["svar"]
)


def _validate_reform(reform) -> None:
    """Backwards-compatible alias: validate and discard the normalised form."""
    validate_reform(reform)


def score_reform(
    country: str,
    reform: dict,
    model: str,
    start_year: int = 2026,
    max_iter: int = OG_DEFAULT_MAX_ITER,
    years: int = 5,
    dataset: str | None = None,
) -> dict:
    """Score a PolicyEngine reform with one of the suite's scoring models.

    One reform vocabulary across the suite: ``reform`` is the same flat
    {parameter_path: value} dict the microsimulation tools take
    (pe_population_impact, pe_household_impact). Each model consumes it
    through its declared contract, and every result carries a common
    ``"score"`` block (ScoreResult, issue #10) so results are comparable
    side by side:

    - "og": the reform enters through PolicyEngine-estimated tax functions
      (long-run steady-state general-equilibrium comparison; UK only).
      Extra arg: max_iter.
    - "obr": the microsim static-costing bridge (issue #9): PolicyEngine
      population costing per year in the window enters the OBR emulator as
      an HHDI shock path; second-round demand effects come out. UK only.
      Extra args: years (window length), dataset. Raw exogenous-variable
      shocks in model units remain available via obr_shock.
    - "microsim": PolicyEngine population microsimulation itself (static
      annual costing + distribution, no macro feedback). UK or US.
      Extra arg: dataset.
    - "og+microsim": dynamic scoring (issue #11): OG-UK long-run wage and
      labour-supply changes become an EconomicAssumptions overlay applied
      as direct input scaling of the reform simulation's employment-income
      arrays, scored against the stock baseline. UK only. Extra args:
      max_iter, dataset.

    "frbus", "hank"/"us-hank", "define"/"define-uk" and "svar"/"boe-svar" are
    deliberately NOT accepted and raise an explanation naming the tool to use
    instead (see SCORE_MODELS_WITHOUT_REFORM_BRIDGE). None of them has a
    PolicyEngine-reform bridge, so returning a number would be a
    plausible-looking wrong answer.
    """
    # Checked before country/reform validation so the caller gets the real
    # reason ("frbus has no reform bridge") rather than being sent off to fix
    # an unrelated argument first.
    if model in SCORE_MODELS_WITHOUT_REFORM_BRIDGE:
        raise ValueError(SCORE_MODELS_WITHOUT_REFORM_BRIDGE[model])
    country = _validate_country(country)
    reform = validate_reform(reform)
    if model not in SCORE_MODELS:
        prefix = "model is required and " if model is None else ""
        raise ValueError(
            f"{prefix}model must be one of {SCORE_MODELS}, got {model!r}. "
            "'microsim' is the fast static population costing; 'obr' adds "
            "macro feedback; 'og' is the long-run OLG comparison."
        )
    if model == "og":
        if country != "uk":
            raise ValueError(
                "the OG member is UK-only (OG-UK); country must be 'uk'"
            )
        return og_score_reform(
            reform=reform, start_year=start_year, max_iter=max_iter
        )
    if model == "obr":
        if country != "uk":
            raise ValueError(
                "the OBR member is UK-only; country must be 'uk'"
            )
        return obr_score_reform(
            reform=reform, start_year=start_year, years=years, dataset=dataset
        )
    if model == "microsim":
        return pe_population_impact(
            country=country, reform=reform, year=start_year, dataset=dataset
        )
    if model == "og+microsim":
        if country != "uk":
            raise ValueError(
                "the og+microsim member is UK-only (OG-UK); country must "
                "be 'uk'"
            )
        return dynamic_population_reform_impact(
            country=country, reform=reform, year=start_year,
            dataset=dataset, max_iter=max_iter,
        )
    raise ValueError(f"model must be one of {SCORE_MODELS}, got {model!r}")


# ---------------------------------------------------------------------------
# Cheap summary from the repo's committed results
# ---------------------------------------------------------------------------

def _parse_kv_lines(text: str) -> list[str]:
    return [ln.strip("- ").strip() for ln in text.splitlines()
            if ln.strip().startswith("- ")]


def _parse_md_table(text: str, heading: str) -> list[dict]:
    """Parse the first markdown pipe table after a heading line containing `heading`."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.startswith("#") and heading in ln)
    except StopIteration:
        return []
    rows, header = [], None
    for ln in lines[start + 1:]:
        if ln.strip().startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                continue
            if header is None:
                header = cells
            else:
                rows.append(dict(zip(header, cells)))
        elif header is not None:
            break
    return rows


def svar_summary() -> dict:
    """Parse the SVAR repo's committed results (no estimation; instant).

    Reads summary.md and forecast_summary.md via boe_var.data.results_dir(),
    which resolves the repo checkout when present and the packaged snapshot
    otherwise (so this works from a bare pip install).
    """
    try:
        from boe_var.data import results_dir
        rdir = results_dir()
    except ImportError:
        env = os.environ.get(BOE_VAR_REPO_ENV)
        if not env:
            return {
                "error": (
                    "boe_var is not installed and POLICYENGINE_MACRO_BOE_VAR_REPO is "
                    "not set; install the SVAR package (pip install git+"
                    "https://github.com/PolicyEngine/boe-var-model) or point "
                    "POLICYENGINE_MACRO_BOE_VAR_REPO at a boe-var-model checkout"
                )
            }
        rdir = Path(env) / "results"
    summary_path = rdir / "summary.md"
    fsummary_path = rdir / "forecast_summary.md"
    out: dict = {
        "source": str(rdir),
        "provenance": _provenance(
            model_id="boe-svar",
            distribution="boe-var-model",
            data_vintage="estimation through 2025Q1; conditioning data through 2026Q1",
            baseline="committed replication and forecast artefacts",
        ),
    }

    if summary_path.exists():
        text = summary_path.read_text()
        # Two FEVD tables, and which one a caller compares to the paper
        # matters. ``fevd_1yr_headline`` is the sum of per-shock posterior
        # medians renormalised to 100% — the historical presentation, kept
        # for continuity. ``fevd_1yr_group_shares`` forms the group share on
        # every accepted draw and reports its posterior mean, which is what
        # the paper's Figure 4 plots ("the mean of the sum") and what its
        # ~40% / ~50% refer to. Renormalising inflates the identified shares
        # by about a third here, because the per-shock medians sum to ~0.62
        # (GDP) and ~0.71 (CPI) rather than to 1.
        #
        # The heading match is a substring of the heading rather than the
        # whole of it: the upstream heading gained "(4-quarter-ahead forecast
        # error)" when the off-by-one was fixed, and an exact-ish match
        # returned an empty table with no error anywhere.
        out["replication"] = {
            "metadata": _parse_kv_lines(text.split("##")[0]),
            "fevd_1yr_headline": _parse_md_table(text, "FEVD at"),
            "fevd_1yr_group_shares": _parse_md_table(
                text, "Posterior of the group share"),
            "fevd_note": (
                "fevd_1yr_headline renormalises a sum of per-shock medians to "
                "100%; compare fevd_1yr_group_shares (mean column) to the "
                "paper, which reports shares of total variance and leaves "
                "roughly 20% with the unidentified shocks."
            ),
        }
    else:
        out["replication"] = {"error": f"missing {summary_path}"}

    if fsummary_path.exists():
        text = fsummary_path.read_text()
        out["forecast_revision"] = {
            "metadata": _parse_kv_lines(text.split("##")[0]),
            "latest_shock_signs": _parse_md_table(text, "P(sign)"),
            "composite_irf": _parse_kv_lines(
                text.split("Composite impulse response")[-1].split("##")[0]
            ),
        }
    else:
        out["forecast_revision"] = {"error": f"missing {fsummary_path}"}
    return out


# ---------------------------------------------------------------------------
# DEFINE-UK (local-only): curated climate-policy scenario deltas.
# The upstream R code is unlicensed and never hosted; the adapter package
# `define_uk` reads a locally cached run at a pinned commit. On the hosted
# server (or any environment without the package/cache) these functions
# return run instructions instead of raising — the same local-only contract
# as the OG model.

_DEFINE_INSTRUCTIONS = {
    "model": "define-uk",
    "available": False,
    "how_to_run": (
        "DEFINE-UK is local-only (unlicensed upstream; never hosted). "
        "Install the adapter: pip install "
        "git+https://github.com/PolicyEngine/define-uk-model — then produce "
        "the cached run once with `python -c \"import define_uk.runner as r; "
        "r.run()\"` (needs R >= 4.0 with the upstream packages) and rerun "
        "this command. Results are scenario DELTAS vs baseline, experimental."
    ),
}


def define_list_scenarios() -> dict:
    """Curated DEFINE-UK scenario registry, or run instructions if the
    local adapter/cache is unavailable."""
    try:
        from define_uk import scenarios as _sc
        return {"model": "define-uk", "available": True,
                "scenarios": _sc.list_scenarios()}
    except ImportError:
        return dict(_DEFINE_INSTRUCTIONS)


# Extra series the microsim incidence overlay needs on top of the default
# reporting variables: nominal household disposable income, the price
# level, and the real wage.
DEFINE_INCIDENCE_VARIABLES = ("YD_HH", "P", "WR")


def define_scenario(
    name: str, horizon_years: int = 15, incidence: bool = False
) -> dict:
    """Annualised scenario deltas vs baseline from the cached pinned
    upstream run, with mandatory deltas-only framing; or run instructions
    if the local adapter/cache is unavailable.

    ``incidence=True`` adds DEFINE_INCIDENCE_VARIABLES to the returned
    series, producing a payload define_scenario_incidence accepts."""
    try:
        from define_uk import scenarios as _sc
    except ImportError:
        return dict(_DEFINE_INSTRUCTIONS)
    variables = _sc.DEFAULT_VARIABLES + DEFINE_INCIDENCE_VARIABLES \
        if incidence else _sc.DEFAULT_VARIABLES
    try:
        result = _sc.run_scenario(
            name, variables=variables, horizon_years=horizon_years,
        )
    except FileNotFoundError as e:
        out = dict(_DEFINE_INSTRUCTIONS)
        out["error"] = str(e)
        return out
    except (KeyError, ValueError) as e:
        # Unknown scenario name (or bad horizon): the adapter IS installed,
        # so install instructions would mislead — point at the listing tool.
        return {
            "model": "define-uk",
            "available": False,
            "error": f"Unknown DEFINE-UK scenario {name!r}: {e}",
            "how_to_run": (
                "Run `pe-macro define-scenarios` (or the "
                "define_list_scenarios tool) to list the valid scenario "
                "names, then retry with one of them."
            ),
        }
    result["model"] = "define-uk"
    result["available"] = True
    return result


def define_scenario_incidence(
    scenario: str,
    year: int = 2030,
    income_concept: str = "disposable_income",
    dataset: str | None = None,
    define_payload: dict | None = None,
) -> dict:
    """Household-level incidence of a DEFINE-UK climate-policy scenario
    (experimental): who bears the scenario, household by household.

    ``define_payload`` accepts a pre-computed define_scenario result (run
    with ``incidence=True`` / `pe-macro define-scenario <name> --incidence
    --json`) so the DEFINE deltas and the microsim can run in separate
    environments — the SAME local-only contract as everything DEFINE: the
    unlicensed upstream never runs hosted, but its numeric deltas may
    travel. On a host without the adapter and without a payload, this
    returns run instructions instead of results. The payload's scenario
    must match the argument; mixing is refused.

    Pipeline (mirrors frbus_shock_incidence / hank_shock_incidence):
      1. define_scenario with the incidence variables (YD_HH, P, WR —
         annual % deltas vs baseline);
      2. EconomicAssumptions.from_define_scenario — the ``year`` delta
         becomes a pre-tax earnings factor ('disposable_income' =
         YD_HH% − P%, 'real_wage' = WR%);
      3. the factor scales the UK population microsimulation's
         employment-income inputs (reform-free: policy is identical on
         both sides), so deciles/winners/losers and the budget change are
         the scenario's incidence THROUGH THE AUTOMATIC STABILIZERS.

    NOT reform scoring: score_reform keeps refusing model='define' (no
    statute mapping). UK only. Deltas only, never levels.
    """
    from policyengine_macro.assumptions import (
        SCALED_INPUT_VARIABLES, EconomicAssumptions,
    )

    if define_payload is not None:
        got = define_payload.get("scenario")
        if got != scenario:
            raise ValueError(
                f"define_payload was produced for scenario {got!r}, not "
                f"{scenario!r}; refusing to mix them — pass the unmodified "
                "output of `pe-macro define-scenario "
                f"{scenario} --incidence --json`"
            )
        payload = define_payload
    else:
        payload = define_scenario(scenario, incidence=True)
        if not payload.get("available"):
            out = dict(payload)
            out["how_to_run"] = (
                "DEFINE-UK incidence needs the scenario deltas. Either run "
                "locally with the adapter installed, or produce the deltas "
                "on a machine that has it — `pe-macro define-scenario "
                f"{scenario} --incidence --json > deltas.json` — and pass "
                "them via define_payload (MCP) / --define-payload (CLI): "
                "only numbers travel, never the unlicensed upstream code. "
                + out.get("how_to_run", "")
            )
            return out

    ea = EconomicAssumptions.from_define_scenario(
        payload, year=year, income_concept=income_concept,
    )
    modifier = ea.input_scaling_modifier()
    micro = _pe_population_incidence(
        country="uk", year=year, dataset=dataset, modifier=modifier,
        label=f"DEFINE-UK {scenario} earnings incidence ({year})",
    )

    assumptions = ea.assumption_strings()
    caveats = ea.caveat_strings() + list(payload.get("caveats", []))
    out = {
        "model": "DEFINE-UK scenario + PolicyEngine population "
                 "microsimulation",
        "available": True,
        "country": "uk",
        "scenario": scenario,
        "year": int(year),
        "income_concept": income_concept,
        "define": payload,
        "economic_assumptions": ea.model_dump(),
        "application": {
            "method": "input-scaling",
            "variables_tried": list(SCALED_INPUT_VARIABLES),
            "earnings_factor": ea.earnings_factor,
            "applied": modifier is not None,
        },
        "microsim": micro,
        "assumptions": assumptions,
        "caveats": caveats,
    }
    out["score"] = _incidence_score_block(
        model_id="define+microsim",
        model_class="ecological SFC overlay on microsim",
        analysis_type="scenario incidence (experimental)",
        country="uk",
        year=year,
        reform={},
        micro=micro,
        assumptions=assumptions,
        caveats=caveats,
        baseline=(
            f"PolicyEngine baseline policy for {year}, with the DEFINE-UK "
            f"{scenario} scenario's {year} deltas applied as a pre-tax "
            "earnings overlay"
        ),
        data_vintage=(
            f"PolicyEngine dataset {micro.get('dataset', dataset or 'default')}; "
            "DEFINE-UK 1.1 upstream at pinned commit 846081a"
        ),
        horizon=f"annual {year}, one calendar year of the delta path",
        basis_suffix=(
            "from the climate-policy scenario through the automatic "
            "stabilizers (no reform)"
        ),
    )
    return out
