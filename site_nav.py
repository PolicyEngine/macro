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
STYLE_VERSION = 27
STYLE_HREF = f"/style.css?v={STYLE_VERSION}"

# Inter (latin) is the body face on every page, but the browser only finds the
# file after it has fetched and parsed fonts.css and laid out text. With
# font-display: swap the page first paints in the fallback face and re-wraps
# when Inter lands, which shifted /notes/2026-07-25-cpi-2026q2 by CLS 0.35 at
# 1440 px. Preloading it starts the download with the HTML, so the first paint
# is already in Inter. JetBrains Mono is not preloaded: 14 pages never use it.
# ``render`` writes the line into every page; economy/topics.py emits it too.
FONTS_CSS_LINK = '<link rel="stylesheet" href="/vendor/fonts/fonts.css" />'
FONT_PRELOAD = (
    '<link rel="preload" href="/vendor/fonts/inter-latin.woff2" as="font" '
    'type="font/woff2" crossorigin />'
)

DESTINATIONS = (
    # Shell v3 (redesign r12): a product header. The brand is the way home,
    # so there is no Home tab; the three sections follow in reading order:
    # the scored record, the models, then how to run them.
    ("forecasts", "/forecasts", "Forecasts", "nav-tab"),
    ("models", "/models", "Models", "nav-tab"),
    ("use", "/connect", "Use", "nav-tab"),
)

# ---------------------------------------------------------------------------
# The one icon system (redesign r12): Lucide (ISC licence) 24px stroke paths,
# inlined so no page loads an icon font or a sprite. Every icon on the site —
# nav, tabs, headings, cards, stat tiles, CTAs, callouts — comes from here.
# Generators import ``icon``; hand-kept pages paste its output. Decorative by
# default (aria-hidden): the visible label carries the meaning.
ICONS = {
    "home": '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "forecasts": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="m19 9-5 5-4-4-3 3"/>',
    "models": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "use": '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
    "github": '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "arrow-up-right": '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
    "calculator": '<rect width="16" height="20" x="4" y="2" rx="2"/><line x1="8" x2="16" y1="6" y2="6"/><line x1="16" x2="16" y1="14" y2="18"/><path d="M16 10h.01"/><path d="M12 10h.01"/><path d="M8 10h.01"/><path d="M12 14h.01"/><path d="M8 14h.01"/><path d="M12 18h.01"/><path d="M8 18h.01"/>',
    "landmark": '<line x1="3" x2="21" y1="22" y2="22"/><line x1="6" x2="6" y1="18" y2="11"/><line x1="10" x2="10" y1="18" y2="11"/><line x1="14" x2="14" y1="18" y2="11"/><line x1="18" x2="18" y1="18" y2="11"/><polygon points="12 2 20 7 4 7"/>',
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "building": '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "hourglass": '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>',
    "leaf": '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12"/>',
    "shield-check": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "network": '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
    "table": '<path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/>',
    "book-open": '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
    "file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
    "code": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "mail": '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "check-circle": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "x-circle": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "archive": '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
    "bug": '<path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/>',
    "git-merge": '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/>',
    "list": '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>',
    "tag": '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    "scale": '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
}
# Legacy name: generators written before r12 import VIEW_ICONS.
VIEW_ICONS = {key: ICONS[key] for key in ("home", "models", "forecasts", "use")}

# Model id -> icon, so every surface shows the same mark for a model.
MODEL_ICONS = {
    "pe-microsim": "calculator",
    "obr-macro": "landmark",
    "boe-svar": "activity",
    "frb-us": "building",
    "us-hank": "users",
    "psl-og": "hourglass",
    "define-uk": "leaf",
}


