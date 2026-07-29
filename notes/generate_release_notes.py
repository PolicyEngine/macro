#!/usr/bin/env python3
"""Generate reviewable factual notes for new official-data vintages."""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES_INDEX = ROOT / "notes" / "index.html"
SITEMAP = ROOT / "sitemap.xml"
GENERATED_ROOT = ROOT / "notes" / "releases"


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
    observations = series["observations"]
    if len(observations) < 2:
        return "No prior observation is stored for comparison."
    now, prior = observations[-1], observations[-2]
    change = now["value"] - prior["value"]
    units = series["units"].lower()
    if "percent" in units:
        value = f"{change:+.1f} percentage points"
    elif units.startswith("£m"):
        value = f"£{abs(change) / 1000:,.1f}bn {'higher' if change > 0 else 'lower'}"
    else:
        value = f"{change:+,.1f}"
    return f"That is {value} compared with {prior['period']}."


def note_page(series: dict, vintage: str) -> str:
    now = series["observations"][-1]
    title = f"{series['title']}: {now['period']}"
    value = display_value(series, now["value"])
    source = series["source"]
    cdid = series["cdid"]
    next_release = " ".join((series.get("next_release") or "not supplied").split())
    canonical = f"https://policyengine-macro.vercel.app/notes/releases/{vintage}-{series['series']}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>PolicyEngine Macro — {html.escape(title)}</title>
<meta name="description" content="Factual release note for {html.escape(series['title'])}, observation {now['period']}, from the committed {vintage} vintage." />
<link rel="canonical" href="{canonical}" />
<link rel="icon" type="image/svg+xml" href="/assets/policyengine-mark.svg" />
<link rel="stylesheet" href="/vendor/fonts/fonts.css" />
<link rel="stylesheet" href="/vendor/ui-kit-tokens.css" />
<link rel="stylesheet" href="/style.css" />
</head>
<body class="doc">
<a class="skip-link" href="#top">Skip to main content</a>
<div class="grain" aria-hidden="true"></div>
<header class="nav">
  <a class="brand" href="/">
    <img class="brand-logo" src="/assets/policyengine-mark.svg" alt="" width="20" height="20" />PolicyEngine Macro
  </a>
  <nav class="nav-links" aria-label="Primary">
    <a href="/">Home</a>
    <a class="nav-mobile" href="/economy">Economy</a>
    <a href="/models">Models</a>
    <a href="/forecasts">Forecasts</a>
    <a href="/validation">Evidence</a>
    <a class="nav-mobile nav-start" href="/connect">Use</a>
    <a href="/contact">Contact</a>
    <a class="nav-gh" href="https://github.com/PolicyEngine/macro" aria-label="GitHub"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 19c-4.3 1.4 -4.3 -2.5 -6 -3m12 5v-3.5c0 -1 .1 -1.4 -.5 -2c2.8 -.3 5.5 -1.4 5.5 -6a4.6 4.6 0 0 0 -1.3 -3.2a4.2 4.2 0 0 0 -.1 -3.2s-1.1 -.3 -3.5 1.3a12.3 12.3 0 0 0 -6.2 0c-2.4 -1.6 -3.5 -1.3 -3.5 -1.3a4.2 4.2 0 0 0 -.1 3.2c-.9 .9 -1.3 2 -1.3 3.2c0 4.6 2.7 5.7 5.5 6c-.6 .6 -.6 1.2 -.5 2v3.5"/></svg></a>
  </nav>
</header>
<main id="top">
  <section class="hero model-hero">
    <div class="hero-inner">
      <p class="eyebrow">{vintage} · automated factual release note</p>
      <h1 class="page-title">{html.escape(series['title'])}</h1>
      <p class="lede">{html.escape(now['period'])}: <strong>{html.escape(value)}</strong>.</p>
    </div>
  </section>
  <section class="band">
    <div class="band-head"><span class="kicker mono">01 — what changed</span><h2>The newest stored observation.</h2></div>
    <div class="prose">
      <p>{html.escape(delta(series))}</p>
      <p>This page is generated from committed data and contains no editorial or causal interpretation.</p>
    </div>
  </section>
  <section class="band band-alt">
    <div class="band-head"><span class="kicker mono">02 — provenance</span><h2>The release as it entered the record.</h2></div>
    <div class="prose">
      <dl>
        <dt>Observation</dt><dd>{html.escape(now['period'])}</dd>
        <dt>Stored vintage</dt><dd>{vintage}</dd>
        <dt>Publisher</dt><dd>{html.escape(source)}</dd>
        <dt>Series</dt><dd>{html.escape(cdid)}</dd>
        <dt>Next release</dt><dd>{html.escape(next_release)}</dd>
      </dl>
      <p><a href="{html.escape(series['url'])}">Open the publisher series →</a></p>
      <p><a href="https://github.com/PolicyEngine/macro/blob/main/{series['_path']}">Open the immutable snapshot →</a></p>
    </div>
  </section>
  <section class="band">
    <div class="band-head"><span class="kicker mono">03 — model context</span><h2>Outturn first; interpretation separately.</h2></div>
    <div class="prose">
      <p>The <a href="/economy">Economy page</a> places this observation beside the other current indicators. If it completes an archived forecast period, the <a href="/forecasts">forecast record</a> is scored by the separate outturn pipeline.</p>
      <p>A dated research note may add model interpretation after human review. This factual page does not pretend the observation establishes a cause or policy conclusion.</p>
    </div>
  </section>
</main>
<footer class="foot foot-bar"><p class="footer-legal">© 2026 PolicyEngine. All rights reserved.</p></footer>
<script src="/reveal.js" defer></script>
</body>
</html>
"""


def generated_pages() -> list[Path]:
    return sorted(GENERATED_ROOT.glob("*/index.html")) if GENERATED_ROOT.exists() else []


def rebuild_indexes() -> None:
    index_rows = []
    sitemap_rows = []
    for page in reversed(generated_pages()):
        slug = page.parent.name
        date, series = slug[:10], slug[11:]
        title_match = re.search(r"<h1 class=\"page-title\">(.*?)</h1>", page.read_text())
        title = title_match.group(1) if title_match else series
        index_rows.append(
            f'        <a href="/notes/releases/{slug}/"><span>{title}</span>'
            f"<strong>{date} · automatic release note</strong></a>"
        )
        sitemap_rows.append(
            f"  <url><loc>https://policyengine-macro.vercel.app/notes/releases/{slug}</loc>"
            "<priority>0.6</priority></url>"
        )
    marker_replace(NOTES_INDEX, "generated-release-notes", "\n".join(index_rows))
    marker_replace(SITEMAP, "generated-release-notes", "\n".join(sitemap_rows))


def check() -> int:
    failures = []
    index = NOTES_INDEX.read_text()
    sitemap = SITEMAP.read_text()
    for page in generated_pages():
        slug = page.parent.name
        if f"/notes/releases/{slug}/" not in index:
            failures.append(f"{slug}: missing from notes index")
        if f"/notes/releases/{slug}</loc>" not in sitemap:
            failures.append(f"{slug}: missing from sitemap")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"OK — {len(generated_pages())} generated release note(s) indexed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--vintage",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check()

    written = 0
    for series in snapshots(args.vintage):
        destination = GENERATED_ROOT / f"{args.vintage}-{series['series']}" / "index.html"
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True)
        destination.write_text(note_page(series, args.vintage))
        written += 1
    rebuild_indexes()
    print(f"generated {written} release note(s) for {args.vintage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
