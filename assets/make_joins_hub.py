#!/usr/bin/env python3
"""Render the joins hub (r12): microsimulation at the centre, six macro models
around it, three colour-coded flow types. Writes between
<!-- joins-hub:begin --> and <!-- joins-hub:end --> in the pages below.

Facts it encodes (keep them): every join starts or ends at the
microsimulation; no macro model feeds another; the OG-UK dynamic score is
local only, with none published; the four incidence joins are experimental.

Run:  python3 assets/make_joins_hub.py          # rewrite pages
      python3 assets/make_joins_hub.py --check  # fail if stale
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from site_nav import icon, MODEL_ICONS  # noqa: E402

PAGES = {"index.html": "/", "models/index.html": "/models"}
OPEN, CLOSE = "<!-- joins-hub:begin -->", "<!-- joins-hub:end -->"

# key, model id, href, name, flow, status, x%, y%, caption, panel (on /models)
NODES = (
    ("svar", "boe-svar", "/svar", "BoE SVAR", "in", "Experimental", 12.5, 15,
     "Its CPI path drives benefit-uprating incidence.", "incidence"),
    ("frbus", "frb-us", "/frb-us", "FRB/US", "in", "Experimental", 12.5, 38.3,
     "Its wage and hours paths drive employment-income incidence.", "incidence"),
    ("hank", "us-hank", "/us-hank", "US HANK", "in", "Experimental", 12.5, 61.7,
     "Its wage and labour responses drive employment-income incidence.", "incidence"),
    ("define", "define-uk", "/define", "DEFINE-UK", "in", "Experimental", 12.5, 85,
     "Its scenario income deltas drive employment-income incidence.", "incidence"),
    ("obr", "obr-macro", "/obr", "OBR emulator", "out", "Hosted", 87.5, 27,
     "A reform's static cost goes in as an add-factor; GDP feedback comes out. UK only.", "score"),
    ("og", "psl-og", "/olg", "OG-UK", "back", "Local only · none published", 87.5, 73,
     "Long-run wage and rate changes feed a second microsimulation run. None published.", "og-join"),
)
FLOWS = (
    ("out", "Out: reform cost", "macro feedback"),
    ("back", "Back: long-run wages", "dynamic score"),
    ("in", "In: macro path", "who gains and loses"),
)
DEFAULT = "No macro model feeds another."

W, H = 1000, 440
CX, CY = 500, 220


def _path(x, y, flow):
    px, py = x / 100 * W, y / 100 * H
    if flow == "in":   # node right edge -> centre left edge
        sx, sy, ex, ey = px + 105, py, CX - 120, CY + (py - CY) * 0.18
    elif flow == "out":  # centre right edge -> node left edge
        sx, sy, ex, ey = CX + 120, CY - 18, px - 112, py
    else:  # back: node left edge -> centre right edge
        sx, sy, ex, ey = px - 105, py, CX + 124, CY + 18
    mx = (sx + ex) / 2
    return f"M{sx:.0f} {sy:.0f} C{mx:.0f} {sy:.0f} {mx:.0f} {ey:.0f} {ex:.0f} {ey:.0f}"


def render(page: str) -> str:
    on_models = page == "models/index.html"
    paths = "\n".join(
        f'    <path class="hub-edge hub-{flow}" data-k="{k}" d="{_path(x, y, flow)}" marker-end="url(#hub-arrow-{flow})"/>'
        for k, _m, _h, _n, flow, _s, x, y, _c, _p in NODES)
    markers = "".join(
        f'<marker id="hub-arrow-{f}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path class="hub-head hub-{f}" d="M0 0 10 5 0 10z"/></marker>' for f, _a, _b in FLOWS)
    nodes = []
    for k, mid, href, name, flow, status, x, y, cap, panel in NODES:
        extra = f' data-panel="{panel}"' if on_models else ""
        nodes.append(
            f'  <li class="hub-node hub-{flow}" data-k="{k}" style="--x:{x}%;--y:{y}%">\n'
            f'    <button type="button" class="hub-btn" data-k="{k}" data-cap="{cap}" data-href="{href}"{extra} aria-describedby="hub-cap">'
            f'<span class="hub-ic">{icon(MODEL_ICONS[mid], 18)}</span>'
            f'<span class="hub-txt"><strong>{name}</strong><span class="hub-chip hub-chip-{status.split()[0].lower()}">{status}</span></span></button>\n'
            f'    <p class="hub-mcap">{cap}</p>\n  </li>')
    legend = "".join(
        f'<li class="hub-{f}"><span class="hub-swatch" aria-hidden="true"></span>{a} {icon("arrow-right", 12)} {b}</li>'
        for f, a, b in FLOWS)
    return f'''{OPEN}
<div class="hub" data-hub>
  <ul class="hub-legend" aria-label="Flow types">{legend}</ul>
  <div class="hub-stage">
  <svg class="hub-svg" viewBox="0 0 {W} {H}" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <defs>{markers}</defs>
{paths}
  </svg>
  <div class="hub-core" style="--x:50%;--y:50%"><a href="/pe">{icon(MODEL_ICONS["pe-microsim"], 22)}<span><strong>Microsimulation</strong><small>UK + US &middot; the core</small></span></a></div>
  <ul class="hub-nodes">
{chr(10).join(nodes)}
  </ul>
  </div>
  <p class="hub-cap" id="hub-cap" aria-live="polite" data-default="{DEFAULT}">{icon("info", 16)}<span>{DEFAULT}</span></p>
  <p class="hub-note"><strong>No US macro bridge:</strong> US reforms are scored statically.{'' if on_models else ' <a href="/models#joins">See every join</a>'}</p>
</div>
{CLOSE}'''


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for page in PAGES:
        path = ROOT / page
        src = path.read_text()
        a, b = src.index(OPEN), src.index(CLOSE) + len(CLOSE)
        new = src[:a] + render(page) + src[b:]
        if new != src:
            stale.append(page)
            if not check:
                path.write_text(new)
    if check and stale:
        print("FAIL joins hub stale in: " + ", ".join(stale) + "; run python3 assets/make_joins_hub.py", file=sys.stderr)
        return 1
    print("OK — joins hub current" if check else f"wrote {', '.join(stale) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
