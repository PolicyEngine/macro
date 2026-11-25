"""Upstream contract tests: every name this package hardcodes must still
exist upstream.

The adapters compose upstream packages but necessarily hardcode a few names —
curated parameter paths, headline output-variable names, SVAR column names.
These tests fail loudly when an upstream rename would otherwise surface as a
silent drift (stale baseline, mislabeled series) or a runtime AttributeError.

The boe_var checks are fast and run by default. The PolicyEngine checks need
the full country models (~20s import) and are marked `slow`
(`pytest --runslow`); they also run implicitly wherever PE is installed,
e.g. the Modal image.
"""

import importlib
import os

import pytest

from policyengine_macro import core


def _import_or_require(modname: str):
    """Import an upstream module; in the dedicated contract job
    (POLICYENGINE_MACRO_REQUIRE_PE=1) a missing/broken install FAILS instead of
    skipping — a contract run that silently skips is vacuous."""
    require = os.environ.get("POLICYENGINE_MACRO_REQUIRE_PE") == "1"
    try:
        return importlib.import_module(modname)
    except Exception as e:
        msg = f"{modname} not importable: {type(e).__name__}: {e}"
        pytest.fail(msg) if require else pytest.skip(msg)


# ---------------------------------------------------------------------------
# Pinned-model gates (slow; the nightly contract job installs the pins)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_svar_data_edge_strings_match_the_pinned_data():
    """The registry and model_summary state the SVAR data edge by hand.

    They went stale once already: after the 2026Q2 dataset was pinned they
    said 2026Q1 for a month (macro #225), while forecast_uk, which reads the
    edge from the data, said 2026Q2. This reads the last quarter of the
    installed data and fails when either string disagrees.

    Slow-marked on purpose: the fast CI job installs boe_var from its HEAD,
    not the pin, so there the data can run ahead of these strings without
    anything being wrong here. The nightly contract job installs the pin.
    """
    data = _import_or_require("boe_var.data")
    from policyengine_macro import capabilities

    edge = str(data.load_data().index[-1])
    entry = capabilities.MODELS["boe-svar"]
    assert entry["data_edge"] == edge, (
        f"capabilities.MODELS['boe-svar']['data_edge'] says "
        f"{entry['data_edge']!r}; the installed boe_var data ends {edge}"
    )
    assert edge in entry["data_vintage"], entry["data_vintage"]
    vintage = core.svar_summary()["provenance"]["data_vintage"]
    assert f"conditioning data through {edge}" in vintage, vintage
    assert core._SVAR_EST_END <= edge


@pytest.mark.slow
def test_obr_household_lever_is_symmetric_and_linear():
    """A reform and its mirror image must score as mirror images.

    score_reform(model="obr") injects the costing through HHDI_ADDFACTOR, so
    its GDP figure is a difference of two solves on this lever. On 6 Nov
    2026, at a pin where no quarter converged, +1000 and -1000 differed by
    32% of the peak response and doubling the shock missed by 16% (macro
    #215). At obr-macroeconomic-model 0e44ec8 both are 0.15%. The bound is
    2% of the peak: loose enough for a re-pin to move it, tight enough that
    a return of solver residue fails.
    """
    _import_or_require("obr_macro")
    run_reform = core._import_obr()

    def solve(shock: float) -> list[float]:
        df = run_reform(
            name=f"HHDI_ADDFACTOR {shock:+g}", var="HHDI_ADDFACTOR",
            shock=shock, start=core._OBR_START, end=core._OBR_DEFAULT_END,
            periods=8, investment_closure=False,
        )
        assert df.attrs.get("solver_converged") is True, (
            shock, df.attrs.get("solver_nonconverged_periods")
        )
        return [float(v) for v in df.delta_gdp_bn]

    up, down, double = solve(1000.0), solve(-1000.0), solve(2000.0)
    peak = max(abs(v) for v in up)
    assert peak > 0.05, f"the household lever barely moved GDP: {up}"
    # Revenue raised lowers GDP in every quarter, and the mirror raises it.
    assert all(v < 0 for v in up) and all(v > 0 for v in down)
    asymmetry = max(abs(a + b) for a, b in zip(up, down)) / peak
    nonlinearity = max(abs(c - 2 * a) for a, c in zip(up, double)) / peak
    assert asymmetry < 0.02, f"+1000 and -1000 differ by {asymmetry:.1%} of peak"
    assert nonlinearity < 0.02, f"+2000 is {nonlinearity:.1%} of peak from 2 x +1000"


# ---------------------------------------------------------------------------
# boe_var (fast)
# ---------------------------------------------------------------------------

