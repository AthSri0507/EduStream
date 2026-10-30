"""EduStream dashboard (PLAN M5; ARCHITECTURE §1; docs/UI_DESIGN.md): a near-real-time, read-only view of
data/edustream.db.

Pages in the top bar: In class (landing with "Join a live class", or the live notes and the assistant), Revise (any
lecture) and System (pipeline health, window stats, alerts, data). Above every page: the theme variables
(dashboard/theme.py), the status row and the live tab title (dashboard/status.py). No sidebar. Live parts refresh in
their own fragments (status, notes and recorder bar 2 s, assistant 1 s). The database is opened read-only (mode=ro); storage/db_sink.py is the
only writer. Look and copy: docs/UI_DESIGN.md and .claude/skills/edustream-ui/SKILL.md.

    .venv\\Scripts\\streamlit run dashboard\\app.py          (normally started by scripts\\start_all.ps1)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import queries, status, theme  # noqa: E402
from storage.db import connect_readonly, db_path  # noqa: E402

st.set_page_config(page_title="EduStream", page_icon=":material/edit_note:", layout="wide")
st.logo(str(ROOT / "dashboard" / "static" / "edustream_wordmark.svg"), size="large")   # tools/build_logo.py

PAGES = [st.Page("app_pages/in_class.py", title="In class", icon=":material/podium:", default=True),
         st.Page("app_pages/revise.py", title="Revise", icon=":material/menu_book:"),
         st.Page("app_pages/system.py", title="System", icon=":material/monitoring:")]


@st.fragment(run_every="2s")
def lecture_watch(known: tuple) -> None:
    """Waits for the database and reruns the page when a new lecture appears (refreshes the lecture picker)."""
    path = db_path()
    if not path.exists():
        st.info("EduStream is not running on this laptop yet. Start it with `scripts\\start_all.ps1`; this page "
                "connects by itself.", icon=":material/hourglass_empty:")
        return
    try:
        conn = connect_readonly(path)
        try:
            current = tuple(queries.lectures(conn)["video_id"]) if queries.kpis(conn)["lectures"] else ()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        st.warning(f"The notes can't be read right now ({exc}). Trying again.")
        return
    if current != known:
        st.rerun(scope="app")


def known_lectures() -> tuple:
    if not db_path().exists():
        return ()
    try:
        conn = connect_readonly(db_path())
        try:
            return tuple(queries.lectures(conn)["video_id"]) if queries.kpis(conn)["lectures"] else ()
        finally:
            conn.close()
    except sqlite3.Error:
        return ()


nav = st.navigation(PAGES, position="top")
theme.inject()
status.status_row()
lecture_watch(known_lectures())
nav.run()
