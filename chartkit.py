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
      <p class="vc-source">Source: …</p> optional: where the numbers come from
    </div><!-- /vc-fig -->

The overlay is ``aria-hidden``: the SVG's ``<title>`` and ``<desc>`` already
state every value a sighted reader would take from the labels.

Stdlib only; every generator imports it from the repository root.
"""

from __future__ import annotations

import json
import re

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


_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_INFO_ICON = ('<svg class="vc-src-ic" viewBox="0 0 24 24" width="14" height="14" '
              'style="width:14px;height:14px;flex:0 0 14px" aria-hidden="true" fill="none" '
              'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
              'stroke-linejoin="round"><circle cx="12" cy="12" r="10"/>'
              '<path d="M12 16v-4"/><path d="M12 8h.01"/></svg>')


def short_date(iso: str) -> str:
    """'2026-11-12' -> '12 Nov 2026'; anything else is returned unchanged."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso.strip())
    if not m:
        return iso
    return f"{int(m.group(3))} {_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"


def short_source(source: str) -> str:
    """Publishers and dates only, derived from a full source line.

    Each ";"-separated part keeps its first comma clause, with tags, file
    names and paths dropped and ISO dates written out. The full line is kept
    verbatim in the "Source details" expander, so nothing is lost.
    """
    text = re.sub(r"<[^>]+>", "", source)
    parts = []
    for part in text.split(";"):
        clause = part.split(",")[0].split(":")[0]
        words = [w for w in clause.split()
                 if not ("/" in w and ("." in w or w.count("/") > 1)) and not re.search(r"\.(json|csv|txt|TXT|py)$", w)
                 and w not in ("→", "from", "stored", "in")]
        clause = re.sub(r"\d{4}-\d{2}-\d{2}", lambda m: short_date(m.group(0)), " ".join(words)).strip()
        if clause and clause.lower() not in ("archived round", "outturns the data store"):
            parts.append(clause)
    return " · ".join(parts) or "see details"


def source_block(source: str, short: str | None = None) -> str:
    """One short muted source line, then the full provenance behind a toggle.

    The full line is printed exactly as before (``<p class="vc-source">Source:
    …</p>``) inside the expander, so provenance checks that match it still do.
    """
    return (
        f'<p class="vc-src-line">{_INFO_ICON}<span style="min-width:0;flex:1">Source: {short or short_source(source)}</span></p>\n'
        '<details class="vc-src"><summary>Source details</summary>\n'
        f'<p class="vc-source">Source: {source}</p>\n</details>'
    )


_DETAILS_WRAP = re.compile(r"^\s*<details[^>]*>\s*<summary>.*?</summary>\s*(.*?)\s*</details>\s*$", re.S)
_SRC_FOOT = re.compile(
    r'(<p class="vc-src-line">.*?</p>)\n<details class="vc-src"><summary>Source details</summary>\n'
    r'(<p class="vc-source">.*?</p>)\n</details>', re.S)