def test_svar_headline_columns_exist_upstream():
    data = _import_or_require("boe_var.data")
    for col in (core._COL_CPI, core._COL_GDP):
        assert col in data.COLUMNS, (
            f"boe_var.data.COLUMNS no longer contains {col!r}; "
            "the SVAR headline series lookup would fail"
        )


def test_svar_identified_schema_aligned():
    """WORLD_SHOCKS + UK_SHOCKS is the canonical schema the adapter uses;
    SHOCK_NAMES must stay positionally aligned with it (an upstream reorder
    must fail here, not silently shift UK shock probabilities)."""
    analysis = _import_or_require("boe_var.analysis")
    identified = sorted(analysis.WORLD_SHOCKS + analysis.UK_SHOCKS)
    assert len(identified) == 6 and len(set(identified)) == 6
    assert all(0 <= j < len(analysis.SHOCK_NAMES) for j in identified)
    assert all(
        not analysis.SHOCK_NAMES[j].startswith("Unident") for j in identified
    ), [analysis.SHOCK_NAMES[j] for j in identified]
    unidentified = [
        analysis.SHOCK_NAMES[j]
        for j in range(len(analysis.SHOCK_NAMES))
        if j not in identified
    ]
    assert all(n.startswith("Unident") for n in unidentified), unidentified
    # Semantic alignment, not just structure: a swap of e.g. UK demand/supply
    # labels would silently relabel probabilities — pin the exact names.
    assert tuple(
        analysis.SHOCK_NAMES[j] for j in analysis.WORLD_SHOCKS
    ) == ("World demand", "World energy", "World supply")
    assert tuple(
        analysis.SHOCK_NAMES[j] for j in analysis.UK_SHOCKS
    ) == ("UK demand", "UK supply", "UK mon. pol.")


# ---------------------------------------------------------------------------
# PolicyEngine (slow: full country-model import)
# ---------------------------------------------------------------------------

# Every variable name _pe_summary and pe_population_impact read off results.
PE_VARIABLE_CONTRACT = {
    "uk": [
        "income_tax", "national_insurance", "hbai_household_net_income",
        "household_tax", "household_benefits", "universal_credit",
        "child_benefit",
        # population scoring
        "gov_balance", "gov_tax", "household_net_income",
        "household_income_decile",
    ],
    "us": [
        "income_tax", "employee_payroll_tax", "state_income_tax", "ctc",
        "eitc", "household_net_income", "household_tax",
        "household_benefits",
    ],
}


def _pe_model(country):
    # importorskip only catches ImportError; a broken policyengine install
    # (e.g. a pydantic version mismatch) raises other exceptions at import
    # time and should also skip, not error. In the dedicated contract job
    # (POLICYENGINE_MACRO_REQUIRE_PE=1) a missing/broken install FAILS instead: a
    # contract run that silently skips every contract is vacuous.
    require = os.environ.get("POLICYENGINE_MACRO_REQUIRE_PE") == "1"
    try:
        import policyengine as pe
    except Exception as e:
        msg = f"policyengine not importable: {type(e).__name__}: {e}"
        pytest.fail(msg) if require else pytest.skip(msg)
    country_mod = getattr(pe, country, None)
    if country_mod is None:
        msg = f"policyengine has no {country} country model (base-only install)"
        pytest.fail(msg) if require else pytest.skip(msg)
    return country_mod.model


@pytest.mark.slow
@pytest.mark.parametrize("entry", core.PE_PARAMETERS,
                         ids=lambda e: f"{e['country']}:{e['path']}")
def test_curated_parameter_paths_resolve(entry):
    model = _pe_model(entry["country"])
    model.get_parameter(entry["path"])  # raises ValueError if renamed away


@pytest.mark.slow
@pytest.mark.parametrize("country", sorted(PE_VARIABLE_CONTRACT))
def test_hardcoded_variable_names_exist(country):
    model = _pe_model(country)
    missing = []
    for name in PE_VARIABLE_CONTRACT[country]:
        try:
            model.get_variable(name)
        except ValueError:
            missing.append(name)
    assert not missing, (
        f"{country} model no longer defines {missing}; "
        "_pe_summary/pe_population_impact would break or silently change"
    )


@pytest.mark.slow
def test_parameters_resolve_live_with_baselines():
    _pe_model("uk")  # skip cleanly when policyengine is not importable
    out = core.pe_list_common_parameters()
    broken = [(p["path"], p.get("live_error")) for p in out if not p.get("live")]
    assert not broken, f"parameter paths failed live resolution: {broken}"
    no_baseline = [p["path"] for p in out if p.get("baseline_value") is None]
    assert not no_baseline, f"no current baseline value for: {no_baseline}"
