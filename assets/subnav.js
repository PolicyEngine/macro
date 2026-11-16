/* Section sub-nav (r13): two labelled groups, Forecasts and Data.
   Wide: each group's items sit inline; the Topics list is a dropdown.
   820px and below: each group is one dropdown button ("Forecasts ▾",
   "Data ▾") and Topics show as a flat list inside Data. Each item appears
   once at every width. Without script, everything is inline and the row
   wraps. site_nav.render adds this file to pages with .economy-subnav. */
(function () {
  var nav = document.querySelector(".economy-subnav.sn3, .economy-subnav.sn2");
  if (!nav) return;
  nav.classList.add("js");
  var toggles = Array.from(nav.querySelectorAll(".sn-group-btn, .sn-menu-btn"));
  function owner(btn) { return btn.closest(".sn-menu") || btn.closest(".sn-group"); }
  function close(except) {
    toggles.forEach(function (b) {
      var box = owner(b);
      if (box === except || (except && box.contains(except))) return;
      box.classList.remove("open"); b.setAttribute("aria-expanded", "false");
    });
  }
  toggles.forEach(function (b) {
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      var box = owner(b), open = !box.classList.contains("open");
      close(box);
      box.classList.toggle("open", open);
      b.setAttribute("aria-expanded", String(open));
    });
  });
  document.addEventListener("click", function (e) { if (!nav.contains(e.target)) close(null); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(null); });
  window.addEventListener("resize", function () { close(null); });
}());
