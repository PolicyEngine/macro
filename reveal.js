// Scroll reveal (r15 polish): a subtle fade and 8px rise as blocks enter,
// a short stagger inside card grids, and a gentle count-up on stat values.
// Progressive enhancement: nothing is hidden unless this script runs and
// motion is allowed (html.rv-on); anything above the viewport — after an
// anchor jump or a fast scroll — is shown at once, so no block is ever left
// faded; print and reduced motion show everything at rest.
(function () {
  "use strict";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var BLOCKS = "main .band > *, main .model-evidence-links-top, main section > .lp-wrap > *, main .ab-sec > *, main .gl-sec > *, main .fc-body > section > *";
  var GRIDS = "main :is(.mc-grid, .uc-grid, .qc-grid, .stat-row, .stat-grid, .fc-tiles, .ct-grid, .pp-list, .tr-list, .lp-models)";
  var targets = Array.from(document.querySelectorAll(BLOCKS));
  document.querySelectorAll(GRIDS).forEach(function (grid) {
    Array.from(grid.children).forEach(function (child, i) {
      child.style.setProperty("--rv-d", Math.min(i, 7) * 85 + "ms");
      child.classList.add("rv-card");
      targets.push(child);
    });
  });
  targets = targets.filter(function (el, i, all) { return all.indexOf(el) === i && !el.closest(".hero, .lp-hero, .mp-hero, [data-no-reveal]"); });
  var HEADS = ".sh, .band-head";
  targets.forEach(function (el) {
    el.classList.add("scroll-reveal");
    if (el.matches(HEADS)) el.classList.add("rv-head");
  });
  function showAll() { targets.forEach(function (el) { el.classList.add("in-view", "reveal-initial"); }); }
  window.addEventListener("beforeprint", showAll);
  if (reduce || !("IntersectionObserver" in window)) { showAll(); return; }
  document.documentElement.classList.add("rv-on");

  var COUNT = ".stat-value, .stat-num, .fc-tile-v, .lp-stat-v";
  function countUp(root) {
    root.querySelectorAll(COUNT).forEach(function (el) {
      if (el.dataset.counted || el.children.length) return;
      var text = el.textContent;
      var m = text.match(/^(\s*[^\d\-−]*)(-|−)?(\d+(?:\.\d+)?)(.*)$/s);
      if (!m) return;
      var end = parseFloat(m[3]); if (!isFinite(end) || end === 0) return;
      var decimals = (m[3].split(".")[1] || "").length;
      if (!decimals && end >= 1900 && end <= 2100) return;   /* years and quarters do not count */
      el.dataset.counted = "1";
      var start = null, dur = 900;
      function step(ts) {
        if (start === null) start = ts;
        var t = Math.min(1, (ts - start) / dur), e = 1 - Math.pow(1 - t, 3);
        el.textContent = m[1] + (m[2] || "") + (end * e).toFixed(decimals) + m[4];
        if (t < 1) requestAnimationFrame(step); else el.textContent = text;
      }
      requestAnimationFrame(step);
    });
  }
  /* charts: lines draw in, bands fade up after the line, bars grow from the
     baseline, dots pop in one by one. Web Animations only: the resting state is
     always the visible one, so nothing can be left hidden. */
  var EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
  function chartSvgs(root) {
    return Array.from(root.querySelectorAll("svg:not(.i):not(.flag)")).filter(function (svg) {
      var vb = svg.viewBox && svg.viewBox.baseVal;
      return vb && vb.width >= 200 && !svg.closest("[data-no-reveal]") && !svg.dataset.drawn;
    });
  }
  function drawCharts(root, delay) {
    if (!Element.prototype.animate) return;
    delay = delay || 0;
    chartSvgs(root).forEach(function (svg) {
      svg.dataset.drawn = "1";
      var vbw = svg.viewBox.baseVal.width, lineEnd = delay;
      svg.querySelectorAll("path, polyline").forEach(function (p) {
        var cs = getComputedStyle(p);
        if (cs.fill !== "none" || cs.stroke === "none" || parseFloat(cs.strokeWidth) < 1.4) return;
        if (cs.strokeDasharray && cs.strokeDasharray !== "none") return;
        var len = 0; try { len = p.getTotalLength(); } catch (e) { return; }
        if (len < 60) return;
        p.style.strokeDasharray = len;
        var a = p.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
          { duration: 1100, delay: delay, easing: EASE, fill: "backwards" });
        lineEnd = Math.max(lineEnd, delay + 700);
        a.onfinish = a.oncancel = function () { p.style.strokeDasharray = ""; };
      });
      svg.querySelectorAll("path").forEach(function (p) {
        var cs = getComputedStyle(p);
        if (cs.fill === "none" || parseFloat(cs.fillOpacity) >= 1 && parseFloat(cs.opacity) >= 1) return;
        p.animate([{ opacity: 0 }, { opacity: cs.opacity }], { duration: 700, delay: lineEnd - 300, easing: "ease-out", fill: "backwards" });
      });
      var bars = Array.from(svg.querySelectorAll("rect")).filter(function (r) {
        var w = r.width.baseVal.value, h = r.height.baseVal.value;
        return h > 2 && w > 1 && w < vbw * 0.5 && getComputedStyle(r).fill !== "none";
      });
      bars.forEach(function (r, i) {
        r.style.transformBox = "fill-box"; r.style.transformOrigin = "50% 100%";
        r.animate([{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }],
          { duration: 750, delay: delay + Math.min(i, 12) * 40, easing: EASE, fill: "backwards" });
      });
      var dots = Array.from(svg.querySelectorAll("circle")).filter(function (c) { return c.r.baseVal.value <= 7; });
      dots.forEach(function (c, i) {
        c.style.transformBox = "fill-box"; c.style.transformOrigin = "50% 50%";
        c.animate([{ transform: "scale(0)", opacity: 0 }, { transform: "scale(1.25)", opacity: 1, offset: 0.7 }, { transform: "scale(1)", opacity: 1 }],
          { duration: 420, delay: lineEnd - 200 + Math.min(i, 16) * 70, easing: "ease-out", fill: "backwards" });
      });
    });
    root.querySelectorAll(".fc-pips").forEach(function (row) {
      Array.from(row.children).forEach(function (d, i) {
        d.animate([{ transform: getComputedStyle(d).transform === "none" ? "scale(0)" : getComputedStyle(d).transform + " scale(0)", opacity: 0 }, { opacity: 1 }],
          { duration: 360, delay: delay + 200 + Math.min(i, 16) * 70, easing: "ease-out", fill: "backwards" });
      });
    });
  }
  function reveal(el, animate) {
    if (el.classList.contains("in-view")) return;
    if (!animate) el.classList.add("reveal-initial");
    el.classList.add("in-view");
    if (animate) {
      countUp(el);
      drawCharts(el, 250 + (parseInt(el.style.getPropertyValue("--rv-d"), 10) || 0));
    }
    /* once in place, hand the transform back to hover styles with no stagger delay */
    setTimeout(function () { el.classList.add("rv-done"); }, animate ? 1300 : 0);
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { reveal(e.target, true); io.unobserve(e.target); } });
  }, { threshold: 0.06, rootMargin: "0px 0px -6% 0px" });
  var vh = window.innerHeight;
  targets.forEach(function (el) {
    var r = el.getBoundingClientRect();
    if (r.top < vh * 0.94 || r.height > vh * 0.8) reveal(el, false);
    else if (r.top < vh) reveal(el, true);   /* peeking in at the bottom edge: animate in now */
    else io.observe(el);
  });
  /* charts already on screen at load (the home fan) draw in once; not after an anchor jump */
  if (!location.hash) {
    Array.from(document.querySelectorAll("main svg:not(.i):not(.flag)")).forEach(function (svg) {
      if (svg.getBoundingClientRect().top < vh * 0.9) drawCharts(svg.parentElement, 200);
    });
  }
  /* catch-up: blocks scrolled past are shown at once; blocks entering the viewport
     animate, unless the scroll was a jump (anchor, Home/End, scrollbar drag) */
  var lastY = window.scrollY;
  function catchUp(jump) {
    var h = window.innerHeight;
    targets.forEach(function (el) {
      if (el.classList.contains("in-view")) return;
      var r = el.getBoundingClientRect();
      if (r.bottom < 0) reveal(el, false);
      else if (r.top < h * 0.94) reveal(el, !jump);
    });
  }
  var timer = null;
  window.addEventListener("scroll", function () {
    /* synchronous catch-up, plus a timer fallback for throttled tabs where
       animation frames are delayed: nothing is left faded after a jump */
    var dy = Math.abs(window.scrollY - lastY);
    lastY = window.scrollY;
    catchUp(dy > window.innerHeight * 1.2);
    clearTimeout(timer); timer = setTimeout(function () { catchUp(false); }, 150);
  }, { passive: true });
  window.addEventListener("hashchange", function () {
    targets.forEach(function (el) { if (el.getBoundingClientRect().top < window.innerHeight) reveal(el, false); });
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
  if (window.ResizeObserver) new ResizeObserver(set).observe(nav);
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

// Numeric columns right-aligned (DESIGN.md §4.12): a body column whose every
// filled cell reads as a number ("703.8", "+0.70%", "−£520m", "2.1pp") gets
// .num on its cells and its head, so figures line up on the decimal side
// without each page marking them by hand.
(function () {
  "use strict";
  var ONE = "[+\\-−±~≈]?\\s*[£$€]?\\s*\\d[\\d,]*(\\.\\d+)?\\s*(%|pp|bp|bn|m|k|x|×)?";
  var NUM = new RegExp("^[\\s(]*" + ONE + "(\\s*[–\\-—to]+\\s*" + ONE + ")?[\\s)]*[*†‡¹²³]*$", "i");
  document.querySelectorAll("main table:not(.sb-grid):not(.cap-grid)").forEach(function (table) {
    var rows = Array.from(table.tBodies).reduce(function (all, body) {
      return all.concat(Array.from(body.rows));
    }, []);
    if (!rows.length) return;
    var width = Math.max.apply(null, rows.map(function (r) { return r.cells.length; }));
    for (var c = 1; c < width; c++) {
      var cells = rows.map(function (r) { return r.cells[c]; }).filter(Boolean);
      var filled = cells.filter(function (cell) { return cell.textContent.trim() && cell.textContent.trim() !== "—"; });
      if (!filled.length) continue;
      var hits = filled.filter(function (cell) { return NUM.test(cell.textContent.trim()); }).length;
      if (hits / filled.length < 0.6) continue;
      cells.forEach(function (cell) { cell.classList.add("num"); });
      if (table.tHead) Array.from(table.tHead.rows).forEach(function (r) {
        if (r.cells.length === width && r.cells[c]) r.cells[c].classList.add("num");
      });
    }
  });
})();

/* Shared table component (r12, style.css §15). Every .table-scroll table
   gets: data-label on each cell so phones can show it as stacked cards,
   and an edge fade while the table scrolls sideways. Tables with merged
   cells or more than eight columns keep scrolling instead of stacking. */
(function () {
  "use strict";
  var SKIP = ".sb-grid, .cap-grid, .vc-table, .vc-narrow-table";
  document.querySelectorAll(".table-scroll").forEach(function (box) {
    var table = box.querySelector(":scope > table");
    if (!table || table.matches(SKIP)) return;
    box.classList.add("tbl");
    var head = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    var labels = head ? Array.from(head.cells).map(function (c) { return c.textContent.trim(); }) : [];
    var merged = table.querySelector("[colspan]:not([colspan='1']), [rowspan]:not([rowspan='1'])");
    var own = table.matches(".t-stack") || box.matches(".has-t-stack, .mo-tablecard");
    if (labels.length && labels.length <= 8 && !merged && !own) {
      table.classList.add("tbl-stack");
      Array.from(table.tBodies).forEach(function (body) {
        Array.from(body.rows).forEach(function (row) {
          Array.from(row.cells).forEach(function (cell, i) {
            if (labels[i] && !cell.hasAttribute("data-label")) cell.setAttribute("data-label", labels[i]);
          });
        });
      });
    }
    function edge() {
      var more = box.scrollWidth - box.clientWidth > 2;
      box.classList.toggle("is-scroll", more);
      box.classList.toggle("at-end", !more || box.scrollLeft + box.clientWidth >= box.scrollWidth - 2);
    }
    edge();
    box.addEventListener("scroll", edge, { passive: true });
    window.addEventListener("resize", edge);
  });
})();

/* In-page sub-nav scroll-spy (r14): any nav made of same-page links
   (/models sub-nav, "on this page" rails, data-spy navs) marks the link for
   the section in view with aria-current, so the teal underline follows the
   scroll; clicks scroll smoothly with the sticky-header offset (CSS
   scroll-margin-top). */
(function () {
  "use strict";
  if (!("IntersectionObserver" in window)) return;
  var navs = Array.from(document.querySelectorAll(".mp-subnav, .page-rail, [data-spy]")).filter(function (nav) {
    return nav.querySelectorAll('a[href^="#"]').length >= 2;
  });
  navs.forEach(function (nav) {
    var links = Array.from(nav.querySelectorAll('a[href^="#"]'));
    var map = new Map();
    links.forEach(function (a) {
      var el = document.getElementById(decodeURIComponent(a.getAttribute("href").slice(1)));
      if (el) map.set(el, a);
    });
    var visible = new Set();
    var first = Array.from(map.keys())[0];
    function setCurrent(a) {
      links.forEach(function (x) { if (x !== a) x.removeAttribute("aria-current"); });
      a.setAttribute("aria-current", "location");
      /* keep the active tab visible when the strip scrolls sideways */
      var strip = a.parentElement;
      if (strip && strip.scrollWidth > strip.clientWidth) {
        strip.scrollTo({ left: a.offsetLeft - (strip.clientWidth - a.offsetWidth) / 2, behavior: "smooth" });
      }
    }
    function mark() {
      if (first && window.scrollY + 160 < first.getBoundingClientRect().top + window.scrollY) { setCurrent(map.get(first)); return; }
      var best = null, top = -Infinity;
      map.forEach(function (_a, el) { var t = el.getBoundingClientRect().top; if (t <= 160 && t > top) { top = t; best = el; } });
      if (best) setCurrent(map.get(best));
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) visible.add(e.target); else visible.delete(e.target); });
      mark();
    }, { rootMargin: "-150px 0px -40% 0px" });
    window.addEventListener("scroll", function () { window.requestAnimationFrame(mark); }, { passive: true });
    map.forEach(function (_a, el) { io.observe(el); });
    links.forEach(function (a) {
      a.addEventListener("click", function () { setCurrent(a); });
    });
  });
})();

