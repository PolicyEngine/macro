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

# r13 framing (Vahid: "this platform should be hosting different macro models,
# but have also microsim, how can it be helpful"): the six macro models are
# the product; the microsimulation adds the household layer. Three use cases
# say what the combination does, each read left to right with verbs on the
# arrows, so nothing needs a legend or a hover.
# Facts it encodes (keep them): every join starts or ends at the
# microsimulation; no macro model feeds another; the OG-UK dynamic score is
# local only, with none published; the four incidence joins are experimental.
MACRO = (
    ("obr-macro", "/obr", "OBR emulator", "UK fiscal scenarios"),
    ("boe-svar", "/svar", "BoE SVAR", "UK shocks and forecasts"),
    ("frb-us", "/frb-us", "FRB/US", "US monetary and fiscal shocks"),
    ("us-hank", "/us-hank", "US HANK", "US shocks by household wealth"),
    ("psl-og", "/olg", "OG-UK", "UK long run"),
    ("define-uk", "/define", "DEFINE-UK", "UK climate scenarios"),
)
# key, panel id on /models, icon, title, status, status class, flow steps.
# A step is (kind, text): "in" a plain input, "m" the microsimulation,
# "x" a macro model, "out" the result; "v" is the verb on the next arrow.
USES = (
    ("score", "score", "calculator", "Score a tax reform", "Hosted", "hosted",
     (("calculator", "Microsimulation", "costs the reform"),
      ("landmark", "OBR emulator", "adds GDP feedback"),
      ("check-circle", "Cost + GDP feedback", "UK only"))),
    ("shock", "incidence", "users", "Who gains and loses from a shock", "Experimental", "exp",
     (("activity", "A macro model's path", "BoE SVAR · FRB/US · US HANK · DEFINE-UK"),
      ("calculator", "Microsimulation", "splits it by household"),
      ("check-circle", "Winners and losers", "UK + US"))),
    ("long", "og-join", "hourglass", "Long-run dynamic score", "Local only", "local",
     (("hourglass", "OG-UK", "long-run wages"),
      ("calculator", "Microsimulation", "runs a second time"),
      ("check-circle", "Dynamic score", "UK · none published"))),
)
W, H = 0, 0  # kept for callers that import the old geometry names


def _chip(kind, text):
    if kind == "m":
        return f'<span class="u-node u-micro">{icon(MODEL_ICONS["pe-microsim"], 14)}{text}</span>'
    if kind in ("x", "x2"):
        return f'<span class="u-node u-macro">{text.split("|")[0]}</span>'
    if kind == "out":
        return f'<span class="u-node u-out">{icon("check-circle", 14)}{text}</span>'
    return f'<span class="u-node u-in">{text}</span>'


def _flow(steps):
    """Chips joined by connectors. Each connector travels with the chip after
    it (one .u-seg), so a narrow row wraps at a connector, never mid-chip."""
    out, verb = [], None
    for kind, text in steps:
        if kind == "v":
            verb = text
            continue
        chip = _chip(kind, text)
        if verb is None:
            out.append(chip)
        else:
            out.append(f'<span class="u-seg"><span class="u-arrow" aria-hidden="true">'
                       f'<small>{verb}</small><i></i></span>{chip}</span>')
        verb = None
    return "".join(out)


def _sub(steps):
    for kind, text in steps:
        if kind == "x2":
            return f'<span class="use-sub">{text.split("|")[1]}</span>'
    return ""


def render(page: str) -> str:
    on_models = page == "models/index.html"
    cards = "\n".join(
        f'      <a class="mx" href="{href}"><span class="mx-ic">{icon(MODEL_ICONS[mid], 18)}</span>'
        f'<span class="mx-t"><strong>{name}</strong><small>{job}</small></span></a>'
        for mid, href, name, job in MACRO)
    uses = []
    for key, panel, ic, title, status, cls, nodes in USES:
        href = f"#{panel}" if on_models else f"/models#{panel}"
        steps = "".join(
            f'<li class="vf-step{" vf-micro" if name == "Microsimulation" else ""}{" vf-out" if i == len(nodes) - 1 else ""}">'
            f'<span class="vf-dot">{icon(nic, 14)}</span><span class="vf-t"><strong>{name}</strong><small>{verb}</small></span></li>'
            for i, (nic, name, verb) in enumerate(nodes))
        flow = " → ".join(n for _i, n, _v in nodes)
        uses.append(
            f'      <li class="uc uc-{cls}"><a href="{href}">'
            f'<span class="uc-head"><span class="uc-ic">{icon(ic, 20)}</span><strong class="uc-title">{title}</strong>'
            f'<span class="uc-chip">{status}</span></span>'
            f'<ol class="vf" aria-label="{flow}">{steps}</ol>'
            f'<span class="uc-foot"><span class="uc-go">Details {icon("arrow-right", 14)}</span></span></a></li>')
    macro_tier = (
        '<div class="hub2-tier hub2-macro">\n'
        f'    <p class="hub2-label">{icon("models", 14)}Six macro models: the economy-wide answer</p>\n'
        f'    <div class="mx-grid">\n{cards}\n    </div>\n  </div>'
    ) if False else ""
    note_link = '' if on_models else f'<a class="hub2-foot-go" href="/models#joins">How each link works {icon("arrow-right", 14)}</a>'
    return f'''{OPEN}
<div class="hub2" data-hub2>
  {macro_tier}
  <ol class="hub2-uses uc-grid" aria-label="What the microsimulation adds">
{chr(10).join(uses)}
  </ol>
  <p class="hub2-foot">{icon("info", 16)}<span>Every route ends in the household layer, <a href="/pe">PolicyEngine microsimulation</a> (UK and US). No macro model feeds another, and there is no US macro bridge, so US reforms are scored statically.</span>{note_link}</p>
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
