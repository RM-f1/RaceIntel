"""
Retro Terminal visual design system for RaceIntel.

Inspired by classic Nokia-era monochrome LCD hardware and F1 race-control
consoles: deep phosphor forest background (#17251D), bright sage display ink
(#D5E8B5), muted bezel grey-green (#A7B89C), crisp white highlights (#FFFFFF),
thick square borders, and zero rounded corners.
"""

from __future__ import annotations

import html
from typing import Any

import altair as alt
import streamlit as st

BG_PRIMARY = "#17251D"
BG_SURFACE = "#1E2F25"
BG_PANEL = "#1B2B22"
FG_PRIMARY = "#D5E8B5"
BG_SECONDARY = "#A7B89C"
FG_LIGHT = "#FFFFFF"
BORDER_DIM = "#385243"

MONO_FONT = "'JetBrains Mono', 'Cascadia Mono', 'Consolas', 'Courier New', monospace"

RETRO_SERIES_PALETTE = [
    "#D5E8B5",
    "#FFFFFF",
    "#A7B89C",
    "#7FA085",
    "#E9F4D6",
    "#5E7D67",
]


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def get_retro_css() -> str:
    """Return full Retro Terminal CSS stylesheet for Streamlit."""
    return f"""
<style>
:root {{
    --ri-bg: {BG_PRIMARY};
    --ri-surface: {BG_SURFACE};
    --ri-panel: {BG_PANEL};
    --ri-fg: {FG_PRIMARY};
    --ri-sec: {BG_SECONDARY};
    --ri-white: {FG_LIGHT};
    --ri-dim: {BORDER_DIM};
    --ri-font: {MONO_FONT};
}}

/* Force square CRT geometry & monospace aesthetic globally */
html, body, [class*="css"], .stApp {{
    background-color: var(--ri-bg) !important;
    color: var(--ri-fg) !important;
    font-family: var(--ri-font) !important;
}}

/* Subtle hardware scanline texture over canvas without blocking interaction */
[data-testid="stAppViewContainer"]::before {{
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 999;
    background: repeating-linear-gradient(
        0deg,
        rgba(213, 232, 181, 0.025) 0px,
        rgba(213, 232, 181, 0.025) 1px,
        transparent 1px,
        transparent 3px
    );
}}

[data-testid="stHeader"] {{
    background-color: var(--ri-bg) !important;
    border-bottom: 2px solid var(--ri-sec) !important;
}}

[data-testid="stSidebar"] {{
    background-color: #131F18 !important;
    border-right: 3px solid var(--ri-sec) !important;
}}

[data-testid="stSidebar"] * {{
    color: var(--ri-fg) !important;
    font-family: var(--ri-font) !important;
}}

/* Remove rounded corners everywhere */
*, *::before, *::after {{
    border-radius: 0px !important;
}}

/* Headings */
h1, h2, h3, h4 {{
    color: var(--ri-white) !important;
    font-family: var(--ri-font) !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
}}

/* Primary & Secondary Buttons */
.stButton > button {{
    background-color: var(--ri-surface) !important;
    color: var(--ri-fg) !important;
    border: 2px solid var(--ri-fg) !important;
    font-family: var(--ri-font) !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    padding: 0.45rem 0.85rem !important;
    box-shadow: 3px 3px 0px var(--ri-sec) !important;
    transition: transform 0.08s ease, background-color 0.08s ease !important;
}}

.stButton > button:hover {{
    background-color: var(--ri-fg) !important;
    color: var(--ri-bg) !important;
    border-color: var(--ri-white) !important;
}}

.stButton > button:active {{
    transform: translate(2px, 2px) !important;
    box-shadow: 1px 1px 0px var(--ri-sec) !important;
}}

/* Radio navigation in sidebar */
[data-testid="stSidebar"] [role="radiogroup"] label {{
    background-color: var(--ri-panel) !important;
    border: 2px solid var(--ri-dim) !important;
    padding: 0.45rem 0.65rem !important;
    margin-bottom: 0.35rem !important;
    width: 100% !important;
}}

[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
    border-color: var(--ri-fg) !important;
}}

/* Inputs, Selectboxes, Textareas */
[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
textarea,
input {{
    background-color: var(--ri-surface) !important;
    color: var(--ri-white) !important;
    border: 2px solid var(--ri-sec) !important;
    font-family: var(--ri-font) !important;
}}

/* Chat input bar */
[data-testid="stChatInput"] {{
    background-color: var(--ri-surface) !important;
    border: 2px solid var(--ri-fg) !important;
}}

/* Tabs */
[data-baseweb="tab-list"] {{
    gap: 0.4rem !important;
    border-bottom: 2px solid var(--ri-sec) !important;
}}

[data-baseweb="tab"] {{
    background-color: var(--ri-panel) !important;
    color: var(--ri-fg) !important;
    border: 2px solid var(--ri-dim) !important;
    border-bottom: none !important;
    font-family: var(--ri-font) !important;
    text-transform: uppercase !important;
    font-weight: 700 !important;
}}

[aria-selected="true"][data-baseweb="tab"] {{
    background-color: var(--ri-fg) !important;
    color: var(--ri-bg) !important;
    border-color: var(--ri-white) !important;
}}

/* Dataframes & Tables */
[data-testid="stDataFrame"],
[data-testid="stTable"] {{
    border: 2px solid var(--ri-sec) !important;
    background-color: var(--ri-panel) !important;
}}

/* Terminal KPI Card */
.ri-kpi {{
    background-color: var(--ri-surface);
    border: 2px solid var(--ri-fg);
    box-shadow: 4px 4px 0px #0D1611;
    padding: 0.75rem 0.9rem;
    margin-bottom: 0.65rem;
}}

.ri-kpi-label {{
    color: var(--ri-sec);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.2rem;
}}

.ri-kpi-value {{
    color: var(--ri-white);
    font-size: 1.35rem;
    font-weight: 800;
    line-height: 1.2;
    word-break: break-word;
}}

.ri-kpi-sub {{
    color: var(--ri-fg);
    font-size: 0.74rem;
    margin-top: 0.25rem;
}}

/* Section Banner */
.ri-section-bar {{
    background-color: var(--ri-surface);
    border: 2px solid var(--ri-sec);
    border-left: 6px solid var(--ri-fg);
    padding: 0.45rem 0.85rem;
    margin: 0.9rem 0 0.65rem 0;
    color: var(--ri-white);
    font-size: 0.92rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}}

/* Header Console Bar */
.ri-console-header {{
    background-color: #121E17;
    border: 3px solid var(--ri-fg);
    box-shadow: 5px 5px 0px #0C140F;
    padding: 0.85rem 1.1rem;
    margin-bottom: 1rem;
}}

.ri-console-top {{
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    border-bottom: 2px dashed var(--ri-dim);
    padding-bottom: 0.45rem;
    margin-bottom: 0.45rem;
}}

.ri-console-title {{
    color: var(--ri-white);
    font-size: 1.25rem;
    font-weight: 800;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}}

.ri-console-sub {{
    color: var(--ri-fg);
    font-size: 0.82rem;
}}

.ri-badge {{
    display: inline-block;
    padding: 0.18rem 0.55rem;
    border: 2px solid var(--ri-fg);
    font-size: 0.74rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}}

.ri-badge-ok {{
    background-color: var(--ri-fg);
    color: var(--ri-bg);
}}

.ri-badge-warn {{
    background-color: var(--ri-surface);
    color: var(--ri-white);
    border-color: var(--ri-sec);
}}

.ri-badge-err {{
    background-color: #3A1D1D;
    color: var(--ri-white);
    border-color: #FFFFFF;
}}

.ri-notice {{
    background-color: var(--ri-panel);
    border: 2px solid var(--ri-sec);
    padding: 0.65rem 0.85rem;
    color: var(--ri-fg);
    font-size: 0.84rem;
    margin: 0.5rem 0;
}}

.ri-error-box {{
    background-color: #2B1818;
    border: 2px solid var(--ri-white);
    padding: 0.75rem 0.9rem;
    color: var(--ri-white);
    font-size: 0.86rem;
    margin: 0.6rem 0;
}}

.ri-chat-msg {{
    border: 2px solid var(--ri-sec);
    padding: 0.75rem 0.9rem;
    margin-bottom: 0.65rem;
    background-color: var(--ri-panel);
}}

.ri-chat-user {{
    border-color: var(--ri-white);
    background-color: #203429;
}}

.ri-chat-ai {{
    border-color: var(--ri-fg);
    background-color: #142119;
}}

.ri-chat-role {{
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: var(--ri-sec);
    text-transform: uppercase;
    margin-bottom: 0.3rem;
}}

@keyframes riBlink {{
    0%, 49% {{ opacity: 1; }}
    50%, 100% {{ opacity: 0; }}
}}

.ri-cursor {{
    display: inline-block;
    width: 0.55rem;
    height: 0.95rem;
    background-color: var(--ri-fg);
    vertical-align: text-bottom;
    margin-left: 0.25rem;
    animation: riBlink 1.1s steps(1, end) infinite;
}}
</style>
"""