def icon(key: str, size: int = 16, cls: str = "i") -> str:
    """One inline Lucide icon. ``cls`` sizes and colours it through style.css."""
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
        'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{ICONS[key]}</svg>'
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
    "/models/compare": "Same question",
    "/obr": "OBR emulator",
    "/svar": "BoE SVAR",
    "/frb-us": "FRB/US",
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
    "/pe": "PolicyEngine microsimulation",
    # Papers are each model's fifth tab, so the leaf reads like the other
    # tabs ("Paper") and the crumb runs through the model (CRUMB_PARENTS).
    "/papers/pe-microsim": "Paper",
    "/papers/obr-macro": "Paper",
    "/papers/boe-svar": "Paper",
    "/papers/frb-us": "Paper",
    "/papers/psl-og": "Paper",
    "/papers/define-uk": "Paper",
    "/reports/define-uk-replication": "Replication report",
    "/reports/us-hank-open-source": "HANK survey",
    "/forecasts": "Forecasts",
    "/forecasts/us": "United States",
    "/notes/releases": "Releases",
    "/connect": "Use",
    "/contact": "Contact",
    "/glossary": "Glossary",
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
    # A paper is read as its model's Paper tab (it carries the model's
    # sub-tab row), so its pathway runs through the model —
    # Home / Models / OBR emulator / Paper — not straight to /models, which
    # left the reader with a tab row for a model the crumb never named.
    "/papers/pe-microsim": "/pe",
    "/papers/obr-macro": "/obr",
    "/papers/boe-svar": "/svar",
    "/papers/frb-us": "/frb-us",
    "/papers/psl-og": "/olg",
    "/papers/define-uk": "/define",
    "/reports/define-uk-replication": "/define",
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
# never reaches it. /connect keeps a hand-kept row of in-page anchors: its
# label does not end in " pages" and SUBTAB_ROW skips it. /models was the
# same until r5 (one 13k px page on phones); the router is now the page and
# each former section is its own tab, so its row is generated like the
# model rows and a new /models/* page joins it by being listed here.
SUBTABS = {
    # r12: /models is one page; side-by-side, combine, validation and papers
    # are sections of it. The row survives only on /models/compare, as a way
    # back plus its own tab (the "/models#choose" href never equals a URL, so
    # /models itself carries no row).
    "models": ("Models pages", (
        ("/models#choose", "All models"), ("/models/compare", "Same question"))),
    "obr": ("OBR emulator pages", (
        ("/obr", "Overview"), ("/obr/methodology", "Methodology"),
        ("/obr/validation", "Validation"), ("/obr/code", "Use it"))),
    "svar": ("BoE SVAR pages", (
        ("/svar", "Overview"), ("/svar/methodology", "Methodology"),
        ("/svar/validation", "Validation"), ("/svar/code", "Use it"))),
    "frb-us": ("FRB/US pages", (
        ("/frb-us", "Overview"), ("/frb-us/methodology", "Methodology"),
        ("/frb-us/validation", "Validation"), ("/frb-us/code", "Use it"))),
    "us-hank": ("US HANK pages", (
        ("/us-hank", "Overview"), ("/us-hank/methodology", "Methodology"),
        ("/us-hank/validation", "Validation"), ("/us-hank/code", "Use it"),
        # us-hank has no paper; its fifth tab is a survey of other HANK models,
        # so it is labelled as such rather than as a page about this model.
        ("/reports/us-hank-open-source", "HANK survey"))),
    "olg": ("OG-UK pages", (
        ("/olg", "Overview"), ("/olg/methodology", "Methodology"),
        ("/olg/validation", "Validation"), ("/olg/code", "Use it"))),
    "pe": ("PolicyEngine microsim pages", (
        ("/pe", "Overview"), ("/pe/methodology", "Methodology"),
        ("/pe/validation", "Validation"), ("/pe/code", "Use it"))),
    "define": ("DEFINE-UK pages", (
        ("/define", "Overview"), ("/define/methodology", "Methodology"),
        ("/define/validation", "Validation"), ("/define/code", "Use it"))),
}
# Pages that belong to a model's row without being one of its URLs. r12:
# the Paper tab folded into Methodology (Fable 5.2), so each paper (and
# DEFINE-UK's replication report) shows the row with Methodology chosen; the
# chosen tab still links back to the Methodology page itself.
SUBTAB_EXTRA = {
    "/papers/obr-macro": ("obr", "Methodology"),
    "/papers/boe-svar": ("svar", "Methodology"),
    "/papers/frb-us": ("frb-us", "Methodology"),
    "/papers/psl-og": ("olg", "Methodology"),
    "/papers/pe-microsim": ("pe", "Methodology"),
    "/papers/define-uk": ("define", "Methodology"),
    "/reports/define-uk-replication": ("define", "Methodology"),
}
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
        if label == chosen and url in SUBTAB_EXTRA:
            # a page filed under this tab: highlight it, keep the route back
            rows.append(f'      <a class="model-tabs-link" href="{href}" aria-current="true">{label}</a>')
        elif label == chosen:
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


