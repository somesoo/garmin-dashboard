"""The dashboard itself as an app on the phone's home screen (full screen, no address bar).

Streamlit's page has no web app manifest and no Apple meta tags, so a dashboard
added to the home screen opened as an ordinary browser tab: address bar on top,
browser navigation at the bottom. ``head()`` puts them into the page's <head>
on every run, before sign-in (so the sign-in screen can be installed too):

- the manifest (``pwa/dashboard.webmanifest``: ``start_url``/``scope`` ``/``,
  ``display: standalone``) is served by the API next to the phone app, at
  ``/api/app/dashboard.webmanifest`` -- same origin through the proxy, no new route;
- ``apple-mobile-web-app-capable`` + a touch icon for iOS, which reads them from
  the page when "Add to Home Screen" is tapped;
- a service worker (``pwa/dashboard-sw.js``) registered for scope ``/``.

**The worker is what buys the window.** Android (Chrome, Samsung Internet) hands
a home-screen icon its own window only when the manifest's ``start_url`` lies in
the scope of a worker with a fetch handler; with the manifest alone it quietly
makes a bookmark instead, and a bookmark always wears the address bar. The file
is served from ``/api/app/`` like everything else here, and claims the scope
above itself through the ``Service-Worker-Allowed: /`` header (``api.py``).

Without the API (one person, no ``GARMIN_API_PORT``) the manifest link answers
404 and nothing changes. The small summary app under ``/api/app/`` (pwa/) is a
separate app with its own manifest and scope.
"""

from __future__ import annotations

import json

import streamlit as st

MANIFEST = "/api/app/dashboard.webmanifest"
ICON = "/api/app/icon-192.png"
WORKER = "/api/app/dashboard-sw.js"

TAGS = [
    ("link", {"rel": "manifest", "href": MANIFEST}),
    ("link", {"rel": "apple-touch-icon", "href": ICON}),
    ("meta", {"name": "apple-mobile-web-app-capable", "content": "yes"}),
    ("meta", {"name": "mobile-web-app-capable", "content": "yes"}),
    # "black", not "black-translucent": the top line of the page must not slide under the clock.
    ("meta", {"name": "apple-mobile-web-app-status-bar-style", "content": "black"}),
    ("meta", {"name": "apple-mobile-web-app-title", "content": "Dashboard"}),
    ("meta", {"name": "theme-color", "content": "#000000"}),
]

# Runs in the page itself (st.html) or, on an older Streamlit, from a component
# frame of the same origin (window.parent). Each tag is added once per page load.
SCRIPT = """<script>
(() => {
  let doc = document;
  try { if (window.frameElement && window.parent.document) doc = window.parent.document; } catch (e) {}
  for (const [tag, attrs] of %s) {
    const key = attrs.rel ? `${tag}[rel="${attrs.rel}"]` : `${tag}[name="${attrs.name}"]`;
    if (doc.head.querySelector(key)) continue;
    const el = doc.createElement(tag);
    for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, value);
    doc.head.appendChild(el);
  }
  // Without this the icon is a bookmark with an address bar (module docstring).
  if (navigator.serviceWorker) navigator.serviceWorker.register(%s, { scope: "/" }).catch(() => {});
})();
</script>""" % (json.dumps([[tag, attrs] for tag, attrs in TAGS]), json.dumps(WORKER))


def head() -> None:
    """Make the page installable as a standalone app (see the module docstring)."""
    try:
        st.html(SCRIPT, unsafe_allow_javascript=True)
    except TypeError:  # Streamlit without unsafe_allow_javascript
        import streamlit.components.v1 as components

        components.html(SCRIPT, height=0)
