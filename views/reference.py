"""Glossary page: every number on the dashboard, what it is and why it is there."""

from __future__ import annotations

import streamlit as st

import glossary


def render() -> None:
    st.title("Słownik")
    st.caption(
        "Co oznacza każdy wskaźnik, po co jest i jak go czytać. To samo objaśnienie jest pod „Co to jest?” "
        "przy sekcjach i w podpowiedziach kafelków."
    )
    needle = st.text_input("Szukaj", placeholder="np. HRV, TSB, pewność", key="glossary_search").strip().lower()
    for group, keys in glossary.groups().items():
        items = [glossary.term(key) for key in keys]
        if needle:
            items = [item for item in items if needle in f"{item.name} {item.what} {item.why} {item.read}".lower()]
        if not items:
            continue
        st.markdown(f"## {group}")
        for item in items:
            with st.expander(item.name, expanded=bool(needle)):
                st.markdown(item.what)
                st.markdown(f"*Po co:* {item.why}")
                if item.read:
                    st.markdown(f"*Jak czytać:* {item.read}")
    st.markdown("## Wykresy")
    st.markdown(glossary.TREND_HOW)
