"""EduStream dashboard (PLAN M5; ARCHITECTURE §1): a near-real-time, read-only view of data/edustream.db.

Refreshes every 2 s. Tabs: live notes, window stats, alerts, pipeline health. The database is
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
from dashboard import queries  # noqa: E402
from storage.db import connect_readonly, db_path  # noqa: E402

st.set_page_config(page_title="EduStream", layout="wide")

# Categorical slots (dataviz reference palette): colour follows the lecture (partition order), never its rank.
SERIES = {"light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
          "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]}
MUTED = {"light": "#898781", "dark": "#a3a29b"}
SEVERITY = {"info": "ℹ️ info", "warn": "⚠️ warn", "crit": "⛔ crit"}
MAX_NOTES_SHOWN = 12
# Tab labels double as URL values (bind="query-params"): e.g. http://localhost:8501/?tab=Pipeline+health
TABS = ["Notebook", "Window stats", "Alerts", "Pipeline health"]
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

def notebook_view(conn: sqlite3.Connection, video_id: str) -> bool:
    """Rev 6 notebook (minimal M6a view; M6c adds the player, exports and final titles). False if empty."""
    nb = queries.notebook(conn, video_id)
    if nb["updates"] == 0:
        return False
    points, terms = nb["points"], nb["terms"]
    for _, sec in nb["sections"].iterrows():
        st.markdown(f"#### {sec['section_id']}. {sec['title']}")
        rows = points[points["section_id"] == sec["section_id"]]
        if rows.empty:
            st.caption("(no points yet)")
        for _, p in rows.iterrows():
            label = "*Example:* " if p["kind"] == "example" else ""
            extractive = " <sub>`extractive`</sub>" if p["generator"] == "extractive" else ""
            st.markdown(f"- `[{mmss(p['t'])}]` {label}{p['text']}{extractive}", unsafe_allow_html=True,
                        help=f"Said: \"{p['quote']}\"")
            if isinstance(p["background"], str) and p["background"]:
                st.caption(f"Background (not from the lecture): {p['background']}")
    if not terms.empty:
        with st.expander(f"Glossary ({len(terms)})"):
            for _, term in terms.iterrows():
                note = " *(background)*" if term["source"] == "background" else ""
                st.markdown(f"**{term['term']}**{note}: {term['definition']} `[{mmss(term['t'])}]`")
    if not nb["tail"].empty:
        with st.container(border=True):
            st.caption(f"Live tail: said after {mmss(nb['covered_s'])}, not in the notebook yet")
            st.write(" ".join(nb["tail"]["text"].tolist()[-12:]))
    return True


def notes_tab(conn: sqlite3.Connection, lectures: pd.DataFrame) -> None:
    if lectures.empty:
        st.info("No lecture yet. Start one with `.venv\\Scripts\\python -m producer.lecture_source --demo` "
                "(or replay recorded transcripts with `-m tools.replay_fixtures --demo`).")
        return
    titles = dict(zip(lectures["video_id"], lectures["title"]))
    video_id = st.selectbox("Lecture", list(titles), format_func=lambda v: titles[v], key="notes_lecture")
    lecture = lectures[lectures["video_id"] == video_id].iloc[0]
    st.caption(f"{lecture['status']} · partition {lecture['partition']} · "
               f"{lecture['chunks_stored']}/{lecture['expected_chunks']} chunks · "
               f"{lecture['windows']} windows · {lecture['updates']} notebook updates")
    if notebook_view(conn, video_id):
        return
    df = queries.notes(conn, video_id)          # notes.v1 from runs before M6a
    if df.empty:
        st.info("No notes yet: the first notebook update appears about 2 minutes into a lecture "
                "(90 s of lecture, then about 25 s until its last window closes).")
        tail = queries.notebook(conn, video_id)["tail"]
        if not tail.empty:
            st.caption("Live transcript so far")
            st.write(" ".join(tail["text"].tolist()[-12:]))
        return
    if len(df) > MAX_NOTES_SHOWN:
        st.caption(f"Newest {MAX_NOTES_SHOWN} of {len(df)} windows")
    for _, n in df.head(MAX_NOTES_SHOWN).iterrows():
        with st.container(border=True):
            badge = "LLM" if n["generator"] == "llm" else "extractive"
            revision = f" · revision {n['revision']}" if n["revision"] > 1 else ""
            st.markdown(f"**{mmss(n['media_start'])}–{mmss(n['media_end'])}** · window {n['window_index']} · "
                        f"`{badge}`{revision}")
            st.markdown(n["summary"] or "_(no sentence long enough for a note)_")
            points = [p for p in n["key_points"] if p != n["summary"]]
            if points:
                st.markdown("\n".join(f"- {p}" for p in points))
            if n["terms"]:
                st.markdown("**Terms:** " + "; ".join(f"*{t['term']}*: {t['definition']}" for t in n["terms"]))
            if n["questions"]:
                st.markdown("**Review:** " + " ".join(n["questions"]))
            with st.expander("Transcript of this window"):
                st.write(n["transcript"] or "")


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
                               "completeness_pct", "windows", "notes"]], hide_index=True, width="stretch")

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
st.caption("Live lecture transcription and notes · Kafka → Whisper → Kafka Streams → SQLite · "
           "near-real-time view, refreshes every 2 s")


@st.fragment(run_every="2s")
def live() -> None:
    path = db_path()
    if not path.exists():
        st.info(f"Waiting for the database ({path}). Start the pipeline with `scripts\\start_all.ps1`.")
        return
    try:
        conn = connect_readonly(path)
        kpi = queries.kpis(conn)
    except sqlite3.Error as exc:
        st.warning(f"Database not readable yet ({exc}); retrying.")
        return
    try:
        lectures = queries.lectures(conn)
        cols = st.columns(6)
        cols[0].metric("Lectures", kpi["lectures"], border=True)
        cols[1].metric("Chunks transcribed", kpi["chunks"], border=True)
        cols[2].metric("Windows closed", kpi["windows"], border=True)
        cols[3].metric("Notebook updates", kpi["updates"] or kpi["notes"], border=True,
                       help="One per 90 s of lecture (rev 6)")
        cols[4].metric("Alerts", kpi["alerts"], border=True, help="LOW_ASR_SCORE, SILENCE, CONSUMER_LAG")
        cols[5].metric("LATE_DROP", kpi["late_drop"], border=True,
                       help="Records dropped as late. Must stay 0 (S1: one lecture per partition).")
        if kpi["last_sink_ts"]:
            st.caption(f"Last write by the sink at {clock(kpi['last_sink_ts'])} · DLQ: {kpi['dlq']} records")
        # Bound to the URL; only the visible tab is computed on each 2 s refresh (.open is True for it).
        notes_t, stats_t, alerts_t, health_t = st.tabs(TABS, key="tab", bind="query-params")
        with notes_t:
            if notes_t.open is not False:
                notes_tab(conn, lectures)
        with stats_t:
            if stats_t.open:
                stats_tab(conn, lectures)
        with alerts_t:
            if alerts_t.open:
                alerts_tab(conn)
        with health_t:
            if health_t.open:
                health_tab(conn, lectures, kpi)
    finally:
        conn.close()


live()
