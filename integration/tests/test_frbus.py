"""Tests for the FRB/US adapters.

These are the tests that would catch a BROKEN DEPLOYMENT rather than a broken
import: the hosted server can only produce right answers if the model files
survived the image's vendor/ pruning, the tracking invariant still holds, and a
known shock still produces the documented impulse responses.

Everything that needs a real solve is marked `slow` (run with `--runslow`) and
additionally skipped when `frbus` or its vendor data is unavailable, so a
checkout without the model repo still gets the fast contract coverage.

Magnitudes are asserted with deliberately loose tolerances against the figures
in us-frb-model's VALIDATION.md. They are NOT exact floats: LONGBASE is a
quarterly data vintage, and a re-vintaged baseline legitimately moves these
responses by a few percent. The tests are here to catch a sign flip, a
disconnected lever or a mis-specified baseline — not to freeze a data release.
"""

from __future__ import annotations

import pytest

from policyengine_macro import core


def _frbus_available() -> bool:
    try:
        core._frbus_repo()
    except Exception:
        return False
    return True


requires_frbus = pytest.mark.skipif(
    not _frbus_available(),
    reason="frbus (installed editably, with vendor/ present) is required",
)


# ---------------------------------------------------------------------------
# Fast tests: catalogue, metadata and argument validation. No solve.
# ---------------------------------------------------------------------------

def test_list_variables_documents_units_for_every_lever():
    """Units are the whole point of this catalogue: the same number means a
    100bp rate move on one lever and a solver divergence on another."""
    variables = core.frbus_list_variables()
    assert len(variables) >= 5
    for entry in variables:
        assert entry["var"]
        assert entry["description"]
        assert entry["units"], f"{entry['var']} has no documented units"
        assert isinstance(entry["typical_shock"], (int, float))
        assert entry["requires_policy_rule"] in (None, *core.FRBUS_POLICY_RULES)


def test_list_variables_returns_copies():
    """A caller mutating the result must not corrupt the module-level catalogue
    for every later request in a long-lived container."""
    core.frbus_list_variables()[0]["units"] = "corrupted"
    assert core.frbus_list_variables()[0]["units"] != "corrupted"


def test_every_policy_rule_is_self_consistent():
    for name, spec in core.FRBUS_POLICY_RULES.items():
        assert spec["description"]
        assert isinstance(spec["switches"], dict)
        assert isinstance(spec["exogenize"], list)
        lever = spec["shock_lever"]
        if lever is not None:
            entry = core._FRBUS_VAR_INDEX[lever]
            assert entry["requires_policy_rule"] == name, (
                f"{name}'s shock_lever {lever} does not declare it back"
            )


def test_summary_reports_validation_provenance():
    summary = core.frbus_summary()
    assert summary["equations"] == 284
    assert "2026" in summary["data_vintage"]
    val = summary["validation"]
    # The gates the model repo's own CI enforces; if these drift in the text
    # here they stop matching VALIDATION.md and the provenance becomes a lie.
    assert val["tracking_invariant"]["value"] < val["tracking_invariant"]["gate"]
    assert val["vs_vendor_pyfrbus"]["value"] < val["vs_vendor_pyfrbus"]["gate"]
    assert val["monetary_tightening_properties"]["xgdp_trough_pct"] < 0
    assert val["monetary_tightening_properties"]["lur_peak_pp"] > 0
    assert "MCE" in summary["expectations"]


def test_summary_states_there_is_no_reform_bridge():
    assert "NONE" in core.frbus_summary()["reform_bridge"]


@pytest.mark.parametrize("rule", ["taylor", "fixed_funds_rate"])
def test_rffintay_shock_is_refused_under_a_rule_that_ignores_it(rule):
    """The silent-zero trap. Under a non-inertial rule this shock is a valid
    column, the solve converges, and every response is exactly 0.0 — which
    reads as 'monetary policy does nothing'. It must raise instead."""
    with pytest.raises(ValueError, match="disconnected"):
        core.frbus_shock(var="rffintay_aerr", shock=1.0, policy_rule=rule)


def test_unknown_policy_rule_is_rejected():
    with pytest.raises(ValueError, match="policy_rule must be one of"):
        core.frbus_shock(var="rffintay_aerr", shock=1.0, policy_rule="nope")


