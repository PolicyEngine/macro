from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

import policyengine_macro.adapters as adapters
from policyengine_macro.adapters import (
    AnalysisRequest,
    OBRPolicyReformAdapter,
    USHankShockAdapter,
)
from policyengine_macro.core import ScoreResult


REQUEST = {
    "model_id": "obr-macro",
    "analysis_type": "translated_policy_scenario",
    "country": "uk",
    "inputs": {"reform": {"gov.test": 1}, "start_year": 2026, "years": 1},
    "baseline": "OBR Economic and Fiscal Outlook, March 2026",
    "horizon": "quarterly window 2026Q1..2026Q4",
    "requested_outputs": ["gdp"],
}


def result_payload(**overrides):
    payload = {
        "model": "obr-macro",
        "model_class": "semi-structural",
        "analysis_type": "translated fiscal scenario",
        "result_type": "scenario",
        "country": "uk",
        "reform": {"gov.test": 1},
        "baseline": REQUEST["baseline"],
        "provenance": {
            "model_id": "obr-macro", "package": "obr-macro-model",
            "package_version": "test", "model_version": "test",
            "adapter_version": "test", "source_url": "https://example.test",
            "source_revision": "fixture", "data_vintage": "March 2026 EFO",
            "baseline_vintage": "March 2026 EFO", "baseline": REQUEST["baseline"],
            "run_at": datetime.now(timezone.utc),
            "reproducibility": "run the pytest fixture",
        },
        "horizon": REQUEST["horizon"],
        "quantities": {"gdp": {
            "delta_bn": 0.2, "units": "GBP bn", "unit_code": "GBP_BN",
            "basis": "delta from baseline", "time_basis": "2026Q1..2026Q4",
            "price_basis": "real", "geography": "uk",
            "baseline_definition": REQUEST["baseline"],
            "uncertainty": "not estimated",
            "comparability": "related-not-like-for-like",
        }},
        "assumptions": ["fixture"], "caveats": ["fixture only"],
        "validation": ["contract fixture"],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def obr_adapter(monkeypatch):
    monkeypatch.setattr(
        adapters, "obr_score_reform", lambda **kwargs: {"score": result_payload()}
    )
    return OBRPolicyReformAdapter()


def test_real_obr_adapter_returns_canonical_score_result(obr_adapter):
    result = obr_adapter.run(REQUEST)
    assert isinstance(result, ScoreResult)
    assert result.quantities["gdp"].unit_code == "GBP_BN"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"country": "us"}, "does not support us"),
        ({"requested_outputs": ["borrowing"]}, "unsupported outputs"),
        ({"analysis_type": "forecast"}, "does not support forecast"),
    ],
)
def test_request_rejects_unsupported_capabilities(change, message):
    with pytest.raises(ValidationError, match=message):
        AnalysisRequest.model_validate({**REQUEST, **change})


@pytest.mark.parametrize("field", ["model", "country", "baseline", "horizon"])
def test_adapter_rejects_result_that_does_not_match_request(
    monkeypatch, field
):
    bad = result_payload(**{field: "wrong"})
    if field == "model":
        bad["provenance"]["model_id"] = "wrong"
    monkeypatch.setattr(adapters, "obr_score_reform", lambda **kwargs: {"score": bad})
    with pytest.raises(ValueError, match=field):
        OBRPolicyReformAdapter().run(REQUEST)


def test_result_requires_units_provenance_validation_and_limitations():
    payload = result_payload()
    del payload["quantities"]["gdp"]["unit_code"]
    with pytest.raises(ValidationError, match="unit_code"):
        ScoreResult.model_validate(payload)


def test_provenance_requires_timezone_aware_timestamp():
    payload = result_payload()
    payload["provenance"]["run_at"] = datetime.now()
    with pytest.raises(ValidationError, match="timezone-aware"):
        ScoreResult.model_validate(payload)


