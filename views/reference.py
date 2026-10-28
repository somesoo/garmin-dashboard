"""Glossary page: every number on the dashboard, what it is and why it is there."""

from __future__ import annotations

import streamlit as st

import bento
import glossary
import i18n


def render() -> None:
    bento.header(
        i18n.page("slownik"),
        i18n.tr(pl="Co oznacza każdy wskaźnik, po co jest i jak go czytać. To samo objaśnienie jest pod „?” "
                   "w nagłówku każdego kafla i w podpowiedziach liczb.",
                en="What every indicator means, why it is there and how to read it. The same explanation sits "
                   "behind the “?” in every tile's header and in the number tooltips."),
    )
    needle = st.text_input(i18n.tr(pl="Szukaj", en="Search"),
                           placeholder=i18n.tr(pl="szukaj: HRV, TSB, pewność…", en="search: HRV, TSB, confidence…"),
                           key="glossary_search",
                           label_visibility="collapsed").strip().lower()
    groups = []
    for group, keys in glossary.groups().items():
        items = [glossary.term(key) for key in keys]
        if needle:
            items = [item for item in items if needle in f"{item.name} {item.what} {item.why} {item.read}".lower()]
        if items:
            groups.append((group, items))
    # Two columns, filled alternately: groups differ in length, and a strict
    # row grid would leave holes under the short ones.
    columns = bento.row(2, 2)
    for index, (group, items) in enumerate(groups):
        count = f"{len(items)} {i18n.plural(len(items), pl=('pojęcie', 'pojęcia', 'pojęć'), en=('term', 'terms'))}"
        with columns[index % 2], bento.panel(group, key=f"glossary_{index}", caption=count):
            for item in items:
                with st.expander(item.name, expanded=bool(needle)):
                    st.markdown(item.what)
                    st.markdown(f"*{glossary.why_label()}:* {item.why}")
                    if item.read:
                        st.markdown(f"*{glossary.read_label()}:* {item.read}")
    with bento.panel(i18n.tr(pl="Wykresy", en="Charts"), key="glossary_charts"):
        st.markdown(glossary.trend_how())
