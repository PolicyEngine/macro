"""The track record says plainly when it was last scored (r5 usability test, #220).

The date shown must be the newest outturn snapshot any scored forecast was
read from, so a stalled pipeline shows up as an old date on the page.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_forecasts_page_states_when_the_record_was_last_scored():
    card = json.loads((ROOT / "forecasts" / "scorecard.json").read_text())
    vintages = [e["outturn_vintage"] for d in card["detail"] for e in d["entries"]]
    page = (ROOT / "forecasts" / "index.html").read_text()
    m = re.search(r'<p class="record-asof"><strong>Last scored <time datetime="([0-9-]+)">', page)
    assert m, "the scoreboard has no 'Last scored' line"
    assert m.group(1) == max(vintages)
    # It sits above the tiles, not under them.
    assert page.index('class="record-asof"') < page.index('aria-label="The record so far"')