def test_obr_adapter_rejects_unknown_input(obr_adapter):
    request = {**REQUEST, "inputs": {**REQUEST["inputs"], "magic_units": "guess"}}
    with pytest.raises(ValueError, match="unknown OBR adapter inputs"):
        obr_adapter.run(request)


# ---------------------------------------------------------------------------
# US HANK stylized-shock adapter
# ---------------------------------------------------------------------------

HANK_REQUEST = {
    "model_id": "us-hank",
    "analysis_type": "economic_shock",
    "country": "us",
    "inputs": {"kind": "monetary", "size": -0.0025, "persistence": 0.6},
    "baseline": "calibrated steady state (production grids)",
    "horizon": "quarterly impulse responses, 20 quarters",
    "requested_outputs": ["gdp", "consumption", "inflation"],
}


def hank_payload():
    """A fixture shaped like core.hank_shock output (no model solve)."""
    return {
        "horizon": 20,
        "peaks": {
            "Y": {"value": 0.42, "quarter": 1},
            "C": {"value": 0.31, "quarter": 0},
            "I": {"value": 1.10, "quarter": 1},
            "pi": {"value": 0.08, "quarter": 0},
            "r": {"value": -0.24, "quarter": 0},
        },
        "provenance": {
            "model_id": "us-hank", "package": "us-hank-model",
            "package_version": "0.1.0", "model_version": "0.1.0",
            "adapter_version": "test",
            "source_url": "https://github.com/PolicyEngine/us-hank-model",
            "source_revision": "fixture",
            "data_vintage": "ABRS (2021) calibration",
            "baseline_vintage": HANK_REQUEST["baseline"],
            "baseline": HANK_REQUEST["baseline"],
            "run_at": datetime.now(timezone.utc),
            "reproducibility": "run the pytest fixture",
        },
    }


@pytest.fixture
def hank_adapter(monkeypatch):
    monkeypatch.setattr(adapters, "hank_shock", lambda **kwargs: hank_payload())
    return USHankShockAdapter()


def test_hank_adapter_returns_canonical_score_result(hank_adapter):
    result = hank_adapter.run(HANK_REQUEST)
    assert isinstance(result, ScoreResult)
    assert result.model == "us-hank"
    assert result.quantities["gdp"].delta_pct == 0.42
    assert result.quantities["inflation"].unit_code == "PP_DEV_SS"
    assert result.reform == {}
    # The honest framing must survive into the common contract.
    caveats = " ".join(result.caveats).lower()
    assert "not a forecaster" in caveats
    assert "first-order" in caveats


def test_hank_request_rejects_unsupported_capabilities():
    with pytest.raises(ValidationError, match="does not support uk"):
        AnalysisRequest.model_validate({**HANK_REQUEST, "country": "uk"})
    with pytest.raises(ValidationError, match="does not support forecast"):
        AnalysisRequest.model_validate(
            {**HANK_REQUEST, "analysis_type": "forecast"}
        )
    with pytest.raises(ValidationError, match="unsupported outputs"):
        AnalysisRequest.model_validate(
            {**HANK_REQUEST, "requested_outputs": ["revenue"]}
        )


def test_hank_adapter_rejects_unknown_and_missing_inputs(hank_adapter):
    with pytest.raises(ValueError, match="unknown US HANK adapter inputs"):
        hank_adapter.run({**HANK_REQUEST,
                          "inputs": {**HANK_REQUEST["inputs"], "reform": {}}})
    with pytest.raises(ValueError, match="explicit 'size'"):
        hank_adapter.run({**HANK_REQUEST, "inputs": {"kind": "monetary"}})


def test_hank_adapter_refuses_investment_from_the_one_asset_variant(
    hank_adapter,
):
    request = {
        **HANK_REQUEST,
        "inputs": {**HANK_REQUEST["inputs"], "variant": "one_asset"},
        "requested_outputs": ["gdp", "investment"],
    }
    with pytest.raises(ValueError, match="investment"):
        hank_adapter.run(request)
