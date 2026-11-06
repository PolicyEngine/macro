"""The hand-typed OBR validation figures must match the committed CSVs."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "validation" / "check_obr_tables.py"


def test_obr_validation_figures_match_csvs():
    spec = importlib.util.spec_from_file_location("check_obr_tables", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0