# Section sub-nav script (r12): folds the topic links into a "Topics" menu on
# narrow screens. Added to every page carrying .economy-subnav.
SUBNAV_TAG = '<script src="/assets/subnav.js" defer></script>'


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
    """Retired in r12: the header tab says which section a page is in and the
    page title says where; the extra pathway bar is gone sitewide. Kept as a
    function so generators that call it keep working."""
    return ""


GITHUB = (
    '    <a class="nav-gh" href="https://github.com/PolicyEngine/macro" aria-label="GitHub">'
    + icon("github", 18) + "</a>"
)
NAV_CTA = (
    '    <a class="nav-cta" href="/connect">Run a model' + icon("arrow-right", 14) + "</a>"
)

# Footer (r12): four short columns and a legal row. Contact lives here, never
# in the header tabs (site_contract.check_economy_navigation).
_MODEL_LINKS = (
    ("/pe", "PolicyEngine microsimulation"), ("/obr", "OBR emulator"),
    ("/svar", "BoE SVAR"), ("/frb-us", "FRB/US"), ("/us-hank", "US HANK"),
    ("/olg", "OG-UK"), ("/define", "DEFINE-UK"),
)
_FOOTER_COLUMNS = (
    ("Site", (("/forecasts", "Forecasts"), ("/models", "Models"),
                 ("/connect", "Use"), ("/notes/releases", "Release notes"))),
    ("Models", _MODEL_LINKS),
    ("Evidence", (("/models#trust", "Where models fail"), ("/models/compare", "Same question"),
               ("/models#papers", "Papers"), ("/glossary", "Glossary"))),
    ("Project", (("https://policyengine.org", "PolicyEngine"),
                 ("https://github.com/PolicyEngine/macro", "GitHub"),
                 ("https://github.com/PolicyEngine/macro/issues", "Report an issue"),
                 ("/contact", "Contact"))),
)


def _footer_links() -> str:
    cols = [
        '    <div class="foot-brand">\n'
        '      <a class="footer-policyengine" href="/"><img src="/assets/policyengine-mark.svg" alt="" width="20" height="20" />PolicyEngine Macro</a>\n'
        '      <p>Open economic models for UK and US policy, each labelled with how far it can be checked.</p>\n'
        '    </div>'
    ]
    for title, links in _FOOTER_COLUMNS:
        items = "\n".join(
            f'        <li><a class="footer-text" href="{href}">{label}</a></li>'
            for href, label in links
        )
        cols.append(
            f'    <div class="foot-col">\n      <p class="foot-head">{title}</p>\n'
            f'      <ul>\n{items}\n      </ul>\n    </div>'
        )
    return "\n".join(cols)


FOOTER_LINKS = _footer_links()


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
            f"    <a{class_attr} href=\"{href}\"{current_attr}>{icon(key, 18)}{label}</a>"
        )
    return """<header class="nav">
  <a class="brand" href="/" aria-label="PolicyEngine Macro home">
    <img class="brand-logo" src="/assets/policyengine-mark.svg" alt="" width="24" height="24" /><span class="brand-name">PolicyEngine <b>Macro</b></span>
  </a>
  <nav class="nav-links" aria-label="Primary">
%s
  </nav>
  <div class="nav-end">
%s
%s
  </div>
</header>

""" % ("\n".join(links), GITHUB, "" if page_href == "/connect" else NAV_CTA)


