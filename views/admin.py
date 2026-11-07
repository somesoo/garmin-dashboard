"""Admin: how many people, what the server uses, the state of every warehouse and pull.

Only for a person marked ``admin`` in the registry (``python -m core.tenant admin
<id>``): app.py registers the page for them alone, and ``render`` checks again.
The numbers come from ``monitor.py``; nothing here reads anyone's health data.

The live part (processes, RAM, CPU, warnings) is a fragment that refreshes
itself; the people and the pulls redraw on demand. Starting a pull or a
rebuild for someone else is allowed one at a time: the server has 1 GB of RAM,
and two builds side by side once pushed it to 7 MB free.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from ui import tables
from ui import bento
from core import i18n
from core import monitor
from core import sync
from core import audit
from core import privacy
from core import tenant

REFRESH_S = 15


def _dec(value: float, digits: int = 1) -> str:
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if i18n.lang() == "pl" else text


def _bytes(value: float | None) -> str:
    if value is None:
        return "—"
    for unit, size in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if value >= size:
            return f"{_dec(value / size)} {unit}"
    return f"{int(value)} B"


def _ago(value: str | None) -> str:
    tr = i18n.tr
    try:
        when = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return "—"
    minutes = (dt.datetime.now() - when).total_seconds() / 60
    if minutes < 1:
        return tr(pl="przed chwilą", en="just now")
    if minutes < 90:
        return tr(pl=f"{minutes:.0f} min temu", en=f"{minutes:.0f} min ago")
    if minutes < 48 * 60:
        return tr(pl=f"{minutes / 60:.0f} h temu", en=f"{minutes / 60:.0f} h ago")
    return f"{when:%d.%m.%Y %H:%M}"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    hours = seconds / 3600
    if hours < 1:
        return f"{seconds / 60:.0f} min"
    if hours < 48:
        return f"{_dec(hours)} h"
    return i18n.tr(pl=f"{hours / 24:.0f} dni", en=f"{hours / 24:.0f} days")


def render() -> None:
    tr = i18n.tr
    if not tenant.current().admin:
        st.error(tr(pl="Ta strona jest tylko dla administratora serwera.", en="This page is for the server's admin only."))
        return
    bento.header(i18n.page("admin"), tr(
        pl="Ile osób korzysta z aplikacji, co zużywa serwer i czy pobierania działają. Bez danych zdrowotnych — "
           "tylko rozmiary, liczby i godziny.",
        en="How many people use the app, what the server uses and whether the pulls work. No health data — "
           "sizes, counts and times only."))
    folks = monitor.people()
    st.fragment(run_every=REFRESH_S)(_live)(folks)
    _people(folks)
    _pulls(folks)
    _privacy()


# ------------------------------------------------------------------ live: the machine


def _live(folks: list[dict]) -> None:
    tr = i18n.tr
    machine = monitor.snapshot()
    version = monitor.code()
    server = next((p for p in machine["processes"] if p["role"] == "server"), None)
    app_rss = sum(p["rss_kb"] or 0 for p in machine["processes"]) * 1024
    mem, room = machine["memory"], machine["disk"]
    sources = pd.Series([p.get("source") for p in folks]).value_counts().to_dict()
    cells = bento.row(1, 1, 1, 1)
    bento.stat(cells[0], tr(pl="Osoby", en="People"), str(len(folks)),
               " · ".join(f"{name} {count}" for name, count in sources.items()), key="adm_people")
    bento.stat(cells[1], tr(pl="RAM aplikacji", en="App RAM"), _bytes(app_rss),
               tr(pl=f"z {_bytes((mem['total_kb'] or 0) * 1024)} serwera", en=f"of the server's "
                  f"{_bytes((mem['total_kb'] or 0) * 1024)}") if mem["total_kb"] else None, key="adm_ram",
               help=tr(pl="Suma pamięci wszystkich procesów aplikacji: serwer, API, trwające pobrania.",
                       en="Memory of every app process together: the server, the API, running pulls."))
    cpu = server.get("cpu_pct") if server else None
    bento.stat(cells[2], tr(pl="CPU serwera aplikacji", en="App server CPU"),
               f"{_dec(cpu)}%" if cpu is not None else "—",
               tr(pl=f"cała maszyna {_dec(machine['cpu_pct'])}% · {machine['cores']} rdz.",
                  en=f"whole machine {_dec(machine['cpu_pct'])}% · {machine['cores']} cores")
               if machine["cpu_pct"] is not None else None, key="adm_cpu",
               help=tr(pl="Procent jednego rdzenia, mierzony przez 0,3 s. Load average w kontenerze LXC to "
                          "obciążenie hosta, więc go nie pokazujemy.",
                       en="Percent of one core, measured over 0.3 s. Inside an LXC container the load average "
                          "is the host's, so it is not shown."))
    bento.stat(cells[3], tr(pl="Wolne miejsce", en="Free disk"), _bytes(room["free"]),
               tr(pl=f"dane aplikacji {_bytes(room['data'])}", en=f"app data {_bytes(room['data'])}"), key="adm_disk")

    left, right = bento.row(2, 2)
    with left, bento.panel(tr(pl="Serwer", en="Server"), key="adm_server",
                           caption=tr(pl=f"Odświeża się co {REFRESH_S} s · {machine['at'][11:]}",
                                      en=f"Refreshes every {REFRESH_S} s · {machine['at'][11:]}")):
        lines = []
        if mem["total_kb"]:
            lines.append(tr(pl=f"RAM: wolne {_bytes(mem['available_kb'] * 1024)} z {_bytes(mem['total_kb'] * 1024)}",
                            en=f"RAM: {_bytes(mem['available_kb'] * 1024)} free of {_bytes(mem['total_kb'] * 1024)}"))
        if mem["swap_total_kb"]:
            used = (mem["swap_total_kb"] - (mem["swap_free_kb"] or 0)) * 1024
            lines.append(tr(pl=f"Swap: zajęte {_bytes(used)} z {_bytes(mem['swap_total_kb'] * 1024)}",
                            en=f"Swap: {_bytes(used)} used of {_bytes(mem['swap_total_kb'] * 1024)}"))
        lines.append(tr(pl=f"Dysk: zajęte {_bytes(room['used'])} z {_bytes(room['total'])}",
                        en=f"Disk: {_bytes(room['used'])} used of {_bytes(room['total'])}"))
        if machine["sessions"] is not None:
            lines.append(tr(pl=f"Otwarte karty przeglądarki: {machine['sessions']}",
                            en=f"Open browser tabs: {machine['sessions']}"))
        if server:
            lines.append(tr(pl=f"Serwer działa od {_duration(server['uptime_s'])} (pid {server['pid']})",
                            en=f"Server up for {_duration(server['uptime_s'])} (pid {server['pid']})"))
        if version["commit"]:
            lines.append(tr(pl=f"Kod: {version['commit']}", en=f"Code: {version['commit']}")
                         + (tr(pl=" — nowszy niż działający serwer, potrzebny restart", en=" — newer than the "
                               "running server, a restart is needed") if version["stale"] else ""))
        bento.bullets(lines)
        roles = {"server": tr(pl="serwer", en="server"), "api": "API", "etl": tr(pl="pobieranie / przebudowa",
                 en="pull / rebuild"), "other": tr(pl="inny", en="other")}
        table = pd.DataFrame([{
            tr(pl="proces", en="process"): roles[p["role"]], "pid": p["pid"],
            "RAM": _bytes((p["rss_kb"] or 0) * 1024) if p["rss_kb"] is not None else "—",
            "CPU": f"{_dec(p['cpu_pct'])}%" if p.get("cpu_pct") is not None else "—",
            tr(pl="działa od", en="up for"): _duration(p["uptime_s"]),
        } for p in machine["processes"]])
        tables.show(table)
    with right, bento.panel(tr(pl="Co wymaga uwagi", en="What needs attention"), key="adm_warnings"):
        found = monitor.warnings(machine, folks, version)
        if not found:
            st.success(tr(pl="Wszystko w porządku.", en="All good."))
        names = {p["id"]: p.get("name", p["id"]) for p in folks}
        for item in found:
            text = _warning(item, names.get(item["person"], item["person"]))
            (st.error if item["code"] in ("memory_low", "disk_low", "unreadable", "token_expired") else st.warning)(text)


def _warning(item: dict, who: str | None) -> str:
    tr = i18n.tr
    value = item["value"]
    return {
        "memory_low": tr(pl=f"Mało wolnej pamięci: {value}% RAM. Przy braku pamięci earlyoom ubija procesy Pythona, "
                            "także serwer.",
                         en=f"Little free memory: {value}% of RAM. Out of memory, earlyoom kills Python processes, "
                            "the server included."),
        "disk_low": tr(pl=f"Mało miejsca na dysku: wolne {value}%.", en=f"Little disk space: {value}% free."),
        "code_stale": tr(pl="Kod na dysku jest nowszy niż działający serwer — zrestartuj usługę.",
                         en="The code on disk is newer than the running server — restart the service."),
        "parallel_runs": tr(pl=f"{value} pobrania/przebudowy naraz — na 1 GB RAM to ryzyko braku pamięci.",
                            en=f"{value} pulls/rebuilds at once — on 1 GB of RAM that risks running out of memory."),
        "unreadable": tr(pl=f"{who}: nie da się odczytać stanu ({value}).", en=f"{who}: state unreadable ({value})."),
        "no_build": tr(pl=f"{who}: brak zbudowanych tabel.", en=f"{who}: no tables built."),
        "token_expired": tr(pl=f"{who}: Garmin odrzucił zapisane logowanie — trzeba połączyć konto ponownie.",
                            en=f"{who}: Garmin rejected the saved login — the account has to be connected again."),
        "pull_failed": tr(pl=f"{who}: ostatnie pobranie skończyło się błędem (kod {value}).",
                          en=f"{who}: the last pull failed (code {value})."),
        "pull_died": tr(pl=f"{who}: ostatnie pobranie przerwało się bez wyniku (zabity proces?).",
                        en=f"{who}: the last pull stopped without a result (a killed process?)."),
        "pull_stale": tr(pl=f"{who}: brak udanego pobrania od {value} h." if value is not None
                         else f"{who}: jeszcze żadnego udanego pobrania.",
                         en=f"{who}: no successful pull for {value} h." if value is not None
                         else f"{who}: no successful pull yet."),
        "rebuild_waiting": tr(pl=f"{who}: przebudowa czeka w kolejce, a nic nie działa.",
                              en=f"{who}: a rebuild is queued and nothing is running."),
        "not_connected": tr(pl=f"{who}: konto Garmin niepołączone.", en=f"{who}: Garmin account not connected."),
    }[item["code"]]


# ------------------------------------------------------------------ the people


def _people(folks: list[dict]) -> None:
    tr = i18n.tr
    yes, no = tr(pl="tak", en="yes"), tr(pl="nie", en="no")
    sources = {"garmin": "Garmin", "apple": "Apple"}
    rows = []
    for p in folks:
        rows.append({
            tr(pl="osoba", en="person"): p.get("name", p["id"]),
            "id": p["id"],
            tr(pl="źródło", en="source"): sources.get(p.get("source"), p.get("source")),
            tr(pl="logowanie", en="sign-in"): ", ".join(p.get("identities") or []) or "—",
            "admin": yes if p.get("admin") else "",
            tr(pl="dane", en="data"): _bytes(p.get("bytes")),
            tr(pl="surowe", en="raw"): _bytes(p.get("raw_bytes")),
            tr(pl="tabele", en="tables"): _bytes(p.get("tables_bytes")),
            tr(pl="dni", en="days"): p.get("days"),
            tr(pl="aktywności", en="activities"): p.get("activities"),
            tr(pl="ostatni dzień", en="last day"): p.get("last_day") or "—",
            tr(pl="zbudowano", en="built"): _ago(p.get("built_at")),
            "Garmin": (yes if p["garmin"] else no) if p.get("garmin") is not None else "—",
            tr(pl="klucze API", en="API keys"): p.get("keys"),
            tr(pl="strefy z testu", en="zones from a test"): yes if p.get("zones") else "",
        })
    with bento.panel(tr(pl="Osoby", en="People"), key="adm_people_table",
                     caption=tr(pl=f"{len(folks)} w rejestrze (data/users.json). Admina nadaje "
                                   "`python -m core.tenant admin <id>` w konsoli serwera.",
                                en=f"{len(folks)} in the registry (data/users.json). Admin is granted with "
                                   "`python -m core.tenant admin <id>` in the server's shell.")):
        tables.show(pd.DataFrame(rows))


# ------------------------------------------------------------------ the pulls


def _pulls(folks: list[dict]) -> None:
    tr = i18n.tr
    busy = [p for p in folks if p.get("running")]
    with bento.panel(tr(pl="Synchronizacja", en="Sync"), key="adm_pulls",
                     caption=tr(pl="Pobieranie z Garmina i przebudowa tabel każdej osoby. Jedno naraz — serwer ma "
                                   "mało RAM.",
                                en="Pulling from Garmin and rebuilding each person's tables. One at a time — the "
                                   "server has little RAM.")):
        if busy:
            st.info(tr(pl=f"Trwa: {', '.join(p.get('name', p['id']) for p in busy)}. Przyciski wrócą, gdy skończy.",
                       en=f"Running: {', '.join(p.get('name', p['id']) for p in busy)}. The buttons return when "
                          "it is done."))
        codes = {0: tr(pl="OK", en="OK"), 1: tr(pl="błąd", en="error"),
                 2: tr(pl="logowanie wygasło", en="login expired"), None: "—"}
        for p in folks:
            if p.get("error"):
                continue
            state = tr(pl="trwa", en="running") if p.get("running") else codes.get(p.get("pull_code"),
                                                                                    str(p.get("pull_code")))
            label = (f"{p.get('name', p['id'])} · {tr(pl='ostatnio', en='last')} {_ago(p.get('pull_finished'))} · "
                     f"{state}")
            with st.expander(label):
                st.caption(tr(pl=f"Start {p.get('pull_started') or '—'} · koniec {p.get('pull_finished') or '—'} · "
                                 f"tabele zbudowane {p.get('built_at') or '—'}",
                              en=f"Started {p.get('pull_started') or '—'} · finished {p.get('pull_finished') or '—'} · "
                                 f"tables built {p.get('built_at') or '—'}"))
                pull, rebuild = st.columns(2)
                can_pull = p.get("source") == "garmin" and bool(p.get("garmin"))
                if pull.button(tr(pl="Pobierz teraz", en="Pull now"), key=f"adm_pull_{p['id']}",
                               disabled=bool(busy) or not can_pull, type="primary"):
                    _start(p["id"], None)
                if rebuild.button(tr(pl="Przelicz tabele", en="Rebuild tables"), key=f"adm_rebuild_{p['id']}",
                                  disabled=bool(busy)):
                    _start(p["id"], ["--rebuild-only"])
                log = monitor.logs(tenant.get(p["id"]))
                st.code(log or tr(pl="(pusty log)", en="(empty log)"), language=None)
        with st.expander(tr(pl="Log serwera", en="Server log")):
            st.code(monitor.server_log() or tr(pl="(pusty log)", en="(empty log)"), language=None)


def _start(person_id: str, args: list[str] | None) -> None:
    with tenant.use(person_id):
        started = sync.start(args)
    if started and person_id != tenant.current().id:
        # Acting on someone else's data is the admin's to answer for: it goes to their access log.
        audit.record("admin", person_id, by=tenant.current().id, detail=" ".join(args or ["pull"]))
    if not started:
        st.warning(i18n.tr(pl="Już trwa — spróbuj, gdy skończy.", en="Already running — try when it is done."))
        return
    st.rerun()


# ------------------------------------------------------------------ privacy: consents, retention, access


def _privacy() -> None:
    """Who consented, who is past the inactivity limit, who was refused -- no health data in any of it."""
    tr = i18n.tr
    stored = privacy.settings()
    due = {person.id for person, _ in privacy.inactive()}
    rows = []
    for person in tenant.users().values():
        given = privacy.consent(person)
        if privacy.controller(person):
            state = tr(pl="administrator", en="controller")
        elif not given:
            state = tr(pl="brak zgody", en="no consent")
        elif given.get("version") != privacy.POLICY_VERSION:
            state = tr(pl=f"stara wersja {given.get('version')}", en=f"old version {given.get('version')}")
        else:
            state = tr(pl=f"zgoda {str(given.get('accepted_at', ''))[:10]}", en=f"consent {str(given.get('accepted_at', ''))[:10]}")
        last = privacy.last_seen(person)
        rows.append({tr(pl="osoba", en="person"): person.name, tr(pl="zgoda", en="consent"): state,
                     tr(pl="ostatnio", en="last seen"): str(last or "—"),
                     tr(pl="do usunięcia", en="to delete"): "●" if person.id in due else ""})
    name, contact = privacy.responsible()
    left, right = bento.row(2, 2)
    with left, bento.panel(tr(pl="Prywatność", en="Privacy"), key="adm_privacy",
                           caption=tr(pl=f"Zasady {privacy.POLICY_VERSION} · administrator: {name} {contact} · konto "
                                         f"nieużywane {stored['inactive_days']} dni do usunięcia.",
                                      en=f"Policy {privacy.POLICY_VERSION} · controller: {name} {contact} · accounts "
                                         f"unused for {stored['inactive_days']} days are deleted.")):
        tables.show(pd.DataFrame(rows))
        if due:
            st.warning(tr(pl="Konta po terminie usuwa `python -m core.privacy retention --apply` na serwerze.",
                          en="Accounts past the limit are deleted by `python -m core.privacy retention --apply` on "
                             "the server."))
    with right, bento.panel(tr(pl="Dziennik dostępu", en="Access log"), key="adm_audit",
                            caption=tr(pl=f"Ostatnie zdarzenia wszystkich osób ({audit.KEEP_DAYS} dni). Odmowy "
                                          "logowania to pierwsze, na co patrzeć.",
                                       en=f"Latest events of everyone ({audit.KEEP_DAYS} days). Refused sign-ins "
                                          "are the first thing to look at.")):
        items = audit.events(limit=40)
        if not items:
            st.caption(tr(pl="Pusto.", en="Empty."))
            return
        tables.show(pd.DataFrame([{
            tr(pl="kiedy", en="when"): item["at"].replace("T", " "),
            tr(pl="co", en="what"): item["event"],
            tr(pl="kto", en="who"): item.get("person") or item.get("identity") or "—",
            tr(pl="skąd", en="from"): item.get("ip") or "—"} for item in items]))
