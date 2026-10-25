"""Glossary page: every number on the dashboard, what it is and why it is there."""

from __future__ import annotations

import streamlit as st

import bento
import glossary


def render() -> None:
    bento.header(
        "Słownik",
        "Co oznacza każdy wskaźnik, po co jest i jak go czytać. To samo objaśnienie jest pod „?” w nagłówku "
        "każdego kafla i w podpowiedziach liczb.",
    )
    needle = st.text_input("Szukaj", placeholder="szukaj: HRV, TSB, pewność…", key="glossary_search",
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
        with columns[index % 2], bento.panel(group, key=f"glossary_{index}", caption=f"{len(items)} pojęć"):
            for item in items:
                with st.expander(item.name, expanded=bool(needle)):
                    st.markdown(item.what)
                    st.markdown(f"*Po co:* {item.why}")
                    if item.read:
                        st.markdown(f"*Jak czytać:* {item.read}")
    with bento.panel("Wykresy", key="glossary_charts"):
        st.markdown(glossary.TREND_HOW)
