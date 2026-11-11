"""Touch and pointer rules for the whole page: nothing reacts by accident.

* **Charts sleep until double-tapped.** A thumb scrolling the page over a chart used
  to pin a tooltip, and a drag zoomed it. Now a chart is inert until it is
  clicked once: on a touch screen the plot hands every touch back to the page
  (``pointer-events: none`` in ``shell.page_style``, so the tap lands on the
  chart's box); with a mouse the hover still reads values, but a drag or the
  wheel do nothing. One tap only shows how to wake it; a double tap (double
  click) arms it, and the chart says so in its corner. Armed, the chart zooms as
  Plotly does (double tap resets); a tap anywhere else puts it back to sleep.
* **Tabs follow a swipe.** A horizontal swipe over a tab's content (not over
  an armed chart, a map or a table that scrolls sideways) clicks the next or
  previous tab, and brings the tab bar back into view if it scrolled away.
* **No keyboard for a list.** A Streamlit select box is a search field, so on a
  phone opening it slid the keyboard over half the screen. On touch screens
  its input gets ``inputmode="none"``: the list opens, the keyboard does not.

One script in the page itself (as ``ui/webapp.py``), installed once.
"""

from __future__ import annotations

import streamlit as st

SCRIPT = """<script>
(() => {
  const doc = window.frameElement ? window.parent.document : document;
  if (doc.__garminGesture) return;
  doc.__garminGesture = true;
  const win = doc.defaultView;
  const touch = win.matchMedia("(hover: none)").matches;
  // The replay's own controls (play buttons, slider) work on a sleeping chart: they zoom nothing.
  const chart = (el) => el && el.closest && !el.closest('.updatemenu-container, .slider-container')
      && el.closest('[data-testid="stPlotlyChart"]');
  const sleep = (keep) => doc.querySelectorAll('[data-testid="stPlotlyChart"].armed')
      .forEach((c) => { if (c !== keep) { c.classList.remove("armed"); delete c.dataset.hint; } });
  // The words come from Python (install), in the page's language.
  const words = () => win.__garminGestureWords || { arm: "double tap to zoom", armed: "zoom on" };
  const hint = (c, text, ms) => {
    c.dataset.hint = text;
    clearTimeout(c.__hintTimer);
    if (ms) c.__hintTimer = setTimeout(() => { if (!c.classList.contains("armed")) delete c.dataset.hint; }, ms);
  };
  let last = { c: null, at: 0 };

  doc.addEventListener("click", (e) => {
    // A tab tapped by hand fades in; only a swipe slides from its side.
    const tab = e.isTrusted && e.target.closest && e.target.closest('[data-testid="stTabs"] [role="tab"]');
    if (tab) delete tab.closest('[data-testid="stTabs"]').dataset.swipe;
    const c = chart(e.target);
    sleep(c);
    if (!c || c.classList.contains("armed")) return;
    // Asleep: one tap only says how to wake it; two quick taps (or a double click) do.
    e.stopPropagation();
    const now = Date.now();
    if (last.c === c && now - last.at < 450) {
      c.classList.add("armed");
      hint(c, words().armed, 0);
      last = { c: null, at: 0 };
    } else {
      last = { c, at: now };
      hint(c, words().arm, 1800);
    }
  }, true);
  // A mouse: no drag-zoom and no wheel-zoom on a sleeping chart; the wheel scrolls the page.
  const guard = (e) => { const c = chart(e.target); if (c && !c.classList.contains("armed")) e.stopPropagation(); };
  ["mousedown", "wheel", "dblclick"].forEach((type) => doc.addEventListener(type, guard, { capture: true }));
  doc.addEventListener("keydown", (e) => { if (e.key === "Escape") sleep(null); }, true);

  // Swipe between tabs: horizontal, quick, clearly more sideways than down.
  let start = null;
  doc.addEventListener("touchstart", (e) => {
    const t = e.touches[0], panel = e.target.closest && e.target.closest('[data-testid="stTabs"] [role="tabpanel"]');
    const busy = e.target.closest && e.target.closest('.armed, .gt-wrap, .maplibregl-map, input, textarea, [data-baseweb="slider"]');
    start = panel && !busy && e.touches.length === 1 ? { x: t.clientX, y: t.clientY, at: Date.now(), panel } : null;
  }, { capture: true, passive: true });
  doc.addEventListener("touchend", (e) => {
    if (!start) return;
    const t = e.changedTouches[0], dx = t.clientX - start.x, dy = t.clientY - start.y;
    const tabs = start.panel.closest('[data-testid="stTabs"]'), took = Date.now() - start.at;
    start = null;
    if (took > 700 || Math.abs(dx) < 60 || Math.abs(dx) < 1.8 * Math.abs(dy)) return;
    const list = [...tabs.querySelectorAll('[role="tab"]')];
    const at = list.findIndex((b) => b.getAttribute("aria-selected") === "true");
    const next = list[at + (dx < 0 ? 1 : -1)];
    if (!next) return;
    tabs.dataset.swipe = dx < 0 ? "left" : "right";
    next.click();
    next.scrollIntoView({ block: "nearest", inline: "center" });
    const bar = tabs.querySelector('[role="tablist"]');
    if (bar && bar.getBoundingClientRect().top < 0) bar.scrollIntoView({ block: "start", behavior: "smooth" });
  }, { capture: true, passive: true });

  if (touch) {
    const quiet = () => doc.querySelectorAll(
        '[data-testid="stSelectbox"] input:not([inputmode="none"]), [data-testid="stMultiSelect"] input:not([inputmode="none"])')
      .forEach((i) => i.setAttribute("inputmode", "none"));
    quiet();
    new win.MutationObserver(quiet).observe(doc.body, { childList: true, subtree: true });
  }
})();
</script>"""


def install() -> None:
    """Put the script into the page (see the module docstring)."""
    import json

    from core import i18n

    words = json.dumps({
        "arm": i18n.tr(pl="dotknij dwa razy, aby przybliżać", en="double tap to zoom"),
        "armed": i18n.tr(pl="zoom włączony · dotknij obok, aby wyłączyć", en="zoom on · tap outside to stop"),
    })
    script = SCRIPT.replace("<script>", f"<script>\n(window.frameElement ? window.parent : window)"
                                        f".__garminGestureWords = {words};", 1)
    try:
        st.html(script, unsafe_allow_javascript=True)
    except TypeError:  # Streamlit without unsafe_allow_javascript
        import streamlit.components.v1 as components

        components.html(script, height=0)
