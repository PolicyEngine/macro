"""Tests for the macro -> micro EconomicAssumptions overlay (issue #11).

The overlay is applied by DIRECT INPUT SCALING of the reform simulation's
employment-income arrays via the engine's Dynamic(simulation_modifier=...)
hook — NOT by parameter overrides on the uprating indices.

EMPIRICAL RECORD (2026-07-20, production engine via the deployed MCP
server): derived-index overrides are DEAD on pre-built per-year datasets.
Two population_reform_impact calls with a reform overriding
gov.economic_assumptions.indices.obr.average_earnings for 2026 — first
x0.99 (value 1.66561), then a drastic 0.84 (~half the compounded baseline)
— BOTH returned exactly zero everywhere: £0.0bn budgetary impact, 0
winners, 0 losers, all deciles 0.0. Root cause: the per-year datasets
(enhanced_frs_2023_24-year-2026) are pre-uprated at dataset BUILD time
(policyengine tax_benefit_models/uk/datasets.py create_datasets), and
PolicyEngineUKLatest.run feeds the stored input arrays straight into
UKSingleYearDataset, so simulation-time uprating parameters are never
consulted for input variables. Hence the input-scaling mechanism.

Fast tests are engine-free (synthetic OG payloads, fake microsim); the
engine-gated test proving the NEW mechanism bites is slow-marked and
skipped where policyengine does not import or the microdata token is
absent, per the repo's conventions.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from policyengine_macro import core
from policyengine_macro.assumptions import (
    SCALED_INPUT_VARIABLES,
    EconomicAssumptions,
)


def _synthetic_og(w_reform=0.99, l_reform=0.995, start_year=2026):
    base = {"r": 0.05, "w": 1.00, "Y": 2.0, "K": 6.0, "L": 1.00,
            "C": 1.4, "I": 0.4, "G": 0.2, "tax_revenue": 0.6, "debt": 1.8}
    ref = dict(base, w=w_reform, L=l_reform, r=0.051)
    return {
        "start_year": start_year,
        "baseline_steady_state_model_units": base,
        "reform_steady_state_model_units": ref,
    }


# ---------------------------------------------------------------------------
# Unit: EconomicAssumptions construction
# ---------------------------------------------------------------------------

def test_from_og_result_factors():
    ea = EconomicAssumptions.from_og_result(_synthetic_og())
    assert ea.earnings_factor == pytest.approx(0.99)
    assert ea.labour_supply_factor == pytest.approx(0.995)
    assert ea.interest_rate_baseline == 0.05
    assert ea.interest_rate_reform == 0.051
    assert ea.start_year == 2026
    assert any("no transition dynamics" in n for n in ea.notes)
    json.dumps(ea.model_dump())


def test_caveats_report_unallocated_hours():
    ea = EconomicAssumptions.from_og_result(_synthetic_og())
    caveats = ea.caveat_strings()
    assert any("-0.50%" in c for c in caveats)
    assert any("self-employment" in c for c in caveats)


# ---------------------------------------------------------------------------
# Unit: the input-scaling modifier against a fake engine simulation
# ---------------------------------------------------------------------------

class _FakeHolder:
    def __init__(self, arrays: dict):
        self.arrays = arrays  # period -> np.ndarray

    def get_known_periods(self):
        return list(self.arrays)

    def get_array(self, period):
        return self.arrays[period]

    def delete_arrays(self, period):
        del self.arrays[period]


class _FakeMicrosim:
    """Mimics the policyengine_uk.Microsimulation surface the modifier uses
    (get_holder / set_input, the policyengine_core Simulation API)."""

    def __init__(self, holders: dict):
        self.holders = {name: _FakeHolder(arrs)
                        for name, arrs in holders.items()}
        self.set_calls: list[tuple] = []

    def get_holder(self, name):
        return self.holders.setdefault(name, _FakeHolder({}))

    def set_input(self, name, period, values):
        self.set_calls.append((name, period))
        self.holders[name].arrays[period] = values


def test_modifier_scales_before_lsr_inputs():
    ea = EconomicAssumptions.from_og_result(_synthetic_og())
    sim = _FakeMicrosim({
        "employment_income_before_lsr": {2026: np.array([100.0, 200.0])},
        "employment_income": {},
    })
    ea.input_scaling_modifier()(sim)
    scaled = sim.holders["employment_income_before_lsr"].arrays[2026]
    assert scaled == pytest.approx([99.0, 198.0])
    # Only the populated variable was touched, once.
    assert sim.set_calls == [("employment_income_before_lsr", 2026)]


def test_modifier_falls_back_to_employment_income():
    ea = EconomicAssumptions.from_og_result(_synthetic_og())
    sim = _FakeMicrosim({
        "employment_income": {2026: np.array([50.0])},
    })
    ea.input_scaling_modifier()(sim)
    assert sim.holders["employment_income"].arrays[2026] == pytest.approx(
        [49.5]
    )


def test_modifier_refuses_when_no_input_is_populated():
    """Never return a silently static result as a dynamic one."""
    ea = EconomicAssumptions.from_og_result(_synthetic_og())
    with pytest.raises(RuntimeError, match="no populated"):
        ea.input_scaling_modifier()(_FakeMicrosim({}))


def test_null_macro_result_yields_no_modifier():
    """Double-counting invariant: factor 1.0 -> None, so the reform
    simulation carries no Dynamic and is identical to the static one."""
    ea = EconomicAssumptions.from_og_result(
        _synthetic_og(w_reform=1.00, l_reform=1.00)
    )
    assert ea.earnings_factor == 1.0
    assert ea.input_scaling_modifier() is None


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def test_guard_rejects_dead_economic_assumption_reforms():
    """gov.economic_assumptions.* overrides silently do nothing in
    population runs (pre-uprated datasets; see module docstring), so the
    dynamic score refuses them — before any heavy import."""
    with pytest.raises(ValueError, match="no effect in"):
        core.dynamic_population_reform_impact(
            reform={
                "gov.economic_assumptions.indices.obr.average_earnings": 1.0
            }
        )


def test_dynamic_is_uk_only():
    with pytest.raises(ValueError, match="UK-only"):
        core.dynamic_population_reform_impact(
            country="us", reform={"x": 1.0}
        )
    with pytest.raises(ValueError, match="UK-only"):
        core.score_reform("us", {"x": 1.0}, model="og+microsim")


# ---------------------------------------------------------------------------
# Wiring: dynamic scoring end to end with mocked OG + microsim
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_dynamic(monkeypatch):
    calls = {}

    def fake_og(reform, start_year, max_iter, baseline_cache=True):
        calls["og"] = {"reform": reform, "start_year": start_year}
        return _synthetic_og(
            w_reform=calls.get("w_reform", 0.99), start_year=start_year
        )

    def fake_micro(country, reform, year, dataset=None, reform_modifier=None):
        calls["micro"] = {"reform": reform, "year": year,
                          "reform_modifier": reform_modifier}
        return {
            "currency": "GBP", "budgetary_impact_bn": 5.0,
            "budgetary_impact_basis": "change in gov_balance",
            "headline": "The reform raises £5.0bn/year in 2026.",
            "decile_impacts": [], "winners": 0, "losers": 0,
        }

    monkeypatch.setattr(core, "og_score_reform", fake_og)
    monkeypatch.setattr(core, "pe_population_impact", fake_micro)
    return calls


def test_dynamic_applies_modifier_to_reform_side_only(fake_dynamic):
    reform = {"gov.hmrc.income_tax.rates.uk[0].rate": 0.21}
    res = core.dynamic_population_reform_impact(reform=reform, year=2026)
    micro = fake_dynamic["micro"]
    # User reform passes through UNCHANGED (applied once, as policy);
    # the overlay travels separately as the reform-side-only modifier.
    assert micro["reform"] == reform
    assert callable(micro["reform_modifier"])
    assert res["application"]["method"] == "input-scaling"
    assert res["application"]["applied"] is True
    assert res["application"]["variables_tried"] == list(SCALED_INPUT_VARIABLES)
    assert res["score"]["model"] == "og+microsim"
    assert res["economic_assumptions"]["earnings_factor"] == pytest.approx(0.99)
    assert any("hours change" in c for c in res["caveats"])
    assert any("input" in a for a in res["assumptions"])
    json.dumps(res)


def test_dynamic_null_macro_reduces_to_static(fake_dynamic):
    """Invariant end to end: w unchanged -> no modifier attached, so the
    reform simulation is exactly the static one."""
    fake_dynamic["w_reform"] = 1.00
    res = core.dynamic_population_reform_impact(
        reform={"gov.hmrc.income_tax.rates.uk[0].rate": 0.21}
    )
    assert fake_dynamic["micro"]["reform_modifier"] is None
    assert res["application"]["applied"] is False


def test_score_reform_routes_og_microsim(fake_dynamic):
    res = core.score_reform(
        "uk", {"gov.hmrc.income_tax.rates.uk[0].rate": 0.21},
        model="og+microsim",
    )
    assert res["score"]["model"] == "og+microsim"
    assert fake_dynamic["og"]["start_year"] == 2026


# ---------------------------------------------------------------------------
# Engine-gated: the CRITICAL check that the NEW mechanism bites
# ---------------------------------------------------------------------------

def _pe_engine_skip_reason():
    try:
        import policyengine as pe  # noqa: F401
    except Exception as e:  # broad: pydantic mismatches raise non-ImportError
        return f"policyengine not importable: {type(e).__name__}: {e}"
    if not (os.environ.get("HUGGING_FACE_TOKEN") or os.environ.get("HF_TOKEN")):
        return "needs HUGGING_FACE_TOKEN for the UK population microdata"
    return None


_PE_SKIP = _pe_engine_skip_reason()


@pytest.mark.slow
@pytest.mark.skipif(_PE_SKIP is not None, reason=_PE_SKIP or "")
def test_input_scaling_actually_bites():
    """Empirical proof the input-scaling overlay does something: attaching
    the x0.99 modifier via Dynamic(simulation_modifier=...) must lower
    aggregate employment income by ~1% vs stock.

    Context: the previous mechanism (overriding the derived uprating index
    gov.economic_assumptions.indices.obr.average_earnings) was proven DEAD
    against the production engine on 2026-07-20 — two population calls
    overriding the 2026 index by x0.99 (1.66561) and then 0.84 both
    returned exactly zero everywhere (£0.0bn, 0 winners, 0 losers, all
    deciles 0.0), because the per-year datasets are pre-uprated at build
    time. If THIS test fails, the replacement mechanism is dead too — do
    NOT ship the overlay.
    """
    import policyengine as pe
    from policyengine.core import Dynamic, Simulation
    from policyengine.outputs.aggregate import Aggregate, AggregateType

    year = 2026
    ea = EconomicAssumptions.from_og_result(_synthetic_og(w_reform=0.99))
    ds, base_sim = core._pe_pop_baseline("uk", year, None)
    ref_sim = Simulation(
        dataset=ds,
        tax_benefit_model_version=pe.uk.model,
        dynamic=Dynamic(
            name="test x0.99 earnings overlay",
            simulation_modifier=ea.input_scaling_modifier(),
            affects_labor_supply_response=False,
        ),
    )
    ref_sim.run()

    def _sum_emp(sim):
        agg = Aggregate(
            simulation=sim, variable="employment_income",
            aggregate_type=AggregateType.SUM, entity="person",
        )
        agg.run()
        return float(agg.result)

    ratio = _sum_emp(ref_sim) / _sum_emp(base_sim)
    assert 0.985 < ratio < 0.995, (
        f"input-scaling overlay did not bite: employment income ratio "
        f"{ratio:.4f} (expected ~0.99). Do NOT ship the overlay."
    )
