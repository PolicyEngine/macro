# validation/figures

Generating script for the eleven inline SVG charts on `/validation/`, in the same
spirit as the papers' `papers/*/figures/*.py` scripts.

## Regenerate

```sh
python3 validation/figures/make_charts.py
```

This rewrites the eleven `<svg class="vchart">` blocks in `validation/index.html`
in place. Stdlib only — no dependencies. To assert in CI that the page has not
drifted from its sources:

```sh
python3 validation/figures/make_charts.py --check   # exits 1 if stale
```

## Why hand-emitted SVG rather than matplotlib

The rest of the project renders figures with matplotlib, but these charts have two
constraints the papers' figures do not:

1. **They must stay inline in the HTML.** The site ships no third-party JS and no
   external assets; a `.svg` or `.png` file next to the page would be a new
   external request.
2. **They must retheme for light/dark.** Every fill and stroke is a `vc-*` class
   defined in `style.css`, which resolves the site's CSS custom properties. A
   matplotlib export bakes in literal colour values and would need to be
   post-processed to strip them on every regeneration.

Emitting the markup directly satisfies both and keeps the script small enough to
audit line by line, which is the point of the page.

## Where the numbers come from

| Chart (`data-chart`) | Plots | Source |
| --- | --- | --- |
| `obr-anchored` | Quarterly % deviation of the anchored emulator from the March-2026 EFO, 2025Q1–2027Q4, for real GDP and consumption | Computed from `papers/obr-macro/figures/fig_anchored_data.csv` (`*_model` vs `*_efo` levels) |
| `obr-reform` | 1pp basic-rate rise: PolicyEngine static costing vs HMRC ready reckoner, 2026–27 and 2028–29 | `chart_data.json` → `papers/obr-macro/sections/comparison.tex`, table `tab:comparison` panel B |
| `obr-computed-share` | Two stacked bars separating scorecard variables the model actually computes from passthroughs held at the OBR published value | `chart_data.json` (`obr_computed_share`) |
| `obr-freerun` | Free-running vs anchored emulator real GDP levels against the EFO path | `papers/obr-macro/figures/fig_free_running_data.csv` and `fig_anchored_data.csv` |
| `obr-outturn` | Grouped bars: quarter-on-quarter real GDP growth from the emulator, the EFO, and the ONS outturn | `papers/obr-macro/figures/fig_outturn_data.csv` |
| `svar-fevd` | Global-shock FEVD shares at the 1-year horizon, ours vs the paper, for UK GDP and CPI | `papers/boe-svar/figures/comparison_numbers.json` |
| `svar-fan` | Median and 68% forecast fans from the frozen 2024Q2 edge for UK GDP and CPI, with ONS outturns overlaid | `papers/boe-svar/figures/figure_numbers.json` |
| `frbus-residuals` | Max absolute residuals against the Fed's `pyfrbus`, log scale | `chart_data.json` → `papers/frb-us/sections/validation.tex`, tables `tab:tracking` and `tab:refnoise` |
| `hank-targets` | Hosted two-asset steady state against the ABRS (2021) published calibration targets | `papers/us-hank/figures/replication.json` |
| `svar-skill-all` | Rolling-origin RMSE ratios vs the benchmark for every variable–horizon pair, with significance | `papers/boe-svar/figures/rolling_evaluation.json` |
| `svar-winrate` | Per-horizon counts of variables where the SVAR beats the benchmark, split by significance | `papers/boe-svar/figures/rolling_evaluation.json` |

Most charts read committed machine-readable data directly. The others plot
numbers that exist in the project only as LaTeX table cells; those are
transcribed into `chart_data.json` with a per-value source pointer. **Do not edit
a value in `chart_data.json` without changing the cited source** — the file is a
transcription, not an input.

Deriving `obr-anchored`'s deviations from the CSV rather than transcribing them
also gives a free cross-check: the computed values reproduce the four selected
quarters in the paper's comparison table (+0.05%, −0.16%, +0.19%, +0.32% on GDP)
and the MAPEs quoted in the page prose (0.18% GDP, 0.29% consumption).

## Accessibility

Each chart carries `role="img"` and `aria-labelledby` pointing at a `<title>`
(short name) and a `<desc>` (the plotted values in prose, generated from the same
data as the marks, so it cannot drift). Inline SVG is otherwise invisible to
assistive tech.
