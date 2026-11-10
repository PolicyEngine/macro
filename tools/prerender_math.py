"""Pre-render the methodology pages' TeX to static MathJax CHTML.

The methodology tabs used to load MathJax in the browser (tex-chtml-full.js,
1.3 MB / 303 KB gzipped) to typeset about 170 short equations. This script
does the typesetting once, at authoring time, with the same MathJax release
(mathjax-full 3.2.2, the version that was vendored) and writes the result
into the HTML. A page then needs only vendor/mathjax/chtml.css and the
MathJax woff fonts it already used; no script.

Authoring: write TeX in a page as usual, ``\\( ... \\)`` inline or
``\\[ ... \\]`` display, then run ``python3 tools/prerender_math.py``. Each
equation becomes ``<mjx-container ... data-tex="..." data-mjx="...">``: the
TeX source stays on the element (``data-tex``, the source of truth for
re-rendering), a hidden MathML copy (``mjx-assistive-mml``) is what screen
readers read, and ``data-mjx`` is a hash of TeX + output. To edit an
equation, edit its ``data-tex`` (or replace the whole element by fresh
``\\( ... \\)``) and rerun.

``--check`` re-renders every equation and the stylesheet and fails if any
page or chtml.css differs, or if any raw ``\\(``/``\\[`` is left. It needs
node and mathjax-full: ``npm ci --prefix tools`` (tools/package.json), or
``MATHJAX_FULL=/path/to/node_modules/mathjax-full``; ``NODE`` overrides the
node binary. ``verify_static`` is the node-free part (hashes and leftovers),
which tests/test_prerendered_math.py runs on every CI build.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
CSS = ROOT / "vendor" / "mathjax" / "chtml.css"
PAGES = [
    ROOT / f"{model}/methodology/index.html"
    for model in ("obr", "svar", "frb-us", "us-hank", "olg", "define")
]
# Inter's x-height over MathJax TeX's (0.442 em): the browser runtime set the
# equations at font-size 123.6% on these pages.
SCALE = 1.236

CONTAINER = re.compile(r"<mjx-container\b[^>]*\bdata-tex=\"[^\"]*\"[^>]*>.*?</mjx-container>", re.S)
RAW = re.compile(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", re.S)
SKIP = re.compile(r"<(script|style|pre|code|textarea|noscript)\b.*?</\1>|<head>.*?</head>|<!--.*?-->", re.S | re.I)
ATTR = lambda name: re.compile(rf'\s{name}="([^"]*)"')  # noqa: E731
CSS_LINK = re.compile(r'\n?<link rel="stylesheet" href="/vendor/mathjax/chtml\.css(?:\?v=[0-9a-f]+)?" />')
STYLE_LINK = re.compile(r'(<link rel="stylesheet" href="/style\.css\?v=\d+" />)')
RUNTIME_CONFIG = re.compile(r"<script>\s*/\* Self-hosted MathJax.*?</script>\n?", re.S)


def digest(tex: str, display: bool, rendered: str) -> str:
    return hashlib.sha256(f"{int(display)}\0{tex}\0{rendered}".encode()).hexdigest()[:16]


def strip_marks(container: str) -> str:
    """The MathJax output with the two attributes this script adds removed."""
    return re.sub(r' data-(?:tex|mjx)="[^"]*"', "", container, count=2)


def skipped(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in SKIP.finditer(text)]


def inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def find_math(text: str) -> list[dict]:
    """Every equation in page order: raw TeX or an already rendered element."""
    spans = skipped(text)
    found = []
    for m in CONTAINER.finditer(text):
        if inside(m.start(), spans):
            continue
        tag = text[m.start(): text.index(">", m.start())]
        tex = html.unescape(ATTR("data-tex").search(tag).group(1))
        found.append({"span": m.span(), "tex": tex, "display": ' display="true"' in tag, "old": m.group(0)})
    taken = [f["span"] for f in found]
    for m in RAW.finditer(text):
        if inside(m.start(), spans) or inside(m.start(), taken):
            continue
        body = m.group(1) if m.group(1) is not None else m.group(2)
        if "<" in body or ">" in body:
            raise ValueError(f"TeX contains markup near offset {m.start()}: {body[:60]!r}")
        found.append({"span": m.span(), "tex": html.unescape(body), "display": m.group(2) is not None, "old": None})
    return sorted(found, key=lambda f: f["span"][0])


def node_render(items: list[dict]) -> dict:
    node = os.environ.get("NODE") or shutil.which("node")
    mj = os.environ.get("MATHJAX_FULL") or str(TOOLS / "node_modules" / "mathjax-full")
    if not node or not Path(mj, "js", "mathjax.js").exists():
        raise RuntimeError(
            "needs node and mathjax-full 3.2.2: run `npm ci --prefix tools`, or set NODE / MATHJAX_FULL"
        )
    payload = json.dumps({"items": [{"tex": i["tex"], "display": i["display"]} for i in items], "scale": SCALE})
    out = subprocess.run(
        [node, str(TOOLS / "prerender_math.cjs")], input=payload, capture_output=True, text=True,
        env={**os.environ, "MATHJAX_FULL": mj}, check=True,
    )
    result = json.loads(out.stdout)
    if result["version"] != "3.2.2":
        raise RuntimeError(f"mathjax-full {result['version']} found; the pages are pinned to 3.2.2")
    return result


def mark(rendered: str, tex: str, display: bool) -> str:
    assert rendered.startswith("<mjx-container ")
    attrs = f'data-tex="{html.escape(tex, quote=True)}" data-mjx="{digest(tex, display, rendered)}"'
    return rendered.replace("<mjx-container ", f"<mjx-container {attrs} ", 1)


def build() -> tuple[dict[Path, str], str]:
    """Rendered text of every page and the stylesheet, without writing."""
    texts = {p: p.read_text() for p in PAGES}
    found = {p: find_math(t) for p, t in texts.items()}
    flat = [m for p in PAGES for m in found[p]]
    result = node_render(flat)
    css = result["css"].strip() + "\n"
    css_hash = hashlib.sha256(css.encode()).hexdigest()[:10]
    link = f'<link rel="stylesheet" href="/vendor/mathjax/chtml.css?v={css_hash}" />'
    rendered = iter(result["items"])
    out = {}
    for p in PAGES:
        text, pieces, last = texts[p], [], 0
        for m in found[p]:
            a, b = m["span"]
            pieces += [text[last:a], mark(next(rendered), m["tex"], m["display"])]
            last = b
        text = "".join(pieces) + text[last:]
        text = RUNTIME_CONFIG.sub("", text)
        text = CSS_LINK.sub("", text)
        if found[p]:
            text, n = STYLE_LINK.subn(lambda s: f"{s.group(1)}\n{link}", text, count=1)
            if n != 1:
                raise ValueError(f"no style.css link in {p.relative_to(ROOT)}")
        out[p] = text
    header = (
        "/* MathJax 3.2.2 CHTML styles for the pre-rendered equations.\n"
        "   Generated by tools/prerender_math.py; do not edit. */\n"
    )
    return out, header + css


def verify_static(paths: list[Path] | None = None) -> list[str]:
    """Problems that need no MathJax to see: raw TeX left, edited output."""
    problems = []
    for p in paths or PAGES:
        text = p.read_text()
        rel = p.relative_to(ROOT)
        for m in find_math(text):
            if m["old"] is None:
                problems.append(f"{rel}: raw TeX not pre-rendered: {m['tex'][:60]!r}")
                continue
            tag = m["old"][: m["old"].index(">")]
            stored = ATTR("data-mjx").search(tag)
            if not stored or stored.group(1) != digest(m["tex"], m["display"], strip_marks(m["old"])):
                problems.append(f"{rel}: equation edited without re-rendering: {m['tex'][:60]!r}")
        if "tex-chtml" in text or "window.MathJax" in text:
            problems.append(f"{rel}: still configures the MathJax runtime")
        if find_math(text) and not CSS_LINK.search(text):
            problems.append(f"{rel}: equations but no /vendor/mathjax/chtml.css link")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if any page or chtml.css is stale")
    args = parser.parse_args()
    pages, css = build()
    stale = [p for p, t in pages.items() if t != p.read_text()]
    if not CSS.exists() or CSS.read_text() != css:
        stale.append(CSS)
    if args.check:
        problems = verify_static() + [f"{p.relative_to(ROOT)} is stale" for p in stale]
        for line in problems:
            print(line, file=sys.stderr)
        count = sum(len(find_math(p.read_text())) for p in PAGES)
        if not problems:
            print(f"OK — {count} equations on {len(PAGES)} pages match their TeX; chtml.css current")
        return 1 if problems else 0
    for p in stale:
        (CSS if p == CSS else p).write_text(css if p == CSS else pages[p])
    print(f"wrote {len(stale)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
