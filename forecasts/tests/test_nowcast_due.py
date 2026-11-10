"""``nowcast.py --due`` must tell a stale calendar from a quiet week.

From 17 September to November 2026 every scored series' ``next_release`` in
data/latest was in the past (the store stopped refreshing on 26 August), so
``--due`` found nothing and the nowcast job was green every weekday while GDP,
CPI and unemployment were released with no round archived ahead of them.
"""

import unittest
from datetime import date
from unittest import mock

from forecasts import nowcast

TODAY = date(2026, 11, 6)


def calendar(*entries):
    return mock.patch.object(nowcast, "announced_releases", return_value=list(entries))


class StaleCalendarTests(unittest.TestCase):
    def test_all_past_releases_are_a_stale_calendar(self):
        past = [(date(2026, 8, 13), "uk_gdp_cvm"), (date(2026, 9, 16), "uk_cpi_yoy")]
        with calendar(*past):
            self.assertEqual(nowcast.stale_calendar(TODAY), past)

    def test_one_future_release_is_not_stale(self):
        with calendar((date(2026, 9, 16), "uk_cpi_yoy"), (date(2026, 11, 12), "uk_gdp_cvm")):
            self.assertIsNone(nowcast.stale_calendar(TODAY))

    def test_a_release_today_is_not_stale(self):
        with calendar((TODAY, "uk_gdp_cvm")):
            self.assertIsNone(nowcast.stale_calendar(TODAY))

    def test_an_empty_calendar_is_stale(self):
        with calendar():
            self.assertEqual(nowcast.stale_calendar(TODAY), [])

    def test_due_is_unchanged_for_a_live_calendar(self):
        with calendar((date(2026, 11, 12), "uk_gdp_cvm"), (date(2026, 11, 18), "uk_cpi_yoy")):
            self.assertEqual(nowcast.due(3, date(2026, 11, 9)), [(date(2026, 11, 12), "uk_gdp_cvm")])
            self.assertEqual(nowcast.due(3, TODAY), [])

    def test_cli_exits_2_on_a_stale_calendar(self):
        past = [(date(2026, 8, 13), "uk_gdp_cvm")]
        with calendar(*past), mock.patch("sys.argv", ["nowcast.py", "--due", "3"]), \
                mock.patch.object(nowcast, "datetime") as dt, \
                mock.patch("builtins.print"):
            dt.now.return_value.date.return_value = TODAY
            self.assertEqual(nowcast.main(), 2)


if __name__ == "__main__":
    unittest.main()
