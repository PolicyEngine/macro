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


def _decimals(value: float) -> int:
    text = repr(float(value))
    return 0 if "e" in text else len(text.split(".")[1].rstrip("0"))


def display_value(series: dict, value: float) -> str:
    """The value at the precision the publisher stored it (never rounded up
    to look tidier: Bank Rate 3.75 must not print as 3.8). Percent series are
    capped at two decimals, which is how a gilt yield is quoted."""
    units = series["units"].lower()
    if "percent" in units:
        places = max(1, min(2, _decimals(value)))
        return f"{value:,.{places}f}%"
    if units.startswith("£m"):
        text = f"£{abs(value) / 1000:,.1f}bn"
        return ("\u2212" + text) if value < 0 else text
    if "£ per week" in units:
        return f"£{value:,.0f} per week"
    if "thousands" in units:
        return f"{value:,.0f} thousand"
    return f"{value:,.1f}"


def delta(series: dict) -> str:
    """The change on the prior stored observation, short enough for a cell."""
    observations = series["observations"]
    if len(observations) < 2:
        return "no prior observation stored"
    now, prior = observations[-1], observations[-2]
    change = now["value"] - prior["value"]
    units = series["units"].lower()
    if "percent" in units:
        places = max(1, min(2, max(_decimals(now["value"]), _decimals(prior["value"]))))
        value = f"{change:+.{places}f}pp"
        if float(value[:-2]) == 0:
            value = "unchanged"
    elif units.startswith("£m"):
        value = f"£{abs(change) / 1000:,.1f}bn {'higher' if change > 0 else 'lower'}"
    elif "£ per week" in units:
        value = f"£{abs(change):,.0f} per week {'higher' if change > 0 else 'lower'}"
    elif "thousands" in units:
        value = f"{change:+,.0f} thousand"
    else:
        value = f"{change:+,.1f}"
    if value.startswith("-"):
        value = "\u2212" + value[1:]
    return f"{value} on {prior['period']}"


def prior_snapshot(series: dict, vintage: str) -> dict | None:
    """The same series' newest committed snapshot before this one."""
    folder = (ROOT / series["_path"]).parent
    earlier = sorted(p for p in folder.glob("*.json") if p.stem < vintage)
    return json.loads(earlier[-1].read_text()) if earlier else None


def what_is_new(series: dict, vintage: str) -> str:
    """What the snapshot added, by comparison with the previous one.

    Factual and mechanical: a later last period is a new observation; the same
    last period with any changed value is a revision; otherwise the publisher
    changed only metadata (or nothing the store keeps).
    """
    prior = prior_snapshot(series, vintage)
    if prior is None:
        return "first snapshot"
    before = {o["period"]: o["value"] for o in prior["observations"]}
    now = {o["period"]: o["value"] for o in series["observations"]}
    added = sorted(set(now) - set(before))
    revised = sorted(p for p in set(now) & set(before) if now[p] != before[p])
    parts = []
    if added:
        parts.append(f"{len(added)} new observation{'' if len(added) == 1 else 's'}")
    if revised:
        parts.append(f"{len(revised)} revised")
    return ", ".join(parts) or "no value changed"


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