/* Table status cells (r15): a cell whose whole text is a status word becomes
   a small chip with an icon, so status reads at a glance. Long tables get a
   sticky header (a capped-height scroller, so the header can stick inside
   it). Text is unchanged; only presentation is added. */
(function () {
  "use strict";
  var TAIL = "(\\s*\\([^)]*\\)|,\\s*[^,]{1,24})?$";
  var STATUS = [
    [new RegExp("^(yes|pass|passes|hosted|live|exact|replicates)" + TAIL, "i"), "ok"],
    [new RegExp("^(no|fail|fails|none)" + TAIL, "i"), "no"],
    [new RegExp("^(local|local only|experimental|partial|partial replication|weak|moderate|imposed|anchored)" + TAIL, "i"), "warn"]
  ];
  document.querySelectorAll(".table-scroll.tbl > table").forEach(function (table) {
    Array.from(table.querySelectorAll("tbody td")).forEach(function (td) {
      if (td.children.length || td.classList.contains("num")) return;
      var t = td.textContent.trim();
      if (!t || t.length > 28) return;
      for (var i = 0; i < STATUS.length; i++) {
        if (STATUS[i][0].test(t)) {
          td.innerHTML = '<span class="st st-' + STATUS[i][1] + '">' + td.innerHTML + "</span>";
          break;
        }
      }
    });
    var rows = table.tBodies.length ? table.tBodies[0].rows.length : 0;
    if (rows > 14 && table.tHead) table.parentElement.classList.add("tbl-long");
  });
})();

