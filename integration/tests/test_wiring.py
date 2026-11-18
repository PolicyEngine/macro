"""Wiring / integration tests.

Verify that everything is bolted together: every MCP tool is registered with a
description and schema and dispatches to core; every CLI subcommand runs and
emits valid JSON with --json; and the adapters reject bad input with clear
errors instead of crashing.

Kept fast: the introspection and pure-Python paths need no heavy model import,
and the couple of checks that touch a model (SVAR summary via boe_var) skip
cleanly when it is unavailable. Full solves live behind the `slow` marker, so
this whole module runs in the default (non-slow) suite in seconds.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from policyengine_macro import core, mcp_server
from policyengine_macro.cli import main

# The full tool surface the server must expose (README + mcp_server.py).
EXPECTED_TOOLS = {
    "score_reform",
    "list_reform_variables",
    "forecast_uk",
    "latest_shocks",
    "model_summary",
    "calculate_household",
    "household_reform_impact",
    "list_reform_parameters",
    "population_reform_impact",
    "obr_shock",
}


# ---------------------------------------------------------------------------
# MCP tool registration + schemas
# ---------------------------------------------------------------------------

def _registered_tools() -> dict:
    return {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}


def test_all_mcp_tools_registered():
    assert EXPECTED_TOOLS <= set(_registered_tools())


def test_mcp_tools_have_descriptions_and_object_schemas():
    for name, tool in _registered_tools().items():
        assert tool.description and tool.description.strip(), f"{name}: no description"
        schema = tool.inputSchema
        assert isinstance(schema, dict), f"{name}: no input schema"
        assert schema.get("type") == "object", f"{name}: schema not an object"


@pytest.mark.parametrize(
    "tool, params",
    [
        ("score_reform", {"country", "reform", "model"}),
        ("obr_shock", {"var", "shock", "periods"}),
        ("forecast_uk", {"horizons", "draws"}),
        ("latest_shocks", {"draws"}),
        ("calculate_household", {"country", "people"}),
        ("household_reform_impact", {"country", "people", "reform"}),
        ("population_reform_impact", {"country", "reform"}),
    ],
)
def test_mcp_tool_schema_exposes_expected_params(tool, params):
    props = set(_registered_tools()[tool].inputSchema.get("properties", {}))
    assert params <= props, f"{tool} missing {params - props}"


def test_expensive_mcp_inputs_publish_safe_schema_bounds():
    tools = _registered_tools()
    obr_periods = tools["obr_shock"].inputSchema["properties"]["periods"]
    forecast = tools["forecast_uk"].inputSchema["properties"]
    shocks_draws = tools["latest_shocks"].inputSchema["properties"]["draws"]

    # 25 = 2025Q1..2031Q1, the OBR databank window (core._OBR_MAX_PERIODS).
    assert (obr_periods["minimum"], obr_periods["maximum"]) == (1, core._OBR_MAX_PERIODS) == (1, 25)
    assert (forecast["horizons"]["minimum"], forecast["horizons"]["maximum"]) == (
        1,
        40,
    )
    assert (forecast["draws"]["minimum"], forecast["draws"]["maximum"]) == (
        50,
        10_000,
    )
    assert (shocks_draws["minimum"], shocks_draws["maximum"]) == (50, 10_000)


# ---------------------------------------------------------------------------
# MCP thin wrappers dispatch to core (instant tools, no heavy solve)
# ---------------------------------------------------------------------------

def test_mcp_list_reform_variables_wired():
    out = mcp_server.list_reform_variables()
    assert isinstance(out, list) and out
    assert {"CGG", "TCPRO"} <= {v["var"] for v in out}
    json.dumps(out)


def _no_pe():
    raise ImportError("fast suite: static catalogue only")


def test_mcp_list_reform_parameters_wired(monkeypatch):
    monkeypatch.setattr(core, "_import_pe", _no_pe)
    out = mcp_server.list_reform_parameters()
    assert isinstance(out, list) and len(out) >= 8
    assert all({"country", "path", "description", "unit"} <= set(p) for p in out)
    json.dumps(out)


def test_mcp_model_summary_wired():
    pytest.importorskip("boe_var")
    out = mcp_server.model_summary()
    assert {"replication", "forecast_revision"} <= set(out)
    json.dumps(out)


# ---------------------------------------------------------------------------
# CLI subcommands run and emit valid JSON with --json
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


def _json_ok(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_cli_help_lists_all_commands(runner):
    out = runner.invoke(main, ["--help"]).output
    for cmd in [
        "score", "compare", "obr-shock", "variables", "forecast", "shocks", "summary",
        "parameters", "household", "household-impact", "population-impact",
        "og-score", "og-baseline", "define-scenarios", "define-scenario",
    ]:
        assert cmd in out, f"CLI help missing subcommand {cmd!r}"


def test_cli_variables_json(runner):
    data = _json_ok(runner.invoke(main, ["variables", "--json"]))
    assert isinstance(data, list)
    assert {"CGG", "TCPRO"} <= {v["var"] for v in data}
    for v in data:
        assert {"var", "description", "units", "investment_closure"} <= set(v)


def test_cli_parameters_json(runner, monkeypatch):
    monkeypatch.setattr(core, "_import_pe", _no_pe)
    data = _json_ok(runner.invoke(main, ["parameters", "--json"]))
    assert isinstance(data, list) and len(data) >= 8
    assert all({"country", "path", "description", "unit"} <= set(p) for p in data)


def test_cli_summary_json(runner):
    pytest.importorskip("boe_var")
    data = _json_ok(runner.invoke(main, ["summary", "--json"]))
    assert "replication" in data and "forecast_revision" in data


# ---------------------------------------------------------------------------
# Bad input is reported with a clear error, not a crash
# ---------------------------------------------------------------------------

def test_cli_malformed_json_people(runner):
    res = runner.invoke(main, ["household", "--country", "uk", "--people", "not-json"])
    assert res.exit_code != 0
    assert "valid JSON" in res.output


def test_cli_household_requires_people(runner):
    res = runner.invoke(main, ["household", "--country", "uk"])
    assert res.exit_code != 0
    assert "people" in res.output.lower()


def test_cli_score_requires_reform_and_model(runner):
    res = runner.invoke(main, ["score", "--model", "og"])
    assert res.exit_code != 0
    assert "reform" in res.output.lower()
    res = runner.invoke(main, ["score", "--reform", '{"x": 1}'])
    assert res.exit_code != 0
    assert "model" in res.output.lower()


def test_cli_score_obr_corp_tax_is_clear_error(runner):
    """A corporation-tax reform must be refused with a pointer to the direct
    TCPRO lever, before any heavy model import."""
    res = runner.invoke(main, [
        "score", "--reform", '{"gov.hmrc.corporation_tax.main_rate": 0.2}',
        "--model", "obr",
    ])
    assert res.exit_code != 0
    assert "Traceback" not in res.output
    assert "TCPRO" in res.output


def test_cli_compare_bad_model_is_clean_error(runner):
    # "svar" is no longer a bad model name — it is a known member that refuses
    # reform scoring with an explanation — so an unknown name is needed to
    # exercise the enum fallback.
    res = runner.invoke(main, [
        "compare", "--reform", '{"x": 1}', "--models", "not-a-model",
    ])
    assert res.exit_code != 0
    assert "Traceback" not in res.output
    assert "model must be one of" in res.output


def test_cli_compare_names_the_alternative_for_a_model_that_cannot_score(runner):
    """A member that deliberately has no reform bridge says so, and says what
    to use instead — the whole point of the explicit refusal."""
    res = runner.invoke(main, [
        "compare", "--reform", '{"x": 1}', "--models", "svar",
    ])
    assert res.exit_code != 0
    assert "Traceback" not in res.output
    assert "no PolicyEngine-reform bridge" in res.output
    assert "forecast_uk" in res.output


def test_cli_obr_shock_requires_var(runner):
    res = runner.invoke(main, ["obr-shock", "--shock", "1000"])
    assert res.exit_code != 0
    assert "var" in res.output.lower()


def test_cli_rejects_invalid_country_choice(runner):
    # click.Choice(["uk","us"]) rejects before any model import.
    res = runner.invoke(main, ["household", "--country", "fr", "--people", "[]"])
    assert res.exit_code != 0
    assert "fr" in res.output


# ---------------------------------------------------------------------------
# core adapters reject bad input with a clear error (no heavy import needed:
# these validate before importing the underlying model)
# ---------------------------------------------------------------------------

def test_core_household_bad_country_raises():
    with pytest.raises(ValueError):
        core.pe_household("fr", [{"age": 30}])


def test_core_household_impact_requires_reform():
    with pytest.raises(ValueError):
        core.pe_household_impact("uk", [{"age": 30}], reform={})


def test_core_population_impact_validation():
    with pytest.raises(ValueError):
        core.pe_population_impact("uk", reform={})
    with pytest.raises(ValueError):
        core.pe_population_impact("fr", reform={"x": 1})


# ---------------------------------------------------------------------------
# End-to-end CLI wiring through the real models (slow: OBR solve / PE import)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_cli_obr_shock_json_end_to_end(runner):
    data = _json_ok(runner.invoke(
        main, ["obr-shock", "--var", "CGG", "--shock", "1250", "--periods", "4", "--json"]
    ))
    assert data["var"] == "CGG"
    assert len(data["results"]) >= 4
    assert data["results"][0]["delta_gdp_bn"] > 0


@pytest.mark.slow
def test_cli_forecast_json_end_to_end(runner):
    data = _json_ok(runner.invoke(
        main, ["forecast", "--horizons", "4", "--draws", "100", "--json"]
    ))
    assert data["horizons"] == 4
    assert len(data["gdp_growth_yoy"]) == 4


@pytest.mark.slow
def test_cli_household_json_end_to_end(runner):
    data = _json_ok(runner.invoke(main, [
        "household", "--country", "uk",
        "--people", '[{"age":35,"employment_income":50000}]', "--json",
    ]))
    assert data["currency"] == "GBP"
    assert data["summary"]["income_tax_by_person"][0] > 0


def test_cli_define_scenarios_json_end_to_end(runner):
    # Works in BOTH environments the local-only contract defines: with the
    # define_uk adapter + cached run it returns the scenario registry, and
    # without it (CI, hosted) it returns run instructions — never a crash.
    data = _json_ok(runner.invoke(main, ["define-scenarios", "--json"]))
    assert data["model"] == "define-uk"
    if data["available"]:
        names = {s["name"] for s in data["scenarios"]}
        assert {"fossil_fuel_ban", "green_public_investment"} <= names
    else:
        assert "never hosted" in data["how_to_run"]


def test_cli_define_scenario_json_end_to_end(runner):
    data = _json_ok(runner.invoke(
        main, ["define-scenario", "green_public_investment", "--json"]
    ))
    assert data["model"] == "define-uk"
    if data["available"]:
        assert data["caveats"], "mandatory caveats missing"
        assert "GDP_R" in data["variables"]
        paths = data["variables"]["GDP_R"]
        assert len(data["years"]) == len(paths["delta_level"])
    else:
        assert "how_to_run" in data


def test_cli_define_unknown_scenario_is_clean_error(runner):
    # With the adapter installed, a bogus name must point at the listing
    # command, not traceback; without it, the instructions path serves.
    res = runner.invoke(main, ["define-scenario", "not_a_real_scenario", "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["available"] is False
    assert "how_to_run" in data


@pytest.mark.slow
def test_core_obr_extreme_shock_is_wellformed():
    # An out-of-range shock should still solve to well-formed output, not crash.
    res = core.obr_shock(var="CGG", shock=1_000_000, periods=2)
    assert res["periods"] == 2 and len(res["results"]) >= 2
    json.dumps(res)


def test_cli_obr_shock_closure_tristate(runner, monkeypatch):
    """Omitted --investment-closure must reach core as None (per-variable
    default), not False — the TCPRO zero-effects footgun (review #15.1)."""
    seen = []

    def fake_obr_shock(**kwargs):
        seen.append(kwargs["investment_closure"])
        return {"name": "x", "var": "TCPRO", "shock": -0.05, "periods": 1,
                "investment_closure": True, "results": [],
                "cumulative_delta_gdp_bn_over_shock_periods": 0.0,
                "peak_pct_gdp": 0.0, "peak_period": "2025Q1"}

    monkeypatch.setattr(core, "obr_shock", fake_obr_shock)
    for args, expected in [
        (["obr-shock", "--var", "TCPRO", "--shock", "-0.05", "--json"], None),
        (["obr-shock", "--var", "TCPRO", "--shock", "-0.05",
          "--investment-closure", "--json"], True),
        (["obr-shock", "--var", "TCPRO", "--shock", "-0.05",
          "--no-investment-closure", "--json"], False),
    ]:
        res = runner.invoke(main, args)
        assert res.exit_code == 0, res.output
        assert seen[-1] is expected


def test_cli_wrong_shaped_reform_is_clean_error(runner):
    """Valid JSON of the wrong shape ('[]', '{}') must be a Click error,
    never a traceback (review #15.4)."""
    for cmd in (["score", "--model", "og"], ["og-score"]):
        for bad in ("[]", "{}"):
            res = runner.invoke(main, cmd + ["--reform", bad])
            assert res.exit_code != 0
            assert "Traceback" not in res.output
            assert "non-empty" in res.output


def test_cli_score_names_the_alternative_for_a_model_without_a_reform_bridge(runner):
    """`--model svar` must reach core's explanation, not click's usage error.

    --model was a click.Choice over SCORE_MODELS, so click rejected every
    known-but-unbridgeable member with a bare "invalid choice" listing the
    valid names — the exact unhelpful message core.score_reform was given
    explicit refusals to replace. The refusals existed and no CLI user could
    ever see them.
    """
    for model, expected in (("svar", "forecast_uk"), ("define", "define_scenario")):
        res = runner.invoke(main, [
            "score", "--country", "uk", "--reform", '{"x": 1}', "--model", model,
        ])
        assert res.exit_code != 0
        assert "Traceback" not in res.output
        assert "no PolicyEngine-reform bridge" in res.output, (model, res.output)
        assert expected in res.output, (model, res.output)


def test_cli_score_still_rejects_a_genuinely_unknown_model(runner):
    """Opening up the option must not swallow typos."""
    res = runner.invoke(main, [
        "score", "--country", "uk", "--reform", '{"x": 1}', "--model", "not-a-model",
    ])
    assert res.exit_code != 0
    assert "Traceback" not in res.output
    assert "model must be one of" in res.output


def test_obr_shock_carries_the_lever_caveat_in_the_payload():
    """None of the three OBR levers reads straight, and the payload says so.

    Measured in the model repo: under the default closure CGIPS moves total
    fixed investment by exactly zero in all twelve quarters (business
    investment moves only as an accounting offset), and
    TCPRO's response converges only slowly (a 12-quarter run captures ~40%
    of the plateau, since the 2026-08 log-space anchor fix gave it a steady
    state at all). A docstring does not reach an MCP caller reading a JSON
    result, so the caveat travels with the numbers.

    CGG carries one too, as of 2026-08. It was previously exempt because the
    "~1 by construction" reading was documented on the website -- but the
    website is exactly what an MCP caller never sees, which is the reason
    the other two levers carry caveats at all. Measured at obr 0fe04c9
    (October 2026 EFO): +1250/qtr gives GDP +1.267bn rising to +1.310bn, a multiplier of 1.01
    rising to 1.05, against the OBR's published 0.6 (1.0000 and flat under
    the old published closure). That is the largest published-vs-modelled gap of any
    lever here, so it is the last one that should have shipped silent.
    """
    from policyengine_macro import core

    levers = {v["var"]: v for v in core.obr_list_variables()}
    assert levers["TCPRO"]["caveat"], "the slow-converging lever declares no caveat"
    assert levers["CGIPS"]["caveat"], "the non-transmitting lever declares no caveat"
    assert "default closure" in levers["CGIPS"]["caveat"]
    assert "investment_closure=True" in levers["CGIPS"]["caveat"]
    assert "price_passthrough=True" in levers["VREC"]["caveat"]
    assert "off by default" in levers["VREC"]["caveat"]
    assert levers["CGG"]["caveat"], "the identity lever declares no caveat"
    assert "1.01" in levers["CGG"]["caveat"], "CGG caveat omits the measured multiplier"
    assert "0.6" in levers["CGG"]["caveat"], "CGG caveat omits the OBR published figure"


def test_obr_bank_rate_and_household_levers_are_listed_with_caveats():
    """R and HHDI_ADDFACTOR are the two levers the site's worked examples and
    drift canaries use, yet the variable list named only CGG, TCPRO and CGIPS,
    so an MCP caller could neither discover them nor read their caveats
    (polish run, 16 Nov 2026)."""
    from policyengine_macro import core

    levers = {v["var"]: v for v in core.obr_list_variables()}
    assert "3.5-6 times" in levers["R"]["caveat"]
    assert "pp" in levers["R"]["units"]
    assert "current_price" in levers["HHDI_ADDFACTOR"]["caveat"]
    assert "positive = household income falls" in levers["HHDI_ADDFACTOR"]["units"]


def test_obr_shock_carries_the_household_ratio_on_both_bases(monkeypatch):
    """The household rows are real GDP but the shock is current-price
    revenue; the payload must carry the model's current-price ratio, the
    one comparable with the OBR's 0.3, not leave callers to form the real one."""
    import pandas as pd
    from policyengine_macro import core

    def fake_run_reform(**kw):
        df = pd.DataFrame({
            "period": ["2025Q1", "2025Q2"], "delta_gdp_bn": [-0.15, -0.21],
            "pct_gdp": [-0.02, -0.03], "delta_cons_m": [-150.0, -210.0],
            "delta_if_m": [0.0, 0.0],
        })
        df.attrs.update(
            gdp_per_revenue_current_price=[0.0987, 0.1405],
            gdp_per_revenue_real=[0.0929, 0.1310],
            gdp_per_revenue_basis_note="compare the current-price ratio",
            solver_converged=True, solver_nonconverged_periods=[],
        )
        return df

    monkeypatch.setattr(core, "_import_obr", lambda: fake_run_reform)
    monkeypatch.setattr(core, "_obr_window_end", lambda periods: "2025Q2")
    out = core.obr_shock("HHDI_ADDFACTOR", 1637.5, periods=2)
    assert out["gdp_per_revenue_current_price"] == [0.0987, 0.1405]
    assert out["gdp_per_revenue_real"] == [0.0929, 0.131]
    assert "current-price" in out["gdp_per_revenue_basis_note"]
    assert "current_price" in out["caveat"]


def _obr_frame(attrs=None):
    import pandas as pd

    df = pd.DataFrame({
        "period": ["2025Q1", "2025Q2"], "delta_gdp_bn": [3.075, 3.01],
        "pct_gdp": [0.437, 0.43], "delta_cons_m": [0.0, -1.0],
        "delta_if_m": [3075.4, 3010.0],
    })
    df.attrs.update(solver_converged=True, solver_nonconverged_periods=[])
    df.attrs.update(attrs or {})
    return df


def test_obr_shock_default_call_forwards_no_overlay(monkeypatch):
    """The opt-in routes are opt-in: a default run makes exactly the call it
    made before price_passthrough existed, and the adapter adds no overlay
    label of its own (the model's attrs, absent from this stub, are the only
    source of mechanical_passthrough)."""
    from policyengine_macro import core

    seen = []

    def fake_run_reform(name, var, shock, start, end, periods, investment_closure):
        seen.append(investment_closure)
        return _obr_frame()

    monkeypatch.setattr(core, "_import_obr", lambda: fake_run_reform)
    monkeypatch.setattr(core, "_obr_window_end", lambda periods: "2025Q2")
    for var in ("CGG", "CGIPS", "VREC"):
        out = core.obr_shock(var, 1000.0, periods=2)
        assert "price_passthrough" not in out
        assert "mechanical_passthrough" not in out
    assert seen == [False, False, False], "an opt-in route was on by default"
    assert "does not transmit" in core.obr_shock("CGIPS", 3000.0, periods=2)["caveat"]


def test_obr_shock_cgips_investment_closure_is_labelled_passthrough(monkeypatch):
    """obr #70: under the opt-in investment closure government investment
    reaches GDP as an identity. The payload must not carry the default
    "does not transmit" caveat, and must carry the model's own label."""
    from policyengine_macro import core

    seen = []

    def fake_run_reform(**kw):
        seen.append(kw)
        return _obr_frame({
            "mechanical_passthrough": True,
            "transmission_note": "Investment closure: identity passthrough.",
            "investment_closure_plateau_fraction": None,
        })

    monkeypatch.setattr(core, "_import_obr", lambda: fake_run_reform)
    monkeypatch.setattr(core, "_obr_window_end", lambda periods: "2025Q2")
    out = core.obr_shock("CGIPS", 3000.0, periods=2, investment_closure=True)
    assert seen[0]["investment_closure"] is True
    assert "price_passthrough" not in seen[0]
    assert out["investment_closure"] is True
    assert out["mechanical_passthrough"] is True
    assert "identity passthrough" in out["transmission_note"]
    assert "identity passthrough" in out["caveat"]
    assert "not a validated" in out["caveat"]
    assert "does not transmit" not in out["caveat"]
    assert out["investment_closure_plateau_fraction"] is None


def test_obr_shock_price_passthrough_is_forwarded_and_labelled(monkeypatch):
    """obr #60/#70: the VAT price overlay is forwarded only when asked for,
    and the payload carries the model's judgement-overlay note and CPI shift
    rather than the default run's "no price channel" note."""
    from policyengine_macro import core

    seen = []

    def fake_run_reform(**kw):
        seen.append(kw)
        return _obr_frame({
            "transmission_note": "CPI is exogenous, so there is no price channel.",
            "price_passthrough_note": "Judgement overlay, not the shipped listing.",
            "price_passthrough_detail": {"cpi_pct_delta": [0.4078, 0.3889, 0.3817]},
        })

    monkeypatch.setattr(core, "_import_obr", lambda: fake_run_reform)
    monkeypatch.setattr(core, "_obr_window_end", lambda periods: "2025Q2")
    out = core.obr_shock("VREC", 2200.0, periods=2, price_passthrough=True)
    assert seen[0]["price_passthrough"] is True
    assert seen[0]["investment_closure"] is False
    assert out["price_passthrough"] is True
    assert "Judgement overlay" in out["price_passthrough_note"]
    assert out["cpi_pct_delta"] == [0.4078, 0.3889]
    assert "transmission_note" not in out
    assert "off by default" in out["caveat"]


@pytest.mark.parametrize(
    ("var", "kwargs", "match"),
    [
        ("CGG", {}, "indirect-tax shock"),
        ("HHDI_ADDFACTOR", {}, "indirect-tax shock"),
        ("VREC", {"investment_closure": True}, "demand closure only"),
    ],
)
def test_obr_shock_refuses_a_misapplied_price_passthrough(monkeypatch, var, kwargs, match):
    """The model defines the overlay only for VREC/TXFUEL under the demand
    closure; the adapter refuses anything else before importing the model."""
    from policyengine_macro import core

    def no_import():
        raise AssertionError("the model was imported for a refused call")

    monkeypatch.setattr(core, "_import_obr", no_import)
    with pytest.raises(ValueError, match=match):
        core.obr_shock(var, 1000.0, periods=2, price_passthrough=True, **kwargs)


def test_price_passthrough_reaches_core_from_the_cli_and_mcp(runner, monkeypatch):
    """Off unless asked for on both surfaces, and forwarded when asked."""
    seen = []

    def fake_obr_shock(**kwargs):
        seen.append(kwargs["price_passthrough"])
        return {"name": "x", "var": "VREC", "shock": 2200.0, "periods": 12,
                "investment_closure": False, "results": [],
                "cumulative_delta_gdp_bn_over_shock_periods": 0.0,
                "peak_pct_gdp": 0.0, "peak_period": "2025Q1"}

    monkeypatch.setattr(core, "obr_shock", fake_obr_shock)
    base = ["obr-shock", "--var", "VREC", "--shock", "2200", "--json"]
    assert runner.invoke(main, base).exit_code == 0
    assert runner.invoke(main, base + ["--price-passthrough"]).exit_code == 0
    assert seen == [False, True]
    schema = _registered_tools()["obr_shock"].inputSchema["properties"]
    assert schema["price_passthrough"]["default"] is False


def test_cli_refuses_a_misapplied_price_passthrough_cleanly(runner):
    """Refused before the model import, so it is fast and needs no stub."""
    res = runner.invoke(
        main, ["obr-shock", "--var", "CGG", "--shock", "1", "--price-passthrough"]
    )
    assert res.exit_code != 0
    assert "Traceback" not in res.output
    assert "indirect-tax shock" in res.output


def test_cli_help_header_names_every_subcommand():
    # The header said "the OBR emulator and the UK SVAR model" long after
    # FRB/US, HANK, OG-UK, DEFINE-UK and the microsim joined (issue #225).
    from policyengine_macro.cli import main

    header = main.help or ""
    missing = [name for name in main.commands if name not in header]
    assert not missing, f"pe-macro --help header omits {missing}"
