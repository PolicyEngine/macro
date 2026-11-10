"""Every tool's recorded model id, package and source URL match the registry.

Issue #225: ``obr_shock`` recorded ``model_id="obr-emulator"`` (not a registry
id, so its source URL fell back to the macro repo) and ``svar_summary`` asked
for the distribution ``boe-var-model`` (installed as ``boe_var``, so it
reported "not-installed"). OG-UK's recorded URL pointed at a repo that does
not exist. The check is static over every provenance call site in core.py, so
it covers tools whose compute is too heavy to run in the unit suite.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from policyengine_macro import core
from policyengine_macro.capabilities import MODELS

CORE_SRC = Path(core.__file__).read_text()

# pe-microsim records the country package it actually ran with.
PE_COUNTRY_PACKAGES = {"policyengine-uk", "policyengine-us"}


def _call_sites():
    """(line, model_id, distribution-node) for every provenance-bearing call."""
    sites = []
    for node in ast.walk(ast.parse(CORE_SRC)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if name not in {"_provenance", "_incidence_score_block", "ScoreResult"}:
            continue
        kw = {k.arg: k.value for k in node.keywords}
        id_node = kw.get("model" if name == "ScoreResult" else "model_id")
        if not isinstance(id_node, ast.Constant):
            continue  # forwarded variable; its callers are checked instead
        sites.append((node.lineno, id_node.value, kw.get("distribution")))
    return sites


SITES = [
    pytest.param(line, mid, dist, id=f"core.py:{line}-{mid}")
    for line, mid, dist in _call_sites()
]


def _constants(node):
    if isinstance(node, ast.Constant):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _constants(node.body) | _constants(node.orelse)
    raise AssertionError(f"unexpected distribution expression {ast.dump(node)}")


def test_call_sites_found():
    # Guard against a vacuous pass if the helpers are renamed.
    assert len(SITES) >= 20


@pytest.mark.parametrize("line,model_id,dist", SITES)
def test_recorded_model_id_is_a_registry_id(line, model_id, dist):
    known = set(MODELS) | set(core.INCIDENCE_OVERLAY_MODEL_IDS)
    assert model_id in known, f"core.py:{line} records unknown model id {model_id!r}"


@pytest.mark.parametrize("line,model_id,dist", SITES)
def test_recorded_package_matches_registry(line, model_id, dist):
    if dist is None or model_id not in MODELS:
        return
    expected = {MODELS[model_id]["package"]}
    if model_id == "pe-microsim":
        expected |= PE_COUNTRY_PACKAGES
    got = _constants(dist)
    assert got <= expected, (
        f"core.py:{line} records package {sorted(got)} for {model_id}; "
        f"registry says {MODELS[model_id]['package']!r}"
    )


@pytest.mark.parametrize("model_id", sorted(MODELS) + sorted(core.INCIDENCE_OVERLAY_MODEL_IDS))
def test_recorded_source_url_matches_registry(model_id):
    prov = core._provenance(
        model_id=model_id, distribution="x", data_vintage="v", baseline="b",
    )
    expected = MODELS.get(model_id, {}).get("source_url", core.MACRO_SOURCE_URL)
    assert prov["source_url"] == expected
    assert prov["model_id"] == model_id


def test_overlays_compose_registry_members():
    for overlay, member in core.INCIDENCE_OVERLAY_MODEL_IDS.items():
        assert member in MODELS, overlay
        assert overlay not in MODELS


def test_registry_urls_and_packages_are_distinct():
    urls = [m["source_url"] for k, m in MODELS.items() if k != "og+microsim"]
    assert len(urls) == len(set(urls))
    assert all(u.startswith("https://github.com/") for u in urls)


@pytest.mark.skipif(
    importlib.util.find_spec("boe_var") is None, reason="boe_var not installed"
)
def test_svar_summary_reports_installed_version():
    s = core.svar_summary()
    if "error" in s:
        pytest.skip(s["error"])
    assert s["provenance"]["package_version"] != "not-installed"
