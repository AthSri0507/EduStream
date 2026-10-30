"""The Lecture Assistant's panel in the dashboard (ARCHITECTURE §8.2, §8.3): a plain chat, like any LLM chat.

The user types everything ("I didn't get the last 10 seconds", "explain that more simply", "what happened at
12:30?"); there are no buttons in the chat (your decision, 15 Oct). One switch above it chooses the source (28 Oct):
the lecture only (default), or the lecture plus general knowledge, always labelled as not from the lecture.

A figure (table, worked steps, flowchart, concept map, timeline: NOTEBOOK_DESIGN §13) is followed by an offer, "Add
this to your notes under …?". The next message is read by code first (agents/additions.py): yes / no / "yes, under
topic 2". Yes produces an addition.v1 record to user_notes (the sink stores it; the dashboard never writes SQLite). A
saved addition can be redrawn from the notebook page in one click (its question asked again, the new figure in its
place). Streamlit re-runs the script on every interaction, and
a re-run aborts whatever the old run was doing (step 0, bench/STEP0_RESULTS.md §3), so a turn never runs in the
script: it runs in a background thread that writes into a job dict kept in session_state, and this panel (its
own fragment, polled every second) shows the job's progress and then the verified answer.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import streamlit as st

from agents import assistant as A
from agents import embeddings
from agents import lecture_tools as tools
from agents import additions, figures, llm
from agents.text import mmss
from common import schemas
from common.config import TOPIC_USER_NOTES, load
from common.kafka_utils import make_producer, send_and_wait
from common.log import JsonLog
from common.partitioning import partition_for
from dashboard import figure_draw
from storage import indexer
from dashboard import queries
from storage.db import connect_readonly

WAIT_FOR_TRANSCRIPT_S = 45          # a moment is transcribed about 12-15 s after it was said


@st.cache_resource
def _shared() -> dict:
    """One LLM client (one token budget) and one log for the whole dashboard process."""
    log = JsonLog("assistant")
    return {"client": llm.Client("assistant", log=log), "log": log}


@st.cache_resource
def _producer():
    """One Kafka producer for the dashboard process, made on first use (additions only)."""
    return make_producer(load(), client_id="dashboard")


def _state() -> dict:
    s = st.session_state
    s.setdefault("a_turns", [])         # [{role, text, answer}]
    s.setdefault("a_job", None)         # the running job, if any
    s.setdefault("a_explained", [])
    s.setdefault("a_outside", False)    # the switch: general knowledge allowed
    s.setdefault("a_offer", None)       # a figure the student may add to the notes (§13.3)
    s.setdefault("a_redraw", {})        # addition_id -> its running redraw job
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


def _ask(conn, job: dict, video_id: str, msg: str, turns: list, explained: list, outside: bool) -> A.Answer | None:
    """One assistant turn; None (and the job done with an error) when the lecture is not in the database yet."""
    pos = _position(conn, video_id)
    if pos is None:
        job.update(done=True, error="The lecture is not in the database yet.")
        return None
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
        return A.run_turn(conn, _shared()["client"], msg, turns, pos, explained=explained, vconn=vconn,
                          embedder=embeddings.get(), outside=outside)
    finally:
        if vconn is not None:
            vconn.close()


def _send(video_id: str, payload: dict) -> None:
    """One addition.v1 record to user_notes (raises ProduceFailed when Kafka is unreachable)."""
    send_and_wait(_producer(), TOPIC_USER_NOTES, schemas.encode("addition.v1", payload), key=video_id,
                  partition=partition_for(video_id, load().partitions))


def _run_job(job: dict, video_id: str, msg: str, turns: list, explained: list, outside: bool = False) -> None:
    shared = _shared()
    try:
        conn = connect_readonly()
        try:
            answer = _ask(conn, job, video_id, msg, turns, explained, outside)
            if answer is None:
                return
            if answer.figure:                           # where it would go in the notes, for the offer
                nb = queries.notebook(conn, video_id)
                span = additions.span_of(answer.plan.span, answer.evidence)
                draft = {"figure": answer.figure, "span": span, "question": msg, "topic_override": None}
                placement = additions.place(draft, nb["topics"], nb["since"], nb["finished"])
                job["offer"] = {**draft, "video_id": video_id, "outside": outside, "model": answer.model,
                                "text": additions.offer_text(answer.figure, placement, nb["topics"])}
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


def _answer_offer(offer: dict, decision: str, topic: int | None) -> str:
    """Yes: produce the addition (the sink stores it). The reply says where it went, or why it could not be saved."""
    if decision == "no":
        return "OK, not added to your notes."
    conn = connect_readonly()
    try:
        nb = queries.notebook(conn, offer["video_id"])
    finally:
        conn.close()
    known = {t["n"] for t in nb["topics"]}
    note = ""
    if topic is not None and topic not in known:
        note = f" (there is no topic {topic} yet)"
        topic = None
    payload = additions.payload_add(offer["video_id"], offer["figure"], offer["span"], offer["question"],
                                    offer["outside"], offer["model"], topic)
    try:
        _send(offer["video_id"], payload)
    except Exception as exc:  # noqa: BLE001 - Kafka unreachable (ProduceFailed) or anything else: shown, never fatal
        _shared()["log"].error("addition_failed", video_id=offer["video_id"], error=repr(exc))
        return "I couldn't save it: the pipeline isn't reachable right now. It's still here in the chat."
    placement = additions.place(payload, nb["topics"], nb["since"], nb["finished"])
    _shared()["log"].info("addition_saved", video_id=offer["video_id"], addition_id=payload["addition_id"],
                          shape=offer["figure"]["shape"], placement=placement)
    return f"Added to your notes {additions.describe(placement, nb['topics'])}{note}."


def remove_addition(video_id: str, addition_id: str) -> None:
    """The ✕ on the notebook page: a removal record (the sink marks the addition removed; nothing is deleted)."""
    try:
        _send(video_id, additions.payload_remove(video_id, addition_id))
        st.toast("Removed from your notes.")
    except Exception as exc:  # noqa: BLE001 - Kafka unreachable: shown, never fatal
        _shared()["log"].error("addition_remove_failed", video_id=video_id, error=repr(exc))
        st.toast("Couldn't remove it: the pipeline isn't reachable right now.")


def redraw_addition(video_id: str, addition: dict) -> None:
    """The ↻ on the notebook page: the saved question is asked again (with its own switch setting, not the current
    one) and the new figure takes the old one's place. No chat and no second offer: the student already said yes.
    The new one is saved first and keeps the old span, topic and order; the old one is removed only after that, so a
    failure at any point leaves the saved version in the notes. Runs in a thread, like a chat turn."""
    jobs = _state()["a_redraw"]
    if addition["addition_id"] in jobs:
        return
    job = {"done": False, "status": "thinking…"}
    jobs[addition["addition_id"]] = job
    threading.Thread(target=_run_redraw, daemon=True, args=(job, video_id, addition)).start()


def _run_redraw(job: dict, video_id: str, addition: dict) -> None:
    shared = _shared()
    old = addition["figure"]
    try:
        conn = connect_readonly()
        try:
            answer = _ask(conn, job, video_id, addition["question"], [], [], addition["outside"])
        finally:
            conn.close()
        if answer is None:
            return
        if not answer.figure:
            job.update(done=True, error="I couldn't redraw it this time, so your saved version stays. Try again later.")
            return
        payload = additions.payload_add(video_id, answer.figure, addition["span"], addition["question"],
                                        addition["outside"], answer.model, addition.get("topic_override"),
                                        now_ms=addition.get("created_ts"))
        _send(video_id, payload)
        _send(video_id, additions.payload_remove(video_id, addition["addition_id"]))
        job.update(done=True, text=f"Redrawn as a {figures.NAME[answer.figure['shape']]}.")
        shared["log"].info("addition_redrawn", video_id=video_id, old_id=addition["addition_id"],
                           new_id=payload["addition_id"], old_shape=old["shape"], shape=answer.figure["shape"],
                           model=answer.model, flags=answer.flags)
    except Exception as exc:  # noqa: BLE001 - Kafka unreachable or anything else: shown, never fatal
        job.update(done=True, error="I couldn't redraw it: the pipeline isn't reachable right now. Your saved version "
                                    "stays.")
        shared["log"].error("addition_redraw_failed", video_id=video_id, error=repr(exc))


def redraw_state(addition_id: str) -> str | None:
    """"running" while that addition is being redrawn, else None."""
    job = _state()["a_redraw"].get(addition_id)
    return "running" if job is not None and not job.get("done") else None


def redraw_notices() -> None:
    """Toasts for finished redraws (called from the notebook's own refresh)."""
    jobs = _state()["a_redraw"]
    for addition_id in [k for k, j in jobs.items() if j.get("done")]:
        job = jobs.pop(addition_id)
        st.toast(job.get("text") or job.get("error") or "Done.")


def submit(video_id: str, msg: str) -> None:
    s = _state()
    msg = (msg or "").strip()
    if not msg or (s["a_job"] is not None and not s["a_job"].get("done")):
        return                                                   # one turn at a time
    offer = s["a_offer"]
    reply = additions.read_reply(msg) if offer and offer["video_id"] == video_id else None
    if reply is not None:                                        # an answer to the offer, read by code (§13.3)
        s["a_turns"].append({"role": "user", "text": msg})
        s["a_turns"].append({"role": "assistant", "text": _answer_offer(offer, *reply), "answer": None})
        s["a_offer"] = None
        return
    s["a_turns"].append({"role": "user", "text": msg})
    history = [{"role": t["role"], "text": t["text"]} for t in s["a_turns"][:-1]]
    job = {"done": False, "status": "thinking…"}
    s["a_job"] = job
    threading.Thread(target=_run_job, daemon=True,
                     args=(job, video_id, msg, history, list(s["a_explained"]), bool(s["a_outside"]))).start()


def render_figure(figure: dict) -> None:
    """A figure from the assistant (NOTEBOOK_DESIGN §13): drawings as images, the rest as escaped HTML."""
    if figure_draw.is_drawing(figure):
        st.image(figure_draw.draw_png(figure, _theme()), caption=figure_draw.caption(figure))
    else:
        st.html(figure_draw.figure_html(figure))


def _theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # noqa: BLE001 - older/unknown theme info
        return "light"


SHORT_ITEMS = 2                       # an answer shows its first two points; the rest behind "Show more"


def _item(item: dict) -> None:
    st.markdown(f"{item['text']} :gray-background[{mmss(item['t'])}]", help=f"Said: “{item['quote']}”")


def _render_answer(answer: A.Answer) -> None:
    """The short answer first (summary and first points), the rest behind Show more, the lecture's own words folded
    (docs/UI_DESIGN.md §5)."""
    source = "lecture and general knowledge" if answer.outside else "from the lecture only"
    st.caption(f"{answer.plan.chip()}, {source}")
    if answer.note and (not answer.items or (answer.plan.shape and not answer.figure)):
        st.write(answer.note)
    for item in answer.items[:SHORT_ITEMS]:
        _item(item)
    if answer.figure:
        render_figure(answer.figure)
    for q in answer.questions:
        with st.expander(q["q"] + (f"  :gray-background[{mmss(q['t'])}]" if q.get("t") is not None else "")):
            st.write(q["answer"] or "")
    if answer.stats:
        s = answer.stats
        st.markdown(f"From **{mmss(s['span'][0])}** to **{mmss(s['span'][1])}**: "
                    f"{s['words_per_min'] if s['words_per_min'] is not None else '–'} words per minute "
                    f"({s['words']} words).")
        if s["alerts"]:
            st.caption("Alerts in this lecture: " + ", ".join(f"{k} × {v}" for k, v in s["alerts"].items()))
    rest = answer.items[SHORT_ITEMS:]
    if rest or answer.background:
        with st.expander(f"Show more ({len(rest)} more points)" if rest else "Show more"):
            for item in rest:
                _item(item)
            for text in answer.background:
                st.markdown(f":gray-background[Beyond the lecture: general knowledge] {text}")
    show_said = answer.generator == "evidence" or "no_lecture_items" in answer.flags
    if show_said and answer.evidence and answer.plan.intent != "data":
        with st.expander(f"What the lecturer said ({min(len(answer.evidence), 12)})"):
            for e in answer.evidence[:12]:
                st.markdown(f":gray-background[{mmss(e['t'])}] {e['text']}")


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
            if job.get("offer"):                                 # the offer replaces an older one
                s["a_offer"] = job["offer"]
                s["a_turns"].append({"role": "assistant", "text": job["offer"]["text"], "answer": None})
            if answer.plan.term:
                s["a_explained"] = (s["a_explained"] + [answer.plan.term])[-20:]
        s["a_job"] = job = None

    with st.container(key="assistant", border=True):          # a raised card; text at the notes' size (theme.py)
        with st.container(horizontal=True, vertical_alignment="center", horizontal_alignment="distribute"):
            st.markdown("**Lecture assistant**", width="content")
            st.toggle("General knowledge", key="a_outside", width="content",
                      help="Off: answers come only from what was said in this lecture. On: the assistant may add "
                           "general knowledge, always labelled as not from the lecture.")
        talking = bool(s["a_turns"]) or job is not None
        with st.container(height=600 if talking else "content", border=False):
            if not talking:
                st.caption("Ask anything about the lecture, the way you would ask any chat assistant: "
                           "“I missed the last 2 minutes”, “explain that more simply”, “quiz me”.")
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
