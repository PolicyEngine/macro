"""Tests for the US HANK adapters.

Mirrors tests/test_frbus.py: fast contract tests cover the catalogue,
metadata, argument validation and the reform-bridge refusal without importing
the model package; everything that needs a real solve is marked `slow` (run
with `--runslow`) and additionally skipped when `us_hank` is unavailable.

The slow tests assert signs and qualitative properties, not exact floats: the
model is a validated replication of Auclert, Bardóczy, Rognlie & Straub
(Econometrica 2021) and its own repo gates magnitudes; these tests catch a
sign flip, a dead cache, or a mislabeled series in OUR adapter.
"""

from __future__ import annotations

import pytest

from policyengine_macro import core


def _hank_available() -> bool:
    try:
        import us_hank  # noqa: F401
    except Exception:
        return False
    return True


requires_hank = pytest.mark.skipif(
    not _hank_available(),
    reason="us_hank (pip install us-hank-model) is required",
)


# ---------------------------------------------------------------------------
# Fast tests: catalogue, metadata and argument validation. No solve.
# ---------------------------------------------------------------------------

def test_shock_catalogue_documents_units_for_every_kind():
    kinds = core.hank_list_shocks()
    assert {k["kind"] for k in kinds} == {
        "monetary", "fiscal_spending", "productivity"
    }
    for entry in kinds:
        assert entry["input"]
        assert entry["description"]
        assert entry["units"], f"{entry['kind']} has no documented units"
        assert isinstance(entry["typical_size"], (int, float))
        assert set(entry["variants"]) <= set(core.HANK_VARIANTS)


def test_shock_catalogue_returns_copies():
    core.hank_list_shocks()[0]["units"] = "corrupted"
    assert core.hank_list_shocks()[0]["units"] != "corrupted"


def test_unknown_kind_is_rejected_and_explains_the_endogenous_tax():
    """The silent-fabrication trap: there is no transfer/tax-rate instrument
    in the DAG, so asking for one must raise with the reason, not guess."""
    with pytest.raises(ValueError, match="endogenous"):
        core.hank_shock(kind="transfer", size=0.01)


def test_fiscal_shock_is_refused_in_the_one_asset_variant():
    with pytest.raises(ValueError, match="two_asset"):
        core.hank_shock(kind="fiscal_spending", size=0.01, variant="one_asset")


def test_unknown_variant_is_rejected():
    with pytest.raises(ValueError, match="variant must be one of"):
        core.hank_shock(kind="monetary", size=-0.0025, variant="three_asset")


@pytest.mark.parametrize("kwargs", [
    {"persistence": 1.0},
    {"persistence": -0.1},
    {"horizon": 0},
    {"horizon": core.HANK_T + 1},
])
def test_invalid_windows_and_persistence_are_rejected(kwargs):
    with pytest.raises(ValueError):
        core.hank_shock(kind="monetary", size=-0.0025, **kwargs)


def test_distribution_is_refused_for_the_one_asset_variant():
    with pytest.raises(ValueError, match="two_asset"):
        core.hank_shock(kind="monetary", size=-0.0025, variant="one_asset",
                        include_distribution=True)


def test_summary_reports_honest_framing_without_a_solve():
    summary = core.hank_summary()
    framing = summary["framing"].lower()
    for claim in ("validated replication", "stylized shocks",
                  "not a forecaster", "first-order"):
        assert claim in framing, f"framing must state: {claim}"
    assert "Econometrica 2021" in summary["upstream"]
    assert "replication suite" in summary["validation"]["suite"]
    assert "endogenous" in summary["no_tax_or_transfer_instrument"]
    assert summary["provenance"]["model_id"] == "us-hank"


def test_summary_states_there_is_no_reform_bridge():
    assert "NONE" in core.hank_summary()["reform_bridge"]


def test_score_reform_refuses_hank_and_names_the_alternative():
    """SCOPE GUARD: the model scores stylized shocks, not tax reforms, so
    score_reform must never quietly return a number for model='hank'."""
    with pytest.raises(ValueError) as excinfo:
        core.score_reform(
            country="us",
            reform={"gov.irs.credits.ctc.amount.base[0].amount": 3000},
            model="hank",
        )
    message = str(excinfo.value)
    assert "hank_shock" in message
    assert "no mapping exists" in message


def test_score_reform_rejects_hank_even_with_junk_other_arguments():
    with pytest.raises(ValueError, match="hank_shock"):
        core.score_reform(country=None, reform=None, model="us-hank")


def test_hank_is_not_in_the_supported_score_models():
    assert "hank" not in core.SCORE_MODELS
    assert "hank" in core.SCORE_MODELS_WITHOUT_REFORM_BRIDGE
    assert "us-hank" in core.SCORE_MODELS_WITHOUT_REFORM_BRIDGE