@pytest.mark.parametrize("kwargs", [
    {"periods": 0},
    {"periods": 30, "horizon": 20},
])
def test_invalid_windows_are_rejected(kwargs):
    with pytest.raises(ValueError):
        core.frbus_shock(var="rffintay_aerr", shock=1.0, **kwargs)


def test_score_reform_refuses_frbus_and_names_the_alternative():
    """SCOPE GUARD: there is no PolicyEngine->FRB/US reform mapping, so
    score_reform must never quietly return a number for model='frbus'."""
    with pytest.raises(ValueError) as excinfo:
        core.score_reform(
            country="us",
            reform={"gov.irs.credits.ctc.amount.base[0].amount": 3000},
            model="frbus",
        )
    message = str(excinfo.value)
    assert "frbus_shock" in message
    assert "no mapping" in message.lower()


def test_score_reform_rejects_frbus_even_with_junk_other_arguments():
    """The bridge refusal must not depend on the rest of the call being
    well-formed, or a caller fixing their reform dict would eventually get a
    fabricated FRB/US answer."""
    with pytest.raises(ValueError, match="frbus_shock"):
        core.score_reform(country=None, reform=None, model="frbus")


def test_frbus_is_not_in_the_supported_score_models():
    assert "frbus" not in core.SCORE_MODELS
    assert "frbus" in core.SCORE_MODELS_WITHOUT_REFORM_BRIDGE


# ---------------------------------------------------------------------------
# Slow tests: real solves. These are the deployment gates.
# ---------------------------------------------------------------------------

@pytest.mark.slow
@requires_frbus
def test_model_and_data_files_resolve_from_installed_package():
    """A normal wheel install must carry both files needed by every solve."""
    from pathlib import Path

    model_path, data_path = core._frbus_paths()
    assert Path(model_path).is_file()
    assert Path(data_path).is_file()
    assert "_data" in Path(model_path).parts
    assert "_data" in Path(data_path).parts


@pytest.mark.slow
@requires_frbus
def test_tracking_invariant_holds_after_init_trac():
    """VALIDATION.md Test 1, re-run through OUR adapter's baseline setup.

    After init_trac, solving the baseline must reproduce LONGBASE for all 284
    endogenous variables. If this fails, every deviation the shock tool reports
    is measured against a baseline that is already wrong, so nothing else in
    this file means anything. The model repo gates at 1e-8; we assert the same
    bound rather than the achieved 7.3e-12, so a solver change that stays
    within the published gate does not fail us.
    """
    import pandas as pd

    start = pd.Period(core.FRBUS_DEFAULT_START, freq="Q")
    end = start + core.FRBUS_DEFAULT_HORIZON - 1
    model, with_adds = core._frbus_baseline("inertial_taylor", start, end)

    solved = model.solve(start, end, with_adds)
    worst = max(
        float((solved.loc[start:end, v] - with_adds.loc[start:end, v]).abs().max())
        for v in model.endo_names
    )
    assert len(model.endo_names) == 284
    assert worst < 1e-8, f"tracking invariant broken: max abs error {worst:.2e}"


@pytest.mark.slow
@requires_frbus
def test_monetary_tightening_has_the_documented_signs_and_magnitudes():
    """VALIDATION.md Test 3: 100bp rffintay_aerr shock in 2026Q1.

    Documented: rff +1.00pp on impact, xgdp trough -0.56%, lur peak +0.28pp,
    picxfe trough -0.034pp. Asserted with wide bands (roughly +/-40% on the
    real-side magnitudes) so a LONGBASE re-vintage does not break the build,
    while a sign flip, a decoupled lever or an order-of-magnitude error does.
    """
    res = core.frbus_shock(var="rffintay_aerr", shock=1.0)

    assert res["policy_rule"] == "inertial_taylor"
    assert "warning" not in res, res.get("warning")
    assert len(res["results"]) == core.FRBUS_DEFAULT_HORIZON

    # Impact: the shock is a 100bp tightening and must show up as one.
    impact = res["results"][0]
    assert impact["period"] == "2026Q1"
    assert 0.9 < impact["rff"] < 1.1

    # Monetary tightening contracts output and raises unemployment.
    gdp = [r["xgdp"] for r in res["results"]]
    lur = [r["lur"] for r in res["results"]]
    picxfe = [r["picxfe"] for r in res["results"]]

    assert -0.85 < min(gdp) < -0.30, f"xgdp trough {min(gdp)} (expected ~-0.56%)"
    assert 0.15 < max(lur) < 0.40, f"lur peak {max(lur)} (expected ~+0.28pp)"
    assert min(picxfe) < 0, "core inflation must fall after a tightening"
    assert abs(min(picxfe)) < 0.5, "inflation response is implausibly large"

    # The trough is a lagged response, not an impact effect: FRB/US puts it
    # around 2027Q4. Anything in the first year would mean the propagation
    # dynamics are wrong even if the peak magnitude happened to look right.
    trough_period = res["peaks"]["xgdp"]["period"]
    assert trough_period.startswith(("2027", "2028")), trough_period
    assert res["peaks"]["xgdp"]["value"] == pytest.approx(min(gdp))


