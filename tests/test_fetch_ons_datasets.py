"""``data/fetch.py`` keeps the newest of the ONS datasets that publish a series.

The regression this prevents (#241)
-----------------------------------
UK real GDP (ABMI) is published in two ONS datasets, and each is updated by a
different release. PN2 changes at the GDP first quarterly estimate. QNA changes
at the Quarterly National Accounts. The fetcher used to read QNA only, so the
2026Q3 first estimate (12 Nov 2026) never reached the store. These tests use
canned payloads with no network access, and check that:

* the dataset with the newer release is the one stored, in both directions;
* the stored ``url`` names the dataset that was used;
* a failure on any one dataset fails the series rather than falling back;
* the store never takes an older release than the one it already holds.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

QNA = "economy/grossdomesticproductgdp/timeseries/abmi/qna"
PN2 = "economy/grossdomesticproductgdp/timeseries/abmi/pn2"


def _load_fetch():
    spec = importlib.util.spec_from_file_location("fetch_under_test", ROOT / "data" / "fetch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(stamp: str, quarters: dict[str, str], next_release: str) -> dict:
    return {
        "description": {"title": "Gross Domestic Product: chained volume measures: Seasonally adjusted £m", "nextRelease": next_release},
        "quarters": [
            {"year": p[:4], "quarter": p[4:], "value": v, "updateDate": stamp}
            for p, v in quarters.items()
        ],
    }


QNA_SEP = _payload("2026-09-29T23:00:00.000Z", {"2026Q1": "740509", "2026Q2": "744453"}, "12 November 2026")
PN2_NOV = _payload(
    "2026-11-12T00:00:00.000Z",
    {"2026Q1": "740509", "2026Q2": "744453", "2026Q3": "749999"},
    "22 December 2026",
)
PN2_AUG = _payload("2026-08-13T00:00:00.000Z", {"2026Q1": "740100", "2026Q2": "744000"}, "30 September 2026")


@pytest.fixture
def fetch(tmp_path, monkeypatch):
    module = _load_fetch()
    monkeypatch.setattr(module, "VINTAGES", tmp_path / "vintages")
    return module


def _serve(monkeypatch, module, responses: dict):
    def fake_get_json(url):
        for path, payload in responses.items():
            if url == f"https://www.ons.gov.uk/{path}/data":
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(module, "get_json", fake_get_json)


def _stored(module, vintage: str) -> dict:
    return json.loads((module.VINTAGES / "ons" / "uk_gdp_cvm" / f"{vintage}.json").read_text())


def test_gdp_lists_both_abmi_datasets(fetch):
    spec = fetch.ONS_SERIES["uk_gdp_cvm"]
    assert {spec["path"], *spec["alternates"]} == {QNA, PN2}


def test_first_estimate_in_pn2_is_stored(fetch, monkeypatch):
    _serve(monkeypatch, fetch, {QNA: QNA_SEP, PN2: PN2_NOV})
    spec = fetch.ONS_SERIES["uk_gdp_cvm"]

    assert fetch.fetch_series("uk_gdp_cvm", spec, "2026-11-15") == "written"
    stored = _stored(fetch, "2026-11-15")
    assert stored["last_period"] == "2026Q3"
    assert stored["url"] == f"https://www.ons.gov.uk/{PN2}/data"
    assert stored["next_release"] == "22 December 2026"


def test_quarterly_accounts_in_qna_win_when_newer(fetch, monkeypatch):
    _serve(monkeypatch, fetch, {QNA: QNA_SEP, PN2: PN2_AUG})
    spec = fetch.ONS_SERIES["uk_gdp_cvm"]

    assert fetch.fetch_series("uk_gdp_cvm", spec, "2026-10-01") == "written"
    stored = _stored(fetch, "2026-10-01")
    assert stored["url"] == f"https://www.ons.gov.uk/{QNA}/data"
    assert stored["release_updated"] == "2026-09-29T23:00:00.000Z"


def test_a_failed_dataset_fails_the_series(fetch, monkeypatch):
    _serve(monkeypatch, fetch, {QNA: QNA_SEP, PN2: urllib.error.URLError("down")})
    spec = fetch.ONS_SERIES["uk_gdp_cvm"]

    with pytest.raises(urllib.error.URLError):
        fetch.fetch_series("uk_gdp_cvm", spec, "2026-11-15")
    assert not (fetch.VINTAGES / "ons" / "uk_gdp_cvm").exists()


def test_store_never_takes_an_older_release(fetch, monkeypatch):
    spec = fetch.ONS_SERIES["uk_gdp_cvm"]
    _serve(monkeypatch, fetch, {QNA: QNA_SEP, PN2: PN2_NOV})
    assert fetch.fetch_series("uk_gdp_cvm", spec, "2026-11-15") == "written"

    # Both datasets now serve something older than what is stored, as a stale
    # cache might. Nothing may be written.
    _serve(monkeypatch, fetch, {QNA: QNA_SEP, PN2: PN2_AUG})
    assert fetch.fetch_series("uk_gdp_cvm", spec, "2026-11-16") == "stale"
    assert not (fetch.VINTAGES / "ons" / "uk_gdp_cvm" / "2026-11-16.json").exists()


def test_unchanged_newest_release_writes_nothing(fetch, monkeypatch):
    spec = fetch.ONS_SERIES["uk_gdp_cvm"]
    _serve(monkeypatch, fetch, {QNA: QNA_SEP, PN2: PN2_NOV})
    assert fetch.fetch_series("uk_gdp_cvm", spec, "2026-11-15") == "written"
    assert fetch.fetch_series("uk_gdp_cvm", spec, "2026-11-16") == "unchanged"


def test_single_dataset_series_reads_only_its_path(fetch, monkeypatch):
    spec = fetch.ONS_SERIES["uk_cpi_yoy"]
    assert "alternates" not in spec
    seen = []

    def fake_get_json(url):
        seen.append(url)
        return {"description": {}, "quarters": [{"year": "2026", "quarter": "Q3", "value": "3.1", "updateDate": "2026-10-21T00:00:00.000Z"}]}

    monkeypatch.setattr(fetch, "get_json", fake_get_json)
    assert fetch.fetch_series("uk_cpi_yoy", spec, "2026-11-15") == "written"
    assert seen == [f"https://www.ons.gov.uk/{spec['path']}/data"]
