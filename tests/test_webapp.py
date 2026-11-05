"""The dashboard is installable as a standalone app (webapp.py, pwa/dashboard.webmanifest)."""

import json
import unittest
from pathlib import Path

import api
from ui import webapp

PWA = Path(__file__).resolve().parent.parent / "pwa"


class DashboardManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((PWA / "dashboard.webmanifest").read_text(encoding="utf-8"))

    def test_full_screen_over_the_whole_site(self):
        self.assertEqual(self.manifest["display"], "standalone")
        self.assertEqual(self.manifest["start_url"], "/")
        self.assertEqual(self.manifest["scope"], "/")

    def test_icons_exist_with_install_sizes(self):
        sizes = set()
        for icon in self.manifest["icons"]:
            self.assertTrue((PWA / icon["src"]).exists(), icon["src"])
            sizes.add(icon["sizes"])
        self.assertTrue({"192x192", "512x512"} <= sizes)

    def test_served_next_to_the_phone_app(self):
        # The API mounts pwa/ at /api/app (api.py); the link and the icon point there.
        self.assertEqual(webapp.MANIFEST, "/api/app/" + "dashboard.webmanifest")
        self.assertTrue((PWA / Path(webapp.ICON).name).exists())

    def test_script_carries_every_tag(self):
        for _, attrs in webapp.TAGS:
            self.assertIn(json.dumps(attrs.get("rel") or attrs["name"]), webapp.SCRIPT)
        self.assertIn('"apple-mobile-web-app-capable"', webapp.SCRIPT)


class OwnWindow(unittest.TestCase):
    """The home-screen icon opens without an address bar only with a worker.

    The manifest and the Apple tags are not enough: Android hands a page its own
    window only when start_url lies in the scope of a service worker that has a
    fetch handler. Without one it silently makes a bookmark instead.
    """

    def setUp(self):
        self.worker = PWA / Path(webapp.WORKER).name

    def test_the_page_registers_a_worker_for_the_whole_site(self):
        self.assertTrue(self.worker.exists(), webapp.WORKER)
        self.assertIn(json.dumps(webapp.WORKER), webapp.SCRIPT)
        self.assertIn('scope: "/"', webapp.SCRIPT)

    def test_the_worker_answers_requests_and_is_allowed_above_its_folder(self):
        source = self.worker.read_text(encoding="utf-8")
        self.assertIn('addEventListener("fetch"', source)
        # It is served from /api/app/ but must claim "/"; the header that grants
        # that is checked against a real request in test_api.AppFiles.
        self.assertEqual(api.DASHBOARD_WORKER, self.worker.name)

    def test_neither_worker_empties_the_other_one_s_cache(self):
        # Caches are shared across the origin: a blanket "delete every cache but
        # mine" on activate would take the neighbour app offline.
        for name, prefix in ((webapp.WORKER, "gd-dashboard"), ("sw.js", "gd-shell")):
            source = (PWA / Path(name).name).read_text(encoding="utf-8")
            self.assertIn(f'key.startsWith("{prefix}")', source)


if __name__ == "__main__":
    unittest.main()
