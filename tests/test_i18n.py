"""Both languages everywhere i18n.py says the interface is bilingual."""

from __future__ import annotations

import ast
import datetime as dt
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import i18n

ROOT = Path(__file__).resolve().parent.parent
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


def _untranslated(path: Path) -> list[str]:
    """Polish string literals that are not the ``pl=`` side of a translation.

    Docstrings are code documentation, not interface; a line marked
    ``# i18n: key`` holds an identifier (a column name), not text.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "pl":
                    allowed.update(id(child) for child in ast.walk(keyword.value))
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                allowed.add(id(body[0].value))
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and POLISH.search(node.value)
                and id(node) not in allowed and "# i18n: key" not in lines[node.lineno - 1]):
            found.append(f"{path.name}:{node.lineno}: {node.value!r}")
    return found


class Bilingual(unittest.TestCase):
    def test_no_polish_outside_translations(self):
        found = [line for name in i18n.BILINGUAL for line in _untranslated(ROOT / name)]
        self.assertEqual(found, [])

    def test_no_empty_english(self):
        for name in i18n.BILINGUAL:
            for node in ast.walk(ast.parse((ROOT / name).read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "tr":
                    for keyword in node.keywords:
                        if keyword.arg == "en" and isinstance(keyword.value, ast.Constant):
                            self.assertTrue(str(keyword.value.value).strip(), f"{name}:{node.lineno}")

    def test_every_page_has_a_title(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        paths = re.findall(r'_page\([\w.]+, "([^"]+)"', source)
        self.assertTrue(paths)
        self.assertEqual(set(paths), set(i18n._PAGES))


class Choice(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(i18n, "SETTINGS", Path(tempfile.mkdtemp()) / "ui.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_default_is_polish(self):
        self.assertEqual(i18n.lang(), "pl")
        self.assertEqual(i18n.tr(pl="dziś", en="today"), "dziś")

    def test_remembered_choice(self):
        i18n.remember("en")
        self.assertEqual(i18n.lang(), "en")
        self.assertEqual(i18n.tr(pl="dziś", en="today"), "today")
        self.assertEqual(i18n.day_month(dt.date(2026, 7, 26)), "26 Jul")
        self.assertEqual(i18n.weekdays(long=True)[2], "Wednesday")

    def test_unknown_language_falls_back(self):
        i18n.SETTINGS.write_text('{"lang": "de"}', encoding="utf-8")
        self.assertEqual(i18n.lang(), "pl")
        i18n.remember("de")
        self.assertEqual(i18n.lang(), "pl")

    def test_broken_file_falls_back(self):
        i18n.SETTINGS.write_text("not json", encoding="utf-8")
        self.assertEqual(i18n.lang(), "pl")
        i18n.remember("en")
        self.assertEqual(i18n.lang(), "en")


class Plural(unittest.TestCase):
    FORMS = dict(pl=("dzień", "dni", "dni"), en=("day", "days"))
    RUNS = dict(pl=("bieg", "biegi", "biegów"), en=("run", "runs"))

    def test_polish(self):
        with mock.patch.object(i18n, "lang", return_value="pl"):
            got = {n: i18n.plural(n, **self.RUNS) for n in (0, 1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 112, 122)}
        self.assertEqual(got, {0: "biegów", 1: "bieg", 2: "biegi", 4: "biegi", 5: "biegów", 11: "biegów",
                               12: "biegów", 14: "biegów", 21: "biegów", 22: "biegi", 25: "biegów",
                               112: "biegów", 122: "biegi"})

    def test_english(self):
        with mock.patch.object(i18n, "lang", return_value="en"):
            self.assertEqual([i18n.plural(n, **self.FORMS) for n in (0, 1, 2, 21)], ["days", "day", "days", "days"])


if __name__ == "__main__":
    unittest.main()
