"""Every help reference on a page points at an entry that exists."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import glossary

ROOT = Path(__file__).resolve().parent.parent


class Glossary(unittest.TestCase):
    def test_referenced_terms_exist(self):
        sources = [*(ROOT / "views").glob("*.py"), ROOT / "shell.py"]
        used = set()
        for path in sources:
            text = path.read_text(encoding="utf-8")
            for block in re.findall(r"terms=\[([^\]]*)\]", text):
                used.update(re.findall(r'"([a-z0-9_]+)"', block))
            used.update(re.findall(r'(?:glossary\.short|_help)\("([a-z0-9_]+)"\)', text))
        self.assertTrue(used)
        self.assertEqual(used - set(glossary.TERMS), set())
        self.assertEqual(set(glossary.FIELDS.values()) - set(glossary.TERMS), set())

    def test_every_entry_says_what_and_why(self):
        for key, item in glossary.TERMS.items():
            self.assertTrue(item.what and item.why and item.group, key)
