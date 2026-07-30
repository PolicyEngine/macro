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
    document.documentElement.style.setProperty("--nav-h", nav.offsetHeight + "px");
  }
  window.addEventListener("resize", set, { passive: true });
  set();
})();
