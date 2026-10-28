"""The chart system: one palette, one plotly template, a few builders.

Every figure in the dashboard is built here so the whole page reads as one
system. Three rules this module enforces structurally, because they are the
mistakes that otherwise creep back in:

1. **No chart titles inside the figure.** Titles are Streamlit headings above
   the plot. A plotly title and a top legend fight for the same band and end up
   overlapping; moving the title out of the figure removes the collision class
   entirely and gives the page one typographic hierarchy.
2. **No dual axes.** ``timeseries`` takes a single value axis. Two measures of
   different scale go into ``stacked_panels`` (small multiples sharing the x
   axis) instead, because the alignment of two y-scales is arbitrary and invents
   correlations that are not in the data.
3. **Colour is assigned by the job it does**: identity -> the fixed categorical
   order, magnitude -> one blue ramp light-to-dark, polarity -> blue/red with a
   grey midpoint. Ordered categories (sleep depth, heart-rate zones) get the
   ordinal ramp, never the categorical one.

The palettes are the data-viz reference instance, validated with the skill's
own checker against both surfaces this app actually renders on (light #fcfcfb,
Streamlit dark #0e1117): categorical slots 1-3 pass all-pairs CVD and
normal-vision floors in both modes, and the 4/5-step ordinal ramps pass
monotonicity, step gap, single hue and light-end contrast.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import i18n

LIGHT: dict[str, Any] = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink_secondary": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    # Categorical identity, in fixed order. Slot 4+ does not exist on purpose:
    # past three series a chart becomes small multiples or folds a tail into
    # "pozostałe".
    "series": ["#2a78d6", "#eb6834", "#1baf7a"],
    # Single-hue magnitude ramp, light -> dark.
    "sequential": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    # Ordered categories: start no lighter than step 250 so the light end still
    # separates from the surface.
    "ordinal": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
    # Polarity: warm/cool poles, neutral grey midpoint.
    "diverging": ["#0d366b", "#2a78d6", "#9ec5f4", "#f0efec", "#f3a3a2", "#e34948", "#8f2322"],
    "status": {
        "good": "#0ca30c",
        "warning": "#fab219",
        "serious": "#ec835a",
        "critical": "#d03b3b",
    },
}

DARK: dict[str, Any] = {
    "surface": "#1a1c20",
    "ink": "#ffffff",
    "ink_secondary": "#c3c2b7",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "series": ["#3987e5", "#d95926", "#199e70"],
    "sequential": ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
    "ordinal": ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
    "diverging": ["#cde2fb", "#6da7ec", "#3987e5", "#383835", "#e66767", "#d03b3b", "#8f2322"],
    "status": {
        "good": "#0ca30c",
        "warning": "#fab219",
        "serious": "#ec835a",
        "critical": "#d03b3b",
    },
}

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Stage and zone orders are meaningful, so they carry the ordinal ramp.
SLEEP_STAGE_ORDER = ["deep", "light", "rem", "awake"]


def sleep_stage_labels() -> dict[str, str]:
    return {
        "deep": i18n.tr(pl="głęboki", en="deep"),
        "light": i18n.tr(pl="lekki", en="light"),
        "rem": "REM",
        "awake": i18n.tr(pl="czuwanie", en="awake"),
    }


ZONE_ORDER = ["hr_z1", "hr_z2", "hr_z3", "hr_z4", "hr_z5"]


def sleep_stage_colors() -> dict[str, str]:
    """Depth reads as lightness: deep is the strongest step, REM the faintest
    sleep step, and waking is not on the sleep ramp at all (neutral grey).

    Steps are spread across the 7-step ramp rather than taken adjacently: four
    neighbouring blues were indistinguishable in thin stacked slices.
    """
    t = tokens()
    ramp = t["sequential"]
    return {"deep": ramp[6], "light": ramp[3], "rem": ramp[1], "awake": _alpha(t["muted"], 0.55)}


def intensity_colors() -> dict[str, str]:
    """Easy / middle / hard, the polarised-training reading of HR zones.

    Easy takes the calm series blue, hard the warm accent, and the grey middle
    is the "no man's land" the model is about -- three classes a reader can
    tell apart at a glance, where five ramp steps of blue could not be.
    """
    t = tokens()
    return {"easy": t["series"][0], "middle": _alpha(t["muted"], 0.55), "hard": t["series"][1]}


def mode() -> str:
    """Which theme the page is actually rendered in.

    A theme pinned in the config (``theme.base``, set by serve.py and
    .streamlit/config.toml) wins: Streamlit renders it whatever the system
    prefers, while ``st.context.theme`` can still report the browser's own
    preference -- trusting that put light widget CSS under dark white text.
    """
    try:
        base = st.get_option("theme.base")
        if base in ("light", "dark"):
            return base
    except Exception:  # noqa: BLE001
        pass
    try:
        value = st.context.theme.type  # Streamlit >= 1.46
        if value in ("light", "dark"):
            return value
    except Exception:  # noqa: BLE001 - older Streamlit or no context
        pass
    return "light"


def tokens() -> dict[str, Any]:
    return DARK if mode() == "dark" else LIGHT


def series_colors(count: int) -> list[str]:
    """Categorical colours in fixed order; a 4th series is a design error."""
    palette = tokens()["series"]
    if count > len(palette):
        raise ValueError(
            f"{count} serii kategorialnych: uzyj stacked_panels albo zwin ogon "
            f"do 'pozostale' (max {len(palette)})"
        )
    return palette[:count]


def ordinal_colors(count: int) -> list[str]:
    ramp = tokens()["ordinal"]
    if count <= len(ramp):
        return ramp[:count]
    step = (len(ramp) - 1) / (count - 1)
    return [ramp[round(i * step)] for i in range(count)]


def base_layout(legend: bool, height: int, hover: str = "x unified") -> dict[str, Any]:
    t = tokens()
    return dict(
        height=height,
        # Small base margins; the axes carry automargin, so tick labels and axis
        # titles push these out as far as they actually need. Fixing the margins
        # by hand is how axis labels end up clipped at some window widths.
        margin=dict(l=8, r=14, t=40 if legend else 12, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=t["ink_secondary"]),
        hovermode=hover,
        hoverlabel=dict(
            bgcolor=t["surface"],
            bordercolor=t["axis"],
            font=dict(family=FONT, size=12, color=t["ink"]),
        ),
        showlegend=legend,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.06,
            xanchor="left",
            x=0,
            title=None,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=12),
        ),
        colorway=t["series"],
        bargap=0.22,
    )


def style_axes(fig: go.Figure) -> go.Figure:
    """Recessive hairline grid; solid, never dashed."""
    t = tokens()
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        linecolor=t["axis"],
        tickfont=dict(color=t["muted"], size=11),
        title_font=dict(color=t["muted"], size=11),
        title_standoff=8,
        automargin=True,
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=t["grid"],
        gridwidth=1,
        zeroline=False,
        linecolor="rgba(0,0,0,0)",
        tickfont=dict(color=t["muted"], size=11),
        title_font=dict(color=t["muted"], size=11),
        title_standoff=8,
        automargin=True,
    )
    return fig


def _numeric(frame: pd.DataFrame, columns: Iterable[str]) -> tuple[pd.DataFrame, list[str]]:
    """Drop columns the watch never recorded; cast the rest to one dtype."""
    out = frame.copy()
    keep: list[str] = []
    for column in columns:
        if column not in out.columns:
            continue
        values = pd.to_numeric(out[column], errors="coerce")
        if values.notna().any():
            out[column] = values
            keep.append(column)
    return out, keep


def timeseries(
    frame: pd.DataFrame,
    x: str,
    series: Mapping[str, str],
    *,
    height: int = 300,
    y_title: str | None = None,
    emphasis: str | None = None,
    markers: bool = False,
    fill: bool = False,
    end_labels: bool = False,
    decimals: int = 0,
) -> go.Figure | None:
    """Lines on a single value axis. ``series`` maps label -> column.

    ``emphasis`` names the one label that stays saturated while the rest drop
    to the muted ink - the way to show one line against its context without
    spending a categorical slot on each.
    """
    data, columns = _numeric(frame, series.values())
    labels = [label for label, column in series.items() if column in columns]
    if not labels or data.empty:
        return None

    colors = series_colors(len(labels)) if emphasis is None else None
    t = tokens()
    fig = go.Figure()
    for index, label in enumerate(labels):
        column = series[label]
        if emphasis is None:
            color = colors[index]
            width = 2
        elif label == emphasis:
            color = t["series"][0]
            width = 2.4
        else:
            color = t["muted"]
            width = 1.4
        fig.add_scatter(
            x=data[x],
            y=data[column],
            name=label,
            mode="lines+markers" if markers else "lines",
            line=dict(width=width, color=color, shape="linear"),
            marker=dict(size=8, color=color, line=dict(width=2, color=t["surface"])),
            fill="tozeroy" if fill and len(labels) == 1 else None,
            fillcolor=_alpha(color, 0.12) if fill and len(labels) == 1 else None,
            connectgaps=False,
            hovertemplate="%{y}<extra>" + label + "</extra>",
        )
        if end_labels:
            line = data[[x, column]].dropna()
            if not line.empty:
                value = float(line[column].iloc[-1])
                text = f"{value:.{decimals}f}" if len(labels) == 1 else f"{label} {value:.{decimals}f}"
                _end_label(fig, line[x].iloc[-1], value, text, color)
    fig.update_layout(**base_layout(legend=len(labels) > 1, height=height))
    if end_labels:
        fig.update_layout(margin=dict(l=8, r=78, t=40 if len(labels) > 1 else 12, b=8))
    if y_title:
        fig.update_yaxes(title_text=y_title)
    return _dates(style_axes(fig), data[x])


def bars(
    frame: pd.DataFrame,
    x: str,
    y: str,
    *,
    height: int = 260,
    y_title: str | None = None,
    diverging: bool = False,
    label: str | None = None,
) -> go.Figure | None:
    """One measure as bars. ``diverging`` colours by sign (polarity, not rank)."""
    data, columns = _numeric(frame, [y])
    if not columns or data.empty:
        return None
    t = tokens()
    if diverging:
        colors = [
            t["diverging"][1] if value >= 0 else t["diverging"][-2]
            for value in data[y].fillna(0)
        ]
    else:
        colors = t["series"][0]
    fig = go.Figure(
        go.Bar(
            x=data[x],
            y=data[y],
            marker=dict(color=colors, line=dict(width=0)),
            name=label or y,
            hovertemplate="%{y}<extra>%{x}</extra>",
        )
    )
    fig.update_layout(**base_layout(legend=False, height=height))
    if y_title:
        fig.update_yaxes(title_text=y_title)
    return _dates(style_axes(fig), data[x])


def hbars(
    frame: pd.DataFrame,
    label: str,
    value: str,
    *,
    unit: str = "",
    decimals: int = 0,
    height: int | None = None,
) -> go.Figure | None:
    """A ranking: horizontal bars, names readable on the left, value at the tip.

    Vertical bars with category names make the reader tilt their head at
    rotated labels; a ranked list of places reads top to bottom.
    """
    data, keep = _numeric(frame, [value])
    if not keep:
        return None
    data = data.dropna(subset=[value]).sort_values(value)
    if data.empty:
        return None
    t = tokens()
    suffix = f" {unit}" if unit else ""
    text = [f"{v:.{decimals}f}{suffix}" for v in data[value]]
    fig = go.Figure(
        go.Bar(
            x=data[value], y=data[label].astype(str), orientation="h",
            marker=dict(color=t["series"][0], line=dict(width=0), cornerradius=3),
            text=text, textposition="outside", cliponaxis=False,
            textfont=dict(family=FONT, size=12, color=t["ink_secondary"]),
            hovertemplate="%{y}: %{x}" + suffix + "<extra></extra>",
            width=0.62,
        )
    )
    fig.update_layout(**base_layout(legend=False, height=height or 34 * len(data) + 30, hover="closest"))
    fig.update_layout(margin=dict(l=8, r=40, t=8, b=8))
    fig = style_axes(fig)
    # The labels at the bar tips carry the values; the x axis would repeat them.
    fig.update_xaxes(showticklabels=False, showgrid=False, showline=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, color=t["ink_secondary"]))
    return fig


def stacked(
    frame: pd.DataFrame,
    x: str,
    columns: Sequence[str],
    labels: Mapping[str, str] | None = None,
    *,
    height: int = 320,
    y_title: str | None = None,
    normalise: bool = False,
    reverse_ramp: bool = False,
    colors: Mapping[str, str] | None = None,
    area: bool | None = None,
) -> go.Figure | None:
    """Stacked bars for ordered parts of a whole, on the ordinal ramp.

    Segments are separated by a 2px surface gap rather than an outline, so the
    stack reads as parts of one bar instead of a set of bordered boxes.

    Past ~30 periods the bars turn into a barcode -- ninety slivers separated by
    gaps -- so ``area`` (auto by default) draws the same shares as stacked
    layers. ``colors`` maps column -> colour when the ramp is not the right one.
    """
    data, keep = _numeric(frame, columns)
    if not keep or data.empty:
        return None
    if normalise:
        total = data[keep].sum(axis=1).replace(0, pd.NA)
        for column in keep:
            data[column] = (100 * data[column] / total).round(1)
    ramp = ordinal_colors(len(keep))
    if reverse_ramp:
        # Sleep depth reads darkest-is-deepest; the plain ramp would put the
        # lightest step on deep sleep and invert the metaphor.
        ramp = list(reversed(ramp))
    if colors:
        ramp = [colors.get(column, color) for column, color in zip(keep, ramp)]
    if area is None:
        area = data[x].nunique() > 30
    t = tokens()
    fig = go.Figure()
    for color, column in zip(ramp, keep):
        name = (labels or {}).get(column, column)
        if area:
            fig.add_scatter(
                x=data[x], y=data[column], name=name, mode="lines", stackgroup="one",
                line=dict(width=0.6, color=t["surface"], shape="spline", smoothing=0.4),
                fillcolor=color,
                hovertemplate="%{y:.0f}<extra>" + name + "</extra>",
            )
        else:
            fig.add_bar(
                x=data[x],
                y=data[column],
                name=name,
                marker=dict(color=color, line=dict(width=2, color=t["surface"])),
                hovertemplate="%{y}<extra>" + name + "</extra>",
            )
    fig.update_layout(**base_layout(legend=True, height=height), barmode="stack",
                      legend_traceorder="normal")
    if y_title:
        fig.update_yaxes(title_text=y_title)
    if normalise:
        fig.update_yaxes(range=[0, 100])
    return _dates(style_axes(fig), data[x])


def scatter(
    frame: pd.DataFrame,
    x: str,
    y: str,
    *,
    color: str | None = None,
    color_kind: str = "sequential",
    size: str | None = None,
    hover: Sequence[str] = (),
    height: int = 380,
    x_title: str | None = None,
    y_title: str | None = None,
    reverse_y: bool = False,
    color_title: str | None = None,
    color_mid: float | None = None,
    pace_y: bool = False,
) -> go.Figure | None:
    """Points with an optional magnitude or polarity colour channel.

    Categorical colour is capped at three groups by the palette; anything past
    that folds into "pozostałe" rather than inventing a fourth hue.
    """
    needed = [c for c in (x, y) if c]
    # A date axis must stay a date axis: coercing it "to numeric" turned
    # timestamps into nanoseconds and labelled the axis 1.785x10^15.
    x_dates = x in frame.columns and pd.api.types.is_datetime64_any_dtype(frame[x])
    data, keep = _numeric(frame, ([y] if x_dates else needed) + ([size] if size else []))
    if x_dates:
        data[x] = frame[x]
        keep = [x] + keep
    if len(keep) < 2 or data.empty:
        return None
    data = data.dropna(subset=[x, y])
    if data.empty:
        return None

    t = tokens()
    fig = go.Figure()
    marker: dict[str, Any] = dict(
        size=9 if size is None else None,
        line=dict(width=2, color=t["surface"]),
    )
    if size and size in data.columns:
        values = pd.to_numeric(data[size], errors="coerce").fillna(0)
        span = float(values.max()) or 1.0
        marker["size"] = (9 + 16 * values / span).clip(lower=7)

    if color and color in frame.columns and color_kind == "categorical":
        groups = list(dict.fromkeys(frame[color].dropna()))
        if len(groups) > 3:
            top = groups[:2]
            other = i18n.tr(pl="pozostałe", en="other")
            data[color] = data[color].where(data[color].isin(top), other)
            groups = top + [other]
        for group, hue in zip(groups, series_colors(len(groups))):
            subset = data[data[color] == group]
            if subset.empty:
                continue
            fig.add_scatter(
                x=subset[x],
                y=subset[y],
                mode="markers",
                name=str(group),
                marker={**marker, "color": hue},
                customdata=subset[list(hover)] if hover else None,
                hovertemplate=_hover_template(x, y, hover, str(group)),
            )
        legend = True
    else:
        values = pd.to_numeric(data[color], errors="coerce") if color in data.columns else None
        # A colour channel that is mostly missing paints the chart grey and
        # stretches its scale across a handful of points: drop it instead.
        if values is not None and values.notna().mean() < 0.6:
            values = None
        if color and values is not None:
            # The two lightest sequential steps vanish into the surface as dots;
            # a magnitude ramp on markers starts at the third.
            ramp = t["diverging"] if color_kind == "diverging" else t["sequential"][2:]
            marker.update(
                color=values,
                colorscale=[[i / (len(ramp) - 1), c] for i, c in enumerate(ramp)],
                colorbar=dict(
                    title=dict(text=color_title or color, side="right", font=dict(size=11)),
                    thickness=10,
                    outlinewidth=0,
                    tickfont=dict(size=10, color=t["muted"]),
                ),
            )
            if color_kind == "diverging":
                extent = float(values.abs().max() or 1)
                mid = color_mid if color_mid is not None else 0.0
                marker.update(cmin=mid - extent, cmax=mid + extent, cmid=mid)
            else:
                # Robust limits so one outlier does not flatten the ramp.
                low, high = values.quantile(0.05), values.quantile(0.95)
                if pd.notna(low) and pd.notna(high) and high > low:
                    marker.update(cmin=float(low), cmax=float(high))
        else:
            marker["color"] = t["series"][0]
        fig.add_scatter(
            x=data[x],
            y=data[y],
            mode="markers",
            marker=marker,
            customdata=data[list(hover)] if hover else None,
            hovertemplate=_hover_template(x, y, hover, None),
            showlegend=False,
        )
        legend = False

    fig.update_layout(**base_layout(legend=legend, height=height, hover="closest"))
    fig.update_xaxes(title_text=x_title if x_title is not None else x)
    fig.update_yaxes(title_text=y_title or y, autorange="reversed" if reverse_y else True)
    fig = _dates(style_axes(fig), data[x])
    if pace_y:
        for trace in fig.data:
            trace.text = [pace_text(v) for v in trace.y]
            trace.hovertemplate = trace.hovertemplate.replace(f"{y}: %{{y}}", "tempo: %{text}/km")
        pace_axis(fig, data[y], reverse=reverse_y)
    return fig


def heatmap(
    grid: pd.DataFrame,
    *,
    kind: str = "sequential",
    height: int = 460,
    x_title: str | None = None,
    color_title: str | None = None,
    mid: float | None = None,
    text: pd.DataFrame | None = None,
) -> go.Figure | None:
    """Matrix of one measure. Sequential for magnitude, diverging for polarity."""
    if grid is None or grid.empty:
        return None
    t = tokens()
    ramp = t["diverging"] if kind == "diverging" else t["sequential"]
    colorscale = [[i / (len(ramp) - 1), c] for i, c in enumerate(ramp)]
    rows = list(grid.index)
    if rows and all(hasattr(i, "month") and hasattr(i, "day") for i in rows):
        # Date rows as "26 lip" text: plotly would otherwise parse them into its
        # own (English-only) date axis.
        rows = [i18n.day_month(i) for i in rows]
    trace = go.Heatmap(
        z=grid.values,
        x=list(grid.columns),
        y=[str(i) for i in rows],
        hoverongaps=False,
        colorscale=colorscale,
        zmid=mid if kind == "diverging" else None,
        colorbar=dict(
            title=dict(text=color_title or "", side="right", font=dict(size=11)),
            thickness=10,
            outlinewidth=0,
            tickfont=dict(size=10, color=t["muted"]),
        ),
        hovertemplate="%{y} · %{x}: %{z}<extra></extra>",
        xgap=1,
        ygap=1,
    )
    if text is not None:
        trace.update(text=text.values, texttemplate="%{text}", textfont=dict(size=10))
    fig = go.Figure(trace)
    fig.update_layout(**base_layout(legend=False, height=height, hover="closest"))
    if x_title:
        fig.update_xaxes(title_text=x_title)
    fig = style_axes(fig)
    fig.update_yaxes(showgrid=False, autorange="reversed", nticks=12)
    # Missing cells sit on a faint wash instead of punching white holes.
    fig.update_layout(plot_bgcolor=_alpha(t["muted"], 0.08))
    return fig


def stacked_panels(
    frame: pd.DataFrame,
    x: str,
    panels: Sequence[Mapping[str, Any]],
    *,
    height: int = 460,
) -> go.Figure | None:
    """Small multiples sharing one x axis -- the honest answer to two scales.

    Each panel is ``{"title": str, "series": {label: column}, "kind": "line"
    | "bar", "height": float}``. A legend entry is shown once per label, not
    once per panel -- six entries for "HRV, średnia 7 d, RHR, średnia 7 d..."
    was a legend that explained nothing.
    """
    usable = []
    for panel in panels:
        data, keep = _numeric(frame, panel["series"].values())
        # A panel needs a line, not a lone point: one weigh-in in 90 days draws
        # an empty-looking axis that only says "no data" in a roundabout way.
        keep = [column for column in keep if data[column].notna().sum() >= 3]
        labels = [label for label, column in panel["series"].items() if column in keep]
        if labels:
            usable.append((panel, labels))
    if not usable:
        return None

    weights = [panel.get("height", 1.0) for panel, _ in usable]
    total = sum(weights)
    fig = make_subplots(
        rows=len(usable),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.12,
        row_heights=[w / total for w in weights],
        subplot_titles=[panel.get("title", "") for panel, _ in usable],
    )

    t = tokens()
    shown: set[str] = set()
    for row, (panel, labels) in enumerate(usable, start=1):
        colors = series_colors(len(labels))
        for color, label in zip(colors, labels):
            legend_here = len(labels) > 1 and label not in shown
            shown.add(label)
            column = panel["series"][label]
            values = pd.to_numeric(frame[column], errors="coerce")
            # Rows come from a frame shared by every panel; a series sampled on
            # its own clock (night HR vs HRV) is NaN on everyone else's rows,
            # and without dropping those the line breaks into dashes.
            present = values.notna()
            xs, values = frame.loc[present, x], values[present]
            if panel.get("kind") == "bar":
                fig.add_bar(
                    x=xs,
                    y=values,
                    name=label,
                    marker=dict(color=_alpha(color, 0.55), line=dict(width=0)),
                    hovertemplate="%{y}<extra>" + label + "</extra>",
                    row=row,
                    col=1,
                    legendgroup=label,
                    showlegend=legend_here,
                )
            else:
                pace = bool(panel.get("pace"))
                fig.add_scatter(
                    x=xs,
                    y=values,
                    name=label,
                    mode="lines",
                    line=dict(width=2, color=color),
                    connectgaps=False,
                    text=[pace_text(v) for v in values] if pace else None,
                    hovertemplate=("%{text}/km" if pace else "%{y}") + "<extra>" + label + "</extra>",
                    row=row,
                    col=1,
                    legendgroup=label,
                    showlegend=legend_here,
                )

    legend = any(len(labels) > 1 for _, labels in usable)
    fig.update_layout(**base_layout(legend=legend, height=height))
    # Panels need room for their own titles on top of the legend band.
    fig.update_layout(margin=dict(l=8, r=14, t=64 if legend else 34, b=8), bargap=0.1)
    for annotation in fig.layout.annotations:
        annotation.update(
            text=f"<b>{annotation.text}</b>" if annotation.text else annotation.text,
            font=dict(size=12, color=t["ink_secondary"], family=FONT),
            x=0,
            xanchor="left",
        )
    fig = style_axes(fig)
    fig.update_yaxes(nticks=4)
    for row, (panel, labels) in enumerate(usable, start=1):
        if panel.get("pace"):
            values = pd.concat([pd.to_numeric(frame[panel["series"][l]], errors="coerce") for l in labels])
            pace_axis(fig, values, row=row, robust=True)
    return _dates(fig, frame[x])


def band(fig: go.Figure, low: float, high: float, *, row: int | None = None) -> go.Figure:
    """A shaded reference band (a target range), behind the marks."""
    t = tokens()
    kwargs = dict(y0=low, y1=high, fillcolor=_alpha(t["status"]["good"], 0.10), line_width=0)
    if row is not None:
        fig.add_hrect(row=row, col=1, **kwargs)
    else:
        fig.add_hrect(**kwargs)
    return fig


def _data_range(fig: go.Figure) -> tuple[float, float] | None:
    values: list[float] = []
    for trace in fig.data:
        y = getattr(trace, "y", None)
        if y is None:
            continue
        series = pd.to_numeric(pd.Series(list(y)), errors="coerce").dropna()
        if not series.empty:
            values.extend([float(series.min()), float(series.max())])
    if not values:
        return None
    return min(values), max(values)


def threshold(
    fig: go.Figure,
    value: float,
    *,
    label: str | None = None,
    status: str = "critical",
    row: int | None = None,
) -> go.Figure:
    """A dashed rule for a real threshold -- the one legitimate use of dashing.

    Skipped when the threshold sits far outside the data: drawing it would
    stretch the axis and squash every actual value into a corner.
    """
    span = _data_range(fig)
    if span is not None:
        low, high = span
        margin = max((high - low) * 0.35, 1e-6)
        if value > high + margin or value < low - margin:
            return fig
    t = tokens()
    kwargs = dict(
        y=value,
        line_dash="dash",
        line_width=1,
        line_color=_alpha(t["status"][status], 0.75),
        annotation_text=label,
        annotation_position="top left",
        annotation_font=dict(size=10, color=t["muted"]),
    )
    if row is not None:
        fig.add_hline(row=row, col=1, **kwargs)
    else:
        fig.add_hline(**kwargs)
    return fig


def periods(fig: go.Figure, spans: Sequence[tuple[Any, Any, str]], *, today: Any = None) -> go.Figure:
    """Shade consecutive periods of a time axis (``(start, end, label)``, in
    order) and label each at the top; optionally mark today.

    Periods are ordered (base -> build -> peak -> taper), so they take the
    ordinal ramp at low alpha: the data stays the foreground.
    """
    t = tokens()
    colors = ordinal_colors(max(len({label for *_, label in spans}), 1))
    shade = {}
    for start, end, label in spans:
        color = shade.setdefault(label, colors[len(shade) % len(colors)])
        fig.add_vrect(x0=start, x1=end, fillcolor=_alpha(color, 0.13), line_width=0, layer="below")
        fig.add_annotation(x=start, xanchor="left", xshift=4, y=1, yref="paper", yanchor="top",
                           text=label, showarrow=False, font=dict(family=FONT, size=11, color=t["muted"]))
    if today is not None:
        fig.add_vline(x=today, line_width=1.5, line_color=t["ink_secondary"])
        fig.add_annotation(x=today, xanchor="left", xshift=4, y=0, yref="paper", yanchor="bottom",
                           text=i18n.tr(pl="dziś", en="today"), showarrow=False,
                           font=dict(family=FONT, size=11, color=t["ink_secondary"]))
    return fig


def zero_lines(fig: go.Figure) -> go.Figure:
    """Quadrant guides for a z-score scatter."""
    t = tokens()
    for adder in (fig.add_hline, fig.add_vline):
        adder(0, line_width=1, line_color=t["axis"])
    return fig


def show(
    fig: go.Figure | None,
    *,
    table: pd.DataFrame | None = None,
    note: str | None = None,
    empty: str | None = None,
    key: str | None = None,
) -> None:
    """Render a figure with its table-view twin.

    Every chart ships a table: colour and position are never the only way to
    read a value.
    """
    if fig is None:
        st.caption(empty or i18n.tr(pl="Brak danych w tym zakresie.", en="No data in this range."))
        return
    st.plotly_chart(fig, width="stretch", key=key, config={"displayModeBar": False})
    if note:
        st.caption(note)
    if table is not None and not table.empty:
        with st.expander("dane"):
            st.dataframe(readable_paces(table), width="stretch", hide_index=True)


def _alpha(color: str, alpha: float) -> str:
    color = color.lstrip("#")
    r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def pace_text(minutes: Any) -> str | None:
    """Decimal minutes per km as ``m:ss``: 5.72 is 5:43, not "five seventy-two"."""
    if minutes is None or pd.isna(minutes):
        return None
    seconds = int(round(float(minutes) * 60))
    return f"{seconds // 60}:{seconds % 60:02d}"


def readable_paces(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    """Every pace column (decimal min/km, named *pace* or *tempo*) as ``m:ss``.

    Applied to every table a person reads -- widget tables, the data twin
    behind the table icon, SQL results -- so 4.36 never shows up where 4:22
    is meant. Text columns (already formatted) are left alone.
    """
    if frame is None or frame.empty:
        return frame
    out = frame
    for column in frame.columns:
        name = str(column).lower()
        if ("pace" in name or "tempo" in name) and pd.api.types.is_float_dtype(frame[column]):
            if out is frame:
                out = frame.copy()
            out[column] = frame[column].map(pace_text)
    return out


def pace_axis(
    fig: go.Figure,
    values: Any,
    *,
    row: int | None = None,
    reverse: bool = True,
    robust: bool = False,
) -> go.Figure:
    """``m:ss`` ticks on a pace (min/km) y axis, faster at the top.

    ``robust`` frames the 2nd-98th percentile, so a stop at the lights
    (20 min/km for three seconds) does not squash the run into one line.
    """
    data = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if data.empty:
        return fig
    low, high = (data.quantile(0.02), data.quantile(0.98)) if robust else (data.min(), data.max())
    low, high = float(low), float(high)
    if high - low < 0.1:  # at least 6 s of frame, centred on the data
        middle = (low + high) / 2
        low, high = middle - 0.05, middle + 0.05
    span = high - low
    # Down to 5 s: intervals run within a few seconds of each other, and a
    # 15 s grid left them between two ticks with no label on the axis.
    step = next(s for s in (5 / 60, 10 / 60, 0.25, 0.5, 1.0, 2.0, 5.0) if span / s <= 6)
    pad = max(span * 0.06, step * 0.25)
    bottom, top = low - pad, high + pad
    # At least two labelled ticks inside the frame: widen to the nearest ones.
    inside = math.floor(top / step + 1e-9) - math.ceil(bottom / step - 1e-9) + 1
    if inside < 2:
        bottom = min(bottom, math.floor(low / step + 1e-9) * step - pad)
        top = max(top, math.ceil(high / step - 1e-9) * step + pad)
    first = math.floor(bottom / step) * step
    ticks = [round(first + i * step, 6) for i in range(int((top - first) / step) + 2)]
    rng = [top, bottom] if reverse else [bottom, top]
    kwargs = dict(tickmode="array", tickvals=ticks, ticktext=[pace_text(t) for t in ticks],
                  range=rng, autorange=False)
    if row is not None:
        fig.update_yaxes(row=row, col=1, **kwargs)
    else:
        fig.update_yaxes(**kwargs)
    return fig


def _hover_template(x: str, y: str, hover: Sequence[str], name: str | None) -> str:
    parts = [f"{x}: %{{x}}", f"{y}: %{{y}}"]
    for index, field in enumerate(hover):
        parts.append(f"{field}: %{{customdata[{index}]}}")
    tail = f"<extra>{name}</extra>" if name else "<extra></extra>"
    return "<br>".join(parts) + tail


# ---------------------------------------------------------------- daily trends
#
# The idiom for one noisy daily measure: the days as faint dots, the 7-day
# mean as the one saturated line, the person's own normal range as a wash
# behind both, and the latest value written at the end of the line. The raw
# series drawn as a full-strength line is what made every chart look like a
# 2005 spreadsheet: ninety jagged segments shouting over the trend.

def local_dates(fig: go.Figure, values: pd.Series, *, row: int | None = None) -> go.Figure:
    """Tick labels on a date axis in the interface language (i18n.py); plotly
    only ships English months, and its own ticks ignore the language anyway.

    Ticks are chosen for the span: Mondays under ~7 weeks, month starts under
    ~8 months, every other month beyond. The year is written on the first tick
    and on every January, so it appears once, not under one random label.
    """
    days = pd.to_datetime(pd.Series(values), errors="coerce").dropna()
    if days.empty:
        return fig
    if days.max() - days.min() < pd.Timedelta(days=2):
        # One night or one session: the axis is a clock, not a calendar.
        kwargs = dict(tickformat="%H:%M", hoverformat="%H:%M")
        if row is not None:
            fig.update_xaxes(row=row, col=1, **kwargs)
        else:
            fig.update_xaxes(**kwargs)
        return fig
    first, last = days.min().normalize(), days.max().normalize()
    span = (last - first).days
    if span <= 50:
        ticks = pd.date_range(first, last, freq="W-MON")
        text = [i18n.day_month(d) for d in ticks]
    else:
        step = "MS" if span <= 240 else ("2MS" if span <= 550 else "3MS")
        ticks = pd.date_range(first + pd.offsets.MonthBegin(0), last, freq=step)
        text = []
        for index, d in enumerate(ticks):
            label = i18n.months()[d.month - 1]
            text.append(f"{label} {d.year}" if index == 0 or d.month == 1 else label)
    kwargs = dict(tickmode="array", tickvals=list(ticks), ticktext=text,
                  hoverformat=i18n.tr(pl="%d.%m.%Y", en="%b %d, %Y"))
    if row is not None:
        fig.update_xaxes(row=row, col=1, **kwargs)
    else:
        fig.update_xaxes(**kwargs)
    return fig


def _dates(fig: go.Figure, values: Any) -> go.Figure:
    """Localised date ticks when the x values are dates; anything else untouched."""
    series = pd.Series(values)
    if pd.api.types.is_datetime64_any_dtype(series):
        return local_dates(fig, series)
    return fig


def _end_label(fig: go.Figure, x: Any, y: float, text: str, color: str) -> None:
    t = tokens()
    fig.add_scatter(
        x=[x], y=[y], mode="markers",
        marker=dict(size=9, color=color, line=dict(width=2, color=t["surface"])),
        hoverinfo="skip", showlegend=False,
    )
    fig.add_annotation(
        x=x, y=y, text=f"<b>{text}</b>", showarrow=False, xanchor="left", xshift=9,
        font=dict(family=FONT, size=12, color=t["ink"]),
    )


def trend(
    frame: pd.DataFrame,
    x: str,
    series: Mapping[str, tuple[str, str]],
    *,
    band: tuple[str, str] | None = None,
    unit: str = "",
    decimals: int = 0,
    height: int = 210,
    smooth_label: str | None = None,
) -> go.Figure | None:
    """Daily dots + rolling-mean line (+ normal band) on one value axis.

    ``series`` maps label -> (raw column, smoothed column). One entry is the
    usual case; two share the axis when they share a unit (day vs sleep
    stress). The end of each smoothed line carries its value, so the reader
    does not have to trace it back to the axis.
    """
    columns = [c for pair in series.values() for c in pair] + (list(band) if band else [])
    data, keep = _numeric(frame, columns)
    labels = [label for label, (raw, smooth) in series.items() if smooth in keep or raw in keep]
    if not labels or data.empty:
        return None
    data = data.sort_values(x)
    t = tokens()
    smooth_label = smooth_label or i18n.tr(pl="średnia 7 d", en="7-day mean")
    fig = go.Figure()

    if band and all(c in keep for c in band):
        low, high = band
        edge = data[[x, low, high]].dropna()
        # Lower edge first, then the upper one filled down to it.
        fig.add_scatter(x=edge[x], y=edge[low], mode="lines", line=dict(width=0),
                        hoverinfo="skip", showlegend=False)
        fig.add_scatter(
            x=edge[x], y=edge[high], mode="lines", line=dict(width=0), fill="tonexty",
            fillcolor=_alpha(t["muted"], 0.16), name=i18n.tr(pl="norma", en="normal"),
            customdata=edge[[low]].to_numpy(),
            hovertemplate=f"%{{customdata[0]:.{decimals}f}}–%{{y:.{decimals}f}}<extra>norma</extra>",
            showlegend=False,
        )

    suffix = f" {unit}" if unit else ""
    for color, label in zip(series_colors(len(labels)), labels):
        raw, smooth = series[label]
        prefix = "" if len(labels) == 1 else f"{label}: "
        day = i18n.tr(pl="dzień", en="day")
        if raw in keep:
            fig.add_scatter(
                x=data[x], y=data[raw], mode="markers", name=f"{prefix}{day}",
                marker=dict(size=6, color=_alpha(color, 0.38), line=dict(width=0)),
                hovertemplate=f"%{{y:.{decimals}f}}{suffix}<extra>{prefix}{day}</extra>",
                showlegend=False,
            )
        if smooth in keep:
            line = data[[x, smooth]].dropna()
            fig.add_scatter(
                x=line[x], y=line[smooth], mode="lines", name=f"{prefix}{smooth_label}",
                line=dict(width=2.6, color=color, shape="spline", smoothing=0.6),
                hovertemplate=f"%{{y:.{decimals}f}}{suffix}<extra>{prefix}{smooth_label}</extra>",
                showlegend=False,
            )
            if not line.empty:
                value = float(line[smooth].iloc[-1])
                number = f"{value:,.{decimals}f}".replace(",", "\u2009")
                text = f"{number}{suffix}" if len(labels) == 1 else f"{label} {number}"
                _end_label(fig, line[x].iloc[-1], value, text, color)

    fig.update_layout(**base_layout(legend=False, height=height))
    # Room on the right for the end label.
    fig.update_layout(margin=dict(l=8, r=78, t=10, b=8))
    fig = style_axes(fig)
    fig.update_yaxes(nticks=4)
    return local_dates(fig, data[x])


def spark(
    frame: pd.DataFrame,
    x: str,
    column: str,
    *,
    smooth: str | None = None,
    band: tuple[str, str] | None = None,
    unit: str = "",
    decimals: int = 0,
    height: int = 74,
) -> go.Figure | None:
    """Card-sized ``trend``: no axes, no grid, the last value at the end.

    Only for the cards on the Dziś page, where a shape next to a number says
    "rising / flat / falling" faster than a second number would. Anything that
    has to be read off an axis belongs in a full-width ``trend``.
    """
    columns = [column] + ([smooth] if smooth else []) + (list(band) if band else [])
    data, keep = _numeric(frame, columns)
    if column not in keep or data[column].notna().sum() < 3:
        return None
    data = data.sort_values(x)
    t = tokens()
    color = series_colors(1)[0]
    fig = go.Figure()
    if band and all(c in keep for c in band):
        edge = data[[x, *band]].dropna()
        fig.add_scatter(x=edge[x], y=edge[band[0]], mode="lines", line=dict(width=0), hoverinfo="skip")
        fig.add_scatter(x=edge[x], y=edge[band[1]], mode="lines", line=dict(width=0), fill="tonexty",
                        fillcolor=_alpha(t["muted"], 0.16), hoverinfo="skip")
    suffix = f" {unit}" if unit else ""
    fig.add_scatter(
        x=data[x], y=data[column], mode="markers" if smooth in keep else "lines+markers",
        marker=dict(size=4, color=_alpha(color, 0.45)), line=dict(width=1.4, color=_alpha(color, 0.6)),
        hovertemplate=f"%{{x|%d.%m}}: %{{y:.{decimals}f}}{suffix}<extra></extra>",
    )
    line_col = smooth if smooth in keep else column
    line = data[[x, line_col]].dropna()
    if smooth in keep:
        fig.add_scatter(x=line[x], y=line[line_col], mode="lines", hoverinfo="skip",
                        line=dict(width=2.2, color=color, shape="spline", smoothing=0.6))
    fig.add_scatter(x=[line[x].iloc[-1]], y=[line[line_col].iloc[-1]], mode="markers", hoverinfo="skip",
                    marker=dict(size=7, color=color, line=dict(width=2, color=t["surface"])))
    fig.update_layout(**base_layout(legend=False, height=height, hover="closest"))
    fig.update_layout(margin=dict(l=2, r=2, t=4, b=2), showlegend=False)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def range_bars(
    frame: pd.DataFrame,
    x: str,
    low: str,
    high: str,
    *,
    unit: str = "",
    height: int = 220,
    clock: bool = False,
) -> go.Figure | None:
    """One floating bar per day from its minimum to its maximum.

    ``clock`` reads the values as hours on a continuous axis (25.5 = 01:30),
    labels them as times and runs the axis downwards, evening on top -- the
    way a sleep diary is drawn.

    The shape of a day (how far it charged, how far it drained) is the bar;
    three lines for max, min and wake drew the same information as three
    tangled zig-zags.
    """
    data, keep = _numeric(frame, [low, high])
    if len(keep) < 2:
        return None
    data = data.dropna(subset=[low, high]).sort_values(x)
    if data.empty:
        return None
    t = tokens()
    suffix = f" {unit}" if unit else ""
    if clock:
        clock_low = data[low].map(_clock_text)
        clock_high = data[high].map(_clock_text)
    fig = go.Figure(
        go.Bar(
            x=data[x], y=data[high] - data[low], base=data[low],
            marker=dict(color=_alpha(t["series"][0], 0.30), line=dict(width=0), cornerradius=3),
            customdata=(
                pd.DataFrame({"a": clock_low, "b": clock_high}).to_numpy()
                if clock else data[[low, high]].to_numpy()
            ),
            hovertemplate=(
                "%{customdata[0]} → %{customdata[1]}<extra></extra>" if clock
                else f"%{{customdata[0]:.0f}} → %{{customdata[1]:.0f}}{suffix}<extra></extra>"
            ),
            width=pd.Timedelta(hours=11).total_seconds() * 1000,
        )
    )
    # The latest day is the one being asked about.
    last = data.iloc[-1]
    fig.add_bar(
        x=[last[x]], y=[last[high] - last[low]], base=[last[low]],
        marker=dict(color=t["series"][0], line=dict(width=0), cornerradius=3),
        width=pd.Timedelta(hours=11).total_seconds() * 1000, hoverinfo="skip", showlegend=False,
    )
    # Written beside the bar, like the end label of a trend line.
    end_text = (
        f"{_clock_text(last[low])}–{_clock_text(last[high])}" if clock
        else f"{last[low]:.0f}–{last[high]:.0f}"
    )
    fig.add_annotation(
        x=last[x], y=float(last[high] + last[low]) / 2,
        text=f"<b>{end_text}</b>",
        showarrow=False, xanchor="left", xshift=10,
        font=dict(family=FONT, size=12, color=t["ink"]),
    )
    fig.update_layout(**base_layout(legend=False, height=height), barmode="overlay")
    fig.update_layout(margin=dict(l=8, r=96 if clock else 78, t=10, b=8))
    fig = style_axes(fig)
    fig.update_yaxes(nticks=5)
    if clock:
        top = float(data[low].quantile(0.02)) // 1
        bottom = float(data[high].quantile(0.98)) // 1 + 1
        hours = list(range(int(top), int(bottom) + 1))
        step = 2 if len(hours) > 8 else 1
        fig.update_yaxes(
            range=[bottom, top], tickmode="array",
            tickvals=hours[::step], ticktext=[_clock_text(h) for h in hours[::step]],
        )
    return local_dates(fig, data[x])


def _clock_text(hours: float) -> str:
    if hours is None or pd.isna(hours):
        return "—"
    minutes = int(round(float(hours) * 60)) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def trail(
    frame: pd.DataFrame,
    x: str,
    y: str,
    *,
    when: str = "day",
    recent: int = 7,
    corners: Mapping[str, str] | None = None,
    hover: Sequence[str] = (),
    x_title: str | None = None,
    y_title: str | None = None,
    height: int = 420,
) -> go.Figure | None:
    """A cloud of past days with the last ``recent`` days drawn as a path.

    The question a z-score quadrant answers is "where am I now and which way
    am I heading", so history is grey context and only the recent week is in
    colour, joined in order and ending on a labelled "dziś". ``corners`` maps
    "tl"/"tr"/"bl"/"br" to the name of that quadrant, written in the corner.
    """
    data, keep = _numeric(frame, [x, y])
    if len(keep) < 2:
        return None
    data = data.dropna(subset=[x, y]).sort_values(when)
    if data.empty:
        return None
    t = tokens()
    accent = t["series"][0]
    history, latest = data.iloc[:-recent], data.iloc[-recent:]
    extent = max(float(data[[x, y]].abs().max().max()), 1.0) * 1.12

    fig = go.Figure()
    for adder in (fig.add_hline, fig.add_vline):
        adder(0, line_width=1, line_color=t["axis"])
    fig.add_scatter(
        x=history[x], y=history[y], mode="markers", name=i18n.tr(pl="wcześniej", en="earlier"),
        marker=dict(size=8, color=_alpha(t["muted"], 0.35), line=dict(width=0)),
        customdata=history[[when, *hover]].to_numpy() if hover else history[[when]].to_numpy(),
        hovertemplate=_trail_hover(hover), showlegend=False,
    )
    fig.add_scatter(
        x=latest[x], y=latest[y], mode="lines+markers", name=i18n.tr(pl=f"ostatnie {recent} dni", en=f"last {recent} days"),
        line=dict(width=1.6, color=_alpha(accent, 0.55)),
        marker=dict(size=9, color=accent, line=dict(width=2, color=t["surface"])),
        customdata=latest[[when, *hover]].to_numpy() if hover else latest[[when]].to_numpy(),
        hovertemplate=_trail_hover(hover), showlegend=False,
    )
    today = latest.iloc[-1]
    fig.add_scatter(
        x=[today[x]], y=[today[y]], mode="markers",
        marker=dict(size=15, color=accent, line=dict(width=3, color=t["surface"])),
        hoverinfo="skip", showlegend=False,
    )
    fig.add_annotation(
        x=today[x], y=today[y], text=f"<b>{i18n.tr(pl='dziś', en='today')}</b>", showarrow=False, xanchor="left", xshift=12,
        font=dict(family=FONT, size=12, color=t["ink"]),
    )
    spots = {"tl": (0.01, 0.99, "left", "top"), "tr": (0.99, 0.99, "right", "top"),
             "bl": (0.01, 0.01, "left", "bottom"), "br": (0.99, 0.01, "right", "bottom")}
    for corner, name in (corners or {}).items():
        px, py, xa, ya = spots[corner]
        fig.add_annotation(
            x=px, y=py, xref="x domain", yref="y domain", text=name, showarrow=False,
            xanchor=xa, yanchor=ya, font=dict(family=FONT, size=12, color=t["muted"]),
        )
    fig.update_layout(**base_layout(legend=False, height=height, hover="closest"))
    fig = style_axes(fig)
    fig.update_xaxes(range=[-extent, extent], title_text=x_title, showgrid=True,
                     gridcolor=t["grid"], dtick=1)
    fig.update_yaxes(range=[-extent, extent], title_text=y_title, dtick=1)
    return fig


def _trail_hover(hover: Sequence[str]) -> str:
    parts = ["%{customdata[0]|%d.%m.%Y}", "HRV %{x:+.1f} σ · RHR %{y:+.1f} σ"]
    for index, field in enumerate(hover, start=1):
        parts.append(f"{field}: %{{customdata[{index}]}}")
    return "<br>".join(parts) + "<extra></extra>"


def key(items: Sequence[tuple[str, str]]) -> None:
    """One shared legend for a group of small charts, written once above them.

    ``items`` are (kind, label) with kind in dot / line / band / bar. The
    marks use the chart colours; the words stay in the text tokens.
    """
    t = tokens()
    accent = t["series"][0]
    glyphs = {
        "dot": f'<svg width="10" height="10"><circle cx="5" cy="5" r="3.2" fill="{_alpha(accent, 0.45)}"/></svg>',
        "line": f'<svg width="18" height="10"><path d="M1 5 H17" stroke="{accent}" stroke-width="2.6" stroke-linecap="round"/></svg>',
        "band": f'<svg width="16" height="10"><rect x="0" y="1" width="16" height="8" rx="2" fill="{_alpha(t["muted"], 0.3)}"/></svg>',
        "bar": f'<svg width="10" height="12"><rect x="2" y="0" width="6" height="12" rx="2" fill="{t["sequential"][2]}"/></svg>',
    }
    spans = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:18px">'
        f'{glyphs[kind]}<span>{label}</span></span>'
        for kind, label in items
    )
    st.markdown(
        f'<div style="font-size:0.8rem;color:{t["ink_secondary"]};margin:0.2rem 0 0.4rem 0">{spans}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------- maps


def _map_layout(
    fig: go.Figure,
    points: pd.DataFrame,
    height: int,
    zoom_pad: float = 0.12,
    uirevision: str | None = None,
    robust: bool = False,
) -> go.Figure:
    """Centre and zoom a map on its own track, with a neutral basemap.

    The basemap follows the theme (positron / dark matter): a light raster in a
    dark widget reads as a pasted-in screenshot. ``route_map`` picks the ramp to
    match, so the track keeps its contrast on either.
    """
    t = tokens()
    lat = pd.to_numeric(points["lat"], errors="coerce").dropna()
    lon = pd.to_numeric(points["lon"], errors="coerce").dropna()
    if lat.empty or lon.empty:
        return fig

    # Web Mercator: at zoom z the world is 256*2^z px wide, so the zoom that
    # makes a bounding box fill the viewport is log2(360 * px / (256 * span)).
    # Guessing a constant instead leaves the track as a dot in a sea of map.
    if robust:
        # Frame the bulk of the points, not their extremes: one trip abroad
        # otherwise zooms the whole map out to continental scale, where a
        # density radius of a few pixels renders nothing at all.
        lat_low, lat_high = lat.quantile(0.02), lat.quantile(0.98)
        lon_low, lon_high = lon.quantile(0.02), lon.quantile(0.98)
    else:
        lat_low, lat_high = lat.min(), lat.max()
        lon_low, lon_high = lon.min(), lon.max()

    lat_span = max(float(lat_high - lat_low), 1e-4)
    lon_span = max(float(lon_high - lon_low), 1e-4)
    viewport_width, viewport_height = 900.0, max(height, 240)
    import math

    # MapLibre (what plotly's map traces render with) uses 512px tiles, so the
    # world is 512*2^z wide -- the 256px figure from the slippy-map era is one
    # zoom level off and lands the track half outside the frame.
    tile = 512.0
    zoom_lon = math.log2(360 * viewport_width / (tile * lon_span * (1 + zoom_pad)))
    # Latitude degrees shrink with cos(lat) on the mercator grid.
    lat_scale = max(math.cos(math.radians(float(lat.mean()))), 0.1)
    zoom_lat = math.log2(
        360 * viewport_height * lat_scale / (tile * lat_span * (1 + zoom_pad))
    )
    fig.update_layout(
        map=dict(
            style="carto-darkmatter" if mode() == "dark" else "carto-positron",
            center=dict(
                lat=float((lat_low + lat_high) / 2), lon=float((lon_low + lon_high) / 2)
            ),
            zoom=max(8.0, min(16.0, min(zoom_lon, zoom_lat))),
            # Set on the subplot as well as the layout: the subplot property is
            # what actually guards the pan/zoom state, and inheriting it is one
            # plotly version away from surprising us.
            uirevision=uirevision,
        ),
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=t["ink_secondary"]),
        hoverlabel=dict(
            bgcolor=t["surface"],
            bordercolor=t["axis"],
            font=dict(family=FONT, size=12, color=t["ink"]),
        ),
        showlegend=False,
        # Plotly keeps the current pan/zoom while this token is unchanged, so
        # recolouring the track leaves the viewer where they were. The token
        # changes with the activity, which is when a reset is what you want.
        uirevision=uirevision,
    )
    return fig


def _pace_ticks(low: float, high: float) -> dict[str, Any]:
    span = max(high - low, 0.1)
    step = next(s for s in (0.25, 0.5, 1.0, 2.0) if span / s <= 5)
    first = -(-low // step) * step
    ticks = [first + i * step for i in range(int((high - first) / step) + 1)]
    return dict(tickmode="array", tickvals=ticks, ticktext=[pace_text(v) for v in ticks])


def route_map(
    points: pd.DataFrame,
    *,
    color: str | None = None,
    color_title: str | None = None,
    reverse_scale: bool = False,
    height: int = 520,
    uirevision: str | None = None,
    pace: bool = False,
    highlight: str | None = None,
) -> go.Figure | None:
    """One GPS track as a line whose colour carries the measure.

    ``pace`` writes the colour scale and the hover as ``m:ss`` per km.
    ``highlight`` (a boolean column, instead of ``color``) draws the run muted
    and the marked stretch in the series colour -- a segment being cut.

    A line, not a string of dots: a route is a continuous thing, and sampled
    markers break it into beads that drift apart as you zoom in. The colour
    runs along the line itself -- each segment takes the shade of the value at
    its start -- so the shape and the measure share one mark instead of two.
    """
    if points is None or points.empty or "lat" not in points.columns:
        return None
    track = points.dropna(subset=["lat", "lon"]).copy()
    if len(track) < 3:
        return None

    t = tokens()
    # The basemap follows the theme (see _map_layout). On the dark one the two
    # darkest ramp steps sink into the tiles, so the ramp starts at step 3.
    dark = mode() == "dark"
    m = dict(DARK, sequential=DARK["sequential"][2:]) if dark else LIGHT
    fig = go.Figure()
    # A single wide pass underneath keeps the route legible where it doubles
    # back on itself and where one segment is a different shade from the next.
    fig.add_trace(
        go.Scattermap(
            lat=track["lat"],
            lon=track["lon"],
            mode="lines",
            line=dict(width=7, color=_alpha(m["ink"], 0.14)),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    values = pd.to_numeric(track[color], errors="coerce") if color in track.columns else None
    distance = (
        pd.to_numeric(track.get("distance_km"), errors="coerce")
        if "distance_km" in track.columns
        else pd.Series(range(len(track)), index=track.index, dtype="float64")
    )

    if values is not None and values.notna().any():
        ramp = list(reversed(m["sequential"])) if reverse_scale else list(m["sequential"])
        # Clamp to robust quantiles: a few stopped-at-the-lights samples at
        # 20 min/km otherwise squash the whole run into one shade.
        low, high = values.quantile(0.05), values.quantile(0.95)
        if not (pd.notna(low) and pd.notna(high) and high > low):
            low, high = values.min(), values.max()
        low, high = float(low), float(high)
        span = high - low or 1.0

        lat = track["lat"].to_numpy()
        lon = track["lon"].to_numpy()
        filled = values.ffill().bfill().to_numpy()
        # One trace per shade, each holding its own segments: plotly colours a
        # line per trace, so a continuous gradient along one polyline is not on
        # the table. Seven shades read as a gradient and cost seven traces.
        steps = len(ramp)
        bins: list[tuple[list[float], list[float]]] = [([], []) for _ in range(steps)]
        for i in range(len(lat) - 1):
            share = (float(filled[i]) - low) / span
            index = min(steps - 1, max(0, int(share * steps)))
            lats, lons = bins[index]
            lats.extend((lat[i], lat[i + 1], None))
            lons.extend((lon[i], lon[i + 1], None))
        for index, (lats, lons) in enumerate(bins):
            if not lats:
                continue
            fig.add_trace(
                go.Scattermap(
                    lat=lats,
                    lon=lons,
                    mode="lines",
                    line=dict(width=4, color=ramp[index]),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
        # The colourbar needs a trace that carries a scale; this one is only
        # ever a legend -- its markers are invisible.
        fig.add_trace(
            go.Scattermap(
                lat=[float(lat[0])],
                lon=[float(lon[0])],
                mode="markers",
                marker=dict(
                    size=0.1,
                    opacity=0,
                    color=[low],
                    cmin=low,
                    cmax=high,
                    colorscale=[[i / (len(ramp) - 1), c] for i, c in enumerate(ramp)],
                    showscale=True,
                    colorbar=dict(
                        title=dict(text=color_title or color, side="right", font=dict(size=11)),
                        thickness=10,
                        outlinewidth=0,
                        tickfont=dict(size=10, color=t["muted"]),
                        **(_pace_ticks(low, high) if pace else {}),
                    ),
                ),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        if pace:
            hover = "%{customdata[0]:.2f} km<br>tempo: %{customdata[1]}/km<extra></extra>"
            custom = pd.DataFrame({"km": distance, "value": values.map(pace_text)}).to_numpy()
        else:
            hover = (
                "%{customdata[0]:.2f} km<br>"
                + (color_title or color)
                + ": %{customdata[1]:.1f}<extra></extra>"
            )
            custom = pd.DataFrame({"km": distance, "value": values}).to_numpy()
    else:
        marked = track[highlight].fillna(False).astype(bool) if highlight in track.columns else None
        fig.add_trace(
            go.Scattermap(
                lat=track["lat"],
                lon=track["lon"],
                mode="lines",
                line=dict(width=4, color=m["muted"] if marked is not None else m["series"][0]),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        if marked is not None and marked.any():
            # Gaps (None) between separate stretches, so they are not joined.
            stretch = track[["lat", "lon"]].astype(object).where(marked, None)
            fig.add_trace(
                go.Scattermap(
                    lat=stretch["lat"],
                    lon=stretch["lon"],
                    mode="lines",
                    line=dict(width=6, color=m["series"][0]),
                    hoverinfo="skip",
                    showlegend=False,
                    connectgaps=False,
                )
            )
        hover = "%{customdata[0]:.2f} km<extra></extra>"
        custom = distance.to_frame().to_numpy()

    # Hover lives on an invisible marker layer: the values stay readable point
    # by point without putting dots back on the map.
    fig.add_trace(
        go.Scattermap(
            lat=track["lat"],
            lon=track["lon"],
            mode="markers",
            marker=dict(size=12, opacity=0),
            customdata=custom,
            hovertemplate=hover,
            showlegend=False,
        )
    )

    # Start and finish, labelled rather than colour-coded. On a loop the two
    # markers land on top of each other, so the labels go to opposite corners.
    endpoints = (
        ("start", track.iloc[0], "top right"),
        (i18n.tr(pl="koniec", en="finish"), track.iloc[-1], "bottom left"),
    )
    for label, row, position in endpoints:
        fig.add_trace(
            go.Scattermap(
                lat=[row["lat"]],
                lon=[row["lon"]],
                mode="markers+text",
                marker=dict(size=12, color=m["ink"]),
                text=[label],
                textposition=position,
                textfont=dict(size=12, color=m["ink"]),
                hoverinfo="skip",
                showlegend=False,
            )
        )
    return _map_layout(fig, track, height, uirevision=uirevision)


def profile(
    track: pd.DataFrame,
    *,
    x: str = "distance_km",
    y: str = "elevation_m",
    height: int = 220,
    y_title: str | None = None,
) -> go.Figure | None:
    """Elevation (or any stream) against distance, as a filled profile."""
    data, keep = _numeric(track, [x, y])
    if len(keep) < 2 or data.empty:
        return None
    data = data.dropna(subset=[x, y])
    if data.empty:
        return None
    t = tokens()
    fig = go.Figure(
        go.Scatter(
            x=data[x],
            y=data[y],
            mode="lines",
            line=dict(width=2, color=t["series"][0]),
            fill="tozeroy",
            fillcolor=_alpha(t["series"][0], 0.14),
            hovertemplate="%{x:.2f} km · %{y:.0f}<extra></extra>",
        )
    )
    fig.update_layout(**base_layout(legend=False, height=height))
    fig.update_yaxes(title_text=y_title or i18n.tr(pl="m n.p.m.", en="m a.s.l."))
    fig.update_xaxes(title_text=i18n.tr(pl="dystans (km)", en="distance (km)"))
    fig = style_axes(fig)
    low = float(data[y].min())
    high = float(data[y].max())
    pad = max((high - low) * 0.15, 4)
    fig.update_yaxes(range=[low - pad, high + pad])
    return fig


def geo_cells(
    frame: pd.DataFrame,
    *,
    lat: str = "start_lat",
    lon: str = "start_lon",
    grid: float = 0.35,
) -> pd.Series:
    """Coarse grid key for a set of coordinates.

    A hundred runs from the same park are one place, not a hundred overlapping
    dots. The key is shared by :func:`geo_clusters` and by the caller, so a
    clicked marker resolves back to the activities inside it.
    """
    la = (pd.to_numeric(frame[lat], errors="coerce") / grid).round() * grid
    lo = (pd.to_numeric(frame[lon], errors="coerce") / grid).round() * grid
    return la.round(3).astype(str) + "," + lo.round(3).astype(str)


def geo_clusters(
    points: pd.DataFrame,
    *,
    lat: str = "start_lat",
    lon: str = "start_lon",
    label: str = "location",
    when: str = "start_local",
    grid: float = 0.35,
) -> pd.DataFrame:
    """One row per place: its centre, how many activities, how far, how recent."""
    if points is None or points.empty or lat not in points.columns:
        return pd.DataFrame()
    frame = points.dropna(subset=[lat, lon]).copy()
    if frame.empty:
        return pd.DataFrame()
    frame["cell"] = geo_cells(frame, lat=lat, lon=lon, grid=grid)
    aggregation: dict[str, Any] = {
        "count": (lat, "size"),
        "lat": (lat, "mean"),
        "lon": (lon, "mean"),
    }
    if "distance_km" in frame.columns:
        aggregation["km"] = ("distance_km", "sum")
    if label in frame.columns:
        aggregation["name"] = (
            label,
            lambda s: s.dropna().mode().iloc[0] if s.notna().any() else "—",
        )
    if when in frame.columns:
        aggregation["last"] = (when, "max")
    clusters = frame.groupby("cell").agg(**aggregation).reset_index()
    return clusters.sort_values("count", ascending=False).reset_index(drop=True)
