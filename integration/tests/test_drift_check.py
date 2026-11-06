"""The drift check's comparison logic and the committed canary list.

No network: hosted responses are hand-built dicts shaped like the adapters'.
The stale-pin case reproduces macro #218: the OBR Bank Rate canary on the old
pin (1ed742c) must fail, on value and on revision, while the new pin passes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

INTEGRATION = Path(__file__).resolve().parents[1]
REPO = INTEGRATION.parent
_spec = importlib.util.spec_from_file_location(
    "drift_check", INTEGRATION / "drift" / "drift_check.py"
)
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)

REGISTRY = dc.load_registry()
PINS = dc.load_pins()
CANARIES = {c["id"]: c for c in dc.load_canaries()}
OBR_URL = REGISTRY["obr-macro"]["source_url"]


def _obr_response(gdp_m, revision, model_id="obr-macro", url=OBR_URL):
    return {
        "results": [{"period": f"q{i + 1}", "delta_gdp_bn": g / 1000}
                    for i, g in enumerate(gdp_m)],
        "provenance": {"model_id": model_id, "source_url": url,
                       "source_revision": revision},
    }


# Bank Rate +1 x12, quarter-by-quarter ΔGDP (£m), from r5/obrpin old/new.json.
NEW_PIN_PATH = [-121, -200, -300, -431, -460, -470, -480, -482, -470, -450, -430, -416]
OLD_PIN_PATH = [-119, -200, -300, -446, -480, -500, -515, -525, -515, -505, -495, -490]


# --- extract ----------------------------------------------------------------


def test_extract_index_key_and_scale():
    obj = {"results": [{"x": 1.5}, {"x": 2.0}]}
    assert dc.extract(obj, {"path": ["results", 1, "x"], "scale": 1000}) == 2000.0


def test_extract_wildcard_with_reducers():
    obj = {"rows": [{"y": -0.2}, {"y": -0.55}, {"y": -0.1}]}
    assert dc.extract(obj, {"path": ["rows", "*", "y"], "reduce": "min"}) == -0.55
    assert dc.extract(obj, {"path": ["rows", "*", "y"], "reduce": "max"}) == -0.1
    assert dc.extract(obj, {"path": ["rows", "*", "y"], "reduce": "first"}) == -0.2
    assert dc.extract(obj, {"path": ["rows", "*", "y"], "reduce": "mean"}) == pytest.approx(-0.85 / 3)


def test_extract_selects_by_label():
    obj = {"f": [{"period": "2026Q2", "median": 1.1}, {"period": "2026Q3", "median": 1.4}]}
    spec = {"path": ["f", {"key": "period", "equals": "2026Q3"}, "median"]}
    assert dc.extract(obj, spec) == 1.4


def test_extract_missing_label_and_key_raise():
    with pytest.raises(KeyError):
        dc.extract({"f": []}, {"path": ["f", {"key": "period", "equals": "2026Q2"}]})
    with pytest.raises(KeyError):
        dc.extract({"a": 1}, {"path": ["b"]})


def test_extract_refuses_non_numbers_unless_compared_exactly():
    with pytest.raises(TypeError):
        dc.extract({"a": "x"}, {"path": ["a"]})
    assert dc.extract({"a": False}, {"path": ["a"], "equals": True}) is False


# --- compare ----------------------------------------------------------------


@pytest.mark.parametrize("got,ok", [(-416.0, True), (-426.0, True), (-426.5, False), (-490.0, False)])
def test_compare_is_absolute_and_inclusive(got, ok):
    assert dc.compare_value(got, -416, 10)[0] is ok


def test_compare_diff_message_names_the_gap():
    ok, msg = dc.compare_value(-490.0, -416, 10)
    assert not ok and "-490" in msg and "-416" in msg and "-74" in msg


def test_compare_rejects_nan_and_inf():
    assert not dc.compare_value(float("nan"), 0.0, 1e9)[0]
    assert not dc.compare_value(float("inf"), 0.0, 1e9)[0]


def test_compare_exact_for_booleans():
    assert dc.compare_value(False, False, 0)[0]
    assert not dc.compare_value(True, False, 0)[0]


# --- provenance -------------------------------------------------------------


def test_new_pin_passes_the_bank_rate_canary():
    c = CANARIES["obr_bank_rate_100bp"]
    row = dc.evaluate(c, _obr_response(NEW_PIN_PATH, PINS["OBR_REVISION"]), REGISTRY, PINS)
    assert row["status"] == "pass", row["failures"]


def test_stale_pin_fails_on_value_and_revision():
    """macro #218: the deployment that served the wrong-sign OBR score."""
    c = CANARIES["obr_bank_rate_100bp"]
    stale = "1ed742c" + "0" * 33
    row = dc.evaluate(c, _obr_response(OLD_PIN_PATH, stale), REGISTRY, PINS)
    kinds = {k for k, _ in row["failures"]}
    assert row["status"] == "fail"
    assert {"value", "revision"} <= kinds
    assert any("dgdp_q12_m" in m and "-490" in m for _, m in row["failures"])


