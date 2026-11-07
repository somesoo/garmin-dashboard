"""Privacy: sealed tokens, consent, retention, the access log, encrypted backups (docs/PRYWATNOSC.md)."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import api
from core import audit
from core import monitor
from core import privacy
from core import secretbox
from core import sync
from core import tenant
from etl import garmin_auth
from tests.helpers import consent, people
from tests.test_api import call, push
from tools import backup

TWO = {"x": {"admin": True, "identities": ["x@example.com"]}, "y": {"source": "apple", "identities": ["y@example.com"]}}
TOKENS = json.dumps({"di_token": "access", "di_refresh_token": "refresh", "di_client_id": "client"})


class SealedTokens(unittest.TestCase):
    def setUp(self):
        self.enterContext(people({"x": {}}, current="x"))
        self.store = str(tenant.current().root / "garmin")

    def test_tokens_never_rest_in_clear_text(self):
        garmin_auth.store(self.store, TOKENS)
        folder = Path(self.store)
        self.assertFalse((folder / garmin_auth.TOKEN_FILE).exists())
        sealed = (folder / garmin_auth.SEALED_FILE).read_bytes()
        self.assertNotIn(b"refresh", sealed)
        self.assertEqual((folder / garmin_auth.SEALED_FILE).stat().st_mode & 0o777, 0o600)
        self.assertEqual(garmin_auth.load(self.store), TOKENS)
        self.assertTrue(garmin_auth.connected(self.store))

    def test_a_plain_file_from_before_is_sealed_on_first_read(self):
        folder = Path(self.store)
        folder.mkdir(parents=True)
        (folder / garmin_auth.TOKEN_FILE).write_text(TOKENS)
        self.assertEqual(garmin_auth.load(self.store), TOKENS)
        self.assertFalse((folder / garmin_auth.TOKEN_FILE).exists())
        self.assertTrue((folder / garmin_auth.SEALED_FILE).exists())

    def test_the_key_lives_outside_data_and_another_key_cannot_open(self):
        garmin_auth.store(self.store, TOKENS)
        self.assertNotIn(tenant.current().root, secretbox.key_path().parents)
        with tempfile.TemporaryDirectory() as other, \
                mock.patch.dict(os.environ, {secretbox.KEY_ENV: str(Path(other) / "k")}):
            with self.assertRaises(secretbox.Unreadable):
                garmin_auth.load(self.store)

    def test_a_refresh_during_a_pull_is_sealed_back(self):
        garmin_auth.store(self.store, TOKENS)

        class Client:
            def __init__(self):
                self.payload = None

            def loads(self, text):
                self.payload = text

            def dumps(self):
                return self.payload

        class FakeGarmin:
            def __init__(self):
                self.client = Client()

            def login(self, tokenstore):
                self.client.loads(tokenstore)  # inline JSON, as garmin_auth hands it over

        with mock.patch("garminconnect.Garmin", FakeGarmin):
            fake = garmin_auth.connect(self.store)
        fake.client.payload = TOKENS.replace("refresh", "rotated")
        fake.client.dump("ignored-path")  # what garminconnect calls after refreshing
        self.assertIn("rotated", garmin_auth.load(self.store))
        self.assertFalse((Path(self.store) / garmin_auth.TOKEN_FILE).exists())

    def test_disconnect_forgets_the_sealed_file(self):
        garmin_auth.store(self.store, TOKENS)
        garmin_auth.disconnect(self.store)
        self.assertFalse(garmin_auth.connected(self.store))


class Consent(unittest.TestCase):
    def setUp(self):
        self.enterContext(people(TWO))

    def test_the_controller_is_never_asked_everyone_else_is(self):
        self.assertFalse(privacy.required(tenant.get("x")))
        self.assertTrue(privacy.required(tenant.get("y")))

    def test_the_only_person_and_the_old_layout_are_the_controller(self):
        with people({"solo": {}}):
            self.assertFalse(privacy.required(tenant.get("solo")))
        with people({"me": {"root": "."}, "y": {}}):
            self.assertFalse(privacy.required(tenant.get("me")))
            self.assertTrue(privacy.required(tenant.get("y")))

    def test_consent_is_versioned_and_logged(self):
        y = tenant.get("y")
        privacy.accept(y, "en", "100.64.0.9")
        self.assertFalse(privacy.required(y))
        self.assertEqual(privacy.consent(y)["lang"], "en")
        self.assertEqual(audit.events("y")[0]["event"], "consent")
        with mock.patch.object(privacy, "POLICY_VERSION", "2099-01-01"):
            self.assertTrue(privacy.required(y), "a new policy asks again")

    def test_withdrawing_deletes_everything_and_asks_again(self):
        y = tenant.get("y")
        consent("y")
        (y.root / "raw").mkdir(parents=True)
        (y.root / "raw" / "day.json").write_text("{}")
        privacy.withdraw(y)
        self.assertEqual(list(y.root.iterdir()), [])
        self.assertTrue(privacy.required(y))
        self.assertEqual(audit.events("y")[0]["event"], "withdraw")

    def test_the_policy_names_the_controller_and_the_authority(self):
        text = privacy.policy()
        self.assertIn("x@example.com", text)
        self.assertIn("UODO", text.upper())
        self.assertIn(privacy.POLICY_VERSION, text)
        privacy.SETTINGS.write_text(json.dumps({"controller": "Jan K.", "contact": "jan@k.pl", "host": "Hetzner"}))
        text = privacy.policy()
        self.assertIn("Jan K.", text)
        self.assertIn("Hetzner", text)


class Retention(unittest.TestCase):
    def setUp(self):
        self.enterContext(people({**TWO, "z": {}}))
        consent("y", "z")

    def test_inactive_people_are_listed_never_the_controller(self):
        today = dt.date.today()
        privacy.seen(tenant.get("y"), today - dt.timedelta(days=400))
        privacy.seen(tenant.get("z"), today - dt.timedelta(days=10))
        privacy.seen(tenant.get("x"), today - dt.timedelta(days=900))
        self.assertEqual([p.id for p, _ in privacy.inactive(today)], ["y"])
        privacy.SETTINGS.write_text(json.dumps({"inactive_days": 5}))
        self.assertEqual([p.id for p, _ in privacy.inactive(today)], ["y", "z"])

    def test_retention_apply_deletes_and_logs(self):
        y = tenant.get("y")
        privacy.seen(y, dt.date.today() - dt.timedelta(days=400))
        with mock.patch("sys.stdout", io.StringIO()):
            privacy.main(["retention"])
            self.assertTrue(y.consent_file.exists(), "nothing goes without --apply")
            privacy.main(["retention", "--apply"])
        self.assertFalse(y.consent_file.exists())
        self.assertEqual(audit.events("y")[0]["event"], "inactive_erase")


class AccessLog(unittest.TestCase):
    def setUp(self):
        self.enterContext(people(TWO))

    def test_events_are_per_person_newest_first_and_owner_only(self):
        audit.record("signin", "x", ip="1.2.3.4")
        audit.record("signin", "y")
        audit.record("archive", "y")
        self.assertEqual([e["event"] for e in audit.events("y")], ["archive", "signin"])
        self.assertEqual(len(audit.events()), 3)
        month = next(audit.DIR.glob("*.jsonl"))
        self.assertEqual(month.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            audit.record("heart_rate_was_high", "y")

    def test_old_months_are_deleted(self):
        audit.DIR.mkdir(parents=True)
        (audit.DIR / "2026-01.jsonl").write_text("{}\n")
        (audit.DIR / "2026-10.jsonl").write_text("{}\n")
        self.assertEqual(audit.prune(dt.date(2026, 11, 7)), ["2026-01.jsonl"])

    def test_phone_reads_are_logged_at_most_hourly_per_key(self):
        audit._recent.clear()
        for _ in range(5):
            audit.api_read("y", "gd_abc", None)
        self.assertEqual(len(audit.events("y")), 1)

    def test_the_archive_carries_the_persons_own_lines_only(self):
        audit.record("signin", "x")
        audit.record("signin", "y", ip="9.9.9.9")
        with zipfile.ZipFile(io.BytesIO(tenant.archive(tenant.get("y")))) as zipped:
            lines = zipped.read("access_log.jsonl").decode().splitlines()
        self.assertEqual([json.loads(line)["person"] for line in lines], ["y"])


class AdminSeesNoHealth(unittest.TestCase):
    def test_pull_log_is_redacted(self):
        text = ("[07:43:32] zalogowany jako Jan Kowalski\n[07:43:33]   activities 2026-10: 16\n"
                "  model Banistera: tau_fitness=63.3d, tau_fatigue=5.3d, R2=0.148, szczyt po 11 dniach")
        shown = monitor.redact(text)
        self.assertNotIn("Kowalski", shown)
        self.assertNotIn("63.3", shown)
        self.assertIn("activities 2026-10: 16", shown)


class ApiNeedsConsent(unittest.TestCase):
    def setUp(self):
        self.enterContext(people(TWO))
        self.app = api.build_app()
        self.enterContext(mock.patch.object(sync, "start", return_value=True))

    def test_a_valid_key_opens_nothing_without_consent(self):
        y = tenant.get("y")
        ingest = api.create_token(y, "iPhone", "ingest")
        read = api.create_token(y, "phone", "read")
        body = json.dumps(push()).encode()
        self.assertEqual(call(self.app, "POST", "/api/ingest/apple", ingest, body)[0], 403)
        self.assertEqual(call(self.app, "GET", "/api/manifest", read)[0], 403)
        self.assertFalse((y.raw / "apple" / "push").exists(), "nothing stored without consent")
        consent("y")
        self.assertEqual(call(self.app, "POST", "/api/ingest/apple", ingest, body)[0], 202)
        self.assertIn("api_ingest", [e["event"] for e in audit.events("y")])


class Backups(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.data = self.folder / "data"
        (self.data / "users" / "y" / "raw").mkdir(parents=True)
        (self.data / "users" / "y" / "raw" / "day.json").write_text('{"rhr": 51}')
        (self.data / "users" / "y" / "cache").mkdir()
        (self.data / "users" / "y" / "cache" / "big.sqlite").write_bytes(os.urandom(3 * backup.CHUNK))
        self.identity = self.folder / "owner.key"
        with mock.patch("sys.stdout", io.StringIO()):
            self.public = backup.keygen(self.identity)
        self.enterContext(mock.patch.dict(os.environ, {secretbox.KEY_ENV: str(self.folder / "data.key")}))
        secretbox.seal(b"make the key")

    def test_round_trip_and_nothing_readable_without_the_owners_key(self):
        made = backup.create(self.data, backup._public(self.public), self.folder / "out")
        self.assertNotIn(b"rhr", made.read_bytes())
        names = backup.members(made, self.identity)
        self.assertIn("data/users/y/raw/day.json", names)
        self.assertIn("_keys/data.key", names)
        self.assertFalse(any("cache" in name for name in names))
        backup.restore(made, self.identity, self.folder / "back")
        self.assertEqual((self.folder / "back/data/users/y/raw/day.json").read_text(), '{"rhr": 51}')
        with mock.patch("sys.stdout", io.StringIO()):
            stranger = backup.keygen(self.folder / "stranger.key")
        del stranger
        with self.assertRaises(SystemExit):
            backup.members(made, self.folder / "stranger.key")

    def test_a_cut_or_changed_file_does_not_open(self):
        (self.data / "big.bin").write_bytes(os.urandom(2 * backup.CHUNK + 5))
        made = backup.create(self.data, backup._public(self.public), self.folder / "out")
        blob = made.read_bytes()
        made.write_bytes(blob[: len(blob) // 2])
        with self.assertRaises(SystemExit):
            backup.members(made, self.identity)
        changed = bytearray(blob)
        changed[200] ^= 1
        made.write_bytes(bytes(changed))
        with self.assertRaises(SystemExit):
            backup.members(made, self.identity)

    def test_old_backups_rotate_out(self):
        out = self.folder / "out"
        old = backup.create(self.data, backup._public(self.public), out, dt.datetime(2026, 9, 1, 3, 0))
        new = backup.create(self.data, backup._public(self.public), out, dt.datetime(2026, 11, 6, 3, 0))
        self.assertEqual(backup.prune(out, 30, dt.date(2026, 11, 7)), [old])
        self.assertTrue(new.exists())


if __name__ == "__main__":
    unittest.main()


ROOT = Path(__file__).resolve().parents[1]
GATE = f"""
import sys; sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from core import tenant
st.session_state[tenant.SESSION_KEY] = "y"
from views import consent
consent.gate()
st.write("PAST THE GATE")
"""
ACCOUNT = GATE.replace("from views import consent\nconsent.gate()\n", "from views import account\naccount.render()\n")


class Screens(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest

        self.AppTest = AppTest
        self.enterContext(people(TWO))

    def test_consent_screen_stops_until_the_box_is_ticked(self):
        at = self.AppTest.from_string(GATE).run()
        self.assertFalse(at.exception)
        body = " ".join(str(m.value) for m in at.markdown)
        self.assertNotIn("PAST THE GATE", body)
        self.assertIn("UODO", body.upper())
        accept = next(b for b in at.button if b.key == "consent_accept")
        self.assertTrue(accept.disabled)
        at.checkbox(key="consent_check").check().run()
        at.button(key="consent_accept").click().run()
        self.assertIn("PAST THE GATE", " ".join(str(m.value) for m in at.markdown))
        self.assertFalse(privacy.required(tenant.get("y")))

    def test_account_shows_consent_withdrawal_and_own_log(self):
        consent("y")
        audit.record("signin", "y", ip="100.64.0.9")
        audit.record("signin", "x", ip="1.1.1.1")
        at = self.AppTest.from_string(ACCOUNT).run(timeout=30)
        self.assertFalse(at.exception)
        labels = [e.label for e in at.expander]
        self.assertTrue(any("Wycofaj zgodę" in label for label in labels), labels)
        html = " ".join(str(h.proto.body) for h in at.get("html"))
        self.assertIn("100.64.0.9", html)
        self.assertNotIn("1.1.1.1", html, "someone else's lines never show")
