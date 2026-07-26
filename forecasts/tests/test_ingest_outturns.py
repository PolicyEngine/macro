import unittest

from forecasts.ingest_outturns import merge


def observation(value, vintage, period="2026Q2", variable="cpi"):
    return {
        "period": period,
        "variable": variable,
        "value": value,
        "vintage": vintage,
    }


class MergeTests(unittest.TestCase):
    def test_metadata_only_snapshot_does_not_duplicate_outturn(self):
        original = observation(2.8, "2026-07-25")
        merged, added = merge([original], [observation(2.8, "2026-07-26")])

        self.assertEqual(merged, [original])
        self.assertEqual(added, [])

    def test_changed_value_appends_revision(self):
        original = observation(2.8, "2026-07-25")
        revision = observation(2.9, "2026-08-19")
        merged, added = merge([original], [revision])

        self.assertEqual(merged, [original, revision])
        self.assertEqual(added, [revision])

    def test_revision_back_to_earlier_value_is_still_recorded(self):
        existing = [
            observation(2.8, "2026-07-25"),
            observation(2.9, "2026-08-19"),
        ]
        revision = observation(2.8, "2026-09-16")
        merged, added = merge(existing, [revision])

        self.assertEqual(merged, existing + [revision])
        self.assertEqual(added, [revision])

    def test_periods_and_variables_are_compared_independently(self):
        existing = [
            observation(2.8, "2026-07-25"),
            observation(1.1, "2026-07-25", variable="gdp"),
        ]
        gdp_revision = observation(1.2, "2026-08-19", variable="gdp")
        merged, added = merge(
            existing,
            [
                observation(2.8, "2026-07-26"),
                gdp_revision,
                observation(2.8, "2026-07-26", period="2026Q3"),
            ],
        )

        self.assertEqual(added, [gdp_revision, observation(2.8, "2026-07-26", period="2026Q3")])
        self.assertEqual(merged, existing + added)


if __name__ == "__main__":
    unittest.main()
