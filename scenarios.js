/* Scenario switch (DESIGN.md §4.14): a tablist of buttons over .scen-panel
   tabpanels. Without JS every panel shows, stacked; with it, one at a time.
   Selected = fill + border, never a tick. Arrow keys, Home and End move. */
(function () {
  function init(list) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
    function panel(tab) { return document.getElementById(tab.getAttribute('aria-controls')); }
    function select(tab, focus, initial) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        var p = panel(t);
        if (p) { p.hidden = !on; p.tabIndex = 0; }
      });
      if (focus) tab.focus();
      // Charts drawn at load inside a hidden panel redraw on resize.
      if (!initial) window.dispatchEvent(new Event('resize'));
    }
    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () { select(tab, false); });
      tab.addEventListener('keydown', function (e) {
        var j = null;
        if (e.key === 'ArrowRight') j = (i + 1) % tabs.length;
        else if (e.key === 'ArrowLeft') j = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === 'Home') j = 0;
        else if (e.key === 'End') j = tabs.length - 1;
        if (j !== null) { e.preventDefault(); select(tabs[j], true); }
      });
    });
    var current = tabs.filter(function (t) { return t.getAttribute('aria-selected') === 'true'; })[0] || tabs[0];
    list.classList.add('is-live');
    select(current, false, true);
  }
  function run() { Array.prototype.forEach.call(document.querySelectorAll('.scen-switch[role="tablist"]'), init); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
})();
