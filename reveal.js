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
