"""Readable chart labels for the generated SVGs (DESIGN.md §6.3).

Every generated chart is drawn in a ``viewBox`` at ``width: 100%``, so text
*inside* the SVG scales with it: an 11 px tick on a 760-unit chart renders at
about 5 px on a 375 px phone, and at 6–7 px in a StepPanel column on a
desktop. The rule (§1.8) is that no label renders below 11 px.

The approach used everywhere on the site: **marks stay in the SVG, words move
to HTML.** A builder still writes ordinary ``<text>`` elements at viewBox
coordinates; ``figure()`` lifts each one out into an absolutely positioned
``<span>`` laid over the SVG at the same point, in percent of the viewBox, so
the span lands where the text was but keeps its CSS size (12 px) at any width.
In-chart prose (class ``vc-note``) leaves the plot altogether and becomes a
line of text under it, and legends are an HTML list (``legend=``), never a
boxed SVG legend.

Labels that cannot all fit at phone width carry ``vc-minor`` (pass
``minor=`` a predicate, or put the class on the ``<text>``): style.css hides
them when the chart's own box is narrower than 520 px (a container query, so
a chart in a narrow StepPanel column thins out too). Keep the first and
last x tick, and every number a reader needs, out of it.

House layout that goes with it (so labels fit at 375 px): y-tick labels sit
inside the plot, left-aligned just above their gridline (``ytick``), not in a
left gutter; the first x tick is left-aligned and the last right-aligned
(``xtick``); a viewBox may start at a non-zero origin to crop unused margins.

Output contract, one block per chart, keyed by ``data-chart``:

    <div class="vc-fig" data-chart="ID">
      <p class="vc-unit">…</p>            optional: the value axis' unit
      <div class="vc-plot">
        <svg class="vchart …" viewBox="0 0 W H" role="img" aria-labelledby="ID-t ID-d">
          <title id="ID-t">…</title><desc id="ID-d">…</desc>  marks only
        </svg>
        <div class="vc-labels" aria-hidden="true"> <span class="vc-t …" style="left:…%;top:…%">…</span> … </div>
      </div>
      <ul class="vc-legend">…</ul>        optional
      <p class="vc-notes">…</p>          optional
    </div><!-- /vc-fig -->

The overlay is ``aria-hidden``: the SVG's ``<title>`` and ``<desc>`` already
state every value a sighted reader would take from the labels.

Stdlib only; every generator imports it from the repository root.
"""

from __future__ import annotations

import re

END = "<!-- /vc-fig -->"
_TEXT = re.compile(r"<text\b([^>]*)>(.*?)</text>", re.DOTALL)
_ATTR = re.compile(r'([\w:-]+)="([^"]*)"')
_SVG_OPEN = re.compile(r"<svg\b([^>]*)>")


def block_re(chart_id: str) -> re.Pattern:
    """Match a chart's committed block, in the new form or the old bare SVG.

    The old form (``<svg class="vchart" data-chart="ID">…</svg>``) is accepted
    so the first regeneration migrates a page; after that only the new form
    exists and ``--check`` is idempotent.
    """
    cid = re.escape(chart_id)
    return re.compile(
        rf'<div class="vc-fig[^"]*" data-chart="{cid}"[^>]*>.*?{re.escape(END)}'
        rf'|<svg class="[^"]*" data-chart="{cid}".*?</svg>',
        re.DOTALL,
    )


_CIRCLE = re.compile(r"<circle\b([^>]*?)\s*/>")


