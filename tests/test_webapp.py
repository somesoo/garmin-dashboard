"""The dashboard is installable as a standalone app (webapp.py, pwa/dashboard.webmanifest)."""

import json
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
