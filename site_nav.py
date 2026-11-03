#!/usr/bin/env python3
"""Build or check the single global navigation used by every public page."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEADER = re.compile(
    r'<header class="nav">.*?</header>\s*'
    r'(?:<nav class="section-tabs".*?</nav>\s*)?'
    r'(?:<nav class="crumbs.*?</nav>\s*)?',
    re.DOTALL,
)
FOOTER_DIR = re.compile(r'<nav class="footer-dir".*?</nav>\s*', re.DOTALL)
STYLESHEET = re.compile(r'href="/style\.css(?:\?v=[0-9]+)?"')

# Cache buster for the one shared stylesheet. Bump it whenever style.css
# changes in a way a cached copy would render wrongly; ``render`` writes it
# into every page and the generators read it from here (economy/topics.py,
# notes/generate_release_notes.py), so no page can be left on an old copy.
STYLE_VERSION = 8
STYLE_HREF = f"/style.css?v={STYLE_VERSION}"

DESTINATIONS = (
    ("home", "/", "Home", "nav-mobile"),
    ("models", "/models", "Models", "nav-mobile"),
    # Economy was folded into Forecasts: one tab for everything the platform
    # produces and the data it is produced from. /economy and /economy/us keep
    # their URLs — ~200 generated release notes, the homepage and the models
    # hub link to them in prose — but they are Forecasts pages now, and
    # ``section`` and ``CRUMB_PARENTS`` below are what make that true.
    ("forecasts", "/forecasts", "Forecasts", "nav-mobile"),
    ("use", "/connect", "Use", "nav-mobile nav-start"),
)

# One 24px stroke icon per view (DESIGN.md §3.1). Decorative: the label is
# the link text, so every icon is aria-hidden and the tab still reads
# "Forecasts" to a screen reader and to site_contract's ">Forecasts</a>".
VIEW_ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
    "models": '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12.5 9 5 9-5"/><path d="m3 16.5 9 5 9-5"/>',
    "forecasts": '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 6-7"/>',
    "use": '<path d="M9 2v6"/><path d="M15 2v6"/><path d="M6 8h12v4a6 6 0 0 1-12 0V8Z"/><path d="M12 18v4"/>',
}


def icon(key: str) -> str:
    return (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
        'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{VIEW_ICONS[key]}</svg>'
    )

MODEL_ROOTS = {"models", "obr", "svar", "frb-us", "us-hank", "olg", "pe", "define"}
EVIDENCE_ROOTS = {"papers", "reports"}

# Display names used in the pathway line and the footer directory.
PAGE_NAMES = {
    # The two country data hubs. Named for the job they do inside Forecasts —
    # the series, the long view and the provenance the record is scored on —
    # rather than for the URL segment they still live under.
    "/economy": "UK data",
    # Nested topic pages: without these the crumb falls back to
    # "economy/topics".title() and the raw slug, so a reader sees
    # "Economy/Topics / rates" instead of "Topics / Rates and gilts".
    "/economy/topics": "Topics",
    "/economy/topics/growth": "Growth",
    "/economy/topics/inflation": "Inflation",
    "/economy/topics/jobs": "Jobs",
    "/economy/topics/rates": "Rates and gilts",
    "/economy/topics/public-finances": "Public finances",
    "/economy/topics/reform": "Tax and benefit reform",
    "/economy/us": "US data",
    "/economy/us/topics": "Topics",
    "/economy/us/topics/growth": "Growth",
    "/economy/us/topics/inflation": "Inflation",
    "/economy/us/topics/jobs": "Jobs",
    "/economy/us/topics/rates": "Rates and Treasuries",
    "/economy/us/topics/reform": "Tax and benefit reform",
    "/models": "Models",
    "/obr": "OBR emulator",
    "/svar": "BoE SVAR",
    "/frb-us": "FRB-US",
    "/us-hank": "US HANK",
    "/olg": "OG-UK",
    "/define": "DEFINE-UK",
    "/define/methodology": "Methodology",
    "/define/validation": "Validation",
    "/define/code": "Code",
    "/obr/code": "Code",
    "/obr/methodology": "Methodology",
    "/obr/validation": "Validation",
    "/svar/code": "Code",
    "/svar/methodology": "Methodology",
    "/svar/validation": "Validation",
    "/frb-us/code": "Code",
    "/frb-us/methodology": "Methodology",
    "/frb-us/validation": "Validation",
    "/us-hank/code": "Code",
    "/us-hank/methodology": "Methodology",
    "/us-hank/validation": "Validation",
    "/pe/code": "Code",
    "/pe/methodology": "Methodology",
    "/pe/validation": "Validation",
    "/olg/code": "Code",
    "/olg/methodology": "Methodology",
    "/olg/validation": "Validation",
    "/pe": "PolicyEngine microsim",
    "/papers/pe-microsim": "pe-microsim",
    "/papers/obr-macro": "obr-macro",
    "/papers/boe-svar": "boe-svar",
    "/papers/frb-us": "frb-us",
    "/papers/psl-og": "psl-og",
    "/papers/define-uk": "define-uk",
    "/reports/define-uk-replication": "define-uk",
    "/reports/us-hank-open-source": "Open models",
    "/forecasts": "Forecasts",
    "/forecasts/us": "United States",
    "/notes/releases": "Releases",
    "/connect": "Use",
    "/contact": "Contact",
}

# Parent chain overrides where the URL hierarchy is not the reading hierarchy:
# model and evidence pages live under Models; /score is a top-level section.
CRUMB_PARENTS = {
    "/obr": "/models",
    "/svar": "/models",
    "/frb-us": "/models",
    "/us-hank": "/models",
    "/olg": "/models",
    "/pe": "/models",
    "/define": "/models",
    "/papers/pe-microsim": "/models",
    "/papers/obr-macro": "/models",
    "/papers/boe-svar": "/models",
    "/papers/frb-us": "/models",
    "/papers/psl-og": "/models",
    "/papers/define-uk": "/models",
    "/reports/define-uk-replication": "/models",
    # The open-models survey is one of the five us-hank tabs, so its pathway
    # runs through the model rather than straight to /models.
    "/reports/us-hank-open-source": "/us-hank",
    # /notes was folded into /forecasts#notes; the surviving note pages hang
    # off Forecasts so no crumb links to the retired /notes page.
    "/notes/releases": "/forecasts",
    "/notes/2026-07-25-cpi-2026q2": "/forecasts",
    # Economy was merged into Forecasts. The URLs did not move, so the reading
    # hierarchy and the URL hierarchy disagree here on purpose: both country
    # data hubs hang off /forecasts directly rather than off each other, which
    # keeps every crumb four segments at most —
    # Home / Forecasts / US data / Growth.
    "/economy": "/forecasts",
    "/economy/us": "/forecasts",
}


# Model sub-tab rows (DESIGN.md §3.4), keyed by model root: the aria-label
# and the five tabs in order. ``render`` writes the row on every page whose
# URL is one of the tabs, so the rows are generated rather than hand-kept.
# The row sits below the title band, outside ``</header>``, so HEADER above
# never reaches it. /models and /connect keep hand-kept rows of in-page
# anchors: their labels do not end in " pages" and SUBTAB_ROW skips them.
SUBTABS = {
    "obr": ("OBR emulator pages", (
        ("/obr", "Overview"), ("/obr/methodology", "Methodology"),
        ("/obr/validation", "Validation"), ("/obr/code", "Code"),
        ("/papers/obr-macro", "Paper"))),
    "svar": ("BoE SVAR pages", (
        ("/svar", "Overview"), ("/svar/methodology", "Methodology"),
        ("/svar/validation", "Validation"), ("/svar/code", "Code"),
        ("/papers/boe-svar", "Paper"))),
    "frb-us": ("FRB-US pages", (
        ("/frb-us", "Overview"), ("/frb-us/methodology", "Methodology"),
        ("/frb-us/validation", "Validation"), ("/frb-us/code", "Code"),
        ("/papers/frb-us", "Paper"))),
    "us-hank": ("US HANK pages", (
        ("/us-hank", "Overview"), ("/us-hank/methodology", "Methodology"),
        ("/us-hank/validation", "Validation"), ("/us-hank/code", "Code"),
        # us-hank has no paper; its fifth tab is the open-models survey.
        ("/reports/us-hank-open-source", "Open models"))),
    "olg": ("OG-UK pages", (
        ("/olg", "Overview"), ("/olg/methodology", "Methodology"),
        ("/olg/validation", "Validation"), ("/olg/code", "Code"),
        ("/papers/psl-og", "Paper"))),
    "pe": ("PolicyEngine microsim pages", (
        ("/pe", "Overview"), ("/pe/methodology", "Methodology"),
        ("/pe/validation", "Validation"), ("/pe/code", "Code"),
        ("/papers/pe-microsim", "Paper"))),
    "define": ("DEFINE-UK pages", (
        ("/define", "Overview"), ("/define/methodology", "Methodology"),
        ("/define/validation", "Validation"), ("/define/code", "Code"),
        ("/papers/define-uk", "Paper"))),
}
# Pages that belong to a model's row without being one of its five URLs:
# the replication report is read as DEFINE-UK's Paper tab, so on that page
# the Paper tab points at the report itself and is the chosen one.
SUBTAB_EXTRA = {"/reports/define-uk-replication": ("define", "Paper")}
SUBTAB_ROW = re.compile(r'<nav class="model-tabs" aria-label="[^"]* pages">.*?</nav>', re.DOTALL)


def subtab_owner(url: str) -> tuple[str, str] | None:
    """(model root, chosen tab label) for a page that carries a model row."""
    if url in SUBTAB_EXTRA:
        return SUBTAB_EXTRA[url]
    for key, (_, tabs) in SUBTABS.items():
        for href, label in tabs:
            if href == url:
                return key, label
    return None


def subtabs(url: str) -> str | None:
    owner = subtab_owner(url)
    if owner is None:
        return None
    key, chosen = owner
    aria, tabs = SUBTABS[key]
    rows = []
    for href, label in tabs:
        if label == chosen:
            href = url
            rows.append(f'      <a class="model-tabs-link" href="{href}" aria-current="page">{label}</a>')
        else:
            rows.append(f'      <a class="model-tabs-link" href="{href}">{label}</a>')
    return (
        f'<nav class="model-tabs" aria-label="{aria}">\n'
        '    <div class="model-tabs-row">\n'
        + "\n".join(rows)
        + "\n    </div>\n  </nav>"
    )


# Every page with a StepPanel or an "On this page" rail loads the one shared
# script; the inline copies it replaced must not come back.
STEPPER_TAG = '<script src="/stepper.js" defer></script>'
INLINE_STEPPER = re.compile(r"<script>(?:(?!</script>).)*?(?:\.meth-step|\.page-rail)", re.DOTALL)


def needs_stepper(source: str) -> bool:
    return 'class="scrolly-wrap' in source or 'class="page-rail' in source


def page_url(path: Path) -> str:
    rel = path.relative_to(ROOT)
    if rel == Path("index.html"):
        return "/"
    if rel.name == "index.html":
        return "/" + str(rel.parent)
    return "/" + str(rel)


def crumb_chain(url: str) -> list[str]:
    """Ancestor URLs for the pathway line, ending at the page itself."""
    chain: list[str] = []
    current = url
    while current and current != "/":
        chain.insert(0, current)
        if current in CRUMB_PARENTS:
            current = CRUMB_PARENTS[current]
        else:
            current = current.rsplit("/", 1)[0] or "/"
            if current == "/notes":
                # /notes retired into /forecasts#notes: never emit a crumb
                # link to the deleted index page.
                current = "/forecasts"
            if current == "/economy/topics":
                # Same treatment: /economy/topics is a redirect source, not a
                # page, so the crumb on all six topic pages was a 308 hop.
                # One retired prefix was handled here and the other was not.
                current = "/economy"
            if current == "/economy/us/topics":
                # And the US mirror of it. Skipping the segment lands on
                # /economy/us, which is a real page, so the chain reads
                # Home / Economy / United States / <topic>.
                current = "/economy/us"
            if current == "/":
                break
    return chain


def crumbs(path: Path) -> str:
    """One-line pathway under the header: Home / Section / Page."""
    url = page_url(path)
    if url == "/":
        return ""
    parts = ['    <a href="/">Home</a>']
    chain = crumb_chain(url)
    for ancestor in chain[:-1]:
        label = PAGE_NAMES.get(ancestor, ancestor.strip("/").title())
        parts.append(f'    <a href="{ancestor}">{label}</a>')
    # Leaf: current page, not a link. Dated note slugs render as their date.
    leaf = PAGE_NAMES.get(url)
    if leaf is None:
        slug = url.rsplit("/", 1)[-1]
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", slug)
        if m:
            import calendar

            leaf = (
                f"{int(m.group(3))} "
                f"{calendar.month_name[int(m.group(2))]} {m.group(1)}"
            )
        else:
            leaf = slug
    parts.append(f'    <span aria-current="page">{leaf}</span>')
    inner = "\n".join(parts)
    return (
        '<nav class="crumbs mono" aria-label="You are here">\n'
        f"{inner}\n"
        "</nav>\n\n"
    )

GITHUB = """    <a class="nav-gh" href="https://github.com/PolicyEngine/macro" aria-label="GitHub"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 19c-4.3 1.4 -4.3 -2.5 -6 -3m12 5v-3.5c0 -1 .1 -1.4 -.5 -2c2.8 -.3 5.5 -1.4 5.5 -6a4.6 4.6 0 0 0 -1.3 -3.2a4.2 4.2 0 0 0 -.1 -3.2s-1.1 -.3 -3.5 1.3a12.3 12.3 0 0 0 -6.2 0c-2.4 -1.6 -3.5 -1.3 -3.5 -1.3a4.2 4.2 0 0 0 -.1 3.2c-.9 .9 -1.3 2 -1.3 3.2c0 4.6 2.7 5.7 5.5 6c-.6 .6 -.6 1.2 -.5 2v3.5"/></svg></a>"""
# The footer stays one small row (#133 dropped the four-column directory and
# kept PolicyEngine, GitHub and Contact): the views live in the header tabs,
# not here. Contact lives here, never in the header tabs
# (site_contract.check_economy_navigation).
FOOTER_LINKS = """    <a class="footer-text footer-policyengine" href="https://policyengine.org"><img src="/assets/policyengine-mark.svg" alt="" width="17" height="17" />PolicyEngine</a>
    <a class="footer-text" href="https://github.com/PolicyEngine/macro">GitHub</a>
    <a class="footer-text" href="/contact">Contact</a>"""