def _dot(m: re.Match) -> str:
    """A dot that stays round when the plot is stretched.

    The plot is drawn with preserveAspectRatio="none" so it can take a usable
    height on a phone; a <circle> would turn into an ellipse. A zero-length
    path with a round cap and a non-scaling stroke is always a circle of
    diameter stroke-width px. Hollow dots (fill="none") become a ring: a dot
    in the stroke colour with a smaller one in the card colour on top.
    """
    a = dict(_ATTR.findall(m.group(1)))
    cx, cy, r = float(a["cx"]), float(a["cy"]), float(a.get("r", 3))
    d = f"M{cx:g} {cy:g}h0"
    if a.get("fill") == "none":
        sw = float(a.get("stroke-width", 1.2))
        return (f'<path class="vc-dotp vc-ring" d="{d}" stroke-width="{2 * r + sw:g}"/>'
                f'<path class="vc-dotp vc-ring-in" d="{d}" stroke-width="{2 * r - sw:g}"/>')
    cls = a.get("class", "")
    return f'<path class="{cls} vc-dotp" d="{d}" stroke-width="{2 * r:g}"/>'


def ytick(x0: float, y: float, label: str, extra: str = "") -> str:
    """A y-axis label inside the plot, 3 px above its gridline at height y."""
    cls = f"vc-tick vc-y {extra}".strip()
    return f'<text class="{cls}" x="{x0:.1f}" y="{y:.1f}">{label}</text>'


def xtick(x: float, y: float, label: str, i: int, last: int, minor: bool = False) -> str:
    """An x-axis label 6 px under the axis at height y: first left-aligned,
    last right-aligned, others centred."""
    anchor = "start" if i == 0 else "end" if i == last else "middle"
    cls = "vc-tick vc-x vc-minor" if minor and 0 < i < last else "vc-tick vc-x"
    return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{label}</text>'


