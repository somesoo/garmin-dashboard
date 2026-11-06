"""Shared shell for the dashboard pages: data access, chrome, small helpers.

Each page is a module under ``views/`` that calls into here for its tables and
the shared chrome (rail, time range, styles); the page layout itself is the
bento grid in ``bento.py``. Keeping the chrome in the rail is what lets the
canvas be all tiles: nothing has to reserve space for navigation or filters.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd
import streamlit as st

from core import config
from core import db
from ui import glossary
from core import i18n
from ui import routing
from core import sync
from core import tenant

# Plain ground, cards on top: black in dark mode, a flat neutral in light.
# Each mode: canvas, sidebar, widget, edge, inner highlight, resting shadow,
# raised shadow.
_SURFACES = {
    "light": ("#f2f3f5", "#f7f8fa", "#ffffff", "rgba(15,23,42,0.08)",
              "inset 0 1px 0 rgba(255,255,255,0.9)",
              "0 1px 2px rgba(15,23,42,0.05), 0 8px 24px -12px rgba(15,23,42,0.14)",
              "0 2px 4px rgba(15,23,42,0.06), 0 16px 32px -14px rgba(15,23,42,0.22)"),
    # Solid graphite cards on the black ground. No gradients, ever (AGENTS.md).
    "dark": ("#000000", "#0a0a0b", "#1a1c20",
             "rgba(255,255,255,0.11)",
             "inset 0 1px 0 rgba(255,255,255,0.10)",
             "0 1px 2px rgba(0,0,0,0.6), 0 10px 26px -14px rgba(0,0,0,0.9)",
             "0 2px 4px rgba(0,0,0,0.6), 0 18px 36px -14px rgba(0,0,0,0.95)"),
}

_STYLE = """
<style>
  /* ---- canvas ------------------------------------------------------------- */
  [data-testid="stApp"] {background: @CANVAS@;}
  [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stBottom"] > div {background: transparent;}
  [data-testid="stHeader"] {background: transparent;}
  [data-testid="stSidebar"] {background: @SIDEBAR@ !important; border-right: 1px solid @LINE@;}
  [data-testid="stSidebar"] > div {background: transparent;}
  .block-container {padding-top: 1.6rem; padding-bottom: 4rem; max-width: 1560px;}

  /* ---- widgets (bento.py): wgt_ = chart tile, kpi_ = number, pnl_ = form */
  /* No boxes (2026-11-02): a tile is its content under a hairline, the gap does the rest. */
  [class*="st-key-wgt_"], [class*="st-key-kpi_"], [class*="st-key-pnl_"] {
      background: transparent; border: 0 !important; border-top: 1px solid #1f2126 !important; border-radius: 0;
      box-shadow: none; padding: 0.9rem 0.1rem 0.8rem 0.1rem;
      transition: transform .25s cubic-bezier(.2,.75,.25,1), box-shadow .25s ease;
      animation: wgt-rise .55s cubic-bezier(.2,.75,.25,1) both;
      animation-delay: calc(var(--row-delay, 0ms) + var(--col-delay, 0ms));}
  [class*="st-key-wgt_"]:hover, [class*="st-key-kpi_"]:hover {transform: none; box-shadow: none;}
  /* Numbers need less air than charts. */
  [class*="st-key-kpi_"] {padding: 0.75rem 0.1rem 0.7rem 0.1rem;}

  /* Rows line up without fixed heights: columns of a widget row stretch to the
     tallest, and widgets grow to fill their column -- nothing is clipped and
     nothing scrolls inside. Forms (pnl_) keep their own height. */
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-wgt_"]),
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-kpi_"]) {
      align-items: stretch !important;}
  [data-testid="stColumn"]:has([class*="st-key-wgt_"]) > [data-testid="stVerticalBlock"],
  [data-testid="stColumn"]:has([class*="st-key-kpi_"]) > [data-testid="stVerticalBlock"] {height: 100%;}
  [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
      > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-wgt_"], > [class*="st-key-kpi_"]) {
      flex: 1 0 auto; display: flex; flex-direction: column;}
  /* Grow, never shrink: shrinking below the content is exactly the clipping
     this layout exists to avoid. */
  [class*="st-key-wgt_"], [class*="st-key-kpi_"] {flex: 1 0 auto;}

  /* ---- widget chrome ------------------------------------------------------ */
  [class*="st-key-wgthd_"] {min-height: 30px; flex-wrap: nowrap;}
  [class*="st-key-wgthd_"] [data-testid="stElementContainer"]:first-child {flex: 1 1 auto; min-width: 0;}
  [class*="st-key-wgthd_"] [data-testid="stMarkdownContainer"] > div,
  [class*="st-key-wgthd_"] [data-testid="stMarkdown"] {margin: 0 !important;}
  [class*="st-key-wgthd_"] button {padding: 0 0.25rem; min-height: 28px; opacity: .38; transition: opacity .2s;}
  [class*="st-key-wgt_"]:hover [class*="st-key-wgthd_"] button,
  [class*="st-key-pnl_"]:hover [class*="st-key-wgthd_"] button,
  [class*="st-key-wgthd_"] button:focus-visible {opacity: 1;}
  @media (hover: none) {[class*="st-key-wgthd_"] button {opacity: .8;}}
  .tile-title {font-size: 0.86rem; font-weight: 640; letter-spacing: -0.003em; line-height: 1.3;}
  .tile-caption {font-size: 0.78rem; opacity: 0.72; line-height: 1.4;}
  /* Pull the status line up to its title by moving the whole element box, not
     the text inside it: a negative margin on the text sticks out of its own
     container and past the widget's edge. */
  [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] .tile-caption) {margin-top: -0.65rem;}
  /* Streamlit gives every markdown block margin-bottom: -1rem (it expects a
     trailing <p>); with a bare <div> that collapses the block to ~1 px and the
     text spills out of the widget. Widget text gets its real height back. */
  [data-testid="stMarkdownContainer"]:has(> .tile-caption),
  [data-testid="stMarkdownContainer"]:has(> .tile-list),
  [data-testid="stMarkdownContainer"]:has(> .tile-title) {margin-bottom: 0 !important;}
  [class*="st-key-kpi_"] [data-testid="stMetricValue"] {font-size: 1.6rem;
      animation: wgt-num .6s cubic-bezier(.2,.75,.25,1) both;
      animation-delay: calc(var(--row-delay, 0ms) + var(--col-delay, 0ms) + 120ms);}
  [class*="st-key-wgt_"] [data-testid="stMetricValue"] {font-size: 1.3rem;}
  [class*="st-key-wgt_"] [data-testid="stPlotlyChart"] {margin-top: -0.35rem;}
  [class*="st-key-wgt_"] .maplibregl-map, [class*="st-key-wgt_"] .mapboxgl-map {border-radius: 8px; overflow: hidden;}
  .tile-list {margin: 0 !important; padding-left: 1.1rem !important;}
  .tile-list li {font-size: 0.82rem !important; line-height: 1.45 !important; margin-bottom: 0.2rem !important;}

  /* ---- motion --------------------------------------------------------------
     Widgets rise in row by row, column by column; charts wipe in left to right
     (the direction time runs), numbers settle last. Only on first paint of a
     page: Streamlit keeps the DOM across reruns, so a rerun does not replay. */
  @keyframes wgt-rise {from {opacity: 0; transform: translateY(12px) scale(.985);} to {opacity: 1; transform: none;}}
  @keyframes wgt-num {from {opacity: 0; transform: translateY(6px);} to {opacity: 1; transform: none;}}
  @keyframes wgt-wipe {from {clip-path: inset(0 100% 0 0);} to {clip-path: inset(0 0 0 0);}}
  /* Plotly draws later than the widget appears (its library loads after the
     page), so the wipe starts when the traces arrive, not on the row stagger. */
  [class*="st-key-wgt_"] .js-plotly-plot .cartesianlayer .overplot {
      animation: wgt-wipe .9s cubic-bezier(.45,.05,.25,1) .05s both;}
