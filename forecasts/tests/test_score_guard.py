"""The scoring guard compares with the publisher's release time (#242).

A forecast is scored only if it was fixed before the outturn was first
published. The guard used to compare the archive date with the day our store
fetched the value, from the latest vintage, by date only.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORECASTS = HERE.parent
ROOT = FORECASTS.parent
sys.path.insert(0, str(ROOT))


def _load_score():
    spec = importlib.util.spec_from_file_location("score_under_test", FORECASTS / "score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = _load_score()

BAND = {"median": 1.567, "lo68": 1.0, "hi68": 2.1, "lo90": 0.6, "hi90": 2.5}


def rnd(archived: str, path: str = "x") -> dict:
    return {
        "archived_utc": archived,
        "round_id": archived[:10],
        "_path": path,
        "model": {"name": "boe-svar"},
        "information_set": {"data_edge": "2026Q2"},
        "forecast": {"2026Q3": {"gdp": dict(BAND)}},
    }


def obs(vintage: str, released: str | None) -> dict:
    return {
        "period": "2026Q3",
        "variable": "gdp",
        "value": 1.94,
        "vintage": vintage,
        "series": "uk_gdp_cvm",
        "release_updated": released,
    }


def scored(r: dict, observations: list[dict]) -> int:
    return len(score.score_round(r, score.latest_outturns(observations))["entries"])


class IssueCases(unittest.TestCase):
    """The three cases from #242, each of which used to be scored."""

    def test_store_lags_the_publisher(self):
        self.assertEqual(
            scored(rnd("2026-11-16T05:10:00Z"), [obs("2026-12-23", "2026-11-12T00:00:00.000Z")]), 0
        )

    def test_revision_does_not_reset_first_publication(self):
        self.assertEqual(
            scored(
                rnd("2026-12-01T05:10:00Z"),
                [
                    obs("2026-11-13", "2026-11-12T00:00:00.000Z"),
                    obs("2026-12-23", "2026-12-22T00:00:00.000Z"),
                ],
            ),
            0,
        )

    def test_same_day_after_release(self):
        self.assertEqual(
            scored(rnd("2026-11-12T11:46:00Z"), [obs("2026-11-12", "2026-11-12T00:00:00.000Z")]), 0
        )


class ReleaseHour(unittest.TestCase):
    def test_archived_before_0700_on_release_day_is_scored(self):
        # Round 2026-11-12 was archived at 05:13 UTC; ONS released at 07:00.
        self.assertEqual(
            scored(rnd("2026-11-12T05:13:50Z"), [obs("2026-11-15", "2026-11-12T00:00:00.000Z")]), 1
        )

    def test_summer_stamp_is_uk_midnight(self):
        # 2026-07-21T23:00Z is 00:00 BST on 22 July; release at 06:00 UTC.
        released = "2026-07-21T23:00:00.000Z"
        self.assertEqual(scored(rnd("2026-07-22T05:59:00Z"), [obs("2026-07-25", released)]), 1)
        self.assertEqual(scored(rnd("2026-07-22T06:00:00Z"), [obs("2026-07-25", released)]), 0)

    def test_scored_value_is_the_latest_vintage(self):
        r = rnd("2026-11-12T05:13:50Z")
        first = obs("2026-11-15", "2026-11-12T00:00:00.000Z")
        revised = dict(obs("2026-12-23", "2026-12-22T00:00:00.000Z"), value=2.05)
        entries = score.score_round(r, score.latest_outturns([first, revised]))["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["outturn"], 2.05)

    def test_no_release_stamp_falls_back_to_fetch_day(self):
        self.assertEqual(scored(rnd("2026-11-14T23:00:00Z"), [obs("2026-11-15", None)]), 1)
        self.assertEqual(scored(rnd("2026-11-15T00:00:00Z"), [obs("2026-11-15", None)]), 0)


class DocumentedExceptions(unittest.TestCase):
    def test_each_exception_matches_its_round(self):
        for rel, exception in score.FIXED_BEFORE_ARCHIVE.items():
            with self.subTest(round=rel):
                round_doc = json.loads((ROOT / rel).read_text())
                self.assertEqual(
                    round_doc["provenance"]["source_sha256"], exception["source_sha256"]
                )
                fixed = score._parse_utc(exception["fixed_utc"])
                archived = score._parse_utc(round_doc["archived_utc"])
                self.assertLess(fixed, archived, "an exception may only move the time earlier")

    def test_exception_keeps_the_2026_07_21_cpi_entry(self):
        rounds = {r["_path"]: r for r in score.load_rounds()}
        r = rounds["forecasts/rounds/2026-07-21/boe-svar.json"]
        doc = json.loads((FORECASTS / "outturns.json").read_text())
        entries = score.score_round(r, score.latest_outturns(doc["observations"]))["entries"]
        self.assertIn(("2026Q2", "cpi"), {(e["period"], e["variable"]) for e in entries})


if __name__ == "__main__":
    unittest.main()
