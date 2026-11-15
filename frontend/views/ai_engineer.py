"""05 // AI RACE ENGINEER — Retro Terminal Interface to RaceIntel RAG & SQL Pipeline."""

from __future__ import annotations

import html
import streamlit as st

from frontend.api_client import RaceIntelAPIClient
from frontend.theme import (
    render_error_box,
    render_notice_box,
    render_section_title,
)

SEASON_QUERIES: dict[int, list[str]] = {
    2022: [
        "Who won the 2022 Drivers Championship?",
        "How many races did Max Verstappen win in 2022?",
        "Compare Charles Leclerc and Max Verstappen in 2022.",
        "Show the 2022 Constructor Championship standings.",
        "Who won the 2022 Monaco Grand Prix?",
        "What happened in the 2022 British Grand Prix at Silverstone?",
    ],
    2023: [
        "Who won the 2023 Drivers Championship?",
        "How many points did Red Bull score in 2023?",
        "Compare Fernando Alonso and Lewis Hamilton in 2023.",
        "Who won the 2023 Singapore Grand Prix?",
        "What was the fastest lap in the 2023 Italian Grand Prix?",
        "Show the 2023 Constructor Championship standings.",
    ],
    2024: [
        "Who won the 2024 British Grand Prix?",
        "Show the 2024 Constructor Championship standings after Abu Dhabi.",
        "Compare Max Verstappen and Lando Norris in 2024.",
        "Who retired from the 2024 Australian Grand Prix?",
        "What was the fastest lap in the 2024 Italian Grand Prix?",
        "Who finished on the podium in Monaco 2024?",
    ],
    2025: [
        "Who won the 2025 Drivers Championship?",
        "How did Lewis Hamilton perform for Ferrari in 2025?",
        "Compare Lando Norris and Charles Leclerc in 2025.",
        "Show the 2025 Constructor Championship standings.",
        "Who won the 2025 Australian Grand Prix?",
        "What were the podium finishes in Monaco 2025?",
    ],
    2026: [
        "Which constructors are competing in the 2026 season?",
        "Who are the new drivers entered for 2026?",
        "Show the 2026 F1 race calendar and completed sessions.",
        "Compare Cadillac and Sauber in 2026.",
        "Who leads the 2026 championship standings?",
        "What are the completed race results for 2026?",
    ],
}


def _render_message(role: str, content: str, sources: list[str] | None = None) -> None:
    is_user = role == "user"
    css_cls = "ri-chat-msg ri-chat-user" if is_user else "ri-chat-msg ri-chat-ai"
    badge = "USER // PITWALL" if is_user else "RACEINTEL ENGINE // AI"
    escaped = html.escape(content).replace("\n", "<br/>")
    src_html = ""
    if sources:
        src_items = "".join(f"<li>{html.escape(str(s))}</li>" for s in sources)
        src_html = f"<hr style='border-color:#385243;'/><small><strong>CITATIONS:</strong><ul>{src_items}</ul></small>"
    st.markdown(
        f"""
        <div class="{css_cls}">
            <div class="ri-chat-role">[ {badge} ]</div>
            <div>{escaped}</div>
            {src_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_ai_engineer_page(client: RaceIntelAPIClient, season: int = 2024) -> None:
    """Render AI Race Engineer chat view powered by FastAPI `POST /chat/`."""
    render_section_title("AI-01", f"AI RACE ENGINEER TERMINAL // SEASON {season} // SQL + RAG HYBRID CORE")

    if "ri_chat_history" not in st.session_state:
        st.session_state["ri_chat_history"] = []
    if "ri_last_chat_error" not in st.session_state:
        st.session_state["ri_last_chat_error"] = None

    top_left, top_right = st.columns([4, 1])
    with top_left:
        render_notice_box(
            f"Active Session: Season {season} :: DomainGuard -> IntentClassifier -> QueryPlanner / SQL -> Calibrated Chroma RAG -> Grounded Synthesis."
        )
    with top_right:
        if st.button("CLEAR LOG", width="stretch", key="ai_clear_btn"):
            st.session_state["ri_chat_history"] = []
            st.session_state["ri_last_chat_error"] = None
            st.rerun()

    st.markdown(f"**QUICK TELEMETRY PROMPTS ({season}):**")
    btn_cols = st.columns(3)
    queued_prompt: str | None = None
    example_queries = SEASON_QUERIES.get(season, SEASON_QUERIES[2024])
    for idx, sample in enumerate(example_queries):
        with btn_cols[idx % 3]:
            if st.button(sample, key=f"ex_q_{idx}", width="stretch"):
                queued_prompt = sample

    user_input = st.chat_input("ENTER F1 RACE CONTROL QUERY...", key="ai_chat_input")
    prompt = queued_prompt or (user_input.strip() if user_input else None)

    if prompt:
        st.session_state["ri_last_chat_error"] = None
        st.session_state["ri_chat_history"].append({"role": "user", "content": prompt, "sources": None})
        with st.spinner("EXECUTING QUERY PLANNER & EVIDENCE RETRIEVAL..."):
            resp, err = client.ask_race_engineer(prompt)
        if err:
            st.session_state["ri_last_chat_error"] = err
        elif resp:
            answer = resp.get("answer") or "No response returned by RaceIntel backend."
            sources = resp.get("sources") if isinstance(resp.get("sources"), list) else None
            st.session_state["ri_chat_history"].append({"role": "assistant", "content": answer, "sources": sources})

    if st.session_state.get("ri_last_chat_error"):
        render_error_box("AI ENGINEER QUERY FAILED", st.session_state["ri_last_chat_error"])

    history = st.session_state.get("ri_chat_history", [])
    if not history:
        render_notice_box("TERMINAL READY. Select a quick telemetry prompt above or enter a question below.")
    else:
        for msg in history:
            _render_message(msg["role"], msg["content"], msg.get("sources"))
