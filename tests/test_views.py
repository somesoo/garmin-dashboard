"""analysis/views.py and /api/views: small read-only views for other apps."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import api
from analysis import views
from core import tenant
from etl import apple_push
from tests.helpers import consent, people
from tests.test_api import call, push

ROOT = Path(__file__).resolve().parent.parent
DAYS = ("2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02")


@contextlib.contextmanager
def loaded(extra: dict | None = None):
    """Person ``y`` with four pushed days built into tables; yields (app, read token)."""
    with people({"y": {"source": "apple"}, **(extra or {})}), contextlib.redirect_stdout(io.StringIO()):
        with tenant.use("y"):
            for day in DAYS:
                apple_push.store(json.dumps(push(day)).encode())
            from etl import load
            load.main()
        yield api.build_app(), api.create_token(tenant.get("y"), "tiles", "read")


class Pages(unittest.TestCase):
    def test_every_view_points_at_a_registered_page(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        registered = set(re.findall(r'_page\([\w.]+, "([\w-]+)"', source))
        for name, page in views.PAGES.items():
            self.assertIn(page, registered, name)
        self.assertIn("bieg", registered)  # a last workout that is a run links to the run page
        self.assertEqual(set(views.NAMES), set(views.BUILDERS))


class Endpoint(unittest.TestCase):
    def test_needs_a_read_key_and_a_known_view(self):
        with loaded() as (app, token):
            ingest = api.create_token(tenant.get("y"), "watch", "ingest")
            for path in ("/api/views", "/api/views/recovery"):
                self.assertEqual(call(app, "GET", path)[0], 401)
                self.assertEqual(call(app, "GET", path, ingest)[0], 401)
                self.assertEqual(call(app, "GET", path, "gd_wrong")[0], 401)
            status, _, body = call(app, "GET", "/api/views/everything", token)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["views"], list(views.NAMES))
            # Path tricks do not reach another file or view.
            self.assertEqual(call(app, "GET", "/api/views/..%2Fsummary", token)[0], 404)

    def test_index_and_links_follow_the_address_of_the_request(self):
        with loaded() as (app, token):
            host = {"host": "mac.tail.ts.net", "x-forwarded-proto": "https"}
            status, headers, body = call(app, "GET", "/api/views", token, headers=host)
            self.assertEqual(status, 200)
            index = json.loads(body)
            self.assertEqual(index["dashboard"], "https://mac.tail.ts.net")
            self.assertEqual([v["name"] for v in index["views"]], list(views.NAMES))
            self.assertEqual(index["views"][0]["url"], "https://mac.tail.ts.net/regeneracja")
            one = json.loads(call(app, "GET", "/api/views/recovery", token, headers=host)[2])
            self.assertEqual((one["page"], one["url"]), ("regeneracja", "https://mac.tail.ts.net/regeneracja"))
            with mock.patch.dict(os.environ, {"GARMIN_PUBLIC_URL": "https://dash.example/"}):
                fixed = json.loads(call(app, "GET", "/api/views/recovery", token, headers=host)[2])
            self.assertEqual(fixed["url"], "https://dash.example/regeneracja")

    def test_recovery_and_last_workout_from_the_warehouse(self):
        with loaded() as (app, token):
            status, headers, body = call(app, "GET", "/api/views/recovery", token)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual((data["view"], data["person"], data["lang"], data["empty"]), ("recovery", "y", "pl", False))
            self.assertEqual(data["sleep"]["hours"], 6.5)
            self.assertEqual(data["sleep"]["day"][:10], "2026-11-02")
            self.assertEqual(data["rhr"]["value"], 49)
            self.assertIsInstance(data["flags"], list)
            self.assertEqual(call(app, "GET", "/api/views/recovery", token,
                                  headers={"If-None-Match": headers["etag"]})[0], 304)
            # Another address is another answer: the link is part of it.
            self.assertEqual(call(app, "GET", "/api/views/recovery", token,
                                  headers={"If-None-Match": headers["etag"], "host": "other.example"})[0], 200)

            last = json.loads(call(app, "GET", "/api/views/last-workout", token)[2])
            self.assertEqual((last["empty"], last["sport"], last["km"], last["pace"]), (False, "running", 8.0, "5:37"))
            self.assertEqual(last["start"][:10], "2026-11-02")
            self.assertIn(last["page"], ("bieg", "trasy"))
            self.assertEqual(last["days_ago"], (dt.date.today() - dt.date(2026, 11, 2)).days)

    def test_running_views_answer_even_on_a_thin_record(self):
        with loaded() as (app, token):
            for name in ("next-workout", "forecast"):
                status, _, body = call(app, "GET", f"/api/views/{name}?lang=en", token)
                self.assertEqual(status, 200, name)
                data = json.loads(body)
                self.assertEqual((data["view"], data["lang"]), (name, "en"))
                self.assertIn("empty", data)
                self.assertIn(data["page"], ("plan", "prognoza"))

    def test_one_key_opens_one_person_and_the_cache_is_theirs(self):
        with loaded({"z": {"source": "apple"}}) as (app, token):
            consent("y", "z")  # with two people on a server nobody is read without it
            other = api.create_token(tenant.get("z"), "tiles", "read")
            mine = json.loads(call(app, "GET", "/api/views/recovery", token)[2])
            theirs = json.loads(call(app, "GET", "/api/views/recovery", other)[2])
            self.assertEqual((mine["person"], mine["empty"]), ("y", False))
            self.assertEqual((theirs["person"], theirs["empty"]), ("z", True))
            self.assertNotIn("sleep", theirs)
            self.assertTrue(list((tenant.get("y").root / "cache").glob("view-recovery-pl-*.json")))
            self.assertEqual(len(list((tenant.get("z").root / "cache").glob("view-recovery-pl-*.json"))), 1)

    def test_no_consent_no_view(self):
        from core import privacy

        with loaded() as (app, token), mock.patch.object(privacy, "required", return_value=True):
            self.assertEqual(call(app, "GET", "/api/views/recovery", token)[0], 403)
            self.assertEqual(call(app, "GET", "/api/views", token)[0], 403)


if __name__ == "__main__":
    unittest.main()
