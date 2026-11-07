"""Account: who I am, where my data comes from, my phone, my keys, my data.

Everything here acts on the signed-in person only (tenant.current()):

- profile -- the name the dashboard uses (tenant.update), the Google account;
- source -- Garmin or Apple Health. Garmin: connect the Garmin account from the
  browser (etl/garmin_auth.py: password used once, two-step code supported) and
  pull now or the history from a date. Apple: upload the Health export once,
  make a key for the daily push from the iPhone (api.py, etl/apple_push.py);
- phone -- a read key for the app (PWA), keys listed and revocable (shown once,
  only the hash kept);
- your data -- an archive of everything, or deleting everything.

A person with no data yet lands here first (app.py, ONBOARDING).
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import streamlit as st

import api
from ui import tables
from ui import bento
from core import i18n
from core import level
from ui import shell
from core import sync
from core import tenant

NEW_TOKEN = "devices_new_token"


def _base_url() -> str:
    """The address the phone should call: the host this page was opened on."""
    try:
        headers = st.context.headers
        host = headers.get("x-forwarded-host") or headers.get("host") or "localhost:8501"
    except Exception:  # noqa: BLE001 - no browser context
        host = "localhost:8501"
    scheme = "http" if host.startswith(("localhost", "127.")) else "https"
    return f"{scheme}://{host}"


SOURCE_LABELS = {"garmin": "Garmin Connect", "apple": "Apple Health"}
PENDING = "garmin_pending_login"


def _email() -> str | None:
    try:
        return st.user.get("email") if st.user.is_logged_in else None
    except Exception:  # noqa: BLE001 - no sign-in configured
        return None


def render() -> None:
    tr = i18n.tr
    person = tenant.current()
    email = _email() or (person.identities[0] if person.identities else None)
    bento.header(i18n.page("konto"),
                 tr(pl=f"{person.name}{f' · {email}' if email else ''} · dane z: {SOURCE_LABELS[person.source]}. "
                       "Wszystko tutaj dotyczy tylko Ciebie.",
                    en=f"{person.name}{f' · {email}' if email else ''} · data from: {SOURCE_LABELS[person.source]}. "
                       "Everything here is about you only."))
    if not shell.has_data():
        _welcome(person)
    fresh = st.session_state.pop(NEW_TOKEN, None)
    if fresh:
        _show_new(*fresh)
    left, right = bento.row(2, 2)
    with left:
        _source(person)
        if person.source == "apple":
            _upload(person)
            _shortcut(person)
        else:
            _garmin(person)
        _zones(person)
    with right:
        _profile(person, email)
        _level()
        _app(person)
        _tokens(person)
        _yours(person)


def _welcome(person: tenant.User) -> None:
    tr = i18n.tr
    with bento.panel(tr(pl="Zacznijmy", en="Let's start"), key="acc_welcome"):
        st.markdown(tr(
            pl="Nie ma tu jeszcze Twoich danych. Wybierz, skąd mają przychodzić, i połącz źródło poniżej — "
               "pierwsze liczby pojawią się po pobraniu (zwykle kilka minut). Dashboard otworzy się sam.",
            en="There is no data of yours here yet. Choose where it should come from and connect it below — "
               "the first numbers show up once it is pulled (usually a few minutes). The dashboard opens by itself."))
    st.fragment(run_every=10)(_wait_for_data)()


def _wait_for_data() -> None:
    """While onboarding: the moment the first build lands, the whole app reruns into the dashboard."""
    if shell.has_data():
        st.rerun(scope="app")


def _profile(person: tenant.User, email: str | None) -> None:
    tr = i18n.tr
    from core import auth

    with bento.panel(tr(pl="Profil", en="Profile"), key="acc_profile",
                     caption=tr(pl=f"Konto Google: {email}" if email else "Bez logowania (jedna osoba na serwerze).",
                                en=f"Google account: {email}" if email else "No sign-in (one person on this server).")):
        with st.form("acc_profile_form", border=False):
            name = st.text_input(tr(pl="Jak Cię nazywać", en="What to call you"), value=person.name, max_chars=60)
            if st.form_submit_button(tr(pl="Zapisz", en="Save")) and name.strip() and name.strip() != person.name:
                tenant.update(person.id, name=name)
                st.rerun()
        if auth.can_sign_out():
            st.button(tr(pl="Wyloguj", en="Sign out"), on_click=st.logout, key="acc_sign_out", type="tertiary")


def _level() -> None:
    """How much of the dashboard to show (core/level.py); pages above it leave the menu, tiles are not drawn."""
    tr = i18n.tr
    with bento.panel(tr(pl="Poziom szczegółów", en="Level of detail"), key="acc_level",
                     caption=tr(pl="Ile stron i wykresów pokazywać. Nic nie jest kasowane — wyższy poziom przywraca resztę.",
                                en="How many pages and charts to show. Nothing is deleted — a higher level brings the "
                                   "rest back.")):
        choice = st.segmented_control(
            tr(pl="Poziom", en="Level"), list(level.LEVELS), default=level.current(), required=True,
            key=level.KEY, format_func=level.labels().get, label_visibility="collapsed",
            on_change=lambda: level.remember(st.session_state.get(level.KEY)),
        )
        st.caption(level.descriptions()[choice or level.current()])


def _source(person: tenant.User) -> None:
    tr = i18n.tr
    describe = {
        "garmin": tr(pl="Zegarek Garmin: dane pobieramy z Garmin Connect — sami, co kilka godzin.",
                     en="A Garmin watch: data is pulled from Garmin Connect — on its own, every few hours."),
        "apple": tr(pl="Apple Watch / iPhone: eksport z aplikacji Zdrowie na start, potem codzienna wysyłka z iPhone'a.",
                    en="Apple Watch / iPhone: the Health app export to start, then a daily push from the iPhone."),
    }
    with bento.panel(tr(pl="Skąd biorę dane", en="Where my data comes from"), key="acc_source"):
        choice = st.radio(tr(pl="Źródło", en="Source"), list(SOURCE_LABELS), index=list(SOURCE_LABELS).index(person.source),
                          format_func=SOURCE_LABELS.get, horizontal=True, key="acc_source_choice",
                          label_visibility="collapsed")
        st.caption(describe[choice])
        if choice != person.source:
            st.caption(tr(pl="Dane z poprzedniego źródła zostają zapisane; tabele przeliczą się z nowego.",
                          en="Data from the previous source is kept; the tables are rebuilt from the new one."))
            if st.button(tr(pl=f"Przełącz na {SOURCE_LABELS[choice]}", en=f"Switch to {SOURCE_LABELS[choice]}"),
                         type="primary", key="acc_source_save"):
                tenant.update(person.id, source=choice)
                st.cache_data.clear()
                st.rerun()


def _garmin(person: tenant.User) -> None:
    from etl import garmin_auth

    tr = i18n.tr
    store = person.tokenstore
    linked = garmin_auth.connected(store)
    with bento.panel("Garmin Connect", key="acc_garmin",
                     caption=tr(pl="Połączone — pobieramy co kilka godzin." if linked else "Niepołączone.",
                                en="Connected — pulled every few hours." if linked else "Not connected.")):
        pending = st.session_state.get(PENDING)
        if pending is not None:
            _garmin_code(person, pending)
        elif not linked:
            _garmin_login(person)
        else:
            just = st.session_state.pop("acc_connected_as", None)
            if just is not None:
                st.success(tr(pl=f"Połączono z Garmin Connect{f' jako {just}' if just else ''}. Pobieram dane w tle.",
                              en=f"Connected to Garmin Connect{f' as {just}' if just else ''}. Pulling the data."))
            st.fragment(run_every=5 if sync.running() else None)(_pull_status)()
            first, history = st.columns(2, vertical_alignment="bottom")
            if first.button(tr(pl="Pobierz teraz", en="Pull now"), type="primary", key="acc_pull",
                            disabled=sync.running()):
                sync.start()
                st.rerun()
            since = history.date_input(tr(pl="Historia od", en="History since"),
                                       value=dt.date.today() - dt.timedelta(days=365), key="acc_since",
                                       max_value=dt.date.today())
            if history.button(tr(pl="Pobierz historię", en="Pull the history"), key="acc_backfill",
                              disabled=sync.running()):
                sync.start(["--backfill", since.isoformat()])
                st.rerun()
            with st.expander(tr(pl="Odłącz konto Garmin", en="Disconnect the Garmin account")):
                st.caption(tr(pl="Usuwa klucze dostępu do Garmin Connect; pobrane dane zostają.",
                              en="Removes the access to Garmin Connect; the data already pulled stays."))
                if st.button(tr(pl="Odłącz", en="Disconnect"), key="acc_garmin_off"):
                    garmin_auth.disconnect(store)
                    st.rerun()


def _pull_status() -> None:
    tr = i18n.tr
    record = sync.last()
    if sync.running():
        st.info(tr(pl="Pobieranie trwa… strona odświeży się sama.", en="Pulling… the page refreshes by itself."))
    elif record.get("code") == 2:
        st.warning(tr(pl="Garmin odrzucił zapisane logowanie — połącz konto ponownie (Odłącz, potem zaloguj).",
                      en="Garmin rejected the saved login — connect the account again (Disconnect, then sign in)."))
    elif record and record.get("code") not in (0, None):
        st.warning(tr(pl="Ostatnie pobranie nie powiodło się — spróbuj ponownie za chwilę.",
                      en="The last pull failed — try again in a moment."))
    elif record.get("finished_at"):
        st.caption(tr(pl=f"Ostatnie pobranie: {record['finished_at'][:16].replace('T', ' ')}",
                      en=f"Last pull: {record['finished_at'][:16].replace('T', ' ')}"))


def _garmin_login(person: tenant.User) -> None:
    from etl import garmin_auth

    tr = i18n.tr
    st.caption(tr(pl="Hasło służy tylko do jednego logowania i nie jest zapisywane — zostaje klucz dostępu, "
                     "który możesz w każdej chwili odłączyć.",
                  en="The password is used for one sign-in and never stored — what stays is an access key you can "
                     "disconnect at any time."))
    with st.form("acc_garmin_login", border=False, clear_on_submit=True):
        email = st.text_input(tr(pl="E-mail Garmin", en="Garmin e-mail"), autocomplete="username")
        password = st.text_input(tr(pl="Hasło Garmin", en="Garmin password"), type="password",
                                 autocomplete="current-password")
        submitted = st.form_submit_button(tr(pl="Połącz z Garmin Connect", en="Connect Garmin Connect"),
                                          type="primary")
    if not submitted:
        return
    if not email.strip() or not password:
        st.error(tr(pl="Podaj e-mail i hasło.", en="Enter the e-mail and the password."))
        return
    try:
        with st.spinner(tr(pl="Łączę z Garmin Connect…", en="Connecting to Garmin Connect…")):
            status, value = garmin_auth.start(email, password, person.tokenstore)
    except Exception as exc:  # noqa: BLE001 - shown as a reason, never as a trace
        st.error(_garmin_error(garmin_auth.describe(exc)))
        return
    finally:
        password = None  # noqa: F841 - drop the reference at once
    if status == "mfa":
        st.session_state[PENDING] = value
        st.rerun()
    _connected(person, value)


def _garmin_code(person: tenant.User, pending) -> None:
    from etl import garmin_auth

    tr = i18n.tr
    st.markdown(tr(pl="Garmin wysłał kod weryfikacyjny (e-mail albo SMS). Wpisz go tutaj:",
                   en="Garmin sent a verification code (e-mail or text). Enter it here:"))
    with st.form("acc_garmin_mfa", border=False):
        code = st.text_input(tr(pl="Kod", en="Code"), max_chars=10, autocomplete="one-time-code")
        go, cancel = st.columns(2)
        confirmed = go.form_submit_button(tr(pl="Potwierdź", en="Confirm"), type="primary")
        dropped = cancel.form_submit_button(tr(pl="Anuluj", en="Cancel"))
    if dropped:
        st.session_state.pop(PENDING, None)
        st.rerun()
    if confirmed and code.strip():
        try:
            name = garmin_auth.finish(pending, code, person.tokenstore)
        except Exception as exc:  # noqa: BLE001
            st.error(_garmin_error(garmin_auth.describe(exc)))
            return
        st.session_state.pop(PENDING, None)
        _connected(person, name)


def _connected(person: tenant.User, name: str | None) -> None:
    """Right after a successful Garmin sign-in: the first pull -- a year of history for a newcomer."""
    first = not shell.has_data()
    sync.start(["--backfill", (dt.date.today() - dt.timedelta(days=365)).isoformat()] if first else None)
    st.session_state["acc_connected_as"] = name or ""
    st.rerun()


def _garmin_error(kind: str) -> str:
    tr = i18n.tr
    return {
        "credentials": tr(pl="Garmin nie przyjął e-maila albo hasła.", en="Garmin did not accept the e-mail or password."),
        "throttled": tr(pl="Garmin chwilowo blokuje logowania — spróbuj za kilkanaście minut.",
                        en="Garmin is blocking sign-ins for a while — try again in a quarter of an hour."),
    }.get(kind, tr(pl="Nie udało się połączyć z Garmin Connect — spróbuj ponownie.",
                   en="Could not connect to Garmin Connect — try again."))


def _show_new(token: str, scope: str) -> None:
    tr = i18n.tr
    with bento.panel(tr(pl="Nowy klucz — skopiuj teraz", en="New key — copy it now"), key="dev_new"):
        st.warning(tr(pl="Ten klucz widać tylko raz. Zapisz go w Skrócie albo w aplikacji; po odświeżeniu strony "
                         "zniknie.", en="This key is shown once. Put it into the Shortcut or the app; after a reload "
                                        "it is gone."))
        st.code(token, language=None)
        if scope == "ingest":
            st.code(f"POST {_base_url()}/api/ingest/apple\nAuthorization: Bearer {token}\n"
                    "Content-Type: application/json", language=None)
        else:
            # The key rides in the fragment: browsers never send it to a server or a log.
            st.markdown(tr(pl="Otwórz na telefonie (Android: Chrome → *Zainstaluj aplikację*; iPhone: Safari → "
                              "*Udostępnij → Do ekranu początkowego*, potem wklej klucz w aplikacji):",
                           en="Open on the phone (Android: Chrome → *Install app*; iPhone: Safari → *Share → Add to "
                              "Home Screen*, then paste the key inside the app):"))
            st.code(f"{_base_url()}/api/app/#token={token}", language=None)


def _make(person: tenant.User, name: str, scope: str) -> None:
    st.session_state[NEW_TOKEN] = (api.create_token(person, name, scope), scope)


def _upload(person: tenant.User) -> None:
    tr = i18n.tr
    with bento.panel(tr(pl="Historia z Apple Health", en="History from Apple Health"), key="dev_upload",
                     caption=tr(pl="Raz, na start: Zdrowie → zdjęcie profilu → Eksportuj wszystkie dane.",
                                en="Once, to start: Health → profile picture → Export All Health Data.")):
        state = _state(person)
        if state.get("export"):
            st.caption(tr(pl=f"Wczytany eksport: {state['export']} · wysyłek z iPhone'a: {state.get('pushes', 0)} · "
                             f"{state.get('days', 0)} dni",
                          en=f"Imported export: {state['export']} · pushes from the iPhone: {state.get('pushes', 0)} · "
                             f"{state.get('days', 0)} days"))
        upload = st.file_uploader(tr(pl="export.zip", en="export.zip"), type=["zip"], key="dev_export",
                                  label_visibility="collapsed")
        if upload is not None and st.button(tr(pl="Wczytaj eksport", en="Import the export"), type="primary",
                                            key="dev_import"):
            from etl import apple

            folder = person.root / "import"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"upload-{dt.datetime.now():%Y%m%dT%H%M%S}.zip"
            target.write_bytes(upload.getbuffer())
            try:
                apple.import_export(target)
            except (ValueError, OSError) as exc:
                st.error(tr(pl=f"To nie wygląda na eksport Apple Health: {exc}",
                            en=f"This does not look like an Apple Health export: {exc}"))
                return
            finally:
                target.unlink(missing_ok=True)
            started = sync.request_rebuild()
            st.success(tr(pl="Eksport zapisany — tabele przeliczają się w tle (minuta-dwie)." if started == "started"
                          else "Eksport zapisany — przeliczy się po trwającej przebudowie.",
                          en="Export saved — the tables are being rebuilt in the background (a minute or two)."
                          if started == "started" else "Export saved — it is rebuilt after the one running now."))


def _state(person: tenant.User) -> dict:
    try:
        return json.loads(person.state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _shortcut(person: tenant.User) -> None:
    tr = i18n.tr
    with bento.panel(tr(pl="Codzienna wysyłka z iPhone'a", en="Daily push from the iPhone"), key="dev_shortcut",
                     caption=tr(pl="Skrót iOS albo aplikacja Health Auto Export wysyła ostatnie dni na serwer.",
                                en="An iOS Shortcut or the Health Auto Export app sends the last days to the server.")):
        st.markdown(tr(
            pl="1. Utwórz klucz poniżej.\n"
               "2. **Skrót** (bezpłatnie): automatyzacja *Codziennie 9:00 → Uruchom od razu*; akcje *Znajdź próbki "
               "zdrowia* (tętno, HRV, tętno spoczynkowe, kroki, sen — ostatnie 3 dni) → *Słownik* w formacie "
               "`garmin-dashboard/1` → *Pobierz zawartość URL* metodą POST z nagłówkiem `Authorization`.\n"
               "3. **Health Auto Export** (płatna aplikacja, robi to w tle): *Automations → REST API*, format JSON, "
               "ten sam adres i nagłówek.\n\n"
               "Ta sama paczka wysłana dwa razy liczy się raz.",
            en="1. Make a key below.\n"
               "2. **Shortcut** (free): automation *Daily 9:00 → Run immediately*; actions *Find Health Samples* "
               "(heart rate, HRV, resting HR, steps, sleep — last 3 days) → *Dictionary* in the "
               "`garmin-dashboard/1` format → *Get Contents of URL* with POST and the `Authorization` header.\n"
               "3. **Health Auto Export** (paid app, does it in the background): *Automations → REST API*, JSON, "
               "the same address and header.\n\n"
               "The same batch sent twice counts once."))
        st.code(f"{_base_url()}/api/ingest/apple", language=None)
        if st.button(tr(pl="Utwórz klucz do wysyłki", en="Make a key for pushing"), key="dev_make_ingest",
                     type="primary"):
            _make(person, tr(pl="iPhone — wysyłka", en="iPhone — push"), "ingest")
            st.rerun()


def _app(person: tenant.User) -> None:
    tr = i18n.tr
    with bento.panel(tr(pl="Aplikacja na telefonie", en="App on the phone"), key="dev_app",
                     caption=tr(pl="Klucz do odczytu: telefon pobiera Twoją bazę i trzyma ją offline.",
                                en="A read key: the phone downloads your warehouse and keeps it offline.")):
        st.code(f"{_base_url()}/api/manifest\n{_base_url()}/api/db", language=None)
        if st.button(tr(pl="Utwórz klucz do odczytu", en="Make a read key"), key="dev_make_read"):
            _make(person, tr(pl="telefon — odczyt", en="phone — read"), "read")
            st.rerun()


def _tokens(person: tenant.User) -> None:
    tr = i18n.tr
    items = api.list_tokens(person)
    with bento.panel(tr(pl="Twoje klucze", en="Your keys"), key="dev_tokens",
                     caption=f"{len(items)} {i18n.plural(len(items), pl=('klucz', 'klucze', 'kluczy'), en=('key', 'keys'))}"):
        if not items:
            st.caption(tr(pl="Brak kluczy.", en="No keys."))
        for item in items:
            line, button = st.columns([5, 1], vertical_alignment="center")
            used = item["last_used"][:16].replace("T", " ") if item["last_used"] else "—"
            line.markdown(f"`{item['prefix']}…` · {item['name']} · {item['scope']} · "
                          + tr(pl=f"użyty {used}", en=f"used {used}"))
            if button.button(tr(pl="Odwołaj", en="Revoke"), key=f"dev_revoke_{item['prefix']}", type="tertiary"):
                api.revoke_token(person, item["prefix"])
                st.rerun()


def _yours(person: tenant.User) -> None:
    """A copy of everything, and deleting everything -- the person's own rights over their health data."""
    tr = i18n.tr
    with bento.panel(tr(pl="Twoje dane", en="Your data"), key="dev_yours",
                     caption=tr(pl="Kopia wszystkiego, co tu o Tobie jest, albo usunięcie tego.",
                                en="A copy of everything held about you here, or deleting it.")):
        if st.button(tr(pl="Przygotuj archiwum", en="Prepare an archive"), key="dev_archive"):
            st.session_state["dev_archive_data"] = tenant.archive(person)
        data = st.session_state.get("dev_archive_data")
        if data:
            st.download_button(tr(pl=f"Pobierz ({len(data) / 1e6:.1f} MB)", en=f"Download ({len(data) / 1e6:.1f} MB)"),
                               data=data, file_name=f"{person.id}-{dt.date.today()}.zip", mime="application/zip",
                               key="dev_download", on_click="ignore")
        if person.legacy:
            return
        with st.expander(tr(pl="Usuń wszystkie moje dane", en="Delete all my data")):
            st.caption(tr(pl="Usuwa surowe dane, tabele, plany, ustawienia i klucze. Nie da się tego cofnąć. "
                             f"Wpisz „{person.name}”, żeby potwierdzić.",
                          en="Deletes raw data, tables, plans, settings and keys. This cannot be undone. "
                             f"Type “{person.name}” to confirm."))
            typed = st.text_input(tr(pl="Potwierdzenie", en="Confirmation"), key="dev_erase_name",
                                  label_visibility="collapsed")
            if st.button(tr(pl="Usuń na zawsze", en="Delete for good"), key="dev_erase",
                         disabled=typed.strip() != person.name):
                removed = tenant.erase(person)
                st.session_state.pop("dev_archive_data", None)
                st.cache_data.clear()
                st.success(tr(pl=f"Usunięto: {', '.join(removed) or 'nic'}.", en=f"Deleted: {', '.join(removed) or 'nothing'}."))


