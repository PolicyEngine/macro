"""Unit tests for the policyengine_macro adapters (small draws to keep runtime low)."""

import json

import numpy as np
import pytest

from policyengine_macro import core


def test_list_variables():
    vars_ = core.obr_list_variables()
    codes = {v["var"] for v in vars_}
    assert {"CGG", "TCPRO"} <= codes
    for v in vars_:
        assert {"var", "description", "units", "investment_closure"} <= set(v)
    json.dumps(vars_)


@pytest.mark.parametrize("periods", [0, 26, 41, 1.5, "many"])
def test_obr_shock_rejects_unsafe_periods_before_import(periods):
    with pytest.raises(ValueError, match="periods"):
        core.obr_shock(var="CGG", shock=1250, periods=periods)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"horizons": 0, "draws": 100}, "horizons"),
        ({"horizons": 41, "draws": 100}, "horizons"),
        ({"horizons": 4, "draws": 49}, "draws"),
        ({"horizons": 4, "draws": 10_001}, "draws"),
    ],
)
def test_svar_forecast_rejects_unsafe_work_before_import(kwargs, field):
    with pytest.raises(ValueError, match=field):
        core.svar_forecast(**kwargs)


@pytest.mark.parametrize("draws", [0, 49, 10_001, "many"])
def test_latest_shocks_rejects_unsafe_draws_before_import(draws):
    with pytest.raises(ValueError, match="draws"):
        core.svar_latest_shocks(draws=draws)


@pytest.mark.parametrize("model", ["svar", "boe-svar"])
def test_score_reform_refuses_svar_and_names_the_alternative(model):
    """SCOPE GUARD: /svar and /models both tell readers that score_reform does
    not accept the SVAR. It is the baseline/conditioning member — the economy
    reforms are scored *against* — so the refusal must explain that and point
    at forecast_uk and model='obr', not just omit it from an enum."""
    with pytest.raises(ValueError) as excinfo:
        core.score_reform(
            country="uk",
            reform={"gov.hmrc.income_tax.rates.uk[0].rate": 0.21},
            model=model,
        )
    message = str(excinfo.value)
    assert "forecast_uk" in message
    assert "no mapping" in message.lower()


def test_score_reform_rejects_svar_even_with_junk_other_arguments():
    with pytest.raises(ValueError, match="forecast_uk"):
        core.score_reform(country=None, reform=None, model="svar")


def test_svar_is_not_in_the_supported_score_models():
    for model in ("svar", "boe-svar"):
        assert model not in core.SCORE_MODELS
        assert model in core.SCORE_MODELS_WITHOUT_REFORM_BRIDGE


def test_provenance_uses_exact_deployed_source_revision(monkeypatch):
    revision = "a" * 40
    monkeypatch.setenv("POLICYENGINE_MACRO_SOURCE_REVISION_HANK", revision)
    provenance = core._provenance(
        model_id="us-hank",
        distribution="us-hank-model",
        data_vintage="paper calibration",
        baseline="steady state",
    )
    assert provenance["source_revision"] == revision
    assert provenance["source_url"] == (
        "https://github.com/PolicyEngine/us-hank-model"
    )
    assert "recorded source revision" in provenance["reproducibility"]


def test_summary_parses():
    s = core.svar_summary()
    if "error" in s:
        pytest.skip(s["error"])
    assert "replication" in s and "forecast_revision" in s
    fevd = s["replication"]["fevd_1yr_headline"]
    assert any("UK GDP" in row.get("Variable", "") for row in fevd)
    json.dumps(s)


def _fake_run_reform(calls):
    """Stand-in for obr_macro.run_reform with its real window contract:
    the shock is applied for ``periods`` quarters from ``start`` but only
    start..end is solved and returned (reform_analysis.run_reform). Each
    shocked quarter moves GDP by exactly 1.0 £bn, so the cumulative equals
    the number of shocked quarters that made it into the results."""
    import pandas as pd

    def run_reform(name, var, shock, start="2025Q1", end="2027Q4",
                   periods=12, investment_closure=False):
        calls.append({"start": start, "end": end, "periods": periods})
        idx = pd.period_range(start, end, freq="Q")
        shocked = [i < periods for i in range(len(idx))]
        return pd.DataFrame({
            "period": idx,
            "delta_gdp_bn": [1.0 if s else 0.0 for s in shocked],
            "pct_gdp": [0.1 if s else 0.0 for s in shocked],
            "delta_cons_m": 0.0,
            "delta_if_m": 0.0,
        })

    return run_reform


