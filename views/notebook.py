"""Insight notes and the SQL console -- the two pages that read the warehouse raw."""

from __future__ import annotations

import streamlit as st

import bento
import db
import i18n
import insights as insights_mod
import shell
import theme as tz


def insights() -> None:
    bento.header(
        i18n.page("insights"),
        "Notatki z `insights/`: proza plus bloki SQL liczone na świeżych danych przy każdym wejściu — wniosek nie "
        "zestarzeje się po cichu. Nowy dodaje `/garmin-insight` w Claude Code.",
    )
    found = insights_mod.load_all()
    if not found:
        st.caption("Brak plików. W Claude Code: `/garmin-insight hrv vs obciążenie treningowe`.")
        return

    for insight in found:
        meta = [insight.created or "", " ".join(f"#{tag}" for tag in insight.tags), insight.path.name]
        with bento.panel(f"{'📌 ' if insight.meta.get('pinned') else ''}{insight.title}",
                         caption=" · ".join(m for m in meta if m), key=f"insight_{insight.slug}"):
            with st.expander("Treść", expanded=bool(insight.meta.get("pinned")) or len(found) == 1):
                for index, block in enumerate(insight.blocks):
                    if block.kind == "text":
                        st.markdown(block.body)
                        continue
                    _render_sql_block(insight, index, block)


def _render_sql_block(insight, index: int, block) -> None:
    try:
        result = shell.query(block.body)
    except Exception as exc:  # noqa: BLE001 - surfaced in the UI
        st.error(f"SQL nie przeszło: {exc}")
        st.code(block.body, language="sql")
        return

    kind = block.options.get("chart", "table")
    x = block.options.get("x")
    ys = [c for c in (block.options.get("y") or "").split(",") if c]
    title = block.options.get("title")
    if title and kind != "table":
        st.markdown(f"### {title}")

    key = f"{insight.slug}_{index}"
    try:
        if kind == "metric":
            row = result.iloc[0]
            columns = st.columns(len(ys))
            for column, name in zip(columns, ys):
                column.metric(name, f"{row[name]}")
        elif kind in ("line", "area") and x and ys:
            tz.show(
                tz.timeseries(
                    result, x, {c: c for c in ys}, fill=(kind == "area" and len(ys) == 1)
                ),
                table=result,
                key=key,
            )
        elif kind == "bar" and x and ys:
            figure = tz.bars(result, x, ys[0]) if len(ys) == 1 else tz.stacked(result, x, ys)
            tz.show(figure, table=result, key=key)
        elif kind == "scatter" and x and ys:
            tz.show(
                tz.scatter(result, x, ys[0], color=ys[1] if len(ys) > 1 else None),
                table=result,
                key=key,
            )
        else:
            st.dataframe(tz.readable_paces(result), width="stretch", hide_index=True)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Nie udało się narysować: {exc}")
        st.dataframe(tz.readable_paces(result), width="stretch", hide_index=True)
    with st.popover("SQL"):
        st.code(block.body, language="sql")


def sql() -> None:
    schema = db.schema()
    bento.header(i18n.page("sql"), "Hurtownia jest otwarta (DuckDB na plikach parquet); zapytania tylko czytają.")
    default = (
        "SELECT p.day, p.ctl, p.atl, p.tsb, d.hrv_last_night, d.rhr, d.readiness\n"
        "FROM pmc p LEFT JOIN daily d USING (day)\n"
        "ORDER BY p.day DESC\nLIMIT 50"
    )
    left, right = st.columns([3, 1], gap="small")
    with left, bento.panel("Zapytanie", key="sql_query"):
        query = st.text_area("SQL", default, height=180, label_visibility="collapsed")
        run = st.button("Wykonaj", type="primary")
    with right, bento.panel("Tabele", key="sql_tables", caption="Rozwiń, żeby zobaczyć kolumny."):
        for name, columns in schema.items():
            with st.expander(f"{name} ({len(columns)})"):
                st.code(", ".join(columns))
    if run:
        with bento.panel("Wynik", key="sql_result"):
            try:
                st.dataframe(tz.readable_paces(db.query(query)), width="stretch", hide_index=True)
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
