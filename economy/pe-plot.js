// Interactive charts: draws each figure's Plotly JSON (written by chartkit's
// plot_spec/attach_plot, stdlib only) with the vendored plotly.js basic build.
// A progressive enhancement: the SVG chart is in the page first and stays the
// no-JS, print and screen-reader version. Only once Plotly has drawn does the
// figure get .has-plot, which swaps the two on screen.
//
// Colours in the JSON are CSS tokens, "var(--token)" or "var(--token)/0.25"
// for a translucent fill. They are resolved against the figure for the
// current scheme and re-resolved when the scheme changes. No modebar, no
// zoom or drag (touch scrolling passes through), no animated transitions.
(function () {
  "use strict";
  if (!window.Plotly) return;

  var TOKEN = /^var\((--[a-z0-9-]+)\)(?:\/([0-9.]+))?$/i;
  var probe = document.createElement("span");
  probe.style.display = "none";

  // Any CSS colour, including color-mix(), to rgb()/rgba() Plotly can read:
  // the browser computes it on a hidden probe, and color(srgb r g b / a)
  // results are converted by hand.
  function normalise(css, host) {
    probe.style.color = "";
    probe.style.color = css;
    host.appendChild(probe);
    var c = getComputedStyle(probe).color;
    host.removeChild(probe);
    var m = /^color\(srgb ([0-9.e-]+) ([0-9.e-]+) ([0-9.e-]+)(?: \/ ([0-9.e-]+))?\)$/.exec(c);
    if (m) {
      var to = function (v) { return Math.round(parseFloat(v) * 255); };
      return "rgba(" + to(m[1]) + "," + to(m[2]) + "," + to(m[3]) + "," + (m[4] === undefined ? 1 : parseFloat(m[4])) + ")";
    }
    return c;
  }
  function withAlpha(color, alpha) {
    var hex = /^#([0-9a-f]{6})$/i.exec(color);
    if (hex) {
      var n = parseInt(hex[1], 16);
      return "rgba(" + (n >> 16) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
    }
    var rgb = /^rgba?\(([^)]+)\)$/.exec(color);
    if (rgb) {
      var p = rgb[1].split(",").map(function (s) { return s.trim(); });
      var a = p.length > 3 ? parseFloat(p[3]) * alpha : alpha;
      return "rgba(" + p[0] + "," + p[1] + "," + p[2] + "," + a + ")";
    }
    return color;
  }
  function resolve(value, host) {
    if (typeof value === "string") {
      var m = TOKEN.exec(value);
      if (!m) return value;
      var color = normalise("var(" + m[1] + ")", host);
      return m[2] ? withAlpha(color, parseFloat(m[2])) : color;
    }
    if (Array.isArray(value)) return value.map(function (v) { return resolve(v, host); });
    if (value && typeof value === "object") {
      var out = {};
      Object.keys(value).forEach(function (k) { out[k] = resolve(value[k], host); });
      return out;
    }
    return value;
  }

  var CONFIG = { displayModeBar: false, responsive: true, scrollZoom: false,
                 doubleClick: false, showTips: false, staticPlot: false };
  var figures = [];

  function draw(item) {
    var target = item.div;
    if (!target.clientWidth) return;            // hidden (a closed tab): draw when shown
    var spec = resolve(item.spec, item.fig);
    Plotly.react(target, spec.data, spec.layout, CONFIG).then(function () {
      item.drawn = true;
      item.fig.classList.add("has-plot");
    });
  }

  document.querySelectorAll(".vc-fig .pe-plot-json").forEach(function (node) {
    var fig = node.closest(".vc-fig");
    var div = fig.querySelector(".pe-plot");
    var spec;
    try { spec = JSON.parse(node.textContent); } catch (e) { return; }
    var item = { fig: fig, div: div, spec: spec, drawn: false };
    figures.push(item);
    draw(item);
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        if (!item.drawn) draw(item);
        else if (div.clientWidth) Plotly.Plots.resize(div);
      }).observe(div);
    }
  });

  // A chart in a closed tab draws when its panel opens. ResizeObserver covers
  // that; this is the fallback where it is late (a background tab, an old
  // engine): any tab click, hash change or return to the page retries.
  function drawPending() {
    figures.forEach(function (item) { if (!item.drawn) draw(item); });
  }
  var later = function () { setTimeout(drawPending, 0); };
  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest('[role="tab"], summary')) later();
  });
  window.addEventListener("hashchange", later);
  document.addEventListener("visibilitychange", later);

  var scheme = window.matchMedia("(prefers-color-scheme: dark)");
  var redraw = function () { figures.forEach(function (item) { if (item.drawn) draw(item); }); };
  if (scheme.addEventListener) scheme.addEventListener("change", redraw);
  else if (scheme.addListener) scheme.addListener(redraw);
})();
