"""04 // CONSTRUCTOR INTELLIGENCE — Team Season KPIs, Trajectory & Teammate Breakdown."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from frontend.api_client import RaceIntelAPIClient
from frontend.driver_photos import render_driver_portrait
from frontend.theme import (
    BG_SECONDARY,
    FG_LIGHT,
    FG_PRIMARY,
    RETRO_SERIES_PALETTE,
    render_error_box,
    render_kpi_card,
    render_notice_box,
    render_section_title,
    style_altair_chart,
)


def render_constructor_intel_page(client: RaceIntelAPIClient, season: int = 2024) -> None:
    """Render Constructor Intelligence view backed by `/analytics/constructors/{id}/season`."""
    render_section_title("CON-01", f"CONSTRUCTOR CHAMPIONSHIP INTELLIGENCE // SEASON {season}")

    # 1. Fetch active season constructors via Overview standings
    overview, ov_err = client.get_overview(season=season)
    season_con_standings = (overview or {}).get("constructor_standings") or []

    all_constructors, all_err = client.get_constructors()
    if all_err and not season_con_standings:
        render_error_box("CONSTRUCTORS LOAD ERROR", all_err)
        return

    show_all = st.checkbox(
        f"Show all historical constructors (Uncheck to view only active {season} teams)",
        value=False if season_con_standings else True,
        key="con_show_all_toggle",
    )

    con_map: dict[str, int] = {}
    if not show_all and season_con_standings:
        for row in season_con_standings:
            cid = int(row["constructor_id"])
            name = row.get("constructor_name") or "CONSTRUCTOR"
            rank = row.get("rank")
            rank_str = f"P{rank:02d}" if rank else "P--"
            pts_str = f"{row.get('total_points', 0):.0f} PTS"
            label = f"{rank_str} // {name} — {pts_str}"
            con_map[label] = cid
    elif all_constructors:
        for c in sorted(all_constructors, key=lambda x: x.get("constructor_name") or ""):
            cid = int(c["constructor_id"])
            name = c.get("constructor_name") or "CONSTRUCTOR"
            con_map[name] = cid

    if not con_map:
        render_notice_box(f"No constructor records available for season {season}.")
        return

    labels = list(con_map.keys())
    selected_label = st.selectbox("SELECT CONSTRUCTOR DOSSIER", options=labels, index=0, key="con_select")
    constructor_id = int(con_map[selected_label])

    profile, prof_err = client.get_constructor_season(constructor_id, season=season)
    if prof_err:
        render_error_box("CONSTRUCTOR PROFILE ERROR", prof_err)
        return
    if not profile:
        render_notice_box("Constructor profile returned no data.")
        return

    con_info = profile.get("constructor", {})
    summary = profile.get("summary", {})
    contribs = profile.get("driver_contributions") or []
    race_totals = profile.get("race_totals") or []
    driver_results = profile.get("driver_results") or []
    con_name = con_info.get("constructor_name") or "Team"

    # 2. Constructor Headline KPI Console
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        rank = summary.get("championship_rank")
        render_kpi_card(
            "CHAMPIONSHIP RANK",
            f"P{rank}" if rank is not None else "N/A",
            f"TEAM: {con_name}",
        )
    with k2:
        sprint_pts = summary.get("sprint_points", 0.0)
        render_kpi_card(
            "TOTAL TEAM POINTS",
            f"{summary.get('total_points', 0.0)} PTS",
            f"GP: {summary.get('race_points', summary.get('total_points', 0.0))} // SPRINT: {sprint_pts} PTS",
        )
    with k3:
        render_kpi_card(
            "WINS // PODIUMS",
            f"{summary.get('wins', 0)}W // {summary.get('podiums', 0)}P",
            f"DOUBLE-POINTS FINISHES: {summary.get('double_points_finishes', 0)}",
        )
    with k4:
        top_scorer = contribs[0] if contribs else {}
        lead_code = top_scorer.get("driver_code") or "N/A"
        lead_pts = top_scorer.get("total_points", 0)
        team_pts = max(summary.get("total_points", 1), 1)
        lead_pct = (lead_pts / team_pts * 100) if team_pts > 0 else 0
        render_kpi_card(
            "LEAD DRIVER SHARE",
            f"{lead_code} ({lead_pct:.1f}%)",
            f"{lead_pts:.1f} PTS scored by {top_scorer.get('driver_full_name', 'Lead')}",
        )

    if not race_totals:
        render_notice_box(
            f"[DATA STATE] {con_name} has no race points or session records in the {season} season. "
            f"Select another constructor or choose a different season in the sidebar."
        )
        return

    rt_df = pd.DataFrame(race_totals)
    drv_res_df = pd.DataFrame(driver_results)
    contrib_df = pd.DataFrame(contribs)

    # 3. Driver Contribution Split & Teammate Intra-Team Analysis
    render_section_title("CON-02", f"DRIVER ROSTER & INTRA-TEAM CONTRIBUTION SPLIT // {season}")
    c_left, c_right = st.columns([1, 1])

    with c_left:
        st.markdown(f"**{con_name.upper()} DRIVER POINTS SHARE**")
        if not contrib_df.empty:
            contrib_chart = (
                alt.Chart(contrib_df)
                .mark_bar(color=FG_PRIMARY, stroke=FG_LIGHT, strokeWidth=1)
                .encode(
                    x=alt.X("total_points:Q", title="TOTAL POINTS SCORED"),
                    y=alt.Y("driver_code:N", sort="-x", title="DRIVER"),
                    tooltip=["driver_code:N", "driver_full_name:N", "total_points:Q", "wins:Q", "podiums:Q", "average_finish:Q"],
                )
            )
            st.altair_chart(style_altair_chart(contrib_chart, height=220), width="stretch")

    with c_right:
        st.markdown(f"**DRIVER LINEUP DOSSIERS**")
        d_cols = st.columns(len(contribs)) if contribs else []
        for idx, drv in enumerate(contribs):
            with d_cols[idx]:
                render_driver_portrait(
                    driver_code=drv.get("driver_code"),
                    driver_name=drv.get("driver_full_name", ""),
                    constructor_name=con_name,
                    width=130,
                    height=130,
                    show_caption=False,
                )
                st.caption(f"**{drv.get('driver_code')}**: {drv.get('total_points')} PTS ({drv.get('wins', 0)}W/{drv.get('podiums', 0)}P)")

    # Teammate Comparison Table
    if not contrib_df.empty:
        contrib_display = contrib_df.copy()
        total_pts = max(float(summary.get("total_points", 1)), 1.0)
        contrib_display["points_share"] = (contrib_display["total_points"] / total_pts * 100).round(1).astype(str) + "%"
        col_map = {
            "driver_code": "Code",
            "driver_full_name": "Driver",
            "races": "Starts",
            "race_points": "GP Points",
            "sprint_points": "Sprint Points",
            "total_points": "Total Points",
            "points_share": "Share %",
            "wins": "Wins",
            "podiums": "Podiums",
            "best_finish": "Best Finish",
            "average_finish": "Avg Finish",
        }
        cols_to_show = [c for c in col_map.keys() if c in contrib_display.columns]
        st.dataframe(contrib_display[cols_to_show].rename(columns=col_map), width="stretch", hide_index=True)

    # 4. Team Points Progression Dynamics
    render_section_title("CON-03", f"{con_name.upper()} SEASON POINTS PROGRESSION")
    p_left, p_right = st.columns(2)
    with p_left:
        pts_bar = (
            alt.Chart(rt_df)
            .mark_bar(color=BG_SECONDARY, stroke=FG_PRIMARY, strokeWidth=1)
            .encode(
                x=alt.X("round_index:O", title="ROUND NUMBER"),
                y=alt.Y("team_points:Q", title="POINTS SCORED"),
                tooltip=["round_index:Q", "event_name:N", "team_points:Q", "best_finish:Q", "cumulative_points:Q"],
            )
        )
        st.altair_chart(style_altair_chart(pts_bar, height=270, title="POINTS SCORED PER GRAND PRIX"), width="stretch")

    with p_right:
        pts_cum = (
            alt.Chart(rt_df)
            .mark_line(point=True, color=FG_PRIMARY, strokeWidth=2.2)
            .encode(
                x=alt.X("round_index:O", title="ROUND NUMBER"),
                y=alt.Y("cumulative_points:Q", title="CUMULATIVE POINTS"),
                tooltip=["round_index:Q", "event_name:N", "team_points:Q", "cumulative_points:Q"],
            )
        )
        st.altair_chart(style_altair_chart(pts_cum, height=270, title="CUMULATIVE CONSTRUCTOR POINTS TRAJECTORY"), width="stretch")

    # 5. Round-by-Round Classification Matrix
    render_section_title("LOG-04", f"{con_name.upper()} ROUND-BY-ROUND CLASSIFICATION LOG")
    cal_cols = [
        c
        for c in [
            "round_index",
            "event_name",
            "circuit_name",
            "driver_code",
            "driver_full_name",
            "grid_position",
            "finish_position",
            "points_scored",
            "classified_status",
        ]
        if c in drv_res_df.columns
    ]
    st.dataframe(drv_res_df[cal_cols], width="stretch", hide_index=True)
