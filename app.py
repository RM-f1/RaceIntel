import requests
import streamlit as st


API_URL = "http://127.0.0.1:8001"


st.set_page_config(
    page_title="RaceIntel",
    page_icon="🏎️",
    layout="centered",
)

st.title("🏎️ RaceIntel")
st.caption("AI-powered Formula 1 race intelligence")


if "messages" not in st.session_state:
    st.session_state.messages = []


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


question = st.chat_input("Ask me anything about Formula 1...")


if question:
    st.session_state.messages.append(
        {"role": "user", "content": question}
    )

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing race data..."):
            try:
                response = requests.post(
                    f"{API_URL}/chat/",
                    json={"question": question},
                    timeout=120,
                )

                response.raise_for_status()

                data = response.json()
                answer = data["answer"]

                st.markdown(answer)

                st.session_state.messages.append(
                    {"role": "assistant", "content": answer}
                )

            except requests.exceptions.RequestException as e:
                st.error(f"Could not connect to RaceIntel API: {e}")

            except (KeyError, ValueError):
                st.error("The API returned an unexpected response.")