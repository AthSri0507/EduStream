"""The notes and the Lecture assistant, as used by the In class live view and by Revise (docs/UI_DESIGN.md §5).

A toolbar sets the layout: notes only, notes and assistant (default; the assistant about 440 px wide) or assistant
wide, plus the contents and glossary block and the Export menu. Changing the layout reruns the page; an answer in
progress is not lost, because it runs in a background thread and the assistant fragment picks it up again. The notes
refresh in their own 2 s fragment and the assistant in its own 1 s fragment (the fragment rule).
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from agents import additions
from dashboard import assistant_panel, export, queries
from dashboard import notebook_html as nbh
from dashboard.shared import SETTINGS, mmss, mode
from storage.db import connect_readonly, db_path

MAX_NOTES_SHOWN = 12
LAYOUTS = ["Notes only", "Notes and assistant", "Assistant wide"]
ASSISTANT_PX = 440
NOTES_ONLY_PX = 880                    # about 72 characters of 18 px Literata plus the time chips


@st.fragment(run_every="2s")
def notebook_view(video_id: str, toc: bool = False) -> None:
    """Contents and glossary (when switched on), finished topics (collapsed except the latest while live) and the one
    live notes card. Only lecture content: pipeline numbers are on the System page."""
    try:
        conn = connect_readonly(db_path())
    except sqlite3.Error:
        return
    try:
        nb = queries.notebook(conn, video_id, SETTINGS.note_update_s)
        legacy = queries.notes(conn, video_id) if nb["updates"] == 0 else None
    finally:
        conn.close()
    assistant_panel.redraw_notices()
    theme = mode()
    if toc:
        with st.container(border=True):
            st.html(nbh.wrap(nbh.toc_html(nb), theme))
    if nb["updates"] == 0 and legacy is not None and not legacy.empty:
        st.caption("Notes from a run before the notebook (M6a):")
        for _, n in legacy.head(MAX_NOTES_SHOWN).iterrows():
            st.markdown(f"**{mmss(n['media_start'])}** {n['summary']}")
    if not nb["topics"] and not nb["drafts"] and not nb["finished"]:
        st.html(nbh.wrap('<p class="pending">The first notes appear about 2 minutes after the class starts.</p>',
                         theme))
    for topic in nb["topics"]:
        latest = topic is nb["topics"][-1]
        with st.expander(nbh.topic_label(topic), expanded=nb["finished"] or latest, key=f"topic_{video_id}_{topic['n']}"):
            st.html(nbh.wrap(nbh.topic_html(topic, theme), theme))
            addition_buttons(video_id, topic.get("additions") or [])
    if not nb["finished"] and (nb["drafts"] or nb["reach"]):             # the one live card, never twice
        st.html(nbh.wrap(nbh.live_html(nb, theme), theme))
        addition_buttons(video_id, nb["live_additions"])
    if nb["beyond"]:
        with st.expander(f"Beyond the lecture: {len(nb['beyond'])} of your additions", expanded=True, key=f"beyond_{video_id}"):
            st.html(nbh.wrap(nbh.beyond_html(nb, theme), theme))
            addition_buttons(video_id, nb["beyond"])


def addition_buttons(video_id: str, items: list[dict]) -> None:
    """Under a topic, for each of the student's additions in it (NOTEBOOK_DESIGN §13.3): ✕ (removal is an event too)
    and ↻, which rebuilds it from its own question in place, with no second offer."""
    for a in items:
        name = a["figure"].get("title") or "this addition"
        running = assistant_panel.redraw_state(a["addition_id"]) == "running"
        with st.container(horizontal=True, vertical_alignment="center"):
            st.button(f"Remove “{name}” from my notes", key=f"rm_{a['addition_id']}", type="tertiary",
                      icon=":material/close:", disabled=running,
                      on_click=assistant_panel.remove_addition, args=(video_id, a["addition_id"]))
            if a.get("question"):
                st.button("Redrawing…" if running else additions.redraw_label(a), key=f"rd_{a['addition_id']}",
                          type="tertiary", icon=":material/refresh:", disabled=running,
                          help="Ask the saved question again and put the new figure in this one's place.",
                          on_click=assistant_panel.redraw_addition, args=(video_id, a))


def export_menu(video_id: str, title: str) -> None:
    """One "Export notes" menu: Markdown, Word and PDF. Each file is built when its button is clicked (a callable),
    from the notebook as it is at that moment; "Include my additions" (§13.7) adds the student's."""
    def build(fmt: str, include: bool):
        def make() -> bytes:
            conn = connect_readonly(db_path())
            try:
                nb = queries.notebook(conn, video_id, SETTINGS.note_update_s)
            finally:
                conn.close()
            return export.FORMATS[fmt][2](nb, title, include)
        return make

    with st.popover("Export notes", icon=":material/download:"):
        include = st.session_state.get(f"dl_mine_{video_id}", True)
        for fmt, (ext, mime, _) in export.FORMATS.items():
            st.download_button(fmt, build(fmt, include), file_name=f"{export.file_stem(title)}_notes.{ext}",
                               mime=mime, key=f"dl_{fmt}_{video_id}", on_click="ignore", width="stretch")
        st.checkbox("Include my additions", value=True, key=f"dl_mine_{video_id}")


