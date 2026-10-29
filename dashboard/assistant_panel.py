"""The Lecture Assistant's panel in the dashboard (ARCHITECTURE §8.2, §8.3): a plain chat, like any LLM chat.

The user types everything ("I didn't get the last 10 seconds", "explain that more simply", "what happened at
12:30?"); there are no buttons in the chat (your decision, 15 Oct). One switch above it chooses the source (28 Oct):
the lecture only (default), or the lecture plus general knowledge, always labelled as not from the lecture. Streamlit re-runs the script on every interaction, and
a re-run aborts whatever the old run was doing (step 0, bench/STEP0_RESULTS.md §3), so a turn never runs in the
script: it runs in a background thread that writes into a job dict kept in session_state, and this panel (its
own fragment, polled every second) shows the job's progress and then the verified answer.
"""

from __future__ import annotations

import html
import threading
import time
from dataclasses import replace

import streamlit as st

from agents import assistant as A
from agents import embeddings
from agents import lecture_tools as tools
from agents import llm
from agents.text import mmss
from common.log import JsonLog
from storage import indexer
from storage.db import connect_readonly

WAIT_FOR_TRANSCRIPT_S = 45          # a moment is transcribed about 12-15 s after it was said


@st.cache_resource
def _shared() -> dict:
    """One LLM client (one token budget) and one log for the whole dashboard process."""
    log = JsonLog("assistant")
    return {"client": llm.Client("assistant", log=log), "log": log}


def _state() -> dict:
    s = st.session_state
    s.setdefault("a_turns", [])         # [{role, text, answer}]
    s.setdefault("a_job", None)         # the running job, if any
    s.setdefault("a_explained", [])
    s.setdefault("a_outside", False)    # the switch: general knowledge allowed
    return s


def _position(conn, video_id: str) -> A.Position | None:
    """Live lecture: "now" is the lecture's own clock. Recorded: the end (times in the message pick a moment)."""
    info = tools.lecture_info(conn, video_id)
    if info is None:
        return None
    if info["finished"]:
        return A.Position(video_id, info["title"], False, info["covered_s"], info["covered_s"])
    clock = (time.time() * 1000 - info["session_start"]) / 1000 * info["speedup"]
    return A.Position(video_id, info["title"], True, max(0.0, clock), info["covered_s"])


def _run_job(job: dict, video_id: str, msg: str, turns: list, explained: list, outside: bool = False) -> None:
    shared = _shared()
    try:
        conn = connect_readonly()
        try:
            pos = _position(conn, video_id)
            if pos is None:
                job.update(done=True, error="The lecture is not in the database yet.")
                return
            # A live moment is transcribed 12-15 s after it is said: wait for it rather than answer from nothing.
            if pos.live:
                deadline = time.time() + WAIT_FOR_TRANSCRIPT_S
                while pos.covered_s < pos.ref - 12 and time.time() < deadline:
                    job["status"] = "catching up with the lecture…"
                    time.sleep(1.0)
                    pos = replace(pos, covered_s=tools.lecture_info(conn, video_id)["covered_s"])
            job["status"] = "thinking…"
            vconn = indexer.connect_readonly()          # None until the indexer has written anything
            try:
                answer = A.run_turn(conn, shared["client"], msg, turns, pos, explained=explained, vconn=vconn,
                                    embedder=embeddings.get(), outside=outside)
            finally:
                if vconn is not None:
                    vconn.close()
            job.update(done=True, answer=answer)
            shared["log"].info("turn", video_id=video_id, message=msg[:200], plan=answer.plan.chip(),
                               intent=answer.plan.intent, source=answer.plan.source, generator=answer.generator,
                               model=answer.model, outside=outside, items=len(answer.items),
                               background=len(answer.background),
                               flags=answer.flags, latency_s=answer.latency_s)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - shown to the user, logged, never kills the dashboard
        job.update(done=True, error=f"Something went wrong ({type(exc).__name__}). Please ask again.")
        shared["log"].error("turn_failed", video_id=video_id, error=repr(exc))


def submit(video_id: str, msg: str) -> None:
    s = _state()
    msg = (msg or "").strip()
    if not msg or (s["a_job"] is not None and not s["a_job"].get("done")):
        return                                                   # one turn at a time
    s["a_turns"].append({"role": "user", "text": msg})
    history = [{"role": t["role"], "text": t["text"]} for t in s["a_turns"][:-1]]
    job = {"done": False, "status": "thinking…"}
    s["a_job"] = job
    threading.Thread(target=_run_job, daemon=True,
                     args=(job, video_id, msg, history, list(s["a_explained"]), bool(s["a_outside"]))).start()


