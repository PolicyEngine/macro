"""Edge inputs across the public tools that must fail before any solve.

Round-5 API sweep (6 Nov 2026): every case here used to reach a model
import or a full solve before failing, or returned NaN paths.
"""

import math

import pytest

from policyengine_macro import core

_FRBUS_SHOCK, _HANK_SHOCK = core.frbus_shock, core.hank_shock

def _no_solve(*a, **k):
    raise AssertionError("validation must fail before any model is touched")


@pytest.fixture
def no_models(monkeypatch):
    for name in ("_import_obr", "_import_frbus", "_import_us_hank",
                 "frbus_shock", "hank_shock", "_pe_population_incidence"):
        monkeypatch.setattr(core, name, _no_solve)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, "big"])
def test_shock_sizes_must_be_finite(no_models, bad):
    with pytest.raises(ValueError, match="shock|size"):
        core.obr_shock("CGG", bad, periods=4)
    with pytest.raises(ValueError, match="shock"):
        _FRBUS_SHOCK("egfe_aerr", bad)
    with pytest.raises(ValueError, match="size"):
        _HANK_SHOCK("monetary", bad)


@pytest.mark.parametrize("year, start, horizon", [
    (2031, "2026Q1", 20),   # window ends 2030Q4
    (2025, "2026Q1", 20),   # before the window
    (2026, "2026Q2", 20),   # 2026Q1 missing
    (2027, "2026Q1", 7),    # ends 2027Q3
])
def test_frbus_incidence_refuses_year_outside_window_before_solving(
    no_models, year, start, horizon
):
    with pytest.raises(ValueError, match="incidence year"):
        core.frbus_shock_incidence(
            var="egfe_aerr", shock=0.01, year=year, start=start,
            horizon=horizon,
        )


def test_frbus_incidence_accepts_a_covered_year(monkeypatch):
    seen = []
    monkeypatch.setattr(core, "frbus_shock",
                        lambda **kw: seen.append(kw) or (_ for _ in ()).throw(
                            RuntimeError("stop after the window check")))
    with pytest.raises(RuntimeError, match="stop after"):
        core.frbus_shock_incidence(var="egfe_aerr", shock=0.01, year=2030,
                                   start="2026Q1", horizon=20)
    assert seen


@pytest.mark.parametrize("year, start_year, horizon", [
    (2025, 2026, 20),
    (2031, 2026, 20),   # offsets 20..23 need horizon >= 24
])
def test_hank_incidence_refuses_year_outside_horizon_before_solving(
    no_models, year, start_year, horizon
):
    with pytest.raises(ValueError, match="incidence year"):
        core.hank_shock_incidence(
            kind="monetary", size=0.0025, year=year, start_year=start_year,
            horizon=horizon,
        )


def test_score_reform_model_name_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(core, "pe_population_impact",
                        lambda **kw: {"model": "microsim", **kw})
    assert core.score_reform("uk", {"gov.x": 1}, model=" Microsim ")["model"] \
        == "microsim"
    with pytest.raises(ValueError, match="no PolicyEngine-reform bridge"):
        core.score_reform("uk", {"gov.x": 1}, model="FRBUS")