def test_wrong_model_id_and_url_fail_provenance():
    """#225: obr_shock recorded 'obr-emulator' and fell back to the macro URL."""
    c = CANARIES["obr_bank_rate_100bp"]
    resp = _obr_response(NEW_PIN_PATH, PINS["OBR_REVISION"], model_id="obr-emulator",
                         url="https://github.com/PolicyEngine/macro")
    msgs = [m for k, m in dc.evaluate(c, resp, REGISTRY, PINS)["failures"] if k == "provenance"]
    assert any("obr-emulator" in m for m in msgs)
    assert any("source_url" in m for m in msgs)


def test_provenance_inside_score_block_is_found():
    assert dc.find_provenance({"score": {"provenance": {"model_id": "x"}}}) == {"model_id": "x"}
    assert dc.find_provenance({"no": 1}) is None


def test_missing_provenance_is_a_failure_unless_opted_out():
    c = dict(CANARIES["obr_bank_rate_100bp"])
    resp = {"results": [{"delta_gdp_bn": g / 1000} for g in NEW_PIN_PATH]}
    assert dc.evaluate(c, resp, REGISTRY, PINS)["status"] == "fail"
    c["check_provenance"] = False
    assert dc.evaluate(c, resp, REGISTRY, PINS)["status"] == "pass"


def test_local_rows_skip_provenance():
    c = CANARIES["obr_bank_rate_100bp"]
    resp = {"results": [{"delta_gdp_bn": g / 1000} for g in NEW_PIN_PATH]}
    assert dc.evaluate(c, resp, REGISTRY, PINS, source="local")["status"] == "pass"


def test_call_error_is_an_error_row():
    c = CANARIES["obr_bank_rate_100bp"]
    row = dc.evaluate(c, {"__error__": "TimeoutError"}, REGISTRY, PINS)
    assert row["status"] == "error" and row["failures"][0][0] == "error"


def test_unextractable_check_fails_not_crashes():
    c = CANARIES["obr_bank_rate_100bp"]
    resp = _obr_response(NEW_PIN_PATH[:3], PINS["OBR_REVISION"])
    row = dc.evaluate(c, resp, REGISTRY, PINS)
    assert row["status"] == "fail"
    assert any("cannot extract" in m for _, m in row["failures"])


# --- the committed canary list ----------------------------------------------


def test_committed_canaries_are_valid():
    assert dc.validate_canaries(list(CANARIES.values()), REGISTRY) == []


def test_validator_catches_bad_entries():
    bad = [
        {"id": "a", "model_id": "obr-emulator", "source_url": "x", "tool": "t",
         "args": {}, "quoted_at": "p:1", "quote": "q", "checks": [], "cost": "cheap"},
        {"id": "a", "model_id": "obr-macro", "source_url": "wrong", "tool": "t",
         "args": {}, "quoted_at": "p:1", "quote": "q", "cost": "pricey",
         "checks": [{"name": "n", "path": [], "expected": 1, "tolerance": -1}]},
    ]
    problems = "\n".join(dc.validate_canaries(bad, REGISTRY))
    for needle in ("not a registry id", "duplicate id", "differs from the registry",
                   "cost must be", "bad tolerance"):
        assert needle in problems


def test_every_hosted_model_has_a_canary():
    hosted = {"obr-macro", "boe-svar", "frb-us", "us-hank", "pe-microsim"}
    assert hosted <= {c["model_id"] for c in CANARIES.values()}


def test_every_canary_has_a_check():
    for c in CANARIES.values():
        assert c["checks"], c["id"]


@pytest.mark.parametrize("cid", sorted(CANARIES))
def test_quoted_at_points_at_a_real_line(cid):
    """The page/line must exist and the line must carry the first quoted number,
    so moving the page text forces the canary to be revisited."""
    c = CANARIES[cid]
    path, line = c["quoted_at"].rsplit(":", 1)
    lines = (REPO / path).read_text().splitlines()
    assert 1 <= int(line) <= len(lines), c["quoted_at"]
    anchor = c.get("quoted_anchor")
    if anchor:
        assert anchor in lines[int(line) - 1], (c["quoted_at"], anchor)


def test_bank_rate_canary_matches_the_page():
    text = (REPO / "obr/validation/index.html").read_text().splitlines()[544]
    for figure in ("£121m", "£431m", "£482m", "£416m"):
        assert figure in text