@pytest.mark.slow
@requires_frbus
def test_fixed_funds_rate_amplifies_a_demand_shock():
    """The economically load-bearing reason policy_rule is exposed.

    With the funds rate held on its baseline path there is no endogenous
    monetary offset, so the SAME demand shock must move GDP by more than under
    the inertial Taylor rule. If the rule switch were silently ignored the two
    runs would be identical — which is exactly the bug this catches.
    """
    taylor = core.frbus_shock(
        var="egfe_aerr", shock=0.01, periods=4, policy_rule="inertial_taylor")
    fixed = core.frbus_shock(
        var="egfe_aerr", shock=0.01, periods=4, policy_rule="fixed_funds_rate")

    taylor_peak = taylor["peaks"]["xgdp"]["value"]
    fixed_peak = fixed["peaks"]["xgdp"]["value"]

    assert taylor_peak > 0, "a government purchases increase must raise GDP"
    assert fixed_peak > taylor_peak, (
        f"fixed funds rate ({fixed_peak}) should amplify the multiplier "
        f"relative to the inertial Taylor rule ({taylor_peak})"
    )
    # Under the Taylor rule the funds rate responds; under the fixed rule it
    # must not move at all.
    assert abs(fixed["peaks"]["rff"]["value"]) < 1e-6
    assert abs(taylor["peaks"]["rff"]["value"]) > 1e-6


@pytest.mark.slow
@requires_frbus
def test_shock_sign_reverses_with_the_sign_of_the_shock():
    """Cheap symmetry check that the reported deviations really are driven by
    the shock argument, not by a baseline artefact."""
    up = core.frbus_shock(var="trp_aerr", shock=0.01, periods=4)
    down = core.frbus_shock(var="trp_aerr", shock=-0.01, periods=4)
    # A personal tax RISE contracts output; a cut expands it.
    assert min(r["xgdp"] for r in up["results"]) < 0
    assert max(r["xgdp"] for r in down["results"]) > 0


@pytest.mark.slow
@requires_frbus
def test_requested_extra_variables_are_returned_alongside_the_headline():
    res = core.frbus_shock(
        var="rffintay_aerr", shock=1.0, horizon=8, variables=["ecnia", "ebfi"])
    row = res["results"][0]
    for series in ("xgdp", "lur", "picxfe", "pcpi", "rff", "ecnia", "ebfi"):
        assert series in row
        assert series in res["series_meaning"]
    assert len(res["results"]) == 8


@pytest.mark.slow
@requires_frbus
def test_unknown_variables_are_rejected_with_a_useful_message():
    with pytest.raises(ValueError, match="frbus_list_variables"):
        core.frbus_shock(var="not_a_variable", shock=1.0)
    with pytest.raises(ValueError, match="not in the model"):
        core.frbus_shock(var="rffintay_aerr", shock=1.0, variables=["nope"])


@pytest.mark.slow
@requires_frbus
def test_an_absurdly_sized_shock_errors_instead_of_returning_nonsense():
    """egfe_aerr is in log points; a caller treating it as billions of dollars
    passes something like 10. The solver diverges, and the adapter must
    surface that as a units error rather than a raw solver traceback."""
    with pytest.raises(ValueError, match="units"):
        core.frbus_shock(var="egfe_aerr", shock=50.0)