/* Disclosure icons (r15): a details.about/.expander/.more summary with no
   icon of its own gets a real one chosen from its words, so the old generic
   fallback glyph never shows. Bare icon, no tile. */
(function () {
  "use strict";
  var P = {
    calendar: '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    table: '<path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/>',
    shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    book: '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>'
  };
  var RULES = [
    [/^\s*why\b|what (it|this) is/i, "info"],
    [/as it was|published on|vintage|history|archive|snapshot/i, "history"],
    [/release|calendar|announc|schedule|date/i, "calendar"],
    [/endpoint|file format|api|command|code|run it|cli|python|mcp|install/i, "code"],
    [/limit|caveat|warning|known issue|fails?|not\b/i, "alert"],
    [/evidence|validat|check|test|grade|trust/i, "shield"],
    [/table|figures|numbers|by dimension|full/i, "table"],
    [/data|series|source|store/i, "database"],
    [/method|how|paper|read|equation|about/i, "book"]
  ];
  document.querySelectorAll("details:is(.about, .expander, .more):not(.xp) > summary").forEach(function (s) {
    if (s.querySelector("svg")) return;
    var text = s.textContent, key = "info";
    for (var i = 0; i < RULES.length; i++) { if (RULES[i][0].test(text)) { key = RULES[i][1]; break; } }
    var span = document.createElement("span");
    span.className = "sum-ic"; span.setAttribute("aria-hidden", "true");
    span.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' + P[key] + "</svg>";
    s.insertBefore(span, s.firstChild);
    s.classList.add("has-ic");
  });
})();

