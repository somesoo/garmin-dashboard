"""The way in for a friend: sign-in page, first visit without data, the account page's settings."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from core import auth
from core import sync
from core import tenant
from etl import garmin_auth
from tests.helpers import people

ROOT = Path(__file__).resolve().parents[1]
PAGE = f"""
import sys; sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from core import tenant
st.session_state[tenant.SESSION_KEY] = "y"
from views import account
account.render()
"""


def field(at, label: str):
    return next(t for t in at.text_input if t.label == label)


def texts(at) -> str:
    return " ".join(str(m.value) for m in (*at.markdown, *at.caption, *at.info, *at.warning, *at.error, *at.success))


class Registry(unittest.TestCase):
    def test_update_name_and_source_with_validation(self):
        with people({"x": {}, "y": {"source": "apple"}}):
            self.assertEqual(tenant.update("y", name="  Ygrek   Nowak ").name, "Ygrek Nowak")
            self.assertEqual(tenant.update("y", source="garmin").source, "garmin")
            with self.assertRaises(ValueError):
                tenant.update("y", source="fitbit")
            with self.assertRaises(ValueError):
                tenant.update("y", root="..")
            with self.assertRaises(ValueError):
                tenant.update("y", name="   ")
            self.assertEqual(tenant.get("x").source, "garmin", "the other person is untouched")

    def test_single_user_layout_gets_a_registry_on_first_change(self):
        with people({}):
            tenant.REGISTRY.unlink()
            person = tenant.update(tenant.LEGACY_ID, name="Ja")
            self.assertEqual((person.name, person.legacy, person.local), ("Ja", True, True))
            self.assertEqual(len(tenant.users()), 1)


class AccountPage(unittest.TestCase):
    def setUp(self):
        self.enterContext(people({"x": {}, "y": {"source": "garmin"}}))
        self.start = self.enterContext(mock.patch.object(sync, "start", return_value=True))

    def test_profile_name_and_source_switch(self):
        at = AppTest.from_string(PAGE, default_timeout=60).run()
        self.assertFalse(at.exception)
        self.assertIn("Zacznijmy", texts(at), "no data yet: the welcome is shown")
        field(at, "Jak Cię nazywać").input("Ygrek")
        form_submit = [b for b in at.button if b.label == "Zapisz"][0]
        form_submit.click().run()
        self.assertEqual(tenant.get("y").name, "Ygrek")
        at.radio(key="acc_source_choice").set_value("apple").run()
        at.button(key="acc_source_save").click().run()
        self.assertEqual(tenant.get("y").source, "apple")
        self.assertFalse(at.exception)

    def test_garmin_sign_in_with_a_code_then_a_year_of_history(self):
        pending = garmin_auth.Pending(api=object(), state="state")
        with mock.patch.object(garmin_auth, "start", return_value=("mfa", pending)) as begin, \
                mock.patch.object(garmin_auth, "finish", return_value="Ygrek G.") as finish:
            at = AppTest.from_string(PAGE, default_timeout=60).run()
            email, password = field(at, "E-mail Garmin"), field(at, "Hasło Garmin")
            email.input("y@example.com")
            password.input("secret-pass")
            [b for b in at.button if b.label == "Połącz z Garmin Connect"][0].click().run()
            self.assertEqual(begin.call_args.args[:2], ("y@example.com", "secret-pass"))
            self.assertIn("kod", texts(at).lower())
            field(at, "Kod").input("123456")
            [b for b in at.button if b.label == "Potwierdź"][0].click().run()
            finish.assert_called_once()
            self.assertEqual(finish.call_args.args[1], "123456")
        args = self.start.call_args.args[0]
        self.assertEqual(args[0], "--backfill", "a newcomer gets a year of history")
        self.assertFalse(at.exception)

    def test_wrong_password_is_a_sentence_not_a_trace(self):
        with mock.patch.object(garmin_auth, "start", side_effect=RuntimeError("401 Unauthorized")):
            at = AppTest.from_string(PAGE, default_timeout=60).run()
            field(at, "E-mail Garmin").input("y@example.com")
            field(at, "Hasło Garmin").input("bad")
            [b for b in at.button if b.label == "Połącz z Garmin Connect"][0].click().run()
        self.assertIn("nie przyjął", texts(at))
        self.assertNotIn("401", texts(at))
        self.start.assert_not_called()


SIGNIN = f"""
import sys; sys.path.insert(0, {str(ROOT)!r})
from core import auth
auth.gate()
import streamlit as st
st.write("INSIDE")
"""


class SignIn(unittest.TestCase):
    def test_sign_in_page_and_unknown_account(self):
        with people({"x": {"identities": ["x@example.com"]}, "y": {"identities": ["y@example.com"]}}), \
                mock.patch.object(auth, "_oidc_configured", return_value=True):
            with mock.patch.object(auth.st, "user", mock.Mock(is_logged_in=False)):
                at = AppTest.from_string(SIGNIN, default_timeout=60).run()
                self.assertIn("Zaloguj przez Google", [b.label for b in at.button])
                self.assertNotIn("INSIDE", texts(at))
            stranger = mock.Mock(is_logged_in=True)
            stranger.get.side_effect = {"email": "<b>evil</b>@example.com", "email_verified": True}.get
            with mock.patch.object(auth.st, "user", stranger):
                at = AppTest.from_string(SIGNIN, default_timeout=60).run()
                self.assertIn("Zaloguj innym kontem", [b.label for b in at.button])
                self.assertIn("&lt;b&gt;evil", texts(at), "the address is escaped")

    def test_first_sign_in_takes_the_google_name(self):
        with people({"x": {"identities": ["x@example.com"]}, "y": {"identities": ["y@example.com"]}}), \
                mock.patch.object(auth, "_oidc_configured", return_value=True):
            user = mock.Mock(is_logged_in=True)
            user.get.side_effect = {"email": "y@example.com", "email_verified": True, "name": "Ygrek Nowak"}.get
            with mock.patch.object(auth.st, "user", user):
                at = AppTest.from_string(SIGNIN, default_timeout=60).run()
            self.assertIn("INSIDE", texts(at))
            self.assertEqual(tenant.get("y").name, "Ygrek Nowak")


APP = str(ROOT / "app.py")


class FirstVisit(unittest.TestCase):
    def test_no_data_opens_the_account_page_only(self):
        with people({"y": {"source": "apple"}}), mock.patch.object(auth, "_is_local", return_value=True):
            at = AppTest.from_file(APP, default_timeout=120).run()
            self.assertFalse(at.exception)
            self.assertIn("Zacznijmy", texts(at))
            self.assertTrue(any(r.key == "acc_source_choice" for r in at.radio))


if __name__ == "__main__":
    unittest.main()
