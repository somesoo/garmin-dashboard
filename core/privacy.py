"""Privacy: who answers for the data, the consent each person gives, how long anything stays.

Health data is a special category (RODO art. 9): the lawful basis here is the
person's **explicit consent** (art. 9(2)(a), 6(1)(a)), given on a screen of its
own before any source is connected (views/consent.py) and recorded per person
in ``consent.json`` with the policy version. Withdrawing it deletes everything
the person owns (there is no other basis to keep it).

**The controller** (``controller(person)``) gives no consent to themselves: the
server's admin (``admin: true``), the person of the old single-user layout
(``root: "."``), or the only person in the registry. Everyone else is asked,
and asked again when ``POLICY_VERSION`` changes.

The policy text (``policy()``) is built from ``data/privacy.json``::

    {"controller": "Jan Kowalski", "contact": "jan@example.com",
     "host": "Hetzner Online GmbH", "location": "Niemcy (UE)",
     "inactive_days": 365, "backup_days": 30}

(``python -m core.privacy setup ...``); without it the admin's name and e-mail
stand in. **Retention**: a person nobody has seen for ``inactive_days`` is
deleted by ``python -m core.privacy retention --apply`` (the admin page lists
them first); backups age out after ``backup_days`` (tools/backup.py); the
access log after ``audit.KEEP_DAYS``.

    python -m core.privacy                      status: controller, consents, last seen
    python -m core.privacy setup --controller "Jan K." --contact jan@x.pl --host "Hetzner" --location "Niemcy (UE)"
    python -m core.privacy policy [--lang en]   the policy as Markdown
    python -m core.privacy retention [--apply]  people past the inactivity limit (--apply deletes them)
    python -m core.privacy log [--person y]     the access log
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from core import audit
from core import config
from core import i18n
from core import tenant

# A change to what is collected, why, or who receives it = a new version, and
# every person who is not the controller is asked again.
POLICY_VERSION = "2026-11-07"
SETTINGS = config.DATA / "privacy.json"
DEFAULTS = {"inactive_days": 365, "backup_days": 30}
UODO = "Prezes Urzędu Ochrony Danych Osobowych, ul. Stawki 2, 00-193 Warszawa, uodo.gov.pl"  # i18n: key


# ------------------------------------------------------------------ settings


def settings() -> dict:
    try:
        stored = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    return {**DEFAULTS, **(stored if isinstance(stored, dict) else {})}


def _admin() -> tenant.User | None:
    everyone = list(tenant.users().values())
    for person in everyone:
        if person.admin:
            return person
    for person in everyone:
        if person.legacy:
            return person
    return everyone[0] if len(everyone) == 1 else None


def responsible() -> tuple[str, str]:
    """(who answers for the data, how to reach them) -- for the policy."""
    stored = settings()
    boss = _admin()
    name = stored.get("controller") or (boss.name if boss else "")
    contact = stored.get("contact") or (boss.identities[0] if boss and boss.identities else "")
    return name or i18n.tr(pl="osoba prowadząca ten serwer", en="the person who runs this server"), contact


# ------------------------------------------------------------------ consent


def controller(person: tenant.User) -> bool:
    """Is this the person who answers for the data (and so gives no consent to themselves)?"""
    if person.admin or person.legacy:
        return True
    return len(tenant.users()) == 1


def consent(person: tenant.User) -> dict | None:
    try:
        value = json.loads(person.consent_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def required(person: tenant.User) -> bool:
    """Must this person give (or renew) consent before anything of theirs is processed?"""
    if controller(person):
        return False
    given = consent(person)
    return not given or given.get("version") != POLICY_VERSION


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.part")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def accept(person: tenant.User, lang: str, ip: str | None = None) -> dict:
    record = {"version": POLICY_VERSION, "accepted_at": dt.datetime.now().isoformat(timespec="seconds"),
              "lang": lang}
    _write(person.consent_file, record)
    audit.record("consent", person.id, version=POLICY_VERSION, ip=ip)
    return record


def withdraw(person: tenant.User, ip: str | None = None) -> list[str]:
    """Withdrawn consent leaves no basis to keep anything: everything the person owns goes."""
    from etl import garmin_auth

    garmin_auth.disconnect(person.tokenstore)  # also when the tokens live outside the person's directory
    removed = tenant.erase(person)
    audit.record("withdraw", person.id, ip=ip)
    return removed


# ------------------------------------------------------------------ retention


def seen(person: tenant.User, today: dt.date | None = None) -> None:
    """Note that the person used the app today (once a day is enough)."""
    day = (today or dt.date.today()).isoformat()
    try:
        if json.loads(person.seen_file.read_text(encoding="utf-8")).get("last") == day:
            return
    except (OSError, ValueError, AttributeError):
        pass
    try:
        _write(person.seen_file, {"last": day})
    except OSError:
        pass


def last_seen(person: tenant.User) -> dt.date | None:
    try:
        return dt.date.fromisoformat(json.loads(person.seen_file.read_text(encoding="utf-8"))["last"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    given = consent(person)
    if given:
        try:
            return dt.datetime.fromisoformat(given["accepted_at"]).date()
        except (KeyError, ValueError):
            pass
    try:
        return dt.date.fromtimestamp(person.root.stat().st_mtime)
    except OSError:
        return None


def inactive(today: dt.date | None = None) -> list[tuple[tenant.User, dt.date | None]]:
    """People past the inactivity limit -- never the controller, never the old layout."""
    today = today or dt.date.today()
    limit = int(settings()["inactive_days"])
    found = []
    for person in tenant.users().values():
        if controller(person) or person.legacy:
            continue
        last = last_seen(person)
        if last is None or (today - last).days > limit:
            found.append((person, last))
    return found


# ------------------------------------------------------------------ the policy


def consent_sentence() -> str:
    return i18n.tr(
        pl="Wyrażam wyraźną zgodę na przetwarzanie moich danych dotyczących zdrowia (sen, tętno, HRV, stres, "
           "aktywność, treningi z trasami GPS) w tym dashboardzie, w celu pokazywania mi ich i ich analiz, "
           "na zasadach opisanych powyżej. Wiem, że mogę ją w każdej chwili wycofać na stronie Konto.",
        en="I give my explicit consent to the processing of my health data (sleep, heart rate, HRV, stress, "
           "activity, workouts with GPS tracks) in this dashboard, to show them and their analysis to me, as "
           "described above. I know I can withdraw it at any time on the Account page.")


def policy() -> str:
    """The information notice (RODO art. 13) as Markdown, in the current language."""
    tr = i18n.tr
    name, contact = responsible()
    stored = settings()
    host = stored.get("host") or tr(pl="dostawca serwera, na którym działa dashboard",
                                    en="the provider of the server the dashboard runs on")
    where = stored.get("location") or tr(pl="Unia Europejska", en="the European Union")
    inactive_days = int(stored["inactive_days"])
    backup_days = int(stored["backup_days"])
    reach = f" — {contact}" if contact else ""
    return tr(
        pl=f"""**Kto odpowiada za Twoje dane.** Administratorem jest {name}{reach}. Dashboard to prywatny projekt
