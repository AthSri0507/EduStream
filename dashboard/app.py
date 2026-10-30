"""EduStream dashboard (PLAN M5; ARCHITECTURE §1): a near-real-time, read-only view of data/edustream.db.

Tabs: Notebook (study notes + Lecture Assistant chat), Data (query the stored data),
window stats, alerts, pipeline health. Sidebar: start and stop a live class (dashboard/live_panel.py). Live parts refresh in their own fragments (2 s; assistant 1 s). The database is
opened read-only (mode=ro); storage/db_sink.py is the only writer.

    .venv\\Scripts\\streamlit run dashboard\\app.py          (normally started by scripts\\start_all.ps1)
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import load  # noqa: E402
from agents import additions  # noqa: E402
from dashboard import assistant_panel, live_panel, queries, sql_box  # noqa: E402
from dashboard import export  # noqa: E402
from dashboard import notebook_html as nbh  # noqa: E402
from storage.db import connect_readonly, db_path  # noqa: E402

st.set_page_config(page_title="EduStream", layout="wide")

# Categorical slots (dataviz reference palette): colour follows the lecture (partition order), never its rank.
SERIES = {"light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
          "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]}
MUTED = {"light": "#898781", "dark": "#a3a29b"}
SEVERITY = {"info": "ℹ️ info", "warn": "⚠️ warn", "crit": "⛔ crit"}
MAX_NOTES_SHOWN = 12
# Tab labels double as URL values (bind="query-params"): e.g. http://localhost:8501/?tab=Pipeline+health
TABS = ["Notebook", "Data", "Window stats", "Alerts", "Pipeline health"]
SETTINGS = load()


def mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # noqa: BLE001 - older/unknown theme info
        return "light"


def mmss(seconds) -> str:
    if seconds is None or pd.isna(seconds):
        return "--:--"
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def clock(ms) -> str:
    return "" if ms is None or pd.isna(ms) else datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


def lecture_colors(lectures: pd.DataFrame) -> tuple[list[str], list[str]]:
    slots = SERIES[mode()]
    titles = list(lectures["title"])
    return titles, [slots[i % len(slots)] for i in range(len(titles))]


# --------------------------------------------------
# Tabs
# --------------------------------------------------

@st.fragment(run_every="2s")
def notebook_view(video_id: str, title: str) -> None:
    """The notebook (NOTEBOOK_DESIGN §6, §11.6): contents rail, finished topics (collapsed except the latest while
    live), the live box with the drafts since the last consolidation, and the downloads (M6c). Only lecture content:
    pipeline numbers are on Pipeline health (decision 5)."""
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
    st.html(nbh.wrap(nbh.head_html(nb), theme))
    rail, main = st.columns([1, 3.3], gap="medium")
    with rail:
        st.html(nbh.wrap(nbh.rail_html(nb), theme))
    with main:
        if nb["topics"] or nb["drafts"]:
            download_row(video_id, title)
        if nb["updates"] == 0 and legacy is not None and not legacy.empty:
            st.caption("Notes from a run before the notebook (M6a):")
            for _, n in legacy.head(MAX_NOTES_SHOWN).iterrows():
                st.markdown(f"**{mmss(n['media_start'])}** {n['summary']}")
        for i, topic in enumerate(nb["topics"]):
            latest = i == len(nb["topics"]) - 1
            with st.expander(nbh.topic_label(topic), expanded=nb["finished"] or latest):
                st.html(nbh.wrap(nbh.topic_html(topic, theme), theme))
                addition_buttons(video_id, topic.get("additions") or [])
        if not nb["finished"]:
            st.html(nbh.wrap(nbh.live_html(nb, theme), theme))
            addition_buttons(video_id, nb["live_additions"])
        if nb["beyond"]:
            with st.expander(f"Beyond the lecture · {len(nb['beyond'])} of your additions", expanded=True):
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


def download_row(video_id: str, title: str) -> None:
    """Markdown, Word and PDF of the notes. Each file is built when its button is clicked (a callable), from the
    notebook as it is at that moment, not on every 2 s refresh; "Include my additions" (§13.7) adds the student's."""
    def build(fmt: str, include: bool):
        def make() -> bytes:
            conn = connect_readonly(db_path())
            try:
                nb = queries.notebook(conn, video_id, SETTINGS.note_update_s)
            finally:
                conn.close()
            return export.FORMATS[fmt][2](nb, title, include)
        return make

    with st.container(horizontal=True, vertical_alignment="center"):
        include = st.session_state.get(f"dl_mine_{video_id}", True)
        for fmt, (ext, mime, _) in export.FORMATS.items():
            st.download_button(fmt, build(fmt, include), file_name=f"{export.file_stem(title)}_notes.{ext}",
                               mime=mime, key=f"dl_{fmt}_{video_id}", on_click="ignore", icon=":material/download:")
        st.checkbox("Include my additions", value=True, key=f"dl_mine_{video_id}")


