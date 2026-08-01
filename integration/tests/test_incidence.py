"""Tests for the macro -> micro shock-incidence layer.

Covers the two new EconomicAssumptions constructors (from_frbus_result,
from_hank_result), the reform-free _pe_population_incidence seam, the three
public incidence functions with stubbed model payloads, and the pointer
additions to the reform-bridge refusal messages.

All fast tests are model-free (synthetic frbus/hank/svar payloads, fake
engine modules) per the repo's conventions; nothing here runs FRB/US, HANK,
the SVAR, or PolicyEngine.
"""

from __future__ import annotations

import json

import pytest

from policyengine_macro import core
from policyengine_macro.assumptions import (
    SCALED_INPUT_VARIABLES,
    EconomicAssumptions,
)


# ---------------------------------------------------------------------------
# Synthetic payloads
# ---------------------------------------------------------------------------

def _synthetic_frbus(pl=-1.0, lhp=-0.5, leh=-0.4, rff=-0.2,
                     start="2026Q1", quarters=8):
    """A frbus_shock-shaped payload with constant deviations."""
    year, q = int(start[:4]), int(start[-1])
    rows = []
    for _ in range(quarters):
        rows.append({
            "period": f"{year}Q{q}",
            "xgdp": -0.3, "lur": 0.1, "picxfe": -0.05, "pcpi": -0.1,
            "rff": rff, "pl": pl, "lhp": lhp, "leh": leh,
        })
        q += 1
        if q == 5:
            year, q = year + 1, 1
    return {
        "name": "synthetic", "var": "trp_aerr", "shock": 0.01,
        "results": rows,
    }


def _synthetic_hank(w=1.0, n=0.5, r=-0.1, quarters=8):
    """A hank_shock-shaped payload with constant deviations."""
    rows = [
        {"quarter": t, "Y": 1.5, "C": 1.0, "I": 2.0, "pi": 0.2, "r": r,
         "w": w, "N": n, "shock": 0.01 * 0.9 ** t}
        for t in range(quarters)
    ]
    return {"name": "synthetic", "kind": "productivity", "size": 0.01,
            "results": rows}


# ---------------------------------------------------------------------------
# from_frbus_result
# ---------------------------------------------------------------------------

def test_from_frbus_wage_bill_factor_math():
    ea = EconomicAssumptions.from_frbus_result(
        _synthetic_frbus(pl=-1.0, lhp=-0.5), year=2027
    )
    assert ea.earnings_factor == pytest.approx(1 - 0.015)
    assert ea.labour_supply_factor == pytest.approx(1 - 0.005)
    assert ea.start_year == 2027
    # rff carried against the 0.0 baseline convention.
    assert ea.interest_rate_baseline == 0.0
    assert ea.interest_rate_reform == pytest.approx(-0.2)
    assert any("pre-tax" in n for n in ea.notes)
    assert any("transition-quarter average" in n for n in ea.notes)
    assert any("US" in n for n in ea.notes)
    assert any("job losers" in c for c in ea.caveat_strings())
    json.dumps(ea.model_dump())


def test_from_frbus_wage_concept_drops_hours():
    ea = EconomicAssumptions.from_frbus_result(
        _synthetic_frbus(pl=-1.0, lhp=-0.5), year=2027,
        income_concept="wage",
    )
    assert ea.earnings_factor == pytest.approx(0.99)
    assert ea.labour_supply_factor == pytest.approx(0.995)
    assert any("reported, not applied" in n for n in ea.notes)


def test_from_frbus_rejects_unknown_income_concept():
    with pytest.raises(ValueError, match="income_concept"):
        EconomicAssumptions.from_frbus_result(
            _synthetic_frbus(), year=2027, income_concept="profits"
        )


def test_from_frbus_requires_the_labour_series():
    payload = _synthetic_frbus()
    for row in payload["results"]:
        del row["pl"], row["lhp"], row["leh"]
    with pytest.raises(ValueError) as excinfo:
        EconomicAssumptions.from_frbus_result(payload, year=2027)
    # The error must tell the caller HOW to fix the call.
    assert 'variables=["pl", "lhp", "leh"]' in str(excinfo.value)


def test_from_frbus_requires_the_years_quarters():
    with pytest.raises(ValueError, match="four quarters of 2031"):
        EconomicAssumptions.from_frbus_result(
            _synthetic_frbus(quarters=8), year=2031
        )


