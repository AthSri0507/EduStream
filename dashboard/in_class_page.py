"""In class (docs/UI_DESIGN.md §4): the landing when no class is running, the live notes when one is.

Landing: "Join a live class" (the recorder form), "Upload a lecture recording" (coming soon: see §3) and the recent
lectures, each opening in Revise. Live: the recorder bar with Stop class (when this laptop records), then the notes
and the assistant in the chosen layout. A class counts as running while this laptop's recorder is starting,
recording or stopping, or while a lecture is still storing new notes (a recording played from a file, for example).
"""

from __future__ import annotations

import sqlite3
import time

import pandas as pd
import streamlit as st

from dashboard import live_panel, notebook_page, status
from dashboard.notebook_html import duration
from storage.db import connect_readonly, db_path

RECENT = 5
UPLOAD_NOTE = ("Today a recording plays through EduStream in real time, so a one-hour lecture would take about an "
               "hour. Upload arrives together with faster playback.")


def running_lecture() -> dict | None:
    """The lecture being written now (status.lecture_state: unfinished and storing in the last 30 minutes)."""
    if not db_path().exists():
        return None
    try:
        conn = connect_readonly(db_path())
        try:
            lecture = status.lecture_state(conn, int(time.time() * 1000))
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return lecture if lecture and lecture["live"] else None


def recent_lectures(all_lectures: pd.DataFrame) -> None:
    st.subheader("Recent lectures")
    if all_lectures.empty:
        st.caption("Your lectures appear here after your first class.")
        return
    for _, row in all_lectures.sort_values("session_start", ascending=False).head(RECENT).iterrows():
        with st.container(horizontal=True, vertical_alignment="center", border=True):
            st.markdown(f"**{row['title']}**  \n:gray[{'Finished' if row['status'] == 'finished' else 'Not finished'}"
                        f", {row['chunks_stored'] * 10 // 60} min recorded]")
            if st.button("Open in Revise", key=f"open_{row['video_id']}", icon=":material/menu_book:"):
                st.session_state["open_lecture"] = row["video_id"]   # Revise selects it
                st.switch_page("app_pages/revise.py")              # not in a callback: pages exist only after
                                                                    # st.navigation has run


def landing() -> None:
    done = live_panel.finished_banner()
    if done:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.success(f"Class finished: {done}. Your notes are ready.", icon=":material/check_circle:")
    join, upload = st.columns(2, gap="medium")
    with join, st.container(border=True, height="stretch"):
        st.subheader("Join a live class")
        live_panel.join_form()
    with upload, st.container(border=True, height="stretch"):
        st.subheader("Upload a lecture recording")
        st.badge("Coming soon", icon=":material/schedule:", color="gray")
        st.write(UPLOAD_NOTE)
    recent_lectures(notebook_page.lectures())


def page() -> None:
    if not db_path().exists():                            # app.lecture_watch says EduStream is not running yet
        return
    recorder = live_panel.live_phase()
    lecture = running_lecture()
    if recorder in ("starting", "recording", "stopping") or lecture:
        live_panel.recorder_bar()
        if lecture:
            notebook_page.notes_and_assistant(lecture["video_id"], lecture["title"])
        return
    st.session_state["live_phase"] = recorder             # the recorder bar compares against this
    landing()
