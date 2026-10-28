"""Send the next days of a training plan to the Garmin calendar (and the watch).

    python -m etl.push_plan                    active plan, next 7 days
    python -m etl.push_plan <plan_id> --days 14
    python -m etl.push_plan --dry-run          print what would change and the JSON

Idempotent: what was pushed is recorded in the plan file (``plan["garmin"]``),
so a second run sends nothing, and a session changed since -- edited by the
assistant, softened on the Dziś page, rebuilt by "Przebuduj" -- is replaced
rather than duplicated. Uses the same tokens as etl/fetch.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import i18n  # noqa: E402
from running import garmin_workout as gw, store  # noqa: E402


def _id(payload: Any, *keys: str) -> int | None:
    if isinstance(payload, dict):
        for key in keys:
            if payload.get(key):
                return int(payload[key])
    return None


def _drop(api: Any, entry: dict[str, Any]) -> None:
    """Unschedule and delete; a workout already removed by hand in Connect is fine."""
    for method, key in (("unschedule_workout", "schedule_id"), ("delete_workout", "workout_id")):
        if entry.get(key):
            try:
                getattr(api, method)(entry[key])
            except Exception as error:  # noqa: BLE001 - 404 after a manual delete is normal
                print(f"  {method}({entry[key]}): {error}")
            time.sleep(config.THROTTLE)


def push(plan: dict[str, Any], api: Any, today: dt.date, days: int, log=print) -> dict[str, Any]:
    """Apply ``sync_actions`` through ``api``; returns the plan with an updated registry.

    The registry is written after every action, so an interrupted run (rate
    limit, lost network) never forgets a workout it already created.
    """
    registry = dict(plan.get("garmin") or {})
    plan["garmin"] = registry
    for action in gw.sync_actions(plan, today, days):
        log(gw.describe(action))
        if action["action"] in ("remove", "replace"):
            _drop(api, action["entry"])
            registry.pop(action["session_id"], None)
            store.save_plan(plan)
        if action["action"] in ("upload", "replace"):
            session = action["session"]
            created = api.upload_workout(gw.to_garmin(session))
            workout_id = _id(created, "workoutId")
            if workout_id is None:
                raise RuntimeError(i18n.tr(pl=f"Garmin nie zwrócił workoutId: {created!r}",
                                           en=f"Garmin returned no workoutId: {created!r}"))
            time.sleep(config.THROTTLE)
            scheduled = api.schedule_workout(workout_id, session["date"])
            registry[session["id"]] = {
                "workout_id": workout_id,
                "schedule_id": _id(scheduled, "workoutScheduleId", "scheduleId", "id"),
                "fingerprint": gw.fingerprint(session),
                "date": session["date"],
                "title": session.get("title"),
                "at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            store.save_plan(plan)
            time.sleep(config.THROTTLE)
    return plan


def main(argv: list[str] | None = None) -> int:
    tr = i18n.tr
    p = argparse.ArgumentParser(description=tr(pl="Wyślij plan treningowy do kalendarza Garmin",
                                               en="Send the training plan to the Garmin calendar"))
    p.add_argument("plan_id", nargs="?", help=tr(pl="domyślnie plan najbliższego startu",
                                                 en="default: the plan of the nearest race"))
    p.add_argument("--days", type=int, default=7, help=tr(pl="ile dni naprzód (domyślnie 7)",
                                                          en="how many days ahead (default 7)"))
    p.add_argument("--dry-run", action="store_true", help=tr(pl="pokaż zmiany i JSON, nic nie wysyłaj",
                                                             en="show the changes and the JSON, send nothing"))
    p.add_argument("--lang", choices=list(i18n.LANGS),
                   help=tr(pl="język nazw i opisów treningów", en="the language of workout names and descriptions"))
    args = p.parse_args(argv)
    if args.lang:
        i18n.force(args.lang)

    today = dt.date.today()
    if args.plan_id:
        plan = store.plan(args.plan_id)
    else:
        ahead = [x for x in store.plans() if x.get("request", {}).get("race_date", "") >= today.isoformat()]
        plan = min(ahead, key=lambda x: x["request"]["race_date"]) if ahead else None
    if plan is None:
        print(tr(pl="Brak planu (podaj id albo utwórz plan na stronie Plan treningowy).",
                 en="No plan (give an id or create a plan on the Training plan page)."))
        return 1
    errors = store.validate_plan(plan)
    if errors:
        print(tr(pl="Plan nie przechodzi walidacji:", en="The plan fails validation:") + "\n  " + "\n  ".join(errors))
        return 1

    actions = gw.sync_actions(plan, today, args.days)
    if not actions:
        name = plan.get("name", plan["id"])
        print(tr(pl=f"{name}: kalendarz Garmin aktualny na {args.days} dni.",
                 en=f"{name}: the Garmin calendar is up to date for {args.days} days."))
        return 0
    if args.dry_run:
        for action in actions:
            print(gw.describe(action))
            if action.get("session"):
                print(json.dumps(gw.to_garmin(action["session"]), indent=2, ensure_ascii=False))
        return 0

    from etl.fetch import connect

    push(plan, connect(), today, args.days)
    print(tr(pl="Gotowe — zsynchronizuj zegarek, żeby treningi pojawiły się w kalendarzu.",
             en="Done — sync the watch so the sessions show up in its calendar."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