def test_from_frbus_rejects_non_payloads():
    with pytest.raises(ValueError, match="frbus_shock"):
        EconomicAssumptions.from_frbus_result({"nope": 1}, year=2027)


def test_from_frbus_plausibility_gate():
    with pytest.raises(ValueError, match="implausible"):
        EconomicAssumptions.from_frbus_result(
            _synthetic_frbus(pl=-60.0, lhp=0.0), year=2027
        )


def test_from_frbus_noop_yields_no_modifier():
    """No-op invariant: zero deviations -> factor exactly 1.0 -> None."""
    ea = EconomicAssumptions.from_frbus_result(
        _synthetic_frbus(pl=0.0, lhp=0.0, leh=0.0), year=2027
    )
    assert ea.earnings_factor == 1.0
    assert ea.input_scaling_modifier() is None


def test_from_frbus_notes_when_rff_absent():
    payload = _synthetic_frbus()
    for row in payload["results"]:
        del row["rff"]
    ea = EconomicAssumptions.from_frbus_result(payload, year=2027)
    assert ea.interest_rate_reform == 0.0
    assert any("rff was not in" in n for n in ea.notes)


# ---------------------------------------------------------------------------
# from_hank_result
# ---------------------------------------------------------------------------

def test_from_hank_wage_bill_factor_math():
    ea = EconomicAssumptions.from_hank_result(
        _synthetic_hank(w=1.0, n=0.5), year=2026
    )
    assert ea.earnings_factor == pytest.approx(1.015)
    assert ea.labour_supply_factor == pytest.approx(1.005)
    assert ea.interest_rate_reform == pytest.approx(-0.1)
    assert any("pre-tax" in n for n in ea.notes)
    assert any("job losers" in c for c in ea.caveat_strings())
    json.dumps(ea.model_dump())


def test_from_hank_maps_year_to_quarter_offsets():
    """Quarters 4-7 are the second calendar year from start_year."""
    payload = _synthetic_hank(quarters=8)
    for row in payload["results"][4:]:
        row["w"], row["N"] = 2.0, 1.0
    ea = EconomicAssumptions.from_hank_result(
        payload, year=2027, start_year=2026
    )
    assert ea.earnings_factor == pytest.approx(1.03)


def test_from_hank_requires_enough_horizon():
    with pytest.raises(ValueError, match="horizon >= 12"):
        EconomicAssumptions.from_hank_result(
            _synthetic_hank(quarters=8), year=2028, start_year=2026
        )


def test_from_hank_rejects_year_before_start_year():
    with pytest.raises(ValueError, match="before start_year"):
        EconomicAssumptions.from_hank_result(
            _synthetic_hank(), year=2025, start_year=2026
        )


def test_from_hank_requires_wage_and_labor_series():
    payload = _synthetic_hank()
    for row in payload["results"]:
        del row["w"], row["N"]
    with pytest.raises(ValueError, match="re-run hank_shock"):
        EconomicAssumptions.from_hank_result(payload, year=2026)


def test_from_hank_noop_yields_no_modifier():
    ea = EconomicAssumptions.from_hank_result(
        _synthetic_hank(w=0.0, n=0.0), year=2026
    )
    assert ea.earnings_factor == 1.0
    assert ea.input_scaling_modifier() is None


def test_from_hank_plausibility_gate():
    with pytest.raises(ValueError, match="implausible"):
        EconomicAssumptions.from_hank_result(
            _synthetic_hank(w=80.0, n=40.0), year=2026
        )


# ---------------------------------------------------------------------------
# Refusal-message pointers
# ---------------------------------------------------------------------------

def test_frbus_refusal_points_to_the_incidence_tool():
    msg = core.SCORE_MODELS_WITHOUT_REFORM_BRIDGE["frbus"]
    assert "frbus_shock_incidence" in msg
    with pytest.raises(ValueError, match="frbus_shock_incidence"):
        core.score_reform(country="us", reform={"x": 1.0}, model="frbus")


def test_hank_refusal_points_to_the_incidence_tool():
    for key in ("hank", "us-hank"):
        assert "hank_shock_incidence" in (
            core.SCORE_MODELS_WITHOUT_REFORM_BRIDGE[key]
        )


