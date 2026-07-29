"""Build the current boe-svar forecast data used by the live site.

This is deliberately separate from ``make_figures.py``.  The latter freezes
the information set at 2024Q2 for honest out-of-sample validation; this script
publishes the forecast from the latest complete quarterly data edge.

It calls the hosted adapter (``policyengine_macro.core.svar_forecast``) rather
than re-implementing the pipeline, so the published artifact and the hosted
model cannot drift apart: same estimation sample, same importance weights,
same defaults. Run it inside the integration environment::

    integration/.venv/bin/python papers/boe-svar/figures/make_current_forecast.py
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "integration" / "src"))

from policyengine_macro.core import svar_forecast  # noqa: E402

# 5600 draws clears the adapter's own effective-sample-size guidance for
# publication-grade bands; the hosted interactive default is lower.
N_DRAWS = 5600
HORIZONS = 13


def main() -> None:
    res = svar_forecast(horizons=HORIZONS, draws=N_DRAWS)
    if res["warnings"]:
        raise RuntimeError(f"adapter warnings, refusing to publish: {res['warnings']}")

    origin = res["forecast_origin"]
    by_quarter: dict[str, dict] = {}
    for var, key in (("gdp", "gdp_growth_yoy"), ("cpi", "cpi_inflation_yoy")):
        for row in res[key]:
            by_quarter.setdefault(row["quarter"], {})[var] = {
                k: row[k] for k in ("median", "lo68", "hi68", "lo90", "hi90")
            }

    quarters = list(by_quarter)
    payload = {
        "model": "boe-svar",
        "generated": datetime.date.today().isoformat(),
        "data_edge": origin,
        "forecast_start": quarters[0],
        "estimation_sample": res["provenance"]["estimation_sample"],
        "draws": res["draws"],
        "accepted": res["accepted_draws"],
        "ess": res["ess"],
        "paths_per_draw": 5,
        "units": "year-on-year percent",
        "source": (
            "PolicyEngine/boe-var-model via "
            "policyengine_macro.core.svar_forecast"
        ),
        "forecast": by_quarter,
    }
    target = HERE / "current_forecast.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"wrote {target} ({res['accepted_draws']}/{res['draws']} draws accepted, "
        f"ESS {res['ess']}, sample {payload['estimation_sample']})"
    )


if __name__ == "__main__":
    main()