dla kilku osób, nie usługa komercyjna; z każdym pytaniem o dane pisz na ten adres.

**Jakie dane.**
- konto: adres e-mail i imię z logowania Google;
- z zegarka (Garmin Connect albo Apple Health): sen i jego fazy, tętno, HRV, stres, kroki, energia,
  treningi z trasami GPS, okrążenia i wskaźniki wydolności — to **dane dotyczące zdrowia** (art. 9 RODO);
- to, co sam(a) wpiszesz: starty, plan, strefy tętna, segmenty, ustawienia;
- techniczne: dziennik dostępu (kiedy, jaki rodzaj dostępu, adres IP) — bez wartości zdrowotnych.

**Po co.** Wyłącznie po to, żeby pokazać Tobie Twoje dane i ich analizy. Nie sprzedajemy ich, nie
pokazujemy reklam, nie wysyłamy ich do usług analitycznych ani modeli AI, nie podejmujemy na ich
podstawie decyzji o Tobie (art. 22 RODO). Dashboard **nie jest wyrobem medycznym** — liczby i
propozycje treningów nie są poradą lekarską.

**Podstawa prawna.** Twoja wyraźna zgoda (art. 9 ust. 2 lit. a i art. 6 ust. 1 lit. a RODO). Dziennik
dostępu: prawnie uzasadniony interes — bezpieczeństwo Twoich danych (art. 6 ust. 1 lit. f).