def data_tab() -> None:
    """Storage you can query (A19): ready-made queries and a locked, read-only SQL box."""
    st.markdown("**Query the stored data** (SQLite, read-only). Pick a ready-made query or write your own SELECT.")
    name = st.selectbox("Ready-made query", list(sql_box.READY_MADE), key="data_query")
    sql = st.text_area("SQL", sql_box.READY_MADE[name], key=f"data_sql_{name}", height=110)
    if st.button("Run query", type="primary", key="data_run"):
        try:
            conn = connect_readonly(db_path())
            try:
                df, truncated = sql_box.run_query(conn, sql)
            finally:
                conn.close()
        except sql_box.QueryRefused as exc:
            st.error(f"Query refused: {exc}")
            return
        except sqlite3.Error as exc:
            st.error(f"Database not readable: {exc}")
            return
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption(f"{len(df)} rows" + (f" (first {sql_box.MAX_ROWS} only)" if truncated else ""))
        st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), file_name="edustream_query.csv",
                           mime="text/csv", key="data_csv")
    st.caption(f"Only SELECT on the EduStream tables is allowed; queries stop after {sql_box.TIME_LIMIT_S:g} s "
               f"and return at most {sql_box.MAX_ROWS} rows. Tables: " + ", ".join(sorted(
                   t for t in sql_box.ALLOWED if not t.startswith("sqlite"))) + ".")


def stats_tab(conn: sqlite3.Connection, lectures: pd.DataFrame) -> None:
    ws = queries.window_stats(conn)
    if ws.empty:
        st.info("No closed windows yet.")
        return
    ws["minute"] = ws["media_start"] / 60
    domain, colors = lecture_colors(lectures)
    color = alt.Color("title:N", title=None, scale=alt.Scale(domain=domain, range=colors),
                      legend=alt.Legend(orient="bottom", direction="vertical", labelLimit=400))
    tooltip = [alt.Tooltip("title:N", title="Lecture"), alt.Tooltip("minute:Q", title="Minute", format=".1f"),
               alt.Tooltip("words_per_min:Q", title="Words/min"), alt.Tooltip("score_avg:Q", title="asr_score avg",
                                                                              format=".3f"),
               alt.Tooltip("chunk_count:Q", title="Chunks")]
    base = alt.Chart(ws).encode(x=alt.X("minute:Q", title="Lecture time (minutes)"), color=color, tooltip=tooltip)
    line = {"strokeWidth": 2, "point": alt.OverlayMarkDef(size=40, filled=True)}

    left, right = st.columns(2)
    with left:
        st.markdown("**Speaking rate per 30 s window**")
        silence = alt.Chart(pd.DataFrame({"y": [40]})).mark_rule(color=MUTED[mode()], strokeWidth=1).encode(y="y:Q")
        chart = base.mark_line(**line).encode(y=alt.Y("words_per_min:Q", title="Words per minute")) + silence
        st.altair_chart(chart.properties(height=240), width="stretch", height=400)
        st.caption("Grey rule: 40 words/min, the SILENCE alert threshold.")
    with right:
        st.markdown("**Transcription confidence (asr_score) per window**")
        scored = ws[ws["score_avg"].notna()]
        if scored.empty:
            st.info("No asr_score values (e.g. a caption replay has none).")
        else:
            threshold = alt.Chart(pd.DataFrame({"y": [SETTINGS.t_score]})).mark_rule(
                color=MUTED[mode()], strokeWidth=1).encode(y="y:Q")
            chart = base.transform_filter("datum.score_avg != null").mark_line(**line).encode(
                y=alt.Y("score_avg:Q", title="Average asr_score", scale=alt.Scale(domain=[0.4, 1.0]))) + threshold
            st.altair_chart(chart.properties(height=240), width="stretch", height=400)
            st.caption(f"Grey rule: T_SCORE = {SETTINGS.t_score} (LOW_ASR_SCORE, informational only: "
                       "M2 found asr_score a weak signal).")
    with st.expander("Table view"):
        table = ws[["title", "media_start", "media_end", "chunk_count", "word_count", "words_per_min",
                    "score_avg", "score_min", "score_max", "compression_ratio_max", "top_terms"]].copy()
        table["media_start"] = table["media_start"].map(mmss)
        table["media_end"] = table["media_end"].map(mmss)
        st.dataframe(table, hide_index=True, width="stretch")