# ---------------------------------------------------------------------------
# _pe_population_incidence seam: reform-free, Dynamic on the shocked side
# (fake engine modules, mirroring test_dynamic.py's fake_engine)
# ---------------------------------------------------------------------------

class _FakeDS:
    name = "fake-ds"

    class data:
        household = [0] * 3


class _FakeAggregate:
    def __init__(self, simulation=None, variable=None, aggregate_type=None,
                 entity=None):
        self.result = 0.0

    def run(self):
        pass


class _FakeDynamic:
    def __init__(self, name=None, simulation_modifier=None,
                 affects_labor_supply_response=None):
        self.name = name
        self.simulation_modifier = simulation_modifier
        self.affects_labor_supply_response = affects_labor_supply_response


class _CaptureSimulation:
    captured: list = []

    def __init__(self, **kwargs):
        _CaptureSimulation.captured.append(kwargs)

    def run(self):
        pass


@pytest.fixture
def fake_engine(monkeypatch):
    import sys
    import types

    _CaptureSimulation.captured = []
    pe_mod = types.ModuleType("policyengine")
    pe_mod.us = types.SimpleNamespace(model="fake-us-model")
    pe_mod.uk = types.SimpleNamespace(model="fake-uk-model")
    core_mod = types.ModuleType("policyengine.core")
    core_mod.Simulation = _CaptureSimulation
    core_mod.Dynamic = _FakeDynamic
    outputs_mod = types.ModuleType("policyengine.outputs")
    agg_mod = types.ModuleType("policyengine.outputs.aggregate")
    agg_mod.Aggregate = _FakeAggregate
    agg_mod.AggregateType = types.SimpleNamespace(SUM="sum")
    dec_mod = types.ModuleType("policyengine.outputs.decile_impact")
    dec_mod.calculate_decile_impacts = (
        lambda **kw: types.SimpleNamespace(outputs=[])
    )
    for name, mod in {
        "policyengine": pe_mod,
        "policyengine.core": core_mod,
        "policyengine.outputs": outputs_mod,
        "policyengine.outputs.aggregate": agg_mod,
        "policyengine.outputs.decile_impact": dec_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(core, "_import_pe", lambda: pe_mod)
    monkeypatch.setattr(
        core, "_pe_pop_baseline", lambda c, y, d: (_FakeDS(), object())
    )
    return _CaptureSimulation


def test_incidence_seam_attaches_dynamic_and_no_policy(fake_engine):
    sentinel = object()
    res = core._pe_population_incidence(
        country="us", year=2027, dataset=None, modifier=sentinel,
        label="test overlay",
    )
    (sim_kwargs,) = fake_engine.captured
    assert "policy" not in sim_kwargs, "incidence runs must carry NO reform"
    dyn = sim_kwargs["dynamic"]
    assert dyn.simulation_modifier is sentinel
    assert dyn.affects_labor_supply_response is False
    assert res["currency"] == "USD"
    assert "reform" not in res
    assert "automatic stabilizers" in res["headline"]
    json.dumps(res)


def test_incidence_seam_none_modifier_attaches_no_dynamic(fake_engine):
    res = core._pe_population_incidence(
        country="us", year=2027, dataset=None, modifier=None,
        label="null overlay",
    )
    (sim_kwargs,) = fake_engine.captured
    assert "dynamic" not in sim_kwargs
    assert res["budgetary_impact_bn"] == 0.0


# ---------------------------------------------------------------------------
# Wiring: the public incidence functions with stubbed models + microsim
# ---------------------------------------------------------------------------

_FAKE_MICRO = {
    "model": "PolicyEngine population microsimulation (macro-shock incidence)",
    "country": "us", "year": 2027, "dataset": "fake-cps",
    "n_households": 3, "currency": "USD", "shock_label": "x",
    "budgetary_impact_bn": -12.3,
    "budgetary_impact_basis": "change in household_tax minus change in "
                              "household_benefits",
    "household_net_income_change_bn": -40.0,
    "decile_impacts": [], "winners": 0, "losers": 100,
    "headline": "Through the automatic stabilizers, ...",
}


@pytest.fixture
def fake_frbus_incidence(monkeypatch):
    calls = {}

    def fake_shock(**kwargs):
        calls["frbus"] = kwargs
        return _synthetic_frbus(pl=-1.0, lhp=-0.5, quarters=8)

    def fake_incidence(country, year, dataset, modifier, label):
        calls["micro"] = {"country": country, "year": year,
                          "modifier": modifier, "label": label}
        return dict(_FAKE_MICRO)

    monkeypatch.setattr(core, "frbus_shock", fake_shock)
    monkeypatch.setattr(core, "_pe_population_incidence", fake_incidence)
    return calls


def test_frbus_shock_incidence_wiring(fake_frbus_incidence):
    res = core.frbus_shock_incidence(var="trp_aerr", shock=0.01, year=2027)
    # The labour series were requested from frbus_shock.
    assert fake_frbus_incidence["frbus"]["variables"] == ["pl", "lhp", "leh"]
    micro = fake_frbus_incidence["micro"]
    assert micro["country"] == "us"
    assert micro["year"] == 2027
    assert callable(micro["modifier"])
    assert res["application"]["method"] == "input-scaling"
    assert res["application"]["applied"] is True
    assert res["application"]["variables_tried"] == list(SCALED_INPUT_VARIABLES)
    assert res["economic_assumptions"]["earnings_factor"] == pytest.approx(0.985)
    assert res["score"]["model"] == "frbus+microsim"
    assert res["score"]["result_type"] == "illustration"
    assert res["score"]["analysis_type"] == "shock incidence (experimental)"
    assert res["score"]["reform"] == {}
    assert "automatic stabilizers" in res["score"]["quantities"]["revenue"]["basis"]
    assert any("not a reform score" in c for c in res["caveats"])
    json.dumps(res)


def test_frbus_shock_incidence_noop_attaches_no_modifier(monkeypatch):
    monkeypatch.setattr(
        core, "frbus_shock",
        lambda **kw: _synthetic_frbus(pl=0.0, lhp=0.0, leh=0.0),
    )
    seen = {}

    def fake_incidence(country, year, dataset, modifier, label):
        seen["modifier"] = modifier
        return dict(_FAKE_MICRO)

    monkeypatch.setattr(core, "_pe_population_incidence", fake_incidence)
    res = core.frbus_shock_incidence(var="trp_aerr", shock=0.0, year=2027)
    assert seen["modifier"] is None
    assert res["application"]["applied"] is False


def test_hank_shock_incidence_wiring(monkeypatch):
    calls = {}

    def fake_shock(**kwargs):
        calls["hank"] = kwargs
        return _synthetic_hank(w=1.0, n=0.5, quarters=8)

    def fake_incidence(country, year, dataset, modifier, label):
        calls["micro"] = {"country": country, "year": year,
                          "modifier": modifier}
        return dict(_FAKE_MICRO)

    monkeypatch.setattr(core, "hank_shock", fake_shock)
    monkeypatch.setattr(core, "_pe_population_incidence", fake_incidence)
    res = core.hank_shock_incidence(kind="productivity", size=0.01, year=2026)
    assert calls["hank"]["kind"] == "productivity"
    assert calls["micro"]["country"] == "us"
    assert callable(calls["micro"]["modifier"])
    assert res["economic_assumptions"]["earnings_factor"] == pytest.approx(1.015)
    assert res["score"]["model"] == "hank+microsim"
    assert res["score"]["result_type"] == "illustration"
    json.dumps(res)


# ---------------------------------------------------------------------------
# svar_inflation_incidence with a stubbed forecast, parameter tree, microsim
# ---------------------------------------------------------------------------

def _fake_forecast(cpi_median=3.0, origin="2026Q1", horizons=12):
    year, q = int(origin[:4]), int(origin[-1])
    rows = []
    for _ in range(horizons):
        q += 1
        if q == 5:
            year, q = year + 1, 1
        rows.append({"quarter": f"{year}Q{q}", "median": cpi_median,
                     "lo68": cpi_median - 1, "hi68": cpi_median + 1,
                     "lo90": cpi_median - 2, "hi90": cpi_median + 2})
    return {
        "forecast_origin": origin,
        "provenance": {"model_id": "boe-svar"},
        "draws": 2000, "accepted_draws": 135, "ess": 65.3, "warnings": [],
        "cpi_inflation_yoy": rows,
        "gdp_growth_yoy": rows,
    }


class _FakeParamValue:
    def __init__(self, start, value):
        from datetime import date

        y, m, d = (int(x) for x in start.split("-"))
        self.start_date = date(y, m, d)
        self.value = value


class _FakeParam:
    def __init__(self, value):
        self.parameter_values = [_FakeParamValue("2020-04-06", value)]


@pytest.fixture
def fake_svar_incidence(monkeypatch):
    import sys
    import types

    calls = {}
    monkeypatch.setattr(
        core, "svar_forecast",
        lambda horizons, draws: _fake_forecast(horizons=horizons),
    )
    values = {p["path"]: 100.0 for p in core.SVAR_CPI_UPRATED_PARAMETERS}

    class _FakeModel:
        @staticmethod
        def get_parameter(path):
            return _FakeParam(values[path])

    pe_mod = types.ModuleType("policyengine")
    pe_mod.uk = types.SimpleNamespace(model=_FakeModel())
    monkeypatch.setitem(sys.modules, "policyengine", pe_mod)
    monkeypatch.setattr(core, "_import_pe", lambda: pe_mod)

    def fake_pop(country, reform, year, dataset=None):
        calls["micro"] = {"country": country, "reform": reform, "year": year}
        return {
            "currency": "GBP", "dataset": "fake-frs",
            "budgetary_impact_bn": -0.8,
            "budgetary_impact_basis": "change in gov_balance",
            "household_net_income_change_bn": 0.8,
            "decile_impacts": [], "winners": 100, "losers": 0,
            "headline": "The reform costs £0.8bn/year in 2028.",
            "score": {"model": "pe-microsim"},
        }

    monkeypatch.setattr(core, "pe_population_impact", fake_pop)
    calls["values"] = values
    return calls


def test_svar_inflation_incidence_builds_the_scaled_reform(fake_svar_incidence):
    res = core.svar_inflation_incidence(year=2027, reference="target")
    micro_call = fake_svar_incidence["micro"]
    assert micro_call["country"] == "uk"
    assert micro_call["year"] == 2028, "the uprating lands the FOLLOWING year"
    # gap = 3.0 - 2.0 = 1.0pp; every parameter scaled by 1.01 from 6 April.
    assert res["cpi_gap_pp"] == pytest.approx(1.0)
    for entry in core.SVAR_CPI_UPRATED_PARAMETERS:
        assert micro_call["reform"][entry["path"]] == {
            "2028-04-06": pytest.approx(101.0)
        }
    assert res["score"]["model"] == "svar+microsim"
    assert res["score"]["result_type"] == "illustration"
    # One authoritative score: the nested static block is stripped.
    assert "score" not in res["microsim"]
    assert any("triple lock" in c for c in res["caveats"])
    assert "costs" in res["headline"]
    json.dumps(res)


def test_svar_inflation_incidence_rejects_bad_reference(fake_svar_incidence):
    with pytest.raises(ValueError, match="reference"):
        core.svar_inflation_incidence(year=2027, reference="boe")


def test_svar_inflation_incidence_requires_horizon_coverage(fake_svar_incidence):
    with pytest.raises(ValueError, match="horizons>="):
        core.svar_inflation_incidence(year=2031, reference="target")


def test_svar_inflation_incidence_errors_on_unresolvable_parameter(
    fake_svar_incidence,
):
    """A stale curated path must error loudly, never be skipped."""
    del fake_svar_incidence["values"][
        core.SVAR_CPI_UPRATED_PARAMETERS[0]["path"]
    ]
    with pytest.raises(ValueError, match="refusing to skip"):
        core.svar_inflation_incidence(year=2027, reference="target")


def test_svar_curated_list_is_short_and_documented():
    assert 3 <= len(core.SVAR_CPI_UPRATED_PARAMETERS) <= 6
    for entry in core.SVAR_CPI_UPRATED_PARAMETERS:
        assert entry["path"].startswith("gov.")
        assert entry["description"] and entry["unit"]


def test_frbus_incidence_refuses_mismatched_payload():
    with pytest.raises(ValueError, match="refusing to mix"):
        core.frbus_shock_incidence(
            var="rffintay_aerr", shock=1.0,
            frbus_payload={"var": "trp_aerr", "shock": 0.01},
        )


def test_hank_incidence_refuses_mismatched_payload():
    with pytest.raises(ValueError, match="refusing to mix"):
        core.hank_shock_incidence(
            kind="monetary", size=-0.0025,
            hank_payload={"kind": "fiscal_spending", "size": 0.01},
        )
