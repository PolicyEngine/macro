"""A run simulation is registered with policyengine so ensure() reuses it.

policyengine 6.11.1's calculate_decile_impacts calls Simulation.ensure(),
which re-runs (and saves to disk) any simulation not in its own cache. These
tests use a stand-in for policyengine.core.simulation, so no microdata is
needed.
"""

import sys
import types

from policyengine_macro import core


class _Cache:
    def __init__(self):
        self.items = {}

    def add(self, key, value):
        self.items[key] = value


def _install_fake(monkeypatch, cache):
    pkg = types.ModuleType("policyengine")
    core_pkg = types.ModuleType("policyengine.core")
    sim_mod = types.ModuleType("policyengine.core.simulation")
    if cache is not None:
        sim_mod._cache = cache
    core_pkg.simulation = sim_mod
    pkg.core = core_pkg
    monkeypatch.setitem(sys.modules, "policyengine", pkg)
    monkeypatch.setitem(sys.modules, "policyengine.core", core_pkg)
    monkeypatch.setitem(sys.modules, "policyengine.core.simulation", sim_mod)


def test_run_simulation_is_cached_under_its_storage_id(monkeypatch):
    cache = _Cache()
    _install_fake(monkeypatch, cache)
    sim = types.SimpleNamespace(storage_id="abc-123", output_dataset=object())
    core._pe_register_run(sim)
    assert cache.items == {"abc-123": sim}


def test_unrun_simulation_is_not_cached(monkeypatch):
    cache = _Cache()
    _install_fake(monkeypatch, cache)
    core._pe_register_run(types.SimpleNamespace(storage_id="x", output_dataset=None))
    assert cache.items == {}


def test_missing_private_cache_is_a_no_op(monkeypatch):
    _install_fake(monkeypatch, None)
    core._pe_register_run(types.SimpleNamespace(storage_id="x", output_dataset=object()))
