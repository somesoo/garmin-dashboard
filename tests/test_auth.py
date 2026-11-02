"""auth.identify: which person a browser session is, and when it is nobody."""

from __future__ import annotations

import os
import unittest
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

    def test_oidc_email_picks_the_person(self):
        self.enterContext(people(TWO))
        user = mock.Mock(is_logged_in=True)
        user.get.return_value = "x@example.com"
        self.enter(mock.patch.object(auth, "_oidc_configured", return_value=True),
                   mock.patch.object(auth.st, "user", user), *_context({}, ip="192.168.1.20"))
        self.assertEqual(self.who(), ("x", "x@example.com"))


if __name__ == "__main__":
    unittest.main()