def lectures() -> pd.DataFrame:
    if not db_path().exists():
        return pd.DataFrame()
    try:
        conn = connect_readonly(db_path())
        try:
            return queries.lectures(conn)
        finally:
            conn.close()
    except sqlite3.Error:
        return pd.DataFrame()


def has_notes(video_id: str) -> bool:
    try:
        conn = connect_readonly(db_path())
        try:
            return bool(conn.execute("SELECT EXISTS(SELECT 1 FROM drafts WHERE video_id = ?) OR "
                                     "EXISTS(SELECT 1 FROM topics WHERE video_id = ?)", (video_id, video_id)).fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def toolbar(titles: dict | None = None, fixed: tuple[str, str] | None = None) -> tuple[str, str, str, bool]:
    """One row above the notes: the lecture picker (Revise only), the layout, the contents and glossary switch, and
    Export. Returns video_id, title, layout, show contents."""
    if titles:
        pick, mid, right = st.columns([1.7, 3.2, 1], vertical_alignment="center")
        with pick:
            video_id = st.selectbox("Lecture", list(titles), format_func=lambda v: titles[v], key="notes_lecture",
                                    label_visibility="collapsed")
        title = titles[video_id]
    else:
        mid, right = st.columns([4, 1], vertical_alignment="center")
        video_id, title = fixed
    with mid, st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        layout = st.segmented_control("Layout", LAYOUTS, default=LAYOUTS[1], key="layout", required=True,
                                      label_visibility="collapsed")
        toc = st.toggle("Contents and glossary", key="show_toc")
    with right, st.container(horizontal=True, horizontal_alignment="right"):
        if has_notes(video_id):
            export_menu(video_id, title)
    return video_id, title, layout or LAYOUTS[1], toc


def layout_notes(video_id: str, layout: str, toc: bool) -> None:
    if layout == "Notes only":                            # a reading column, centred: no 1,300 px lines
        with st.container(horizontal=True, horizontal_alignment="center"):
            with st.container(key="notes_card", border=True, width=NOTES_ONLY_PX):
                notebook_view(video_id, toc)
    elif layout == "Assistant wide":
        notes, side = st.columns([2, 3], gap="medium")
        with notes, st.container(key="notes_card", border=True):
            notebook_view(video_id, toc)
        with side:
            assistant_panel.panel(video_id)
    else:
        with st.container(horizontal=True, gap="medium"):
            with st.container(key="notes_card", border=True, width="stretch"):
                notebook_view(video_id, toc)
            with st.container(width=ASSISTANT_PX):
                assistant_panel.panel(video_id)


def notes_and_assistant(video_id: str, title: str) -> None:
    """In class: the running lecture, no picker."""
    _, _, layout, toc = toolbar(fixed=(video_id, title))
    layout_notes(video_id, layout, toc)


def empty_state() -> None:
    st.info("No lectures yet. Start a class on the In class page; its notes appear here as they are written.",
            icon=":material/menu_book:")


def revise_page() -> None:
    """Revise: pick any lecture and read, ask about or export it."""
    if not db_path().exists():                            # app.lecture_watch says EduStream is not running yet
        return
    all_lectures = lectures()
    if all_lectures.empty:
        empty_state()
        return
    newest_first = all_lectures.sort_values("session_start", ascending=False, kind="stable")
    titles = dict(zip(newest_first["video_id"], newest_first["title"]))
    if st.session_state.get("open_lecture") in titles:   # "Open in Revise" on the In class landing
        st.session_state["notes_lecture"] = st.session_state.pop("open_lecture")
    video_id, _, layout, toc = toolbar(titles=titles)
    layout_notes(video_id, layout, toc)
