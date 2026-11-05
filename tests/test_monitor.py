"""The admin page's numbers: people, sizes, warnings -- and who may see the page."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import monitor
from core import tenant
from tests import helpers

NOW = dt.datetime(2026, 11, 4, 12, 0)


def _machine(available_kb: int = 600_000, free: int = 5_000) -> dict:
    return {"memory": {"total_kb": 1_000_000, "available_kb": available_kb},
            "disk": {"total": 10_000, "free": free}}


def _person(**fields) -> dict:
    return {"id": "x", "name": "X", "source": "garmin", "garmin": True, "built_at": "2026-11-04T11:00:00",
            "pull_started": "2026-11-04T10:00:00", "pull_finished": "2026-11-04T10:01:00", "pull_code": 0,
            "running": False, "pending": False, **fields}


class Sizes(unittest.TestCase):
    def test_size_and_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "a").mkdir()
            (base / "a" / "one.bin").write_bytes(b"x" * 100)
            (base / "two.txt").write_text("\n".join(str(i) for i in range(100)), encoding="utf-8")
            self.assertEqual(monitor.size(base / "a"), 100)
            self.assertEqual(monitor.size(base / "missing"), 0)
            self.assertEqual(monitor.tail(base / "two.txt", 3), "97\n98\n99")
            self.assertEqual(monitor.tail(base / "missing"), "")


class Warnings(unittest.TestCase):
    def test_a_healthy_server_says_nothing(self):
        self.assertEqual(monitor.warnings(_machine(), [_person()], {"stale": False}, now=NOW), [])

    def test_memory_disk_and_code_come_first(self):
        found = monitor.warnings(_machine(available_kb=50_000, free=500), [_person(pull_code=1)],
                                 {"stale": True}, now=NOW)
        self.assertEqual([w["code"] for w in found], ["memory_low", "disk_low", "pull_failed", "code_stale"])
        self.assertEqual(found[0]["value"], 5)

    def test_pulls(self):
        codes = lambda **f: [w["code"] for w in monitor.warnings(_machine(), [_person(**f)], now=NOW)]  # noqa: E731
        self.assertEqual(codes(pull_code=2), ["token_expired"])
        self.assertEqual(codes(pull_code=None), ["pull_died"])
        self.assertEqual(codes(pull_started=None, pull_finished=None, pull_code=None), ["pull_stale"])
        self.assertEqual(codes(pull_finished="2026-11-02T10:00:00"), ["pull_stale"])
        self.assertEqual(codes(garmin=False), ["not_connected"])
        self.assertEqual(codes(source="apple", garmin=None, pull_started=None, pull_code=None), [])
        self.assertEqual(codes(built_at=None), ["no_build"])
        self.assertEqual(codes(pending=True), ["rebuild_waiting"])
        self.assertEqual(codes(running=True, pull_code=None), [])  # a pull in progress is not a failure

    def test_two_runs_at_once(self):
        found = monitor.warnings(_machine(), [_person(running=True), _person(id="y", running=True)], now=NOW)
        self.assertIn("parallel_runs", [w["code"] for w in found])


class People(unittest.TestCase):
    def test_a_person_without_data_is_listed(self):
        with helpers.person("p", source="apple") as user:
            row = monitor.person(user)
        self.assertEqual((row["id"], row["source"], row["bytes"], row["built_at"], row["running"]),
                         ("p", "apple", 0, None, False))

    def test_state_and_pull_are_read(self):
        with helpers.person("p") as user:
            user.root.mkdir(parents=True, exist_ok=True)
            user.state_file.write_text(json.dumps({"built_at": "2026-11-04T11:00:00", "days": 3}), encoding="utf-8")
            user.fetch_record.write_text(json.dumps({"started_at": "x", "finished_at": "y", "code": 0}),
                                         encoding="utf-8")
            row = monitor.person(user)
        self.assertEqual((row["days"], row["pull_code"], row["garmin"]), (3, 0, False))
        self.assertGreater(row["bytes"], 0)

    def test_snapshot_has_every_field(self):
        shot = monitor.snapshot(interval=0.01)
        self.assertTrue({"processes", "memory", "disk", "cpu_pct", "cores", "sessions"} <= set(shot))
        self.assertGreater(shot["disk"]["total"], 0)


class Admin(unittest.TestCase):
    def test_flag_from_the_registry_and_the_cli(self):
        with helpers.people({"a": {}, "b": {"admin": True}}):
            self.assertFalse(tenant.get("a").admin)
            self.assertTrue(tenant.get("b").admin)
            tenant.main(["admin", "a"])
            self.assertTrue(tenant.get("a").admin)
            tenant.main(["admin", "a", "--off"])
            self.assertFalse(tenant.get("a").admin)
            self.assertEqual(tenant.main(["admin", "nobody"]), 1)

    def test_the_single_user_layout_is_its_own_admin(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(tenant, "REGISTRY", Path(folder) / "users.json"):
                self.assertTrue(next(iter(tenant.users().values())).admin)


if __name__ == "__main__":
    unittest.main()
