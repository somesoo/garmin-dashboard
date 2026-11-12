"""OSM integration: request scheduling and deployment referrer policies."""

import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class MapTiles(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the tile loader tests")
    def test_browser_loader(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", str(ROOT / "tests" / "osm_tiles.test.mjs")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_proxy_allows_origin_referrers_to_map_providers(self):
        for name in ("Caddyfile", "nginx-garmin.conf"):
            with self.subTest(proxy=name):
                source = (ROOT / "deploy" / name).read_text(encoding="utf-8")
                self.assertRegex(source, r'Referrer-Policy\s+"strict-origin-when-cross-origin"')

    def test_component_and_preview_identify_the_site_and_credit_osm(self):
        class Document(HTMLParser):
            def __init__(self):
                super().__init__()
                self.referrer = None
                self.links = []

            def handle_starttag(self, tag, attributes):
                attributes = dict(attributes)
                if tag == "meta" and attributes.get("name") == "referrer":
                    self.referrer = attributes.get("content")
                if tag == "a":
                    self.links.append(attributes.get("href"))

        for name in ("globe/index.html", "globe/test.html", "replay/index.html"):
            with self.subTest(document=name):
                document = Document()
                document.feed((ROOT / "ui" / "components" / name).read_text(encoding="utf-8"))
                self.assertEqual(document.referrer, "strict-origin-when-cross-origin")
                self.assertIn("https://www.openstreetmap.org/copyright", document.links)


if __name__ == "__main__":
    unittest.main()
