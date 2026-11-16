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

import html as html_lib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_LINK = '<link rel="stylesheet" href="/models/model-pages.css?v=22" />'
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
    "frb-us": ("Fed FRB/US, rebuilt", "US", ("Replicates one published shock", "replicates"), "hosted", "Quarterly"),
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
    "obr": "Scores income tax and NICs changes; not a forecaster.",
    "pe": "Exact for rules; costings static, no interval.",
    "svar": "GDP variance share consistent with the paper; no forecast skill.",
    "frb-us": "Solver matches the Fed&rsquo;s code; economic checks weak.",
    "us-hank": "Parameters match the paper; responses not validated.",
    "olg": "Targets met by construction; no outcome benchmark.",
    "define": "Deltas only, never levels.",
}
VERDICT_RE = re.compile(
    r'<p class="ov-verdict-line"><span>(?P<full>.*?)</span>\s*'
    r'<a class="ov-verdict-link" href="(?P<href>[^"]+)">How far to trust it <span aria-hidden="true">&rarr;</span></a></p>',
    re.S)


WHY_RE = re.compile(r'<details class="ov-verdict-more"><summary>Why</summary><p>(.*?)</p></details>', re.S)


def verdict(key: str, out: str) -> str:
    out = WHY_RE.sub(r'<span class="ov-verdict-why">\1</span>', out)
    def repl(m: re.Match) -> str:
        return (
            f'<div class="ov-verdict-line"><span class="ov-verdict-short">{SHORT_VERDICT[key]}</span>\n'
            f'      <a class="ov-verdict-link" href="{m.group("href")}">Evidence <span aria-hidden="true">&rarr;</span></a>\n'
            f'      <details class="ov-verdict-more"><summary>Why</summary><p>{m.group("full")}</p></details></div>'
        )
    return VERDICT_RE.sub(repl, out, count=1)


SIGNED_RE = re.compile(r'<span class="stat-value(?: is-(?:gain|loss))?">(\s*(&minus;|−|-|\+)[^<]*)</span>')


# Tiles where "up" is not a gain (unemployment, prices, emissions) stay uncoloured.
NEUTRAL_LABEL = re.compile(r"unemploy|inflation|\bPCE\b|\bCPI\b|emission|price", re.I)


def signed(out: str) -> str:
    """Gains teal, losses amber; the printed sign stays (never colour alone)."""
    def sub(m: re.Match) -> str:
        start = out.rfind('<div class="stat', 0, m.start())
        if NEUTRAL_LABEL.search(re.sub(r"<[^>]+>", " ", out[start:m.start()] + out[m.end():m.end() + 300].split("</div>")[0])):
            return f'<span class="stat-value">{m.group(1)}</span>'
        return f'<span class="stat-value is-{"gain" if m.group(2) == "+" else "loss"}">{m.group(1)}</span>'
    return SIGNED_RE.sub(sub, out)


VOID_TAGS = {"br", "img", "input", "meta", "link", "hr", "wbr", "source", "col", "area", "base", "param", "track"}
TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)([^>]*?)(/?)>")


def _children(html: str, start: int) -> tuple[list[tuple[int, int, str]], int, int]:
    """Top-level child element spans of the element whose open tag starts at start.
    Returns (children [(s, e, open_tag)], content_start, close_tag_start)."""
    m = TAG_RE.match(html, start)
    pos, depth, kids, cur = m.end(), 0, [], None
    content_start = pos
    for t in TAG_RE.finditer(html, pos):
        closing, name, selfclose = t.group(1), t.group(2).lower(), t.group(4)
        if name in VOID_TAGS or selfclose:
            if depth == 0:
                kids.append((t.start(), t.end(), t.group(0)))
            continue
        if not closing:
            if depth == 0:
                cur = (t.start(), t.group(0))
            depth += 1
        else:
            if depth == 0:
                return kids, content_start, t.start()
            depth -= 1
            if depth == 0:
                kids.append((cur[0], t.end(), cur[1]))
    raise ValueError("unbalanced")


def _summarise(chunk: str) -> str:
    parts = []
    n_tab = chunk.count("<table")
    n_fig = len(re.findall(r'<figure|class="vfig', chunk))
    n_code = chunk.count('class="codeblock"')
    n_list = len(re.findall(r"<li\b", chunk))
    n_p = len(re.findall(r"<p\b", chunk))
    if n_tab: parts.append("table" if n_tab == 1 else f"{n_tab} tables")
    if n_fig: parts.append("chart" if n_fig == 1 else f"{n_fig} charts")
    if n_code: parts.append("code" if n_code == 1 else f"{n_code} snippets")
    if n_list: parts.append(f"{n_list} points")
    elif n_p: parts.append("notes")
    return ", ".join(parts) if parts else "notes"


