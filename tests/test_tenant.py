"""One directory per person (tenant.py): nobody reads anybody else's data."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import unittest
from unittest import mock

import duckdb
import pandas as pd

from core import config
from core import db
from analysis import insights
from core import tenant
from running import store
from tests.helpers import people


def _tables(user_id: str, value: int) -> None:
    with tenant.use(user_id) as person:
        person.tables.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"day": [pd.Timestamp("2026-11-01")], "steps": [value]}).to_parquet(
            person.tables / "daily.parquet", index=False)


class Registry(unittest.TestCase):
    def test_without_registry_one_person_reads_data_itself(self):
        with people({}) as base:
            tenant.REGISTRY.unlink()
            everyone = tenant.users()
            self.assertEqual(list(everyone), [tenant.LEGACY_ID])
            self.assertEqual(tenant.current().root, config.DATA)
            self.assertTrue(tenant.current().legacy)
            self.assertNotEqual(base, config.DATA)

    def test_several_people_and_nobody_chosen_is_an_error(self):
        with people({"x": {}, "y": {"source": "apple"}}), mock.patch.dict(os.environ, {"GARMIN_USER": ""}):
            with self.assertRaises(tenant.NoUser):
                tenant.current()
            with self.assertRaises(tenant.NoUser):
                config.tables()

    def test_environment_names_the_person_outside_streamlit(self):
        with people({"x": {}, "y": {"source": "apple"}}), mock.patch.dict(os.environ, {"GARMIN_USER": "y"}):
            self.assertEqual(tenant.current().id, "y")
            self.assertEqual(config.raw(), tenant.USERS / "y" / "raw")

    def test_unknown_person_is_an_error_not_a_fallback(self):
        with people({"x": {}}), mock.patch.dict(os.environ, {"GARMIN_USER": "nobody"}):
            with self.assertRaises(tenant.NoUser):
                tenant.current()

    def test_broken_registry_does_not_fall_back_to_single_user(self):
        with people({"x": {}}):
            tenant.REGISTRY.write_text("{oops", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                tenant.users()

    def test_root_outside_data_is_refused(self):
        with people({"x": {"root": "../../etc"}}):
            with self.assertRaises(RuntimeError):
                tenant.users()

    def test_identity_matches_one_person_case_insensitively(self):
        with people({"x": {"identities": ["X@Example.com"]}, "y": {"identities": ["y@example.com"]}}):
            self.assertEqual(tenant.by_identity(" x@example.COM ").id, "x")
            self.assertIsNone(tenant.by_identity("z@example.com"))
            self.assertIsNone(tenant.by_identity(""))

    def test_tokens_live_with_the_person(self):
        with people({"x": {}, "y": {"tokenstore": "~/.garminconnect"}}):
            with tenant.use("x"):
                self.assertEqual(config.tokenstore(), str(tenant.USERS / "x" / "garmin"))
            with tenant.use("y"):
                self.assertEqual(config.tokenstore(), "~/.garminconnect")


class Isolation(unittest.TestCase):
    def setUp(self):
        self.enterContext(people({"x": {"insights": True}, "y": {"source": "apple"}}))
        _tables("x", 111)
        _tables("y", 222)

    def test_each_person_queries_only_their_tables(self):
        with tenant.use("x"):
            self.assertEqual(db.query("SELECT steps FROM daily")["steps"].tolist(), [111])
        with tenant.use("y"):
            self.assertEqual(db.query("SELECT steps FROM daily")["steps"].tolist(), [222])

    def test_sql_cannot_read_another_persons_files(self):
        other = (tenant.USERS / "x" / "tables" / "daily.parquet").resolve()
        attempts = [f"SELECT * FROM read_parquet('{other}')",
                    "SELECT * FROM read_parquet('../x/tables/daily.parquet')",
                    "SELECT * FROM read_csv('/etc/passwd')",
                    "SET enable_external_access = true",
                    f"ATTACH '{tenant.USERS / 'y' / 'evil.db'}'"]
        with tenant.use("y"):
            for sql in attempts:
                with self.subTest(sql=sql), self.assertRaises(duckdb.Error):
                    db.query(sql)

    def test_coach_files_are_per_person(self):
        with tenant.use("x"):
            store.save_race({"name": "Bieg X", "date": "2027-04-01", "distance": "hm", "priority": "A"})
        with tenant.use("y"):
            self.assertEqual(store.races(), [])
        with tenant.use("x"):
            self.assertEqual([r["name"] for r in store.races()], ["Bieg X"])

    def test_file_keys_are_stable_and_differ_between_people(self):
        with tenant.use("x") as x:
            first = x.file_key("tracks")
            self.assertEqual(first, tenant.current().file_key("tracks"))
        with tenant.use("y") as y:
            self.assertNotEqual(first, y.file_key("tracks"))
        self.assertRegex(first, r"^[0-9a-f]{20}$")

    def test_insight_prose_only_for_the_person_it_is_about(self):
        with tenant.use("y"):
            self.assertEqual(insights.load_all(), [])
        with tenant.use("x"):
            self.assertEqual(len(insights.load_all()), len(insights.originals()))


class Rights(unittest.TestCase):
    def test_archive_holds_the_data_and_no_secrets(self):
        import io as _io
        import zipfile

        with people({"x": {}, "y": {"source": "apple"}}):
            y = tenant.get("y")
            for name, body in (("raw/apple/push/a.json", "{}"), ("tables/daily.parquet", "p"), ("tokens.json", "[]"),
                               ("garmin/garmin_tokens.json", "secret"), ("cache/summary.json", "{}")):
                (y.root / name).parent.mkdir(parents=True, exist_ok=True)
                (y.root / name).write_text(body)
            names = zipfile.ZipFile(_io.BytesIO(tenant.archive(y))).namelist()
            self.assertEqual(sorted(names), ["raw/apple/push/a.json", "tables/daily.parquet"])

    def test_legacy_archive_takes_only_the_persons_part_of_data(self):
        import io as _io
        import zipfile

        with people({}) as base, mock.patch.object(config, "DATA", base):
            tenant.REGISTRY.unlink()
            (base / "tables").mkdir()
            (base / "tables" / "daily.parquet").write_text("p")
            (base / "users" / "y").mkdir(parents=True)
            (base / "users" / "y" / "secret.json").write_text("{}")
            (base / "server.secret").write_text("k")
            me = tenant.User(id="me", name="me", source="garmin", root=base, legacy=True)
            names = zipfile.ZipFile(_io.BytesIO(tenant.archive(me))).namelist()
            self.assertEqual(names, ["tables/daily.parquet"])

    def test_erase_removes_one_person_only_and_remove_drops_the_entry(self):
        with people({"x": {}, "y": {"source": "apple"}}), contextlib.redirect_stdout(io.StringIO()):
            _tables("x", 1)
            _tables("y", 2)
            self.assertEqual(tenant.erase(tenant.get("y")), ["tables"])
            self.assertTrue((tenant.USERS / "y").is_dir())
            self.assertFalse((tenant.USERS / "y" / "tables").exists())
            self.assertTrue((tenant.USERS / "x" / "tables" / "daily.parquet").exists())
            self.assertEqual(tenant.remove(argparse.Namespace(id="y", yes=False)), 1)
            self.assertEqual(tenant.remove(argparse.Namespace(id="y", yes=True)), 0)
            self.assertNotIn("y", tenant.users())
            self.assertFalse((tenant.USERS / "y").exists())


class Cli(unittest.TestCase):
    def _args(self, **values):
        defaults = {"name": None, "source": "garmin", "identity": None, "local": False}
        return argparse.Namespace(**{**defaults, **values})

    def test_init_add_migrate(self):
        with people({}) as base, mock.patch.object(config, "DATA", base), contextlib.redirect_stdout(None):
            tenant.REGISTRY.unlink()
            (base / "raw" / "sleep").mkdir(parents=True)
            (base / "raw" / "sleep" / "2026-11-01.json").write_text("{}", encoding="utf-8")
            (base / "ui.json").write_text('{"lang": "en"}', encoding="utf-8")

            self.assertEqual(tenant.init(self._args(id="x", local=True)), 0)
            self.assertEqual(tenant.get("x").root, base.resolve())
            self.assertEqual(tenant.add(self._args(id="y", source="apple", identity=["y@example.com"])), 0)
            self.assertEqual(tenant.add(self._args(id="y")), 1, "a second add of the same id is refused")
            self.assertTrue((tenant.USERS / "y").is_dir())

            self.assertEqual(tenant.migrate(argparse.Namespace(id="x")), 0)
            moved = tenant.get("x")
            self.assertEqual(moved.root, tenant.USERS / "x")
            self.assertTrue((moved.raw / "sleep" / "2026-11-01.json").exists())
            self.assertFalse((base / "raw").exists())
            self.assertEqual(json.loads(moved.ui_settings.read_text())["lang"], "en")
            entry = json.loads(tenant.REGISTRY.read_text())["users"]["x"]
            self.assertNotIn("root", entry)
            self.assertIn("tokenstore", entry, "tokens stay where etl/login.py put them")
            self.assertTrue(entry["insights"])

    def test_bad_id_is_refused(self):
        with people({"x": {}}), contextlib.redirect_stdout(None):
            with self.assertRaises(RuntimeError):
                tenant.add(self._args(id="../evil"))


if __name__ == "__main__":
    unittest.main()
