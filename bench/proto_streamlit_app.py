"""Step-0 prototype 3, the app under test (ARCHITECTURE §12 item 13). Driven by bench/proto_streamlit_check.py.

A fake 3 s "LLM" is called two ways while a fragment auto-refreshes every 2 s (like the notebook):
  threaded: started in a background thread from the assistant's own fragment; the fragment polls the
            shared job dict and shows the text as it streams in;
  inline:   called directly inside a button handler (the naive way).
"""

import threading
import time

import streamlit as st

st.title("Streamlit execution-model check")
jobs = st.session_state.setdefault("jobs", {})
WORDS = "this is a streamed answer from a fake model that takes three seconds to finish".split()


@st.fragment(run_every="2s")
def notebook():
    st.caption(f"notebook auto-refresh at {time.strftime('%H:%M:%S')}")


notebook()


def fake_llm(job: dict) -> None:
    for word in WORDS:
        time.sleep(3 / len(WORDS))
        job["text"] += word + " "
    job["done"] = True


@st.fragment(run_every="0.5s")
def assistant():
    if st.button("Ask (threaded)", key="ask_threaded"):
        job = {"text": "", "done": False}
        jobs["threaded"] = job
        threading.Thread(target=fake_llm, args=(job,), daemon=True).start()
    job = jobs.get("threaded")
    if job:
        st.markdown(f"THREADED-TEXT: {job['text']}")
        if job["done"]:
            st.markdown("THREADED-DONE")


assistant()

if st.button("Ask (inline)", key="ask_inline"):
    text = ""
    for word in WORDS:
        time.sleep(3 / len(WORDS))
        text += word + " "
    st.session_state["inline"] = "INLINE-DONE"
st.markdown(st.session_state.get("inline", "inline: no answer yet"))
st.checkbox("another widget", key="other")