@DELAYS@
  @media (prefers-reduced-motion: reduce) {
      [class*="st-key-wgt_"], [class*="st-key-kpi_"], [class*="st-key-pnl_"],
      [class*="st-key-kpi_"] [data-testid="stMetricValue"],
      [class*="st-key-wgt_"] .js-plotly-plot .cartesianlayer .overplot {animation: none !important; transition: none;}
      [class*="st-key-wgt_"]:hover, [class*="st-key-kpi_"]:hover {transform: none;}}

  /* ---- type and the rest ---------------------------------------------------- */
  h1 {font-size: 1.55rem !important; font-weight: 650; letter-spacing: -0.015em;
      margin-bottom: 0.1rem !important;}
  h2 {font-size: 1.05rem !important; font-weight: 620; letter-spacing: -0.005em;
      margin: 2.4rem 0 0.15rem 0 !important;}
  h3 {font-size: 0.9rem !important; font-weight: 600; margin: 1.1rem 0 0 0 !important;}
  [data-testid="stMetricValue"] {font-size: 1.45rem; font-weight: 600;}
  [data-testid="stMetricLabel"] {opacity: 0.68; font-size: 0.78rem;}
  [data-testid="stCaptionContainer"] {max-width: 72ch; line-height: 1.55; opacity: 0.85;}
  [data-testid="stSidebarNav"] {padding-top: 0.5rem;}
  div[data-testid="stExpander"] details summary p {font-size: 0.8rem; opacity: 0.65;}
  div[data-testid="stExpander"] {border: none; border-top: 1px solid rgba(128,128,128,0.18);
      border-radius: 0;}
  /* The globe bleeds past the grid -- it is the one element that should feel
     bigger than the page. Flat ground behind it: no halo, no gradient. */
  .st-key-globe_stage {margin: 0 -3.5rem;}
  .st-key-globe_stage [data-testid="stPlotlyChart"] {margin: 0;}
  hr {margin: 2.2rem 0 0 0; opacity: 0.25;}

  /* ---- wayfinding (guide.py) ---------------------------------------------- */
  .page-eyebrow {font-size: 0.78rem; opacity: 0.6; letter-spacing: 0.01em; margin-bottom: -0.6rem;}
  [data-testid="stMarkdownContainer"]:has(> .page-eyebrow) {margin-bottom: 0 !important;}
  [class*="st-key-viewswitch_"] {margin: 0.2rem 0 -0.4rem 0;}
  .st-key-guide_next {margin-top: 2.6rem; padding-top: 1rem; border-top: 1px solid @LINE@; flex-wrap: wrap;}
  .guide-next-label {font-size: 0.78rem; opacity: 0.6; margin-right: 0.4rem;}
  [data-testid="stMarkdownContainer"]:has(> .guide-next-label) {margin-bottom: 0 !important;}

  /* ---- no sidebar: one centred column, chrome in the top line (story.py) ----
     Streamlit's own page list never shows anywhere: the drawer writes its own
     (drawer.py). The panel and the hamburger are hidden here and revealed by
     ``_DRAWER`` below, which ``page_style`` adds only for a visitor who gets the
     drawer -- so the hamburger exists exactly when there is a drawer behind it. */
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"],
  [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarResizeHandle"],
  [data-testid="stSidebarNav"] {display: none !important;}
  .block-container {max-width: 1320px !important; padding-top: 0.6rem !important; padding-left: 2.75rem !important;
      padding-right: 2.75rem !important; margin: 0 auto;}
  [data-testid="stHeader"] {height: 0; min-height: 0;}
  [data-testid="stToolbar"] {top: 0.3rem;}
  .st-key-topbar {padding: 0.35rem 0 0.2rem 0; margin-bottom: 0.4rem;}
  .st-key-topbar [data-testid="stPageLink"] a {padding: 0 !important; background: none !important; min-height: 0;}
  .st-key-topbar [data-testid="stPageLink"] p, .st-key-topbar [data-testid="stPopover"] button p {font-size: 0.86rem; color: #898781;}
  .st-key-topbar [data-testid="stPageLink"] a:hover p {color: #fff;}
  .tb-here {font-size: 0.86rem; color: #fff; font-weight: 640;}
  /* Page links are words: no menu icons in the top line or the loop. */
  .st-key-topbar [data-testid="stPageLink"] a > span:has([data-testid="stIconMaterial"]),
  .st-key-loop [data-testid="stPageLink"] a > span:has([data-testid="stIconMaterial"]),
  .st-key-topbar [data-testid="stPageLink"] [data-testid="stIconMaterial"],
  .st-key-loop [data-testid="stPageLink"] [data-testid="stIconMaterial"] {display: none !important;}
  .view-title {font-size: 0.78rem; letter-spacing: 0.12em; text-transform: uppercase; color: #5f6570; font-weight: 650;
      margin: 1.2rem 0 0.2rem 0;}
  [data-testid="stMarkdownContainer"]:has(> .view-title) {margin-bottom: 0 !important;}
  [data-testid="stAppDeployButton"] {display: none;}
  .tb-note {font-size: 0.8rem; color: #5f6570;}
  /* Sign-in (auth._refused): one flat, centred card -- the app icon's ring, a title, one button. */
  .st-key-signin_card {margin-top: 14vh; text-align: center; gap: 0.9rem;}
  .signin-mark {width: 54px; height: 54px; margin: 0 auto 0.4rem; border-radius: 50%;
                border: 9px solid #3987e5; box-sizing: border-box; position: relative;}
  .signin-mark::after {content: ""; position: absolute; inset: 13px; border-radius: 50%; background: #fafafa;}
  .signin-title {font-size: 1.9rem !important; font-weight: 680 !important; margin: 0 !important; padding: 0 !important;}
  .signin-sub {color: #9aa0a6; margin: 0.2rem 0 0.6rem; font-size: 0.98rem;}
  .signin-note {color: #8a9099; font-size: 0.82rem; line-height: 1.45; margin-top: 0.4rem;}

  /* ---- the headline and the loop next to it ------------------------------- */
  .story-h {font-size: 2.15rem !important; line-height: 1.12 !important; letter-spacing: -0.03em; font-weight: 700 !important;
      margin: 0.1rem 0 0.4rem 0 !important; padding: 0 !important; max-width: 24ch;}
  .story-h em {font-style: normal; color: #9ec5f4;}
  .story-sub {color: #898781; font-size: 0.92rem; max-width: 68ch; margin: 0;}
  .st-key-loop {position: relative; padding-left: 1.1rem; gap: 0 !important;}
  .st-key-loop::before {content: ""; position: absolute; left: 0.27rem; top: 0.7rem; bottom: 1.6rem; width: 1px; background: #2c2f36;}
  .lp {position: relative; display: flex; gap: 0.5rem; align-items: baseline; font-size: 0.86rem; color: #898781; margin-top: 0.35rem;}
  .lp::before {content: ""; position: absolute; left: -1.1rem; top: 0.38rem; width: 9px; height: 9px; border-radius: 50%;
      background: #000; border: 1.5px solid #4a4f59;}
  .lp.on::before {background: #3987e5; border-color: #3987e5; box-shadow: 0 0 0 3px rgba(57,135,229,.22);}
  .lp-i {font-size: 0.7rem; color: #5f6570; font-weight: 700;}
  .lp-n {flex: 1;} .lp.on .lp-n {color: #fff; font-weight: 640;}
  .lp-v {color: #c3c2b7; font-weight: 640; font-variant-numeric: tabular-nums;} .lp.on .lp-v {color: #fff;}
  [class*="st-key-lp_pages_"] {gap: 0.15rem 0.8rem !important; margin-top: -0.2rem;}
  [class*="st-key-lp_pages_"] [data-testid="stPageLink"] a {padding: 0 !important; background: none !important; min-height: 0;}
  [class*="st-key-lp_pages_"] [data-testid="stPageLink"] p {font-size: 0.76rem; color: #5f6570;}
  [class*="st-key-lp_pages_"] [data-testid="stPageLink"] a:hover p {color: #fff;}
  .lp-here {font-size: 0.76rem; color: #9ec5f4;}
  .lp-again {font-size: 0.7rem; color: #5f6570; margin-top: 0.3rem;}
  [data-testid="stMarkdownContainer"]:has(> .lp), [data-testid="stMarkdownContainer"]:has(> .lp-again),
  [data-testid="stMarkdownContainer"]:has(> .lp-here), [data-testid="stMarkdownContainer"]:has(> .tb-here),
  [data-testid="stMarkdownContainer"]:has(> .tb-note), [data-testid="stMarkdownContainer"]:has(> .story-more-note),
  [data-testid="stMarkdownContainer"]:has(> .story-h) {margin-bottom: 0 !important;}

  /* ---- buttons, variant C: no boxes. A thick blue rule under the main action, a dotted one under the rest. */
  [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-tertiary"],
  [data-testid="stPopoverButton"], [data-testid="stBaseButton-borderlessIcon"],
  [data-testid="stDownloadButton"] button, [data-testid="stFormSubmitButton"] button {
      background: none !important; border: 0 !important; border-radius: 0 !important; box-shadow: none !important;
      padding: 0 0 3px 0 !important; min-height: 0 !important; color: #c3c2b7 !important;
      border-bottom: 2px dotted #4a4f59 !important; transition: border-color .15s, color .15s;}
  [data-testid="stBaseButton-secondary"] p, [data-testid="stBaseButton-primary"] p, [data-testid="stPopoverButton"] p {font-weight: 620;}
  [data-testid="stBaseButton-secondary"]:hover, [data-testid="stBaseButton-tertiary"]:hover, [data-testid="stPopoverButton"]:hover,
  [data-testid="stDownloadButton"] button:hover, [data-testid="stFormSubmitButton"] button:hover {
      color: #fff !important; border-bottom-color: #9ec5f4 !important;}
  [data-testid="stBaseButton-primary"] {color: #fff !important; border-bottom: 3px solid #3987e5 !important;}
  [data-testid="stBaseButton-primary"]:hover {border-bottom-color: #9ec5f4 !important;}
  /* Icons in a tile's header stay icons: no rule under a "?" */
  [class*="st-key-wgthd_"] button, [data-testid="stPopoverButton"]:has(> div > [data-testid="stIconMaterial"]:only-child) {
      border-bottom: 0 !important; padding: 0 0.25rem !important;}
  /* Choices (range, language, view switch): words, the chosen one underlined in blue. */
  [data-testid="stButtonGroup"] button {background: none !important; border: 0 !important; box-shadow: none !important;
      border-radius: 0 !important; padding: 0 0.1rem 3px 0.1rem !important; min-height: 0 !important; color: #5f6570 !important;
      border-bottom: 2px solid transparent !important;}
  [data-testid="stButtonGroup"] button:hover {color: #c3c2b7 !important;}
  [data-testid="stButtonGroup"] button[aria-checked="true"] {color: #fff !important; border-bottom-color: #3987e5 !important;}
  [data-testid="stButtonGroup"] > div {gap: 0.9rem !important;}
  [data-testid="stButtonGroup"] p {font-size: 0.84rem;}

  /* ---- details: a layer over the page, the old tiles in it without boxes ---- */
  [data-testid="stDialog"] {background: rgba(0,0,0,0.94) !important;}
  [data-testid="stDialog"] > div {background: #000 !important; box-shadow: none !important; border: 0 !important;}
  [data-testid="stDialog"] div[role="dialog"] {width: min(1320px, 96vw) !important; max-width: none !important;
      background: #000 !important; border: 0 !important; box-shadow: none !important; border-radius: 0 !important;}
  [data-testid="stDialog"] [class*="st-key-wgt_"], [data-testid="stDialog"] [class*="st-key-kpi_"],
  [data-testid="stDialog"] [class*="st-key-pnl_"] {background: transparent !important; border: 0 !important;
      border-top: 1px solid #1f2126 !important; border-radius: 0 !important; box-shadow: none !important;
      padding-left: 0; padding-right: 0; animation: none;}
  [data-testid="stDialog"] [class*="st-key-wgt_"]:hover, [data-testid="stDialog"] [class*="st-key-kpi_"]:hover {transform: none;}
  [class*="st-key-story_more_"] {margin-top: 0.4rem; padding-top: 0.6rem; border-top: 1px solid #16181b; gap: 0.8rem !important;}
  .story-more-note {font-size: 0.8rem; color: #5f6570;}

  /* ---- "Dalej": words with an arrow, no boxes ------------------------------ */
  .st-key-guide_next {margin-top: 0.8rem !important; padding-top: 0.6rem !important; border-top: 0 !important; gap: 1.6rem !important;}
  /* ---- narrow screens: the phone layout -----------------------------------
     Streamlit columns do not wrap by themselves. A bento row of four stays
     four at 360 px -- 68 px a tile, which is what "it goes to pieces on the
     phone" actually is. Here every row of columns wraps and a column takes the
     whole width; a KPI strip is the exception and goes two by two, because four
     full-width numbers are a screen of scrolling for four numbers. The house
     rule "KPIs always four" is about the strip having four tiles, not about
     them standing in one line.

     The switch is the viewport, not the device, so a narrow desktop window gets
     the same layout -- that is how this is checked without a phone in hand.
     *What* a phone is shown instead is a separate question, decided in Python
     (``shell.phone``, ``story.second``): CSS can only move things, and the
     point on a phone is to render less, not to hide more. */
  /* ---- tables (ui/tables.py): rows on the ground, not a grid in a box ---- */
  [data-testid="stHtml"]:has(> .gt-wrap) {margin-bottom: 0.4rem;}
  .gt-wrap {overflow-x: auto; overscroll-behavior-x: contain;}
  .gt {border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; font-size: 0.92rem;}
  .gt th {font-size: 0.68rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: #6b707a;
      text-align: left; padding: 0.35rem 0.6rem 0.45rem; border-bottom: 1px solid #2c2f36; white-space: nowrap;}
  .gt td {padding: 0.45rem 0.6rem; border-bottom: 1px solid #1f2126; white-space: nowrap; color: #d5d7dc;}
  .gt th:first-child, .gt td:first-child {padding-left: 2px; position: sticky; left: 0; background: @CANVAS@;}
  .gt td:first-child {color: #fafafa;}
  .gt .n {text-align: right;}
  .gt th[title] {cursor: help; text-decoration: underline dotted #4a4f59; text-underline-offset: 3px;}
  [data-testid="stPopoverBody"] .gt th:first-child, [data-testid="stPopoverBody"] .gt td:first-child,
  [data-testid="stExpander"] .gt th:first-child, [data-testid="stExpander"] .gt td:first-child {background: #1a1c20;}

  /* ---- tabs: one question each, swiped on a phone (ui/gesture.py) ------- */
  [data-testid="stTabs"] [role="tablist"] {gap: 1.4rem; border-bottom: 1px solid #1f2126;
      overflow-x: auto; scrollbar-width: none; scroll-margin-top: 3.5rem;}
  [data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar {display: none;}
  [data-testid="stTabs"] [role="tab"] {padding: 0.55rem 0 0.6rem; min-height: 44px; flex: 0 0 auto;}
  [data-testid="stTabs"] [role="tab"] p {font-size: 0.98rem; font-weight: 600; color: #6b707a;}
  [data-testid="stTabs"] [role="tab"][aria-selected="true"] p {color: #fafafa;}
  [data-testid="stTabs"] [role="tabpanel"]:not([hidden]) {animation: tab-in .22s ease-out both;}
  [data-testid="stTabs"][data-swipe="left"] [role="tabpanel"]:not([hidden]) {animation-name: tab-from-right;}
  [data-testid="stTabs"][data-swipe="right"] [role="tabpanel"]:not([hidden]) {animation-name: tab-from-left;}
  @keyframes tab-in {from {opacity: 0;} to {opacity: 1;}}
  @keyframes tab-from-right {from {opacity: 0; transform: translateX(24px);} to {opacity: 1; transform: none;}}
  @keyframes tab-from-left {from {opacity: 0; transform: translateX(-24px);} to {opacity: 1; transform: none;}}
  @media (prefers-reduced-motion: reduce) {[data-testid="stTabs"] [role="tabpanel"] {animation: none !important;}}

  /* ---- charts sleep until tapped (ui/gesture.py): a finger that scrolls the
     page over a chart must not zoom it or pin a tooltip. Touch screens hand
     the whole plot back to the page; a click arms one chart. */
  @media (hover: none) {
    [data-testid="stPlotlyChart"]:not(.armed) .js-plotly-plot,
    [data-testid="stPlotlyChart"]:not(.armed) .maplibregl-map {pointer-events: none !important;}
  }
  [data-testid="stPlotlyChart"] {border-radius: 8px; transition: box-shadow .15s; position: relative;}
  [data-testid="stPlotlyChart"][data-hint]::after {content: attr(data-hint); position: absolute; top: 6px; right: 8px;
      z-index: 5; pointer-events: none; font-size: 0.72rem; color: #d5d7dc; background: #1a1c20;
      border: 1px solid #2c2f36; border-radius: 6px; padding: 0.15rem 0.5rem;}
  [data-testid="stPlotlyChart"].armed[data-hint]::after {border-color: #3987e5; color: #fafafa;}
  [data-testid="stPlotlyChart"].armed {box-shadow: 0 0 0 1px #3987e5;}

  @media (max-width: 760px) {
    .gt {font-size: 0.86rem;}
    .gt th, .gt td {padding-left: 0.4rem; padding-right: 0.4rem;}
    .block-container {max-width: none !important;
        padding: 0.2rem 0.95rem 2.4rem 0.95rem !important;}
    /* Rows of columns only: a horizontal container (the tile header, the top
       line) holds elements, not stColumn, and must keep standing in a line. */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) {flex-wrap: wrap !important;}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) > [data-testid="stColumn"] {
        flex: 1 1 100% !important; width: 100% !important; min-width: 0 !important;}
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-kpi_"])
        > [data-testid="stColumn"] {flex: 1 1 38% !important; width: auto !important;}
    /* Stacked, the column stagger would run down the page twice (once per row,
       once per column) and the last tile would wait 0.6 s. One axis is enough. */
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {--col-delay: 0ms;}

    h1 {font-size: 1.35rem !important;}
    h2 {font-size: 1rem !important; margin-top: 1.5rem !important;}
    .story-h {font-size: 1.5rem !important; line-height: 1.16 !important; max-width: none;}
    .story-sub {max-width: none;}
    [class*="st-key-kpi_"] [data-testid="stMetricValue"] {font-size: 1.3rem;}
    [class*="st-key-wgt_"], [class*="st-key-kpi_"], [class*="st-key-pnl_"] {padding-left: 0; padding-right: 0;}

    .st-key-topbar {flex-wrap: wrap !important; gap: 0.1rem 0.9rem !important;}
    /* "stretch" in a wrapping line would push the right-hand half onto a row of
       its own; on a phone the top line is words that flow. */
    .st-key-topbar [data-testid="stSpacer"] {display: none !important;}
    [data-testid="stButtonGroup"] > div {gap: 0.7rem !important;}
    .st-key-guide_next {gap: 0.9rem !important;}

    /* The globe still bleeds past the text, by the page padding, not by 3.5rem. */
    .st-key-globe_stage {margin: 0 -0.95rem;}
    /* Details are the whole screen: a dialog inset on a phone is a letterbox. */
    [data-testid="stDialog"] div[role="dialog"] {width: 100vw !important; max-height: 100vh !important;
        border-radius: 0 !important;}
  }

  /* ---- the top line on a phone: the page's title next to the hamburger ----- */
  .tb-page {font-size: 0.86rem; color: #fff; font-weight: 640;}
  [data-testid="stMarkdownContainer"]:has(> .tb-page) {margin-bottom: 0 !important;}
</style>
"""

# Added by ``page_style`` only when the visitor gets the drawer (drawer.py).
# Everything here either undoes the blanket hide above or styles the panel, so a
# wide window never carries it -- and ``?layout=phone`` on a desktop does,
# which is how the drawer is reviewed without a phone in hand.
_DRAWER = """
<style>
  [data-testid="stSidebar"], [data-testid="stSidebarCollapseButton"],
  [data-testid="stExpandSidebarButton"] {display: flex !important;}
  /* A page whose head is a control (guide.OWN_TOP: the run picker) puts it in
     the hamburger's line, between the hamburger and Streamlit's menu. */
  .st-key-run_top {margin-top: -2.6rem; padding: 0 0 0 2.6rem; position: relative; z-index: 1000000;
      pointer-events: none;}
  /* Streamlit's "⋮" menu: hidden on a phone; "Reload" is at the foot of the drawer. */
  /* Only the menu: the toolbar itself also holds the hamburger. */
  [data-testid="stMainMenu"], [data-testid="stToolbarActions"] {display: none !important;}
  /* The padding lies over the hamburger and the menu: only the card itself takes a tap. */
  .st-key-run_top iframe {pointer-events: auto;}
  /* Room for the hamburger: the header is 0 high everywhere else, being empty. */
  [data-testid="stHeader"] {height: 2.7rem !important; min-height: 2.7rem !important;}
  /* Streamlit's control for a shut sidebar is a double chevron; the ligature
     "menu" in its place is the hamburger a thumb goes looking for. */
  [data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {font-size: 0 !important;}
  [data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"]::after {
      content: "menu"; font-family: "Material Symbols Rounded"; font-size: 1.7rem; color: #c3c2b7;}
  [data-testid="stSidebar"] {width: min(84vw, 320px) !important; min-width: 0 !important; background: #000 !important;}
  [data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"] {background: #000 !important;}
  .st-key-drawer {gap: 0 !important;}
  .dw-who {font-weight: 650; font-size: 1.02rem;}
  .dw-note {font-size: 0.72rem; color: #5f6570; margin-top: 0.1rem;}
  .dw-h {font-size: 0.68rem; letter-spacing: 0.12em; text-transform: uppercase; color: #5f6570; font-weight: 700;
      margin: 1.5rem 0 0.3rem 0;}
  /* A stage of the loop: its number, what it is about, its number of the day. */
  .dw-s {display: flex; gap: 0.5rem; align-items: baseline; font-size: 0.8rem; color: #898781; margin: 1rem 0 0.1rem 0;}
  .dw-s.on .dw-n {color: #fff; font-weight: 640;}
  .dw-i {font-size: 0.66rem; color: #4a4f59; font-weight: 700;}
  .dw-n {flex: 1;}
  .dw-v {color: #c3c2b7; font-weight: 640; font-variant-numeric: tabular-nums;}
  /* A page is a word on a line of its own, with a thumb's worth of room on it. */
  .dw-here {font-size: 0.95rem; color: #9ec5f4; padding: 0.55rem 0; font-weight: 620;}
  .st-key-drawer [data-testid="stPageLink"] a {padding: 0.55rem 0 !important; background: none !important;
      min-height: 0;}
  .st-key-drawer [data-testid="stPageLink"] p {font-size: 0.95rem; color: #c3c2b7;}
  .st-key-drawer [data-testid="stPageLink"] a:hover p {color: #fff;}
  /* Page links are words here too (as in the top line and the loop): no icons. */
  .st-key-drawer [data-testid="stPageLink"] a > span:has([data-testid="stIconMaterial"]),
  .st-key-drawer [data-testid="stPageLink"] [data-testid="stIconMaterial"] {display: none !important;}
  .st-key-drawer [data-testid="stButtonGroup"] {margin: 0.1rem 0 0.7rem 0;}
  .st-key-drawer [data-testid="stButton"], .st-key-drawer .st-key-tb_pull {margin-top: 0.9rem;}
  [data-testid="stMarkdownContainer"]:has(> .dw-who), [data-testid="stMarkdownContainer"]:has(> .dw-note),
  [data-testid="stMarkdownContainer"]:has(> .dw-h), [data-testid="stMarkdownContainer"]:has(> .dw-s),
  [data-testid="stMarkdownContainer"]:has(> .dw-here) {margin-bottom: 0 !important;}
</style>
"""


def _delays() -> str:
    # Stagger as CSS variables: the page row sets --row-delay, the column inside
    # it adds --col-delay, and every widget below inherits both.
    rows = "\n".join(
        f'  [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > :nth-child({n})'
        f" {{--row-delay: {min(n, 12) * 55}ms;}}"
        for n in range(1, 25)
    )
    columns = "\n".join(
        f'  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child({n}) {{--col-delay: {n * 70}ms;}}'
        for n in range(1, 5)
    )
    return rows + "\n" + columns


def page_style(mode: str = "light") -> str:
    """The app's CSS for the theme the browser renders (``theme.mode()``).

    The arrangement is keyed on the viewport (the media query in ``_STYLE``).
    One block is keyed on the visitor instead: the drawer's (``_DRAWER``), because
    Streamlit's sidebar and its hamburger are chrome only CSS can reach, and they
    must appear exactly for the visitor whose page renders a drawer in them.
    """
    canvas, sidebar, widget, line, highlight, shadow, raised = _SURFACES.get(mode, _SURFACES["light"])
    tokens = {"@CANVAS@": canvas, "@SIDEBAR@": sidebar, "@WIDGET@": widget, "@LINE@": line,
              "@HIGHLIGHT@": highlight, "@SHADOW@": shadow, "@RAISED@": raised, "@DELAYS@": _delays()}
    style = _STYLE + (_DRAWER if phone() else "")
    for token, value in tokens.items():
        style = style.replace(token, value)
    return style


# ---------------------------------------------------------------- which layout

# Two layouts, not two apps. The *arrangement* is settled in CSS by the
# viewport (the media query above), so a narrow desktop window behaves like a
# phone and nothing has to be guessed. This decides the other half: *what gets
# rendered at all*. A phone screen holds roughly the headline, four numbers and
# one chart before the fold, and the whole page on a phone should be that -- the
# rest moved behind "Szczegóły" (``story.second``), not merely pushed down.
#
# Only the server can skip rendering, and the only thing the server knows about
# the screen is the request. ``st.context.headers`` is free (no component, no
# rerun, no second paint); a viewport width measured in the browser would arrive
# one rerun late and the first paint would still be the desktop page.
LAYOUTS = ("phone", "wide")
_LAYOUT_KEY = "layout_choice"
# Hand-held by name. Android tablets send "Android" without "Mobile", and an
# iPad reports itself as a Mac -- both are wide screens, and both are right to
# get the whole dashboard.
_HANDHELD = ("iphone", "ipod", "windows phone", "iemobile", "blackberry", "opera mini")


def phone_ua(agent: str) -> bool:
    """Is this user agent a phone? (Pure, so it is testable without a server.)"""
    ua = (agent or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return False
    if any(name in ua for name in _HANDHELD):
        return True
    return "android" in ua and "mobile" in ua


def _user_agent() -> str:
    try:
        return st.context.headers.get("User-Agent") or ""
    except Exception:  # no request in scope (a CLI, a test, a bare rerun)
        return ""


def layout() -> str:
    """``"phone"`` or ``"wide"`` -- which page this visitor gets.

    ``?layout=phone`` / ``?layout=wide`` wins and is remembered for the tab: the
    phone page can be opened on a desktop (how it is reviewed), and a phone can
    ask for the whole dashboard when that is what it came for.
    """
    try:
        asked = st.query_params.get("layout")
        if asked in LAYOUTS:
            st.session_state[_LAYOUT_KEY] = asked
        chosen = st.session_state.get(_LAYOUT_KEY)
    except Exception:
        chosen = None
    if chosen in LAYOUTS:
        return chosen
    return "phone" if phone_ua(_user_agent()) else "wide"


def phone() -> bool:
    """Shorthand for ``layout() == "phone"``."""
    return layout() == "phone"


# Activity tables: the warehouse field, its header in the interface language,
# and its format. Raw floats ("130.3395") and seconds on the start time are
# noise in a log you scan by eye.
def activity_labels() -> dict[str, str]:
    """Field -> table header; rename a frame with it, then pass activity_columns()."""
    tr = i18n.tr
    return {
        "start_local": tr(pl="kiedy", en="when"),
        "sport": "sport",
        "name": tr(pl="nazwa", en="name"),
        "location": tr(pl="miejsce", en="place"),
        "distance_km": "km",
        "duration_min": "min",
        "pace_min_km": tr(pl="tempo /km", en="pace /km"),
        "avg_hr": tr(pl="tętno", en="HR"),
        "max_hr": tr(pl="tętno max", en="max HR"),
        "training_load": "load",
        "te_aerobic": tr(pl="TE tlenowy", en="aerobic TE"),
        "te_anaerobic": tr(pl="TE beztlenowy", en="anaerobic TE"),
        "best_1k_s": tr(pl="najlepszy 1 km", en="best 1 km"),
        "best_5k_s": tr(pl="najlepszy 5 km", en="best 5 km"),
        "calories": "kcal",
        "elevation_gain_m": tr(pl="przewyższenie", en="elevation gain"),
    }


def activity_columns() -> dict[str, Any]:
    number = st.column_config.NumberColumn
    formats = {"distance_km": "%.1f", "duration_min": "%.0f", "avg_hr": "%.0f", "max_hr": "%.0f",
               "training_load": "%.0f", "te_aerobic": "%.1f", "te_anaerobic": "%.1f", "calories": "%.0f",
               "elevation_gain_m": "%.0f m"}
    labels = activity_labels()
    return {labels[field]: number(labels[field], format=fmt) for field, fmt in formats.items()}


# The value kept in the session is the key, not the label: switching the
# language must not reset the range.
WINDOWS = {"30d": 30, "90d": 90, "365d": 365, "all": None}


def _window_label(key: str) -> str:
    return {
        "30d": i18n.tr(pl="30 dni", en="30 days"),
        "90d": i18n.tr(pl="90 dni", en="90 days"),
        "365d": i18n.tr(pl="rok", en="year"),
        "all": i18n.tr(pl="wszystko", en="all"),
    }[key]


@st.cache_data(show_spinner=False, max_entries=64)
def _table(name: str, build: str) -> pd.DataFrame:
    return db.table(name)


@st.cache_data(show_spinner=False, max_entries=64)
def _sql(sql: str, build: str) -> pd.DataFrame:
    return db.query(sql)


@st.cache_data(show_spinner=False)
def _models(build: str) -> dict:
    path = config.tables() / "models.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def build_id() -> str:
    """The cache key of everything read from the warehouse: whose it is and when it was built.

    Every ``@st.cache_data`` takes this as an argument, and the cache is shared
    by all sessions of the process -- without the person in it, two people with
    a build from the same second (or none yet) would get each other's tables.
    """
    return f"{tenant.current().id}@{db.state().get('built_at', 'none')}"


def table(name: str) -> pd.DataFrame:
    """A warehouse table, cached until the ETL rebuilds it."""
    return _table(name, build_id())


def query(sql: str) -> pd.DataFrame:
    return _sql(sql, build_id())


def models() -> dict:
    return _models(build_id())


def state() -> dict[str, Any]:
    return db.state()


def has(*columns: str) -> bool:
    """Does the person's source record this at all (any day of the whole history)?

    Not the selected range: a tile whose data is just outside the range stays and
    says so; a tile the watch never fills (Body Battery on an Apple Watch) goes.
    """
    frame = table("daily")
    return any(c in frame.columns and frame[c].notna().any() for c in columns)


def daily() -> pd.DataFrame:
    frame = table("daily")
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"])
    return frame


def window_days() -> int | None:
    """The active time window, chosen once in the sidebar for every page."""
    return WINDOWS.get(st.session_state.get("range_choice", "90d"), 90)


def cutoff() -> pd.Timestamp | None:
    span = window_days()
    if span is None:
        return None
    frame = daily()
    if frame.empty:
        return None
    return frame["day"].max() - pd.Timedelta(days=span)


def clip(frame: pd.DataFrame, column: str = "day") -> pd.DataFrame:
    """Restrict a table to the active window."""
    edge = cutoff()
    if frame.empty or edge is None or column not in frame.columns:
        return frame
    out = frame.copy()
    out[column] = pd.to_datetime(out[column])
    return out[out[column] >= edge]


def range_picker() -> None:
    """The one global filter, in the top line (story.topbar)."""
    if st.session_state.get("range_choice") not in WINDOWS:
        st.session_state["range_choice"] = "90d"
    st.segmented_control(
        i18n.tr(pl="Zakres", en="Range"),
        list(WINDOWS),
        required=True,
        key="range_choice",
        format_func=_window_label,
        label_visibility="collapsed",
    )


def language_picker() -> None:
    """Interface language, remembered for the next tab (i18n.py)."""
    st.segmented_control(
        i18n.tr(pl="Język", en="Language"),
        list(i18n.LANGS),
        default=i18n.lang(),
        required=True,
        key=i18n.KEY,
        format_func=lambda code: code.upper(),
        on_change=lambda: i18n.remember(st.session_state.get(i18n.KEY)),
        label_visibility="collapsed",
    )


def pull_inline(was_busy: bool) -> None:
    """The Garmin pull in the top line: one link, the time of the last pull next to it (sync.py)."""
    busy = sync.running()
    if busy != was_busy:
        st.rerun()
    record = sync.last()
    tr = i18n.tr
    with st.container(horizontal=True, key="tb_pull", vertical_alignment="center", gap="small"):
        if busy:
            st.markdown(f"<span class='tb-note'>{tr(pl='Pobieranie z Garmina…', en='Pulling from Garmin…')} "
                        f"{tr(pl='od', en='since')} {_stamp(record.get('started_at'))}</span>",
                        unsafe_allow_html=True, width="content")
            return
        if st.button(tr(pl="Pobierz z Garmina", en="Pull from Garmin"), key="pull_garmin"):
            sync.start()
            st.rerun()
        if record.get("code") == 2:
            note = tr(pl="token wygasł — etl/login.py", en="token expired — etl/login.py")
        elif record and record.get("code") != 0:
            note = tr(pl="ostatnie pobranie nie powiodło się — data/fetch.log", en="the last pull failed — data/fetch.log")
        else:
            note = _stamp(record.get("finished_at"))
        st.markdown(f"<span class='tb-note'>{note}</span>", unsafe_allow_html=True, width="content")


def status_lines() -> str:
    """The warehouse in one line (the lab menu shows it)."""
    info = state()
    days, activities = (int(info.get(k, 0) or 0) for k in ("days", "activities"))
    return (f"{days} {i18n.plural(days, pl=('dzień', 'dni', 'dni'), en=('day', 'days'))} · {activities} "
            f"{i18n.plural(activities, pl=('aktywność', 'aktywności', 'aktywności'), en=('activity', 'activities'))} · "
            + i18n.tr(pl="zbudowano", en="built") + f" {_stamp(info.get('built_at'))}")


def _stamp(value: str | None) -> str:
    try:
        return f"{dt.datetime.fromisoformat(value):%d.%m %H:%M}"
    except (TypeError, ValueError):
        return "—"


def lead(title: str, note: str | None = None, *, terms: tuple | list = (), how: str | None = None) -> None:
    """Section heading plus the sentence that says why the section is there.

    ``terms`` are glossary keys and ``how`` says how to read the chart; both go
    into a "Co to jest?" popover, so the canvas carries one sentence and the
    explanation is one click away instead of a legend in prose.
    """
    st.markdown(f"## {title}")
    if note:
        st.caption(note)
    explain(terms, how)


def sub(title: str, note: str | None = None, *, terms: tuple | list = (), how: str | None = None) -> None:
    st.markdown(f"### {title}")
    if note:
        st.caption(note)
    explain(terms, how)


def explain(terms: tuple | list = (), how: str | None = None) -> None:
    """The help popover: what each number is, why it matters, how to read it."""
    if not terms and not how:
        return

    with st.popover(i18n.tr(pl="Co to jest?", en="What is this?"), icon=":material/help_outline:", type="tertiary"):
        for index, key in enumerate(terms):
            if index:
                st.divider()
            st.markdown(glossary.markdown(key))
        if how:
            if terms:
                st.divider()
            st.markdown(f"**{i18n.tr(pl='Jak czytać wykres', en='How to read the chart')}** — {how}")
        target = routing.page("slownik")
        if target is not None:
            st.page_link(target, label=i18n.tr(pl="Wszystkie pojęcia — Słownik", en="All terms — Glossary"),
                         icon=":material/menu_book:")


def metrics(row: pd.Series | None, previous: pd.Series | None, specs: list[tuple]) -> None:
    """A strip of tiles: ``(field, label, unit[, delta_color])``.

    ``delta_color`` is Streamlit's: "normal" when up is good, "inverse" when up
    is bad (resting HR, stress), "off" when the direction alone means nothing
    (fatigue, load ratios). Left to the default every rise turns green.
    """
    columns = st.columns(len(specs))
    for column, spec in zip(columns, specs):
        field, label, unit = spec[:3]
        delta_color = spec[3] if len(spec) > 3 else "normal"
        help_text = glossary.short(glossary.FIELDS[field]) if field in glossary.FIELDS else None
        value = row.get(field) if row is not None else None
        if value is None or pd.isna(value):
            column.metric(label, "—", help=help_text)
            continue
        delta = None
        before = previous.get(field) if previous is not None else None
        if before is not None and not pd.isna(before):
            diff = float(value) - float(before)
            delta = f"{diff:+.1f}".rstrip("0").rstrip(".") + (f" {unit}" if unit else "")
        shown = f"{float(value):.1f}".rstrip("0").rstrip(".")
        column.metric(label, f"{shown}{(' ' + unit) if unit else ''}", delta, delta_color=delta_color,
                      help=help_text)


def week_before(frame: pd.DataFrame) -> pd.Series | None:
    """Mean of the seven days before the latest one: the baseline the tiles
    compare against. Yesterday alone is too noisy a reference for HRV or sleep."""
    if len(frame) < 3:
        return None
    return frame.sort_values("day").iloc[-8:-1].mean(numeric_only=True)


def missing(name: str, hint: str = "") -> None:
    st.caption(i18n.tr(pl=f"Tabela `{name}` jest pusta. {hint}", en=f"Table `{name}` is empty. {hint}").strip())


def pace(minutes: float | None) -> str:
    """Tile text for a pace: ``5:43 /km``."""
    if minutes is None or pd.isna(minutes):
        return "—"
    seconds = int(round(float(minutes) * 60))
    return f"{seconds // 60}:{seconds % 60:02d} /km"


def pace_column(values: pd.Series) -> pd.Series:
    """A pace column for tables, as ``m:ss`` text."""
    return pd.to_numeric(values, errors="coerce").map(
        lambda v: pace(v).removesuffix(" /km") if pd.notna(v) else None
    )


def clock(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def latest_day() -> pd.Series | None:
    frame = daily()
    if frame.empty:
        return None
    scored = frame.dropna(subset=["readiness", "sleep_score"], how="all")
    return (scored if not scored.empty else frame).iloc[-1]


def days_since(row: pd.Series | None) -> int | None:
    if row is None:
        return None
    return (dt.date.today() - row["day"].date()).days


def has_data() -> bool:
    return not daily().empty
