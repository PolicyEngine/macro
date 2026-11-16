"""Stamp the shared model-page hero strip onto every model page.

One template for the seven models' pages (Overview, Methodology, Validation,
Code, Paper): icon tile, kind line, name, the page's own lede, and a meta row
(country, trust status, access, cadence). The trust chip links to the same
glossary entry the Overview verdict uses, so the status reads identically on
every tab. Idempotent: re-running replaces the strip in place.

    python3 tools/model_hero.py          # rewrite pages
    python3 tools/model_hero.py --check  # exit 1 if any page is stale
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_LINK = '<link rel="stylesheet" href="/models/model-pages.css?v=4" />'
CSS_RE = re.compile(r'<link rel="stylesheet" href="/models/model-pages\.css(?:\?v=\d+)?" />\n?')

# Tabler-style 24px stroke icons.
ICONS = {
    # PolicyEngine microsimulation: a population of households
    "pe": '<path d="M5 7a4 4 0 1 0 8 0a4 4 0 1 0-8 0M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2M16 3.1a4 4 0 0 1 0 7.8M21 21v-2a4 4 0 0 0-3-3.85"/>',
    # OBR: a balance sheet / fiscal ledger
    "obr": '<path d="M3 21h18"/><path d="M5 21V10"/><path d="M19 21V10"/><path d="M9 21v-7"/><path d="M15 21v-7"/><path d="m3 10 9-6 9 6"/>',
    # SVAR: shock decomposition — stacked waves
    "svar": '<path d="M3 12h4l3 8 4-16 3 8h4"/>',
    # FRB/US: a gauge / policy dial
    "frb-us": '<path d="M12 6a2 2 0 1 0 4 0a2 2 0 1 0-4 0M4 6h8M16 6h4M6 12a2 2 0 1 0 4 0a2 2 0 1 0-4 0M4 12h2M10 12h10M15 18a2 2 0 1 0 4 0a2 2 0 1 0-4 0M4 18h11M19 18h1"/>',
    # US HANK: distribution — histogram bars
    "us-hank": '<path d="M3 21h18M6 21v-4M10 21V10M14 21V5M18 21v-8"/>',
    # OG-UK: generations over time — hourglass
    "olg": '<path d="M6.5 7h11M6.5 17h11M6 20v-2a6 6 0 1 1 12 0v2a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1zM6 4v2a6 6 0 1 0 12 0V4a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1z"/>',
    # DEFINE-UK: stock-flow loop with a leaf (ecological)
    "define": '<path d="M5 21c.5-4.5 2.5-8 7-10M9 18c6.2 0 10.5-3.3 11-12V4h-4c-9 0-12 4-12 9 0 1 0 3 2 5h3z"/>',
}
META_ICONS = {
    "country": '<circle cx="12" cy="12" r="9"/><path d="M3.6 9h16.8"/><path d="M3.6 15h16.8"/><path d="M12 3a15 15 0 0 1 0 18"/><path d="M12 3a15 15 0 0 0 0 18"/>',
    "trust": '<path d="M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6l-8-3Z"/><path d="m9 12 2 2 4-4"/>',
    "hosted": '<path d="M7 18a4.5 4.5 0 0 1-.5-9 6 6 0 0 1 11.5 1.5A3.8 3.8 0 0 1 17.5 18H7Z"/>',
    "local": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8"/><path d="M12 16v4"/>',
    "cadence": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}

# kind line, country, (trust label, glossary anchor), access, cadence
MODELS = {
    "pe": ("Tax-benefit microsimulation", "UK · US", ("Exact for rules", "exact-for-rules"), "hosted", "Annual"),
    "obr": ("OBR macroeconometric model", "UK", ("Anchored, not validated", "anchored-not-validated"), "hosted", "Quarterly"),
    "svar": ("Bank of England structural VAR", "UK", ("Partial replication", "partial-replication"), "hosted", "Quarterly"),
    "frb-us": ("Fed FRB/US, rebuilt", "US", ("Replicates", "replicates"), "hosted", "Quarterly"),
    "us-hank": ("Two-asset HANK", "US", ("Partial replication", "partial-replication"), "hosted", "Quarterly IRFs"),
    "olg": ("OG-UK overlapping generations", "UK", ("Calibrated", "calibrated-counterfactual"), "local", "Long-run steady state"),
    "define": ("DEFINE-UK ecological stock-flow", "UK", ("Partial replication", "partial-replication"), "local", "Annual to 2037"),
}

# page -> model key; the two reports keep their own kind line
PAGES: dict[str, str] = {}
for key, paper in [("pe", "pe-microsim"), ("obr", "obr-macro"), ("svar", "boe-svar"),
                   ("frb-us", "frb-us"), ("us-hank", None), ("olg", "psl-og"), ("define", "define-uk")]:
    for sub in ("", "methodology/", "validation/", "code/"):
        PAGES[f"{key}/{sub}index.html"] = key
    if paper:
        PAGES[f"papers/{paper}/index.html"] = key
PAGES["reports/us-hank-open-source/index.html"] = "us-hank"
PAGES["reports/define-uk-replication/index.html"] = "define"

HERO_RE = re.compile(r'<section class="hero model-hero[^"]*">.*?</section>', re.S)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
LEDE_RE = re.compile(r'<p class="lede[^"]*"[^>]*>(.*?)</p>', re.S)
KIND_RE = re.compile(r'<p class="eyebrow[^"]*"[^>]*>(.*?)</p>', re.S)


def svg(body: str, size: int) -> str:
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>')


def hero(rel: str, old: str) -> str:
    key = PAGES[rel]
    kind, country, (trust, anchor), access, cadence = MODELS[key]
    title = " ".join(H1_RE.search(old).group(1).split())
    lede_m = LEDE_RE.search(old)
    lede = " ".join(lede_m.group(1).split()) if lede_m else ""
    if rel.startswith("reports/"):
        # a report about the model, not the model: keep its own fact line
        kind = " ".join(KIND_RE.search(old).group(1).split())
        kind = kind[:1].upper() + kind[1:]
    access_label = "Hosted" if access == "hosted" else "Runs locally"
    lines = [
        '<section class="hero model-hero mh">',
        '    <div class="hero-inner mh-inner">',
        f'      <span class="mh-icon" aria-hidden="true">{svg(ICONS[key], 28)}</span>',
        '      <div class="mh-body">',
        f'        <p class="eyebrow mh-kind">{kind}</p>',
        f'        <h1 class="page-title">{title}</h1>',
    ]
    if lede:
        lines.append(f'        <p class="lede">{lede}</p>')
    lines += [
        '        <ul class="mh-meta" aria-label="Model facts">',
        f'          <li class="mh-chip">{svg(META_ICONS["country"], 14)}{country}</li>',
        f'          <li><a class="mh-chip mh-trust" href="/glossary#{anchor}">{svg(META_ICONS["trust"], 14)}{trust}</a></li>',
        f'          <li class="mh-chip mh-{access}">{svg(META_ICONS[access], 14)}{access_label}</li>',
        f'          <li class="mh-chip">{svg(META_ICONS["cadence"], 14)}{cadence}</li>',
        '        </ul>',
        '      </div>',
        '    </div>',
        '  </section>',
    ]
    return "\n".join(lines)


LEVELS = {"weak": "weak", "moderate": "moderate", "strong": "strong", "not applicable": "na"}
LEVEL_RE = re.compile(r'<span class="chip"(?: data-level="[a-z]+")?>(weak|moderate|strong|not applicable)</span>')
LIMITS_RE = re.compile(r'(?:[ \t]*<details class="expander limit".*?</details>\n?)+', re.S)
# The trust label now sits in the hero on every tab; the Overview verdict
# line keeps its sentence and link and drops its duplicate chip.
VERDICT_CHIP_RE = re.compile(r'(<p class="ov-verdict-line">)<a class="chip chip-brand" href="/glossary#[^"]*">[^<]*</a>\s*')


def body(rel: str, source: str) -> str:
    out = LEVEL_RE.sub(lambda m: f'<span class="chip" data-level="{LEVELS[m.group(1)]}">{m.group(1)}</span>', source)
    out = VERDICT_CHIP_RE.sub(r"\1", out)
    if rel.endswith("validation/index.html") and '<div class="limit-list">' not in out:
        out = LIMITS_RE.sub(lambda m: '      <div class="limit-list">\n' + m.group(0) + '      </div>\n', out, count=1)
    return out


def stamp(rel: str, source: str) -> str:
    m = HERO_RE.search(source)
    if not m:
        raise ValueError(f"no model hero in {rel}")
    out = source[: m.start()] + hero(rel, m.group(0)) + source[m.end():]
    out = body(rel, out)
    out = CSS_RE.sub("", out)
    out = re.sub(r'(<link rel="stylesheet" href="/style\.css[^"]*" />)', r"\1\n" + CSS_LINK, out, count=1)
    return out


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for rel in PAGES:
        path = ROOT / rel
        src = path.read_text()
        new = stamp(rel, src)
        if new != src:
            stale.append(rel)
            if not check:
                path.write_text(new)
    if check and stale:
        print("stale model heroes:", *stale, sep="\n  ")
        return 1
    print(f"{'checked' if check else 'stamped'} {len(PAGES)} pages; {len(stale)} changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