@pytest.mark.parametrize(
    ("periods", "end", "n_rows"),
    [(4, "2027Q4", 12), (12, "2027Q4", 12), (20, "2029Q4", 20), (25, "2031Q1", 25)],
)
def test_obr_shock_solves_every_shocked_quarter(monkeypatch, periods, end, n_rows):
    """Before 6 Nov 2026 obr_shock never passed ``end``, so run_reform
    stopped at 2027Q4 and periods=20 reported a 12-quarter cumulative as
    "over shock periods". The window now runs to the last shocked quarter
    (never earlier than 2027Q4, never past the 2031Q1 databank end)."""
    calls = []
    monkeypatch.setattr(core, "_import_obr", lambda: _fake_run_reform(calls))
    res = core.obr_shock(var="CGG", shock=1250, periods=periods)
    assert calls == [{"start": "2025Q1", "end": end, "periods": periods}]
    assert res["window"] == {"start": "2025Q1", "end": end}
    assert len(res["results"]) == n_rows
    assert res["cumulative_delta_gdp_bn_over_shock_periods"] == float(periods)


def test_obr_shock_refuses_a_cumulative_over_fewer_quarters(monkeypatch):
    """If the solve ever returns fewer quarters than were shocked, the
    labelled cumulative would be wrong, so obr_shock raises instead."""
    import pandas as pd

    def short_run(**kw):
        idx = pd.period_range("2025Q1", "2027Q4", freq="Q")
        return pd.DataFrame({"period": idx, "delta_gdp_bn": 1.0, "pct_gdp": 0.1,
                             "delta_cons_m": 0.0, "delta_if_m": 0.0})

    monkeypatch.setattr(core, "_import_obr", lambda: short_run)
    with pytest.raises(RuntimeError, match="20-quarter shock"):
        core.obr_shock(var="CGG", shock=1250, periods=20)


def test_obr_periods_cap_is_the_databank_window():
    """25 quarters is exactly 2025Q1..2031Q1 (obr_macro/baseline.py END)."""
    assert core._OBR_MAX_PERIODS == 25
    assert core._obr_window_end(core._OBR_MAX_PERIODS) == core._OBR_DATA_END


@pytest.mark.slow
def test_obr_shock_cgg():
    res = core.obr_shock(var="CGG", shock=1250, periods=4)
    assert res["periods"] == 4
    assert len(res["results"]) >= 4
    # A spending increase should raise GDP in the first shocked quarter.
    assert res["results"][0]["delta_gdp_bn"] > 0
    json.dumps(res)


@pytest.mark.slow
def test_svar_forecast_and_cache():
    res = core.svar_forecast(horizons=4, draws=100)
    assert len(res["gdp_growth_yoy"]) == 4
    row = res["gdp_growth_yoy"][0]
    assert row["lo90"] <= row["lo68"] <= row["median"] <= row["hi68"] <= row["hi90"]
    json.dumps(res)
    # Second call must hit the in-process cache (same object).
    assert core.svar_forecast(horizons=4, draws=100) is res


# ---------------------------------------------------------------------------
# PolicyEngine adapters
# ---------------------------------------------------------------------------

def test_pe_list_common_parameters():
    params = core.pe_list_common_parameters(resolve=False)
    assert len(params) >= 8
    for p in params:
        assert {"country", "path", "description", "unit"} <= set(p)
        assert p["country"] in ("uk", "us")
    paths = {p["path"] for p in params}
    assert "gov.hmrc.income_tax.rates.uk[0].rate" in paths
    json.dumps(params)


