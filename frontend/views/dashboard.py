"""01 // MAIN DASHBOARD — Season Overview, Race Snapshot & Cumulative Standings."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from frontend.api_client import RaceIntelAPIClient
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


def render_dashboard_page(client: RaceIntelAPIClient, season: int = 2024) -> None:
    """Render Main Race Control Overview dashboard backed by live API endpoints."""
    render_section_title("SYS-01", f"RACE CONTROL OVERVIEW // SEASON {season}")

    overview, err = client.get_overview(season=season)
    if err:
        render_error_box("OVERVIEW FETCH FAILED", err)
        return
    if not overview or not overview.get("calendar"):
        render_notice_box(f"No race calendar data available for season {season}.")
        return

    calendar = overview["calendar"]
    counts = overview.get("counts", {})
    latest_race = overview.get("latest_race") or calendar[-1]
    drv_leader = overview.get("driver_leader") or {}
    con_leader = overview.get("constructor_leader") or {}

    # Top KPI Console Grid
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_kpi_card(
            "RACES INDEXED",
            overview.get("total_races", len(calendar)),
            f"LAPS LOGGED: {counts.get('total_laps', 0):,}",
        )
    with c2:
        render_kpi_card(
            "LATEST GRAND PRIX",
            latest_race.get("event_name", "N/A"),
            f"WINNER: {latest_race.get('winner_code') or 'N/A'} ({latest_race.get('winner_constructor') or 'N/A'})",
        )
    with c3:
        render_kpi_card(
            "DRIVER LEADER",
            drv_leader.get("driver_code") or drv_leader.get("driver_full_name") or "N/A",
            f"{drv_leader.get('total_points', 0)} PTS // {drv_leader.get('constructor_name', '')}",
        )
    with c4:
        render_kpi_card(
            "CONSTRUCTOR LEADER",
            con_leader.get("constructor_name") or "N/A",
            f"{con_leader.get('total_points', 0)} PTS // WX SAMPLES: {counts.get('total_weather_observations', 0):,}",
        )

    # Race Checkpoint Selector
    render_section_title("CAL-02", "ROUND CHECKPOINT & CUMULATIVE CHAMPIONSHIP STATE")
    race_options = {
        f"R{idx + 1:02d} // {r['event_name']} ({r.get('winner_code') or 'SCHEDULED'})": r["session_id"]
        for idx, r in enumerate(calendar)
    }
    labels = list(race_options.keys())
    completed_indices = [idx for idx, r in enumerate(calendar) if r.get("winner_code")]
    default_idx = completed_indices[-1] if completed_indices else (len(labels) - 1 if labels else 0)

    selected_label = st.selectbox(
        "SELECT CHECKPOINT ROUND (DEFAULTS TO LATEST COMPLETED RACE)",
        options=labels,
        index=default_idx,
        key="dash_round_select",
    )
    selected_sid = int(race_options[selected_label])

    selected_race_meta = next((r for r in calendar if r["session_id"] == selected_sid), {})
    is_upcoming = not bool(selected_race_meta.get("winner_code"))

    if is_upcoming:
        render_notice_box(
            f"[STATUS: SCHEDULED // UPCOMING] {selected_race_meta.get('event_name', 'This Grand Prix')} has not "
            f"concluded yet. Classification and race telemetry will unlock once the race finishes."
        )
        race_results, rr_err = [], None
    else:
        report, rep_err = client.get_race_report(selected_sid)
        if rep_err:
            render_error_box("RACE SNAPSHOT UNAVAILABLE", rep_err)
        elif report:
            fl = report.get("fastest_lap", {})
            bm = report.get("biggest_mover", {})
            podium = report.get("podium") or []
            podium_str = " > ".join(podium) if podium else "N/A"
            s1, s2, s3 = st.columns(3)
            with s1:
                render_kpi_card("RACE PODIUM [P1 > P2 > P3]", podium_str, f"TOP TEAM: {report.get('top_constructor', 'N/A')}")
            with s2:
                fl_sec = fl.get("seconds")
                fl_txt = f"{fl_sec:.3f}s" if isinstance(fl_sec, (int, float)) else "N/A"
                render_kpi_card("FASTEST LAP", fl.get("driver", "N/A"), f"TIME: {fl_txt}")
            with s3:
                pos_delta = bm.get("positions")
                delta_txt = f"+{pos_delta} POS" if isinstance(pos_delta, (int, float)) else "N/A"
                render_kpi_card("BIGGEST MOVER", bm.get("driver", "N/A"), f"NET GAIN: {delta_txt}")

        race_results, rr_err = client.get_race_driver_standings(selected_sid)

    season_drv, sd_err = client.get_season_driver_standings(selected_sid, season=season)
    season_con, sc_err = client.get_season_constructor_standings(selected_sid, season=season)

    # Cumulative Championship Standings Panels
    left, right = st.columns(2)
    with left:
        st.markdown("**CUMULATIVE DRIVERS CHAMPIONSHIP (TOP 10)**")
        if sd_err:
            render_error_box("DRIVER STANDINGS ERROR", sd_err)
        elif season_drv:
            drv_df = pd.DataFrame(season_drv).head(10)
            chart = (
                alt.Chart(drv_df)
                .mark_bar(color=FG_PRIMARY, stroke=FG_LIGHT, strokeWidth=1)
                .encode(
                    x=alt.X("total_points:Q", title="TOTAL POINTS"),
                    y=alt.Y("driver_code:N", sort="-x", title="DRIVER"),
                    tooltip=["rank:Q", "driver_full_name:N", "constructor_name:N", "total_points:Q", "best_finish:Q"],
                )
            )
            st.altair_chart(style_altair_chart(chart, height=300), width="stretch")
            st.dataframe(
                drv_df[["rank", "driver_code", "driver_full_name", "constructor_name", "total_points", "best_finish"]],
                width="stretch",
                hide_index=True,
            )

    with right:
        st.markdown("**CUMULATIVE CONSTRUCTORS CHAMPIONSHIP**")
        if sc_err:
            render_error_box("CONSTRUCTOR STANDINGS ERROR", sc_err)
        elif season_con:
            con_df = pd.DataFrame(season_con)
            chart = (
                alt.Chart(con_df)
                .mark_bar(color=BG_SECONDARY, stroke=FG_PRIMARY, strokeWidth=1.5)
                .encode(
                    x=alt.X("total_points:Q", title="TOTAL POINTS"),
                    y=alt.Y("constructor_name:N", sort="-x", title="CONSTRUCTOR"),
                    tooltip=["rank:Q", "constructor_name:N", "total_points:Q", "best_finish:Q"],
                )
            )
            st.altair_chart(style_altair_chart(chart, height=300), width="stretch")
            st.dataframe(
                con_df[["rank", "constructor_name", "total_points", "best_finish"]],
                width="stretch",
                hide_index=True,
            )

    # Top-5 Constructor Trajectory + Selected Race Top-10 Classification
    render_section_title("TRK-03", f"SEASON POINTS TRAJECTORY & CHECKPOINT RACE TOP 10")
    t_left, t_right = st.columns([3, 2])
    with t_left:
        prog, prog_err = client.get_standings_progression(season=season)
        if prog_err:
            render_error_box("PROGRESSION UNAVAILABLE", prog_err)
        elif prog and prog.get("constructors"):
            prog_df = pd.DataFrame(prog["constructors"])
            if season_con:
                top5_names = [row["constructor_name"] for row in season_con[:5]]
                prog_df = prog_df[prog_df["constructor_name"].isin(top5_names)]
            line = (
                alt.Chart(prog_df)
                .mark_line(point=True, strokeWidth=2.2)
                .encode(
                    x=alt.X("round_index:Q", title="ROUND NUMBER"),
                    y=alt.Y("cumulative_points:Q", title="CUMULATIVE PTS"),
                    color=alt.Color(
                        "constructor_name:N",
                        title="CONSTRUCTOR",
                        scale=alt.Scale(range=RETRO_SERIES_PALETTE),
                    ),
                    tooltip=["round_index:Q", "event_name:N", "constructor_name:N", "points_scored:Q", "cumulative_points:Q"],
                )
            )
            st.altair_chart(style_altair_chart(line, height=300, title="TOP-5 CONSTRUCTORS CUMULATIVE POINTS"), width="stretch")

    with t_right:
        if is_upcoming:
            render_notice_box("Selected round has not concluded yet. Classification will appear once race concludes.")
        elif rr_err:
            render_error_box("RACE CLASSIFICATION UNAVAILABLE", rr_err)
        elif race_results:
            st.markdown("**SELECTED RACE TOP-10 FINISHERS**")
            rr_df = pd.DataFrame(race_results).head(10)
            st.dataframe(
                rr_df[["finish_position", "driver_code", "constructor_name", "points_scored"]],
                width="stretch",
                hide_index=True,
            )

    # Full Season Race Winners Log
    render_section_title("LOG-04", f"{season} RACE WINNERS MATRIX")
    cal_df = pd.DataFrame(calendar)
    cal_df.insert(0, "round", range(1, len(cal_df) + 1))
    display_cols = [c for c in ["round", "event_name", "country_name", "circuit_name", "winner_code", "winner_name", "winner_constructor"] if c in cal_df.columns]
    st.dataframe(cal_df[display_cols], width="stretch", hide_index=True)
