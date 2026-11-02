"""auth.identify: which person a browser session is, and when it is nobody."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import auth
from tests.helpers import people

TWO = {"x": {"identities": ["x@example.com"], "local": True},
       "y": {"source": "apple", "identities": ["y@example.com"]}}


def _context(headers: dict | None = None, ip: str | None = "100.64.0.7"):
    """Stand-ins for st.context: request headers (lower-case) and the peer address."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    return [mock.patch.object(auth, "_header", side_effect=lambda name: headers.get(name.lower())),
            mock.patch.object(auth.st, "context", mock.Mock(ip_address=ip))]


class Identify(unittest.TestCase):
    def enter(self, *patches):
        for patch in patches:
            self.enterContext(patch)

    def setUp(self):
        self.enter(mock.patch.object(auth, "_oidc_configured", return_value=False),
                   mock.patch.dict(os.environ, {auth.HEADER_ENV: ""}))

    def who(self):
        person, presented = auth.identify()
        return (person.id if person else None), presented

    def test_single_person_needs_no_sign_in(self):
        self.enterContext(people({"x": {}}))
        self.enter(mock.patch.object(auth, "_is_local", return_value=False))
        self.assertEqual(self.who(), ("x", None))

    def test_trusted_header_picks_the_person(self):
        self.enterContext(people(TWO))
        self.enter(mock.patch.dict(os.environ, {auth.HEADER_ENV: "Tailscale-User-Login"}),
                   *_context({"Tailscale-User-Login": "Y@example.com"}))
        self.assertEqual(self.who(), ("y", "Y@example.com"))

    def test_unknown_identity_is_refused_even_from_this_machine(self):
        self.enterContext(people(TWO))
        self.enter(mock.patch.dict(os.environ, {auth.HEADER_ENV: "Tailscale-User-Login"}),
                   *_context({"Tailscale-User-Login": "stranger@example.com"}, ip=None))
        self.assertEqual(self.who(), (None, "stranger@example.com"))

    def test_header_is_ignored_unless_the_operator_trusts_it(self):
        self.enterContext(people(TWO))
        self.enter(*_context({"Tailscale-User-Login": "y@example.com"}))
        self.assertEqual(self.who(), (None, None))

    def test_browser_on_this_machine_is_the_local_person(self):
        self.enterContext(people(TWO))
        self.enter(*_context({}, ip=None))
        self.assertEqual(self.who(), ("x", None))
        self.enter(*_context({}, ip="::1"))
        self.assertEqual(self.who(), ("x", None))

    def test_proxied_request_is_not_local(self):
        """`tailscale serve` connects from 127.0.0.1: without its header trusted it must not become x."""
        self.enterContext(people(TWO))
        self.enter(*_context({"X-Forwarded-For": "100.64.0.9"}, ip=None))
        self.assertEqual(self.who(), (None, None))

    def test_remote_without_identity_is_nobody(self):
        self.enterContext(people(TWO))
        self.enter(*_context({}, ip="192.168.1.20"))
        self.assertEqual(self.who(), (None, None))

    def test_no_local_person_marked_means_nobody(self):
        self.enterContext(people({"x": {}, "y": {}}))
        self.enter(*_context({}, ip=None))
        self.assertEqual(self.who(), (None, None))

    def test_with_google_configured_this_machine_is_nobody_until_signed_in(self):
        self.enterContext(people(TWO))
        self.enter(mock.patch.object(auth, "_oidc_configured", return_value=True),
                   mock.patch.object(auth.st, "user", mock.Mock(is_logged_in=False)),
                   mock.patch.dict(os.environ, {auth.HEADER_ENV: "Tailscale-User-Login"}),
                   *_context({"Tailscale-User-Login": "x@example.com"}, ip=None))
        self.assertEqual(self.who(), (None, None))

    def test_two_google_accounts_two_people(self):
        self.enterContext(people(TWO))
        self.enter(mock.patch.object(auth, "_oidc_configured", return_value=True), *_context({}, ip=None))
        for email, expected in (("x@example.com", "x"), ("Y@Example.com", "y")):
            user = mock.Mock(is_logged_in=True)
            user.get.side_effect = {"email": email, "email_verified": True}.get
            with mock.patch.object(auth.st, "user", user):
                self.assertEqual(self.who()[0], expected)

    def test_unverified_email_is_refused(self):
        self.enterContext(people(TWO))
        user = mock.Mock(is_logged_in=True)
        user.get.side_effect = {"email": "x@example.com", "email_verified": False}.get
        self.enter(mock.patch.object(auth, "_oidc_configured", return_value=True),
                   mock.patch.object(auth.st, "user", user), *_context({}, ip=None))
        self.assertEqual(self.who(), (None, "x@example.com"))

    def test_oidc_email_picks_the_person(self):
        self.enterContext(people(TWO))
        user = mock.Mock(is_logged_in=True)
        user.get.return_value = "x@example.com"
        self.enter(mock.patch.object(auth, "_oidc_configured", return_value=True),
                   mock.patch.object(auth.st, "user", user), *_context({}, ip="192.168.1.20"))
        self.assertEqual(self.who(), ("x", "x@example.com"))


class Setup(unittest.TestCase):
    def test_secrets_file_is_private_and_refuses_plain_http(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(auth, "SECRETS", Path(folder) / "s.toml"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(auth.setup(["http://example.com"]), 1)
            self.assertEqual(auth.setup(["https://mac.tail1234.ts.net/"]), 0)
            text = auth.SECRETS.read_text()
            self.assertIn('redirect_uri = "https://mac.tail1234.ts.net/oauth2callback"', text)
            self.assertEqual(auth.SECRETS.stat().st_mode & 0o777, 0o600)
            self.assertEqual(auth.setup(["https://other"]), 1, "an existing file is not overwritten")


class ServeFlags(unittest.TestCase):
    def test_several_people_bind_to_localhost_and_pass_secrets(self):
        import serve

        with people(TWO), tempfile.TemporaryDirectory() as folder:
            secrets_file = Path(folder) / "secrets.toml"
            secrets_file.write_text("[auth]\n")
            with mock.patch.object(auth, "SECRETS", secrets_file):
                flags = serve.security_flags([])
                self.assertIn("127.0.0.1", flags)
                self.assertIn(str(secrets_file), flags)
                self.assertNotIn("127.0.0.1", serve.security_flags(["--server.address", "0.0.0.0"]))
        with people({"x": {}}), mock.patch.object(auth, "SECRETS", Path("/nonexistent/secrets.toml")):
            flags = serve.security_flags([])
            self.assertNotIn("--server.address", flags)
            self.assertNotIn("--secrets.files", flags)
            self.assertIn("--browser.gatherUsageStats", flags)


if __name__ == "__main__":
    unittest.main()