def apply_retro_theme() -> None:
    """Inject the Retro Terminal stylesheet into the active Streamlit page."""
    st.markdown(get_retro_css(), unsafe_allow_html=True)


def render_terminal_header(title: str, subtitle: str, status_label: str, online: bool = True) -> None:
    """Render top race-control console header bar."""
    badge_cls = "ri-badge ri-badge-ok" if online else "ri-badge ri-badge-err"
    st.markdown(
        f"""
        <div class="ri-console-header">
            <div class="ri-console-top">
                <div class="ri-console-title">&gt;_ {_esc(title)}<span class="ri-cursor"></span></div>
                <span class="{badge_cls}">{_esc(status_label)}</span>
            </div>
            <div class="ri-console-sub">{_esc(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_title(code: str, title: str) -> None:
    """Render a terminal section divider banner."""
    st.markdown(
        f'<div class="ri-section-bar">[{_esc(code)}] {_esc(title)}</div>',
        unsafe_allow_html=True,
    )


def render_kpi_card(label: str, value: Any, subtext: str = "") -> None:
    """Render a bordered square pixel-terminal KPI metric box."""
    sub_html = f'<div class="ri-kpi-sub">{_esc(subtext)}</div>' if subtext else ""
    st.markdown(
        f"""
        <div class="ri-kpi">
            <div class="ri-kpi-label">{_esc(label)}</div>
            <div class="ri-kpi-value">{_esc(value)}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_notice_box(message: str) -> None:
    """Render a bordered informational terminal notice box."""
    st.markdown(
        f'<div class="ri-notice">&gt; {_esc(message)}</div>',
        unsafe_allow_html=True,
    )


def render_error_box(title: str, detail: str) -> None:
    """Render a high-contrast bordered terminal error panel."""
    st.markdown(
        f"""
        <div class="ri-error-box">
            <strong>[ERR // {_esc(title)}]</strong><br/>
            {_esc(detail)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def style_altair_chart(chart: alt.Chart, height: int = 320, title: str = "") -> alt.Chart:
    """Apply consistent monochrome phosphor green Retro Terminal theme to an Altair chart."""
    styled = chart.properties(height=height)
    if title:
        styled = styled.properties(title=title)
    return (
        styled.configure(background=BG_PRIMARY, font="Consolas, Courier New, monospace")
        .configure_view(fill=BG_SURFACE, stroke=BG_SECONDARY, strokeWidth=1.5)
        .configure_title(color=FG_LIGHT, fontSize=13, anchor="start", font="Consolas, Courier New, monospace")
        .configure_axis(
            gridColor="#2C4336",
            gridDash=[2, 2],
            domainColor=BG_SECONDARY,
            tickColor=BG_SECONDARY,
            labelColor=FG_PRIMARY,
            titleColor=FG_LIGHT,
            labelFontSize=11,
            titleFontSize=11,
        )
        .configure_legend(
            labelColor=FG_PRIMARY,
            titleColor=FG_LIGHT,
            fillColor=BG_PANEL,
            strokeColor=BG_SECONDARY,
            padding=6,
        )
    )
