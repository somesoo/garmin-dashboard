"""Devices: where the signed-in person's data comes from, and the keys that let a phone in.

For an Apple Watch person: upload the full Health export (once, for history) and
make a token for the iOS Shortcut that pushes every day (api.py, etl/apple_push.py).
For anyone: a read token for the phone app. A token is shown once; only its hash
is kept. Everything here acts on the signed-in person only (tenant.current()).
"""

from __future__ import annotations

import datetime as dt
import json

import streamlit as st

import api
import bento
import i18n
import sync
import tenant

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


def render() -> None:
    tr = i18n.tr
    person = tenant.current()
    source = {"apple": "Apple Health", "garmin": "Garmin Connect"}.get(person.source, person.source)
    bento.header(i18n.page("urzadzenia"),
                 tr(pl=f"Dane: {person.name} · źródło: {source}. Klucze, którymi telefon wysyła i pobiera Twoje dane "
                       "— każdy otwiera tylko Twoje dane i da się go odwołać.",
                    en=f"Data of: {person.name} · source: {source}. The keys a phone uses to send and fetch your data "
                       "— each opens only your data and can be revoked."))
    fresh = st.session_state.pop(NEW_TOKEN, None)
    if fresh:
        _show_new(*fresh)
    left, right = bento.row(2, 2)
    with left:
        if person.source == "apple":
            _upload(person)
            _shortcut(person)
        else:
            with bento.panel(tr(pl="Garmin", en="Garmin"), key="dev_garmin"):
                st.markdown(tr(pl="Dane przychodzą z Garmin Connect przyciskiem „Pobierz z Garmina” i co kilka godzin "
                                  "same. Telefon nie musi nic wysyłać.",
                               en="Data comes from Garmin Connect with the “Pull from Garmin” button and on its own "
                                  "every few hours. The phone does not need to send anything."))
    with right:
        _app(person)
        _tokens(person)
        _yours(person)


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