@pytest.mark.slow
@requires_frbus
def test_baseline_is_cached_per_policy_rule():
    core._FRBUS_BASELINE_CACHE.clear()
    core.frbus_shock(var="rffintay_aerr", shock=1.0, horizon=8)
    assert len(core._FRBUS_BASELINE_CACHE) == 1
    core.frbus_shock(var="rffintay_aerr", shock=0.5, horizon=8)
    assert len(core._FRBUS_BASELINE_CACHE) == 1, "identical window re-solved"
    core.frbus_shock(var="egfe_aerr", shock=0.01, horizon=8,
                     policy_rule="fixed_funds_rate")
    assert len(core._FRBUS_BASELINE_CACHE) == 2


def test_extra_rate_series_are_level_deviations_not_percent_of_the_rate():
    """A 10-year yield requested through ``variables`` used to come back as
    100*(new/base-1): a +30bp move on a 4% yield read as +7.5."""
    mode, meaning = core._frbus_series_mode("rg10", "10-year Treasury bond rate")
    assert mode == "pp" and "level deviation" in meaning
    assert core._frbus_series_mode("lfpr", "Labor force participation rate")[0] == "pp"
    # Levels, including the incidence inputs pl/lhp/leh, stay % deviations.
    for var, definition in [
        ("pl", "Compensation per hour, business"),
        ("lhp", "Aggregate labor hours, business sector"),
        ("leh", "Civilian employment (break adjusted)"),
        ("fpx", "Nominal exchange rate (G39, import/export trade weights)"),
        ("egfe", "Federal Government expenditures, CW 2012$"),
        ("zzz", None),
    ]:
        assert core._frbus_series_mode(var, definition)[0] == "pct", var
    # Headline series keep their declared modes.
    assert core._frbus_series_mode("rff", "anything") == core.FRBUS_HEADLINE["rff"]


def test_every_stacking_lever_says_so_and_poil_has_real_units():
    """Issue #212: us-frb-model VALIDATION.md asks every wrapper exposing
    `periods` to document stacking on every lever."""
    for entry in core.FRBUS_VARIABLES:
        if entry["var"] == "poil_aerr":
            assert "dollars per barrel" in entry["units"]
            assert "does not stack" in entry["units"]
        else:
            assert "PER SHOCKED PERIOD" in entry["units"], entry["var"]


# Levers whose own equation carries the shock forward, so holding the
# add-error for several quarters builds the move up. Measured at us-frb-model
# 162cfe6 (October 2026 LONGBASE), shock from 2026Q1; the same table is pinned
# upstream in us-frb-model #28.
_FRBUS_STACKING = {
    # lever: (own variable, shock, policy rule, own variable in the fourth
    #         of four shocked quarters: % for levels, decimal for tax rates)
    "rffintay_aerr": ("rff", 1.0, None, 2.97),
    "egfe_aerr": ("egfe", 0.01, None, 2.90),
    "egse_aerr": ("egse", 0.01, None, 3.71),
    "trp_aerr": ("trp", 0.01, None, 0.0233),
    "trci_aerr": ("trci", 0.01, None, 0.0295),
    "ecnia_aerr": ("ecnia", 0.01, None, 4.19),
    "ebfi_aerr": ("ebfi", 0.01, None, 5.95),
}
_FRBUS_NOT_STACKING = ("rfftay_aerr", "poil_aerr")


def test_stacking_text_matches_which_levers_stack():
    """The non-inertial Taylor rule has no lag of the funds rate, so its
    add-factor does not stack; before 25 Nov 2026 it carried the inertial
    rule's "peaks near +3pp" text. Every curated lever is in exactly one of
    the two lists, and its units string says the right thing."""
    index = core._FRBUS_VAR_INDEX
    assert set(_FRBUS_STACKING) | set(_FRBUS_NOT_STACKING) == set(index)
    for var in _FRBUS_NOT_STACKING:
        assert "does not stack" in index[var]["units"], var
        assert "+3pp" not in index[var]["units"], var
    for var in _FRBUS_STACKING:
        units = index[var]["units"]
        assert "does not stack" not in units, var
        assert "stack" in units or "accumulate" in units, var
    # A one-period investment shock keeps building; the text must not say
    # the level is 1% higher "after one period" and stop there.
    assert "keeps building" in index["ebfi_aerr"]["units"]
    # The figures us-frb-model #28's VALIDATION.md table prints, to its
    # decimals: egfe is 4.5% of real GDP in 2026Q1, and the one-quarter
    # responses are quoted in q4 (the fourth quarter), as that table does.
    assert "~4.5% of real GDP" in index["egfe_aerr"]["units"]
    assert "0.045% of GDP" in index["egfe_aerr"]["units"]
    assert "trci 2.95pp" in index["trci_aerr"]["units"]
    assert "BFI 5.95%" in index["ebfi_aerr"]["units"]
    assert "1.79% in the fourth quarter" in index["ebfi_aerr"]["units"]
    assert "1.01% in the fourth quarter" in index["ecnia_aerr"]["units"]


