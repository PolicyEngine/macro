"""US topic pages when the newest month has no counterpart a year earlier.

FRED publishes no CPIAUCSL value for 2025-10 (the row is blank in
fredgraph.csv), so when the October 2026 index arrived on 11 November 2026
``economy/topics.py`` raised ``TypeError: 'NoneType' object is not
subscriptable`` in ``us_inflation_note`` and the whole data refresh stopped
(Fetch data vintages run 42980628369). Main's committed data ends at 2026-09,
so these tests use a synthetic series with the same hole rather than the
store: a test that read the store would have passed before the fix.

What the pages must do instead: derive the rate for the newest month that has
a counterpart, say plainly that the newest month has none, and never derive a
number for it from some other month.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_topics():
    spec = importlib.util.spec_from_file_location(
        "topics_under_test", ROOT / "economy" / "topics.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


topics = _load_topics()


def _cpi(last: str) -> dict:
    """A monthly index 2024-01..``last`` with no 2025-10, like CPIAUCSL."""
    observations = []
    value = 300.0
    year, month = 2024, 1
    while f"{year}-{month:02d}" <= last:
        period = f"{year}-{month:02d}"
        value = round(value * 1.003, 3)
        if period != "2025-10":
            observations.append({"period": period, "value": value})
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "series": "us_cpi",
        "source": "FRED",
        "cdid": "CPIAUCSL",
        "title": "US consumer price index, all urban consumers",
        "units": "index 1982-84=100, seasonally adjusted",
        "url": "https://fred.stlouisfed.org/series/CPIAUCSL",
        "vintage": "2026-11-11",
        "first_period": "2024-01",
        "observations": observations,
    }


def _value(series: dict, period: str) -> float:
    return next(o["value"] for o in series["observations"] if o["period"] == period)


@pytest.fixture
def october_cpi(monkeypatch):
    series = _cpi("2026-10")
    monkeypatch.setattr(topics, "load", lambda name: series)
    return series


def test_latest_year_on_year_skips_to_the_newest_matched_month(october_cpi):
    now, before, unmatched = topics.latest_year_on_year(october_cpi)
    assert (now["period"], before["period"]) == ("2026-09", "2025-09")
    assert [row["period"] for row in unmatched] == ["2026-10"]


def test_latest_year_on_year_is_the_newest_month_when_nothing_is_missing():
    series = _cpi("2025-09")
    now, before, unmatched = topics.latest_year_on_year(series)
    assert (now["period"], before["period"], unmatched) == ("2025-09", "2024-09", [])


def test_us_inflation_note_survives_a_newest_month_with_no_year_earlier(october_cpi):
    note = topics.us_inflation_note()  # raised TypeError before the fix

    rate = 100 * (_value(october_cpi, "2026-09") / _value(october_cpi, "2025-09") - 1)
    assert f"in 2026-09 against {topics.stored(_value(october_cpi, '2025-09'))} in 2025-09 is {rate:.1f}%" in note
    assert "2026-10, has no year-on-year rate here" in note
    assert "no 2025-10 observation" in note
    # No number is derived for 2026-10 against some other month.
    for other in ("2025-09", "2025-11"):
        invented = 100 * (_value(october_cpi, "2026-10") / _value(october_cpi, other) - 1)
        assert f"{invented:.1f}%" not in note


def test_us_inflation_card_names_the_month_its_rate_is_for(october_cpi):
    card = topics.stat_card(october_cpi, "yoy")  # raised RuntimeError before the fix
    assert '<span class="stat-sub">2026-09 &middot;' in card
    assert "2026-10, has no year-on-year rate here" in card


def test_us_inflation_hook_pairs_the_rate_with_its_own_index(october_cpi):
    hook = topics.us_inflation_hook()
    assert "in 2026-09" in hook
    assert topics.stored(_value(october_cpi, "2026-09")) in hook
    # Before the fix the 2026-09 rate was printed beside the 2026-10 index.
    assert topics.stored(_value(october_cpi, "2026-10")) not in hook


def test_movement_does_not_call_a_two_month_gap_the_prior_month(monkeypatch):
    series = _cpi("2026-11")  # 2026-10 has no rate, so 2026-11 is compared with 2026-09
    monkeypatch.setattr(topics, "load", lambda name: series)
    text = topics.movement("us_cpi")
    assert "the prior month" not in text
    assert "against 2026-09, the latest earlier rate (2026-10 has none)" in text


def test_movement_wording_is_unchanged_when_the_prior_month_has_a_rate(october_cpi):
    text = topics.movement("us_cpi")
    assert text.endswith("against the prior month (2026-08)")


def test_previous_period():
    assert topics.previous_period("2026-01") == "2025-12"
    assert topics.previous_period("2026-11") == "2026-10"
    assert topics.previous_period("2026Q1") == "2025Q4"
    assert topics.previous_period("2026Q3") == "2026Q2"
