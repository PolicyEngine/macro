// Shared page behaviour for the two-sided StepPanel and the "On this page"
// rail (DESIGN.md §4.6, §4.9). One copy for every page that has either; the
// pages used to carry four slightly different inline versions of it.
//
// StepPanel: each .scrolly-wrap is handled on its own (several pages carry
// more than one). The step whose top has passed the reading line (a third of
// the viewport down) gets .active, and the sticky aside shows the panel whose
// data-step matches it. A step with no panel of its own keeps the nearest
// earlier panel pinned; before the first panelled step the earliest panel is
// shown, so the column is never empty.
//
// Rail: the link whose target has passed 30% of the viewport is marked
// aria-current="location".
(function () {
  "use strict";

  var updaters = [];

  Array.from(document.querySelectorAll(".scrolly-wrap")).forEach(function (wrap) {
    var steps = Array.from(wrap.querySelectorAll(".meth-step"));
    var panels = Array.from(wrap.querySelectorAll(".meth-panel"));
    if (!steps.length || !panels.length) return;
    var keys = panels.map(function (panel) { return Number(panel.getAttribute("data-step")); });
    var first = Math.min.apply(null, keys);
    var current = -1;
    updaters.push(function () {
      var line = window.innerHeight * 0.33, active = 0;
      steps.forEach(function (step, i) {
        if (step.getBoundingClientRect().top < line) active = i;
      });
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
