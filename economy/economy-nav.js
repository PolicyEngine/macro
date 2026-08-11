(function () {
  "use strict";

  var nav = document.querySelector(".economy-topics");
  if (!nav) return;
  // The same bar carries in-page anchors on /economy/us and links to the six
  // topic pages on /economy and the topics themselves. Only the anchor form
  // has sections to spy on; the page-link form is marked server-side with
  // aria-current="page" and needs nothing here.
  var links = Array.from(nav.querySelectorAll('a[href^="#"]'));
  if (!links.length) return;
  var sections = links
    .map(function (link) {
      return document.querySelector(link.getAttribute("href"));
    })
    .filter(Boolean);

  function highlight(id) {
    links.forEach(function (link) {
      var active = link.getAttribute("href") === "#" + id;
      if (active) {
        link.setAttribute("aria-current", "location");
        link.scrollIntoView({
          behavior: "auto",
          block: "nearest",
          inline: "center"
        });
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  var observer = new IntersectionObserver(
    function (entries) {
      var visible = entries
        .filter(function (entry) { return entry.isIntersecting; })
        .sort(function (a, b) { return a.boundingClientRect.top - b.boundingClientRect.top; });
      if (visible.length) highlight(visible[0].target.id);
    },
    { rootMargin: "-28% 0px -62% 0px", threshold: 0 }
  );
  sections.forEach(function (section) { observer.observe(section); });

  links.forEach(function (link) {
    link.addEventListener("click", function () {
      highlight(link.getAttribute("href").slice(1));
    });
  });
  highlight((location.hash || links[0].getAttribute("href")).slice(1));
})();