def attach_table(fig: str, table: str, label: str = "Numbers by quarter") -> str:
    """Fold a chart's data table into its source footer.

    A chart with both a "Source details" disclosure and a separate data-table
    expander gets one footer row instead: the short source line on the left
    and one "Details" disclosure on the right, opening to two sections, the
    numbers and the full sources. ``table`` is the table markup, or a whole
    ``<details>`` expander, whose wrapper and summary are dropped. The full
    ``<p class="vc-source">Source: …</p>`` line is kept verbatim.
    """
    m = _DETAILS_WRAP.match(table)
    inner = m.group(1) if m else table.strip()
    foot = _SRC_FOOT.search(fig)
    if not foot:
        raise ValueError("attach_table() needs a figure() block with a source")
    merged = (
        '<div class="vc-foot">\n'
        f"{foot.group(1)}\n"
        '<details class="vc-src vc-more"><summary>Details</summary>\n'
        '<div class="vc-more-body">\n'
        f'<section class="vc-more-sec"><p class="vc-more-h">{label}</p>\n{inner}\n</section>\n'
        f'<section class="vc-more-sec"><p class="vc-more-h">Sources</p>\n{foot.group(2)}\n</section>\n'
        "</div>\n</details>\n</div>"
    )
    return fig[:foot.start()] + merged + fig[foot.end():]


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
    keep_ratio: bool = False,
    source: str | None = None,
    source_short: str | None = None,
    y_gutter: bool = False,
) -> str:
    """Turn a builder's SVG string into the readable block described above.

    ``legend``: (swatch class, label HTML) pairs rendered as an HTML list.
    ``notes``: extra lines of HTML under the chart (after any vc-note text).
    ``minor``: optional predicate on a label's attribute dict; True marks the
    label ``vc-minor`` (hidden in a narrow chart).
    ``min_h``: the plot's minimum rendered height in px (default 210, in
    style.css), for charts whose rows need more room on a phone.
    ``keep_ratio``: opt this chart out of the tall-plot rule (style.css
    §6.10: a plot ≥ 640 px wide is drawn at least 340-380 px tall); for a
    chart whose shape must not stretch (a strip, a sparkline).
    ``unit``: what the y values are measured in ("% q/q", "£bn a year"),
    printed once above the plot's top-left corner, the way the BoE and the
    OBR head a chart's value axis. Words come from the chart's own caption.
    ``source``: one line of HTML naming where the numbers come from (the
    committed file or the publisher), printed under the chart after any notes,
    the way the BoE and the OBR foot a chart. "Source: " is added here.
    ``y_gutter``: draw the y labels in a gutter left of the plot, right-aligned
    and centred on their gridline, instead of inside the plot above it. For
    fans and line charts whose data start at the left edge, where an inside
    label would sit on the first points of the line (style.css .vc-ygutter).
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
    if keep_ratio:
        attrs["class"] = (attrs.get("class", "") + " vc-keep-ratio").strip()
    open_attrs = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    if y_gutter:
        wrap_class = (wrap_class + " vc-ygutter").strip()
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
    if source:
        parts.append(source_block(source, source_short))
    parts.append(f"</div>{END}")
    return "\n".join(parts)


# ---------------------------------------------------------------- Plotly
# Interactive versions of the charts, drawn by the vendored plotly.js basic
# build (vendor/plotly/) through economy/pe-plot.js. The figures are plain
# Plotly JSON written here with the standard library: no plotly, pandas or
# numpy, so every generator keeps running on a bare Python. Colours are CSS
# tokens ("var(--series-ours)", optionally "/alpha"); the loader resolves them
# for the current light or dark scheme. The SVG stays in the page as the
# no-JS, print and screen-reader version.

PLOTLY_JS = "/vendor/plotly/plotly-basic-2.35.2.min.js"
PLOT_LOADER = "/economy/pe-plot.js"


def plot_scripts() -> str:
    """The two script tags a page with an interactive chart loads, once."""
    return (f'<script src="{PLOTLY_JS}" defer></script>\n'
            f'<script src="{PLOT_LOADER}" defer></script>')


def period_date(period: str) -> str:
    """An x position for a period: quarters and months at their middle."""
    m = re.fullmatch(r"(\d{4})Q([1-4])", period)
    if m:
        return f"{m.group(1)}-{3 * int(m.group(2)) - 1:02d}-15"
    if re.fullmatch(r"\d{4}-\d{2}", period):
        return f"{period}-15"
    return period


def _r(v):
    return None if v is None else round(float(v), 4)


def plot_line(points: list[tuple[str, float | None]], name: str, color: str, *,
              dash: str = "solid", width: float = 2.25, unit: str = "%",
              digits: int = 1, markers: bool = False) -> dict:
    """A line (or dots) through (period, value) pairs; None breaks the line."""
    return {
        "type": "scatter", "mode": "markers" if markers else "lines", "name": name,
        "x": [period_date(p) if p else None for p, _ in points],
        "y": [_r(v) for _, v in points],
        "customdata": [p for p, _ in points],
        "line": {"color": color, "width": width, "dash": dash, "shape": "linear"},
        "marker": {"color": color, "size": 6},
        "connectgaps": False,
        "hovertemplate": f"%{{customdata}}<br><b>%{{y:.{digits}f}}{unit}</b><extra>{name}</extra>",
    }


def plot_band(rows: list[tuple[str, float, float]], name: str, color: str,
              unit: str = "%") -> list[dict]:
    """A filled band from (period, low, high): a hidden lower edge, then the upper."""
    xs = [period_date(p) for p, _, _ in rows]
    low = {"type": "scatter", "mode": "lines", "x": xs, "y": [_r(lo) for _, lo, _ in rows],
           "line": {"width": 0, "color": color}, "hoverinfo": "skip", "showlegend": False}
    high = {"type": "scatter", "mode": "lines", "name": name, "x": xs,
            "y": [_r(hi) for _, _, hi in rows], "fill": "tonexty", "fillcolor": color,
            "line": {"width": 0, "color": color},
            "customdata": [[p, _r(lo), _r(hi)] for p, lo, hi in rows],
            "hovertemplate": f"{name}: %{{customdata[1]:.2f}}{unit} to %{{customdata[2]:.2f}}{unit}<extra></extra>"}
    return [low, high]


def plot_last(period: str, value: float, color: str, unit: str = "%", digits: int = 1,
              position: str = "middle right") -> dict:
    """The emphasised last point, labelled with its value and period."""
    return {"type": "scatter", "mode": "markers+text", "x": [period_date(period)], "y": [_r(value)],
            "text": [f"{value:.{digits}f}{unit}"], "textposition": position, "cliponaxis": False,
            "textfont": {"color": "var(--text-strong)", "size": 12},
            "marker": {"color": color, "size": 9, "line": {"color": "var(--surface-card)", "width": 2}},
            "customdata": [period], "showlegend": False,
            "hovertemplate": f"%{{customdata}}<br><b>%{{y:.{digits}f}}{unit}</b><extra>Latest</extra>"}


def _date_span(first: str, last: str, pad: float = 0.04) -> list[str]:
    """An x range from the first to the last period, with a little room each side."""
    import datetime as _dt
    a = _dt.date.fromisoformat(period_date(first))
    b = _dt.date.fromisoformat(period_date(last))
    d = _dt.timedelta(days=max(10, round((b - a).days * pad)))
    return [(a - d).isoformat(), (b + d).isoformat()]


def _x_ticks(x_span: tuple[str, str] | None) -> dict:
    """Yearly ticks; quarterly ones ('2026Q3') when the window is under two years."""
    if x_span:
        a, b = (period_date(p)[:7] for p in x_span)
        months = (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])
        if months < 24:
            return {"dtick": "M3", "tickformat": "%YQ%q", "tick0": "2000-02-15"}
    return {"dtick": "M12", "tickformat": "%Y"}


def plot_spec(traces: list[dict], *, unit: str = "%", height: int = 260,
              zero: bool = False, target: float | None = None, target_label: str = "",
              edge: str | None = None, y_range: tuple[float, float] | None = None,
              x_span: tuple[str, str] | None = None, hovermode: str = "closest",
              y_dtick: float | None = None) -> dict:
    """House-style layout: Inter, light grid, no modebar, no zoom or drag."""
    shapes, notes = [], []
    if zero:
        shapes.append({"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": 0, "y1": 0,
                       "line": {"color": "var(--chart-zero)", "width": 1.25}})
    if target is not None:
        shapes.append({"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": target, "y1": target,
                       "line": {"color": "var(--text-muted)", "width": 1, "dash": "dash"}})
        notes.append({"xref": "paper", "x": 0.02, "xanchor": "left", "y": target, "yanchor": "top",
                      "text": target_label, "showarrow": False,
                      "font": {"size": 11, "color": "var(--text-muted)"}})
    if edge:
        shapes.append({"type": "line", "yref": "paper", "y0": 0, "y1": 1,
                       "x0": period_date(edge), "x1": period_date(edge),
                       "line": {"color": "var(--line)", "width": 1, "dash": "dot"}})
    axis = {"fixedrange": True, "showline": False, "zeroline": False,
            "tickfont": {"size": 11, "color": "var(--text-muted)"}}
    layout = {
        "height": height,
        "margin": {"l": 44, "r": 52 if any(t.get("textposition") for t in traces) else 14, "t": 18, "b": 30},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "Inter, system-ui, sans-serif", "size": 12, "color": "var(--text-body)"},
        "showlegend": False, "dragmode": False, "hovermode": hovermode,
        "hoverlabel": {"bgcolor": "var(--surface-card)", "bordercolor": "var(--hairline)",
                       "font": {"color": "var(--text-strong)", "size": 12}},
        "xaxis": {**axis, "type": "date", "showgrid": False, "ticks": "outside",
                  **({"hoverformat": "%YQ%q"} if hovermode == "x unified" else {}),
                  "ticklen": 4, "tickcolor": "var(--hairline)", "tickangle": 0,
                  "ticklabelmode": "instant", **_x_ticks(x_span),
                  **({"range": _date_span(*x_span)} if x_span else {})},
        "yaxis": {**axis, "showgrid": True, "gridcolor": "var(--chart-grid)", "ticksuffix": unit,
                  "nticks": 6, **({"range": [_r(y_range[0]), _r(y_range[1])]} if y_range else {}),
                  **({"dtick": y_dtick} if y_dtick else {})},
        "shapes": shapes, "annotations": notes, "transition": {"duration": 0},
    }
    return {"data": traces, "layout": layout}


def attach_plot(fig: str, spec: dict) -> str:
    """Add the interactive version to a figure() block; the SVG stays as the fallback."""
    payload = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    marker = '<div class="vc-plot">'
    if marker not in fig:
        raise ValueError("attach_plot() needs a figure() block")
    block = ('<div class="pe-plot" aria-hidden="true"></div>\n'
             f'<script type="application/json" class="pe-plot-json">{payload}</script>\n')
    return fig.replace(marker, block + marker, 1)


def fan_plot(rows: list[dict], *, median_name: str, band_note: str,
             overlay: tuple[str, str] | None = None,
             dots: list[tuple[str, float]] | None = None,
             y_range: tuple[float, float] | None = None, zero: bool = False,
             target: float | None = None, height: int = 300) -> dict:
    """A forecast fan as Plotly JSON: 90% and 68% bands, the median, an
    optional published path (``overlay`` = (label, row key), dashed) and
    outturn dots. ``rows`` carry period, median, lo68, hi68, lo90, hi90."""
    traces = [
        *plot_band([(r["period"], r["lo90"], r["hi90"]) for r in rows], f"90% band {band_note}".strip(), "var(--band-90)"),
        *plot_band([(r["period"], r["lo68"], r["hi68"]) for r in rows], f"68% band {band_note}".strip(), "var(--band-68)"),
        plot_line([(r["period"], r["median"]) for r in rows], median_name, "var(--series-ours)", digits=2),
    ]
    if overlay:
        traces.append(plot_line([(r["period"], r[overlay[1]]) for r in rows], overlay[0],
                                "var(--series-official)", dash="dash", width=2, digits=2))
    if dots:
        out = plot_line(dots, "ONS outturn", "var(--series-outturn)", digits=2, markers=True)
        out["marker"] = {"color": "var(--series-outturn)", "size": 9,
                         "line": {"color": "var(--surface-card)", "width": 2}}
        traces.append(out)
    for t in traces:   # unified hover: the quarter heads the box
        if t.get("name") and "band" not in t["name"]:
            t["hovertemplate"] = f"{t['name']}: %{{y:.2f}}%<extra></extra>"
    span = (y_range[1] - y_range[0]) if y_range else None
    dtick = None if span is None else next((d for d in (0.1, 0.2, 0.5, 1, 2, 5) if span / d <= 7), 10)
    return plot_spec(traces, unit="%", height=height, zero=zero, target=target,
                     target_label="2% target", y_range=y_range, y_dtick=dtick,
                     x_span=(rows[0]["period"], rows[-1]["period"]), hovermode="x unified")