def alerts_tab(conn: sqlite3.Connection) -> None:
    df = queries.alerts(conn)
    if df.empty:
        st.info("No alerts.")
        return
    window = [mmss((ws - s) / 1000) if pd.notna(ws) and pd.notna(s) else "" for ws, s in
              zip(df["window_start"], df["session_start"])]
    table = pd.DataFrame({"time": df["created_ts"].map(clock), "severity": df["severity"].map(SEVERITY),
                          "type": df["type"], "lecture": df["lecture"].fillna("(system)"), "window at": window,
                          "value": df["value"].round(3), "threshold": df["threshold"], "reason": df["reason"]})
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption("LOW_ASR_SCORE and SILENCE are informational. CONSUMER_LAG = a stage is more than "
               f"{SETTINGS.lag_alert_s:g} s of audio behind. LATE_DROP must never appear (S1 tripwire).")


def health_tab(conn: sqlite3.Connection, lectures: pd.DataFrame, kpi: dict) -> None:
    kpi_strip(kpi)
    st.markdown("**Partitions: lecture → transcription worker**")
    pmap = queries.partition_map(conn)
    if pmap.empty:
        st.info("No lectures yet.")
    else:
        st.dataframe(pmap.rename(columns={"owner_now": "owned now by", "latest_chunk_by": "latest chunk by",
                                          "workers_used": "workers used"}), hide_index=True, width="stretch")

    st.markdown("**Consumer lag (seconds of audio behind)**")
    lag = queries.lag(conn)
    if lag.empty:
        st.info("No lag samples yet (the sink samples every 5 s).")
    else:
        lag["over threshold"] = lag["lag_seconds"] > SETTINGS.lag_alert_s
        lag["sampled"] = lag["sampled_ts"].map(clock)
        st.dataframe(lag[["group_id", "partition", "lecture", "owner", "lag", "lag_seconds", "over threshold",
                          "sampled"]], hide_index=True, width="stretch")

    st.markdown("**Completeness**")
    if not lectures.empty:
        st.dataframe(lectures[["title", "partition", "status", "chunks_stored", "expected_chunks",
                               "completeness_pct", "windows", "updates", "passes"]], hide_index=True, width="stretch")

    st.markdown(f"**Dead-letter queue** ({kpi['dlq']} records)")
    dlq = queries.dlq(conn)
    if dlq.empty:
        st.caption("Empty.")
    else:
        dlq["failed_ts"] = dlq["failed_ts"].map(clock)
        st.dataframe(dlq, hide_index=True, width="stretch")


# --------------------------------------------------
# Page
# --------------------------------------------------

