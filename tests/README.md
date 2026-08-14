# Repository test suite

Structural checks over the published site, the data vintage store, and the
repository's own provenance files. Stdlib-only apart from pytest, matching the
dependency-free rule the site scripts follow — CI needs nothing else installed.

```bash
python3 -m pytest tests -q          # whole suite, ~1 second
python3 -m pytest tests -q -k links # one area
```

Failures are parametrised per file, so the test id names the offending page or
vintage, and each message names the file and line at fault.

## What each file covers

### `test_site_integrity.py`

Everything about the 78 public HTML pages that can break without anyone
noticing. Resolution follows `vercel.json`: `cleanUrls`, `trailingSlash: false`,
and the `redirects` table (a link to a redirect *source* is fine — the
destination is what must exist).

- **Links** — every `href`/`src` that points into the repo resolves to a file
  Vercel could serve. All broken links are reported in one message.
- **Redirects** — every `vercel.json` destination resolves, including its
  in-page anchor, and no page links to a redirect *source*: an inbound link
  from outside the site may take the 308, one page of this site linking to
  another may not.
- **Head metadata** — doctype, `<html lang="en">`, charset, viewport, a
  non-empty `<title>`, a `<meta name="description">`, and exactly one
  `rel="canonical"` whose URL matches where the file is actually served.
- **Accessibility** — images have alt text (or are explicitly decorative), one
  `<h1>` per page, no skipped heading levels, every `aria-controls` /
  `aria-labelledby` / `href="#…"` target id exists, every `<a>` has a
  discernible name.
- **Sitemap** — every `<loc>` resolves and is not a redirect source; every
  public page appears. Deliberate omissions go in `SITEMAP_EXCLUSIONS` at the
  top of the file, with the reason.
- **Domain** — internal links use paths, not the current Vercel hostname.

The canonical origin is read from the first `<loc>` in `sitemap.xml` rather than
hardcoded, so moving the site to a new domain is a one-line edit.

This complements `site_contract.py` and `site_nav.py` rather than replacing
them: those assert on prose and navigation markup, these assert only on
structure, so a copy rewrite cannot fail them and a broken link cannot pass.

### `test_data_store.py`

Integrity of the append-only vintage store under `data/`.

- Every `data/vintages/**/*.json` is valid JSON with the required keys, a
  `vintage` matching its filename, and an ISO-8601 `fetched_utc`.
- Observations are non-empty, chronologically ordered, free of duplicates,
  numeric, and use the period grammar their declared frequency implies
  (`2026Q2`, `2026-06`, `2026-08-10`); `first_period` / `last_period` match the
  actual endpoints, and nothing runs past `last_period`.
- **`data/latest/<series>.json` is content-identical to the newest vintage.**
  This is the one that catches the site publishing superseded numbers.
- `data/MANIFEST.json` lists exactly the series on disk, and each entry agrees
  with the vintage it summarises.
- No snapshot was fetched before the release it captured, and every `url` is
  https on the domain of the source it names.

Overlaps `python3 data/fetch.py --check` on purpose, and goes further:
`--check` never looks at `latest/`, at period formats, or at source URLs.

### `test_repo_hygiene.py`

The provenance files that live outside the website.

- `CITATION.cff` parses and its `version` matches the package version.
- `CHANGELOG.md`'s topmost version heading matches the package version.
- The `[models]` extra pins every git dependency to a full 40-character commit
  SHA — never a branch or tag. The reproducibility claim on `/models` depends
  on this.
- No `README.md` link points at a repo path that does not exist.

### `conftest.py`

Shared machinery: a tolerant `html.parser` tree (so an `<h4>` inside a
JavaScript string is not mistaken for a heading), a `Site` object that resolves
URLs the way Vercel does, and the `pytest_generate_tests` hook that
parametrises per HTML page, per vintage file, and per series.

## Running in CI

Nothing to install beyond pytest, and no network access is used. The natural
home is a step alongside the existing gates in
`.github/workflows/site-provenance.yml`:

```yaml
- run: pip install pytest
- run: python3 -m pytest tests -q
```