def _zones(person: tenant.User) -> None:
    """Heart-rate zones: what they rest on now, and anchors typed in from a test (hrzones.py)."""
    from running import hrzones
    from running import physio

    tr = i18n.tr
    manual = hrzones.settings()
    has = shell.has_data()
    efforts = shell.table("run_efforts") if has else pd.DataFrame()
    runs = shell.table("run_sessions") if has else pd.DataFrame()
    # Anchored on today: without it the window would follow the last effort and never age.
    measured = physio.threshold_hr(efforts, pd.Timestamp.today().normalize()) if not efforts.empty else None
    data_max = physio.robust_hr_max(runs["max_hr"]) if not runs.empty and "max_hr" in runs.columns else None
    found = hrzones.anchors(lthr=(measured or {}).get("bpm"), hr_max=data_max, manual=manual)
    source = {"manual": tr(pl="wpisane z testu", en="typed in from a test"),
              "data": tr(pl="z Twoich danych", en="from your data"),
              "estimate": tr(pl="szacunek", en="an estimate")}
    with bento.panel(tr(pl="Strefy tętna", en="Heart rate zones"), key="acc_zones", terms=["hr_zones"],
                     caption=tr(pl="Od Twoich progów, nie od % tętna maksymalnego jak w Garminie.",
                                en="From your thresholds, not from % of the maximum as on Garmin.")):
        if found is None:
            st.caption(tr(pl="Nie ma jeszcze z czego ich wyznaczyć: brak wysiłku progowego i tętna maksymalnego. "
                             "Wpisz wynik testu poniżej.",
                          en="Nothing to set them from yet: no threshold effort and no maximum heart rate. "
                             "Type a test result in below."))
        else:
            _zone_summary(found, measured, source)
        _zone_form(manual)
        with st.expander(tr(pl="Na czym to stoi", en="What this rests on")):
            st.markdown(_zone_sources())


