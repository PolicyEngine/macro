"""Deployment source revisions must be exact and synchronized."""

import ast
from pathlib import Path
import re


INTEGRATION = Path(__file__).resolve().parents[1]
PIN_NAMES = (
    "OBR_REVISION",
    "BOE_REVISION",
    "FRB_REVISION",
    "HANK_REVISION",
)


def _modal_pins() -> dict[str, str]:
    tree = ast.parse((INTEGRATION / "modal_app.py").read_text())
    pins: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id in PIN_NAMES
            and isinstance(node.value, ast.Constant)
        ):
            pins[target.id] = node.value.value
    return pins


def test_modal_model_sources_are_full_git_revisions():
    pins = _modal_pins()
    assert set(pins) == set(PIN_NAMES)
    for revision in pins.values():
        assert re.fullmatch(r"[0-9a-f]{40}", revision)


def test_optional_model_dependencies_use_deployment_revisions():
    pyproject = (INTEGRATION / "pyproject.toml").read_text()
    for revision in _modal_pins().values():
        assert f"@{revision}" in pyproject
