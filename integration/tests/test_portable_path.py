"""Hosted results must not name the account a path was built under."""

import os

from policyengine_macro import core


def test_paths_under_any_home_are_shortened():
    assert core._portable_path("/Users/someone/us-frb-model/vendor") == "~/us-frb-model/vendor"
    assert core._portable_path("/home/ci/boe-var-model/results") == "~/boe-var-model/results"


def test_own_home_is_shortened():
    home = os.path.expanduser("~")
    assert core._portable_path(os.path.join(home, "x", "y")) == "~/x/y"


def test_neutral_paths_are_unchanged():
    assert core._portable_path("/opt/policyengine-models/us-frb-model") == "/opt/policyengine-models/us-frb-model"
