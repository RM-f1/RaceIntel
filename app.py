"""
RaceIntel — Retro Terminal F1 Race Control Dashboard.

Run FastAPI backend first:
    uvicorn raceintel.api.main:app --port 8001
Then launch this Streamlit console:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from frontend.api_client import RaceIntelAPIClient, get_api_base_url
from frontend.theme import apply_retro_theme, render_error_box, render_terminal_header
from frontend.views.ai_engineer import render_ai_engineer_page
from frontend.views.constructor_intel import render_constructor_intel_page
from frontend.views.dashboard import render_dashboard_page
from frontend.views.driver_intel import render_driver_intel_page
from frontend.views.race_analysis import render_race_analysis_page
from frontend.views.system_about import render_system_about_page

NAV_OPTIONS = [
    "01 // DASHBOARD",
    "02 // RACE ANALYSIS",
    "03 // DRIVER INTELLIGENCE",
    "04 // CONSTRUCTOR INTELLIGENCE",
    "05 // AI RACE ENGINEER",
    "06 // SYSTEM / ABOUT",
]

st.set_page_config(
    page_title="RACEINTEL // F1 RACE CONTROL",
    page_icon="🏁",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    apply_retro_theme()
    client = RaceIntelAPIClient()

    health, health_err = client.get_health()
    api_online = bool(health and health.get("status") == "healthy" and health_err is None)
    status_badge = "LINK: ONLINE // DB READY" if api_online else "LINK: OFFLINE // CHECK PORT"

    with st.sidebar:
        st.markdown(
            """
            <div style="border:2px solid #D5E8B5; background:#17251D; padding:0.7rem; margin-bottom:0.8rem;">
                <div style="font-size:1.05rem; font-weight:800; color:#FFFFFF; letter-spacing:0.1em;">
                    [ RACEINTEL ]
                </div>
                <div style="font-size:0.72rem; color:#D5E8B5; margin-top:0.2rem;">
                    F1 RACE CONTROL TERMINAL v6.0
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected_page = st.radio(
            "CONSOLE MODULE",
            options=NAV_OPTIONS,
            index=0,
            key="nav_module",
        )

        season = st.selectbox(
            "ACTIVE SEASON",
            options=[2026, 2025, 2024, 2023, 2022],
            index=0,
            key="global_season",
        )

        st.markdown("---")
        st.caption(f"API TARGET: {get_api_base_url()}")
        st.caption(f"STATUS: {'ONLINE' if api_online else 'OFFLINE'}")
        if st.button("REFRESH LINK", width="stretch", key="sidebar_refresh"):
            st.rerun()

    render_terminal_header(
        title="RACEINTEL // F1 RACE CONTROL INTELLIGENCE",
        subtitle="REAL DATA PIPELINE :: FASTAPI + SQLITE ANALYTICS + CHROMADB RAG + AI RACE ENGINEER",
        status_label=status_badge,
        online=api_online,
    )

    if not api_online and selected_page != "06 // SYSTEM / ABOUT":
        render_error_box(
            "BACKEND API CONNECTION UNAVAILABLE",
            f"{health_err or 'Unable to verify /health/'} — Ensure FastAPI is running on {get_api_base_url()}.",
        )

    if selected_page == "01 // DASHBOARD":
        render_dashboard_page(client, season=int(season))
    elif selected_page == "02 // RACE ANALYSIS":
        render_race_analysis_page(client, season=int(season))
    elif selected_page == "03 // DRIVER INTELLIGENCE":
        render_driver_intel_page(client, season=int(season))
    elif selected_page == "04 // CONSTRUCTOR INTELLIGENCE":
        render_constructor_intel_page(client, season=int(season))
    elif selected_page == "05 // AI RACE ENGINEER":
        render_ai_engineer_page(client, season=int(season))
    else:
        render_system_about_page(client, season=int(season))


if __name__ == "__main__":
    main()
else:
    # Executed cleanly under Streamlit's runner as well as AppTest
    main()