def expander(icon_key: str, title: str, summary: str, body: str, open_: bool = False, id_: str = "") -> str:
    """The one shared expander (r12): icon, title, one-line summary, chevron.

    A native <details>, so it works with no script and is keyboard and
    screen-reader accessible; style.css section 13 animates the open where the
    browser supports ::details-content. ``body`` is trusted HTML.
    """
    attrs = (" open" if open_ else "") + (f' id="{id_}"' if id_ else "")
    return (
        f'<details class="xp"{attrs}>\n'
        f'  <summary><span class="xp-ic">{icon(icon_key, 16)}</span>'
        f'<span class="xp-t"><strong>{title}</strong><small>{summary}</small></span>'
        '<span class="xp-chev" aria-hidden="true"></span></summary>\n'
        f'  <div class="xp-body">\n{body}\n  </div>\n</details>'
    )


# "Where next" row (DESIGN.md §4.7, §8): the last card on generated pages.
# Icons are 24 px Lucide-style strokes, decorative.
CARD_ICONS = {
    # Aliases onto the one icon set, so "where next" cards match the shell.
    "chart": ICONS["forecasts"], "data": ICONS["database"], "topic": ICONS["book-open"],
    "list": ICONS["list"], "model": ICONS["models"], "plug": ICONS["use"],
    "target": ICONS["target"],
}


def where_next(cards: list[tuple[str, str, str, str]], indent: str = "  ") -> str:
    """A "where next" card: (href, icon key, title, one line) per entry card."""
    rows = []
    for href, key, title, line in cards:
        rows.append(
            f'{indent}    <a class="entry-card" href="{href}">\n'
            f'{indent}      <span class="icon-badge" aria-hidden="true"><svg viewBox="0 0 24 24" '
            'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
            f'stroke-linejoin="round">{CARD_ICONS[key]}</svg></span>\n'
            f"{indent}      <h3>{title}</h3>\n"
            f"{indent}      <p>{line}</p>\n"
            f'{indent}      <span class="entry-cta">Explore <span aria-hidden="true">&rarr;</span></span>\n'
            f"{indent}    </a>"
        )
    return (
        f'{indent}<section class="band where-next" id="where-next">\n'
        f'{indent}  <div class="band-head" data-icon="link"><h2>Keep reading</h2></div>\n'
        f'{indent}  <div class="entry-grid">\n' + "\n".join(rows) + "\n"
        f"{indent}  </div>\n{indent}</section>"
    )


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
        if not any(
            part.startswith(".") or part == "node_modules"
            for part in path.relative_to(ROOT).parts
        )
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


def render(path: Path, source: str | None = None) -> str:
    """The page at ``path`` with the shell stamped in.

    ``source`` renders a page body that is not on disk yet (a generator's
    template) as if it lived at ``path``; nothing is written either way.
    """
    if source is None:
        source = path.read_text()
    updated, replacements = HEADER.subn(header(path), source, count=1)
    if replacements != 1:
        raise ValueError(f"could not locate navigation in {path.relative_to(ROOT)}")
    updated = updated.replace(" has-section-tabs", "")
    updated = STYLESHEET.sub(f'href="{STYLE_HREF}"', updated)
    if FONT_PRELOAD not in updated:
        updated = updated.replace(FONTS_CSS_LINK, f"{FONT_PRELOAD}\n{FONTS_CSS_LINK}", 1)
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
    if 'class="economy-subnav"' in updated and SUBNAV_TAG not in updated:
        updated = updated.replace("</body>", f"{SUBNAV_TAG}\n</body>", 1)
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