def fold_steps(rel: str, html: str) -> str:
    """Headline only by default: in each open step keep the head, the lead
    line and one visual; supporting detail goes behind one expander."""
    code_page = rel.endswith("code/index.html")
    out, i = [], 0
    for m in re.finditer(r'<div class="meth-step"(?: id="[^"]*")? data-step="\d+">', html):
        if m.start() < i:
            continue
        kids, cs, ce = _children(html, m.start())
        keep, rest = [], []
        lead = visual = False
        for k in kids:
            frag = html[k[0]:k[1]]
            tag = k[2]
            if "meth-step-head" in tag or 'class="more' in tag or 'class="xp' in tag:
                keep.append(k); continue
            if not lead and tag.startswith("<p"):
                keep.append(k); lead = True; continue
            if code_page and 'class="codeblock"' in tag:
                keep.append(k); continue
            if not visual and (tag.startswith("<figure") or "vfig" in tag or "pipeline" in tag or "meth-map" in tag):
                keep.append(k); visual = True; continue
            rest.append(k)
        details = [k for k in rest if html[k[0]:k[1]].lstrip().startswith("<details")]
        loose = [k for k in rest if k not in details]
        if not loose:
            continue  # already headline + expanders
        loose_html = "\n        ".join(html[k[0]:k[1]] for k in loose)
        parts = [html[k[0]:k[1]] for k in keep]
        if len(details) == 1:
            d = html[details[0][0]:details[0][1]]
            sm = re.search(r"</summary>", d)
            d = d[:sm.end()] + "\n        " + loose_html + d[sm.end():]
            parts.append(d)
        else:
            parts.append(site_nav.expander("list", "More detail", _summarise(loose_html), loose_html))
            parts += [html[k[0]:k[1]] for k in details]
        out.append(html[i:cs]); out.append("\n        " + "\n        ".join(parts) + "\n      "); i = ce
    out.append(html[i:])
    return "".join(out)


MORE_OPEN = re.compile(r'<details class="more"><summary><span class="more-title">(.*?)</span><span class="more-sub">(.*?)</span></summary>', re.S)
DETAILS_TAG = re.compile(r"<(/?)details\b[^>]*>")


ABOUT_OPEN = re.compile(r'<details class="about"(?: id="[^"]*")?>\s*<summary(?: [^>]*)?>(.*?)</summary>', re.S)


def _close(html: str, start: int):
    depth = 1
    for t in DETAILS_TAG.finditer(html, start):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return t
    raise ValueError("unbalanced details")


CARD_OPEN = re.compile(r'<details class="expander">\s*<summary>Model card <span class="expander-meta">(.*?)</span></summary>', re.S)


def to_shared_expander(html: str) -> str:
    """Our r12 'more' folds and the plain 'About this step' folds become the
    shell's one expander (.xp), so every tab has a single expander style."""
    while True:
        m = ABOUT_OPEN.search(html)
        if not m:
            break
        end = _close(html, m.end())
        body = html[m.end():end.start()].strip("\n")
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip() or "More detail"
        html = html[:m.start()] + site_nav.expander("list", title, _summarise(body), body) + html[end.end():]
    m = CARD_OPEN.search(html)
    if m:
        end = _close(html, m.end())
        body = html[m.end():end.start()].strip("\n")
        html = html[:m.start()] + site_nav.expander("file-text", "Model card", m.group(1).strip(), body) + html[end.end():]
    while True:
        m = MORE_OPEN.search(html)
        if not m:
            return html
        depth, end = 1, None
        for t in DETAILS_TAG.finditer(html, m.end()):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                end = t
                break
        body = html[m.end():end.start()].strip("\n")
        html = html[:m.start()] + site_nav.expander("list", m.group(1), m.group(2), body) + html[end.end():]


def _txt(x: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", x)).strip()


def _about_name(body: str) -> tuple[str, str]:
    """Name an 'About this step' fold after its own content: the step's section
    title (or first sub-heading) and the next one or two sub-headings."""
    pool = [_txt(x) for x in re.findall(r'meth-sec-title">(.*?)</div>', body)]
    pool += [_txt(x) for x in re.findall(r"<h4[^>]*>(.*?)</h4>", body)]
    pool += [_txt(x) for x in re.findall(r"<p><strong>(.*?)</strong>", body)]
    if not pool:
        return "", ""
    title, rest, summ = pool[0].rstrip(".:"), pool[1:], ""
    for item in rest:
        cand = (summ + " · " if summ else "") + item.rstrip(".:")
        if len(cand) > 60:
            break
        summ = cand
    if not summ:
        plain = [l.strip() for l in _txt(re.sub(r"<(svg|mjx-container|pre|table)\b.*?</\1>", "", body, flags=re.S)).split("\n") if l.strip()]
        plain = [l for l in plain if l.rstrip(".:") != title]
        if plain:
            summ = plain[0] if len(plain[0]) <= 60 else plain[0][:57].rsplit(" ", 1)[0] + "…"
    return title, summ


ABOUT_XP = re.compile(r'(<span class="xp-t"><strong>)About this step(</strong><small>)(.*?)(</small>.*?<div class="xp-body">)(.*?)(\n  </div>\n</details>)', re.S)


def name_about(html: str) -> str:
    def sub(m: re.Match) -> str:
        title, summ = _about_name(m.group(5))
        if not title:
            return m.group(0)
        return m.group(1) + html_lib.escape(title, quote=False) + m.group(2) + html_lib.escape(summ, quote=False) + m.group(4) + m.group(5) + m.group(6)
    return ABOUT_XP.sub(sub, html)


def body(rel: str, source: str) -> str:
    out = signed(source)
    out = to_shared_expander(out)
    if "/methodology/" in rel or "/validation/" in rel or rel.endswith("code/index.html"):
        out = fold_steps(rel, out)
    if "/methodology/" in rel:
        out = name_about(out)
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
    # After the shell stylesheet and, on methodology tabs, after the MathJax
    # sheet that tools/prerender_math.py pins directly under style.css.
    anchor = (r'(<link rel="stylesheet" href="/vendor/mathjax/chtml\.css[^"]*" />)'
              if "/vendor/mathjax/chtml.css" in out else r'(<link rel="stylesheet" href="/style\.css[^"]*" />)')
    out = re.sub(anchor, r"\1\n" + CSS_LINK, out, count=1)
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
