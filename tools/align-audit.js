/* Alignment audit (r14). Paste into the console, or load with
   <script src="/tools/align-audit.js">, to list blocks whose left or right
   edge leaves the content column, or sit at a stray inset (1–40px in from
   the column edge) without being inside a card. Column edges come from the
   tab bar's first link and the header brand, so they follow the shell.
   window.alignAudit(document) returns the list; ?audit=1 also outlines the
   offenders on the page. */
(function () {
  function card(el) {
    for (var p = el.parentElement; p && p.tagName !== "MAIN"; p = p.parentElement) {
      var cs = getComputedStyle(p);
      if ((parseFloat(cs.borderLeftWidth) > 0 && cs.borderLeftStyle !== "none") ||
          (cs.backgroundColor !== "rgba(0, 0, 0, 0)" && cs.backgroundColor !== "transparent")) return true;
    }
    return false;
  }
  function audit(doc) {
    var win = doc.defaultView;
    var brand = doc.querySelector(".brand-logo");
    var W = doc.documentElement.clientWidth;
    var colL = brand ? Math.round(brand.getBoundingClientRect().left) : 0;
    var tab = doc.querySelector(".nav-links a"); if (tab) colL = Math.round(tab.getBoundingClientRect().left + parseFloat(getComputedStyle(tab).paddingLeft));
    var colR = W - colL;
    var out = [];
    var sel = "main h1, main .lede, main .sh, main .band-head, main .economy-subnav-row > *, main section > p, main section > .lp-wrap > p, " +
      "main .table-scroll, main .xp, main .ab-card, main .mp-card, main .lp-score-card, main .hub2 > *, main .hub, main .pp-list, main .tr-list, " +
      "main .mc-grid, main .lp-models, main figure, main .vc-fig, main .stat-grid, main .sc-card, main dl.kv, main .tbl-notes, main .callout";
    doc.querySelectorAll(sel).forEach(function (el) {
      if (!el.offsetWidth || card(el)) return;
      var r = el.getBoundingClientRect();
      var cs = win.getComputedStyle(el);
      var l = Math.round(r.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth));
      var rr = Math.round(r.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth));
      var boxed = (parseFloat(cs.borderLeftWidth) > 0 && cs.borderLeftStyle !== "none") ||
        (cs.backgroundColor !== "rgba(0, 0, 0, 0)" && cs.backgroundColor !== "transparent");
      if (boxed) {
        l = Math.round(r.left); rr = Math.round(r.right);
      }
      var issue = [];
      if (l < colL - 2) issue.push("left outside column (" + l + " < " + colL + ")");
      else if (l > colL + 2 && l <= colL + 40) issue.push("stray left inset " + (l - colL) + "px");
      if (rr > colR + 2) issue.push("right outside column (" + rr + " > " + colR + ")");
      if (issue.length) {
        out.push({ el: el.tagName.toLowerCase() + "." + (el.className || "").toString().split(" ").slice(0, 2).join("."), text: (el.textContent || "").trim().slice(0, 40), issue: issue.join("; ") });
        if (/audit=1/.test(win.location.search)) el.style.outline = "2px solid #D97706";
      }
    });
    return { colL: colL, colR: colR, offenders: out };
  }
  window.alignAudit = audit;
  if (/audit=1/.test(location.search)) console.table(audit(document).offenders);
}());