TABLE_CSS = ("<style>.atab{overflow-x:auto;margin:4px 0 8px}.atab table{border-collapse:collapse;font-size:14px;"
             "min-width:100%}.atab th,.atab td{border:1px solid rgba(128,128,128,.35);padding:5px 9px;text-align:left;"
             "vertical-align:top}.atab th{font-weight:600}.atab .src{white-space:nowrap;font-family:monospace;"
             "font-size:12.5px;opacity:.8}.atab .add{opacity:.75}.atab .cap{font-weight:600;margin-bottom:4px}"
             ".atab .note{font-style:italic;font-size:13px;opacity:.8;margin-top:4px}</style>")


def table_html(table: dict) -> str:
    """The assistant's table (NOTEBOOK_DESIGN §13), as escaped HTML in a box that scrolls sideways (a markdown table
    was cut off in the narrow chat column). A cell not from the lecture carries "†" (only when the switch is on);
    the Source column gives the time where the row's subject was discussed."""
    e = html.escape
    rows = table["rows"]
    head = "".join(f"<th>{e(c)}</th>" for c in table["columns"]) + "<th>Source</th>"
    body = ""
    for r in rows:
        cells = "".join(f'<td class="add">{e(c)} †</td>' if added and c else f"<td>{e(c)}</td>"
                        for c, added in zip(r["cells"], r["added"]))
        body += f"<tr>{cells}<td class=\"src\">{mmss(r['t']) if r['t'] is not None else '—'}</td></tr>"
    added = sum(sum(r["added"]) for r in rows)
    total = sum(len(r["cells"]) for r in rows)
    note = (f"† {added} of {total} cells are general knowledge, not from the lecture." if added
            else "Everything in this table is from the lecture.")
    caption = f'<div class="cap">{e(table["caption"])}</div>' if table.get("caption") else ""
    return (f'{TABLE_CSS}<div class="atab">{caption}<table><tr>{head}</tr>{body}</table>'
            f'<div class="note">{e(note)}</div></div>')


def _render_answer(answer: A.Answer) -> None:
    source = "lecture + general knowledge" if answer.outside else "from the lecture only"
    st.caption(f"{answer.plan.chip()} · {source}")
    if answer.note and not answer.items:
        st.write(answer.note)
    for item in answer.items:
        st.markdown(f"{item['text']} `[{mmss(item['t'])}]`", help=f"Said: “{item['quote']}”")
    if answer.table:
        st.html(table_html(answer.table))
    for text in answer.background:
        st.markdown(f":gray-background[Beyond the lecture: general knowledge] {text}")
    for q in answer.questions:
        with st.expander(q["q"] + (f"  `[{mmss(q['t'])}]`" if q.get("t") is not None else "")):
            st.write(q["answer"] or "")
    if answer.stats:
        s = answer.stats
        st.markdown(f"From **{mmss(s['span'][0])}** to **{mmss(s['span'][1])}**: "
                    f"{s['words_per_min'] if s['words_per_min'] is not None else '–'} words per minute "
                    f"({s['words']} words).")
        if s["alerts"]:
            st.caption("Alerts in this lecture: " + ", ".join(f"{k} × {v}" for k, v in s["alerts"].items()))
    show_said = answer.generator == "evidence" or "no_lecture_items" in answer.flags
    if show_said and answer.evidence and answer.plan.intent != "data":
        st.caption("What was said:")
        for e in answer.evidence[:12]:
            st.markdown(f"`[{mmss(e['t'])}]` {e['text']}")


@st.fragment(run_every="1s")
def panel(video_id: str) -> None:
    s = _state()
    job = s["a_job"]
    if job is not None and job.get("done"):
        if job.get("error"):
            s["a_turns"].append({"role": "assistant", "text": job["error"], "answer": None})
        else:
            answer = job["answer"]
            s["a_turns"].append({"role": "assistant", "text": answer.as_text(), "answer": answer})
            if answer.plan.term:
                s["a_explained"] = (s["a_explained"] + [answer.plan.term])[-20:]
        s["a_job"] = job = None

    head, switch = st.columns([1, 1.3], vertical_alignment="center")
    head.markdown("**Lecture Assistant**")
    switch.toggle("Use general knowledge", key="a_outside",
                  help="Off: answers come only from what was said in this lecture. On: the assistant may add general "
                       "knowledge, always labelled as not from the lecture.")
    with st.container(height=600, border=True):
        if not s["a_turns"] and job is None:
            st.caption("Ask anything about the lecture, the way you would ask any chat assistant. For example: "
                       "“I didn't get the last 10 seconds”, “summarise the last 5 minutes”, "
                       "“what is a computer program?”, “explain that more simply”, “quiz me”.")
        for turn in s["a_turns"]:
            with st.chat_message(turn["role"]):
                if turn["role"] == "user" or turn.get("answer") is None:
                    st.write(turn["text"])
                else:
                    _render_answer(turn["answer"])
        if job is not None:
            with st.chat_message("assistant"):
                st.caption(job.get("status", "thinking…"))
    st.chat_input("Ask about the lecture", key="a_input", disabled=job is not None,
                  on_submit=lambda: submit(video_id, st.session_state.get("a_input")))