**Kto je widzi i gdzie leżą.** Tylko Ty — każda osoba ma osobny katalog i widzi wyłącznie swoje dane.
Administrator ma techniczny dostęp do serwera, ale strona administracyjna nie pokazuje danych
zdrowotnych i nie zagląda do nich. Serwer: {host}, lokalizacja: {where}.
Odbiorcy: ten dostawca (przechowuje pliki), Google (tylko logowanie — dostaje informację, że się
logujesz), Garmin (pobieramy z niego dane Twoimi tokenami; plan treningowy wysyłamy do kalendarza
Garmin tylko po Twoim kliknięciu). Dane zdrowotne nie wychodzą poza Europejski Obszar Gospodarczy.

**Jak chronione.** HTTPS; logowanie tylko zweryfikowanym kontem Google z listy; tokeny Garmina
zaszyfrowane, hasło użyte raz i niezapisywane; klucze telefonu trzymane tylko jako skrót; kopie
zapasowe zaszyfrowane; dziennik dostępu.

**Jak długo.** Dopóki masz konto. Konto nieużywane przez {inactive_days} dni jest usuwane razem z danymi.
Po usunięciu lub wycofaniu zgody dane znikają od razu z serwera, a z kopii zapasowych najpóźniej po
{backup_days} dniach. Dziennik dostępu: {audit.KEEP_DAYS} dni.

**Twoje prawa.** Na stronie **Konto → Twoje dane** sam(a): pobierasz kopię wszystkiego (dostęp i
przenoszenie, art. 15 i 20), usuwasz wszystko (art. 17) i wycofujesz zgodę (art. 7 ust. 3 — nie
wpływa to na to, co działo się przed wycofaniem). Sprostowanie, ograniczenie, sprzeciw — napisz do
administratora. Masz prawo skargi do organu nadzorczego: {UODO}.

**Zmiany.** Gdy zmieni się to, co zbieramy, po co albo komu przekazujemy, poprosimy o zgodę ponownie.
Wersja zasad: {POLICY_VERSION}.""",
        en=f"""**Who answers for your data.** The controller is {name}{reach}. The dashboard is a private project
for a few people, not a commercial service; write to that address with any question about your data.

**What data.**
- account: e-mail address and name from Google sign-in;
- from your watch (Garmin Connect or Apple Health): sleep and its stages, heart rate, HRV, stress,
  steps, energy, workouts with GPS tracks, laps and fitness metrics — this is **data concerning health**
  (GDPR art. 9);
- what you type in yourself: races, the plan, heart rate zones, segments, settings;
- technical: an access log (when, which kind of access, IP address) — no health values.

**What for.** Only to show you your own data and its analysis. We do not sell it, show ads, send it to
analytics services or AI models, or make decisions about you based on it (GDPR art. 22). The dashboard
**is not a medical device** — its numbers and training suggestions are not medical advice.

**Lawful basis.** Your explicit consent (GDPR art. 9(2)(a) and 6(1)(a)). The access log: legitimate
interest — the security of your data (art. 6(1)(f)).

**Who sees it and where it lives.** Only you — every person has a separate directory and sees only their
own data. The controller has technical access to the server, but the admin page shows no health data and
does not look into it. Server: {host}, location: {where}.
Recipients: that provider (stores the files), Google (sign-in only — it learns that you sign in), Garmin
(we pull your data from it with your tokens; the training plan goes to your Garmin calendar only when you
click). Health data does not leave the European Economic Area.

