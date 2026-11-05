import datetime as dt
import json
import os
import unittest
from unittest import mock

from core import sync
from core import tenant
from etl import run
from tests.helpers import people, person


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.person = self.enterContext(person())

    def record(self, **fields):
        sync.record_path().parent.mkdir(parents=True, exist_ok=True)
        sync.record_path().write_text(json.dumps(fields), encoding="utf-8")

    def test_no_record_is_due(self):
        self.assertTrue(sync.due(6))

    def test_good_pull_waits_the_interval(self):
        self.record(started_at="2026-10-28T08:00:00", finished_at="2026-10-28T08:03:00", code=0)
        self.assertFalse(sync.due(6, dt.datetime(2026, 10, 28, 13, 59)))
        self.assertTrue(sync.due(6, dt.datetime(2026, 10, 28, 14, 0)))

    def test_failed_pull_retries_sooner_expired_token_does_not(self):
        self.record(started_at="2026-10-28T08:00:00", finished_at="2026-10-28T08:01:00", code=1)
        self.assertTrue(sync.due(6, dt.datetime(2026, 10, 28, 8, 30)))
        self.record(started_at="2026-10-28T08:00:00", finished_at="2026-10-28T08:01:00", code=2)
        self.assertFalse(sync.due(6, dt.datetime(2026, 10, 28, 8, 30)))

    def test_lock_is_exclusive_and_stale_lock_is_taken_over(self):
        self.assertTrue(run._lock())
        self.assertEqual(sync.lock_path().read_text(), str(os.getpid()))
        self.assertEqual(sync.lock_path().parent, self.person.root)
        with mock.patch.object(sync, "running", return_value=True):
            self.assertFalse(run._lock())
        with mock.patch.object(sync, "running", return_value=False):
            self.assertTrue(run._lock())

    def test_record_keeps_start_when_finishing(self):
        run._record(started_at="2026-10-28T08:00:00", finished_at=None, code=None)
        run._record(finished_at="2026-10-28T08:02:00", code=0)
        self.assertEqual(sync.last(), {"started_at": "2026-10-28T08:00:00",
                                       "finished_at": "2026-10-28T08:02:00", "code": 0})


class PerPerson(unittest.TestCase):
    """Two people: separate locks and records; the timer pulls Garmin people only."""

    def setUp(self):
        self.enterContext(people({"x": {"source": "garmin"}, "y": {"source": "apple"}, "z": {"source": "garmin"}}))

    def test_lock_and_record_are_per_person(self):
        with tenant.use("x"):
            self.assertTrue(run._lock())
            run._record(started_at="2026-10-28T08:00:00", code=0)
        with tenant.use("z"):
            self.assertTrue(run._lock(), "x's pull must not block z's")
            self.assertEqual(sync.last(), {})
        with tenant.use("x"):
            self.assertEqual(sync.last()["started_at"], "2026-10-28T08:00:00")

    def test_apple_person_is_rebuilt_never_pulled(self):
        """The timer never pulls an Apple person; a run started for one (after a push) only
        rebuilds -- etl/fetch.main checks the source -- and works on their directory."""
        with mock.patch.object(sync.subprocess, "Popen") as popen, \
                mock.patch.object(sync, "running", return_value=False), mock.patch.object(sync.time, "sleep"):
            self.assertNotIn("y", sync.check_all(6))
            with tenant.use("y"):
                self.assertTrue(sync.start())
        self.assertEqual(popen.call_args_list[-1].kwargs["env"]["GARMIN_USER"], "y")

    def test_queued_rebuild_is_picked_up_by_the_timer(self):
        with tenant.use("y"):
            sync.pending_path().parent.mkdir(parents=True, exist_ok=True)
            sync.pending_path().touch()
        with mock.patch.object(sync.subprocess, "Popen"), mock.patch.object(sync, "running", return_value=False), \
                mock.patch.object(sync.time, "sleep"):
            self.assertIn("y", sync.check_all(6))

    def test_timer_starts_each_due_garmin_person_with_their_id(self):
        with mock.patch.object(sync.subprocess, "Popen") as popen, \
                mock.patch.object(sync, "running", return_value=False), mock.patch.object(sync.time, "sleep"):
            self.assertEqual(sync.check_all(6), ["x", "z"])
        self.assertEqual([c.kwargs["env"]["GARMIN_USER"] for c in popen.call_args_list], ["x", "z"])


if __name__ == "__main__":
    unittest.main()