@pytest.mark.slow
def test_pe_household_uk_50k():
    res = core.pe_household("uk", [{"age": 35, "employment_income": 50_000}])
    s = res["summary"]
    it = s["income_tax_by_person"][0]
    assert 6_500 < it < 8_500  # ~£7,486 in 2026
    assert s["national_insurance_by_person"][0] > 0
    assert 30_000 < s["household_net_income"] < 45_000
    assert res["currency"] == "GBP"
    json.dumps(res)


@pytest.mark.slow
def test_pe_household_impact_uk_basic_rate_rise():
    res = core.pe_household_impact(
        "uk",
        [{"age": 35, "employment_income": 50_000}],
        reform={"gov.hmrc.income_tax.rates.uk[0].rate": 0.25},
    )
    d_it = res["change"]["income_tax_by_person"][0]
    assert d_it > 500  # 5pp on ~£37.4k of basic-rate income ≈ +£1,872
    assert res["net_income_change"] < 0
    json.dumps(res)


@pytest.mark.slow
def test_pe_household_us():
    res = core.pe_household(
        "us",
        [{"age": 35, "employment_income": 60_000}],
        tax_unit={"filing_status": "SINGLE"},
        household={"state_code": "CA", "county_fips": "06037"},
    )
    s = res["summary"]
    assert s["federal_income_tax"] > 0
    assert s["employee_payroll_tax"] > 0
    assert 35_000 < s["household_net_income"] < 60_000
    assert res["currency"] == "USD"
    assert res["spm"]["selection"]["geography_kind"] == "county"
    json.dumps(res)


@pytest.mark.slow
def test_pe_household_us_national_spm_selection():
    """An explicit national SPM selection runs a state-only household."""
    res = core.pe_household(
        "us",
        [{"age": 35, "employment_income": 60_000}],
        tax_unit={"filing_status": "SINGLE"},
        household={"state_code": "CA"},
        spm={"geography_kind": "national"},
    )
    assert res["spm"]["selection"]["geography_kind"] == "national"
    assert res["summary"]["federal_income_tax"] > 0


@pytest.mark.slow
def test_pe_household_us_state_code_changes_state_income_tax():
    """CA and TX must differ: TX levies no state income tax.

    Regression guard — the state is HOUSEHOLD-level and PolicyEngine US
    silently defaults to CA, so a dropped state would return a
    plausible-looking (but wrong) California answer for every state. Both
    documented state keys are checked.
    """
    people = [{"age": 40, "employment_income": 200_000}]
    tax_unit = {"filing_status": "SINGLE"}

    def state_tax(state_key, code):
        return core.pe_household(
            "us", people, tax_unit=tax_unit,
            household={state_key: code},
            spm={"geography_kind": "national"},
        )["summary"]["state_income_tax"]

    for state_key in core.US_STATE_KEYS:
        ca, tx = state_tax(state_key, "CA"), state_tax(state_key, "TX")
        assert tx == 0, f"TX has no state income tax, got {tx} ({state_key})"
        assert ca > 0, f"CA should levy state income tax, got {ca} ({state_key})"


def test_pe_household_us_requires_spm_geography():
    # policyengine-us 2.x raises SPM_GEOGRAPHY_REQUIRED for a state-only
    # household; the adapter rejects it first, before importing PolicyEngine,
    # and names the choices.
    for spm in (None, {"geography_kind": "county"}):
        with pytest.raises(ValueError, match="county_fips") as error:
            core.pe_household(
                "us", [{"age": 30}], household={"state_code": "TX"}, spm=spm
            )
        assert '"geography_kind": "national"' in str(error.value)
    with pytest.raises(ValueError, match="county_fips"):
        core.pe_household_impact(
            "us", [{"age": 30}], reform={"gov.irs.credits.ctc.amount.base[0].amount": 3000},
        )


def test_pe_household_us_rejects_bad_spm_selection():
    with pytest.raises(ValueError, match="geography_kind must be one of"):
        core.pe_household(
            "us", [{"age": 30}], household={"state_code": "TX"},
            spm={"geography_kind": "state"},
        )
    with pytest.raises(ValueError, match="spm must be a dict"):
        core.pe_household(
            "us", [{"age": 30}], household={"state_code": "TX"}, spm="national",
        )


def test_pe_household_uk_rejects_spm_selection():
    with pytest.raises(ValueError, match="US only"):
        core.pe_household(
            "uk", [{"age": 30}], spm={"geography_kind": "national"}
        )