def test_tool_names_are_on_the_golden_surface():
    import sys
    sys.path.insert(0, str(INTEGRATION / "tests"))
    from tool_surface import GOLDEN_TOOLS
    for c in CANARIES.values():
        assert c["tool"] in GOLDEN_TOOLS, c["id"]


def test_cli_from_raw_exit_codes(tmp_path):
    good = _obr_response(NEW_PIN_PATH, PINS["OBR_REVISION"])
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"obr_bank_rate_100bp": good}))
    assert dc.main(["--from-raw", str(raw), "--only", "obr_bank_rate_100bp"]) == 0
    raw.write_text(json.dumps({"obr_bank_rate_100bp": _obr_response(OLD_PIN_PATH, "deadbeef")}))
    report = tmp_path / "r.md"
    assert dc.main(["--from-raw", str(raw), "--only", "obr_bank_rate_100bp",
                    "--report", str(report)]) == 1
    assert "### Diffs" in report.read_text()


def test_workflow_is_weekly_not_daily():
    wf = (REPO / ".github/workflows/drift-check.yml").read_text()
    assert "workflow_dispatch" in wf
    crons = [l.split("cron:")[1].split("#")[0].strip().strip("'\"")
             for l in wf.splitlines() if "cron:" in l]
    assert len(crons) == 1
    minute, hour, dom, month, dow = crons[0].split()
    assert dom == "*" and month == "*" and dow not in ("*", "1-5", "1-6", "0-6")
    assert "," not in dow and "-" not in dow


def test_local_checks_replace_hosted_checks_for_local_rows():
    c = CANARIES["define_green_public_investment"]
    hosted = {"model": "define-uk", "available": False, "how_to_run": "never hosted"}
    assert dc.evaluate(c, hosted, REGISTRY, PINS)["status"] == "pass"
    leaked = {"model": "define-uk", "available": True}
    assert dc.evaluate(c, leaked, REGISTRY, PINS)["status"] == "fail"
    local = {"variables": {"GDP_R": {"delta_pct": [0.1, 0.9193, 0.7]}}}
    assert dc.evaluate(c, local, REGISTRY, PINS, source="local")["status"] == "pass"
    drifted = {"variables": {"GDP_R": {"delta_pct": [0.1, 0.95]}}}
    assert dc.evaluate(c, drifted, REGISTRY, PINS, source="local")["status"] == "fail"


def test_household_ratio_sign_matches_a_tax_rise():
    """The add-factor carries revenue raised: GDP falls, the ratio is positive."""
    c = CANARIES["obr_household_ratio_q12"]
    resp = _obr_response([-300] * 11 + [-0.342 * 1615.75], PINS["OBR_REVISION"])
    row = dc.evaluate(c, resp, REGISTRY, PINS)
    assert row["status"] == "pass", row["failures"]
    assert row["observed"]["gdp_per_revenue_q12"] == pytest.approx(0.342, abs=1e-6)


def test_svar_canary_matches_the_committed_forecast_file():
    f = json.loads((REPO / "papers/boe-svar/figures/current_forecast.json").read_text())
    exp = {ch["name"]: ch["expected"] for ch in CANARIES["svar_forecast_median"]["checks"]}
    assert exp["gdp_2026Q2_median"] == f["forecast"]["2026Q2"]["gdp"]["median"]
    assert exp["cpi_2026Q2_median"] == f["forecast"]["2026Q2"]["cpi"]["median"]


def test_every_canary_has_an_anchor():
    for c in CANARIES.values():
        assert c.get("quoted_anchor"), c["id"]


def test_skipped_local_rows_do_not_count_as_drift(tmp_path, monkeypatch):
    def missing(canary):
        raise ModuleNotFoundError("No module named 'obr_macro'", name="obr_macro")
    monkeypatch.setattr(dc, "_local_call", missing)
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"obr_bank_rate_100bp":
                               _obr_response(NEW_PIN_PATH, PINS["OBR_REVISION"])}))
    report = tmp_path / "r.md"
    assert dc.main(["--from-raw", str(raw), "--only", "obr_bank_rate_100bp",
                    "--local", "--report", str(report)]) == 0
    assert "skipped" in report.read_text() and "obr_macro" in report.read_text()


def test_via_job_only_for_allow_listed_job_tools():
    import ast
    tree = ast.parse((INTEGRATION / "src/policyengine_macro/jobs.py").read_text())
    job_tools = next(
        ast.literal_eval(n.value) for n in tree.body
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "JOB_TOOLS"
    )
    for c in CANARIES.values():
        if c.get("via_job"):
            assert c["tool"] in job_tools, c["id"]
    # the two OBR solves took 122-130s direct on 6 Nov, inside the 150s ceiling
    # by too little; they must go through a job
    assert all(c.get("via_job") for c in CANARIES.values() if c["tool"] == "obr_shock")
