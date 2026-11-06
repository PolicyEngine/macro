"""The /models/compare page and the battery file behind it (macro#213)."""

from __future__ import annotations

import copy
import html
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "models" / "compare"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


battery = _module("compare_battery", HERE / "run_battery.py")
build = _module("compare_build", HERE / "build.py")
DATA = battery.load()
PAGE = (HERE / "index.html").read_text()


def test_results_file_meets_its_contract():
    assert battery.problems(DATA) == []


def test_page_is_current():
    result = subprocess.run([sys.executable, str(HERE / "build.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_every_question_has_every_model_in_hub_order():
    for q in DATA["questions"]:
        assert [c["model"] for c in q["cells"]] == list(battery.MODEL_ORDER)


def test_validator_catches_a_cell_without_provenance():
    bad = copy.deepcopy(DATA)
    del bad["questions"][0]["cells"][2]["run"]["args"]
    assert any("run.args missing" in p for p in battery.problems(bad))


def test_validator_catches_a_peak_that_disagrees_with_its_path():
    bad = copy.deepcopy(DATA)
    bad["questions"][0]["cells"][2]["gdp"]["value"] = -0.4
    assert any("path peak" in p for p in battery.problems(bad))


def test_validator_catches_a_number_without_units():
    bad = copy.deepcopy(DATA)
    bad["questions"][0]["cells"][0]["gdp"]["units"] = ""
    assert any("gdp has no units" in p for p in battery.problems(bad))


def test_hank_inflation_is_annualised_on_the_page():
    cell = DATA["questions"][0]["cells"][3]
    assert cell["model"] == "us-hank" and cell["path"]["inflation_scale"] == 4
    # Quarterly impact −0.3356pp × 4 = −1.34pp annual: the headline and the
    # stored path agree.
    assert round(cell["path"]["inflation"][0] * 4, 2) == cell["inflation"]["value"]


def test_frbus_stored_paths_reproduce_the_peaks():
    for q in DATA["questions"]:
        for cell in q["cells"]:
            if cell.get("path") and "gdp" in cell:
                peak = max(cell["path"]["gdp"], key=abs)
                assert round(peak, 3) == pytest.approx(cell["gdp"]["value"], abs=0.0015)


def test_monetary_caveat_is_on_the_page_not_folded():
    section = re.search(r'<section class="band cmp-q" id="q-rate-up-100".*?</section>', PAGE, re.S).group(0)
    assert "not like-for-like" in section
    assert "<details" not in section


def test_failures_and_flags_are_plain():
    assert "converged: false" in PAGE
    assert PAGE.count("No instrument") == sum(
        c["status"] == "no_instrument" for q in DATA["questions"] for c in q["cells"])
    for issue in DATA["issues"].values():
        assert issue["url"] in PAGE


def test_no_ticks_and_no_ranking_language():
    text = re.sub(r"<[^>]+>", " ", PAGE).lower()
    assert "✓" not in PAGE and "✔" not in PAGE
    for word in ("best model", "winner", "ranked first", "top model", "worst"):
        assert word not in text


def test_every_benchmark_is_sourced_or_says_none():
    for q in DATA["questions"]:
        section = re.search(rf'id="q-{q["id"]}".*?</section>', PAGE, re.S).group(0)
        if q["benchmarks"]:
            for bid in q["benchmarks"]:
                assert DATA["benchmarks"][bid]["url"] in section
        else:
            assert "None sourced" in section


def test_compare_tab_is_on_both_models_pages():
    models = (ROOT / "models" / "index.html").read_text()
    assert 'href="/models/compare">Same question</a>' in models
    assert 'href="/models/compare" aria-current="page">Same question</a>' in PAGE


def test_refresh_rejects_heavy_models():
    with pytest.raises(SystemExit):
        battery.refresh(json.loads(json.dumps(DATA)), "us-hank")


def _section(qid: str) -> str:
    return re.search(rf'<section class="band cmp-q" id="q-{qid}".*?</section>', PAGE, re.S).group(0)


def test_every_fact_moves_to_details_not_out():
    """The headline rows are short; the run call, reason, units and flags stay on the page."""
    import html as _html
    text = _html.unescape(PAGE)
    for q in DATA["questions"]:
        section = _html.unescape(_section(q["id"]))
        for cell in q["cells"]:
            if cell["status"] != "answered":
                continue
            assert build.call_text(cell["run"]) in section
            for key in ("reason", "verdict_label", "solver", "draws", "experiment", "rate_path",
                        "timing", "multiplier", "symmetry", "linearity", "result"):
                if cell.get(key):
                    assert cell[key] in section, (q["id"], cell["model"], key)
            for key in ("gdp", "inflation"):
                if cell.get(key):
                    assert cell[key]["units"] in section
    assert "186 accepted draws" in text and "744 accepted draws" in text


def test_headline_verdicts_are_short_and_benchmark_row_leads():
    for q in DATA["questions"]:
        for cell in q["cells"]:
            if cell["status"] == "answered":
                assert len(cell["short"]["why"].split()) <= 10
                assert len(cell["short"].get("timing", "").split()) <= 4
        body = _section(q["id"]).split("<tbody>", 1)[1]
        assert body.lstrip().startswith('<tr class="cmp-bench-row">')
        assert 'class="cmp-takeaway"' in _section(q["id"])


def test_validator_catches_a_long_verdict_reason():
    bad = copy.deepcopy(DATA)
    bad["questions"][0]["cells"][0]["short"]["why"] = " ".join(["word"] * 11)
    assert any("over 10 words" in p for p in battery.problems(bad))


def test_takeaway_uses_no_ranking_language():
    for q in DATA["questions"]:
        line = re.search(r'<p class="cmp-takeaway">(.*?)</p>', _section(q["id"])).group(1).lower()
        for word in ("best", "better", "worse", "most accurate", "only"):
            assert word not in line


def test_takeaway_names_the_model_behind_each_verdict():
    # r5 usability test (#220): "which answer holds up?" is read off this line.
    for q in DATA["questions"]:
        line = html.unescape(re.search(r'<p class="cmp-takeaway">(.*?)</p>', _section(q["id"])).group(1))
        for cell in q["cells"]:
            if cell["status"] == "answered":
                assert DATA["models"][cell["model"]]["name"] in line
