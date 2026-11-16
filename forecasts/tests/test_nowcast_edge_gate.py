"""``nowcast.py --edge-gate`` must stop a round before the Modal call when the
hosted model cannot produce a new one.

The hosted forecast_uk reads boe-var-model's data at BOE_REVISION, which ended
2026Q1 while both archived boe-svar rounds already had edge 2026Q1. Every due
day then cost a ~5.5-minute cold Modal solve that write_round refused as
"already archived" (12-13 and 17-19 Aug 2026; issue #224).
"""

import unittest
from unittest import mock

from forecasts import nowcast

CSV = "quarter,uk_gdp\n2025Q4,1346.6\n2026Q1,1347.2\n"


class EdgeGateTests(unittest.TestCase):
    def test_hosted_edge_already_archived_is_skipped(self):
        proceed, reason = nowcast.edge_gate("2026Q1", {"2026Q1"})
        self.assertFalse(proceed)
        self.assertIn("no Modal call", reason)
        self.assertIn("2026Q2", reason)

    def test_hosted_edge_older_than_archived_is_skipped(self):
        self.assertFalse(nowcast.edge_gate("2025Q4", {"2026Q1"})[0])

    def test_newer_hosted_edge_proceeds(self):
        self.assertTrue(nowcast.edge_gate("2026Q2", {"2026Q1"})[0])
        self.assertTrue(nowcast.edge_gate("2027Q1", {"2026Q1", "2026Q4"})[0])

    def test_unknown_edge_or_empty_record_proceeds(self):
        self.assertTrue(nowcast.edge_gate(None, {"2026Q1"})[0])
        self.assertTrue(nowcast.edge_gate("2026Q1", set())[0])

    def test_quarter_arithmetic_crosses_the_year(self):
        self.assertEqual(nowcast.next_quarter("2026Q4"), "2027Q1")
        self.assertEqual(nowcast.next_quarter("2026Q1"), "2026Q2")

    def test_last_quarter_of_the_bundled_csv(self):
        self.assertEqual(nowcast.last_quarter(CSV), "2026Q1")
        self.assertIsNone(nowcast.last_quarter("quarter,x\n"))

    def test_revision_is_read_from_the_modal_app(self):
        self.assertEqual(
            nowcast.hosted_revision('BOE_REVISION = "42cbcbb728b55b3f416764568fa8f3aef68a6730"\n'),
            "42cbcbb728b55b3f416764568fa8f3aef68a6730",
        )
        # The real file pins one, so the gate never silently runs blind.
        self.assertIsNotNone(nowcast.hosted_revision())

    def test_cli_skips_without_touching_the_model(self):
        with mock.patch("sys.argv", ["nowcast.py", "--edge-gate"]), \
                mock.patch.object(nowcast, "hosted_data_edge", return_value="2026Q1"), \
                mock.patch.object(nowcast, "archived_data_edges", return_value={"2026Q1"}), \
                mock.patch.object(nowcast, "fetch_forecast") as fetch, \
                mock.patch("builtins.print"):
            self.assertEqual(nowcast.main(), 1)
            fetch.assert_not_called()

    def test_cli_proceeds_on_a_new_edge(self):
        with mock.patch("sys.argv", ["nowcast.py", "--edge-gate"]), \
                mock.patch.object(nowcast, "hosted_data_edge", return_value="2026Q2"), \
                mock.patch.object(nowcast, "archived_data_edges", return_value={"2026Q1"}), \
                mock.patch("builtins.print"):
            self.assertEqual(nowcast.main(), 0)

    def test_cli_skips_when_the_open_round_pr_already_holds_this_edge(self):
        # PR #238: main's rounds end at 2026Q1, the hosted data at 2026Q2, and
        # an unmerged 2026Q2 round sits on the PR branch. Regenerating it
        # replaced round 2026-11-11 with an identical round 2026-11-12.
        argv = ["nowcast.py", "--edge-gate", "--pending-ref", "origin/forecasts/nowcast-round"]
        with mock.patch("sys.argv", argv), \
                mock.patch.object(nowcast, "hosted_data_edge", return_value="2026Q2"), \
                mock.patch.object(nowcast, "archived_data_edges", return_value={"2026Q1"}), \
                mock.patch.object(nowcast, "pending_data_edges", return_value={"2026Q2"}), \
                mock.patch.object(nowcast, "fetch_forecast") as fetch, \
                mock.patch("builtins.print") as out:
            self.assertEqual(nowcast.main(), 1)
            fetch.assert_not_called()
        self.assertIn("already waiting", out.call_args[0][0])

    def test_cli_proceeds_when_the_hosted_edge_is_newer_than_the_pending_round(self):
        argv = ["nowcast.py", "--edge-gate", "--pending-ref", "origin/forecasts/nowcast-round"]
        with mock.patch("sys.argv", argv), \
                mock.patch.object(nowcast, "hosted_data_edge", return_value="2026Q3"), \
                mock.patch.object(nowcast, "archived_data_edges", return_value={"2026Q1"}), \
                mock.patch.object(nowcast, "pending_data_edges", return_value={"2026Q2"}), \
                mock.patch("builtins.print"):
            self.assertEqual(nowcast.main(), 0)

    def test_pending_edges_are_read_from_the_ref(self):
        files = {
            "forecasts/rounds/2026-07-29/boe-svar.json": '{"information_set": {"data_edge": "2026Q1"}}',
            "forecasts/rounds/2026-11-12/boe-svar.json": '{"information_set": {"data_edge": "2026Q2"}}',
            "forecasts/rounds/2026-07-28/okun-unemployment.json": '{"information_set": {"data_edge": "2025Q4"}}',
        }

        def fake_git(*args):
            if args[0] == "ls-tree":
                return "\n".join(files)
            if args[0] == "show":
                return files[args[1].split(":", 1)[1]]
            return None

        with mock.patch.object(nowcast, "git", side_effect=fake_git):
            self.assertEqual(nowcast.pending_data_edges("origin/x"), {"2026Q1", "2026Q2"})

    def test_an_unreadable_ref_adds_no_edges(self):
        # No open PR, or the branch was not fetched: the gate must behave as
        # it did before, never block.
        with mock.patch.object(nowcast, "git", return_value=None):
            self.assertEqual(nowcast.pending_data_edges("origin/missing"), set())
        argv = ["nowcast.py", "--edge-gate", "--pending-ref", "origin/missing"]
        with mock.patch("sys.argv", argv), \
                mock.patch.object(nowcast, "hosted_data_edge", return_value="2026Q2"), \
                mock.patch.object(nowcast, "archived_data_edges", return_value={"2026Q1"}), \
                mock.patch.object(nowcast, "git", return_value=None), \
                mock.patch("builtins.print"):
            self.assertEqual(nowcast.main(), 0)


if __name__ == "__main__":
    unittest.main()