def tick_plan(n: int, wide: int = 7, narrow: int = 3) -> list[tuple[int, bool]]:
    """Which of n evenly spaced x positions get a label, and which are minor.

    At most ``wide`` labels on a wide chart and ``narrow`` (first, last and
    an even spread between) once the minor ones are hidden; a label that would
    sit closer to the last one than the spacing is dropped so they never touch.
    """
    last = n - 1
    if n <= 1:
        return [(0, False)]
    step = max(1, -(-last // (wide - 1)))
    keep = [i for i in range(0, last + 1, step) if last - i >= step or i == 0]
    keep.append(last)
    nstep = max(1, -(-last // (narrow - 1)))
    major = {0, last} | {i for i in keep if i % nstep == 0 and last - i >= nstep}
    return [(i, i not in major) for i in keep]


def _pct(v: float, total: float) -> str:
    return f"{100 * v / total:.2f}".rstrip("0").rstrip(".") + "%"


def endlabel(x: float, y: float, label: str, series: str = "s1", above: bool = True) -> str:
    """A direct label at a line's last point, in place of a legend entry.

    Right-aligned on the point and lifted 6 px above it (``above``) or hung
    6 px below it, in the series' own ink (``s1`` ours, ``s2`` official, ``s3``
    a labelled neutral), so a reader matches label to line without a key.
    Use it only where the label cannot sit on a line: a right-aligned label
    above a line that rises into its end point is always clear of that line;
    one below it is not. Two lines ending close together get a legend.
    """
    pos = "vc-end-up" if above else "vc-end-dn"
    return (f'<text class="vc-end vc-end-{series} {pos}" x="{x:.1f}" y="{y:.1f}" '
            f'text-anchor="end">{label}</text>')


def swatch(kind: str) -> str:
    """Legend swatch: 'ln-s1'/'ln-s2'/'ln-s3' lines, 'sw-b1'… boxes, 'sw-dot2' dots, etc."""
    return f'<span class="vc-sw {kind}" aria-hidden="true"></span>'


def figure(
    svg: str,
    *,
    legend: list[tuple[str, str]] | None = None,
    notes: list[str] | None = None,
    minor=None,
    wrap_class: str = "",
    min_h: int | None = None,
    narrow_table: tuple[list[str], list[list[str]]] | None = None,
    unit: str | None = None,
) -> str:
    """Turn a builder's SVG string into the readable block described above.

    ``legend``: (swatch class, label HTML) pairs rendered as an HTML list.
    ``notes``: extra lines of HTML under the chart (after any vc-note text).
    ``minor``: optional predicate on a label's attribute dict; True marks the
    label ``vc-minor`` (hidden in a narrow chart).
    ``min_h``: the plot's minimum rendered height in px (default 210, in
    style.css), for charts whose rows need more room on a phone.
    ``unit``: what the y values are measured in ("% q/q", "£bn a year"),
    printed once above the plot's top-left corner, the way the BoE and the
    OBR head a chart's value axis. Words come from the chart's own caption.
    ``narrow_table``: (header cells, rows) shown *instead of* the labels marked
    ``vc-minor`` when the chart is narrower than 520 px: the values a phone
    cannot fit on the bars. Only one of the two is ever visible (the same rule
    as the StepPanel's panel/inline pair, DESIGN.md §1.1).
    """
    head = _SVG_OPEN.search(svg)
    if not head:
        raise ValueError("figure() needs an <svg …> string")
    attrs = dict(_ATTR.findall(head.group(1)))
    chart_id = attrs.pop("data-chart", None)
    if not chart_id:
        raise ValueError("figure() needs data-chart on the <svg>")
    mx, my, vw, vh = (float(v) for v in attrs["viewBox"].split())

    spans: list[str] = []
    below: list[str] = []

    def lift(m: re.Match) -> str:
        a = dict(_ATTR.findall(m.group(1)))
        body = m.group(2).strip()
        classes = a.get("class", "").split()
        if "vc-note" in classes:
            below.append(body)
            return ""
        anchor = a.get("text-anchor", "start")
        if anchor == "start":
            classes.append("vc-a-s")
        elif anchor == "middle":
            classes.append("vc-a-m")
        elif anchor == "end":
            classes.append("vc-a-e")
        if minor is not None and minor(a, body) and "vc-minor" not in classes:
            classes.append("vc-minor")
        x, y = float(a.get("x", 0)), float(a.get("y", 0))
        style = f"left:{_pct(x - mx, vw)};top:{_pct(y - my, vh)}"
        if "data-w" in a:
            # A label allowed to wrap inside a fixed share of the plot width
            # (a bar group's label under its group, say).
            classes.append("vc-wrap")
            style += f";width:{_pct(float(a['data-w']), vw)}"
        spans.append(f'<span class="vc-t {" ".join(classes)}" style="{style}">{body}</span>')
        return ""

    marks = _CIRCLE.sub(_dot, _TEXT.sub(lift, svg[head.end():]))
    # Drop blank lines the lifted <text> elements leave behind.
    marks = "\n".join(line for line in marks.split("\n") if line.strip())
    attrs.setdefault("preserveAspectRatio", "none")
    open_attrs = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    parts = [
        f'<div class="vc-fig{(" " + wrap_class) if wrap_class else ""}" data-chart="{chart_id}"'
        + (f' style="--vc-min-h:{min_h}px">' if min_h else ">"),
    ]
    if unit:
        parts.append(f'<p class="vc-unit">{unit}</p>')
    parts += [
        '<div class="vc-plot">',
        f"<svg {open_attrs}>",
        marks,
    ]
    if spans:
        parts.append('<div class="vc-labels" aria-hidden="true">')
        parts.extend(spans)
        parts.append("</div>")
    parts.append("</div>")
    if legend:
        parts.append('<ul class="vc-legend">')
        parts.extend(f"<li>{swatch(kind)}{label}</li>" for kind, label in legend)
        parts.append("</ul>")
    if narrow_table:
        head, body = narrow_table
        parts.append('<div class="vc-narrow table-scroll"><table class="vc-narrow-table">')
        parts.append("<thead><tr>" + "".join(f'<th scope="col">{h}</th>' for h in head) + "</tr></thead>")
        parts.append("<tbody>")
        for row in body:
            parts.append("<tr>" + f'<th scope="row">{row[0]}</th>'
                         + "".join(f'<td class="num">{c}</td>' for c in row[1:]) + "</tr>")
        parts.append("</tbody></table></div>")
    lines = below + list(notes or [])
    if lines:
        parts.append('<p class="vc-notes">' + "<br />".join(lines) + "</p>")
    parts.append(f"</div>{END}")
    return "\n".join(parts)
