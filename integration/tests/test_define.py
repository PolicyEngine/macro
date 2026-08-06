"""DEFINE-UK local-only surface: instructions without the adapter, deltas with it."""

import builtins

import pytest

from policyengine_macro import core


def _has_define():
    try:
        import define_uk.scenarios  # noqa: F401
        return True
    except ImportError:
        return False


def test_instructions_when_adapter_missing(monkeypatch):
    real_import = builtins.__import__

    def block_define(name, *a, **k):
        if name.startswith("define_uk"):
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", block_define)
    for res in (core.define_list_scenarios(), core.define_scenario("fossil_fuel_ban")):
        assert res["available"] is False
        assert "never hosted" in res["how_to_run"]
        assert "define-uk-model" in res["how_to_run"]


@pytest.mark.skipif(not _has_define(), reason="define_uk not installed")
def test_scenarios_list_and_deltas():
    listing = core.define_list_scenarios()
    if not listing.get("available"):
        pytest.skip("no cached DEFINE-UK run")
    names = {s["name"] for s in listing["scenarios"]}
    assert {"fossil_fuel_ban", "green_public_investment"} <= names

    res = core.define_scenario("fossil_fuel_ban")
    if not res.get("available"):
        pytest.skip("no cached DEFINE-UK run")
    assert res["result_type"] == "scenario deltas"
    assert res["model"] == "define-uk"
    assert res["caveats"], "mandatory caveats missing"
    assert "GDP_R" in res["variables"]
    assert len(res["years"]) == len(res["variables"]["GDP_R"]["delta_level"])


def test_capability_entry_exists():
    from policyengine_macro.capabilities import MODELS
    cap = MODELS["define-uk"]
    assert "local CLI scenarios" in cap["access"]
    assert "hosted" not in cap["access"]
    assert any("score_reform refuses" in c for c in cap["cannot_answer"])
    assert any("define_scenario_incidence" in a for a in cap["access"])


# --- incidence bridge: the EconomicAssumptions leg is pure and testable ----

def _synthetic_payload(scenario="green_public_investment"):
    years = list(range(2023, 2038))
    def series(vals):
        return {"delta_level": vals, "delta_pct": vals}
    n = len(years)
    return {
        "result_type": "scenario deltas",
        "scenario": scenario,
        "years": years,
        "variables": {
            "YD_HH": series([0.7] * n),
            "P": series([-0.1] * n),
            "WR": series([0.35] * n),
        },
        "caveats": ["synthetic"],
    }


def test_incidence_assumptions_disposable_income():
    from policyengine_macro.assumptions import EconomicAssumptions
    ea = EconomicAssumptions.from_define_scenario(
        _synthetic_payload(), year=2030,
    )
    assert ea.earnings_factor == pytest.approx(1.008)  # 0.7 - (-0.1) = 0.8%
    assert ea.labour_supply_factor == 1.0
    assert any("disposable_income" in nt for nt in ea.notes)
    assert any("never levels" in c for c in ea.caveats)


def test_incidence_assumptions_real_wage_and_errors():
    from policyengine_macro.assumptions import EconomicAssumptions
    ea = EconomicAssumptions.from_define_scenario(
        _synthetic_payload(), year=2030, income_concept="real_wage",
    )
    assert ea.earnings_factor == pytest.approx(1.0035)
    with pytest.raises(ValueError, match="income_concept"):
        EconomicAssumptions.from_define_scenario(
            _synthetic_payload(), year=2030, income_concept="wage_bill",
        )
    with pytest.raises(ValueError, match="horizon"):
        EconomicAssumptions.from_define_scenario(
            _synthetic_payload(), year=2050,
        )
    bad = _synthetic_payload()
    del bad["variables"]["P"]
    with pytest.raises(ValueError, match="lacks the series"):
        EconomicAssumptions.from_define_scenario(bad, year=2030)


def test_incidence_refuses_mismatched_payload():
    with pytest.raises(ValueError, match="refusing to mix"):
        core.define_scenario_incidence(
            "fossil_fuel_ban",
            define_payload=_synthetic_payload("green_public_investment"),
        )


def test_incidence_instructions_when_adapter_missing(monkeypatch):
    real_import = builtins.__import__

    def block_define(name, *a, **k):
        if name.startswith("define_uk"):
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", block_define)
    res = core.define_scenario_incidence("green_public_investment")
    assert res["available"] is False
    assert "define_payload" in res["how_to_run"]
    assert "only numbers travel" in res["how_to_run"]
