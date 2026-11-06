"""Touch and pointer rules for the whole page: nothing reacts by accident.

* **Charts sleep until tapped.** A thumb scrolling the page over a chart used
  to pin a tooltip, and a drag zoomed it. Now a chart is inert until it is
  clicked once: on a touch screen the plot hands every touch back to the page
  (``pointer-events: none`` in ``shell.page_style``, so the tap lands on the
  chart's box and arms it); with a mouse the hover still reads values, but a
  drag or the wheel do nothing until the click. Armed, the chart zooms as
  Plotly does (double tap resets); a tap anywhere else puts it back to sleep.
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
  const chart = (el) => el && el.closest && el.closest('[data-testid="stPlotlyChart"]');
  const sleep = (keep) => doc.querySelectorAll('[data-testid="stPlotlyChart"].armed')
      .forEach((c) => { if (c !== keep) c.classList.remove("armed"); });

  doc.addEventListener("click", (e) => {
    const c = chart(e.target);
    sleep(c);
    if (c && !c.classList.contains("armed")) { c.classList.add("armed"); e.stopPropagation(); }
  }, true);
  // A mouse: no drag-zoom and no wheel-zoom on a sleeping chart; the wheel scrolls the page.
  const guard = (e) => { const c = chart(e.target); if (c && !c.classList.contains("armed")) e.stopPropagation(); };
  ["mousedown", "wheel", "dblclick"].forEach((type) => doc.addEventListener(type, guard, { capture: true }));
  doc.addEventListener("keydown", (e) => { if (e.key === "Escape") sleep(null); }, true);

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
    try:
        st.html(SCRIPT, unsafe_allow_javascript=True)
    except TypeError:  # Streamlit without unsafe_allow_javascript
        import streamlit.components.v1 as components

        components.html(SCRIPT, height=0)
