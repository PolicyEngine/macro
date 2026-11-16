/* Joins hub (r12): hover, focus or tap a model to highlight its join and
   show its one-line caption. On /models a tap also opens the matching join
   panel. Reads fine without script: every flow and status is drawn. */
(function () {
  document.querySelectorAll("[data-hub]").forEach(function (hub) {
    var cap = hub.querySelector(".hub-cap span");
    var base = hub.querySelector(".hub-cap").dataset.default;
    var pinned = null;
    function show(btn) {
      hub.dataset.active = btn ? btn.dataset.k : "";
      cap.innerHTML = "";
      if (!btn) { cap.textContent = base; return; }
      cap.appendChild(document.createTextNode(btn.querySelector("strong").textContent + ": " + btn.dataset.cap + " "));
      var a = document.createElement("a");
      a.href = btn.dataset.href; a.textContent = "Open model";
      cap.appendChild(a);
    }
    hub.querySelectorAll(".hub-btn").forEach(function (btn) {
      btn.addEventListener("mouseenter", function () { if (!pinned) show(btn); });
      btn.addEventListener("mouseleave", function () { if (!pinned) show(null); });
      btn.addEventListener("focus", function () { show(btn); });
      btn.addEventListener("click", function () {
        pinned = pinned === btn ? null : btn;
        show(pinned);
        if (pinned && btn.dataset.panel) {
          var tab = document.getElementById("jn-tab-" + btn.dataset.panel);
          if (tab) tab.click();
        }
      });
    });
    hub.addEventListener("focusout", function (e) { if (!hub.contains(e.relatedTarget) && !pinned) show(null); });
  });
}());
