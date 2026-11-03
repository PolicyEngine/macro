// A restrained, one-time reveal for section-level content. The hero and
// navigation paint immediately; only content reached by scrolling moves.
(function () {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const targets = document.querySelectorAll(
    "main .band > *, main .model-evidence-links-top"
  );
  targets.forEach(function (el) { el.classList.add("scroll-reveal"); });
  if (reduce || !("IntersectionObserver" in window)) {
    targets.forEach(function (el) { el.classList.add("in-view"); });
    return;
  }
  const io = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("in-view");
          io.unobserve(e.target);
        }
      });
    },
    { threshold: 0.08, rootMargin: "0px 0px -7% 0px" }
  );
  targets.forEach(function (el) {
    if (el.getBoundingClientRect().top < window.innerHeight * 0.92) {
      el.classList.add("in-view", "reveal-initial");
    } else if (el.offsetHeight > window.innerHeight * 0.7) {
      // Tall blocks (long walkthroughs, scrollytelling wrappers) may never
      // reach the 8% intersection threshold — show them without animation.
      el.classList.add("in-view", "reveal-initial");
    } else {
      io.observe(el);
    }
  });
})();

// Keep sticky subnavs flush under the fixed header: expose the header's
// real height as --nav-h so sticky offsets never drift from it.
(function () {
  "use strict";
  var nav = document.querySelector("header.nav");
  if (!nav) return;
  function set() {
    document.documentElement.style.setProperty(
      "--nav-h", nav.getBoundingClientRect().height + "px"
    );
  }
  window.addEventListener("resize", set, { passive: true });
  window.addEventListener("load", set);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(set);
  set();
})();

/* A fragment that targets a <details> element scrolls to it but does not open
   it — browsers auto-expand only when the fragment targets a DESCENDANT. Three
   high-traffic links point at /models#score, where the id sits on the <details>
   itself, so the primary "score a reform" journey landed on a closed summary
   with the content hidden. Open it on load and on subsequent hash changes. */
(function () {
  "use strict";
  function openTargetedDetails() {
    if (!location.hash || location.hash.length < 2) return;
    var target;
    try { target = document.querySelector(location.hash); } catch (e) { return; }
    if (!target) return;
    if (target.tagName === "DETAILS") target.open = true;
    var parent = target.closest && target.closest("details");
    if (parent) parent.open = true;
    target.scrollIntoView({ block: "start" });
  }
  window.addEventListener("hashchange", openTargetedDetails);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", openTargetedDetails);
  } else {
    openTargetedDetails();
  }
})();


/* Copy-to-clipboard, shared. This handler was pasted verbatim into fifteen
   pages and omitted from models/index.html, which renders a copy button in
   #score — the target of fifteen links — that did nothing. One delegated
   copy, so a page gets the behaviour by loading this file. */
(function () {
  "use strict";
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    // /connect wraps its blocks in .code-window, so the code element is not
    // a child of the button's parent there.
    var container = button.closest(".code-window") || button.parentElement;
    var code = container && container.querySelector("code");
    if (!code || !navigator.clipboard) return;
    navigator.clipboard.writeText(code.textContent).then(function () {
      button.textContent = "copied";
      setTimeout(function () { button.textContent = "copy"; }, 1400);
    });
  });
})();

/* Phone reading (DESIGN.md §1.7, §4.12).
   1. Scroll rows (sub-tab rows, table scrollers, diagram scrollers) get a
      fade on the edge that has more content behind it, so a tab or a column
      past the edge is discoverable; the chosen sub-tab is scrolled into view.
   2. Tables whose cells are mostly words are labelled cell by cell
      (data-label from the column head) and marked .t-stack: below 640px the
      CSS turns each row into a small card instead of a 720px side-scroll.
      Numeric grids keep the scroller. data-stack="no" / "yes" on a table
      overrides the guess. Without JS every table simply scrolls. */
(function () {
  "use strict";
  var NUM = /^[\s(]*[−\-+~≈<>]?[£$€]?[\d.,  ]+(%|pp|bn|m|k|x|×|\*|\))*[\s*)]*$/i;
  function simpleHead(table) {
    var thead = table.tHead;
    if (!thead || thead.rows.length !== 1) return null;
    var cells = thead.rows[0].cells, labels = [];
    for (var i = 0; i < cells.length; i++) {
      if (cells[i].colSpan > 1 || cells[i].rowSpan > 1) return null;
      labels.push(cells[i].textContent.replace(/\s+/g, " ").trim());
    }
    return labels;
  }
  function wordy(table) {
    var cells = table.querySelectorAll("tbody td"), words = 0, n = 0;
    for (var i = 0; i < cells.length; i++) {
      var t = cells[i].textContent.trim();
      if (!t || t === "—" || t === "–") continue;
      n++;
      if (!NUM.test(t)) words++;
    }
    return n > 0 && words / n >= 0.5;
  }
  document.querySelectorAll(".table-scroll > table").forEach(function (table) {
    var mode = table.getAttribute("data-stack");
    if (mode === "no" || table.classList.contains("vc-table") ||
        table.classList.contains("vc-narrow-table")) return;
    var labels = simpleHead(table);
    if (!labels || labels.length < 2) return;
    var nrows = 0;
    for (var t = 0; t < table.tBodies.length; t++) nrows += table.tBodies[t].rows.length;
    // long registers (the 41-series data table) stay a scroller: as cards
    // they would run to many screens.
    if (mode !== "yes" && (nrows > 20 || !wordy(table))) return;
    // a two-column key/detail table reads as cards without column labels
    if (labels.length === 2) labels = ["", ""];
    var rows;
    for (var b = 0; b < table.tBodies.length; b++) {
      rows = table.tBodies[b].rows;
      for (var r = 0; r < rows.length; r++) {
        var col = 0, cells = rows[r].cells;
        for (var c = 0; c < cells.length; c++) {
          if (cells[c].colSpan > 1) { col += cells[c].colSpan; continue; }
          if (labels[col] !== undefined && !cells[c].hasAttribute("data-label")) {
            cells[c].setAttribute("data-label", labels[col]);
          }
          col++;
        }
      }
    }
    table.classList.add("t-stack");
    table.parentElement.classList.add("has-t-stack");
  });

  var rows = document.querySelectorAll(
    ".model-tabs-row, .economy-subnav-row, .table-scroll, .step-diagram"
  );
  function fade(el) {
    var max = el.scrollWidth - el.clientWidth;
    el.classList.toggle("fade-r", max > 2 && el.scrollLeft < max - 2);
    el.classList.toggle("fade-l", max > 2 && el.scrollLeft > 2);
  }
  rows.forEach(function (el) {
    var cur = el.querySelector("[aria-current='page']");
    if (cur && el.scrollWidth > el.clientWidth) {
      var all = el.querySelectorAll("[aria-current='page']");
      cur = all[all.length - 1];
      var box = el.getBoundingClientRect(), r = cur.getBoundingClientRect();
      if (r.right > box.right || r.left < box.left) {
        el.scrollLeft = Math.max(0, r.left - box.left + el.scrollLeft -
          (el.clientWidth - r.width) / 2);
      }
    }
    fade(el);
    el.addEventListener("scroll", function () { fade(el); }, { passive: true });
  });
  window.addEventListener("resize", function () { rows.forEach(fade); }, { passive: true });
})();