st.title("EduStream")
st.caption("Live lecture notes and a lecture assistant · Kafka → Whisper → Kafka Streams → SQLite · "
           "near-real-time view")


@st.fragment(run_every="2s")
def lecture_watch(known: tuple) -> None:
    """Waits for the database and reruns the page when a new lecture appears (refreshes the lecture picker)."""
    path = db_path()
    if not path.exists():
        st.info(f"Waiting for the database ({path}). Start the pipeline with `scripts\\start_all.ps1`.")
        return
    try:
        conn = connect_readonly(path)
        try:
            current = tuple(queries.lectures(conn)["video_id"]) if queries.kpis(conn)["lectures"] else ()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        st.warning(f"Database not readable yet ({exc}); retrying.")
        return
    if current != known:
        st.rerun(scope="app")


def kpi_strip(kpi: dict) -> None:
    cols = st.columns(7)
    cols[0].metric("Lectures", kpi["lectures"], border=True)
    cols[1].metric("Chunks transcribed", kpi["chunks"], border=True)
    cols[2].metric("Windows closed", kpi["windows"], border=True)
    cols[3].metric("Notebook updates", kpi["updates"] or kpi["notes"], border=True,
                   help="Live notes: one per 90 s of lecture")
    cols[4].metric("Consolidations", kpi["passes"], border=True,
                   help="Live notes organised into topics: one per ~6 minutes, and one at the lecture's end")
    cols[5].metric("Alerts", kpi["alerts"], border=True, help="LOW_ASR_SCORE, SILENCE, CONSUMER_LAG")
    cols[6].metric("LATE_DROP", kpi["late_drop"], border=True,
                   help="Records dropped as late. Must stay 0 (S1: one lecture per partition).")
    if kpi["last_sink_ts"]:
        st.caption(f"Last write by the sink at {clock(kpi['last_sink_ts'])} · DLQ: {kpi['dlq']} records")


@st.fragment(run_every="2s")
def refreshing(tab: str) -> None:
    try:
        conn = connect_readonly(db_path())
    except sqlite3.Error:
        return
    try:
        lectures = queries.lectures(conn)
        if tab == "Window stats":
            stats_tab(conn, lectures)
        elif tab == "Alerts":
            alerts_tab(conn)
        else:
            health_tab(conn, lectures, queries.kpis(conn))
    finally:
        conn.close()


def page() -> None:
    with st.sidebar:
        live_panel.panel()
    lectures = pd.DataFrame()
    if db_path().exists():
        try:
            conn = connect_readonly(db_path())
            try:
                lectures = queries.lectures(conn)
            finally:
                conn.close()
        except sqlite3.Error:
            lectures = pd.DataFrame()
    lecture_watch(tuple(lectures["video_id"]) if not lectures.empty else ())
    if lectures.empty:
        st.info("No lecture yet. Start a live class in the sidebar, or play one with "
                "`.venv\\Scripts\\python -m producer.lecture_source --demo`.")
        return
    notebook_t, data_t, stats_t, alerts_t, health_t = st.tabs(TABS, key="tab", bind="query-params", on_change="rerun")
    with notebook_t:
        if notebook_t.open is not False:
            live_first = lectures.sort_values("status", key=lambda s: s != "live", kind="stable")
            titles = dict(zip(live_first["video_id"], live_first["title"]))
            if st.session_state.get("follow_live") in titles:   # a live class started here: show its notes
                st.session_state["notes_lecture"] = st.session_state.pop("follow_live")
            video_id = st.selectbox("Lecture", list(titles), format_func=lambda v: titles[v], key="notes_lecture")
            left, right = st.columns([3.4, 2])
            with left:
                notebook_view(video_id, titles[video_id])
            with right:
                assistant_panel.panel(video_id)
    with data_t:
        if data_t.open:
            data_tab()
    for tab, name in ((stats_t, "Window stats"), (alerts_t, "Alerts"), (health_t, "Pipeline health")):
        with tab:
            if tab.open:
                refreshing(name)


page()
