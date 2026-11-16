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
    ("score", "score", "calculator", "Score a tax reform", "UK · hosted", "hosted",
     (("in", "Reform"), ("v", "is costed by"), ("m", "Microsimulation"), ("v", "sends the cost to"),
      ("x", "OBR emulator"), ("v", "returns"), ("out", "Cost + GDP feedback"))),
    ("shock", "incidence", "users", "Who gains and loses from a macro shock", "UK + US · experimental", "exp",
     (("x2", "Any shock model|BoE SVAR · FRB/US · US HANK · DEFINE-UK"), ("v", "sends its macro path to"),
      ("m", "Microsimulation"), ("v", "shows"), ("out", "Winners and losers"))),
    ("long", "og-join", "hourglass", "Long-run dynamic score", "UK · local only, none published", "local",
     (("x", "OG-UK"), ("v", "sends long-run wages to"), ("m", "Microsimulation"), ("v", "re-scores"),
      ("out", "Dynamic score"))),
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
    for key, panel, ic, title, status, cls, steps in USES:
        href = f"#{panel}" if on_models else f"/models#{panel}"
        text = " → ".join(t.split("|")[0] for k, t in steps if k != "v")
        uses.append(
            f'      <li class="use use-{cls}"><a href="{href}">'
            f'<span class="use-ic">{icon(ic, 18)}</span>'
            f'<span class="use-main"><span class="use-head"><strong>{title}</strong><span class="use-chip">{status}</span></span>'
            f'<span class="use-flow" role="img" aria-label="{text}">{_flow(steps)}</span>{_sub(steps)}</span>'
            f'<span class="use-go" aria-hidden="true">{icon("arrow-right", 16)}</span></a></li>')
    macro_tier = (
        '<div class="hub2-tier hub2-macro">\n'
        f'    <p class="hub2-label">{icon("models", 14)}Six macro models: the economy-wide answer</p>\n'
        f'    <div class="mx-grid">\n{cards}\n    </div>\n  </div>'
    ) if on_models else ""
    note_link = '' if on_models else ' <a href="/models#joins">See how each link works</a>'
    return f'''{OPEN}
<div class="hub2" data-hub2>
  {macro_tier}
  <ol class="hub2-uses" aria-label="What the microsimulation adds">
{chr(10).join(uses)}
  </ol>
  <div class="hub2-tier hub2-micro">
    <span class="hub2-micro-ic">{icon(MODEL_ICONS["pe-microsim"], 20)}</span>
    <p><strong>The household layer: PolicyEngine microsimulation</strong><span>Every household&rsquo;s taxes and benefits, UK and US. <a href="/pe">Open the microsimulation</a></span></p>
  </div>
  <p class="hub2-note"><strong>No macro model feeds another.</strong> No US macro bridge: US reforms are scored statically.{note_link}</p>
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
