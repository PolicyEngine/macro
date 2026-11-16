"""Official benchmarks appear only beside rounds fixed after they were published.

The OBR EFO, BoE MPR and SEF are each stored by edition (forecasts/official/).
A newer edition knows more than an older forecast could, so it must never sit
beside a round archived before it; and one comparison never stitches values
from two editions.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORECASTS = HERE.parent
sys.path.insert(0, str(FORECASTS.parent))


def _load_score():
    spec = importlib.util.spec_from_file_location("score_editions", FORECASTS / "score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = _load_score()


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


class PublishedBefore(unittest.TestCase):
    def test_month_only_date_counts_from_month_end(self):
        self.assertFalse(score.published_before("2026-03", _utc("2026-03-15T00:00:00")))
        self.assertTrue(score.published_before("2026-03", _utc("2026-04-01T00:00:00")))

    def test_day_date(self):
        self.assertFalse(score.published_before("2026-10-28", _utc("2026-10-28T12:00:00")))
        self.assertTrue(score.published_before("2026-10-28", _utc("2026-10-29T00:00:00")))

    def test_latest_edition_does_not_stitch(self):
        editions = [("old", "2026-01", {"cpi": {"2026Q2": 1.0, "2026Q3": 1.5}}),
                    ("new", "2026-05", {"cpi": {"2026Q3": 2.0}})]
        fixed = _utc("2026-07-01T00:00:00")
        self.assertEqual(score.latest_edition(editions, fixed, "cpi", "2026Q3")[0], "new")
        self.assertIsNone(score.latest_edition(editions, fixed, "cpi", "2026Q2"))
        early = _utc("2026-03-01T00:00:00")
        self.assertEqual(score.latest_edition(editions, early, "cpi", "2026Q2")[0], "old")


class ScorecardRespectsPublication(unittest.TestCase):
    def test_no_benchmark_postdates_its_round(self):
        card = json.loads((FORECASTS / "scorecard.json").read_text())
        for detail in card["detail"]:
            fixed = score._parse_utc(detail["archived_utc"])
            exception = score.FIXED_BEFORE_ARCHIVE.get(detail["path"])
            if exception:
                fixed = score._parse_utc(exception["fixed_utc"])
            for entry in detail["entries"]:
                for b in entry["benchmarks"]:
                    self.assertTrue(score.published_before(b["fixed"], fixed),
                                    f"{detail['round_id']}: {b['label']} postdates the round")


if __name__ == "__main__":
    unittest.main()
