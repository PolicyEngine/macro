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
CSS_LINK = '<link rel="stylesheet" href="/models/model-pages.css?v=16" />'
CSS_RE = re.compile(r'<link rel="stylesheet" href="/models/model-pages\.css(?:\?v=\d+)?" />\n?')

sys.path.insert(0, str(ROOT))
import site_nav  # noqa: E402  one icon system: session-wide Lucide set

PUBLIC_ID = {"pe": "pe-microsim", "obr": "obr-macro", "svar": "boe-svar", "frb-us": "frb-us",
             "us-hank": "us-hank", "olg": "psl-og", "define": "define-uk"}
ICONS = {key: site_nav.ICONS[site_nav.MODEL_ICONS[pid]] for key, pid in PUBLIC_ID.items()}
META_ICONS = {
    "country": site_nav.ICONS["globe"],
    "trust": site_nav.ICONS["shield-check"],
    "hosted": '<path d="M7 18a4.5 4.5 0 0 1-.5-9 6 6 0 0 1 11.5 1.5A3.8 3.8 0 0 1 17.5 18H7Z"/>',
    "local": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8"/><path d="M12 16v4"/>',
    "cadence": site_nav.ICONS["clock"],
}

# kind line, country, (trust label, glossary anchor), access, cadence
MODELS = {
    "pe": ("Tax-benefit microsimulation", "UK · US", ("Exact for rules", "exact-for-rules"), "hosted", "Annual"),
    "obr": ("Emulator of the OBR macroeconometric model", "UK", ("Anchored, not validated", "anchored-not-validated"), "hosted", "Quarterly"),
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


LEVELS = {"weak": "weak", "moderate": "moderate", "strong": "strong", "not applicable": "na", "not assessed": "na"}
# The grade lives on the row, so the chip keeps the exact markup the
# registry tests read (<td><span class="chip">level</span></td>).
OLD_CHIP_RE = re.compile(r'<span class="chip" data-level="[a-z]+">')
ROW_RE = re.compile(r'<tr(?: data-level="[a-z]+")?>((?:(?!</tr>).)*?<td><span class="chip">(weak|moderate|strong|not applicable|not assessed)</span></td>)', re.S)
LIMITS_RE = re.compile(r'(?:[ \t]*<details class="expander limit".*?</details>\n?)+', re.S)
# The trust label now sits in the hero on every tab; the Overview verdict
# line keeps its sentence and link and drops its duplicate chip.
VERDICT_CHIP_RE = re.compile(r'(<p class="ov-verdict-line">)<a class="chip chip-brand" href="/glossary#[^"]*">[^<]*</a>\s*')


# Overview verdicts: at most 8 words visible; the full evidence sentence
# stays one click away in an expander, and the link goes to Validation.
SHORT_VERDICT = {
    "obr": "Scores fiscal changes; not a forecaster.",
    "pe": "Exact for rules; costings static, no interval.",
    "svar": "GDP matches the Bank; CPI falls short.",
    "frb-us": "Solver matches pyfrbus; economics not tested.",
    "us-hank": "Parameters match the paper; responses not validated.",
    "olg": "Targets met by construction; no outcome benchmark.",
    "define": "Deltas only, never levels.",
}
VERDICT_RE = re.compile(
    r'<p class="ov-verdict-line"><span>(?P<full>.*?)</span>\s*'
    r'<a class="ov-verdict-link" href="(?P<href>[^"]+)">How far to trust it <span aria-hidden="true">&rarr;</span></a></p>',
    re.S)


def verdict(key: str, out: str) -> str:
    def repl(m: re.Match) -> str:
        return (
            f'<div class="ov-verdict-line"><span class="ov-verdict-short">{SHORT_VERDICT[key]}</span>\n'
            f'      <a class="ov-verdict-link" href="{m.group("href")}">Evidence <span aria-hidden="true">&rarr;</span></a>\n'
            f'      <details class="ov-verdict-more"><summary>Why</summary><p>{m.group("full")}</p></details></div>'
        )
    return VERDICT_RE.sub(repl, out, count=1)


SIGNED_RE = re.compile(r'<span class="stat-value(?: is-(?:gain|loss))?">(\s*(&minus;|−|-|\+)[^<]*)</span>')


def signed(out: str) -> str:
    """Gains teal, losses amber; the printed sign stays (never colour alone)."""
    return SIGNED_RE.sub(
        lambda m: f'<span class="stat-value is-{"gain" if m.group(2) == "+" else "loss"}">{m.group(1)}</span>', out)


def body(rel: str, source: str) -> str:
    out = signed(source)
    out = OLD_CHIP_RE.sub('<span class="chip">', out)
    out = ROW_RE.sub(lambda m: f'<tr data-level="{LEVELS[m.group(2)]}">{m.group(1)}', out)
    out = VERDICT_CHIP_RE.sub(r"\1", out)
    if rel == f"{PAGES[rel]}/index.html":
        out = verdict(PAGES[rel], out)
    # undo the earlier wrapper: .limits groups are styled as lists directly
    out = re.sub(r'      <div class="limit-list">\n((?:[ \t]*<details class="expander limit".*?</details>\n?)+)      </div>\n', r"\1", out, flags=re.S)
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
