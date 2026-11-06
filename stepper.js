// Shared page behaviour for the two-sided StepPanel and the "On this page"
// rail (DESIGN.md §4.6, §4.9). One copy for every page that has either; the
// pages used to carry four slightly different inline versions of it.
//
// StepPanel: each .scrolly-wrap is handled on its own (several pages carry
// more than one). The step whose top has passed the reading line (a third of
// the viewport down) gets .active, and the sticky aside shows the panel whose
// data-step matches it. A wrap where some step has no panel of its own is
// drawn as one column (.single) instead of leaving the right side blank.
//
// Rail: the link whose target has passed 30% of the viewport is marked
// aria-current="location".
(function () {
  "use strict";

  // MathJax (self-hosted, 1.3 MB) loads only once an equation is close to
  // the screen, or an expander holding one opens, instead of on every visit
  // to a methodology tab. The CSP allows no CDN loads.
  (function lazyMath() {
    var main = document.querySelector("main");
    if (!main || !document.querySelector(".meth-step")) return;
    var holders = Array.from(main.querySelectorAll(
      ".meth-inline, .kv, .meth-display, .meth-notation, .about, .meth-step > p"
    )).filter(function (el) { return /\\\(|\\\[/.test(el.textContent); });
    if (!holders.length) return;
    var loaded = false, io = null;
    function load() {
      if (loaded) return;
      loaded = true;
      if (io) io.disconnect();
      window.MathJax = {
        chtml: { fontURL: "/vendor/mathjax/output/chtml/fonts/woff-v2" },
        options: { enableMenu: false }
      };
      var s = document.createElement("script");
      s.src = "/vendor/mathjax/tex-chtml-full.js";
      s.async = true;
      document.head.appendChild(s);
    }
    window.addEventListener("beforeprint", load);
    document.addEventListener("toggle", function (e) {
      if (e.target.open && /\\\(|\\\[/.test(e.target.textContent)) load();
    }, true);
    if (!("IntersectionObserver" in window)) { load(); return; }
    io = new IntersectionObserver(function (entries) {
      if (entries.some(function (en) { return en.isIntersecting; })) load();
    }, { rootMargin: "300px 0px" });
    holders.forEach(function (el) {
      // a closed expander has no box; its toggle loads MathJax instead
      if (!el.closest("details:not([open])")) io.observe(el);
    });
  })();

  // Diagrams on a phone. A 580px-wide SVG in a ~330px column draws its 11px
  // labels at ~6px, so each diagram also gets an HTML layout built from the
  // SVG itself: every box that holds text becomes a card (first line bold),
  // boxes on the same row of the drawing sit side by side, rows stack with
  // an arrow between them, and free-standing text (titles, arrow labels,
  // footnotes) keeps its place in reading order. CSS shows it only <=600px;
  // the SVG stays for wide screens, print and the full-size view.
  (function phoneDiagrams() {
    var figs = document.querySelectorAll(".meth-pair figure.step-diagram");
    Array.prototype.forEach.call(figs, function (fig) {
      // drawn with its own phone-sized SVG (charts, matrices): nothing to build
      if (fig.classList.contains("has-phone-alt")) return;
      var svg = fig.querySelector("svg");
      if (!svg || !svg.viewBox || !svg.viewBox.baseVal) return;
      var num = function (el, a) { return parseFloat(el.getAttribute(a) || "0"); };
      var rects = Array.prototype.map.call(svg.querySelectorAll("rect"), function (r) {
        var fill = (r.getAttribute("fill") || "").trim(), stroke = r.getAttribute("stroke") || "";
        var op = parseFloat(r.getAttribute("opacity") || r.getAttribute("fill-opacity") || "1");
        var kind = /primary|brand/.test(fill) && op >= 0.6 ? "pri"
          : (/primary|brand/.test(stroke) || /primary|brand/.test(fill)) ? "out" : "neu";
        return { x: num(r, "x"), y: num(r, "y"), w: num(r, "width"), h: num(r, "height"), kind: kind, lines: [] };
      }).filter(function (r) { return r.w >= 40 && r.h >= 18; });
      var free = [];
      Array.prototype.forEach.call(svg.querySelectorAll("text"), function (t) {
        var s = (t.textContent || "").replace(/\s+/g, " ").trim();
        // lone operators between boxes (+, -, =) only make sense in the drawing
        if (!s || s.length < 3 && !/\w/.test(s)) return;
        var x = num(t, "x"), y = num(t, "y"), best = null;
        rects.forEach(function (r) {
          if (x >= r.x - 2 && x <= r.x + r.w + 2 && y >= r.y && y <= r.y + r.h + 2 &&
              (!best || r.w * r.h < best.w * best.h)) best = r;
        });
        var item = { s: s, y: y, x: x, bold: /^(6|7|8|9)00$|bold/.test(t.getAttribute("font-weight") || "") };
        if (best) best.lines.push(item); else free.push(item);
      });
      var lines = Array.prototype.map.call(svg.querySelectorAll("line[marker-end]"), function (l) {
        return { x1: num(l, "x1"), y1: num(l, "y1"), x2: num(l, "x2"), y2: num(l, "y2") };
      });
      var boxes = rects.filter(function (r) { return r.lines.length; });
      // a chart-like drawing (many empty bars) or a single box: keep the SVG
      if (boxes.length < 2 || rects.length - boxes.length > 6) return;
      boxes.sort(function (a, b) { return a.y - b.y || a.x - b.x; });
      var rows = [];
      boxes.forEach(function (b) {
        var row = rows.find(function (rw) {
          return b.y < rw.y + rw.h - 4 && b.y + b.h > rw.y + 4;
        });
        if (row) { row.items.push(b); row.y = Math.min(row.y, b.y); }
        else rows.push({ y: b.y, h: b.h, items: [b] });
      });
      var out = document.createElement("div");
      out.className = "diagram-phone";
      out.setAttribute("aria-hidden", "true");
      var title = free.length && free[0].y < (rows[0] ? rows[0].y : 1e9) ? free.shift() : null;
      if (title) { var tt = document.createElement("p"); tt.className = "dp-title"; tt.textContent = title.s; out.appendChild(tt); }
      var el = function (tag, cls, txt) { var e = document.createElement(tag); e.className = cls; if (txt) e.textContent = txt; return e; };
      rows.forEach(function (rw, i) {
        if (i) out.appendChild(el("span", "dp-arrow"));
        var notes = free.filter(function (f) { return f.y < rw.y && !f.used; });
        notes.forEach(function (f) { f.used = true; out.appendChild(el("p", "dp-note", f.s)); });
        rw.items.sort(function (a, b) { return a.x - b.x; });
        // boxes joined left to right by arrows read as a sequence: stack them
        var flow = rw.items.length > 1 && rw.items.slice(1).every(function (b, k) {
          var a = rw.items[k];
          return lines.some(function (l) {
            return Math.min(l.x1, l.x2) >= a.x + a.w - 12 && Math.max(l.x1, l.x2) <= b.x + 12 &&
              Math.abs(l.y1 - l.y2) < 6 && l.y1 > rw.y && l.y1 < rw.y + rw.h + 10;
          });
        });
        var row = el("div", flow ? "dp-row dp-flow" : "dp-row");
        rw.items.forEach(function (b, k) {
          if (flow && k) row.appendChild(el("span", "dp-arrow"));
          var box = el("div", "dp-box dp-" + b.kind);
          b.lines.sort(function (p, q) { return p.y - q.y || p.x - q.x; }).forEach(function (ln, k) {
            if (k === 0) box.appendChild(el("b", "", ln.s));
            else { box.appendChild(document.createTextNode(ln.s)); if (k < b.lines.length - 1) box.appendChild(document.createElement("br")); }
          });
          row.appendChild(box);
        });
        out.appendChild(row);
      });
      free.filter(function (f) { return !f.used; }).forEach(function (f) { out.appendChild(el("p", "dp-note", f.s)); });
      svg.insertAdjacentElement("afterend", out);
      fig.classList.add("has-phone");
    });
  })();

  // The "Notation" link opens the notation expander it points at.
  (function openNotation() {
    function open() {
      var d = location.hash === "#notation" && document.querySelector("#notation details");
      if (d) d.open = true;
    }
    window.addEventListener("hashchange", open);
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest('a[href="#notation"]');
      if (a) { var d = document.querySelector("#notation details"); if (d) d.open = true; }
    });
    open();
  })();

  var updaters = [];

  Array.from(document.querySelectorAll(".scrolly-wrap")).forEach(function (wrap) {
    var steps = Array.from(wrap.querySelectorAll(".meth-step"));
    var panels = Array.from(wrap.querySelectorAll(".meth-panel"));
    // Two sides only when every step has a panel of its own; otherwise one
    // full-width column with the in-step copies (DESIGN.md §4.9). Pages
    // should say .single in the markup; this catches the ones that do not.
    var ownPanel = {};
    panels.forEach(function (panel) { ownPanel[panel.getAttribute("data-step")] = true; });
    var full = steps.every(function (step, i) {
      return ownPanel[step.getAttribute("data-step") || String(i)];
    });
    if (!full) wrap.classList.add("single");
    if (wrap.classList.contains("single")) {
      // A panel whose step carries no in-step copy is moved into the step,
      // so nothing the aside held is lost when the aside is hidden.
      panels.forEach(function (panel) {
        var key = panel.getAttribute("data-step");
        var step = steps.filter(function (s, i) {
          return (s.getAttribute("data-step") || String(i)) === key;
        })[0];
        if (!step || step.querySelector(".meth-inline")) return;
        var copy = panel.cloneNode(true);
        copy.hidden = false;
        copy.className = "meth-inline";
        copy.removeAttribute("data-step");
        step.appendChild(copy);
      });
      return;
    }
    if (!steps.length || !panels.length) return;
    var keys = panels.map(function (panel) { return Number(panel.getAttribute("data-step")); });
    var first = Math.min.apply(null, keys);
    var current = -1;
    updaters.push(function () {
      var line = window.innerHeight * 0.33, active = 0;
      steps.forEach(function (step, i) {
        if (step.getBoundingClientRect().top < line) active = i;
      });
      // At the very end of the page a short last step may never reach the
      // reading line; once the whole wrap is on screen, it is the one read.
      var root = document.documentElement;
      if (window.innerHeight + window.scrollY >= root.scrollHeight - 2 &&
          wrap.getBoundingClientRect().bottom <= window.innerHeight) active = steps.length - 1;
      if (active === current) return;
      current = active;
      steps.forEach(function (step, i) { step.classList.toggle("active", i === active); });
      var want = first;
      keys.forEach(function (k) { if (k <= active && k > want) want = k; });
      panels.forEach(function (panel, i) { panel.hidden = keys[i] !== want; });
    });
  });

  var rail = document.querySelector(".page-rail");
  if (rail) {
    var links = Array.from(rail.querySelectorAll('a[href^="#"]'));
    var targets = links.map(function (a) {
      return document.getElementById(a.getAttribute("href").slice(1));
    });
    updaters.push(function () {
      var line = window.innerHeight * 0.3, current = 0;
      targets.forEach(function (t, i) { if (t && t.getBoundingClientRect().top < line) current = i; });
      links.forEach(function (a, i) {
        if (i === current) a.setAttribute("aria-current", "location");
        else a.removeAttribute("aria-current");
      });
    });
  }

  if (!updaters.length) return;
  function update() { updaters.forEach(function (fn) { fn(); }); }
  function later() { setTimeout(update, 0); }
  window.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update, { passive: true });
  window.addEventListener("hashchange", later);
  // In-card view switches (role="tab") change the height of the steps.
  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest('[role="tab"]')) later();
  });
  update();
})();