**How it is protected.** HTTPS; sign-in only with a verified Google account on the list; Garmin tokens
encrypted, your password used once and never stored; phone keys kept only as a hash; encrypted backups;
an access log.

**How long.** As long as you have an account. An account unused for {inactive_days} days is deleted with
its data. After deletion or withdrawn consent the data is gone from the server at once, and from backups
within {backup_days} days. Access log: {audit.KEEP_DAYS} days.

**Your rights.** On **Account → Your data** you yourself download a copy of everything (access and
portability, art. 15 and 20), delete everything (art. 17) and withdraw consent (art. 7(3) — this does not
affect what happened before). Rectification, restriction, objection — write to the controller. You may
complain to the supervisory authority: {UODO}.

**Changes.** When what we collect, why, or who receives it changes, we ask for your consent again.
Policy version: {POLICY_VERSION}.""")


# ------------------------------------------------------------------ CLI


def _status() -> int:
    tr = i18n.tr
    name, contact = responsible()
    print(tr(pl=f"Administrator: {name} {contact}  · zasady {POLICY_VERSION}",
             en=f"Controller: {name} {contact}  · policy {POLICY_VERSION}"))
    for person in tenant.users().values():
        given = consent(person)
        if controller(person):
            state = tr(pl="administrator", en="controller")
        elif not given:
            state = tr(pl="bez zgody", en="no consent")
        elif given.get("version") != POLICY_VERSION:
            state = tr(pl=f"zgoda na starą wersję {given.get('version')}", en=f"consent to old {given.get('version')}")
        else:
            state = tr(pl=f"zgoda {given.get('accepted_at')}", en=f"consent {given.get('accepted_at')}")
        print(f"{person.id:12} {state:40} {tr(pl='ostatnio', en='last seen')} {last_seen(person) or '—'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    tr = i18n.tr
    parser = argparse.ArgumentParser(prog="python -m core.privacy")
    parser.add_argument("--lang", choices=tuple(i18n.LANGS))
    sub = parser.add_subparsers(dest="command")
    setup = sub.add_parser("setup")
    for flag in ("controller", "contact", "host", "location"):
        setup.add_argument(f"--{flag}")
    setup.add_argument("--inactive-days", type=int)
    setup.add_argument("--backup-days", type=int)
    sub.add_parser("policy")
    keep = sub.add_parser("retention")
    keep.add_argument("--apply", action="store_true")
    log = sub.add_parser("log")
    log.add_argument("--person")
    log.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    if args.lang:
        i18n.force(args.lang)

    if args.command == "setup":
        stored = {k: v for k, v in settings().items()}
        for flag in ("controller", "contact", "host", "location", "inactive_days", "backup_days"):
            value = getattr(args, flag)
            if value is not None:
                stored[flag] = value
        _write(SETTINGS, stored)
        audit.record("policy", detail="settings changed")
        print(tr(pl=f"Zapisano {SETTINGS}", en=f"Wrote {SETTINGS}"))
        return 0
    if args.command == "policy":
        print(policy())
        return 0
    if args.command == "retention":
        due = inactive()
        if not due:
            print(tr(pl="Nikt nie przekroczył limitu nieaktywności.", en="Nobody is past the inactivity limit."))
            return 0
        for person, last in due:
            print(f"{person.id:12} {tr(pl='ostatnio', en='last seen')} {last or '—'}")
            if args.apply:
                from etl import garmin_auth

                garmin_auth.disconnect(person.tokenstore)
                tenant.erase(person)
                audit.record("inactive_erase", person.id, last_seen=last)
        if not args.apply:
            print(tr(pl="Bez --apply nic nie usunięto.", en="Nothing deleted without --apply."))
        return 0
    if args.command == "log":
        for item in reversed(audit.events(args.person, args.limit)):
            extra = " ".join(f"{k}={v}" for k, v in item.items() if k not in ("at", "event", "person"))
            print(f"{item['at']}  {item['event']:16} {item.get('person', '—'):10} {extra}")
        return 0
    return _status()


if __name__ == "__main__":
    raise SystemExit(main())
