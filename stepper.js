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
