#!/usr/bin/env python3
"""Generate reviewable factual notes for new official-data vintages."""

from __future__ import annotations

import argparse
import importlib.util
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES_INDEX = ROOT / "forecasts" / "index.html"
RELEASES_INDEX = ROOT / "notes" / "releases" / "index.html"
SITEMAP = ROOT / "sitemap.xml"
GENERATED_ROOT = ROOT / "notes" / "releases"

import sys

sys.path.insert(0, str(ROOT))
import site_nav  # noqa: E402  (canonical header/crumbs/footer renderer)


def marker_replace(path: Path, name: str, body: str) -> None:
    start, end = f"<!-- {name}:begin -->", f"<!-- {name}:end -->"
    text = path.read_text()
    updated, count = re.subn(
        re.escape(start) + ".*?" + re.escape(end),
        lambda _: f"{start}\n{body}\n{end}",
        text,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError(f"{path}: expected one {name} block, found {count}")
    path.write_text(updated)


def snapshots(vintage: str) -> list[dict]:
    found = []
    for path in sorted((ROOT / "data" / "vintages").glob(f"*/*/{vintage}.json")):
        payload = json.loads(path.read_text())
        payload["_path"] = path.relative_to(ROOT).as_posix()
        found.append(payload)
    return found


def display_value(series: dict, value: float) -> str:
    units = series["units"].lower()
    if "percent" in units:
        return f"{value:,.1f}%"
    if units.startswith("£m"):
        return f"£{value / 1000:,.1f}bn"
    if "£ per week" in units:
        return f"£{value:,.0f} per week"
    if "thousands" in units:
        return f"{value:,.0f} thousand"
    return f"{value:,.1f}"


def delta(series: dict) -> str:
    """The change on the prior stored observation, short enough for a stat tile."""
    observations = series["observations"]
    if len(observations) < 2:
        return "no prior observation stored"
    now, prior = observations[-1], observations[-2]
    change = now["value"] - prior["value"]
    units = series["units"].lower()
    if "percent" in units:
        value = f"{change:+.1f}pp"
    elif units.startswith("£m"):
        value = f"£{abs(change) / 1000:,.1f}bn {'higher' if change > 0 else 'lower'}"
    else:
        value = f"{change:+,.1f}"
    if value.startswith("-"):
        value = "\u2212" + value[1:]
    return f"{value} on {prior['period']}"


def _topics():
    """economy/topics.py, for its series-to-topic table (the topic home of a series)."""
    spec = importlib.util.spec_from_file_location(
        "economy_topics", ROOT / "economy" / "topics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TOPIC_CACHE: dict[str, tuple[str, str]] | None = None


def topic_home(series: dict) -> tuple[str, str]:
    """(url, title) of the topic page that reads this series, else the data hub."""
    global _TOPIC_CACHE
    if _TOPIC_CACHE is None:
        topics = _topics()
        _TOPIC_CACHE = {
            name: (topics.topic_url(topic), topic["title"])
            for topic in topics.TOPICS
            for name in topic["series"]
        }
    if series["series"] in _TOPIC_CACHE:
        return _TOPIC_CACHE[series["series"]]
    if series["series"].startswith("us_"):
        return "/economy/us", "US data"
    return "/economy", "UK data"


def note_page(series: dict, vintage: str) -> str:
    """One factual release note (DESIGN.md §7.7). No interpretation, ever.

    The observation is stated once, in the stat tile: the title band names the
    series and the release, and every other card links to where the series is
    read (its topic page), stored (the data store) and scored (the record).
    """
    now = series["observations"][-1]
    title = f"{series['title']}: {now['period']}"
    value = display_value(series, now["value"])
    source = series["source"]
    cdid = series["cdid"]
    next_release = " ".join((series.get("next_release") or "not supplied").split())
    canonical = f"https://policyengine-macro.vercel.app/notes/releases/{vintage}-{series['series']}"
    topic_url, topic_title = topic_home(series)
    where = site_nav.where_next([
        (topic_url, "topic", html.escape(topic_title), "Where this series stands, and the model that reads it"),
        ("/forecasts#data", "data", "The data store", "Every stored vintage of every series"),
        ("/forecasts#rounds", "chart", "The forecast record", "Rounds scored against outturns like this one"),
    ])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{html.escape(title)} — PolicyEngine Macro</title>
<meta name="description" content="Factual release note for {html.escape(series['title'])}, observation {now['period']}, from the committed {vintage} vintage." />
<link rel="canonical" href="{canonical}" />
<link rel="icon" type="image/svg+xml" href="/assets/policyengine-mark.svg" />
<link rel="stylesheet" href="/vendor/fonts/fonts.css" />
<link rel="stylesheet" href="/vendor/ui-kit-tokens.css" />
<link rel="stylesheet" href="{site_nav.STYLE_HREF}" />
</head>
<body class="doc">
<a class="skip-link" href="#top">Skip to main content</a>
<header class="nav">
</header>
<main id="top">
  <section class="hero model-hero">
    <div class="hero-inner">
      <p class="eyebrow">{vintage} · automated factual release note</p>
      <h1 class="page-title">{html.escape(series['title'])}</h1>
      <p class="lede">The {html.escape(now['period'])} observation, as {html.escape(source)} published it and as it entered the record.</p>
    </div>
  </section>
  <section class="band" id="changed">
    <div class="band-head"><span class="kicker mono">what changed</span><h2>The newest stored observation</h2></div>
    <div class="stat-row">
      <div class="stat stat-neutral">
        <span class="stat-label">{html.escape(series['title'])}, {html.escape(now['period'])}</span>
        <span class="stat-value">{html.escape(value)}</span>
        <span class="stat-sub">{html.escape(delta(series))}</span>
        <span class="stat-foot"><a class="chip" href="{topic_url}#stands">{html.escape(topic_title)}</a></span>
      </div>
    </div>
    <p class="section-intro">Generated from committed data; no editorial or causal interpretation.</p>
  </section>
  <section class="band" id="provenance">
    <div class="band-head"><span class="kicker mono">provenance</span><h2>The release as it entered the record</h2></div>
    <div class="note-provenance">
    <dl>
      <dt>Observation</dt><dd>{html.escape(now['period'])}</dd>
      <dt>Stored vintage</dt><dd>{vintage}</dd>
      <dt>Publisher</dt><dd>{html.escape(source)}</dd>
      <dt>Series</dt><dd>{html.escape(cdid)}</dd>
      <dt>Next release</dt><dd>{html.escape(next_release)}</dd>
    </dl>
    </div>
    <div class="chip-row">
      <a class="chip" href="{html.escape(series['url'])}">Publisher series</a>
      <a class="chip" href="https://github.com/PolicyEngine/macro/blob/main/{series['_path']}">Immutable snapshot</a>
    </div>
  </section>
{where}
</main>
<footer class="foot foot-bar">
  <p class="footer-legal">© 2026 PolicyEngine. All rights reserved.</p>
  <nav class="footer-links" aria-label="PolicyEngine links">
  </nav>
</footer>
<script src="/reveal.js?v=2" defer></script>
</body>
</html>
"""


def note_target(page: Path) -> tuple[dict, str] | None:
    """The snapshot a committed note was generated from, by its slug."""
    slug = page.parent.name
    vintage, name = slug[:10], slug[11:]
    for series in snapshots(vintage):
        if series["series"] == name:
            return series, vintage
    return None


def render_note(destination: Path, series: dict, vintage: str) -> str:
    """The page as committed: template, then the canonical shell from site_nav."""
    previous = destination.read_text() if destination.exists() else None
    destination.write_text(note_page(series, vintage))
    try:
        return site_nav.render(destination)
    finally:
        if previous is not None:
            destination.write_text(previous)


def generated_pages() -> list[Path]:
    return sorted(GENERATED_ROOT.glob("*/index.html")) if GENERATED_ROOT.exists() else []


def rebuild_indexes() -> None:
    index_rows = []
    sitemap_rows = []
    latest = ""
    for page in reversed(generated_pages()):
        slug = page.parent.name
        date, series = slug[:10], slug[11:]
        latest = max(latest, date)
        title_match = re.search(r"<h1 class=\"page-title\">(.*?)</h1>", page.read_text())
        title = title_match.group(1) if title_match else series
        index_rows.append(
            f'        <a href="/notes/releases/{slug}"><span>{title}</span>'
            f"<strong>{date} · automatic release note</strong></a>"
        )
        sitemap_rows.append(
            f"  <url><loc>https://policyengine-macro.vercel.app/notes/releases/{slug}</loc>"
            "<priority>0.6</priority></url>"
        )
    # The full per-note list lives on /notes/releases; the notes section on
    # /forecasts#notes carries a single collapsed row pointing at it.
    count = len(index_rows)
    summary_row = (
        f'        <a href="/notes/releases"><span>{count} automatic release '
        f"notes · {latest} →</span><strong>{latest} · automatic release "
        "notes</strong></a>"
    )
    marker_replace(NOTES_INDEX, "generated-release-notes", summary_row)
    marker_replace(RELEASES_INDEX, "generated-release-notes", "\n".join(index_rows))
    marker_replace(SITEMAP, "generated-release-notes", "\n".join(sitemap_rows))


def check() -> int:
    failures = []
    releases_index = RELEASES_INDEX.read_text()
    sitemap = SITEMAP.read_text()
    if 'href="/notes/releases"' not in NOTES_INDEX.read_text():
        failures.append(
            "forecasts index: missing collapsed link to /notes/releases"
        )
    if "/notes/releases</loc>" not in sitemap:
        failures.append("sitemap: missing /notes/releases entry")
    for page in generated_pages():
        slug = page.parent.name
        if f"/notes/releases/{slug}" not in releases_index:
            failures.append(f"{slug}: missing from releases index")
        if f"/notes/releases/{slug}</loc>" not in sitemap:
            failures.append(f"{slug}: missing from sitemap")
    for page in generated_pages():
        target = note_target(page)
        if target is None:
            failures.append(f"{page.parent.name}: no committed snapshot to rebuild it from")
        elif render_note(page, *target) != page.read_text():
            failures.append(f"{page.parent.name}: stale; run notes/generate_release_notes.py --rebuild")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"OK — {len(generated_pages())} generated release note(s) indexed and current")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--vintage",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--rebuild", action="store_true",
        help="rewrite every committed note from its snapshot (after a template change)",
    )
    args = parser.parse_args()
    if args.check:
        return check()
    if args.rebuild:
        rebuilt = 0
        for page in generated_pages():
            target = note_target(page)
            if target is None:
                raise SystemExit(f"{page.parent.name}: no committed snapshot to rebuild it from")
            fresh = render_note(page, *target)
            if fresh != page.read_text():
                page.write_text(fresh)
                rebuilt += 1
        rebuild_indexes()
        print(f"rebuilt {rebuilt} release note(s)")
        return 0

    written = 0
    for series in snapshots(args.vintage):
        destination = GENERATED_ROOT / f"{args.vintage}-{series['series']}" / "index.html"
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True)
        # Stamp the canonical header, crumbs, and footer so a fresh page
        # matches `python3 site_nav.py` exactly.
        destination.write_text(render_note(destination, series, args.vintage))
        written += 1
    rebuild_indexes()
    print(f"generated {written} release note(s) for {args.vintage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