def section(path: Path) -> str | None:
    relative = path.relative_to(ROOT)
    root = relative.parts[0]
    if relative == Path("index.html"):
        return "home"
    if root in MODEL_ROOTS:
        return "models"
    if root in EVIDENCE_ROOTS:
        return "models"
    # Both roots are one section now. /economy keeps its URLs but highlights
    # the Forecasts tab, so a reader on a topic page is never told they are in
    # a section the header no longer offers.
    if root in ("economy", "forecasts"):
        return "forecasts"
    # Release notes hang off Forecasts in the pathway (CRUMB_PARENTS), so the
    # view tab agrees with the crumb instead of leaving no tab chosen.
    if root == "notes":
        return "forecasts"
    if root == "connect":
        return "use"
    return None


def header(path: Path) -> str:
    current = section(path)
    # aria-current="page" only when the link target IS this page; section
    # ancestors get aria-current="true" so screen readers are not told a
    # different URL is the current page.
    page_href = "/" + str(path.relative_to(ROOT).parent)
    if path.relative_to(ROOT) == Path("index.html"):
        page_href = "/"
    links = []
    for key, href, label, classes in DESTINATIONS:
        class_attr = f' class="{classes}"' if classes else ""
        if href == page_href:
            current_attr = ' aria-current="page"'
        elif key == current:
            current_attr = ' aria-current="true"'
        else:
            current_attr = ""
        links.append(
            f"    <a{class_attr} href=\"{href}\"{current_attr}>{icon(key)}{label}</a>"
        )
    links.append(GITHUB)
    return """<header class="nav">
  <a class="brand" href="/" aria-label="PolicyEngine Macro home">
    <img class="brand-logo" src="/assets/policyengine-mark.svg" alt="" width="26" height="26" /><span class="brand-name">PolicyEngine Macro</span>
  </a>
  <nav class="nav-links" aria-label="Primary">
%s
  </nav>
</header>

%s""" % ("\n".join(links), crumbs(path))


