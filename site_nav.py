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

DESTINATIONS = (
    ("home", "/", "Home", "nav-mobile"),
    ("economy", "/economy", "Economy", "nav-mobile"),
    ("models", "/models", "Models", "nav-mobile"),
    ("forecasts", "/forecasts", "Track record", "nav-mobile"),
    ("use", "/connect", "Use", "nav-mobile nav-start"),
)

MODEL_ROOTS = {"models", "obr", "svar", "frb-us", "us-hank", "olg", "pe"}
EVIDENCE_ROOTS = {"validation", "papers", "docs"}

# Display names used in the pathway line and the footer directory.
PAGE_NAMES = {
    "/economy": "Economy",
    "/economy/us": "United States",
    "/economy/trends": "Trends",
    "/economy/us/trends": "Trends",
    "/models": "Models",
    "/obr": "OBR emulator",
    "/svar": "BoE SVAR",
    "/frb-us": "FRB-US",
    "/us-hank": "US HANK",
    "/olg": "OG-UK",
    "/pe": "PolicyEngine microsim",
    "/validation": "Validation",
    "/papers": "Papers",
    "/papers/obr-macro": "obr-macro",
    "/papers/boe-svar": "boe-svar",
    "/papers/frb-us": "frb-us",
    "/papers/psl-og": "psl-og",
    "/forecasts": "Track record",
    "/notes": "Notes",
    "/connect": "Use",
    "/score": "Score a reform",
    "/contact": "Contact",
}

# Parent chain overrides where the URL hierarchy is not the reading hierarchy:
# model and evidence pages live under Models, /score under Use.
CRUMB_PARENTS = {
    "/obr": "/models",
    "/svar": "/models",
    "/frb-us": "/models",
    "/us-hank": "/models",
    "/olg": "/models",
    "/pe": "/models",
    "/validation": "/models",
    "/papers": "/models",
    "/score": "/connect",
}


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
FOOTER_LINKS = """    <a class="footer-text footer-policyengine" href="https://policyengine.org"><img src="/assets/policyengine-mark.svg" alt="" width="17" height="17" />PolicyEngine</a>
    <a class="footer-text" href="https://github.com/PolicyEngine/macro">GitHub</a>
    <a class="footer-text" href="/contact">Contact</a>"""

# Full site directory rendered above the footer links on every page, so no
# public page is reachable only through in-page prose.
FOOTER_DIRECTORY = (
    ("Economy", (("/economy", "United Kingdom"), ("/economy/us", "United States"),
                 ("/economy/trends", "UK trends"), ("/economy/us/trends", "US trends"),
                 ("/notes", "Research notes"))),
    ("Models", (("/models", "All six models"), ("/obr", "OBR emulator"),
                ("/svar", "BoE SVAR"), ("/frb-us", "FRB-US"),
                ("/us-hank", "US HANK"), ("/olg", "OG-UK"),
                ("/pe", "PolicyEngine microsim"))),
    ("Evidence", (("/validation", "Validation"), ("/papers", "Working papers"),
                  ("/forecasts", "Forecast track record"))),
    ("Use", (("/connect", "Connect an AI or CLI"), ("/score", "Score a reform"),
             ("/contact", "Contact"))),
)


def footer_directory() -> str:
    cols = []
    for heading, links in FOOTER_DIRECTORY:
        rows = "\n".join(
            f'      <a href="{href}">{label}</a>' for href, label in links
        )
        cols.append(
            f'    <div class="footer-dir-col">\n      <strong class="mono">'
            f"{heading}</strong>\n{rows}\n    </div>"
        )
    return (
        '<nav class="footer-dir" aria-label="All pages">\n'
        + "\n".join(cols)
        + "\n  </nav>\n  "
    )


def section(path: Path) -> str | None:
    relative = path.relative_to(ROOT)
    root = relative.parts[0]
    if relative == Path("index.html"):
        return "home"
    if root in MODEL_ROOTS:
        return "models"
    if root in EVIDENCE_ROOTS:
        return "models"
    if root == "economy":
        return "economy"
    if root == "forecasts":
        return "forecasts"
    if root in {"connect", "score"}:
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
        links.append(f"    <a{class_attr} href=\"{href}\"{current_attr}>{label}</a>")
    links.append(GITHUB)
    return """<header class="nav">
  <a class="brand" href="/">
    <img class="brand-logo" src="/assets/policyengine-mark.svg" alt="" width="20" height="20" />PolicyEngine Macro
  </a>
  <nav class="nav-links" aria-label="Primary">
%s
  </nav>
</header>

%s""" % ("\n".join(links), crumbs(path))


# Standalone documents allowed to ship without the global nav header.
# Anything else without <header class="nav"> fails the check instead of
# being silently skipped forever.
NAV_EXEMPT = {
    Path("reports/us-hank-open-source.html"),
}

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
    # Footer directory: strip any previous copy, then insert one before the
    # footer links so every page carries the full site map.
    updated = FOOTER_DIR.sub("", updated)
    updated = updated.replace(
        '<nav class="footer-links" aria-label="PolicyEngine links">',
        footer_directory()
        + '<nav class="footer-links" aria-label="PolicyEngine links">',
        1,
    )
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