def _label(series: dict) -> str:
    spec = importlib.util.spec_from_file_location(
        "data_build_page", ROOT / "data" / "build_page.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PUBLIC_LABELS.get(series["cdid"], series["title"])


def digest_rows(items: list[dict], vintage: str) -> list[str]:
    rows = []
    for series in items:
        now = series["observations"][-1]
        topic_url, topic_title = topic_home(series)
        next_release = " ".join((series.get("next_release") or "not announced").split())
        rows.append(
            f'          <tr id="{series["series"]}">'
            f'<th scope="row">{html.escape(_label(series))}'
            f'<br><a class="mono" href="{topic_url}#stands">{html.escape(topic_title)}</a></th>'
            f'<td class="mono">{html.escape(now["period"])}</td>'
            f'<td class="num">{html.escape(display_value(series, now["value"]))}</td>'
            f'<td class="num">{html.escape(delta(series))}</td>'
            f'<td class="kind">{html.escape(what_is_new(series, vintage))}</td>'
            f"<td>{html.escape(next_release)}</td>"
            f'<td><a href="https://github.com/PolicyEngine/macro/blob/main/{series["_path"]}">Snapshot</a>'
            f' · <a href="{html.escape(series["url"])}">{html.escape(series["source"])} · {html.escape(series["cdid"])}</a></td>'
            "</tr>"
        )
    return rows


def digest_page(vintage: str) -> str:
    """One factual digest per stored vintage date (DESIGN.md §7.7). No
    interpretation, ever.

    Replaces the one-page-per-series notes: a daily gilt fetch produced four
    near-identical pages a day, and a reader looking for what the ONS
    published on a date had to open each. Each observation is still stated
    once, in its row; the row's id is the old page's series slug, so
    /notes/releases/<date>-<series> redirects to /notes/releases/<date>#<series>.
    """
    items = sorted(snapshots(vintage), key=lambda s: (s["series"][:3] != "uk_", _label(s)))
    day = datetime.strptime(vintage, "%Y-%m-%d").strftime("%-d %B %Y")
    canonical = f"https://policyengine-macro.vercel.app/notes/releases/{vintage}"
    new = sum(1 for s in items if "new observation" in what_is_new(s, vintage))
    uk = [s for s in items if s["series"].startswith("uk_")]
    us = [s for s in items if not s["series"].startswith("uk_")]
    head = (
        '          <thead><tr><th scope="col">Series</th><th scope="col">Latest period</th>'
        '<th scope="col">Value</th><th scope="col">Change</th><th scope="col">What is new</th>'
        '<th scope="col">Next release</th><th scope="col">Files</th></tr></thead>'
    )
    tables = []
    for title, group, ident in (("UK", uk, "uk"), ("US", us, "us")):
        if not group:
            continue
        tables.append(f"""    <h3 id="{ident}-series">{title} series</h3>
    <div class="table-scroll">
        <table class="digest-table" data-stack="yes">
          <caption>{title} series with a new snapshot on {vintage}. Change is on the prior stored observation; values as the publisher stored them.</caption>
{head}
          <tbody>
{chr(10).join(digest_rows(group, vintage))}
          </tbody>
        </table>
    </div>""")
    where = site_nav.where_next([
        ("/notes/releases", "list", "All release digests", "Every stored date, newest first"),
        ("/forecasts#data", "data", "The data store", "Every stored vintage of every series"),
        ("/forecasts#scored", "chart", "The forecast record", "Rounds scored against outturns like these"),
    ])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Data stored {day} — PolicyEngine Macro</title>
<meta name="description" content="Factual digest of the {len(items)} official data series with a new committed snapshot on {vintage}: latest value, change, and whether it is a new observation or a revision." />
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
      <p class="eyebrow">{vintage} · automated factual digest · {len(items)} series</p>
      <h1 class="page-title">Official data stored on {day}</h1>
      <p class="lede">Every series whose snapshot changed on this date, as the publisher released it, with no interpretation.</p>
    </div>
  </section>
  <section class="band" id="changed">
    <div class="band-head"><span class="kicker mono">what changed</span><h2>{new} of {len(items)} series added an observation</h2>
    <p class="section-intro">Generated from committed snapshots; no editorial or causal interpretation.</p></div>
    <div class="prose">
{chr(10).join(tables)}
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


LEGACY = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9_]+$")


def digest_dates() -> list[str]:
    """Dates with a digest, plus dates still held by legacy per-series notes."""
    found = set()
    for page in generated_pages():
        slug = page.parent.name
        m = LEGACY.match(slug)
        found.add(m.group(1) if m else slug)
    return sorted(found)


def render_digest(destination: Path, vintage: str) -> str:
    """Pure: template plus the canonical shell, without touching the file."""
    return site_nav.render(destination, digest_page(vintage))


