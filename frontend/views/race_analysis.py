"""02 // RACE ANALYSIS — Classification, Grid Movers, Lap Pace, Tyre Strategy & Weather."""

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


def render_race_analysis_page(client: RaceIntelAPIClient, season: int = 2024) -> None:
    """Render detailed race breakdown backed by `/analytics/race/{session_id}/full`."""
    render_section_title("RAC-01", f"RACE TELEMETRY & STRATEGY LOG // SEASON {season}")

    sessions, err = client.get_sessions(season=season)
    if err:
        render_error_box("SESSIONS LOAD ERROR", err)
        return
    if not sessions:
        render_notice_box(f"No race sessions available for season {season}.")
        return

    overview, _ = client.get_overview(season=season)
    cal_winners = {r["session_id"]: r.get("winner_code") for r in (overview or {}).get("calendar", [])}
    for r in (overview or {}).get("sprint_calendar", []):
        if r.get("session_id") and r.get("winner_code"):
            cal_winners[r["session_id"]] = r["winner_code"]

    all_sessions = [s for s in sessions if s.get("session_type") in ("Race", "Sprint")] or sessions

    session_map: dict[str, int] = {}
    completed_indices: list[int] = []
    for idx, s in enumerate(all_sessions):
        sid = int(s["session_id"])
        stype = s.get("session_type", "Race")
        stype_tag = "[SPRINT]" if stype == "Sprint" else "[GRAND PRIX]"
        winner = cal_winners.get(sid)
        status_tag = f"WINNER: {winner}" if winner else "SCHEDULED"
        label = f"R{idx + 1:02d} // {s['event_name']} {stype_tag} [{status_tag}]"
        session_map[label] = sid
        if winner:
            completed_indices.append(idx)

    labels = list(session_map.keys())
    default_idx = completed_indices[-1] if completed_indices else (len(labels) - 1 if labels else 0)
    selected_label = st.selectbox(
        "SELECT GRAND PRIX / SPRINT SESSION (DEFAULTS TO LATEST COMPLETED RACE)",
        options=labels,
        index=default_idx,
        key="race_analysis_session",
    )
    session_id = int(session_map[selected_label])

    payload, full_err = client.get_full_race_analysis(session_id)
    if full_err:
        render_error_box("RACE ANALYSIS LOAD ERROR", full_err)
        return
    if not payload:
        render_notice_box("No analytical payload returned for selected session.")
        return

    if payload.get("is_scheduled"):
        render_notice_box(payload.get("message") or "This session is scheduled or upcoming. Results are not yet recorded.")
        return

    meta = payload.get("session") or {}
    report = payload.get("report") or {}
    fl_detail = payload.get("fastest_lap_detail") or {}
    stats = report.get("statistics") or {}

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        render_kpi_card("CIRCUIT // LOCATION", meta.get("circuit_name") or "N/A", meta.get("country_name") or "")
    with k2:
        winner_card_title = "SPRINT WINNER" if meta.get("session_type") == "Sprint" else "RACE WINNER"
        render_kpi_card(winner_card_title, report.get("winner") or "N/A", f"TEAM: {report.get('top_constructor') or 'N/A'}")
    with k3:
        fl_time = fl_detail.get("formatted_lap_time") or "N/A"
        fl_drv = fl_detail.get("driver_code") or report.get("fastest_lap", {}).get("driver") or "N/A"
        render_kpi_card("FASTEST LAP", fl_time, f"DRIVER: {fl_drv} (LAP {fl_detail.get('lap_number', '-')})")
    with k4:
        render_kpi_card(
            "SESSION STATS",
            f"{stats.get('drivers', 0)} DRIVERS",
            f"WX: {stats.get('weather_samples', 0)} // COMPOUNDS: {stats.get('tyre_compounds', 0)}",
        )

    tab_res, tab_pace, tab_tyre, tab_wx = st.tabs(
        ["[01] CLASSIFICATION & MOVERS", "[02] LAP PACE", "[03] TYRE STRATEGY", "[04] WEATHER"]
    )

    with tab_res:
        pos_df = pd.DataFrame(payload.get("position_changes") or [])
        cls_df = pd.DataFrame(payload.get("driver_classification") or [])
        con_df = pd.DataFrame(payload.get("constructor_points") or [])

        c_left, c_right = st.columns([3, 2])
        with c_left:
            if not pos_df.empty and "positions_gained" in pos_df.columns:
                chart_df = pos_df.dropna(subset=["positions_gained"]).copy()
                movers_chart = (
                    alt.Chart(chart_df)
                    .mark_bar(stroke=FG_LIGHT, strokeWidth=1)
                    .encode(
                        x=alt.X("positions_gained:Q", title="POSITIONS GAINED / LOST (GRID -> FINISH)"),
                        y=alt.Y("driver_code:N", sort="-x", title="DRIVER"),
                        color=alt.condition(
                            alt.datum.positions_gained >= 0,
                            alt.value(FG_PRIMARY),
                            alt.value(BG_SECONDARY),
                        ),
                        tooltip=["driver_full_name:N", "grid_position:Q", "finish_position:Q", "positions_gained:Q", "classified_status:N"],
                    )
                )
                st.altair_chart(style_altair_chart(movers_chart, height=400, title="GRID-TO-FINISH DELTA"), width="stretch")
            else:
                render_notice_box("Position change data unavailable for this session.")

        with c_right:
            if not con_df.empty:
                st.markdown("**CONSTRUCTOR POINTS SCORED**")
                st.dataframe(con_df, width="stretch", hide_index=True)

        if not cls_df.empty:
            cls_title = "**FULL SPRINT CLASSIFICATION**" if meta.get("session_type") == "Sprint" else "**FULL RACE CLASSIFICATION**"
            st.markdown(cls_title)
            if not pos_df.empty and "grid_position" in pos_df.columns:
                merged = cls_df.merge(
                    pos_df[["driver_code", "grid_position", "positions_gained", "classified_status"]].drop_duplicates("driver_code"),
                    on="driver_code",
                    how="left",
                )
                cols = [c for c in ["finish_position", "grid_position", "positions_gained", "driver_code", "driver_full_name", "constructor_name", "points_scored", "classified_status"] if c in merged.columns]
                st.dataframe(merged[cols], width="stretch", hide_index=True)
            else:
                st.dataframe(cls_df, width="stretch", hide_index=True)

    with tab_pace:
        pace_block = payload.get("pace", {})
        fl_df = pd.DataFrame(pace_block.get("fastest_laps") or [])
        avg_df = pd.DataFrame(pace_block.get("average_pace") or [])
        con_df = pd.DataFrame(pace_block.get("consistency") or [])

        p1, p2 = st.columns(2)
        with p1:
            if not fl_df.empty:
                min_t = max(0.0, float(fl_df["fastest_lap_seconds"].min()) - 1.0)
                max_t = float(fl_df["fastest_lap_seconds"].max()) + 0.5
                fl_chart = (
                    alt.Chart(fl_df)
                    .mark_bar(color=FG_PRIMARY, stroke=FG_LIGHT, strokeWidth=1)
                    .encode(
                        x=alt.X("fastest_lap_seconds:Q", title="BEST LAP (SECONDS)", scale=alt.Scale(domain=[min_t, max_t])),
                        y=alt.Y("driver_code:N", sort="x", title="DRIVER"),
                        tooltip=["driver_full_name:N", "formatted_lap_time:N", "fastest_lap_seconds:Q"],
                    )
                )
                st.altair_chart(style_altair_chart(fl_chart, height=380, title="FASTEST LAP PER DRIVER"), width="stretch")
            else:
                render_notice_box("Fastest lap pace records unavailable.")

        with p2:
            if not avg_df.empty:
                min_a = max(0.0, float(avg_df["average_lap_time_seconds"].min()) - 1.0)
                max_a = float(avg_df["average_lap_time_seconds"].max()) + 0.5
                avg_chart = (
                    alt.Chart(avg_df)
                    .mark_bar(color=BG_SECONDARY, stroke=FG_PRIMARY, strokeWidth=1)
                    .encode(
                        x=alt.X("average_lap_time_seconds:Q", title="AVG LAP TIME (SECONDS)", scale=alt.Scale(domain=[min_a, max_a])),
                        y=alt.Y("driver_code:N", sort="x", title="DRIVER"),
                        tooltip=["driver_full_name:N", "average_lap_time_seconds:Q"],
                    )
                )
                st.altair_chart(style_altair_chart(avg_chart, height=380, title="AVERAGE RACE PACE"), width="stretch")
            else:
                render_notice_box("Average lap pace records unavailable.")

        if not con_df.empty:
            st.markdown("**LAP-TIME CONSISTENCY (LOWER STD DEV = STEADIER PACE)**")
            st.dataframe(con_df, width="stretch", hide_index=True)

        render_notice_box(
            "DATA SCOPE NOTE: RaceIntel SQLite stores lap times, sector splits, and tyre compound/age metadata. "
            "High-frequency car telemetry streams (speed trace, throttle/brake traces, RPM) are not stored and are never fabricated."
        )

    with tab_tyre:
        tyre_block = payload.get("tyres", {})
        usage_df = pd.DataFrame(tyre_block.get("usage") or [])
        comp_df = pd.DataFrame(tyre_block.get("compound_performance") or [])
        stint_df = pd.DataFrame(tyre_block.get("stint_summary") or [])

        t1, t2 = st.columns([3, 2])
        with t1:
            if not usage_df.empty:
                tyre_chart = (
                    alt.Chart(usage_df)
                    .mark_bar(stroke="#17251D", strokeWidth=1)
                    .encode(
                        x=alt.X("laps_completed:Q", title="LAPS COMPLETED", stack="zero"),
                        y=alt.Y("driver_code:N", title="DRIVER"),
                        color=alt.Color(
                            "tyre_compound:N",
                            title="COMPOUND",
                            scale=alt.Scale(range=RETRO_SERIES_PALETTE),
                        ),
                        tooltip=["driver_full_name:N", "tyre_compound:N", "laps_completed:Q"],
                    )
                )
                st.altair_chart(style_altair_chart(tyre_chart, height=400, title="TYRE COMPOUND DISTRIBUTION BY DRIVER"), width="stretch")
            else:
                render_notice_box("Tyre compound usage data unavailable.")

        with t2:
            if not comp_df.empty:
                st.markdown("**COMPOUND PACE SUMMARY**")
                st.dataframe(comp_df, width="stretch", hide_index=True)
            if not stint_df.empty:
                st.markdown("**DRIVER STINT BREAKDOWN**")
                st.dataframe(stint_df.head(30), width="stretch", hide_index=True)

    with tab_wx:
        wx_block = payload.get("weather", {})
        wx_det = wx_block.get("details") or {}
        wx_df = pd.DataFrame(wx_block.get("trend") or [])

        w1, w2, w3, w4 = st.columns(4)
        with w1:
            air = wx_det.get("average_air_temperature")
            render_kpi_card("AVG AIR TEMP", f"{air:.1f} C" if isinstance(air, (int, float)) else "N/A")
        with w2:
            trk = wx_det.get("average_track_temperature")
            render_kpi_card("AVG TRACK TEMP", f"{trk:.1f} C" if isinstance(trk, (int, float)) else "N/A")
        with w3:
            hum = wx_det.get("average_humidity")
            render_kpi_card("AVG HUMIDITY", f"{hum:.1f} %" if isinstance(hum, (int, float)) else "N/A")
        with w4:
            rain_cnt = wx_det.get("rain_observations", 0)
            wind = wx_det.get("average_wind_speed")
            render_kpi_card(
                "WIND // RAIN OBS",
                f"{wind:.2f} m/s" if isinstance(wind, (int, float)) else "N/A",
                f"WET OBSERVATIONS: {rain_cnt}",
            )

        if not wx_df.empty:
            wx_df = wx_df.reset_index().rename(columns={"index": "sample_idx"})
            melted = wx_df.melt(
                id_vars=["sample_idx", "observation_time"],
                value_vars=[c for c in ["air_temperature_celsius", "track_temperature_celsius"] if c in wx_df.columns],
                var_name="metric",
                value_name="celsius",
            )
            temp_chart = (
                alt.Chart(melted)
                .mark_line(strokeWidth=2.2)
                .encode(
                    x=alt.X("sample_idx:Q", title="OBSERVATION SAMPLE SEQUENCE"),
                    y=alt.Y("celsius:Q", title="TEMPERATURE (C)"),
                    color=alt.Color("metric:N", title="SENSOR", scale=alt.Scale(range=[FG_PRIMARY, FG_LIGHT])),
                    tooltip=["observation_time:N", "metric:N", "celsius:Q"],
                )
            )
            st.altair_chart(style_altair_chart(temp_chart, height=300, title="AIR & TRACK TEMPERATURE PROFILE"), width="stretch")

            if "wind_speed_mps" in wx_df.columns and wx_df["wind_speed_mps"].notna().any():
                wind_chart = (
                    alt.Chart(wx_df)
                    .mark_area(color=BG_SECONDARY, opacity=0.35, line={"color": FG_PRIMARY, "strokeWidth": 2})
                    .encode(
                        x=alt.X("sample_idx:Q", title="OBSERVATION SAMPLE SEQUENCE"),
                        y=alt.Y("wind_speed_mps:Q", title="WIND SPEED (M/S)"),
                        tooltip=["observation_time:N", "wind_speed_mps:Q"],
                    )
                )
                st.altair_chart(style_altair_chart(wind_chart, height=220, title="WIND SPEED PROFILE"), width="stretch")
        else:
            render_notice_box("Weather time-series observations unavailable for this session.")