def _zone_summary(found: dict, measured: dict | None, source: dict[str, str]) -> None:
    from running import hrzones

    tr = i18n.tr
    lines = [tr(pl=f"Tętno progowe (LTHR): **{found['lthr']}** bpm — {source[found['lthr_source']]}",
                en=f"Threshold heart rate (LTHR): **{found['lthr']}** bpm — {source[found['lthr_source']]}"),
             tr(pl=f"Próg tlenowy (VT1): **{found['vt1']}** bpm — {source[found['vt1_source']]}",
                en=f"Aerobic threshold (VT1): **{found['vt1']}** bpm — {source[found['vt1_source']]}")]
    if found.get("hr_max"):
        lines.append(tr(pl=f"Tętno maksymalne: **{found['hr_max']}** bpm — {source[found['hr_max_source']]}",
                        en=f"Maximum heart rate: **{found['hr_max']}** bpm — {source[found['hr_max_source']]}"))
    st.markdown("\n".join(f"- {line}" for line in lines))
    if found["lthr_source"] == "data" and measured:
        n = measured.get("n", 1)
        st.caption(tr(pl=f"Próg = mediana średniego tętna {n} najmocniejszych wysiłków 18–60 min bliskich maksymalnego "
                         f"z 120 dni (ostatni {measured['day']}). Liczy się na nowo po każdym pobraniu; gdy zmieni "
                         "się o 3 bpm lub więcej, plan sam przelicza się od jutra.",
                      en=f"Threshold = the median average heart rate of the {n} hardest near-maximal 18–60 min "
                         f"efforts of 120 days (the latest {measured['day']}). It is recomputed after every pull; when "
                         "it moves by 3 bpm or more, the plan rebuilds itself from tomorrow."))
        if measured.get("stale"):
            st.warning(tr(pl=f"Ostatni mocny wysiłek był {measured['age_days']} dni temu. Strefy trzymają ostatni "
                             "zmierzony próg zamiast przeskakiwać na szacunek; po roku bez takiego wysiłku przejdą na "
                             "szacunek z HRmax. 30 min równo i mocno w pojedynkę odświeży próg.",
                          en=f"The last hard effort was {measured['age_days']} days ago. The zones keep the last "
                             "measured threshold instead of jumping to an estimate; after a year without such an "
                             "effort they move to the estimate from HRmax. 30 min even and hard on your own refreshes "
                             "the threshold."))
    if found["lthr_source"] == "estimate":
        st.caption(tr(pl="Bez wysiłku progowego LTHR to 93,5% tętna maksymalnego (średnia 1411 biegaczy, rozrzut "
                         "±5 bpm). 30 min równo i mocno w pojedynkę da zmierzony próg.",
                      en="Without a threshold effort LTHR is 93.5% of the maximum (the mean of 1411 runners, spread "
                         "±5 bpm). 30 min even and hard on your own gives a measured threshold."))
    if found["vt1_source"] == "estimate":
        st.caption(tr(pl="VT1 to szacunek: 0,91 × LTHR (te same 1411 osób, rozrzut ±9 bpm). Zmierzony — w laboratorium "
                         "albo pasem piersiowym przez DFA-α1 — wpisz poniżej.",
                      en="VT1 is an estimate: 0.91 × LTHR (the same 1411 runners, spread ±9 bpm). A measured one — in "
                         "a lab or with a chest strap via DFA-α1 — goes below."))
    names = [tr(pl="1 · regeneracja", en="1 · recovery"), tr(pl="2 · spokojnie", en="2 · easy"),
             tr(pl="3 · między progami", en="3 · between thresholds"),
             tr(pl="4 · tuż pod progiem", en="4 · just below threshold"),
             tr(pl="5 · od progu w górę", en="5 · threshold and up")]

    def text(low: int | None, high: int | None) -> str:
        return f"< {high + 1}" if low is None else f"≥ {low}" if high is None else f"{low}–{high}"

    tables.show(pd.DataFrame({tr(pl="strefa", en="zone"): names,
                              "bpm": [text(low, high) for low, high in hrzones.bands(found)]}))


