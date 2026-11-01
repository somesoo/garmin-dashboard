"""Wayfinding stays in step with the menu: every page has its question, every
"Dalej" link points at a page (and a view) that exists."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import guide
import i18n
from views import hubs

ROOT = Path(__file__).resolve().parent.parent
VIEWS = {hubs.PLAN: {"plan", "races"}, hubs.LOAD: {"run", "all"}, hubs.SPORT: {"today", "disciplines"}}


def _menu() -> set[str]:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    return set(re.findall(r'_page\([\w.]+, "([^"]+)"', source))


class Guide(unittest.TestCase):
    def test_every_page_has_a_title_and_a_question(self):
        pages = _menu()
        self.assertIn("dzis", pages)
        for url_path in pages:
            self.assertTrue(i18n.page(url_path))
            self.assertIn(url_path, guide._questions(), url_path)

    def test_next_links_exist(self):
        pages = _menu()
        for source, steps in guide.NEXT.items():
            self.assertIn(source, pages)
            for target, switch, view in steps:
                self.assertIn(target, pages, f"{source} -> {target}")
                if switch:
                    self.assertIn(view, VIEWS[switch], f"{source} -> {target}/{view}")
                    self.assertTrue(guide._label(target, view))

    def test_no_dead_ends(self):
        # Dziś computes its links from today's state; every other page has fixed ones.
        self.assertEqual(_menu() - set(guide.NEXT) - {"dzis"}, set())


if __name__ == "__main__":
    unittest.main()
