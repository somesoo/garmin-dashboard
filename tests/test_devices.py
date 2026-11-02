"""views/devices.py in a headless app run: a key is made, shown once, and only its hash is kept."""

from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

import api
import tenant
from tests.helpers import people

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = f"""
import sys; sys.path.insert(0, {str(ROOT)!r})
import streamlit as st, tenant
st.session_state[tenant.SESSION_KEY] = "y"
from views import devices
devices.render()
"""


class Devices(unittest.TestCase):
    def test_push_key_is_shown_once_and_stored_hashed(self):
        with people({"x": {}, "y": {"source": "apple"}}):
            at = AppTest.from_string(SCRIPT, default_timeout=60).run()
            self.assertFalse(at.exception)
            at.button(key="dev_make_ingest").click().run()
            shown = [c.value for c in at.code if c.value.startswith(api.TOKEN_PREFIX)]
            self.assertEqual(len(shown), 1)
            token = shown[0]
            self.assertEqual(api.verify(token, "ingest").id, "y")
            self.assertNotIn(token, api.tokens_path(tenant.get("y")).read_text())
            at.run()  # a rerun: the key is gone from the page
            self.assertFalse([c.value for c in at.code if c.value.startswith(api.TOKEN_PREFIX)])
            self.assertEqual(api.list_tokens(tenant.get("x")), [], "the other person got nothing")

    def test_delete_needs_the_name_and_spares_the_other_person(self):
        with people({"x": {}, "y": {"source": "apple", "name": "Ygrek"}}):
            for who in ("x", "y"):
                folder = tenant.get(who).root / "tables"
                folder.mkdir(parents=True)
                (folder / "daily.parquet").write_text("p")
            at = AppTest.from_string(SCRIPT, default_timeout=60).run()
            self.assertTrue(at.button(key="dev_erase").disabled)
            at.text_input(key="dev_erase_name").input("Ygrek").run()
            self.assertFalse(at.button(key="dev_erase").disabled)
            at.button(key="dev_erase").click().run()
            self.assertFalse(at.exception)
            self.assertFalse((tenant.get("y").root / "tables").exists())
            self.assertTrue((tenant.get("x").root / "tables" / "daily.parquet").exists())
            at.button(key="dev_archive").click().run()
            self.assertFalse(at.exception)


if __name__ == "__main__":
    unittest.main()
