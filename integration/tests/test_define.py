"""DEFINE-UK local-only surface: instructions without the adapter, deltas with it."""

import builtins

import pytest

from policyengine_macro import core


def _has_define():
    try:
        import define_uk.scenarios  # noqa: F401
        return True
    except ImportError:
        return False


def test_instructions_when_adapter_missing(monkeypatch):
    real_import = builtins.__import__

    def block_define(name, *a, **k):
        if name.startswith("define_uk"):
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", block_define)
    for res in (core.define_list_scenarios(), core.define_scenario("fossil_fuel_ban")):
        assert res["available"] is False
        assert "never hosted" in res["how_to_run"]
        assert "define-uk-model" in res["how_to_run"]


@pytest.mark.skipif(not _has_define(), reason="define_uk not installed")
def test_scenarios_list_and_deltas():
    listing = core.define_list_scenarios()
    if not listing.get("available"):
        pytest.skip("no cached DEFINE-UK run")
    names = {s["name"] for s in listing["scenarios"]}
    assert {"fossil_fuel_ban", "green_public_investment"} <= names

    res = core.define_scenario("fossil_fuel_ban")
    if not res.get("available"):
        pytest.skip("no cached DEFINE-UK run")
    assert res["result_type"] == "scenario deltas"
    assert res["model"] == "define-uk"
    assert res["caveats"], "mandatory caveats missing"
    assert "GDP_R" in res["variables"]
    assert len(res["years"]) == len(res["variables"]["GDP_R"]["delta_level"])


def test_capability_entry_exists():
    from policyengine_macro.capabilities import MODELS
    cap = MODELS["define-uk"]
    assert "local CLI scenarios" in cap["access"]
    assert "hosted" not in cap["access"]
    assert any("score_reform refuses" in c for c in cap["cannot_answer"])