def _zone_form(manual: dict) -> None:
    from running import hrzones

    tr = i18n.tr
    methods = {"lab": tr(pl="laboratorium (wymiana gazowa / mleczan)", en="lab (gas exchange / lactate)"),
               "field": tr(pl="test w terenie (30 min, średnia z ostatnich 20)", en="field test (30 min, last 20 averaged)"),
               "dfa": tr(pl="DFA-α1 z pasa piersiowego (VT1)", en="DFA-α1 from a chest strap (VT1)"),
               "other": tr(pl="inne", en="other")}
    today = dt.date.today()
    with st.form("acc_zones_form", border=False):
        st.markdown(tr(pl="**Wynik testu** — puste pole liczy się z danych.",
                       en="**A test result** — an empty field comes from the data."))
        a, b, c = st.columns(3)
        lthr = a.number_input("LTHR", min_value=120, max_value=215, value=manual.get("lthr"), step=1,
                              placeholder=tr(pl="z danych", en="from data"))
        vt1 = b.number_input("VT1", min_value=100, max_value=205, value=manual.get("vt1"), step=1,
                             placeholder=tr(pl="z danych", en="from data"))
        top = c.number_input("HRmax", min_value=140, max_value=230, value=manual.get("hr_max"), step=1,
                             placeholder=tr(pl="z danych", en="from data"))
        m, d = st.columns(2)
        method = m.selectbox(tr(pl="Skąd te liczby", en="Where from"), list(methods), format_func=methods.get,
                             index=list(methods).index(manual.get("method", "field")))
        when = d.date_input(tr(pl="Data testu", en="Test date"), max_value=today,
                            value=dt.date.fromisoformat(manual["measured"]) if manual.get("measured") else today)
        save, back = st.columns(2)
        saved = save.form_submit_button(tr(pl="Zapisz i przelicz", en="Save and rebuild"), type="primary")
        reset = back.form_submit_button(tr(pl="Wróć do danych", en="Back to the data"), disabled=not manual)
    if not (saved or reset):
        return
    values = {} if reset else {"lthr": lthr, "vt1": vt1, "hr_max": top, "method": method, "measured": when.isoformat()}
    wrong = hrzones.problems(values)
    if wrong:
        st.error({"vt1_above_lthr": tr(pl="VT1 musi być niższe niż LTHR.", en="VT1 has to be below LTHR."),
                  "lthr_above_max": tr(pl="LTHR musi być niższe niż tętno maksymalne.",
                                       en="LTHR has to be below the maximum heart rate.")}.get(
            wrong[0], tr(pl="Ta liczba jest poza zakresem.", en="That number is out of range.")))
        return
    hrzones.save(values)
    started = sync.request_rebuild(["--rebuild-only"])
    st.success(tr(pl="Zapisane — tabele przeliczają się w tle (minuta–dwie). " if started == "started"
                  else "Zapisane — przeliczy się po trwającym pobieraniu. ",
                  en="Saved — the tables are being rebuilt in the background (a minute or two). " if started == "started"
                  else "Saved — it is rebuilt after the pull running now. ")
               + tr(pl="Plan weźmie nowe strefy po „Przebuduj od jutra”.",
                    en="The plan takes the new zones after “Rebuild from tomorrow”."))


