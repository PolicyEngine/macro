# Data vintage store

Append-only snapshots of the UK official statistics and market data the site depends on.

```
data/
  vintages/ons/<series>/<YYYY-MM-DD>.json   # never edited, never deleted
  vintages/boe/<series>/<YYYY-MM-DD>.json   # never edited, never deleted
  latest/<series>.json                       # flattened newest, read at build time
  MANIFEST.json                              # generated index
  fetch.py
```

## Why vintages rather than "the latest data"

Official statistics get revised, sometimes years later. Reading only the latest
value means the site silently rewrites its own history on every revision: a
forecast that never changed can be made to look better or worse by data it could
not have known about. It also makes look-ahead bias undetectable, because only
one version of the past is ever on disk.

Storing dated snapshots makes both problems visible. The
[forecast track record](../forecasts/README.md) records which vintage each score
was computed against, so any published number can be reproduced.

## Why JSON and not Parquet

These series are small, and a git-diffable format means an upstream revision
arrives as a reviewable diff rather than an opaque binary blob. The
[scheduled fetch](../.github/workflows/fetch-vintages.yml) opens a pull request
instead of pushing, so a revision is something a human sees.

## Why `latest/` exists at all

The published site is static under a CSP with `connect-src 'self'` — the browser
cannot call the ONS. Anything shown on a page has to be baked in at build time,
so `latest/` is the flattened copy the page builders read.

## Series

| name | CDID | source | units |
|------|------|--------|-------|
| `uk_gdp_cvm` | ABMI | ONS QNA | £m, chained volume measure |
| `uk_cpi_yoy` | D7G7 | ONS MM23 | percent, year-on-year |
| `uk_unemployment_rate` | MGSX | ONS LMS | percent |
| `uk_bank_rate` | IUDBEDR | Bank of England IADB | percent |
| `uk_gilt_5y` | IUDSNPY | Bank of England IADB | percent |
| `uk_gilt_10y` | IUDMNPY | Bank of England IADB | percent |
| `uk_gilt_20y` | IUDLNPY | Bank of England IADB | percent |

ONS and Bank of England data are released under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

## Usage

```bash
python3 data/fetch.py                    # all series
python3 data/fetch.py --series uk_cpi_yoy
python3 data/fetch.py --check            # validate the store, fetch nothing
```

A fetch that finds no upstream change writes nothing — otherwise real revisions
would be buried in a stream of identical files. A transient network failure is
reported as a failure, never as "no revision".

## Adding a series

Add an entry to `ONS_SERIES` in `fetch.py` with the ONS topic path, CDID,
frequency and units. Confirm the path by opening
`https://www.ons.gov.uk/<path>/data` in a browser first — the API 404s rather
than redirecting when a series moves between topics.
