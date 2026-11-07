"""The level of detail (core/level.py): what a person sees in the menu."""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from core import config, level, tenant
from tests.helpers import people, person

ROOT = Path(__file__).resolve().parents[1]


class Level(unittest.TestCase):
    def test_nobody_loses_anything_without_a_choice(self):
        with person():
            self.assertEqual(level.current(), "expert")
            self.assertTrue(all(level.lists(url) for url in level.PAGES))

    def test_choice_is_remembered_next_to_the_language(self):
        with person() as who:
            who.ui_settings.parent.mkdir(parents=True, exist_ok=True)
            who.ui_settings.write_text('{"lang": "en"}', encoding="utf-8")
            level.remember("basic")
            saved = json.loads(who.ui_settings.read_text(encoding="utf-8"))
            self.assertEqual(saved, {"lang": "en", "level": "basic"})
            self.assertEqual(level.current(), "basic")
            level.remember("nonsense")
            self.assertEqual(level.current(), "basic", "an unknown level is not saved")

    def test_pages_leave_the_menu_by_level(self):
        with person():
            level.remember("basic")
            self.assertTrue(level.lists("dzien") and level.lists("sen") and level.lists("slownik"))
            self.assertFalse(level.lists("obciazenie-biegowe"))
            self.assertFalse(level.lists("sql"))
            level.remember("standard")
            self.assertTrue(level.lists("obciazenie-biegowe"))
            self.assertFalse(level.lists("fizjologia"))
            self.assertTrue(level.shows("basic") and level.shows("standard") and not level.shows("expert"))

    def test_levelled_pages_exist(self):
        """Every url path in level.PAGES is a page in app.py: a typo would hide nothing."""
        paths = set(re.findall(r'_page\([\w.]+, "([^"]*)"', (ROOT / "app.py").read_text(encoding="utf-8")))
        self.assertTrue(set(level.PAGES) <= paths, set(level.PAGES) - paths)

    def test_a_new_person_starts_basic(self):
        args = argparse.Namespace(id="y", name=None, source="apple", identity=None, local=False)
        with people({"x": {}}) as base, mock.patch.object(config, "DATA", base), contextlib.redirect_stdout(None):
            self.assertEqual(tenant.add(args), 0)
            saved = json.loads(tenant.get("y").ui_settings.read_text(encoding="utf-8"))
            self.assertEqual(saved["level"], "basic")


if __name__ == "__main__":
    unittest.main()
