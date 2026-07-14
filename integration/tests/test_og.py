"""Tests for the OG-UK steady-state adapters.

Fast tests mock the oguk solver and policy construction (a real solve takes
minutes). One slow end-to-end test runs a real reform score.
"""

import json

import pytest

from macromod import core


class _FakeSS:
    """Stands in for oguk.SteadyStateResult."""

    def __init__(self, scale=1.0):
        self._d = {
            "r": 0.05, "w": 1.2, "Y": 2.0 * scale, "K": 6.0 * scale,
            "L": 1.0 * scale, "C": 1.4 * scale, "I": 0.4 * scale,
            "G": 0.2 * scale, "tax_revenue": 0.6 * scale, "debt": 1.8 * scale,
        }

    def model_dump(self):
        return dict(self._d)


class _FakeImpact:
    def model_dump(self):
        d = {}
        for k in ("gdp", "consumption", "investment", "government",
                  "tax_revenue", "debt"):
            d[k] = 100.0
            d[f"{k}_change"] = 1.5
            d[f"{k}_pct"] = 0.05
        d["r_baseline"] = 0.05
        d["r_reform"] = 0.051
        return d


@pytest.fixture
def fake_oguk(monkeypatch):
    calls = {"solve": []}

    def fake_solve(start_year=2026, policy=None, max_iter=250, **kw):
        calls["solve"].append({"start_year": start_year, "policy": policy,
                               "max_iter": max_iter})
        return _FakeSS(scale=1.0 if policy is None else 1.01)

    def fake_map(baseline, reform):
        return _FakeImpact()

    monkeypatch.setattr(core, "_import_oguk", lambda: (fake_solve, fake_map))
    monkeypatch.setattr(core, "_og_build_policy",
                        lambda parameter, value, start_year: object())
    monkeypatch.setattr(core, "_OG_BASELINE_CACHE", {})
    return calls


def test_og_baseline_shape(fake_oguk):
    res = core.og_baseline(start_year=2026)
    assert res["start_year"] == 2026
    ss = res["steady_state_model_units"]
    assert {"r", "w", "Y", "K", "L", "C", "I", "G", "tax_revenue",
            "debt"} == set(ss)
    assert "pooled ages" in res["assumptions"]
    json.dumps(res)


def test_og_score_reform_shape_and_mapping(fake_oguk):
    res = core.og_score_reform("gov.hmrc.income_tax.rates.uk[0].rate", 0.21)
    imp = res["impact"]
    assert imp["levels_bn"]["gdp"] == 100.0
    assert imp["changes_bn"]["gdp_change"] == 1.5
    assert imp["changes_pct"]["tax_revenue_pct"] == 0.05
    assert imp["interest_rate"] == {"baseline": 0.05, "reform": 0.051}
    assert res["reform"] == {
        "parameter": "gov.hmrc.income_tax.rates.uk[0].rate",
        "value": 0.21, "start_year": 2026,
    }
    # Baseline solved without a policy, reform with one.
    solves = fake_oguk["solve"]
    assert len(solves) == 2
    assert solves[0]["policy"] is None
    assert solves[1]["policy"] is not None
    json.dumps(res)


def test_og_baseline_cache_reused(fake_oguk):
    core.og_score_reform("gov.hmrc.income_tax.rates.uk[0].rate", 0.21)
    core.og_score_reform("gov.hmrc.income_tax.rates.uk[0].rate", 0.22)
    # 2 reform solves + only 1 baseline solve (cached).
    baselines = [c for c in fake_oguk["solve"] if c["policy"] is None]
    assert len(baselines) == 1
    assert len(fake_oguk["solve"]) == 3


def test_og_baseline_cache_bypass(fake_oguk):
    core.og_score_reform("x", 0.21, baseline_cache=False)
    core.og_score_reform("x", 0.21, baseline_cache=False)
    baselines = [c for c in fake_oguk["solve"] if c["policy"] is None]
    assert len(baselines) == 2


def test_og_dataset_keyerror_translated(monkeypatch):
    """A calibration KeyError becomes an actionable RuntimeError."""

    def broken_solve(**kw):
        raise KeyError("enhanced_frs_2023_24_2026")

    monkeypatch.setattr(core, "_import_oguk",
                        lambda: (broken_solve, lambda b, r: None))
    monkeypatch.setattr(core, "_OG_BASELINE_CACHE", {})
    with pytest.raises(RuntimeError) as exc:
        core.og_baseline()
    msg = str(exc.value)
    assert "HUGGING_FACE_TOKEN" in msg
    assert "ensure_datasets" in msg
    assert "policyengine-uk==2.88.0" in msg


@pytest.mark.slow
def test_og_build_policy_real():
    """Real PolicyEngine Policy construction (imports policyengine, ~20s)."""
    policy = core._og_build_policy(
        "gov.hmrc.income_tax.rates.uk[0].rate", 0.21, 2026
    )
    pv = policy.parameter_values[0]
    assert pv.value == 0.21
    assert pv.start_date.year == 2026
    assert pv.parameter.name == "gov.hmrc.income_tax.rates.uk[0].rate"


@pytest.mark.slow
def test_og_score_reform_end_to_end():
    """Full baseline + reform steady-state solves (~10+ minutes)."""
    res = core.og_score_reform("gov.hmrc.income_tax.rates.uk[0].rate", 0.21)
    imp = res["impact"]
    # A basic-rate rise should raise long-run tax revenue.
    assert imp["changes_bn"]["tax_revenue_change"] > 0
    assert res["baseline_steady_state_model_units"]["Y"] > 0
    json.dumps(res)