def test_pe_household_us_rejects_invalid_state_code():
    for state_key in core.US_STATE_KEYS:
        with pytest.raises(ValueError, match="two-letter US state"):
            core.pe_household("us", [{"age": 30}], household={state_key: "Texas"})
        with pytest.raises(ValueError, match="two-letter US state"):
            core.pe_household("us", [{"age": 30}], household={state_key: "ZZ"})


def test_pe_household_us_rejects_two_different_states():
    with pytest.raises(ValueError, match="two different states"):
        core._validate_us_household({"state_code": "TX", "state_code_str": "CA"})


def test_pe_household_us_validates_county_fips():
    # A county without a state, or in another state, would run a California
    # household in that county: policyengine-us does not derive one from the
    # other.
    with pytest.raises(ValueError, match="needs the household's state"):
        core._validate_us_household({"county_fips": "36061"})
    with pytest.raises(ValueError, match="is not in TX"):
        core._validate_us_household({"state_code": "TX", "county_fips": "36061"})
    # An integer drops the leading zero (06037 -> 6037).
    for bad_county in (6037, "6037", "060370", "LA"):
        with pytest.raises(ValueError, match="five-digit county FIPS"):
            core._validate_us_household(
                {"state_code": "CA", "county_fips": bad_county}
            )


def test_validate_us_household_normalises_case():
    assert core._validate_us_household({"state_code_str": "tx"}) == {
        "state_code_str": "TX"
    }
    assert core._validate_us_household(
        {"state_code": "ny", "county_fips": "36061"}
    ) == {"state_code": "NY", "county_fips": "36061"}
    assert core._validate_us_household(None) is None


def test_pe_household_bad_country():
    with pytest.raises(ValueError):
        core.pe_household("fr", [{"age": 30}])
    with pytest.raises(ValueError):
        core.pe_household_impact("uk", [{"age": 30}], reform={})


@pytest.mark.slow
def test_svar_latest_shocks():
    res = core.svar_latest_shocks(draws=100)
    assert len(res["shocks"]) == 6
    for s in res["shocks"]:
        assert abs(s["p_positive"] + s["p_negative"] - 1.0) < 1e-6
    json.dumps(res)


def _block_boe_var(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "boe_var", None)
    monkeypatch.setitem(sys.modules, "boe_var.data", None)


def test_summary_without_boe_var_and_env_is_actionable(monkeypatch):
    _block_boe_var(monkeypatch)
    monkeypatch.delenv("POLICYENGINE_MACRO_BOE_VAR_REPO", raising=False)
    out = core.svar_summary()
    assert set(out) == {"error"}
    assert "POLICYENGINE_MACRO_BOE_VAR_REPO" in out["error"]
    json.dumps(out)


def test_summary_without_boe_var_uses_env_checkout(monkeypatch, tmp_path):
    _block_boe_var(monkeypatch)
    results = tmp_path / "results"
    results.mkdir()
    (results / "summary.md").write_text(
        "- draws: 100\n\n## FEVD at 1-year horizon\n"
        "| Variable | Global |\n|---|---|\n| UK GDP | 0.5 |\n"
    )
    (results / "forecast_summary.md").write_text(
        "- origin: 2026Q1\n\n## P(sign)\n"
        "| Shock | P |\n|---|---|\n| UK demand | 0.8 |\n"
        "Composite impulse response\n- flat\n"
    )
    monkeypatch.setenv("POLICYENGINE_MACRO_BOE_VAR_REPO", str(tmp_path))
    out = core.svar_summary()
    assert out["source"] == str(results)
    fevd = out["replication"]["fevd_1yr_headline"]
    assert any("UK GDP" in row.get("Variable", "") for row in fevd)
    assert out["forecast_revision"]["latest_shock_signs"]
    json.dumps(out)


def test_cli_summary_without_boe_var_errors_actionably(monkeypatch):
    from click.testing import CliRunner

    from policyengine_macro.cli import main

    _block_boe_var(monkeypatch)
    monkeypatch.delenv("POLICYENGINE_MACRO_BOE_VAR_REPO", raising=False)
    res = CliRunner().invoke(main, ["summary"])
    assert res.exit_code != 0
    assert "POLICYENGINE_MACRO_BOE_VAR_REPO" in res.output


