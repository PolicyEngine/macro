"""Interval-coverage evaluation for the UK BVAR's predictive bands.

The rolling-origin evaluation (``rolling_evaluation.json``) scores point
forecasts; this script scores the *bands*. At each expanding-window origin it
samples the BVAR posterior, simulates stochastic forecast paths (parameter
and shock uncertainty, the same recipe as the published fan charts), forms
68% and 90% predictive intervals per variable and horizon, and records how
often the realised value fell inside. A calibrated model covers ~68% and
~90%; materially more means the bands are too wide, materially less too
narrow.

Same leakage rules as the rolling evaluation: estimation uses data up to and
including the origin, forecasts start one quarter later, and estimation uses
final revised data — pseudo- rather than real-time out-of-sample. Structural
identification is not used, so the check cannot be tuned to match the
paper's structural results.

Run inside the integration environment (needs the boe_var checkout)::

    integration/.venv/bin/python papers/boe-svar/figures/make_coverage.py

Writes ``coverage_evaluation.json`` next to this script.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from boe_var.bvar import BVAR
from boe_var.data import COLUMNS, load_data
from boe_var import forecast as fc

HERE = Path(__file__).resolve().parent

LAGS = 4
HORIZONS = 8
FIRST_ORIGIN = 80          # matches rolling_evaluation.json
N_DRAWS = 100              # posterior draws per origin
N_PATHS = 5                # stochastic paths per draw
SEED = 20260729


def main() -> None:
    df = load_data()
    y = df.to_numpy(float)
    T, k = y.shape
    last_origin = T - HORIZONS - 1
    origins = list(range(FIRST_ORIGIN, last_origin + 1))
    rng = np.random.default_rng(SEED)

    # hits[level][h][var] counts outturns inside the level band
    hits = {lv: np.zeros((HORIZONS, k)) for lv in (68, 90)}
    n = np.zeros(HORIZONS)

    for origin in origins:
        train = y[: origin + 1]
        model = BVAR(train, lags=LAGS)
        draws = model.sample_posterior(N_DRAWS, seed=SEED + origin)
        paths = np.empty((N_DRAWS * N_PATHS, HORIZONS, k))
        i = 0
        for draw in draws:
            for _ in range(N_PATHS):
                paths[i] = fc.sample_forecast(
                    draw, train, horizons=HORIZONS, rng=rng
                )
                i += 1
        actual = y[origin + 1 : origin + HORIZONS + 1]
        for lv, (a, b) in {68: (16.0, 84.0), 90: (5.0, 95.0)}.items():
            lo = np.percentile(paths, a, axis=0)
            hi = np.percentile(paths, b, axis=0)
            hits[lv] += (lo <= actual) & (actual <= hi)
        n += 1

    report = {
        "method": (
            "expanding-window pseudo-out-of-sample interval coverage; "
            "reduced-form BVAR predictive bands with parameter and shock "
            "uncertainty (posterior draws x stochastic paths), percentile "
            "intervals on the LEVEL of each series"
        ),
        "lags": LAGS,
        "horizons": HORIZONS,
        "origins": len(origins),
        "first_origin": FIRST_ORIGIN,
        "draws_per_origin": N_DRAWS,
        "paths_per_draw": N_PATHS,
        "seed": SEED,
        "sample": {"start": str(df.index[0]), "end": str(df.index[-1])},
        "limitations": [
            "Estimation uses final revised data (pseudo-, not real-time).",
            "Coverage is on series levels in transformed model units.",
            "Consecutive-origin outcomes overlap, so the effective number of "
            "independent observations is well below the origin count.",
            "No Covid dummies in the evaluation model, matching "
            "rolling_evaluation.json.",
        ],
        "coverage": {
            str(lv): {
                f"h{h + 1}": {
                    var: round(float(hits[lv][h, j] / n[h]), 4)
                    for j, var in enumerate(COLUMNS)
                }
                for h in range(HORIZONS)
            }
            for lv in (68, 90)
        },
    }
    target = HERE / "coverage_evaluation.json"
    target.write_text(json.dumps(report, indent=1) + "\n")
    lv68 = np.mean([hits[68][h].sum() / (n[h] * k) for h in range(HORIZONS)])
    lv90 = np.mean([hits[90][h].sum() / (n[h] * k) for h in range(HORIZONS)])
    print(
        f"wrote {target} — mean coverage across variables/horizons: "
        f"68% band {lv68:.1%}, 90% band {lv90:.1%} ({len(origins)} origins)"
    )


if __name__ == "__main__":
    main()
