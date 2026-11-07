"""api.py: tokens, the push endpoint, the warehouse for apps -- and etl/apple_push.py."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import api
from core import sync
from core import tenant
from etl import apple, apple_push
from tests.helpers import consent, people


def call(app, method: str, path: str, token: str | None = None, body: bytes = b"", headers: dict | None = None):
    """One request straight into the ASGI app: (status, headers, body)."""
    sent = {"status": None, "headers": {}, "body": b""}
    raw_headers = [(b"content-length", str(len(body)).encode())]
    if token:
        raw_headers.append((b"authorization", f"Bearer {token}".encode()))
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    path, _, query = path.partition("?")
    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": query.encode(),
             "headers": raw_headers, "scheme": "https", "server": ("127.0.0.1", 8502), "client": ("127.0.0.1", 1),
             "http_version": "1.1", "root_path": ""}
    chunks = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if chunks:
            return chunks.pop(0)
        # A live client stays connected: FileResponse listens for a disconnect and
        # would stop sending the file the moment one arrived.
        await asyncio.Event().wait()

    async def send(message):
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]
            sent["headers"] = {k.decode(): v.decode() for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            sent["body"] += message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return sent["status"], sent["headers"], sent["body"]


def push(day: str = "2026-11-01") -> dict:
    return {
        "format": apple_push.FORMAT,
        "records": [
            {"type": "HeartRate", "start": f"{day}T07:00:00+01:00", "value": 61, "unit": "count/min",
             "source": "Apple Watch"},
            {"type": "HKQuantityTypeIdentifierStepCount", "start": f"{day}T09:00:00+01:00",
             "end": f"{day}T10:00:00+01:00", "value": 5400, "unit": "count", "source": "Apple Watch"},
            {"type": "HeartRateVariabilitySDNN", "start": f"{day}T03:00:00+01:00", "value": 58, "unit": "ms",
             "source": "Apple Watch"},
            {"type": "RestingHeartRate", "start": f"{day}T08:00:00+01:00", "value": 49, "unit": "count/min",
             "source": "Apple Watch"},
        ],
        "sleep": [
            {"start": f"{day}T00:30:00+01:00", "end": f"{day}T03:30:00+01:00", "stage": "Core", "source": "Apple Watch"},
            {"start": f"{day}T03:30:00+01:00", "end": f"{day}T04:30:00+01:00", "stage": "Deep", "source": "Apple Watch"},
            {"start": f"{day}T04:30:00+01:00", "end": f"{day}T07:00:00+01:00", "stage": "REM", "source": "Apple Watch"},
        ],
        "workouts": [{"type": "Running", "start": f"{day}T17:00:00+01:00", "end": f"{day}T17:45:00+01:00",
                      "distance_km": 8.0, "avg_hr": 148, "max_hr": 171, "calories": 540, "source": "Apple Watch"}],
    }


class Tokens(unittest.TestCase):
    def setUp(self):
        self.enterContext(people({"x": {}, "y": {"source": "apple"}}))

    def test_token_is_stored_only_as_a_hash_and_opens_one_person(self):
        y = tenant.get("y")
        token = api.create_token(y, "iPhone", "ingest")
        self.assertNotIn(token, api.tokens_path(y).read_text())
        self.assertEqual(api.tokens_path(y).stat().st_mode & 0o777, 0o600)
        self.assertEqual(api.verify(token, "ingest").id, "y")
        self.assertIsNone(api.verify(token, "read"), "a token carries one scope")
        self.assertIsNone(api.verify(token + "x", "ingest"))
        self.assertIsNone(api.verify("", "ingest"))
        self.assertIsNotNone(api.list_tokens(y)[0]["last_used"])
        self.assertNotIn("sha256", api.list_tokens(y)[0])

    def test_revoke(self):
        y = tenant.get("y")
        token = api.create_token(y, "iPhone", "ingest")
        self.assertEqual(api.revoke_token(y, token[:10]), 1)
        self.assertIsNone(api.verify(token, "ingest"))


class AppFiles(unittest.TestCase):
    """Files of the two apps, served side by side under /api/app/ (ui/webapp.py)."""

    def setUp(self):
        self.enterContext(people({"x": {}}))
        self.app = api.build_app()

    def test_the_dashboard_worker_may_claim_the_whole_site(self):
        # Without this header the browser refuses a scope above the file's own
        # folder, the dashboard ends up with no worker, and a home-screen icon
        # opens as a bookmark with an address bar.
        status, headers, _ = call(self.app, "GET", f"/api/app/{api.DASHBOARD_WORKER}")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("service-worker-allowed"), "/")

    def test_the_phone_app_worker_claims_nothing_above_itself(self):
        status, headers, _ = call(self.app, "GET", "/api/app/sw.js")
        self.assertEqual(status, 200)
        self.assertNotIn("service-worker-allowed", headers)


class Ingest(unittest.TestCase):
    def setUp(self):
        self.enterContext(people({"x": {}, "y": {"source": "apple"}}))
        consent("x", "y")
        self.app = api.build_app()
        self.token = api.create_token(tenant.get("y"), "iPhone", "ingest")
        self.start = self.enterContext(mock.patch.object(sync, "start", return_value=True))

    def test_push_is_stored_once_and_starts_a_rebuild(self):
        body = json.dumps(push()).encode()
        status, _, out = call(self.app, "POST", "/api/ingest/apple", self.token, body)
        self.assertEqual(status, 202, out)
        reply = json.loads(out)
        self.assertEqual((reply["new"], reply["rebuild"], reply["records"], reply["workouts"]),
                         (True, "started", 4, 1))
        with tenant.use("y"):
            self.assertEqual(len(list(apple_push.push_dir().glob("*.json"))), 1)
        status, _, out = call(self.app, "POST", "/api/ingest/apple", self.token, body)
        self.assertEqual(json.loads(out)["new"], False)
        self.assertEqual(self.start.call_count, 1)

    def test_busy_run_queues_the_rebuild(self):
        self.start.return_value = False
        status, _, out = call(self.app, "POST", "/api/ingest/apple", self.token, json.dumps(push()).encode())
        self.assertEqual(json.loads(out)["rebuild"], "queued")
        with tenant.use("y"):
            self.assertTrue(sync.pending_path().exists())

    def test_refusals(self):
        body = json.dumps(push()).encode()
        self.assertEqual(call(self.app, "POST", "/api/ingest/apple", None, body)[0], 401)
        self.assertEqual(call(self.app, "POST", "/api/ingest/apple", "gd_nope", body)[0], 401)
        read = api.create_token(tenant.get("y"), "app", "read")
        self.assertEqual(call(self.app, "POST", "/api/ingest/apple", read, body)[0], 401)
        garmin = api.create_token(tenant.get("x"), "x", "ingest")
        self.assertEqual(call(self.app, "POST", "/api/ingest/apple", garmin, body)[0], 409)
        self.assertEqual(call(self.app, "POST", "/api/ingest/apple", self.token, b"{not json")[0], 400)
        self.assertEqual(call(self.app, "POST", "/api/ingest/apple", self.token, b'{"hello": 1}')[0], 400)
        with mock.patch.object(api, "MAX_BODY", 10):
            self.assertEqual(call(self.app, "POST", "/api/ingest/apple", self.token, body)[0], 413)
        self.assertEqual(call(self.app, "GET", "/api/health")[0], 200)


class Warehouse(unittest.TestCase):
    def test_pushes_become_tables_and_the_app_gets_them_as_sqlite(self):
        with people({"y": {"source": "apple"}}), contextlib.redirect_stdout(io.StringIO()):
            with tenant.use("y"):
                apple_push.store(json.dumps(push("2026-11-01")).encode())
                apple_push.store(json.dumps(push("2026-11-02")).encode())
                from etl import load
                self.assertEqual(load.main(), 0)
            app = api.build_app()
            token = api.create_token(tenant.get("y"), "phone", "read")
            status, _, out = call(app, "GET", "/api/manifest", token)
            self.assertEqual(status, 200)
            manifest = json.loads(out)
            self.assertEqual((manifest["person"], manifest["source"]), ("y", "apple"))
            status, headers, body = call(app, "GET", "/api/db", token)
            self.assertEqual(status, 200)
            with tempfile.NamedTemporaryFile(suffix=".sqlite") as file:
                file.write(body)
                file.flush()
                con = sqlite3.connect(file.name)
                rows = con.execute("SELECT day, steps, sleep_h, hrv_last_night FROM daily ORDER BY day").fetchall()
                meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            self.assertEqual(rows[-1][0][:10], "2026-11-02")
            self.assertEqual(rows[-1][1], 5400)
            self.assertAlmostEqual(rows[-1][2], 6.5)
            self.assertEqual(rows[-1][3], 58)
            self.assertEqual(meta["person"], "y")
            self.assertEqual(call(app, "GET", "/api/db", token, headers={"If-None-Match": headers["etag"]})[0], 304)


class PhoneApp(unittest.TestCase):
    def test_summary_per_language_with_etag_and_the_app_behind_a_csp(self):
        with people({"y": {"source": "apple"}}), contextlib.redirect_stdout(io.StringIO()):
            with tenant.use("y"):
                for day in ("2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"):
                    apple_push.store(json.dumps(push(day)).encode())
                from etl import load
                load.main()
            app = api.build_app()
            token = api.create_token(tenant.get("y"), "phone", "read")
            self.assertEqual(call(app, "GET", "/api/summary")[0], 401)
            status, headers, body = call(app, "GET", "/api/summary", token)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual((data["person"], data["lang"]), ("y", "pl"))
            self.assertEqual(data["today"]["steps"]["value"], 5400)
            self.assertEqual(data["activities"][0]["pace"], "5:37")  # 45 min / 8 km, stored as 5.62 like Garmin's
            self.assertEqual(call(app, "GET", "/api/summary", token, headers={"If-None-Match": headers["etag"]})[0], 304)
            english = json.loads(call(app, "GET", "/api/summary?lang=en", token)[2])
            self.assertEqual(english["lang"], "en")
            self.assertNotEqual(english["stories"]["sleep"]["headline"], data["stories"]["sleep"]["headline"])
            status, headers, body = call(app, "GET", "/api/app/index.html")
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
            self.assertIn(b"app.js", body)


class PushFormats(unittest.TestCase):
    def test_utc_moves_to_local_time_and_offsets_stay_wall_clock(self):
        self.assertEqual(apple_push.wall_time("2026-07-01T05:00:00Z"), dt.datetime(2026, 7, 1, 7, 0))
        self.assertEqual(apple_push.wall_time("2026-07-01T05:00:00+02:00"), dt.datetime(2026, 7, 1, 5, 0))
        self.assertEqual(apple_push.wall_time("2026-07-01 05:00:00 +0200"), dt.datetime(2026, 7, 1, 5, 0))
        self.assertIsNone(apple_push.wall_time("yesterday-ish"))

    def test_health_auto_export_payload(self):
        payload = {"data": {
            "metrics": [
                {"name": "heart_rate", "units": "count/min",
                 "data": [{"date": "2026-11-01 07:00:00 +0100", "Min": 55, "Avg": 60, "Max": 66, "source": "Watch"}]},
                {"name": "step_count", "units": "count",
                 "data": [{"date": "2026-11-01 00:00:00 +0100", "qty": 9100, "source": "Watch"}]},
                {"name": "walking_running_distance", "units": "mi",
                 "data": [{"date": "2026-11-01 00:00:00 +0100", "qty": 2}]},
                {"name": "blood_oxygen_saturation", "units": "%",
                 "data": [{"date": "2026-11-01 03:00:00 +0100", "qty": 97}]},
                {"name": "sleep_analysis", "units": "hr",
                 "data": [{"date": "2026-11-01", "sleepStart": "2026-11-01 00:00:00 +0100",
                           "deep": 1.0, "core": 4.0, "rem": 1.5, "awake": 0.25, "asleep": 6.5}]},
                {"name": "something_new", "data": [{"date": "2026-11-01 00:00:00 +0100", "qty": 1}]},
            ],
            "workouts": [{"name": "Outdoor Run", "start": "2026-11-01 17:00:00 +0100",
                          "end": "2026-11-01 17:40:00 +0100", "duration": 2400,
                          "distance": {"qty": 7.5, "units": "km"}, "activeEnergyBurned": {"qty": 480, "units": "kcal"},
                          "avgHeartRate": {"qty": 150}, "maxHeartRate": {"qty": 170}}],
        }}
        self.assertEqual(apple_push.describe(payload)["workouts"], 1)
        export = apple_push.parse_push(payload)
        self.assertEqual(len(export.heart_rate), 1)
        steps = export.records[export.records["type"] == f"{apple.Q}StepCount"]["value"]
        self.assertEqual(steps.iloc[0], 9100)
        miles = export.records[export.records["type"] == f"{apple.Q}DistanceWalkingRunning"]["value"]
        self.assertAlmostEqual(miles.iloc[0], 3218.688)
        self.assertEqual(sorted(export.sleep["stage"]), ["awake", "deep", "light", "rem"])
        run = export.workouts[0]
        self.assertEqual((run["type"], run["duration_min"], run["distance_km"], run["avg_hr"]), ("Running", 40, 7.5, 150))

    def test_export_and_push_overlap_counts_once(self):
        one = apple_push.parse_push(push())
        both = apple_push.combine([one, apple_push.parse_push(push())])
        self.assertEqual(len(both.records), len(one.records))
        self.assertEqual(len(both.workouts), 1)
        tables = apple.build(both, today=dt.date(2026, 11, 2))
        day = tables["daily"][tables["daily"]["day"] == pd.Timestamp("2026-11-01")].iloc[0]
        self.assertEqual(day["steps"], 5400)


if __name__ == "__main__":
    unittest.main()