def generated_pages() -> list[Path]:
    return sorted(GENERATED_ROOT.glob("*/index.html")) if GENERATED_ROOT.exists() else []


def digest_pages() -> list[Path]:
    return [p for p in generated_pages() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.parent.name)]


def rebuild_indexes() -> None:
    index_rows = []
    sitemap_rows = []
    pages = list(reversed(digest_pages()))
    for page in pages:
        vintage = page.parent.name
        items = snapshots(vintage)
        kinds = [what_is_new(s, vintage) for s in items]
        new = sum(1 for k in kinds if "new observation" in k)
        day = datetime.strptime(vintage, "%Y-%m-%d").strftime("%-d %B %Y")
        index_rows.append(
            f'        <a href="/notes/releases/{vintage}"><span>{day}: {len(items)} '
            f"series, {new} with a new observation</span>"
            f"<strong>{vintage} · automated digest</strong></a>"
        )
        sitemap_rows.append(
            f"  <url><loc>https://policyengine-macro.vercel.app/notes/releases/{vintage}</loc>"
            "<priority>0.6</priority></url>"
        )
    latest = pages[0].parent.name if pages else ""
    summary_row = (
        f'        <a href="/notes/releases"><span>{len(pages)} automated release '
        f"digests, latest {latest} →</span><strong>{latest} · automated release "
        "digests</strong></a>"
    )
    marker_replace(NOTES_INDEX, "generated-release-notes", summary_row)
    marker_replace(RELEASES_INDEX, "generated-release-notes", "\n".join(index_rows))
    marker_replace(SITEMAP, "generated-release-notes", "\n".join(sitemap_rows))


def check() -> int:
    failures = []
    releases_index = RELEASES_INDEX.read_text()
    sitemap = SITEMAP.read_text()
    if 'href="/notes/releases"' not in NOTES_INDEX.read_text():
        failures.append("forecasts index: missing collapsed link to /notes/releases")
    if "/notes/releases</loc>" not in sitemap:
        failures.append("sitemap: missing /notes/releases entry")
    for page in generated_pages():
        if page not in digest_pages():
            failures.append(f"{page.parent.name}: legacy per-series note; run --rebuild")
    for page in digest_pages():
        vintage = page.parent.name
        if f"/notes/releases/{vintage}\"" not in releases_index:
            failures.append(f"{vintage}: missing from releases index")
        if f"/notes/releases/{vintage}</loc>" not in sitemap:
            failures.append(f"{vintage}: missing from sitemap")
        if not snapshots(vintage):
            failures.append(f"{vintage}: no committed snapshot to rebuild it from")
        elif render_digest(page, vintage) != page.read_text():
            failures.append(f"{vintage}: stale; run notes/generate_release_notes.py --rebuild")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"OK — {len(digest_pages())} release digest(s) indexed and current")
    return 0


def write_digest(vintage: str) -> bool:
    destination = GENERATED_ROOT / vintage / "index.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fresh = render_digest(destination, vintage)
    if destination.exists() and destination.read_text() == fresh:
        return False
    destination.write_text(fresh)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--vintage",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--rebuild", action="store_true",
        help="rewrite every digest from its snapshots (after a template change); "
             "folds any legacy per-series note into its date's digest",
    )
    args = parser.parse_args()
    if args.check:
        return check()
    if args.rebuild:
        rebuilt = 0
        for vintage in digest_dates():
            if not snapshots(vintage):
                raise SystemExit(f"{vintage}: no committed snapshot to rebuild it from")
            rebuilt += write_digest(vintage)
        for page in generated_pages():
            if page not in digest_pages():
                page.unlink()
                page.parent.rmdir()
        rebuild_indexes()
        print(f"rebuilt {rebuilt} release digest(s)")
        return 0

    written = 0
    if snapshots(args.vintage):
        written = int(write_digest(args.vintage))
    rebuild_indexes()
    print(f"generated {written} release digest(s) for {args.vintage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
