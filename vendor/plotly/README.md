# plotly.js basic build (vendored)

- **File:** `plotly-basic-2.35.2.min.js` (1,071,091 bytes)
- **Package:** `plotly.js-basic-dist-min` **2.35.2**, unmodified
- **Source URL:** https://cdn.jsdelivr.net/npm/plotly.js-basic-dist-min@2.35.2/plotly-basic.min.js
- **sha256:** `138c2e81014b979dc00867a93da55b7605a17495ee78dd7afb433b7f021dfcfa`
- **Licence:** MIT (Plotly, Inc.)
- **Fetched:** 2026-11-17

The basic build has the scatter, bar and pie traces only (SVG, no WebGL), which is all
the site's charts use, and it runs under the site's CSP (no `unsafe-eval`).

Loaded only on pages with an interactive chart, by `economy/pe-plot.js`. The figures
themselves are plain Plotly JSON written by `chartkit.plot_spec()` with the standard
library, so no generator depends on the plotly Python package. Each chart's SVG stays
in the page as the no-JS, print and screen-reader version.

To upgrade, replace the file with the same package at a new pinned version, update
the version in `chartkit.PLOTLY_JS` and this README, and record the new sha256.
