"""Log-basis rounds are scored on the simple four-quarter rate (#208).

boe-svar rounds archived before 6 Nov 2026 hold 100*log(P_t/P_{t-4}). The
outturns and the published forecasts beside them are 100*(P_t/P_{t-4} - 1).
score.py converts the archived number as it reads the round; the round file
is never rewritten.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORECASTS = HERE.parent
ROOT = FORECASTS.parent
sys.path.insert(0, str(ROOT))


def _load_score():
    spec = importlib.util.spec_from_file_location("score_basis_under_test", FORECASTS / "score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = _load_score()
KEYS = ("median", "lo68", "hi68", "lo90", "hi90")


class Conversion(unittest.TestCase):
    def test_matches_the_definition_on_a_known_level_path(self):
        # Prices up 5% on the year: log difference 4.879, simple rate 5.
        p0, p4 = 100.0, 105.0
        log_diff = 100.0 * math.log(p4 / p0)
        self.assertAlmostEqual(score.log_to_simple_pct(log_diff), 100.0 * (p4 / p0 - 1.0), places=12)
        self.assertAlmostEqual(score.log_to_simple_pct(0.0), 0.0, places=12)
        self.assertLess(score.log_to_simple_pct(-2.0), 0.0)

    def test_is_monotone_so_band_order_survives(self):
        xs = [-3.0, -0.5, 0.0, 1.1, 2.7, 9.0]
        ys = [score.log_to_simple_pct(x) for x in xs]
        self.assertEqual(ys, sorted(ys))

    def test_a_round_that_is_not_listed_is_returned_untouched(self):
        doc = {"_path": "forecasts/rounds/2099-01-01/boe-svar.json",
               "forecast": {"2099Q1": {"cpi": dict.fromkeys(KEYS, 2.0)}}}
        self.assertIs(score.on_simple_basis(doc), doc)

    def test_a_listed_round_converts_growth_rates_only_and_leaves_its_input(self):
        rel = next(iter(score.LOG_BASIS_ROUNDS))
        block = {"cpi": dict.fromkeys(KEYS, 3.0), "unemployment": dict.fromkeys(KEYS, 4.9)}
        doc = {"_path": rel, "forecast": {"2026Q2": block}}
        out = score.on_simple_basis(doc)
        self.assertEqual(doc["forecast"]["2026Q2"]["cpi"]["median"], 3.0)
        cpi = out["forecast"]["2026Q2"]["cpi"]
        for key in KEYS:
            self.assertAlmostEqual(cpi[key], 100.0 * math.expm1(0.03), places=12)
        self.assertEqual(cpi["median_archived_log_basis"], 3.0)
        # A level, not a growth rate: not converted.
        self.assertEqual(out["forecast"]["2026Q2"]["unemployment"]["median"], 4.9)


class ArchivedRounds(unittest.TestCase):
    def test_every_boe_svar_round_has_a_known_basis(self):
        """A new round must either say 'simple' in its units or be listed."""
        for path in sorted((FORECASTS / "rounds").glob("*/boe-svar.json")):
            rel = str(path.relative_to(ROOT))
            units = json.loads(path.read_text())["units"].lower()
            with self.subTest(round=rel):
                self.assertNotEqual(
                    rel in score.LOG_BASIS_ROUNDS, "simple" in units,
                    "a boe-svar round is on the simple basis (its units say so) "
                    "or is listed in LOG_BASIS_ROUNDS, never both and never neither",
                )

    def test_listed_rounds_exist_and_are_not_rewritten(self):
        for rel in score.LOG_BASIS_ROUNDS:
            with self.subTest(round=rel):
                raw = json.loads((ROOT / rel).read_text())
                loaded = {r["_path"]: r for r in score.load_rounds()}[rel]
                for period, block in raw["forecast"].items():
                    for variable in score.LOG_BASIS_VARIABLES:
                        if variable not in block:
                            continue
                        got = loaded["forecast"][period][variable]
                        for key in KEYS:
                            self.assertAlmostEqual(
                                got[key], 100.0 * math.expm1(block[variable][key] / 100.0), places=12
                            )
                        self.assertGreaterEqual(got["median"], block[variable]["median"])

    def test_scored_entries_of_a_listed_round_carry_the_archived_median(self):
        rel = "forecasts/rounds/2026-07-21/boe-svar.json"
        raw = json.loads((ROOT / rel).read_text())
        r = {x["_path"]: x for x in score.load_rounds()}[rel]
        doc = json.loads((FORECASTS / "outturns.json").read_text())
        entries = score.score_round(r, score.latest_outturns(doc["observations"]))["entries"]
        cpi = next(e for e in entries if (e["period"], e["variable"]) == ("2026Q2", "cpi"))
        archived = raw["forecast"]["2026Q2"]["cpi"]["median"]
        self.assertEqual(cpi["forecast_archived_log_basis"], archived)
        self.assertAlmostEqual(cpi["forecast"], 100.0 * math.expm1(archived / 100.0), places=12)
        self.assertAlmostEqual(cpi["error"], cpi["forecast"] - cpi["outturn"], places=12)

    def test_simple_basis_rounds_score_as_archived(self):
        rel = "forecasts/rounds/2026-11-12/boe-svar.json"
        raw = json.loads((ROOT / rel).read_text())
        r = {x["_path"]: x for x in score.load_rounds()}[rel]
        self.assertEqual(r["forecast"], raw["forecast"])
        doc = json.loads((FORECASTS / "outturns.json").read_text())
        for e in score.score_round(r, score.latest_outturns(doc["observations"]))["entries"]:
            self.assertNotIn("forecast_archived_log_basis", e)


if __name__ == "__main__":
    unittest.main()
