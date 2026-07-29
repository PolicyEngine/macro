"""Stress and robustness tests across the hosted models.

The contract tests elsewhere check that each adapter refuses unsupported
*requests*; these check behaviour at the edges of the supported space —
extreme-but-legal shock sizes, boundary horizons, and linearity/symmetry
properties a solver bug would break first. A model that returns plausible
numbers at the default settings but nonsense at the edges fails here rather
than in front of a user.
"""

import math

import pytest

from policyengine_macro import core

from test_frbus import requires_frbus
from test_hank import requires_hank


def _obr_available() -> bool:
    try:
        core._import_obr()
    except Exception:
        return False
    return True


def _svar_available() -> bool:
    try:
        core._import_boe_var()
    except Exception:
        return False
    return True


requires_obr = pytest.mark.skipif(
    not _obr_available(), reason="obr emulator package is required"
)
requires_svar = pytest.mark.skipif(
    not _svar_available(), reason="boe_var package is required"
)


# ---------------------------------------------------------------------------
# Fast: boundary validation. No solves.
# ---------------------------------------------------------------------------

def test_obr_periods_outside_bounds_are_rejected():
    with pytest.raises(ValueError, match="periods must be between"):
        core.obr_shock(var="CGG", shock=100.0, periods=0)
    with pytest.raises(ValueError, match="periods must be between"):
        core.obr_shock(var="CGG", shock=100.0, periods=10_000)


def test_svar_forecast_bounds_are_rejected():
    with pytest.raises(ValueError, match="horizons must be between"):
        core.svar_forecast(horizons=0)
    with pytest.raises(ValueError, match="horizons must be between"):
        core.svar_forecast(horizons=1_000)
    with pytest.raises(ValueError, match="draws must be between"):
        core.svar_forecast(horizons=8, draws=1)
    with pytest.raises(ValueError, match="draws must be between"):
        core.svar_forecast(horizons=8, draws=10_000_000)


def test_non_integer_work_requests_are_rejected():
    with pytest.raises(ValueError, match="must be an integer"):
        core.svar_forecast(horizons=2.5)


# ---------------------------------------------------------------------------
# Slow: solves at the edges of the supported space.
# ---------------------------------------------------------------------------

@pytest.mark.slow
@requires_hank
def test_hank_responses_are_exactly_linear_in_shock_size():
    """The adapter documents first-order (linear) responses; a factor-of-ten
    shock must scale every IRF by exactly ten. A violation means the solver
    or the caching layer is mixing runs."""
    small = core.hank_shock(kind="monetary", size=-0.0025, horizon=20)
    large = core.hank_shock(kind="monetary", size=-0.025, horizon=20)
    for var in ("Y", "C", "I"):
        for a, b in zip(small["results"], large["results"]):
            # The adapter rounds reported IRFs to 6 decimals, so the exact
            # 10x relationship survives only up to that rounding (~5.5e-6
            # after scaling one side by ten).
            assert math.isclose(b[var], 10 * a[var], rel_tol=1e-4, abs_tol=1e-5)


@pytest.mark.slow
@requires_hank
def test_hank_high_persistence_still_reverts_to_steady_state():
    """persistence=0.97 leaves ~0.2% of the shock alive at t=200, so the IRF
    must be back near steady state by then. (0.99 would not be a fair test:
    the shock itself is still ~13% alive at that horizon.)"""
    res = core.hank_shock(kind="monetary", size=-0.0025, persistence=0.97,
                          horizon=200)
    tail = [row["Y"] for row in res["results"][-5:]]
    peak = abs(res["peaks"]["Y"]["value"])
    assert all(abs(v) < 0.05 * peak for v in tail), (
        "IRF does not revert toward steady state at long horizons"
    )


@pytest.mark.slow
@requires_obr
def test_obr_shock_scales_close_to_linearly_and_signs_flip():
    """The emulator is nonlinear, but a 2x spending shock should move GDP by
    roughly 2x (within 25%), and a negative shock should flip the sign.
    Grossly super-linear or sign-preserving responses indicate a broken
    solve rather than economics."""
    one = core.obr_shock(var="CGG", shock=1_250.0, periods=4)
    two = core.obr_shock(var="CGG", shock=2_500.0, periods=4)
    neg = core.obr_shock(var="CGG", shock=-1_250.0, periods=4)

    assert one["peak_pct_gdp"] > 0
    neg_peak = max((r["pct_gdp"] for r in neg["results"]), key=abs)
    assert neg_peak < 0
    assert 1.5 < two["peak_pct_gdp"] / one["peak_pct_gdp"] < 2.5
    assert abs(neg_peak + one["peak_pct_gdp"]) < 0.25 * one["peak_pct_gdp"]


@pytest.mark.slow
@requires_frbus
def test_frbus_opposite_shocks_are_roughly_antisymmetric():
    up = core.frbus_shock(var="rffintay_aerr", shock=1.0, horizon=12)
    down = core.frbus_shock(var="rffintay_aerr", shock=-1.0, horizon=12)

    gdp_up = min(r["xgdp"] for r in up["results"])
    gdp_down = max(r["xgdp"] for r in down["results"])
    assert gdp_up < 0 < gdp_down
    assert abs(gdp_down + gdp_up) < 0.5 * abs(gdp_up), (
        "tightening and easing responses are not close to mirror images"
    )


@pytest.mark.slow
@requires_svar
def test_svar_bands_widen_with_horizon_and_contain_the_median():
    res = core.svar_forecast(horizons=8, draws=200)
    for key in ("gdp_growth_yoy", "cpi_inflation_yoy"):
        rows = res[key]
        for r in rows:
            assert r["lo90"] <= r["lo68"] <= r["median"] <= r["hi68"] <= r["hi90"]
        first, last = rows[0], rows[-1]
        assert (last["hi68"] - last["lo68"]) > (first["hi68"] - first["lo68"]), (
            f"{key}: predictive bands do not widen with horizon"
        )