/* Country switch (.seg): one sliding indicator under the active segment.
   Without this script the active segment carries its own fill (style.css §39). */
(function () {
  var segs = document.querySelectorAll(".seg");
  if (!segs.length) return;
  var ACTIVE = '.is-on, [aria-pressed="true"]';
  function place(seg, target, animate) {
    var on = target || seg.querySelector(ACTIVE);
    var ind = seg.querySelector(".seg-ind");
    if (!ind) return;
    if (!on || !on.offsetWidth) { ind.style.opacity = "0"; return; }
    ind.style.opacity = "1";
    if (!animate) seg.classList.add("seg-still");
    seg.style.setProperty("--seg-x", on.offsetLeft + "px");
    seg.style.setProperty("--seg-w", on.offsetWidth + "px");
    if (!animate) { void ind.offsetWidth; seg.classList.remove("seg-still"); }
  }
  Array.prototype.forEach.call(segs, function (seg) {
    var ind = document.createElement("span");
    ind.className = "seg-ind";
    ind.setAttribute("aria-hidden", "true");
    seg.insertBefore(ind, seg.firstChild);
    seg._segHome = seg.querySelector(".is-on");
    place(seg, null, false);
    seg.classList.add("has-ind");
    if (window.MutationObserver) {
      new MutationObserver(function (list) {
        for (var i = 0; i < list.length; i++) if (list[i].target !== seg && list[i].target !== ind) { place(seg, null, true); return; }
      }).observe(seg, { subtree: true, attributes: true, attributeFilter: ["aria-pressed", "class"] });
    }
    /* a country link navigates: slide to it first so the switch reads as one control */
    seg.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a.cc-tog");
      if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button) return;
      var cur = seg.querySelector(".is-on");
      if (cur && cur !== a) { cur.classList.remove("is-on"); a.classList.add("is-on"); }
    });
  });
  function all() { Array.prototype.forEach.call(segs, function (s) { place(s, null, false); }); }
  window.addEventListener("resize", all);
  /* back from a country link (bfcache): put the current country back */
  window.addEventListener("pageshow", function () {
    Array.prototype.forEach.call(segs, function (s) {
      var home = s._segHome, cur = s.querySelector(".is-on");
      if (home && cur && cur !== home) { cur.classList.remove("is-on"); home.classList.add("is-on"); }
    });
    all();
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(all);
})();

/* Thin teal reading-progress bar under the sticky header (style.css §40). */
(function () {
  var nav = document.querySelector("header.nav");
  if (!nav || !document.querySelector("main")) return;
  var bar = document.createElement("div");
  bar.className = "rv-progress";
  bar.setAttribute("aria-hidden", "true");
  nav.appendChild(bar);   /* inside the header, on its bottom edge: never over the tabs */
  var ticking = false;
  function update() {
    ticking = false;
    var max = document.documentElement.scrollHeight - window.innerHeight;
    var p = max > 120 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
    bar.style.transform = "scaleX(" + p.toFixed(4) + ")";
    bar.classList.toggle("is-on", p > 0.002);
  }
  function onScroll() { if (!ticking) { ticking = true; requestAnimationFrame(update); } }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  update();
})();
