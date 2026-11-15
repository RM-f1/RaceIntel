"""03 // DRIVER INTELLIGENCE — Driver Season Profile, Genuine Portraits & Head-to-Head."""

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


def render_driver_intel_page(client: RaceIntelAPIClient, season: int = 2024) -> None:
    """Render Driver Intelligence view with genuine portraits, season KPIs, and H2H comparison."""
    render_section_title("DRV-01", f"DRIVER TELEMETRY DOSSIER // SEASON {season}")

    # 1. Fetch active season drivers via Overview standings, fallback to full driver list
    overview, ov_err = client.get_overview(season=season)
    season_standings = (overview or {}).get("driver_standings") or []

    all_drivers, all_err = client.get_drivers()
    if all_err and not season_standings:
        render_error_box("DRIVERS LOAD ERROR", all_err)
        return

    # Checkbox to view all historical drivers or only active season drivers
    show_all = st.checkbox(
        f"Show all historical drivers (Uncheck to view only active {season} drivers)",
        value=False if season_standings else True,
        key="drv_show_all_toggle",
    )

    driver_map: dict[str, int] = {}
    driver_meta_map: dict[int, dict] = {}

    if not show_all and season_standings:
        for row in season_standings:
            did = int(row["driver_id"])
            code = row.get("driver_code") or "DRV"
            name = row.get("driver_full_name") or ""
            team = row.get("constructor_name") or "N/A"
            rank = row.get("rank")
            rank_str = f"P{rank:02d}" if rank else "P--"
            pts_str = f"{row.get('total_points', 0):.0f} PTS"
            label = f"{rank_str} // {code} // {name} ({team}) — {pts_str}"
            driver_map[label] = did
            driver_meta_map[did] = row
    elif all_drivers:
        for d in sorted(all_drivers, key=lambda x: x.get("driver_code") or ""):
            did = int(d["driver_id"])
            code = d.get("driver_code") or "DRV"
            name = d.get("driver_full_name") or ""
            team = d.get("constructor") or "N/A"
            label = f"{code} // {name} ({team})"
            driver_map[label] = did
            driver_meta_map[did] = d

    if not driver_map:
        render_notice_box(f"No driver records available for season {season}.")
        return

    labels = list(driver_map.keys())

    # 2. Driver Selection Controls
    c_sel1, c_sel2 = st.columns(2)
    with c_sel1:
        primary_label = st.selectbox("PRIMARY DRIVER DOSSIER", options=labels, index=0, key="drv_primary_select")
    with c_sel2:
        h2h_options = ["[NONE // SINGLE DRIVER MODE]"] + [lbl for lbl in labels if lbl != primary_label]
        compare_label = st.selectbox("HEAD-TO-HEAD OPPONENT", options=h2h_options, index=0, key="drv_compare_select")

    primary_id = int(driver_map[primary_label])
    profile, prof_err = client.get_driver_season(primary_id, season=season)
    if prof_err:
        render_error_box("DRIVER PROFILE ERROR", prof_err)
        return
    if not profile:
        render_notice_box(f"Driver profile returned no data for season {season}.")
        return

    drv_info = profile.get("driver", {})
    summary = profile.get("summary", {})
    races = profile.get("races") or []

    # 3. Primary Driver Profile Card (Genuine Photograph + Comprehensive KPIs)
    p_photo_col, p_stats_col = st.columns([1, 4])
    with p_photo_col:
        render_driver_portrait(
            driver_code=drv_info.get("driver_code"),
            driver_name=drv_info.get("driver_full_name", ""),
            driver_number=drv_info.get("driver_number"),
            constructor_name=drv_info.get("season_constructor") or drv_info.get("constructor_name"),
            width=160,
            height=160,
            show_caption=True,
        )

    with p_stats_col:
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            rank_val = summary.get("championship_rank")
            rank_disp = f"P{rank_val}" if rank_val else "N/A"
            render_kpi_card(
                "CHAMPIONSHIP STANDING",
                rank_disp,
                f"{drv_info.get('driver_code')} // #{drv_info.get('driver_number') or '-'}",
            )
        with k2:
            sprint_pts = summary.get("sprint_points", 0.0)
            render_kpi_card(
                "TOTAL POINTS",
                f"{summary.get('total_points', 0.0)} PTS",
                f"GP: {summary.get('race_points', summary.get('total_points', 0.0))} // SPRINT: {sprint_pts} PTS",
            )
        with k3:
            render_kpi_card(
                "WINS // PODIUMS",
                f"{summary.get('wins', 0)}W // {summary.get('podiums', 0)}P",
                f"PTS FINISHES: {summary.get('points_finishes', 0)} / {summary.get('races', 0)}",
            )
        with k4:
            avg_fin = summary.get("average_finish")
            avg_fin_str = f"P{avg_fin:.2f}" if isinstance(avg_fin, (int, float)) else "N/A"
            avg_grid = summary.get("average_grid")
            avg_grid_str = f"P{avg_grid:.1f}" if isinstance(avg_grid, (int, float)) else "N/A"
            render_kpi_card(
                "RACE & QUALIFYING AVG",
                f"R: {avg_fin_str}",
                f"GRID AVG: {avg_grid_str} // BEST: P{summary.get('best_grid') or '-'}",
            )

        # Secondary KPI Row for Detailed Telemetry
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            render_kpi_card("BEST RACE FINISH", f"P{summary.get('best_finish') or '-'}", f"STARTS: {summary.get('races', 0)}")
        with s2:
            render_kpi_card("BEST QUALIFYING / GRID", f"P{summary.get('best_grid') or '-'}", f"AVERAGE: {avg_grid_str}")
        with s3:
            render_kpi_card("RETIREMENTS / DNF", f"{summary.get('retirements', 0)} DNF", f"COMPLETION RATE: {((summary.get('races', 0) - summary.get('retirements', 0)) / max(summary.get('races', 1), 1) * 100):.1f}%")
        with s4:
            net_gain = summary.get("net_positions_gained", 0)
            render_kpi_card("NET POSITIONS GAINED", f"{net_gain:+d} POS", "OVER TOTAL GRID STARTS")

    if not races:
        render_notice_box(
            f"[DATA STATE] {drv_info.get('driver_full_name')} ({drv_info.get('driver_code')}) has no Grand Prix "
            f"race results logged for the {season} season. Select another driver or switch season in the sidebar."
        )
        return

    df_primary = pd.DataFrame(races)

    # 4. Head-to-Head Comparison Experience
    if compare_label != "[NONE // SINGLE DRIVER MODE]":
        cmp_id = int(driver_map[compare_label])
        cmp_prof, cmp_err = client.get_driver_season(cmp_id, season=season)
        if cmp_err:
            render_error_box("COMPARISON FETCH ERROR", cmp_err)
        elif cmp_prof and cmp_prof.get("races"):
            cmp_info = cmp_prof["driver"]
            cmp_sum = cmp_prof["summary"]
            df_cmp = pd.DataFrame(cmp_prof["races"])

            code_a = drv_info.get("driver_code", "DRV A")
            code_b = cmp_info.get("driver_code", "DRV B")
            team_a = drv_info.get("season_constructor") or drv_info.get("constructor_name")
            team_b = cmp_info.get("season_constructor") or cmp_info.get("constructor_name")
            is_teammates = bool(team_a and team_b and team_a.lower() == team_b.lower())

            render_section_title("H2H-02", f"HEAD-TO-HEAD BATTLE // {code_a} VS {code_b} ({season})")

            if is_teammates:
                render_notice_box(f"[TEAMMATE INTRA-TEAM BATTLE] Both drivers competed for {team_a} in {season}.")

            # Side-by-Side Genuine Driver Photographs and Bio
            col_a, col_mid, col_b = st.columns([2, 3, 2])
            with col_a:
                st.markdown(f"**[ {code_a} // {drv_info.get('driver_full_name')} ]**")
                render_driver_portrait(
                    driver_code=code_a,
                    driver_name=drv_info.get("driver_full_name", ""),
                    driver_number=drv_info.get("driver_number"),
                    constructor_name=team_a,
                    width=150,
                    height=150,
                    show_caption=True,
                )
            with col_mid:
                # Merged comparison metrics
                cols_a = ["session_id", "round_index", "event_name", "finish_position", "grid_position", "points_scored"]
                if "sprint_points" in df_primary.columns:
                    cols_a.append("sprint_points")
                if "round_points" in df_primary.columns:
                    cols_a.append("round_points")
                cols_b = ["session_id", "finish_position", "grid_position", "points_scored"]
                if "sprint_points" in df_cmp.columns:
                    cols_b.append("sprint_points")
                if "round_points" in df_cmp.columns:
                    cols_b.append("round_points")

                merged = df_primary[cols_a].merge(
                    df_cmp[cols_b],
                    on="session_id",
                    suffixes=("_A", "_B"),
                )
                a_ahead = int((merged["finish_position_A"] < merged["finish_position_B"]).sum())
                b_ahead = int((merged["finish_position_B"] < merged["finish_position_A"]).sum())
                equal = int((merged["finish_position_A"] == merged["finish_position_B"]).sum())

                pts_a = float(summary.get("total_points", 0))
                pts_b = float(cmp_sum.get("total_points", 0))
                delta_pts = pts_a - pts_b

                st.markdown(
                    f"""
                    <div style="border:2px solid #D5E8B5; background:#1E2F25; padding:0.8rem; font-family:'Consolas',monospace;">
                        <div style="font-size:0.75rem; color:#A7B89C; margin-bottom:4px;">HEAD-TO-HEAD FINISH RECORD</div>
                        <div style="font-size:1.6rem; font-weight:800; color:#FFFFFF;">
                            {code_a} {a_ahead} — {b_ahead} {code_b}
                        </div>
                        <div style="font-size:0.75rem; color:#D5E8B5; margin-top:4px;">
                            SHARED RACES: {len(merged)} // TIED: {equal}
                        </div>
                        <div style="font-size:0.8rem; color:#FFFFFF; margin-top:8px; border-top:1px solid #385243; padding-top:6px;">
                            POINTS DELTA: <strong>{delta_pts:+.1f} PTS</strong> (in favor of {code_a if delta_pts >= 0 else code_b})
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with col_b:
                st.markdown(f"**[ {code_b} // {cmp_info.get('driver_full_name')} ]**")
                render_driver_portrait(
                    driver_code=code_b,
                    driver_name=cmp_info.get("driver_full_name", ""),
                    driver_number=cmp_info.get("driver_number"),
                    constructor_name=team_b,
                    width=150,
                    height=150,
                    show_caption=True,
                )

            # Comparative Metrics Grid
            cm1, cm2, cm3, cm4 = st.columns(4)
            with cm1:
                render_kpi_card(
                    "CHAMPIONSHIP RANK",
                    f"{code_a}: P{summary.get('championship_rank') or '-'} vs {code_b}: P{cmp_sum.get('championship_rank') or '-'}",
                    f"DELTA: {abs((summary.get('championship_rank') or 0) - (cmp_sum.get('championship_rank') or 0))} POS",
                )
            with cm2:
                render_kpi_card(
                    "TOTAL POINTS",
                    f"{pts_a:.1f} vs {pts_b:.1f}",
                    f"DIFF: {delta_pts:+.1f} PTS",
                )
            with cm3:
                render_kpi_card(
                    "WINS // PODIUMS",
                    f"{summary.get('wins', 0)}W / {summary.get('podiums', 0)}P vs {cmp_sum.get('wins', 0)}W / {cmp_sum.get('podiums', 0)}P",
                    f"{code_a} vs {code_b}",
                )
            with cm4:
                avg_a = summary.get("average_finish") or 0
                avg_b = cmp_sum.get("average_finish") or 0
                render_kpi_card(
                    "AVERAGE FINISH",
                    f"P{avg_a:.2f} vs P{avg_b:.2f}",
                    f"LOWER IS BETTER (ADVANTAGE: {code_a if avg_a <= avg_b else code_b})",
                )

            # Cumulative Points Trajectory Comparison Chart
            both_pts = pd.concat(
                [
                    df_primary.assign(driver_code=code_a),
                    df_cmp.assign(driver_code=code_b),
                ],
                ignore_index=True,
            )
            h2h_pts_chart = (
                alt.Chart(both_pts)
                .mark_line(point=True, strokeWidth=2.4)
                .encode(
                    x=alt.X("round_index:Q", title="ROUND NUMBER"),
                    y=alt.Y("cumulative_points:Q", title="CUMULATIVE POINTS"),
                    color=alt.Color(
                        "driver_code:N",
                        title="DRIVER",
                        scale=alt.Scale(domain=[code_a, code_b], range=[FG_PRIMARY, FG_LIGHT]),
                    ),
                    tooltip=["driver_code:N", "round_index:Q", "event_name:N", "finish_position:Q", "points_scored:Q", "cumulative_points:Q"],
                )
            )
            st.altair_chart(style_altair_chart(h2h_pts_chart, height=280, title=f"CUMULATIVE POINTS TRAJECTORY // {code_a} VS {code_b}"), width="stretch")

            # Race-by-Race Finishing Position Comparison Chart
            h2h_fin_chart = (
                alt.Chart(both_pts)
                .mark_line(point=True, strokeWidth=2.2)
                .encode(
                    x=alt.X("round_index:Q", title="ROUND NUMBER"),
                    y=alt.Y(
                        "finish_position:Q",
                        title="FINISHING POSITION (LOWER = BETTER)",
                        scale=alt.Scale(reverse=True, domain=[1, 20]),
                    ),
                    color=alt.Color(
                        "driver_code:N",
                        title="DRIVER",
                        scale=alt.Scale(domain=[code_a, code_b], range=[FG_PRIMARY, FG_LIGHT]),
                    ),
                    tooltip=["driver_code:N", "round_index:Q", "event_name:N", "grid_position:Q", "finish_position:Q"],
                )
            )
            st.altair_chart(style_altair_chart(h2h_fin_chart, height=280, title=f"RACE-BY-RACE FINISH COMPARISON // {code_a} VS {code_b}"), width="stretch")

            # Shared Grand Prix Comparison Matrix
            if not merged.empty:
                merged["ahead"] = merged.apply(
                    lambda r: code_a if r["finish_position_A"] < r["finish_position_B"] else (code_b if r["finish_position_B"] < r["finish_position_A"] else "TIED"),
                    axis=1,
                )
                cols_to_show = ["round_index", "event_name", "finish_position_A", "finish_position_B", "points_scored_A", "points_scored_B"]
                col_rename = {
                    "round_index": "Round",
                    "event_name": "Grand Prix",
                    "finish_position_A": f"{code_a} Finish",
                    "finish_position_B": f"{code_b} Finish",
                    "points_scored_A": f"{code_a} GP PTS",
                    "points_scored_B": f"{code_b} GP PTS",
                }
                if "sprint_points_A" in merged.columns and "sprint_points_B" in merged.columns:
                    cols_to_show.extend(["sprint_points_A", "sprint_points_B"])
                    col_rename["sprint_points_A"] = f"{code_a} Sprint PTS"
                    col_rename["sprint_points_B"] = f"{code_b} Sprint PTS"
                if "round_points_A" in merged.columns and "round_points_B" in merged.columns:
                    cols_to_show.extend(["round_points_A", "round_points_B"])
                    col_rename["round_points_A"] = f"{code_a} Total PTS"
                    col_rename["round_points_B"] = f"{code_b} Total PTS"
                cols_to_show.append("ahead")
                col_rename["ahead"] = "Advantage"

                h2h_matrix = merged[cols_to_show].rename(columns=col_rename)
                st.dataframe(h2h_matrix, width="stretch", hide_index=True)

    # 5. Individual Driver Telemetry & Performance Breakdown
    render_section_title("LOG-03", f"{drv_info.get('driver_code')} RACE-BY-RACE PERFORMANCE DYNAMICS")
    c_left, c_right = st.columns(2)
    with c_left:
        pts_chart = (
            alt.Chart(df_primary)
            .mark_bar(color=FG_PRIMARY, stroke=FG_LIGHT, strokeWidth=1)
            .encode(
                x=alt.X("round_index:O", title="ROUND NUMBER"),
                y=alt.Y("points_scored:Q", title="RACE POINTS"),
                tooltip=["round_index:Q", "event_name:N", "finish_position:Q", "points_scored:Q", "cumulative_points:Q"],
            )
        )
        st.altair_chart(style_altair_chart(pts_chart, height=280, title="POINTS SCORED PER GRAND PRIX"), width="stretch")

    with c_right:
        fin_chart = (
            alt.Chart(df_primary)
            .mark_line(point=True, color=FG_LIGHT, strokeWidth=2.2)
            .encode(
                x=alt.X("round_index:O", title="ROUND NUMBER"),
                y=alt.Y(
                    "finish_position:Q",
                    title="FINISH POSITION (LOWER = BETTER)",
                    scale=alt.Scale(reverse=True, domain=[1, 20]),
                ),
                tooltip=["round_index:Q", "event_name:N", "grid_position:Q", "finish_position:Q", "positions_gained:Q", "classified_status:N"],
            )
        )
        st.altair_chart(style_altair_chart(fin_chart, height=280, title="FINISHING POSITION TRAJECTORY"), width="stretch")

    # Full Race Classification Log Table
    cols = [
        c
        for c in [
            "round_index",
            "event_name",
            "circuit_name",
            "constructor_name",
            "grid_position",
            "finish_position",
            "positions_gained",
            "points_scored",
            "sprint_points",
            "round_points",
            "cumulative_points",
            "classified_status",
        ]
        if c in df_primary.columns
    ]
    st.dataframe(df_primary[cols], width="stretch", hide_index=True)

    sprint_res = profile.get("sprint_results")
    if sprint_res:
        st.markdown("**OFFICIAL SPRINT RACE PERFORMANCES**")
        sprint_cols = ["round_number", "event_name", "constructor_name", "grid_position", "finish_position", "points_scored", "classified_status"]
        s_df = pd.DataFrame(sprint_res)
        valid_s_cols = [c for c in sprint_cols if c in s_df.columns]
        st.dataframe(s_df[valid_s_cols], width="stretch", hide_index=True)