def _zone_sources() -> str:
    tr = i18n.tr
    return tr(
        pl="- **Dlaczego nie strefy Garmina.** Garmin domyślnie dzieli tętno na 50/60/70/80/90% maksymalnego. "
           "Progi wypadają u różnych osób przy bardzo różnym % HRmax, więc te same procenty wrzucają ludzi w różne "
           "domeny wysiłku: [Iannetta i in. 2020](https://doi.org/10.1249/MSS.0000000000002147) (n = 100), "
           "[Jamnick i in. 2020](https://doi.org/10.1007/s40279-020-01322-8), "
           "[Mann i in. 2013](https://doi.org/10.1007/s40279-013-0045-x).\n"
           "- **Szacunki bez testu**: VT2 ≈ 93,5 ± 2,5% i VT1 ≈ 85,1 ± 4,6% tętna szczytowego u 1411 biegaczy "
           "z testem gazometrycznym ([Esteve-Lanao i in. 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC12845794/)).\n"
           "- **Granice stref 2 i 4** (85% i 95% LTHR) to strefy Friela — praktyka trenerska, nie badanie.\n"
           "- **VT1 bez laboratorium**: DFA-α1 = 0,75 z pasa piersiowego "
           "([Rogers i in. 2021](https://doi.org/10.3389/fphys.2020.596567)); czujnik na nadgarstku jest do tego "
           "za mało dokładny ([Gillinov i in. 2017](https://doi.org/10.1249/MSS.0000000000001284)).\n"
           "- **Bez danych nie ma stref** — żadnego 220 − wiek: wzór nie ma podstaw w badaniach (Robergs i "
           "Landwehr 2002, *J Exerc Physiol Online* 5(2)).",
        en="- **Why not Garmin's zones.** Garmin splits heart rate into 50/60/70/80/90% of the maximum by default. "
           "The thresholds sit at very different % of HRmax from person to person, so the same percentages put people "
           "in different intensity domains: [Iannetta et al. 2020](https://doi.org/10.1249/MSS.0000000000002147) "
           "(n = 100), [Jamnick et al. 2020](https://doi.org/10.1007/s40279-020-01322-8), "
           "[Mann et al. 2013](https://doi.org/10.1007/s40279-013-0045-x).\n"
           "- **Estimates without a test**: VT2 ≈ 93.5 ± 2.5% and VT1 ≈ 85.1 ± 4.6% of peak heart rate in 1411 "
           "runners with a gas-exchange test ([Esteve-Lanao et al. 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC12845794/)).\n"
           "- **The limits of zones 2 and 4** (85% and 95% LTHR) are Friel's zones — coaching practice, not a study.\n"
           "- **VT1 without a lab**: DFA-α1 = 0.75 from a chest strap "
           "([Rogers et al. 2021](https://doi.org/10.3389/fphys.2020.596567)); a wrist sensor is not accurate enough "
           "for it ([Gillinov et al. 2017](https://doi.org/10.1249/MSS.0000000000001284)).\n"
           "- **No data, no zones** — no 220 − age: the formula has no research behind it (Robergs & Landwehr 2002, "
           "*J Exerc Physiol Online* 5(2)).")
