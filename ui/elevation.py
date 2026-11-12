"""One viewer preference controlling height, gain, maps and splits together."""
from __future__ import annotations

import streamlit as st

from core import elevation, i18n, tenant


def selector() -> None:
    if tenant.current().source != "garmin":
        return
    # This is a page-wide control: the normal rerun refreshes every dependent
    # tile, including values read before its position in the page.
    st.segmented_control(
        i18n.tr(pl="Źródło wysokości", en="Elevation source"), list(elevation.MODES),
        default=elevation.current(), key=elevation.KEY, required=True,
        format_func=elevation.labels().get,
        on_change=lambda: elevation.remember(st.session_state.get(elevation.KEY)),
        help=i18n.tr(pl="Zmienia profil, przewyższenia i splity w całym dashboardzie. Oryginalne dane pozostają zachowane. "
                        "Tam, gdzie brakuje korekty, pozostaje zapis źródłowy.",
                     en="Changes the profile, elevation gain and splits throughout the dashboard. Original data is preserved. "
                        "Where no correction is available, the recorded values remain."),
    )