def test_cli_summary_env_checkout_missing_files_errors(monkeypatch, tmp_path):
    """A configured fallback whose files are missing must error, not print
    empty headings and exit 0 (round-2 review, new finding 1)."""
    from click.testing import CliRunner

    from policyengine_macro.cli import main

    _block_boe_var(monkeypatch)
    monkeypatch.setenv("POLICYENGINE_MACRO_BOE_VAR_REPO", str(tmp_path))
    res = CliRunner().invoke(main, ["summary"])
    assert res.exit_code != 0
    assert "no parseable SVAR results" in res.output


def test_svar_summary_serves_the_paper_comparable_fevd(monkeypatch):
    """A heading change upstream must not silently empty a served table.

    ``_parse_md_table`` returns [] when it cannot find the heading, and the
    summary is assembled without checking, so when the upstream heading
    gained "(4-quarter-ahead forecast error)" the served FEVD table became
    empty with no error anywhere in the payload. Both tables are asserted
    here: the renormalised one that was already published, and the group
    share formed per draw, which is the statistic the paper's ~40% / ~50%
    refer to.
    """
    s = core.svar_summary()
    if "error" in s or "error" in s.get("replication", {}):
        pytest.skip(s.get("error") or s["replication"]["error"])
    rep = s["replication"]
    assert rep["fevd_1yr_headline"], "the renormalised FEVD table parsed empty"
    groups = rep["fevd_1yr_group_shares"]
    assert groups, "the per-draw group-share table parsed empty"
    assert {"Variable", "Group", "Mean"} <= set(groups[0])
    assert any(
        row["Variable"] == "UK GDP" and row["Group"] == "global" for row in groups
    )
    assert "renormalises" in rep["fevd_note"]


def test_svar_forecast_reports_simple_yoy_rates_not_log_differences(monkeypatch):
    """Issue #208. For a known level path, the adapter's YoY must be the
    published simple rate 100*(P_t/P_{t-4}-1), not 100*log(P_t/P_{t-4})."""
    import types

    import pandas as pd

    growth = 0.025  # 2.5% a quarter: ~10.4% a year, where the gap is ~0.5pp
    hist = 100.0 * np.log(np.exp(np.arange(8) * growth))[:, None] * np.ones(2)

    def sample_forecast(draw, y_full, horizons, rng):
        last = y_full[-1]
        return last + 100.0 * growth * np.arange(1, horizons + 1)[:, None]

    def aggregate(paths, weights):
        med = np.median(np.asarray(paths), axis=0)
        return {k: med for k in ("median", "lo68", "hi68", "lo90", "hi90")}

    forecast = types.SimpleNamespace(
        sample_forecast=sample_forecast,
        yoy=lambda x: np.asarray(x)[4:] - np.asarray(x)[:-4],
    )  # an older boe_var without log_to_simple_pct: the fallback runs
    analysis = types.SimpleNamespace(aggregate=aggregate)
    est = {
        "modules": (analysis, forecast), "y_full": hist,
        "pairs": [(object(), None)], "weights": np.array([1.0]),
        "df_full": pd.DataFrame(
            hist, columns=[core._COL_GDP, core._COL_CPI],
            index=pd.period_range("2024Q2", periods=8, freq="Q"),
        ),
        "n_accepted": 1, "ess": 1.0, "warnings": [],
        "estimation_sample": "fake",
    }
    monkeypatch.setattr(core, "_estimate", lambda draws: est)
    monkeypatch.setattr(core, "_FORECAST_CACHE", {})
    res = core.svar_forecast(horizons=4, draws=100)
    simple = 100.0 * (np.exp(4 * growth) - 1.0)  # 10.517
    for row in res["cpi_inflation_yoy"] + res["gdp_growth_yoy"]:
        assert row["median"] == pytest.approx(simple, abs=1e-3)
        assert row["lo90"] == pytest.approx(simple, abs=1e-3)
    assert "simple" in res["units"]
