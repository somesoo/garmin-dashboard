import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sync
from etl import run


class SyncTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        patches = [mock.patch.object(sync, "LOCK", tmp / "fetch.lock"),
                   mock.patch.object(sync, "RECORD", tmp / "fetch.json")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def record(self, **fields):
        sync.RECORD.write_text(json.dumps(fields), encoding="utf-8")

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
        self.assertEqual(sync.LOCK.read_text(), str(os.getpid()))
        with mock.patch.object(sync, "running", return_value=True):
            self.assertFalse(run._lock())
        with mock.patch.object(sync, "running", return_value=False):
            self.assertTrue(run._lock())

    def test_record_keeps_start_when_finishing(self):
        run._record(started_at="2026-10-28T08:00:00", finished_at=None, code=None)
        run._record(finished_at="2026-10-28T08:02:00", code=0)
        self.assertEqual(sync.last(), {"started_at": "2026-10-28T08:00:00",
                                       "finished_at": "2026-10-28T08:02:00", "code": 0})


if __name__ == "__main__":
    unittest.main()