@pytest.mark.slow
def test_stacking_text_matches_the_installed_model():
    """The figures the units strings quote, against a real solve."""
    pytest.importorskip("frbus")

    def own_path(var, own, shock, periods, rule=None):
        kwargs = {"policy_rule": rule} if rule else {}
        res = core.frbus_shock(var, shock, periods=periods, horizon=8, **kwargs)
        return [row[own] for row in res["results"]]

    for var, (own, shock, rule, q4) in _FRBUS_STACKING.items():
        path = own_path(var, own, shock, 4, rule)
        assert path[3] == pytest.approx(q4, rel=0.02), (var, path)
        assert abs(path[3]) > 2 * abs(path[0]), (var, path)

    taylor = own_path("rfftay_aerr", "rff", 1.0, 4, "taylor")
    assert taylor[0] == pytest.approx(1.0, abs=0.01)
    assert max(taylor) < 1.01, taylor
    assert taylor[1:4] == pytest.approx([0.82, 0.71, 0.55], abs=0.01)

    oil = own_path("poil_aerr", "poil", 10.0, 4)
    # Reported as a % of the baseline price, which differs by quarter; held
    # in dollars, it never builds up.
    assert max(oil[:4]) == oil[0] and min(oil[:4]) > 0.6 * oil[0], oil

    # One shocked quarter: index 0 is the shocked quarter (q1) and index 3
    # is q4, the column us-frb-model #28's table reports.
    bfi = own_path("ebfi_aerr", "ebfi", 0.01, 1)
    assert bfi[0] == pytest.approx(1.0, abs=0.02)
    assert bfi[3] == pytest.approx(1.79, abs=0.02) and bfi[4] > bfi[3]

    cons = own_path("ecnia_aerr", "ecnia", 0.01, 1)
    assert cons[0] == pytest.approx(1.06, abs=0.01)
    assert cons[3] == pytest.approx(1.01, abs=0.01)


def _fake_frbus(monkeypatch):
    import pandas as pd

    idx = pd.period_range("2026Q1", periods=8, freq="Q")
    cols = list(core.FRBUS_HEADLINE) + ["trp", "trp_aerr", "zz", "zz_aerr"]
    base = pd.DataFrame(1.0, index=idx, columns=cols)
    base[["trp_aerr", "zz_aerr"]] = 0.0

    class _Model:
        def solve(self, start, end, data):
            out = data.copy()
            # a lagged equation: the lever accumulates its add-error
            out["trp"] = base["trp"] + data["trp_aerr"].cumsum()
            out["xgdp"] = base["xgdp"] - data["trp_aerr"].cumsum()
            return out

    monkeypatch.setattr(core, "_frbus_baseline",
                        lambda rule, s, e: (_Model(), base.copy()))
    monkeypatch.setattr(core, "_frbus_definitions",
                        lambda: {"trp": "Average government tax rate",
                                 "zz": "Something, cw 2012$"})


def test_realised_lever_path_is_returned(monkeypatch):
    _fake_frbus(monkeypatch)
    res = core.frbus_shock("trp_aerr", 0.01, periods=4, horizon=8)
    assert "trp" in res["series_meaning"]
    path = [r["trp"] for r in res["results"]]
    assert path[3] == pytest.approx(0.04)  # stacked: 4 x 0.01, not 0.01


def test_uncurated_lever_is_not_labelled_bare_model_units(monkeypatch):
    _fake_frbus(monkeypatch)
    res = core.frbus_shock("zz_aerr", 0.01, horizon=8)
    assert res["units"] != "model units"
    assert "uncurated" in res["units"] and "stacks" in res["units"]
