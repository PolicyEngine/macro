/* Section sub-nav (r12 shell): at 820px and below, the topic links fold into
   one "Topics" menu so the row fits; wider screens show them inline. Without
   script the row simply scrolls (with a fade cue). site_nav.render adds this
   file to every page that carries .economy-subnav. */
(function () {
  document.querySelectorAll(".economy-subnav .economy-topics").forEach(function (row) {
    var topics = Array.from(row.querySelectorAll("a")).filter(function (a) {
      return /\/topics\//.test(a.getAttribute("href") || "");
    });
    if (topics.length < 2) return;
    var current = topics.find(function (a) { return a.hasAttribute("aria-current"); });
    var wrap = document.createElement("div");
    wrap.className = "topics-menu";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "model-tabs-link topics-btn";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-haspopup", "true");
    btn.textContent = current ? current.textContent.trim() : "Topics";
    var chev = document.createElement("span");
    chev.className = "topics-chev";
    chev.setAttribute("aria-hidden", "true");
    btn.appendChild(chev);
    if (current) btn.setAttribute("aria-current", "true");
    var pop = document.createElement("div");
    pop.className = "topics-pop";
    pop.id = "topics-pop-" + Math.random().toString(36).slice(2, 7);
    btn.setAttribute("aria-controls", pop.id);
    topics[0].parentNode.insertBefore(wrap, topics[0]);
    topics.forEach(function (a) { pop.appendChild(a); });
    wrap.appendChild(btn);
    /* The row scrolls and masks its edge, which would clip a dropdown inside
       it; the list lives on <body> at narrow widths and inline when wide. */
    var mq = window.matchMedia("(max-width: 820px)");
    function home() {
      if (mq.matches) { if (pop.parentNode !== document.body) document.body.appendChild(pop); }
      else if (pop.parentNode !== wrap) { wrap.appendChild(pop); }
    }
    home();
    if (mq.addEventListener) mq.addEventListener("change", home);
    function place() {
      var r = btn.getBoundingClientRect();
      pop.style.top = Math.round(r.bottom + 4) + "px";
      pop.style.left = Math.round(Math.min(r.left, window.innerWidth - 240)) + "px";
    }
    function set(open) {
      wrap.classList.toggle("open", open);
      pop.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", String(open));
      if (open) place();
    }
    btn.addEventListener("click", function (e) { e.stopPropagation(); set(!wrap.classList.contains("open")); });
    document.addEventListener("click", function (e) { if (!wrap.contains(e.target) && !pop.contains(e.target)) set(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { set(false); btn.focus(); } });
    window.addEventListener("scroll", function () { if (wrap.classList.contains("open")) place(); }, { passive: true });
    window.addEventListener("resize", function () { set(false); });
  });
}());