# Standalone documents allowed to ship without the global nav header.
# Empty: reports/us-hank-open-source was the last one, and a reader clicking
# through from /us-hank landed on a page with no header, no breadcrumb and no
# footer, which reads as leaving the site. It now carries the global chrome
# like every other page. Anything without <header class="nav"> fails the check
# instead of being silently skipped forever.
NAV_EXEMPT: set[Path] = set()

# Directories that never contain public pages.
SKIP_ROOTS = {"vendor", "reveal.js", "audit", "assets", "data"}


def all_html() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.html")
        if not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
        and path.relative_to(ROOT).parts[0] not in SKIP_ROOTS
    )


def pages() -> list[Path]:
    return [
        path for path in all_html()
        if '<header class="nav">' in path.read_text()
    ]


def navless_violations() -> list[Path]:
    return [
        path for path in all_html()
        if '<header class="nav">' not in path.read_text()
        and path.relative_to(ROOT) not in NAV_EXEMPT
    ]


def render(path: Path) -> str:
    source = path.read_text()
    updated, replacements = HEADER.subn(header(path), source, count=1)
    if replacements != 1:
        raise ValueError(f"could not locate navigation in {path.relative_to(ROOT)}")
    updated = updated.replace(" has-section-tabs", "")
    updated = STYLESHEET.sub(f'href="{STYLE_HREF}"', updated)
    # The footer stays small: a single link row. Strip any directory block a
    # previous revision may have left behind.
    updated = FOOTER_DIR.sub("", updated)
    footer_pattern = re.compile(
        r'(<nav class="footer-links" aria-label="PolicyEngine links">).*?(\s*</nav>)',
        re.DOTALL,
    )
    updated, footer_replacements = footer_pattern.subn(
        lambda match: f"{match.group(1)}\n{FOOTER_LINKS}{match.group(2)}",
        updated,
        count=1,
    )
    if footer_replacements != 1:
        raise ValueError(f"could not locate footer navigation in {path.relative_to(ROOT)}")
    url = page_url(path)
    row = subtabs(url)
    found = SUBTAB_ROW.findall(updated)
    if row is None and found:
        raise ValueError(f"model sub-tab row on a page SUBTABS does not list: {url}")
    if row is not None:
        if len(found) != 1:
            raise ValueError(f"expected one model sub-tab row in {path.relative_to(ROOT)}, found {len(found)}")
        updated = SUBTAB_ROW.sub(lambda _m: row, updated, count=1)
    if INLINE_STEPPER.search(updated):
        raise ValueError(f"inline StepPanel/rail script in {path.relative_to(ROOT)}: use {STEPPER_TAG}")
    if needs_stepper(updated) and STEPPER_TAG not in updated:
        updated = updated.replace("</body>", f"{STEPPER_TAG}\n</body>", 1)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    stale = []
    for path in pages():
        updated = render(path)
        if updated == path.read_text():
            continue
        stale.append(path)
        if args.write:
            path.write_text(updated)

    violations = navless_violations()
    if violations:
        for path in violations:
            print(
                f"FAIL page without global nav (add the header or list it in "
                f"NAV_EXEMPT): {path.relative_to(ROOT)}",
                file=sys.stderr,
            )
        return 1

    if stale and not args.write:
        for path in stale:
            print(f"FAIL stale navigation: {path.relative_to(ROOT)}", file=sys.stderr)
        print("run python3 site_nav.py --write", file=sys.stderr)
        return 1
    print(f"OK — global navigation current on {len(pages())} page(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