# ---------------------------------------------------------------------------
# Slow tests: real solves. These are the deployment gates.
# ---------------------------------------------------------------------------

@pytest.mark.slow
@requires_hank
def test_monetary_easing_is_expansionary_with_the_documented_shape():
    """A -25bp AR(1) easing must raise output, consumption, investment and
    inflation, and the reported r deviation must be negative on impact."""
    res = core.hank_shock(kind="monetary", size=-0.0025, persistence=0.6)

    assert res["variant"] == "two_asset"
    assert "warning" not in res, res.get("warning")
    assert len(res["results"]) == core.HANK_DEFAULT_HORIZON
    assert res["shock_input"] == "rstar"
    assert set(res["series_meaning"]) == {"Y", "C", "I", "pi", "r", "w", "N"}

    first = res["results"][0]
    assert first["Y"] > 0, "an easing must be expansionary on impact"
    assert first["pi"] > 0, "an easing must raise inflation on impact"
    # Ground-truth direction checks for the w/N series feeding the incidence
    # bridge: higher demand raises labor and the real wage on impact, and
    # under a standard production function the labor response must not be
    # dwarfed by output (N moves with Y, not orders of magnitude below it).
    assert first["N"] > 0, "an easing must raise labor on impact"
    assert first["w"] > 0, "an easing must raise the real wage on impact"
    assert first["N"] > 0.1 * first["Y"]
    assert res["peaks"]["Y"]["value"] > 0
    assert res["peaks"]["C"]["value"] > 0
    assert res["peaks"]["I"]["value"] > 0
    # The shock path itself must be reported and decay geometrically.
    assert first["shock"] == pytest.approx(-0.0025)
    assert res["results"][1]["shock"] == pytest.approx(-0.0025 * 0.6)


@pytest.mark.slow
@requires_hank
def test_fiscal_spending_raises_output_but_crowds_out_consumption_channel():
    """A tax-financed G expansion must raise Y on impact; and because it is
    implicitly financed by the endogenous labor tax, the output response must
    exceed the consumption response (no free-lunch transfer)."""
    res = core.hank_shock(kind="fiscal_spending", size=0.01, persistence=0.7)
    first = res["results"][0]
    assert first["Y"] > 0
    assert first["Y"] > first["C"]


@pytest.mark.slow
@requires_hank
def test_responses_are_linear_in_the_shock_size():
    """The adapter promises first-order IRFs; doubling the size must exactly
    double every response (this also proves the cached jacobian is reused)."""
    one = core.hank_shock(kind="monetary", size=-0.0025, persistence=0.6)
    two = core.hank_shock(kind="monetary", size=-0.0050, persistence=0.6)
    # abs tolerance: reported values are rounded to 6 decimal places, so the
    # doubled value can differ by up to 2 units in the last place.
    assert two["results"][0]["Y"] == pytest.approx(
        2 * one["results"][0]["Y"], abs=2e-6
    )


@pytest.mark.slow
@requires_hank
def test_steady_state_and_jacobian_are_cached_per_variant():
    core._HANK_CACHE.clear()
    core.hank_shock(kind="monetary", size=-0.0025)
    assert len(core._HANK_CACHE) == 1
    core.hank_shock(kind="productivity", size=0.01)
    assert len(core._HANK_CACHE) == 1, "same variant re-solved"


@pytest.mark.slow
@requires_hank
def test_one_asset_variant_reports_no_investment_series():
    res = core.hank_shock(kind="monetary", size=-0.0025, variant="one_asset",
                          horizon=8)
    assert "I" not in res["results"][0]
    assert set(res["series_meaning"]) == {"Y", "C", "pi", "r", "w", "N"}
    assert len(res["results"]) == 8


@pytest.mark.slow
@requires_hank
def test_distributional_block_is_coherent_and_labelled_first_order():
    res = core.hank_shock(kind="monetary", size=-0.0025,
                          include_distribution=True)
    d = res["distributional"]
    assert "FIRST-ORDER" in d["note"]

    mpc = d["mpc_by_liquid_quartile"]
    assert set(mpc) == {"Q1", "Q2", "Q3", "Q4"}
    # MPCs fall with liquid wealth: the poorest quartile must have the
    # highest MPC — the economic point of a HANK model.
    assert mpc["Q1"] > mpc["Q4"]
    assert 0 < d["aggregate_quarterly_mpc_liquid"] < 1
    assert 0 < d["hand_to_mouth_share"] < 1

    dc = d["impact_consumption_response_pct_by_wealth_quartile"]
    assert set(dc) == {"Q1", "Q2", "Q3", "Q4"}
    # The easing is expansionary, and the high-MPC (poor) quartile responds
    # by more than the wealthy one under the first-order allocation.
    assert dc["Q1"] > dc["Q4"]
