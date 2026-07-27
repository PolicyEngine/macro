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
    r'(?:<nav class="section-tabs".*?</nav>\s*)?',
    re.DOTALL,
)

DESTINATIONS = (
    ("home", "/", "Home", "nav-mobile"),
    ("economy", "/economy/", "Economy", "nav-mobile"),
    ("models", "/models/", "Models", ""),
    ("forecasts", "/forecasts/", "Forecasts", ""),
    ("evidence", "/validation/", "Evidence", ""),
    ("use", "/connect/", "Use", "nav-mobile nav-start"),
    ("contact", "/contact/", "Contact", ""),
)

MODEL_ROOTS = {"models", "obr", "svar", "frb-us", "us-hank", "olg", "pe"}
EVIDENCE_ROOTS = {"validation", "papers", "docs"}

GITHUB = """    <a class="nav-gh" href="https://github.com/PolicyEngine/macro" aria-label="GitHub"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 19c-4.3 1.4 -4.3 -2.5 -6 -3m12 5v-3.5c0 -1 .1 -1.4 -.5 -2c2.8 -.3 5.5 -1.4 5.5 -6a4.6 4.6 0 0 0 -1.3 -3.2a4.2 4.2 0 0 0 -.1 -3.2s-1.1 -.3 -3.5 1.3a12.3 12.3 0 0 0 -6.2 0c-2.4 -1.6 -3.5 -1.3 -3.5 -1.3a4.2 4.2 0 0 0 -.1 3.2c-.9 .9 -1.3 2 -1.3 3.2c0 4.6 2.7 5.7 5.5 6c-.6 .6 -.6 1.2 -.5 2v3.5"/></svg></a>"""


def section(path: Path) -> str | None:
    relative = path.relative_to(ROOT)
    root = relative.parts[0]
    if relative == Path("index.html"):
        return "home"
    if root in MODEL_ROOTS:
        return "models"
    if root in EVIDENCE_ROOTS:
        return "evidence"
    if root == "economy":
        return "economy"
    if root == "forecasts":
        return "forecasts"
    if root == "connect":
        return "use"
    if root == "contact":
        return "contact"
    return None


def header(path: Path) -> str:
    current = section(path)
    links = []
    for key, href, label, classes in DESTINATIONS:
        class_attr = f' class="{classes}"' if classes else ""
        current_attr = ' aria-current="page"' if key == current else ""
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

""" % "\n".join(links)


def pages() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.html")
        if not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
        and '<header class="nav">' in path.read_text()
    )


def render(path: Path) -> str:
    source = path.read_text()
    updated, replacements = HEADER.subn(header(path), source, count=1)
    if replacements != 1:
        raise ValueError(f"could not locate navigation in {path.relative_to(ROOT)}")
    return updated.replace(" has-section-tabs", "")


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

    if stale and not args.write:
        for path in stale:
            print(f"FAIL stale navigation: {path.relative_to(ROOT)}", file=sys.stderr)
        print("run python3 site_nav.py --write", file=sys.stderr)
        return 1
    print(f"OK — global navigation current on {len(pages())} page(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
